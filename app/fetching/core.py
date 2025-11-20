"""Core fetching utilities and models."""

import tempfile
from pathlib import Path
from uuid import UUID

import httpx
from destiny_sdk.identifiers import DOIIdentifier
from loguru import logger
from pydantic import AnyUrl, BaseModel, Field


class FullTextStreamError(Exception):
    """Custom exception to throw when full text streaming fails."""


class Study(BaseModel):
    """
    Model representing a single study with DOI and unique identifier.

    This is functionally different to a Destiny `Reference`
    as it lacks any other metadata.
    """

    doi: DOIIdentifier = Field(..., description="The DOI identifier of the study.")
    uid: UUID = Field(..., description="A unique identifier for the study.")


class StudyCollection(BaseModel):
    """Model representing a collection of studies."""

    studies: list[Study] = Field(
        default_factory=list, description="A collection of studies."
    )

    def remove_study_by_doi(self, doi: str) -> None:
        """
        Remove a study from the collection by its DOI.

        Args:
            doi (str): The DOI of the study to remove.

        """
        self.studies = [study for study in self.studies if study.doi.identifier != doi]


class AsyncHTTPXRetryClient(httpx.AsyncClient):
    """An HTTPX Client with retry logic for transient errors."""

    def __init__(
        self,
        timeout_seconds: int = 360,
        max_retries: int = 3,
    ) -> None:
        """
        Initialise the HTTPXRetryClient.

        Args:
            timeout_seconds (int): Timeout for requests in seconds. Defaults to 360.
            max_retries (int): Maximum number of retries for transient errors.

        """
        super().__init__(
            timeout=httpx.Timeout(timeout_seconds),
            transport=httpx.AsyncHTTPTransport(retries=max_retries),
        )
        self.max_retries = max_retries

    async def __aenter__(self) -> "AsyncHTTPXRetryClient":
        """
        Define a context manager for an async HTTPX client with retries.

        Returns:
            AsyncHTTPXRetryClient: The async HTTPX client instance.

        """
        await super().__aenter__()
        return self


async def download_temporary_file(url: AnyUrl) -> Path | None:
    """
    Stream bytes from a file from a URL and save it to a temporary file.
    By some definition of "temporary", since the file will persist until deleted.

    Args:
        url (AnyUrl): The URL of the file to download.

    Returns:
        Path | None: The path to the temporary file or None if the download failed.

    """
    with tempfile.NamedTemporaryFile(delete_on_close=False, delete=False) as temp_file:
        output_temporary_file = await stream_file(AnyUrl(url), Path(temp_file.name))
        if output_temporary_file:
            return Path(temp_file.name)
    return None


def delete_temporary_file(temp_file_path: Path) -> None:
    """
    Delete a temporary file.

    Args:
        temp_file_path (Path): The path to the "temporary" file to delete.

    """
    try:
        temp_file_path.unlink()
        logger.debug(f"Temporary file deleted: {temp_file_path}")
    except FileNotFoundError as unfound_file_error:
        logger.error(
            f"Error deleting temporary file {temp_file_path}: {unfound_file_error}"
        )


async def stream_file(
    url: AnyUrl, destination: Path, headers: dict | None = None
) -> Path | None:
    """
    Stream bytes from a file from a URL and save it to the specified destination.

    Args:
        url (AnyUrl): The URL of the file to download.
        destination (Path): The destination file path.
        headers (dict | None): Optional headers to include. Defaults to None.

    Returns:
        Path | None: The path to the downloaded file or None if the download failed.

    """
    if destination.exists():
        logger.info(f"File already exists: {destination}, skipping download.")
        return destination

    try:
        client = httpx.AsyncClient()
        async with client.stream("GET", str(url), headers=headers) as response:
            response.raise_for_status()
            with destination.open("wb") as destination_file:
                async for chunk in response.aiter_bytes():
                    destination_file.write(chunk)

        logger.info(f"File downloaded successfully: {destination}")
    except httpx.HTTPError as http_error:
        logger.error(f"Error downloading {url}: {http_error}")
        error_message = f"Error downloading {url}: {http_error}"
        raise FullTextStreamError(error_message) from http_error
    except httpx.StreamError as stream_error:
        logger.error(f"Streaming error for {url}: {stream_error}")
        error_message = f"Streaming error for {url}: {stream_error}"
        raise FullTextStreamError(error_message) from stream_error
    if destination.exists() and destination.stat().st_size == 0:
        destination.unlink()
        logger.error(f"File empty - removing empty file: {destination}")
        return None
    if not destination.exists():
        logger.error("Streamed file empty - skipping save to disk.")
        return None
    return destination
