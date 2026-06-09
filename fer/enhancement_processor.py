"""Generation functions for single and batch fulltext enhancements."""

import httpx
from destiny_sdk.enhancements import (
    Enhancement,
)
from destiny_sdk.identifiers import DOIIdentifier
from destiny_sdk.references import Reference
from destiny_sdk.robots import (
    RobotEnhancementBatch,
)
from loguru import logger

from fer.config import Settings
from fer.data_models.generic import APIConfig
from fer.fetch_fulltext import (
    FullTextBatchFetcher,
    FullTextResult,
    ZeroFullTextsGeneratedError,
)
from fer.fetching import BasePublisherFetcher
from fer.fetching.core import DOIStudy, DOIStudyCollection


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
            error_message = f"Reference {reference.id} is missing a DOI identifier."
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
        except MissingDOIError as missing_doi_error:
            error_message = (
                "One or more references are missing DOI identifiers: "
                f"{missing_doi_error}"
            )
            raise BatchEnhancementGenerationError(error_message) from missing_doi_error
        try:
            return await self.fulltext_fetcher.get_many_fulltext_pdfs_cycling_apis(
                input_study_collection=study_collection,
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

        This leverages the `get_many_fulltext_pdfs_cycling_apis` method,
        rather than strictly looping over individual requests (although
        this may be done in the background, depending on API config).

        Args:
            references (list[Reference]): A list of reference objects.

        Returns:
            list[Enhancement]: The generated batch of enhancements.

        """
        raise NotImplementedError

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
            httpx.AsyncClient() as client,
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

        async with httpx.AsyncClient() as client:
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
