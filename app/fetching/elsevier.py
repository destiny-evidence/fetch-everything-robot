"""Elsevier Fetcher Module."""

from pathlib import Path

import httpx
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


class ElsevierFetcher(BasePublisherFetcher):
    """Define a concrete fetcher for Elsevier full texts."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialise an ElsevierFetcher.

        Args:
            settings (Settings): The settings to use for the fetcher.

        """
        self.settings = settings
        self.base_url = "https://api.elsevier.com/content/article/doi/"

    async def fetch_full_text(
        self, study_collection: StudyCollection, output_directory: Path
    ) -> dict[str, Path | None]:
        """
        Fetch the full text of an Elsevier article.

        Args:
            study_collection (StudyCollection): The collection of studies to fetch.
            output_directory (Path): The output directory path.

        Returns:
            dict[str, Path]: A dictionary mapping DOIs to the paths of the
                saved XML files

        """
        output_directory.mkdir(parents=True, exist_ok=True)
        headers = {}
        api_key = (
            self.settings.elsevier_scopus_key.get_secret_value()
            if self.settings.elsevier_scopus_key is not None
            else None
        )
        inst_token = (
            self.settings.elsevier_scopus_inst_token.get_secret_value()
            if self.settings.elsevier_scopus_inst_token is not None
            else None
        )
        if api_key is not None:
            headers["X-ELS-APIKey"] = api_key
        if inst_token is not None:
            headers["X-ELS-Insttoken"] = inst_token

        output_doi_paths: dict[str, Path | None] = {}
        for study in study_collection.studies:
            doi = study.doi.identifier.lower()
            uid = study.uid
            url = f"{self.base_url}{doi}/"

            try:
                async with AsyncHTTPXRetryClient() as client:
                    response = await client.get(url, headers=headers)
                    response.raise_for_status()
                    if response.status_code == httpx.codes.OK:
                        file_path = output_directory / f"{uid}.xml"
                        output_file_path = stream_file(
                            AnyUrl(url), file_path, headers=headers
                        )
                        if output_file_path:
                            output_doi_paths[doi] = output_file_path
                        logger.info(f"Elsevier XML content saved {uid}: {file_path}")
                    else:
                        warning_message = (
                            f"Unexpected successful status code for {uid=}, {doi=}."
                            f" Status Code: {response.status_code}"
                        )
                        logger.warning(warning_message)
                        logger.warning(f"Response Content: {response.text}")
                        output_doi_paths[doi] = None
            except httpx.HTTPError as http_error:
                logger.error(
                    f"HTTP error fetching Elsevier data for {doi}: {http_error}"
                )
            except FullTextStreamError as fulltext_download_error:
                error_message = (
                    f"Full text download error for Elsevier DOI {doi}:"
                    f" {fulltext_download_error}"
                )
                logger.error(error_message)
        return output_doi_paths
