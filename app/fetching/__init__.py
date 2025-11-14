"""Module to define full text fetchers per publisher."""

from abc import ABC, abstractmethod
from pathlib import Path

from app.fetching.core import StudyCollection


class BasePublisherFetcher(ABC):
    """Abstract base class for publisher fetchers."""

    @abstractmethod
    async def fetch_full_text(
        self,
        study_collection: StudyCollection,
        output_directory: Path,
    ) -> None:
        """
        Fetch the full text for a given study and save it to output_directory.

        Args:
            study_collection (StudyCollection): The study collection for which to fetch
                the full text.
            output_directory (Path): The directory where the full text should be saved.

        """
