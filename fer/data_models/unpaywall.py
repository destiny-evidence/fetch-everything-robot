"""Config constants for Unpaywall API."""

from pydantic import HttpUrl

from fer.data_models.generic import APIConfig, FullTextUnpackStrategy, QueryType


def get_unpaywall_api_config() -> APIConfig:
    """
    Define and return the Unpaywall API configuration.

    Returns:
        APIConfig: The configuration for the CrossRef API.

    """
    unpaywall_unpack_strategy = FullTextUnpackStrategy(
        source="unpaywall",
        doi_strategy=["doi"],
        pdf_link_strategy=["best_oa_location", "url_for_pdf"],
        xml_strategy=None,
    )
    return APIConfig(
        name="unpaywall",
        url=HttpUrl("https://api.unpaywall.org/v2/"),
        require_api_key=False,
        query_type=QueryType.BATCH,
        unpack_strategy=unpaywall_unpack_strategy,
    )
