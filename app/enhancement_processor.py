"""Generation functions for single and batch fulltext enhancements."""

import httpx
from destiny_sdk.enhancements import (
    Enhancement,
)
from destiny_sdk.references import Reference
from destiny_sdk.robots import (
    LinkedRobotError,
    RobotEnhancementBatch,
)
from loguru import logger

from app.data_models.generic import APIConfig
from app.fetch_fulltext import FullTextFetcher


class BatchEnhancementGenerationError(Exception):
    """Custom exception for errors during batch enhancement generation."""


class FullTextEnhancementProcessor:
    """Handles the processing of full text enhancement requests."""

    def __init__(
        self,
        robot_version: str,
        source_name: str,
        global_api_config: dict[str, APIConfig],
        available_api_configs: list[APIConfig],
    ) -> None:
        """
        Initialise the processor with configuration.

        Args:
            robot_version (str): The version of the robot.
            source_name (str): The name of the `source` in the destiny repository.
                In practical terms, this is the app name _of this app_.
            global_api_config (dict[str, APIConfig]): Global API configuration.
            available_api_configs (list[APIConfig]): List of API configurations.

        """
        self.robot_version = robot_version
        self.source_name = source_name

        self.fulltext_fetcher = FullTextFetcher(global_api_config)
        self.available_api_configs = available_api_configs

    def create_fulltext_enhancement(
        self,
        references: list[Reference],
    ) -> list[Enhancement]:
        """
        Create full text enhancements with efficient memory usage.

        This operates on a batch of references as a default,
        but that could be a batch of one.

        This leverages the `get_many_fulltexts_cycling_apis` method,
        rather than strictly looping over individual requests (although
        this may be done in the background, depending on API config).

        Args:
            references (list[Reference]): A list of reference objects.

        Returns:
            list[Enhancement]: The generated batch of enhancements.

        """
        raise NotImplementedError

    def generate_fulltext_enhancement_batch_request(
        self,
        references: list[Reference],
        enhancements_references_map: list[dict],
        available_api_configs: list[APIConfig],
        app_title: str,
    ) -> list[Enhancement | LinkedRobotError]:
        """
        Generate a batch of full text enhancements from a batch of references.

        Args:
            references (list[Reference]): A list of reference objects.
            enhancements_references_map (list[dict]): A list of enhancement dictionaries
                that map reference IDs to their enhancements.

        Returns:
            list[Enhancement]: The generated batch of enhancements.

        Raises:
            BatchEnhancementGenerationError: If there is an error generating the batch.
                Represents a complete failing of the enhancement process.

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
            generated_enhancements = self.create_fulltext_enhancement(
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
