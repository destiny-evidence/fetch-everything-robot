"""Unpaywall Fetcher Module."""

from pathlib import Path

import httpx
from loguru import logger
from pydantic import AnyUrl, ValidationError

from fer.config import Settings
from fer.data_models.unpaywall import get_unpaywall_api_config
from fer.fetching import BasePublisherFetcher
from fer.fetching.core import (
    AsyncHTTPXRetryClient,
    FullTextStreamError,
    RetrievedFullText,
    StudyCollection,
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

    async def fetch_many_full_texts(
        self,
        study_collection: StudyCollection,
        output_directory: Path,
    ) -> list[RetrievedFullText]:
        """
        Fetch the full text of an Unpaywall article.

        Args:
            study_collection (StudyCollection): The collection of studies to fetch.
            output_directory (Path): The output directory path.

        Returns:
            list[RetrievedFullText]: A list of RetrievedFullText instances
                representing the saved PDF files.

        """
        output_directory.mkdir(parents=True, exist_ok=True)

        found_pdfs = []
        output_items: list[RetrievedFullText] = []
        for study in study_collection.studies:
            doi = study.doi.identifier.lower()
            uid = study.uid
            url = f"{self.base_url}{doi}?email={self.settings.mailto}"

            try:
                async with AsyncHTTPXRetryClient() as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    data = await response.json()
                    pdf_url: AnyUrl | None = None

                    publisher = data.get("publisher", "")
                    pdf_strategy = self.api_config.unpack_strategy.pdf_link_strategy
                    if pdf_strategy is not None:
                        for key in pdf_strategy:
                            if isinstance(data, dict) and key in data:
                                data = data.get(key, {})
                            else:
                                error_message = (
                                    f"Unpaywall PDF key {key} not found for {doi}"
                                )
                                logger.error(error_message)
                                output_items.append(
                                    RetrievedFullText(
                                        doi=doi,
                                        uid=uid,
                                        pdf_path=None,
                                        error=error_message,
                                    )
                                )
                        try:
                            pdf_url = AnyUrl(data) if isinstance(data, str) else None
                        except ValidationError:
                            error_message = (
                                f"Unpaywall: Invalid PDF URL for {doi}: {data}"
                            )
                            logger.error(error_message)
                            pdf_url = None

                    publisher_in_excluded_list = publisher in [
                        "Wiley",
                        "Elsevier BV",
                        "SAGE Publications",
                    ]
                    taylor_and_francis_in_url = (
                        "tandfonline" in str(pdf_url) if pdf_url else False
                    )

                    pdf_found = bool(
                        pdf_url
                        and not publisher_in_excluded_list
                        and not taylor_and_francis_in_url
                    )
                    if pdf_found and pdf_url is not None:
                        pdf_path = output_directory / f"{uid}.pdf"
                        output_file_path = await self.download_one_pdf(
                            AnyUrl(pdf_url), pdf_path
                        )
                        if output_file_path:
                            output_items.append(
                                RetrievedFullText(
                                    doi=doi,
                                    uid=uid,
                                    pdf_path=output_file_path,
                                )
                            )
                        found_pdfs.append(uid)
                        logger.info(
                            f"Unpaywall download success for {uid=}, {doi=}: {pdf_url}"
                        )
                    else:
                        warning_message = f"Unpaywall PDF not found for {uid=}, {doi=}"
                        logger.warning(warning_message)
                        logger.warning(
                            f"{publisher=},"
                            f" {publisher_in_excluded_list=},"
                            f" {taylor_and_francis_in_url=}"
                        )
                        output_items.append(
                            RetrievedFullText(
                                doi=doi, uid=uid, pdf_path=None, error=warning_message
                            )
                        )

            except httpx.HTTPError as http_error:
                error_message = (
                    f"HTTP error fetching Unpaywall data for {doi}: {http_error}"
                )
                logger.error(error_message)
                output_items.append(
                    RetrievedFullText(
                        doi=doi, uid=uid, pdf_path=None, error=error_message
                    )
                )
            except FullTextStreamError as fulltext_download_error:
                error_message = (
                    f"Error streaming Unpaywall data {uid}:{doi}"
                    f" - {fulltext_download_error}"
                )
                logger.error(error_message)
                output_items.append(
                    RetrievedFullText(
                        doi=doi, uid=uid, pdf_path=None, error=error_message
                    )
                )
        logger.info(f"{len(found_pdfs)} full texts found via Unpaywall")
        return output_items
