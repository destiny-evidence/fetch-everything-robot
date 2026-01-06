"""Crossref Fetcher Module."""

import asyncio
from pathlib import Path

from habanero import Crossref, RequestError
from loguru import logger
from pydantic import AnyUrl

from fer.config import Settings
from fer.data_models.crossref import get_crossref_api_config
from fer.fetching import BasePublisherFetcher
from fer.fetching.core import (
    FullTextStreamError,
    RetrievedFullText,
    StudyCollection,
    stream_file,
)


class CrossrefFetcher(BasePublisherFetcher):
    """Define a concrete fetcher for CrossRef full texts."""

    def __init__(
        self, settings: Settings, wait_time_seconds: int = 2, timeout_seconds: int = 180
    ) -> None:
        """
        Initialise a CrossrefFetcher.

        Args:
            settings (Settings): The settings object to use for the fetcher.
            wait_time_seconds (int, optional):
                The number of seconds to wait between requests. Defaults to 2.
            timeout_seconds (int): Number of seconds to define a timeout in
                habanero Crossref requests. Defaults to 180 (3 minutes).

        """
        self.settings = settings
        self.api_config = get_crossref_api_config()
        self.wait_time_seconds = wait_time_seconds
        self.timeout_seconds = timeout_seconds

    def get_url_from_pdf_content_type(self, crossref_response: dict) -> dict:
        """
        Get the URL from the content type of CrossRef data.
        Here we specify content type as 'application/pdf'.

        Args:
            crossref_response (dict): The CrossRef response data.

        Returns:
            dict: The content type and corresponding URL.

        """
        content_type = "application/pdf"
        data = crossref_response
        pdf_link_possible = (
            self.api_config.unpack_strategy.pdf_link_strategy is not None
        )
        if not pdf_link_possible:
            logger.debug("No PDF link strategy defined in CrossRef unpack strategy.")
            return {"content_type": None, "url": None}
        pdf_strategy = self.api_config.unpack_strategy.pdf_link_strategy
        if pdf_strategy is None:
            logger.debug("No PDF link strategy defined in CrossRef unpack strategy.")
            return {"content_type": None, "url": None}
        for key in pdf_strategy:
            if isinstance(data, dict) and key in data:
                data = data.get(key, {})
            else:
                logger.error(f"Key {key} not found in CrossRef response.")
                return {"content_type": None, "url": None}

        unique_content_url_pairs: list[tuple[str, str]] = []
        observed_urls: set[str] = set()
        if isinstance(data, list):
            for link in data:
                url: str = link["URL"]
                if url and url not in observed_urls:
                    found_content_type: str = link.get("content-type", "")
                    unique_content_url_pairs.append((found_content_type, url))
                    observed_urls.add(url)
                    if found_content_type == content_type:
                        logger.debug(f"Found PDF URL in CrossRef response: {url}")
                        return {"content_type": found_content_type, "url": url}
        if unique_content_url_pairs:
            first_content_type, first_url = unique_content_url_pairs[0]
            logger.debug(
                f"No PDF URL found; returning first available URL from"
                f" CrossRef response: {first_url} with content type"
                f" {first_content_type}"
            )
            return {"content_type": first_content_type, "url": first_url}
        logger.debug("No valid content URLs found in CrossRef response.")
        return {"content_type": None, "url": None}

    def pdf_url_is_valid(self, content_info: dict) -> bool:
        """
        Check if the PDF URL is valid based on content info.

        Args:
            content_info (dict): The content information from CrossRef.
                This is expected to have 'content_type' and 'url' keys.

        Returns:
            bool: True if the PDF URL is valid, False otherwise.

        """
        return "pdf" in content_info.get("content_type", "").lower() and all(
            keyword not in content_info.get("url", "").lower()
            for keyword in ["elsevier", "wiley", "tandfonline"]
        )

    async def download_one_pdf(
        self,
        pdf_url: AnyUrl,
        filepath: Path,
        headers: dict | None = None,
    ) -> Path | None:
        """
        Download one PDF from CrossRef.

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
        Fetch full texts using the CrossRef API.

        Args:
            study_collection (StudyCollection): The collection of studies to fetch.
            output_directory (Path): The directory to save the fetched full texts.

        Returns:
            list[RetrievedFullText]: A list of RetrievedFullText instances
                representing the saved full text files.

        """
        _ = kwargs
        output_directory.mkdir(parents=True, exist_ok=True)
        crossref = Crossref(
            mailto=self.settings.mailto,
            timeout=self.timeout_seconds,
        )
        found_pdfs = set()
        output_items: list[RetrievedFullText] = []
        for study in study_collection.studies:
            doi = study.doi.identifier.lower()
            uid = study.uid
            try:
                crossref_response = crossref.works(ids=doi)
                content_info = self.get_url_from_pdf_content_type(crossref_response)
                if self.pdf_url_is_valid(content_info):
                    url = str(content_info.get("url"))
                    pdf_path = output_directory / f"{uid}.pdf"
                    if uid not in found_pdfs:
                        output_file_path = await self.download_one_pdf(
                            AnyUrl(url), pdf_path
                        )
                        if output_file_path:
                            output_items.append(
                                RetrievedFullText(
                                    doi=doi,
                                    uid=uid,
                                    pdf_path=output_file_path,
                                )
                            )
                        found_pdfs.add(uid)
                        logger.info(f"Crossref download success for {uid}: {url}")
                        await asyncio.sleep(self.wait_time_seconds)
                else:
                    error_message = (
                        f"No valid PDF found via CrossRef for {doi=}, {uid=}"
                    )
                    logger.warning(error_message)
                    output_items.append(
                        RetrievedFullText(
                            doi=doi, uid=uid, pdf_path=None, error=error_message
                        )
                    )
            except RequestError as request_error:
                error_message = (
                    f"CrossRef request error for {uid=}, {doi=} - {request_error}"
                )
                logger.error(error_message)
                output_items.append(
                    RetrievedFullText(
                        doi=doi, uid=uid, pdf_path=None, error=error_message
                    )
                )
            except FullTextStreamError as fulltext_download_error:
                error_message = (
                    f"Error streaming CrossRef data {uid}:{doi}"
                    f" - {fulltext_download_error}"
                )
                logger.error(error_message)
                output_items.append(
                    RetrievedFullText(
                        doi=doi, uid=uid, pdf_path=None, error=error_message
                    )
                )

        logger.info(f"{len(found_pdfs)} full texts found via CrossRef!")
        return output_items
