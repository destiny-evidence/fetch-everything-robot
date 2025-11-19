"""Crossref Fetcher Module."""

import asyncio
from pathlib import Path

from habanero import Crossref, RequestError
from loguru import logger
from pydantic import AnyUrl

from app.config import Settings
from app.fetching import BasePublisherFetcher
from app.fetching.core import FullTextStreamError, StudyCollection, stream_file


class CrossrefFetcher(BasePublisherFetcher):
    """Define a concrete fetcher for CrossRef full texts."""

    def __init__(self, settings: Settings, wait_time_seconds: int = 2) -> None:
        """
        Initialise a CrossrefFetcher.

        Args:
            settings (Settings): The settings to use for the fetcher.
            wait_time_seconds (int, optional): The settings to use for the fetcher.

        """
        self.settings = settings
        self.wait_time_seconds = wait_time_seconds

    def get_url_from_pdf_content_type(
        self, data: dict, content_type: str = "application/pdf"
    ) -> dict:
        """
        Get the URL from the content type of CrossRef data.
        Here we specify content type as 'application/pdf'.

        Args:
            data (dict): The CrossRef data.
            content_type (str, optional): The content type to look for.
                Defaults to "application/pdf".

        Returns:
            dict: The content type and corresponding URL.

        """
        if "message" in data and "link" in data["message"]:
            unique_content_url_pairs = []
            observed_urls = set()
            for link in data["message"]["link"]:
                url = link["URL"]
                if url not in observed_urls:
                    found_content_type = link.get("content-type", "")
                    unique_content_url_pairs.append((found_content_type, url))
                    observed_urls.add(url)
                    if found_content_type == content_type:
                        return {"content_type": found_content_type, "url": url}
        if unique_content_url_pairs:
            first_content_type, first_url = unique_content_url_pairs[0]
            return {"content_type": first_content_type, "url": first_url}
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

    async def fetch_many_full_texts(
        self, study_collection: StudyCollection, output_directory: Path
    ) -> dict[str, Path | None]:
        """
        Fetch full texts using the CrossRef API.

        Args:
            study_collection (StudyCollection): The collection of studies to fetch.
            output_directory (Path): The directory to save the fetched full texts.

        Returns:
            dict[str, Path]: A dictionary mapping study UIDs to the paths of
                the saved full text files.

        """
        output_directory.mkdir(parents=True, exist_ok=True)
        crossref = Crossref()
        found_pdfs = set()
        output_doi_paths: dict[str, Path | None] = {}
        for study in study_collection.studies:
            doi = study.doi.identifier.lower()
            uid = study.uid
            try:
                data = crossref.works(ids=doi)
                content_info = self.get_url_from_pdf_content_type(data)
                if self.pdf_url_is_valid(content_info):
                    url = str(content_info.get("url"))
                    pdf_path = output_directory / f"{uid}.pdf"
                    if uid not in found_pdfs:  # Avoid duplicate downloads
                        output_file_path = stream_file(AnyUrl(url), pdf_path)
                        if output_file_path:
                            output_doi_paths[doi] = output_file_path
                        found_pdfs.add(uid)
                        logger.info(f"Crossref download success for {uid}: {url}")
                        await asyncio.sleep(self.wait_time_seconds)
                else:
                    logger.warning(
                        f"No valid PDF found via CrossRef for {doi=}, {uid=}"
                    )
                    output_doi_paths[doi] = None
            except RequestError as request_error:
                error_message = (
                    f"CrossRef request error for {uid}:{doi} - {request_error}"
                )
                logger.error(error_message)
            except FullTextStreamError as fulltext_download_error:
                error_message = (
                    f"Error streaming CrossRef data {uid}:{doi}"
                    f" - {fulltext_download_error}"
                )
                logger.error(error_message)

        logger.info(f"{len(found_pdfs)} full texts found via CrossRef!")
        return output_doi_paths
