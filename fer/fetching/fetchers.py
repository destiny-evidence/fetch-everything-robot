"""Define fetchers to retrieve full-text articles from various sources."""

from pathlib import Path

from fer.config import Settings
from fer.fetching import BasePublisherFetcher
from fer.fetching.core import (
    BaseAuthError,
    DOIStudyCollection,
    OpenAlexStudyCollection,
    RetrievedFullText,
)
from fer.fetching.elsevier import ElsevierFetcher
from fer.fetching.openalex import OpenalexFetcher


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
        study_collection: DOIStudyCollection | OpenAlexStudyCollection,
        output_directory: Path,
        *,
        get_pdf: bool = True,
        get_xml: bool = False,
    ) -> list[RetrievedFullText]:
        """
        Fetch full-text articles from the specified publisher.

        Args:
            publisher_name (str): The name of the publisher.
            study_collection (DOIStudyCollection | OpenAlexStudyCollection):
                A collection of studies.
            output_directory (Path): The directory to save the fetched articles.
            get_pdf (bool, optional): Whether to fetch PDF files. Defaults to True.
            get_xml (bool, optional): Whether to fetch XML files. Defaults to False.

        Returns:
            list[RetrievedFullText]: A list of RetrievedFullText instances
                representing the saved full text files.

        """
        fetcher = self.fetchers.get(publisher_name.lower())
        output_directory.mkdir(parents=True, exist_ok=True)
        if not fetcher:
            error_message = f"Unknown publisher: {publisher_name}"
            raise FullTextFetcherError(error_message)
        try:
            if isinstance(fetcher, OpenalexFetcher):
                return await fetcher.fetch_many_full_texts(
                    study_collection, output_directory
                )
            if not isinstance(study_collection, DOIStudyCollection):
                error_message = (
                    f"Fetcher for '{publisher_name}' requires a "
                    "DOI-based DOIStudyCollection."
                )
                raise FullTextFetcherError(error_message)
            if isinstance(fetcher, ElsevierFetcher):
                return await fetcher.fetch_many_full_texts(
                    study_collection,
                    output_directory,
                    get_pdf=get_pdf,
                    get_xml=get_xml,
                )
            return await fetcher.fetch_many_full_texts(
                study_collection, output_directory
            )
        except BaseAuthError as auth_error:
            error_message = (
                f"Authentication error for publisher {publisher_name}: {auth_error}"
            )
            raise FullTextFetcherError(error_message) from auth_error
