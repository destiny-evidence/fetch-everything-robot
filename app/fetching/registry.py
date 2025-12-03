"""Registry of Publisher Fetchers."""

from app.config import get_settings
from app.fetching.crossref import CrossrefFetcher
from app.fetching.elsevier import ElsevierFetcher
from app.fetching.unpaywall import UnpaywallFetcher

settings = get_settings()
PUBLISHER_FETCHERS = {
    "elsevier": ElsevierFetcher(settings),
    "scopus": ElsevierFetcher(settings),
    "unpaywall": UnpaywallFetcher(settings),
    "crossref": CrossrefFetcher(settings),
}
