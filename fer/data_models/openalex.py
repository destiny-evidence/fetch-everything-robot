"""Config constants for OpenAlex API using batch requests of up to 50 DOIs."""

from fer.config import Settings
from fer.data_models.generic import APIConfig, FullTextUnpackStrategy, QueryType


def get_openalex_batch_api_config(settings: Settings) -> APIConfig:
    """
    Define and return the OpenAlex batch API configuration.

    Note that OpenAlex allows up to 50 DOIs per request.

    Args:
        settings (Settings): The application settings containing configuration values.

    Returns:
        APIConfig: The configuration for the OpenAlex batch API.

    """
    openalex_url = "https://api.openalex.org/works/"
    openalex_query_params = {"mailto": settings.mailto}  # type: dict
    openalex_headers = {
        "User-Agent": "destiny-project-ucl",
        "Accept": "application/json",
    }
    openalex_unpack_strategy = FullTextUnpackStrategy(
        source="openalex",
        doi_strategy="metadata_field",
        pdf_link_strategy=["primary_location", "url"],
        xml_strategy=None,
    )
    return APIConfig(
        name="openalex",
        url=openalex_url,
        require_api_key=True,
        api_key_env_var_name="openalex_key",  # pragma: allowlist secret
        api_key_placement=None,
        headers=openalex_headers,
        query_type=QueryType.BATCH,
        query_params=openalex_query_params,
        unpack_strategy=openalex_unpack_strategy,
    )
