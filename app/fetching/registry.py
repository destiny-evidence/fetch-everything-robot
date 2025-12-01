"""Registry of Publisher Fetchers."""

from app.fetching.crossref import CrossrefFetcher
from app.fetching.elsevier import ElsevierFetcher
from app.fetching.unpaywall import UnpaywallFetcher

PUBLISHER_FETCHERS = {
    "elsevier": ElsevierFetcher,
    "scopus": ElsevierFetcher,
    "unpaywall": UnpaywallFetcher,
    "crossref": CrossrefFetcher,
}
