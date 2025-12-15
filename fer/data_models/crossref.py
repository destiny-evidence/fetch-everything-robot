"""Config constants for CrossRef API."""

from fer.data_models.generic import APIConfig, FullTextUnpackStrategy, QueryType


def get_crossref_api_config() -> APIConfig:
    """
    Define and return the CrossRef API configuration.

    Returns:
        APIConfig: The configuration for the CrossRef API.

    """
    crossref_unpack_strategy = FullTextUnpackStrategy(
        source="crossref",
        doi_strategy=["doi"],
        pdf_link_strategy=["message", "link"],
        xml_strategy=None,
    )
    return APIConfig(
        name="crossref",
        url="https://api.crossref.org",
        require_api_key=False,
        query_type=QueryType.BATCH,
        unpack_strategy=crossref_unpack_strategy,
    )
