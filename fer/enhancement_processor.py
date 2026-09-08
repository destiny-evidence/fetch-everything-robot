"""Generation functions for single and batch fulltext enhancements."""

import asyncio
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
from pydantic import HttpUrl, ValidationError

from fer.blob_storage import BlobUploadError, FetchEverythingBlobStorageClient
from fer.config import Settings
from fer.data_models.generic import APIConfig
from fer.fetch_fulltext import (
    FullTextBatchFetcher,
    FullTextResult,
    ZeroFullTextsGeneratedError,
)
from fer.fetching import BasePublisherFetcher
from fer.fetching.core import DOIStudy, DOIStudyCollection


class FileURLGenerationError(Exception):
    """Custom exception for errors during file URL generation."""


class MissingDOIError(Exception):
    """Custom exception for missing DOI in reference."""


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
    def get_study_or_raise_error(reference: Reference) -> DOIStudy:
        """
        Convert a Reference object to a DOIStudy, raising an error if DOI is missing.

        Args:
            reference (Reference): A Reference object.

        Returns:
            DOIStudy: The corresponding DOIStudy object.

        Raises:
            MissingDOIError: If the Reference does not have a DOI identifier.

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
            error_message = (
                f"Reference {reference.id} is missing a DOI identifier.\n"
                f"full reference: {reference}"
            )
            raise MissingDOIError(error_message)

        return DOIStudy(
            doi=doi_id,
            uid=reference.id,
        )

    @staticmethod
    def get_study_collection_from_references(
        references: list[Reference],
    ) -> DOIStudyCollection:
        """
        Convert a list of Reference objects to a DOIStudyCollection.

        Args:
            references (list[Reference]): A list of Reference objects.

        Returns:
            DOIStudyCollection: The corresponding DOIStudyCollection.

        """
        studies = [
            FullTextEnhancementProcessor.get_study_or_raise_error(reference)
            for reference in references
        ]
        return DOIStudyCollection(studies=studies)

    async def generate_fulltext(
        self,
        references: list[Reference],
        output_directory: Path,
    ) -> list[FullTextResult]:
        """
        Generate a list of FullTextResult objects.

        Args:
            references (list[Reference]): A list of Reference objects.

        Returns:
            list[FullTextResult]: A list of FullTextResult objects.

        """
        try:
            study_collection = self.get_study_collection_from_references(references)
            debug_message = (
                f"DOIs extracted: "
                f"{[study.doi.identifier for study in study_collection.studies]}"
            )
            logger.debug(debug_message)
        except MissingDOIError as missing_doi_error:
            error_message = (
                "One or more references are missing DOI identifiers: "
                f"{missing_doi_error}"
            )
            raise BatchEnhancementGenerationError(error_message) from missing_doi_error
        try:
            return await self.fulltext_fetcher.get_many_fulltext_pdfs_cycling_apis(
                input_study_collection=study_collection,
                output_directory=output_directory,
            )
        except ZeroFullTextsGeneratedError as zero_full_texts_error:
            error_message = "No full texts were retrieved from any API."
            raise BatchEnhancementGenerationError(
                error_message
            ) from zero_full_texts_error

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
                generated_fulltexts: list[
                    FullTextResult
                ] = await self.generate_fulltext(
                    references,
                    output_directory=Path(temp_directory),
                )

                found_results: list[FullTextResult] = [
                    result
                    for result in generated_fulltexts
                    if result.fulltext_path is not None
                ]
                not_found_results: list[FullTextResult] = [
                    result
                    for result in generated_fulltexts
                    if result.fulltext_path is None
                ]
                logger.info(
                    f"Successfully fetched {len(found_results)} full text PDFs."
                )

                if len(not_found_results) > 0:
                    warning_message = (
                        f"Failed to fetch {len(not_found_results)} full text PDFs. "
                        f"DOIs: {[result.doi for result in not_found_results]}"
                    )
                    logger.warning(warning_message)

                enhancements_map = {
                    result.uid: {
                        "doi": result.doi,
                        "openalex_id": result.openalex_id,
                        "fulltext_path": Path(result.fulltext_path)
                        if result.fulltext_path is not None
                        else None,
                        "source": result.source,
                    }
                    for result in generated_fulltexts
                }

                fulltext_enhancements = (
                    await self.generate_fulltext_enhancement_batch_request(
                        references=references,
                        full_text_results_map=enhancements_map,
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

        successful_enhancements = 0
        for reference in references:
            enhancement = full_text_results_map.get(str(reference.id))
            if not enhancement:
                error_message = (
                    f"Enhancement generation error for {reference.id}."
                    " Reference ID is missing in the enhancements map."
                )
                logger.error(error_message)
                raise BatchEnhancementGenerationError(error_message)
            fulltext_path: Path | None = enhancement.get("fulltext_path", None)
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
                fulltext_url = await self.generate_file_url(fulltext_path)
            except FileURLGenerationError as file_url_error:
                error_message = (
                    f"Failed to generate file URL for {reference.id} "
                    f"from source {enhancement_source_short}: {file_url_error}"
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
        self,
        file_path: Path,
    ) -> HttpUrl:
        """
        Generate a file URL for the given file path.

        Uploads the file to blob storage and returns the SAS URL for the uploaded file.

        Args:
            file_path (Path): The path to the file containing a full text.

        Returns:
            HttpUrl: The generated file URL.

        Raises:
            FileURLGenerationError:
                If errors occur during file upload or SAS URL generation.

        """
        storage_client = FetchEverythingBlobStorageClient(self.settings)
        try:
            with file_path.open("rb") as full_text_file:
                blob_name = await asyncio.to_thread(
                    storage_client.blob_upload,
                    data=full_text_file,
                    filename=file_path.name,
                )
        except BlobUploadError as upload_error:
            error_message = (
                f"Failed to upload file {file_path} to blob storage: {upload_error}"
            )
            logger.error(error_message)
            raise FileURLGenerationError(error_message) from upload_error
        try:
            blob_sas_pair = storage_client.get_blob_sas_pair(blob_name)
        except (
            Exception
        ) as sas_error:  # holding pattern until we define a custom exception
            error_message = (
                f"Failed to generate SAS URL for blob {blob_name}: {sas_error}"
            )
            logger.error(error_message)
            raise FileURLGenerationError(error_message) from sas_error
        if not hasattr(blob_sas_pair, "sas_url") or not blob_sas_pair.sas_url:
            error_message = f"SAS URL is missing for blob {blob_name}."
            logger.error(error_message)
            raise FileURLGenerationError(error_message)
        return blob_sas_pair.sas_url

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
