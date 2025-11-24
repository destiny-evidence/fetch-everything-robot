"""Openalex Fetcher module."""

import asyncio
from pathlib import Path

from httpx import HTTPError
from loguru import logger
from pydantic import AnyUrl

from app.config import Settings
from app.fetching import BasePublisherFetcher
from app.fetching.core import (
    AsyncHTTPXRetryClient,
    FullTextStreamError,
    StudyCollection,
    stream_file,
)
from app.utils import format_doi, validate_doi


class OpenAlexAPIError(Exception):
    """Raise when OA API response status code is not 200."""


class PDFUnavailableError(Exception):
    """Raise when we can't find a PDF."""


class OpenalexFetcher(BasePublisherFetcher):
    """Openalex fetcher impelmentation."""

    def __init__(self, settings: Settings, wait_time_seconds: float = 2.0) -> None:
        """
        Init an OpenAlex fetcher instance.

        Args:
            settings (Settings): The settings to use for the fetcher.
            wait_time_seconds (float, optional): Wait time b/w requests.

        """
        self.settings = settings
        self.wait_time_seconds = wait_time_seconds
        # @harryjmoss below could come from api-config also...
        self.base_url: str = (
            "https://api.openalex.org/works/doi:"  # right now just for DOI
        )
        self.query_params: dict = {"mailto": settings.mailto}
        self.headers: dict = {
            "User-Agent": "destiny-project-ucl",
            "Accept": "application/json",
        }

    async def _get_work(self, doi: str) -> dict:
        """Run a GET request from OA API to get one work by DOI."""
        doi_fmtd = format_doi(doi)
        doi_valid = validate_doi(doi_fmtd)

        async with AsyncHTTPXRetryClient() as client:
            response = await client.get(
                url=self.base_url + doi_valid,
                headers=self.headers,
                params=self.query_params,
            )
            response.raise_for_status()

        return response.json()

    def _get_pdf_url(self, response_object: dict) -> AnyUrl | None:
        """Retrieve best pdf URL if available."""
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
    ) -> Path | None:
        """Download one PDF from Openalex."""
        return await stream_file(
            url=pdf_url, destination=filepath
        )

    async def fetch_many_full_texts(
        self, study_collection: StudyCollection, output_directory: Path
    ) -> dict[str, Path | None]:
        """Fetch full text for a given StudyCollection and save them to output_directory."""
        output_directory.mkdir(parents=True, exist_ok=True)
        output_doi_paths: dict[str, Path | None] = {}
        for study in study_collection.iterate_studies():
            try:
                doi = study.doi.identifier.lower()
                uid = study.uid
                work = await self._get_work(doi)
                pdf_url = self._get_pdf_url(work)
                if pdf_url is not None:
                    pdf_path = await self.download_one_pdf(
                        pdf_url=pdf_url, filepath=output_directory / f"{uid}.pdf"
                    )
                else:
                    logger.warning(f"No pdf for doi {doi}.")
                output_doi_paths[doi] = pdf_path

            except OpenAlexAPIError as openalex_error:
                logger.error(
                    f"Openalex API error fetching data for {doi}: {openalex_error}"
                )
            except HTTPError as http_error:
                logger.error(
                    f"HTTP error fetching Openalex data for {doi}: {http_error}"
                )
            except FullTextStreamError as fulltext_download_error:
                error_message = (
                    f"Full text download error for Openalex DOI {doi}:"
                    f" {fulltext_download_error}"
                )
                logger.error(error_message)

            logger.debug(
                f"Sleeping {self.wait_time_seconds} seconds before next request..."
            )
            await asyncio.sleep(self.wait_time_seconds)

        return output_doi_paths
