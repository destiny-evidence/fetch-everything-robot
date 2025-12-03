"""Registry of Publisher Fetchers."""

from app.config import Settings
from app.fetching.crossref import CrossrefFetcher
from app.fetching.elsevier import ElsevierFetcher
from app.fetching.fetchers import BasePublisherFetcher
from app.fetching.unpaywall import UnpaywallFetcher


def get_publisher_fetcher_registry(
    settings: Settings,
) -> dict[str, BasePublisherFetcher]:
    """
    Get a registry of available publisher fetchers.

    Args:
        settings (Settings): The settings to use for the fetchers.

    Returns:
        dict[str, BasePublisherFetcher]: A dictionary mapping publisher names to their
            corresponding fetcher instances.

    """
    return {
        "elsevier": ElsevierFetcher(settings),
        "scopus": ElsevierFetcher(settings),
        "unpaywall": UnpaywallFetcher(settings),
        "crossref": CrossrefFetcher(settings),
    }
