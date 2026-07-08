"""Core fetching utilities and models."""

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx2
from destiny_sdk.identifiers import DOIIdentifier, OpenAlexIdentifier
from loguru import logger
from pydantic import AnyUrl, BaseModel, Field, model_validator


class BaseAuthError(Exception):
    """Raise when fetcher API authentication fails."""


class FullTextStreamError(Exception):
    """Custom exception to throw when full text streaming fails."""


class IncompleteFullTextError(FullTextStreamError):
    """Custom exception to throw when a streamed full text file is incomplete."""


class BaseStudy(BaseModel):
    """Base model representing a study with a unique identifier."""

    uid: UUID = Field(..., description="An internal unique identifier for the study.")


class DOIStudy(BaseStudy):
    """
    Model representing a single study with that uses DOI as a unique identifier.

    It _may_ also have an OpenAlex ID, but this is not required. The DOI is the primary
    identifier for this model, and the OpenAlex ID is optional metadata.

    This is functionally different to a Destiny `Reference`
    as it lacks any other metadata.
    """

    doi: DOIIdentifier = Field(..., description="The DOI identifier of the study.")
    openalex_id: OpenAlexIdentifier | None = Field(
        None, description="The OpenAlex identifier of the study, if available."
    )


class OpenAlexStudy(BaseStudy):
    """
    Model representing a single study that uses OpenAlex ID as a unique identifier.

    It _may_ also have a DOI, but this is not required. The OpenAlex ID is the primary
    identifier for this model, and the DOI is optional metadata as not all
    openalex records have DOIs.

    This is functionally different to a Destiny `Reference`
    as it lacks any other metadata.
    """

    openalex_id: OpenAlexIdentifier = Field(
        ..., description="The OpenAlex identifier of the study, if available."
    )
    doi: DOIIdentifier | None = Field(
        None, description="The DOI identifier of the study."
    )


class BaseStudyCollection[T: BaseStudy](BaseModel):
    """Base model representing a collection of studies."""

    studies: list[T] = Field(
        default_factory=list, description="A collection of studies."
    )

    def _identifier_of(self, study: T) -> str | None:
        """
        Get the unique identifier of a study as a string.

        Subclasses should implement this to extract the identifier for the
        concrete study type `T`.
        """
        exception_message = "Subclasses must implement the _identifier_of method."
        raise NotImplementedError(exception_message)

    def remove_study_by_identifier(self, identifier: str) -> None:
        """
        Remove a study from the collection by its unique identifier.

        Args:
            identifier (str): The unique identifier of the study to remove.

        """
        self.studies = [
            study for study in self.studies if self._identifier_of(study) != identifier
        ]


class DOIStudyCollection(BaseStudyCollection[DOIStudy]):
    """Model representing a collection of DOI studies."""

    studies: list[DOIStudy] = Field(
        default_factory=list, description="A collection of studies."
    )

    def _identifier_of(self, study: DOIStudy) -> str | None:
        """
        Get the DOI identifier of a DOIStudy as a string.

        Args:
            study (DOIStudy): A DOIStudy object from which
                to extract the DOI identifier.

        Returns:
            str | None: The DOI identifier of the study, if available.

        """
        return study.doi.identifier if study.doi is not None else None


class OpenAlexStudyCollection(BaseStudyCollection[OpenAlexStudy]):
    """Model representing a collection of studies."""

    studies: list[OpenAlexStudy] = Field(
        default_factory=list, description="A collection of studies."
    )

    def _identifier_of(self, study: OpenAlexStudy) -> str | None:
        """
        Get the OpenAlex ID of an OpenAlexStudy as a string.

        Args:
            study (OpenAlexStudy): An OpenAlexStudy object from which
                to extract the OpenAlex ID.

        Returns:
            str | None: The OpenAlex ID of the study, if available.

        """
        return study.openalex_id.identifier if study.openalex_id is not None else None


class RetrievedFullText(BaseModel):
    """Model representing a retrieved full text file."""

    doi: str | None = Field(None, description="The DOI of the study, if available.")
    uid: UUID = Field(..., description="The unique identifier of the study.")
    openalex_id: str | None = Field(
        None, description="The OpenAlex ID of the study, if available."
    )
    fulltext_path: Path | None = Field(
        None, description="The path to the retrieved full text file, if it exists."
    )
    file_format: Literal["pdf", "xml"] | None = Field(
        None, description="The file format of the retrieved full text file."
    )
    error: str | None = Field(
        None, description="An error message if the retrieval failed."
    )

    @model_validator(mode="after")
    def check_fulltext_path_or_error(self) -> "RetrievedFullText":
        """
        Validate that either fulltext_path or error is set.

        If a full text is returned and saved to file(as XML or PDF),
        the path should exist. If retrieval fails, this file is not
        created, the path does not exist and an error message should be set instead.

        Raises:
            ValueError: If neither fulltext_path nor error is set.

        """
        if self.fulltext_path is None and self.error is None:
            error_message = "Either fulltext_path or error must be set."
            raise ValueError(error_message)
        if self.fulltext_path is not None and self.error is not None:
            error_message = "Only one of fulltext_path or error can be set."
            raise ValueError(error_message)
        if self.error is None and (
            self.fulltext_path is not None and not self.fulltext_path.exists()
        ):
            error_message = f"Full text path does not exist: {self.fulltext_path}"
            raise ValueError(error_message)
        return self


class AsyncHTTPXRetryClient(httpx2.AsyncClient):
    """An HTTPX2 Client with retry logic for transient errors."""

    def __init__(
        self,
        timeout_seconds: int = 360,
        max_retries: int = 3,
        proxy_url: str | None = None,
    ) -> None:
        """
        Initialise the HTTPXRetryClient.

        Args:
            timeout_seconds (int): Timeout for requests in seconds. Defaults to 360.
            max_retries (int): Maximum number of retries for transient errors.

        """
        if proxy_url is None:
            transport = httpx2.AsyncHTTPTransport(retries=max_retries)
        else:
            transport = httpx2.AsyncProxyTransport.from_url(
                proxy_url, retries=max_retries
            )
        super().__init__(
            timeout=httpx2.Timeout(timeout_seconds),
            transport=transport,
        )
        self.max_retries = max_retries

    async def __aenter__(self) -> "AsyncHTTPXRetryClient":
        """
        Define a context manager for an async HTTPX2 client with retries.

        Returns:
            AsyncHTTPXRetryClient: The async HTTPX2 client instance.

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
    url: AnyUrl,
    destination: Path,
    headers: dict | None = None,
    response_validator: Callable[[httpx2.Headers], None] | None = None,
) -> Path | None:
    """
    Stream bytes from a file from a URL and save it to the specified destination.

    Args:
        url (AnyUrl): The URL of the file to download.
        destination (Path): The destination file path.
        headers (dict | None): Optional headers to include. Defaults to None.
        response_validator (Callable[[httpx2.Headers], None] | None):
            Optional function to validate the response headers. Defaults to None.

    Returns:
        Path | None: The path to the downloaded file or None if the download failed.

    """
    if destination.exists():
        logger.info(f"File already exists: {destination}, skipping download.")
        return destination

    try:
        async with (
            httpx2.AsyncClient(follow_redirects=True) as client,
            client.stream("GET", str(url), headers=headers) as response,
        ):
            response.raise_for_status()
            with destination.open("wb") as destination_file:
                async for chunk in response.aiter_bytes():
                    destination_file.write(chunk)

        if response_validator is not None:
            try:
                response_validator(response.headers)
            except IncompleteFullTextError:
                if destination.exists():
                    destination.unlink()
                    logger.warning(f"Removing incomplete file at {destination}.")
                raise
        logger.info(f"File downloaded successfully: {destination}")
    except httpx2.HTTPError as http_error:
        logger.error(f"Error downloading {url}: {http_error}")
        error_message = f"Error downloading {url}: {http_error}"
        raise FullTextStreamError(error_message) from http_error
    except httpx2.StreamError as stream_error:
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
