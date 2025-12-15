"""Config constants for OpenAlex API using batch requests of up to 50 DOIs."""

from fer.config import Settings
from fer.data_models.generic import APIConfig, FullTextUnpackStrategy, QueryType


def get_openalex_api_config(settings: Settings) -> APIConfig:
    """
    Define and return the OpenAlex API configuration.

    Note that OpenAlex allows up to 50 DOIs per request.

    Args:
        settings (Settings): The application settings containing configuration values.

    Returns:
        APIConfig: The configuration for the OpenAlex API.

    """
    openalex_url = "https://api.openalex.org/works/"
    openalex_query_params = {"mailto": settings.mailto}  # type: dict
    openalex_headers = {
        "User-Agent": "destiny-project-ucl",
        "Accept": "application/json",
        "api_key": "",
    }
    openalex_unpack_strategy = FullTextUnpackStrategy(
        source="openalex",
        doi_strategy=["doi"],
        pdf_link_strategy=["primary_location", "pdf_url"],
        xml_strategy=None,
    )
    return APIConfig(
        name="openalex",
        url=openalex_url,
        require_api_key=True,
        api_key_env_var_name="openalex_key",  # pragma: allowlist secret
        api_key_placement="api_key",  # pragma: allowlist secret
        headers=openalex_headers,
        query_type=QueryType.BATCH,
        query_params=openalex_query_params,
        unpack_strategy=openalex_unpack_strategy,
    )
