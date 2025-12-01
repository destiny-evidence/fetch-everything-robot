"""Define fetchers to retrieve full-text articles from various sources."""

import tempfile
from pathlib import Path

from app.config import Settings
from app.fetching import BasePublisherFetcher
from app.fetching.core import StudyCollection


class FullTextFetcherError(Exception):
    """Custom exception for FullTextFetcher errors."""


class FullTextFetcher:
    """
    A class to fetch full-text articles from various publishers.

    Implemented with the Strategy design pattern to delegate fetching
    to publisher-specific fetchers.
    """

    def __init__(
        self,
        settings: Settings,
        publisher_dict: dict[str, BasePublisherFetcher],
        timeout: int = 300,
    ) -> None:
        """
        Initialise the FullTextFetcher.

        Args:
            settings (Settings): The settings to use for the fetcher.
            timeout (int, optional): The timeout for requests. Defaults to 300.

        """
        self.settings = settings
        self.timeout = timeout
        self.fetchers = publisher_dict

    async def fetch(
        self,
        publisher_name: str,
        study_collection: StudyCollection,
        output_directory: Path | None = None,
    ) -> dict[str, Path | None]:
        """
        Fetch full-text articles from the specified publisher.

        Args:
            publisher_name (str): The name of the publisher.
            study_collection (StudyCollection): A collection of studies.
            output_directory (Path | None, optional): The directory to save the
                fetched articles. Defaults to None.

        Returns:
            dict[str, Path | None]: A dictionary mapping study DOIs to the paths of the
                saved full text files.

        """
        fetcher = self.fetchers.get(publisher_name.lower())
        if not fetcher:
            error_message = f"Unknown publisher: {publisher_name}"
            raise FullTextFetcherError(error_message)
        if output_directory is None:
            output_directory = Path(tempfile.TemporaryDirectory(delete=False).name)
        return await fetcher.fetch_full_text(study_collection, output_directory)
