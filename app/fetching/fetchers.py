"""Define fetchers to retrieve full-text articles from various sources."""

from pathlib import Path
from typing import TYPE_CHECKING

from app.config import Settings
from app.fetching.core import StudyCollection
from app.fetching.registry import PUBLISHER_FETCHERS

if TYPE_CHECKING:
    from app.fetching import BasePublisherFetcher


class FullTextFetcherError(Exception):
    """Custom exception for FullTextFetcher errors."""


class FullTextFetcher:
    """
    A class to fetch full-text articles from various publishers.

    Implemented with the Strategy design pattern to delegate fetching
    to publisher-specific fetchers.
    """

    def __init__(self, settings: Settings, timeout: int = 300) -> None:
        """
        Initialise the FullTextFetcher.

        Args:
            settings (Settings): The settings to use for the fetcher.
            timeout (int, optional): The timeout for requests. Defaults to 300.

        """
        self.settings = settings
        self.timeout = timeout
        self.fetchers: dict[str, BasePublisherFetcher] = {
            name: fetcher_class(settings)
            for name, fetcher_class in PUBLISHER_FETCHERS.items()
        }

    @staticmethod
    def format_identifiers_for_uri(url_entity: str) -> str:
        """
        Format identifiers for use in URLs and file paths.

        Args:
            url_entity (str): The entity to format.

        Returns:
            str: The formatted entity.

        """
        return url_entity.replace("/", "%2F")

    async def fetch(
        self,
        publisher_name: str,
        study_collection: StudyCollection,
        output_directory: Path,
    ) -> None:
        """
        Fetch full-text articles from the specified publisher.

        Args:
            publisher_name (str): The name of the publisher.
            study_collection (StudyCollection): A collection of studies.
            output_directory (Path): The directory to save the fetched articles.

        """
        fetcher = self.fetchers.get(publisher_name)
        if not fetcher:
            error_message = f"Unknown publisher: {publisher_name}"
            raise FullTextFetcherError(error_message)

        await fetcher.fetch_full_text(study_collection, output_directory)
