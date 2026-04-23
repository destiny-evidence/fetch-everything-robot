"""Openalex Fetcher module."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from httpx import HTTPError
from loguru import logger
from pydantic import AnyUrl

from fer.config import Settings
from fer.data_models.openalex import get_openalex_api_config
from fer.fetching import BasePublisherFetcher
from fer.fetching.core import (
    AsyncHTTPXRetryClient,
    FullTextStreamError,
    RetrievedFullText,
    StudyCollection,
    stream_file,
)
from fer.utils import format_doi, validate_doi

if TYPE_CHECKING:
    from fer.data_models.generic import APIConfig


class OpenAlexAPIError(Exception):
    """Raise when OA API response status code is not 200."""


class PDFUnavailableError(Exception):
    """Raise when we can't find a PDF."""


class OpenalexFetcher(BasePublisherFetcher):
    """Openalex fetcher implementation."""

    def __init__(self, settings: Settings, wait_time_seconds: float = 2.0) -> None:
        """
        Initialise an OpenAlex fetcher instance.

        Args:
            settings (Settings): The settings to use for the fetcher.
            wait_time_seconds (float, optional): Wait time between requests.

        """
        self.settings = settings
        self.wait_time_seconds = wait_time_seconds
        self.api_config: APIConfig = get_openalex_api_config(settings)
        self.base_url: AnyUrl = self.api_config.url
        self.query_params: dict | None = self.api_config.query_params
        self.headers: dict = self.api_config.headers

    async def _get_work_doi(self, doi: str) -> dict:
        """
        Run a GET request from OA API to get one work by DOI.

        Args:
            doi (str): The DOI to look up.

        Returns:
            dict: The JSON response from the OA API.

        """
        doi_fmtd = format_doi(doi)
        doi_valid = validate_doi(doi_fmtd)

        async with AsyncHTTPXRetryClient() as client:
            response = await client.get(
                url=f"{self.base_url!s}doi:{doi_valid}",
                headers=self.headers,
                params=self.query_params,
            )
            response.raise_for_status()

        return response.json()

    def _get_pdf_url(self, response_object: dict) -> AnyUrl | None:
        """
        Extract the PDF URL from the OpenAlex response object.

        Retrieves the best pdf URL, if available.

        Args:
            response_object (dict): The response object from OpenAlex API.

        Returns:
            AnyUrl | None: The PDF URL if found, else None.

        """
        if "locations" not in response_object:
            return None
        locations = response_object["locations"]
        pdf_url = None
        for loc in locations:
            if loc["pdf_url"]:
                pdf_url = loc["pdf_url"]
                break
        return pdf_url

    async def download_one_pdf(
        self,
        pdf_url: AnyUrl,
        filepath: Path,
        headers: dict | None = None,
    ) -> Path | None:
        """
        Download one PDF from Openalex.

        Args:
            pdf_url (AnyUrl): The URL of the PDF to download.
            filepath (Path): Output file path.
            headers (dict | None, optional): Optional headers for the request.
                Defaults to None.

        Returns:
            Path | None: The path to the downloaded PDF or None if download failed.

        """
        return await stream_file(url=pdf_url, destination=filepath, headers=headers)

    async def fetch_many_full_texts(
        self,
        study_collection: StudyCollection,
        output_directory: Path,
        **kwargs: object,
    ) -> list[RetrievedFullText]:
        """
        Fetch full text for a given StudyCollection and save them to output_directory.

        Args:
            study_collection (StudyCollection): The study collection for which to fetch
                the full text.
            output_directory (Path): The directory where the full text should be saved.

        Returns:
            list[RetrievedFullText]: A list of RetrievedFullText instances
                representing the saved PDF files.

        """
        _ = kwargs
        output_directory.mkdir(parents=True, exist_ok=True)
        output_items: list[RetrievedFullText] = []
        for study in study_collection.studies:
            try:
                doi = study.doi.identifier.lower()
                uid = study.uid
                work = await self._get_work_doi(doi)
                pdf_url = self._get_pdf_url(work)
                pdf_path: Path | None = None
                if pdf_url is not None:
                    pdf_path = await self.download_one_pdf(
                        pdf_url=pdf_url, filepath=output_directory / f"{uid}.pdf"
                    )
                    output_items.append(
                        RetrievedFullText(
                            doi=doi,
                            uid=uid,
                            fulltext_path=pdf_path,
                            file_format="pdf",
                        )
                    )
                else:
                    warning_message = f"No PDF found for {doi=}."
                    output_items.append(
                        RetrievedFullText(
                            doi=doi, uid=uid, fulltext_path=None, error=warning_message
                        )
                    )
            except OpenAlexAPIError as openalex_error:
                error_message = (
                    f"Openalex API error fetching data for {doi}: {openalex_error}"
                )

                logger.error(error_message)
                output_items.append(
                    RetrievedFullText(
                        doi=doi, uid=uid, fulltext_path=None, error=error_message
                    )
                )
            except HTTPError as http_error:
                error_message = (
                    f"HTTP error fetching Openalex data for {doi}: {http_error}"
                )
                logger.error(error_message)
                output_items.append(
                    RetrievedFullText(
                        doi=doi, uid=uid, fulltext_path=None, error=error_message
                    )
                )
            except FullTextStreamError as fulltext_download_error:
                error_message = (
                    f"Full text download error for Openalex DOI {doi}:"
                    f" {fulltext_download_error}"
                )
                logger.error(error_message)
                output_items.append(
                    RetrievedFullText(
                        doi=doi, uid=uid, fulltext_path=None, error=error_message
                    )
                )

            logger.debug(
                f"Sleeping {self.wait_time_seconds} seconds before next request..."
            )
            await asyncio.sleep(self.wait_time_seconds)

        return output_items
