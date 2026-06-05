"""Unpaywall Fetcher Module."""

from pathlib import Path

import httpx
from loguru import logger
from pydantic import AnyUrl, HttpUrl, ValidationError

from fer.config import Settings
from fer.data_models.unpaywall import get_unpaywall_api_config
from fer.fetching import BasePublisherFetcher
from fer.fetching.core import (
    AsyncHTTPXRetryClient,
    DOIStudy,
    DOIStudyCollection,
    FullTextStreamError,
    RetrievedFullText,
    stream_file,
)


class UnpaywallFetcher(BasePublisherFetcher):
    """Define a concrete fetcher for Unpaywall full texts."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialise an UnpaywallFetcher.

        Args:
            settings (Settings): The settings to use for the fetcher.

        """
        self.settings = settings
        self.api_config = get_unpaywall_api_config()
        self.base_url = self.api_config.url

    async def download_one_pdf(
        self,
        pdf_url: AnyUrl,
        filepath: Path,
        headers: dict | None = None,
    ) -> Path | None:
        """
        Download one PDF from Unpaywall.

        Args:
            pdf_url (AnyUrl): The URL of the PDF to download.
            filepath (Path): Output file path.
            headers (dict | None, optional): Optional headers for the request.
                Defaults to None.

        Returns:
            Path | None: The path to the downloaded PDF or None if download failed.

        """
        return await stream_file(url=pdf_url, destination=filepath, headers=headers)

    def validate_pdf_url(self, doi: str, data: str | dict) -> HttpUrl | None:
        """
        Validate the PDF URL.

        Args:
            doi (str): The DOI of the study.
            data (str | dict): The data to validate as a URL.

        Returns:
            HttpUrl | None: The validated HttpUrl or None if invalid.

        """
        try:
            return HttpUrl(data) if isinstance(data, str) else None
        except ValidationError:
            error_message = f"Unpaywall: Invalid PDF URL for {doi}: {data}"
            logger.error(error_message)
            return None

    async def retrieve_pdf_url(
        self, pdf_strategy: list[str] | None, doi: str, data: dict
    ) -> HttpUrl | None:
        """
        Retrieve the PDF URL using the provided strategy for a single study response.

        Args:
            pdf_strategy (list[str] | None): The list of keys to recursively
                use to extract the PDF URL from the response data dictionary.
            doi (str): The DOI of the study.
            data (dict): The data dictionary containing study information.

        Returns:
            HttpUrl | None: The validated PDF URL or None if not found.

        """
        if not isinstance(pdf_strategy, list) or not pdf_strategy:
            error_message = (
                f"Unpaywall: Invalid PDF strategy provided for {doi}: {pdf_strategy}"
            )
            logger.error(error_message)
            return None
        for key in pdf_strategy:
            if isinstance(data, dict) and key in data:
                data = data.get(key, {})
            else:
                error_message = f"Unpaywall PDF key {key} not found for {doi}"
                logger.error(error_message)
                return None
        return self.validate_pdf_url(doi, data)

    async def process_single_study_response(
        self, study: DOIStudy, output_directory: Path
    ) -> RetrievedFullText:
        """
        Process a single study response from Unpaywall.

        Args:
            study (DOIStudy): The Study object to process.
            output_directory (Path): The directory where the PDF should be saved.

        Returns:
            RetrievedFullText: The result of the PDF retrieval process.

        """
        doi = study.doi.identifier.lower()
        uid = study.uid
        url = f"{self.base_url}{doi}?email={self.settings.mailto}"

        try:
            async with AsyncHTTPXRetryClient() as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                pdf_url: AnyUrl | None = None

                publisher = data.get("publisher", "")
                pdf_strategy = self.api_config.unpack_strategy.pdf_link_strategy
                pdf_url = await self.retrieve_pdf_url(pdf_strategy, doi, data)
                if pdf_url is None:
                    warning_message = f"Unpaywall PDF URL not found for {uid=}, {doi=}"
                    logger.warning(warning_message)
                    return RetrievedFullText(
                        doi=doi,
                        uid=uid,
                        fulltext_path=None,
                        error=warning_message,
                    )

                publisher_in_excluded_list = publisher in [
                    "Wiley",
                    "Elsevier BV",
                    "SAGE Publications",
                ]
                taylor_and_francis_in_url = (
                    "tandfonline" in str(pdf_url) if pdf_url else False
                )

                pdf_found = bool(
                    not publisher_in_excluded_list and not taylor_and_francis_in_url
                )
                if pdf_found:
                    pdf_path = output_directory / f"{uid}.pdf"
                    output_file_path = await self.download_one_pdf(
                        AnyUrl(pdf_url), pdf_path
                    )
                    if output_file_path:
                        logger.info(
                            f"Unpaywall download success for {uid=}, {doi=}: {pdf_url}"
                        )
                        return RetrievedFullText(
                            doi=doi,
                            uid=uid,
                            fulltext_path=output_file_path,
                            file_format="pdf",
                        )
                    return RetrievedFullText(
                        doi=doi,
                        uid=uid,
                        fulltext_path=None,
                        error="Unpaywall PDF download failed.",
                    )

                warning_message = f"Unpaywall PDF not found for {uid=}, {doi=}"
                logger.warning(warning_message)
                logger.warning(
                    f"{publisher=},"
                    f" {publisher_in_excluded_list=},"
                    f" {taylor_and_francis_in_url=}"
                )
                return RetrievedFullText(
                    doi=doi, uid=uid, fulltext_path=None, error=warning_message
                )

        except httpx.HTTPError as http_error:
            error_message = (
                f"HTTP error fetching Unpaywall data for {doi}: {http_error}"
            )
            logger.error(error_message)
            return RetrievedFullText(
                doi=doi, uid=uid, fulltext_path=None, error=error_message
            )
        except FullTextStreamError as fulltext_download_error:
            error_message = (
                f"Error streaming Unpaywall data {uid}:{doi}"
                f" - {fulltext_download_error}"
            )
            logger.error(error_message)
            return RetrievedFullText(
                doi=doi, uid=uid, fulltext_path=None, error=error_message
            )

    async def fetch_many_full_texts(
        self,
        study_collection: DOIStudyCollection,
        output_directory: Path,
        **kwargs: object,
    ) -> list[RetrievedFullText]:
        """
        Fetch the full text of an Unpaywall article.

        Args:
            study_collection (DOIStudyCollection): The collection of studies to fetch.
            output_directory (Path): The output directory path.

        Returns:
            list[RetrievedFullText]: A list of RetrievedFullText instances
                representing the saved PDF files.

        """
        _ = kwargs
        output_directory.mkdir(parents=True, exist_ok=True)

        found_pdfs = []
        output_items: list[RetrievedFullText] = []
        for study in study_collection.studies:
            result = await self.process_single_study_response(study, output_directory)
            output_items.append(result)
            if result.fulltext_path is not None:
                found_pdfs.append(result.uid)

        logger.info(f"{len(found_pdfs)} full texts found via Unpaywall")
        return output_items
