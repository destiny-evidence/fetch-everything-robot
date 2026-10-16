"""Generation functions for single and batch fulltext enhancements."""

import tempfile
import uuid
from pathlib import Path

import httpx2
from destiny_sdk.enhancements import (
    Enhancement,
    FullTextEnhancement,
)
from destiny_sdk.identifiers import DOIIdentifier
from destiny_sdk.references import Reference
from destiny_sdk.robots import (
    LinkedRobotError,
    RobotEnhancementBatch,
)
from destiny_sdk.visibility import Visibility
from loguru import logger
from pydantic import BaseModel, HttpUrl, ValidationError

from fer.config import Settings
from fer.data_models.generic import APIConfig
from fer.fetch_fulltext import (
    FullTextBatchFetcher,
    FullTextResult,
)
from fer.fetching import BasePublisherFetcher
from fer.fetching.core import DOIStudy, DOIStudyCollection


class FullTextRetrievalResultSet(BaseModel):
    """Full-text results and reference-scoped retrieval errors."""

    full_texts_retrieved: list[FullTextResult] | None
    linked_robot_errors: list[LinkedRobotError] | None = None


class ConvertedReferenceOutput(BaseModel):
    """Studies converted from references and errors for references without DOIs."""

    study_collection: DOIStudyCollection
    linked_robot_errors: list[LinkedRobotError]


class BatchEnhancementGenerationError(Exception):
    """Custom exception for errors during batch enhancement generation."""


class FullTextEnhancementProcessor:
    """Handles the processing of full text enhancement requests."""

    def __init__(
        self,
        settings: Settings,
        robot_version: str,
        source_name: str,
        global_api_config: dict[str, APIConfig],
        available_api_configs: list[APIConfig],
        publisher_dict: dict[str, BasePublisherFetcher],
    ) -> None:
        """
        Initialise the processor with configuration.

        Args:
            robot_version (str): The version of the robot.
            source_name (str): The name of the `source` in the destiny repository.
                In practical terms, this is the app name _of this app_.
            global_api_config (dict[str, APIConfig]): Global API configuration.
            available_api_configs (list[APIConfig]): List of API configurations.
            publisher_dict (dict[str, BasePublisherFetcher]): Dictionary of
                publisher fetchers.

        """
        self.settings = settings
        self.robot_version = robot_version
        self.source_name = source_name

        self.fulltext_fetcher = FullTextBatchFetcher(
            self.settings, global_api_config, publisher_dict
        )
        self.available_api_configs = available_api_configs

    @staticmethod
    def convert_reference_to_study(
        reference: Reference,
    ) -> DOIStudy | LinkedRobotError:
        """
        Convert a reference to a study or a linked error if its DOI is missing.

        Args:
            reference (Reference): A Reference object.

        Returns:
            DOIStudy or LinkedRobotError:
                The converted study or a reference-scoped error.

        """
        doi_id = next(
            (
                id_object
                for id_object in reference.identifiers
                if isinstance(id_object, DOIIdentifier)
            ),
            None,
        )

        if doi_id is None:
            error_message = f"Reference {reference.id} is missing a DOI identifier."
            return LinkedRobotError(
                message=error_message,
                reference_id=reference.id,
            )

        return DOIStudy(
            doi=doi_id,
            uid=reference.id,
        )

    @staticmethod
    def get_study_collection_from_references(
        references: list[Reference],
    ) -> ConvertedReferenceOutput:
        """
        Convert a list of Reference objects to a DOIStudyCollection.

        Args:
            references (list[Reference]): A list of Reference objects.

        Returns:
            ConvertedReferenceOutput: The corresponding ConvertedReferenceOutput object.

        """
        studies_and_linked_errors = [
            FullTextEnhancementProcessor.convert_reference_to_study(reference)
            for reference in references
        ]
        found_studies = [
            item for item in studies_and_linked_errors if isinstance(item, DOIStudy)
        ]
        linked_robot_errors = [
            item
            for item in studies_and_linked_errors
            if isinstance(item, LinkedRobotError)
        ]
        study_collection = DOIStudyCollection(studies=found_studies)
        return ConvertedReferenceOutput(
            study_collection=study_collection,
            linked_robot_errors=linked_robot_errors,
        )

    async def generate_fulltext(
        self,
        references: list[Reference],
        output_directory: Path,
    ) -> FullTextRetrievalResultSet:
        """
        Generate a list of FullTextResult objects.

        Args:
            references (list[Reference]): A list of Reference objects.
            output_directory (Path): The directory to save the generated full texts.

        Returns:
            FullTextRetrievalResultSet:
                The result of the full text retrieval: full texts
                and any linked robot errors.

        """
        reference_conversion_output = self.get_study_collection_from_references(
            references
        )
        study_collection = reference_conversion_output.study_collection
        linked_robot_errors = list(reference_conversion_output.linked_robot_errors)

        studies_retrieved = len(study_collection.studies)
        retrieval_rate = studies_retrieved / len(references) if references else 0
        debug_message = (
            f"DOIs extracted: "
            f"{[study.doi.identifier for study in study_collection.studies]}"
        )
        info_message = (
            f"{len(study_collection.studies)} DOIs extracted from "
            f"{len(references)} references ({retrieval_rate:.2%})"
        )
        logger.debug(debug_message)
        logger.info(info_message)

        retrieved_fulltext_results = (
            await self.fulltext_fetcher.get_many_fulltext_pdfs_cycling_apis(
                input_study_collection=study_collection,
                output_directory=output_directory,
            )
        )
        linked_robot_errors.extend(
            [
                LinkedRobotError(
                    message=f"Full text not found: DOI {result.doi} UID: {result.uid}",
                    reference_id=result.uid,
                )
                for result in retrieved_fulltext_results
                if result.fulltext_path is None
            ]
        )
        retrieved_fulltexts = [
            result
            for result in retrieved_fulltext_results
            if result.fulltext_path is not None
        ]

        return FullTextRetrievalResultSet(
            full_texts_retrieved=retrieved_fulltexts,
            linked_robot_errors=linked_robot_errors,
        )

    @staticmethod
    def construct_enhancement_map(
        references: list[Reference],
        retrieval_results: FullTextRetrievalResultSet,
    ) -> dict[str, dict[str, str | None]]:
        """Build a complete enhancement-data map, keyed by reference ID."""
        enhancements_map = {}
        retrieved_full_texts = retrieval_results.full_texts_retrieved or []
        for reference in references:
            doi = next(
                (
                    identifier.identifier
                    for identifier in reference.identifiers
                    if isinstance(identifier, DOIIdentifier)
                ),
                None,
            )
            enhancements_map[str(reference.id)] = {
                "doi": doi,
                "openalex_id": None,
                "fulltext_path": None,
                "source": None,
            }

        enhancements_map.update(
            {
                result.uid: {
                    "doi": result.doi,
                    "openalex_id": result.openalex_id,
                    "fulltext_path": result.fulltext_path,
                    "source": result.source,
                }
                for result in retrieved_full_texts
                if result is not None
            }
        )
        return enhancements_map

    async def create_fulltext_enhancement(
        self,
        references: list[Reference],
    ) -> list[Enhancement]:
        """
        Create full text enhancements with efficient memory usage.

        This operates on a batch of references as a default,
        but that could be a batch of one.

        Args:
            references (list[Reference]): A list of reference objects.

        Returns:
            list[Enhancement]: The generated batch of enhancements.

        """
        try:
            with tempfile.TemporaryDirectory() as temp_directory:
                generated_fulltexts: FullTextRetrievalResultSet = (
                    await self.generate_fulltext(
                        references,
                        output_directory=Path(temp_directory),
                    )
                )

                found_results = generated_fulltexts.full_texts_retrieved or []
                not_found_results = generated_fulltexts.linked_robot_errors or []

                logger.info(
                    f"Successfully fetched {len(found_results)} full text PDFs."
                )

                if not_found_results:
                    logger.warning(
                        "Failed to fetch full texts for references: {}",
                        [str(error.reference_id) for error in not_found_results],
                    )

                enhancements_map = self.construct_enhancement_map(
                    references, generated_fulltexts
                )

                fulltext_enhancements = (
                    await self.generate_fulltext_enhancement_batch_request(
                        references=references,
                        full_text_results_map=enhancements_map,
                        linked_robot_errors=not_found_results,
                        available_api_configs=self.available_api_configs,
                        app_title=self.source_name,
                    )
                )

        except BatchEnhancementGenerationError as batch_error:
            error_message = (
                "Error generating full texts for enhancement creation: "
                f"{batch_error}"
            )
            raise BatchEnhancementGenerationError(error_message) from batch_error
        return fulltext_enhancements

    async def generate_fulltext_enhancement_batch_request(
        self,
        references: list[Reference],
        full_text_results_map: dict[str, dict],
        available_api_configs: list[APIConfig],
        app_title: str,
        linked_robot_errors: list[LinkedRobotError] | None = None,
    ) -> list[Enhancement | LinkedRobotError]:
        """
        Generate a batch of full text enhancements.

        Full text enhancements are in the form of PDFs, stored
        temporarily on disk, to be later uploaded to blob storage.

        The enhancement itself must point to the SAS URL of the uploaded
        PDF.

        Full text enhancements are linked to the reference via the reference ID.

        Args:
            references (list[Reference]): A list of DESTINY `Reference` objects.
            full_text_results_map (dict[str, dict]):
                A map of generated full text results.
            linked_robot_errors (list[LinkedRobotError]):
                A list of linked robot errors.
            available_api_configs (list[APIConfig]):
                A list of available API configurations.
            app_title (str): The title of the application.

        Returns:
            list[Enhancement | LinkedRobotError]:
                A list of generated enhancements or linked robot errors.

        Raises:
            BatchEnhancementGenerationError:
                If there is an error during enhancement generation.

        """
        enhancements_out = []
        version_number = self.robot_version
        linked_errors_by_reference = {
            str(error.reference_id): error for error in linked_robot_errors or []
        }

        successful_enhancements = 0
        for reference in references:
            linked_error = linked_errors_by_reference.get(str(reference.id))
            if linked_error is not None:
                enhancements_out.append(linked_error)
                continue

            enhancement = full_text_results_map.get(str(reference.id))
            if not enhancement:
                error_message = (
                    f"Enhancement generation error for {reference.id}."
                    " Reference ID is missing in the enhancements map."
                )
                logger.error(error_message)
                raise BatchEnhancementGenerationError(error_message)
            fulltext_path = enhancement.get("fulltext_path", None)
            if not fulltext_path:
                sources = {
                    config.name.value.split("_")[0].upper()
                    for config in available_api_configs
                }
                error_message = (
                    f"Full text enhancement generation error for {reference.id} "
                    f"from source {sources}."
                )
                logger.warning(error_message)
                linked_robot_error = LinkedRobotError(
                    message=error_message,
                    reference_id=reference.id,
                )
                enhancements_out.append(linked_robot_error)
                continue
            enhancement_source = enhancement.get("source", app_title)
            if not enhancement_source:
                enhancement_source_short = "UNKNOWN"
            if enhancement_source:
                enhancement_source_short = enhancement_source.split("_")[0].upper()

            visibility_level = Visibility.HIDDEN

            try:
                fulltext_url = await self.generate_file_url(
                    fulltext_path, self.settings
                )
            except Exception as error:  # noqa: BLE001 # holding pattern until we define a custom exception
                error_message = (
                    f"Failed to generate file URL for {reference.id} "
                    f"from source {enhancement_source_short}: {error}"
                )
                logger.warning(error_message)
                linked_robot_error = LinkedRobotError(
                    message=error_message,
                    reference_id=reference.id,
                )
                enhancements_out.append(linked_robot_error)
                continue

            try:
                full_text_enhancement_content = FullTextEnhancement(
                    file_url=fulltext_url,
                    source=enhancement_source_short,
                    visibility=visibility_level,
                )
                enhancements_out.append(
                    Enhancement(
                        reference_id=reference.id,
                        source=app_title,
                        visibility=visibility_level,
                        robot_version=version_number,
                        content_version=f"{uuid.uuid4()}",
                        content=full_text_enhancement_content,
                    )
                )
                successful_enhancements += 1
            except ValidationError as validation_error:
                error_message = (
                    f"Validation error for enhancement of {reference.id} "
                    f"from source {enhancement_source_short}: {validation_error}"
                )
                logger.error(error_message)
                linked_robot_error = LinkedRobotError(
                    message=error_message,
                    reference_id=reference.id,
                )
                enhancements_out.append(linked_robot_error)
                continue

        progress_message = (
            f"Successfully generated enhancements for "
            f"{successful_enhancements}/{len(references)} references."
        )
        logger.info(progress_message)
        return enhancements_out

    async def generate_file_url(
        self, file_path: str, settings: Settings
    ) -> HttpUrl | None:
        """
        Generate a file URL for the given file path.

        Uploads the file to blob storage and returns the SAS URL for the uploaded file.

        Args:
            file_path (str): The path to the file.
            settings (Settings): The application settings.

        Returns:
            HttpUrl | None: The generated file URL or None if the upload fails.

        """
        not_implemented_message = (
            "File URL generation is not implemented. "
            "This method should handle uploading the file to blob storage "
            "and returning the SAS URL for the uploaded file."
        )
        raise NotImplementedError(not_implemented_message)

    async def download_references(self, reference_storage_url: str) -> list[Reference]:
        """
        Download references from a given URL.

        Args:
            reference_storage_url (str): The URL to download references from.

        Returns:
            list[Reference]: A list of Reference objects.

        """
        references = []
        async with (
            httpx2.AsyncClient() as client,
            client.stream("GET", reference_storage_url) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                reference = Reference.model_validate_json(line)
                references.append(reference)
        return references

    async def upload_enhancements(
        self,
        enhancements: list[Enhancement],
        result_storage_url: str,
    ) -> None:
        """
        Upload enhancements to a given URL.

        Args:
            enhancements (list[Enhancement]): A list of Enhancement objects to upload.
            result_storage_url (str): The URL to upload enhancements to.

        """
        file_content = b""
        for enhancement in enhancements:
            file_content += (enhancement.to_jsonl() + "\n").encode("utf-8")

        async with httpx2.AsyncClient() as client:
            response = await client.put(
                result_storage_url,
                content=file_content,
                headers={
                    "Content-Type": "application/jsonl",
                    "x-ms-blob-type": "BlockBlob",
                    "Content-Length": str(len(file_content)),
                },
            )
            response.raise_for_status()

    async def process_batch(self, batch: RobotEnhancementBatch) -> list[Enhancement]:
        """
        Process a batch by downloading references and creating enhancements.

        Args:
            batch (RobotEnhancementBatch): The batch of `Reference`s to enhance.

        Returns:
            list[Enhancement]: The list of generated enhancements.

        """
        logger.info("Processing robot enhancement batch {}", batch.id)
        references = await self.download_references(str(batch.reference_storage_url))
        logger.debug(f"References: {references}")
        try:
            generated_enhancements = await self.create_fulltext_enhancement(
                references=references,
            )
            await self.upload_enhancements(
                enhancements=generated_enhancements,
                result_storage_url=str(batch.result_storage_url),
            )
        except BatchEnhancementGenerationError as full_batch_failure:
            error_message = (
                "Full batch failure during enhancement generation for"
                f" batch {batch.id}:"
                f" {full_batch_failure}"
            )
            logger.error(
                error_message,
                batch.id,
                full_batch_failure,
            )
            raise
        return generated_enhancements
