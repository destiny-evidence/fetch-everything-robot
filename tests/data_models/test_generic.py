"""tests for generic data models in app/data_models/generic.py."""

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.data_models.generic import (
    APIConfig,
    APIKeyNotPresentError,
    ExternalAPI,
    ExternalAPIPriority,
    FullTextNotFoundError,
    FullTextUnpackError,
    prepare_api_config,
)


def test_custom_exceptions():
    error_msg = "API key missing"
    with pytest.raises(APIKeyNotPresentError):
        raise APIKeyNotPresentError(error_msg)
    error_msg = "Unpack failed"
    with pytest.raises(FullTextUnpackError):
        raise FullTextUnpackError(error_msg)
    error_msg = "Not found"
    with pytest.raises(FullTextNotFoundError):
        raise FullTextNotFoundError(error_msg)


def test_external_api_enum():
    assert ExternalAPI.CROSSREF == "crossref"
    assert ExternalAPI.UNPAYWALL == "unpaywall"
    assert ExternalAPI.SCOPUS == "scopus"

    assert set(ExternalAPI) == {
        ExternalAPI.CROSSREF,
        ExternalAPI.UNPAYWALL,
        ExternalAPI.SCOPUS,
    }


def test_external_api_priority_model():
    model = ExternalAPIPriority(
        name="test_priority",
        priorities={
            ExternalAPI.CROSSREF: 1,
            ExternalAPI.UNPAYWALL: 2,
            ExternalAPI.SCOPUS: 3,
        },
    )
    assert model.priorities[ExternalAPI.CROSSREF] == 1
    assert model.priorities[ExternalAPI.UNPAYWALL] == 2
    assert model.priorities[ExternalAPI.SCOPUS] == 3


@pytest.mark.parametrize(
    (
        "api_config_fixture",
        "expected_headers",
        "expected_name",
        "expected_url",
        "expected_query_params",
        "expected_unpack_source",
        "expected_unpack_pdf_link_strategy",
        "expected_unpack_xml_strategy",
    ),
    [
        (
            "scopus_api_config_valid_batch",
            {"X-API-Key": ""},
            ExternalAPI.SCOPUS,
            "https://api.example.com/",
            {},
            ExternalAPI.SCOPUS,
            ["search-results", "entry", "pdf_url"],
            ["search-results", "entry", "xml"],
        ),
        # TODO @harryjmoss: Re-Enable when OpenAlex fetcher is implemented
        # https://github.com/destiny-evidence/fetch-everything-robot/issues/9
        # (
        #     "openalex_api_config_valid_batch",
        #     {"Accept": "application/json"},
        #     ExternalAPI.CROSSREF,
        #     "https://api.example.com/",
        #     {},
        #     ExternalAPI.CROSSREF,
        #     ["message", "pdf_url"],
        #     ["message", "xml"],
        # ),
    ],
)
def test_api_config_validator_success(
    request,
    api_config_fixture,
    expected_headers,
    expected_name,
    expected_url,
    expected_query_params,
    expected_unpack_source,
    expected_unpack_pdf_link_strategy,
    expected_unpack_xml_strategy,
):
    api_config = request.getfixturevalue(api_config_fixture)
    assert api_config.headers == expected_headers
    assert api_config.name == expected_name
    assert str(api_config.url) == expected_url
    assert api_config.query_params == expected_query_params
    assert api_config.unpack_strategy.source == expected_unpack_source
    assert (
        api_config.unpack_strategy.pdf_link_strategy
        == expected_unpack_pdf_link_strategy
    )
    assert api_config.unpack_strategy.xml_strategy == expected_unpack_xml_strategy


@pytest.mark.parametrize(
    ("api_config_fixture"),
    [
        ("scopus_api_config_valid_batch"),
        # TODO @harryjmoss: Re-Enable when OpenAlex fetcher is implemented
        # https://github.com/destiny-evidence/fetch-everything-robot/issues/9
        # ("openalex_api_config_valid_batch"),
    ],
)
def test_api_config_validator_failure(request, api_config_fixture, monkeypatch):
    api_config = request.getfixturevalue(api_config_fixture)
    bad_fields = [
        ("headers", None),
        ("unpack_strategy", "not_a_strategy"),
        ("name", "not_an_enum"),
    ]
    for field, bad_value in bad_fields:
        broken = api_config.model_copy()
        setattr(broken, field, bad_value)
        with pytest.raises(ValidationError):
            APIConfig.model_validate(broken.__dict__)


@pytest.mark.parametrize(
    ("api_config_fixture", "expected_key", "expected_value"),
    [
        ("scopus_api_config_valid_batch", "X-API-Key", "dummy_scopus_key"),
        # TODO @harryjmoss: Re-Enable when OpenAlex fetcher is implemented
        # https://github.com/destiny-evidence/fetch-everything-robot/issues/9
        # ("openalex_api_config_valid_batch", None, None),
    ],
)
def test_api_config_init_api_key_success(
    request, api_config_fixture, expected_key, expected_value, test_settings
):
    api_config = request.getfixturevalue(api_config_fixture)

    api_config.init_api_key(test_settings)
    if expected_key:
        assert api_config.headers[expected_key] == expected_value
    else:
        # For APIs that do not require a key, headers should remain unchanged
        assert "Accept" in api_config.headers or api_config.headers == {}


def test_api_config_init_api_key_missing(invalid_api_config):
    settings = get_settings()
    with pytest.raises(APIKeyNotPresentError):
        invalid_api_config.init_api_key(settings)


@pytest.mark.parametrize(
    ("api_config_fixture", "query"),
    [
        ("scopus_api_config_valid_batch", "test_DOI_1"),
    ],
)
def test_api_config_populate_query_scopus(request, api_config_fixture, query):
    api_config = request.getfixturevalue(api_config_fixture)
    expected_url = f"{api_config.url}{query}"
    request_params = api_config.populate_query(query)
    assert (
        str(request_params["url"]) == expected_url
    ), "URL should append DOI to base URL."


@pytest.mark.xfail(reason="OpenAlex fetcher not yet implemented")
@pytest.mark.parametrize(
    ("api_config_fixture", "query"),
    [
        ("openalex_api_config_valid_batch", ["test_DOI_1", "test_DOI_2"]),
    ],
)
def test_api_config_populate_query_openalex(request, api_config_fixture, query):
    api_config = request.getfixturevalue(api_config_fixture)
    expected_url = f"{api_config.url}?filter=doi:{'|'.join(query)}"
    url = api_config.populate_query(query)["url"]
    assert (
        url == expected_url
    ), "URL should include DOIs as filter parameters, separated by |."


def test_prepare_api_config_key_type(
    test_settings,
    test_available_api_configs,
    external_api_priorities,
):
    result = prepare_api_config(
        api_configs=test_available_api_configs,
        settings=test_settings,
        external_api_priority=external_api_priorities["fulltext"],
    )
    expected_keys = [config.name.name for config in test_available_api_configs]

    assert set(result["fulltext"].keys()) == set(expected_keys)


def test_prepare_api_config_init_api_key_called_correctly(
    test_settings,
    test_available_api_configs,
    external_api_priorities,
):
    all_results = prepare_api_config(
        api_configs=test_available_api_configs,
        settings=test_settings,
        external_api_priority=external_api_priorities["fulltext"],
    )
    results = all_results["fulltext"]

    assert all(
        config.headers == results[config.name.name].headers
        for config in test_available_api_configs
    )
