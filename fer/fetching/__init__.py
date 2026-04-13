"""Module to define full text fetchers per publisher."""

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import AnyUrl

from fer.fetching.core import RetrievedFullText, StudyCollection


class BasePublisherFetcher(ABC):
    """Abstract base class for publisher fetchers."""

    @abstractmethod
    async def download_one_pdf_by_url(
        self,
        pdf_url: AnyUrl,
        filepath: Path,
        headers: dict | None = None,
    ) -> Path | None:
        """
        Download a pdf for a pdf_url associated with a single `Study`.

        Args:
            pdf_url (AnyUrl): The URL of the PDF to download.
            filepath (Path): Output file path.
            headers (dict | None, optional):
                Optional headers to include in the request. Defaults to None.

        Returns:
            Path | None: The path to the downloaded PDF or None if download failed.

        """

    @abstractmethod
    async def download_one_pdf_by_id(
        self, pdf_doi: str, filepath: Path, headers: dict | None = None
    ) -> Path | None:
        """
        Download a pdf for a pdf_id (right now, DOI)
        associated with a single study.

        Args:
            pdf_doi (str): the Study's DOI.
            filepath (Path): Output file path.
            headers (dict | None, optional):
                Optional headers to include in the request. Defaults to None.


        Returns:
            Path | None: Path to the downloaded PDF.

        """

    @abstractmethod
    async def fetch_many_full_texts(
        self,
        study_collection: StudyCollection,
        output_directory: Path,
        **kwargs: object,
    ) -> list[RetrievedFullText]:
        """
        Fetch full text for a given StudyCollection and save them to output_directory.

        Args:
            study_collection (StudyCollection): The study collection for which to fetch
                the full text.
            output_directory (Path): The directory where the full text should be saved.

        Returns:
            list[RetrievedFullText]: A list of RetrievedFullText instances
                representing the saved full text files.

        """
