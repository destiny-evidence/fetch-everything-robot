import pytest

from app.data_models.generic import (
    APIConfig,
    ExternalAPI,
    ExternalAPIPriority,
    FullTextUnpackStrategy,
    QueryType,
)


@pytest.fixture
def external_api_priorities() -> dict[str, ExternalAPIPriority]:
    """
    Fixture to provide the external API priority configuration.

    Returns:
        dict[str, ExternalAPIPriority]:
            Dictionary of the configured external API priorities.

    """
    return {
        "batch": ExternalAPIPriority(
            name="batch",
            priorities={
                ExternalAPI.OPENALEX: 1,
                ExternalAPI.SCOPUS: 2,
            },
        ),
    }


@pytest.fixture
def invalid_api_config() -> APIConfig:
    """
    Provide an invalid API configuration.

    Returns:
        APIConfig: An APIConfig instance with invalid settings.

    """
    return APIConfig(
        name=ExternalAPI.SCOPUS,
        url="http://fake-api.com",
        require_api_key=True,
        api_key_env_var_name="FAKE_API_KEY",  # pragma: allowlist secret
        api_key_placement="api_key_placement",  # pragma: allowlist secret
        query_type=QueryType.BATCH,
        query_params={"param1": "value1"},
        headers={"Authorization": "Bearer fake_token", "api_key_placement": ""},
        unpack_strategy=FullTextUnpackStrategy(
            source=ExternalAPI.SCOPUS,
            strategy=["data", "abstract"],
        ),
    )
