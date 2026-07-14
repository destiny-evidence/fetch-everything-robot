"""Module to define full text fetchers per publisher."""

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import AnyUrl

from fer.fetching.core import DOIStudyCollection, RetrievedFullText


class BasePublisherFetcher(ABC):
    """Abstract base class for publisher fetchers."""

    @abstractmethod
    async def download_one_pdf(
        self,
        pdf_url: AnyUrl,
        filepath: Path,
        headers: dict | None = None,
    ) -> Path | None:
        """
        Download a pdf for a pdf_url associated with a single `DOIStudy`.

        Args:
            pdf_url (AnyUrl): The URL of the PDF to download.
            filepath (Path): Output file path.
            headers (dict | None, optional):
                Optional headers to include in the request. Defaults to None.

        Returns:
            Path | None: The path to the downloaded PDF or None if download failed.

        """

    @abstractmethod
    async def fetch_many_full_texts(
        self,
        study_collection: DOIStudyCollection,
        output_directory: Path,
        **kwargs: object,
    ) -> list[RetrievedFullText]:
        """
        Fetch full text for a given DOIStudyCollection and save to output_directory.

        Args:
            study_collection (DOIStudyCollection): The study collection for which
                to fetch the full text.
            output_directory (Path): The directory where the full text should be saved.

        Returns:
            list[RetrievedFullText]: A list of RetrievedFullText instances
                representing the saved full text files.

        """
