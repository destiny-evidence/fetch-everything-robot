"""tests for the core fetch_abstract module in app/fetch_abstract.py."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import AnyUrl

from app.fetch_fulltext import FullTextFetcher, prepare_api_config


def test_prepare_api_config_success(
    scopus_api_config_valid_batch,
    openalex_api_config_valid_batch,
    external_api_priorities,
    test_settings,
):
    configs = [
        scopus_api_config_valid_batch,
        openalex_api_config_valid_batch,
    ]
    result = prepare_api_config(
        configs,
        test_settings,
        external_api_priority_batch=external_api_priorities["batch"],
    )
    batch_results = result["batch"]
    assert set(batch_results.keys()) == {"OPENALEX", "SCOPUS"}
    assert batch_results["SCOPUS"].headers["X-API-Key"] == "dummy_scopus_key"
    assert batch_results["SCOPUS"].headers["X-Inst-Token"] == "dummy_inst_token"
    assert batch_results["OPENALEX"].headers == {"Accept": "application/json"}
    assert batch_results["OPENALEX"].api_key_env_var_name is None


def test_prepare_api_config_missing_key(
    external_api_priorities, invalid_api_config, test_settings
):
    configs = [invalid_api_config]
    result = prepare_api_config(
        configs,
        test_settings,
        external_api_priority_batch=external_api_priorities["batch"],
    )
    for value in result.values():
        assert value == {}


@pytest.mark.parametrize(
    "api_config_fixture",
    [
        {
            "batch": "scopus_api_config_valid_batch",
        },
        {
            "batch": "openalex_api_config_valid_batch",
        },
    ],
)
def test_abstract_fetcher_init_logs(request, api_config_fixture, test_settings):
    api_config_batch = request.getfixturevalue(api_config_fixture["batch"])
    with patch("app.fetch_fulltext.logger") as mock_logger:
        master_api_config = prepare_api_config([api_config_batch], test_settings)
        fetcher = FullTextFetcher(master_api_config)
        mock_logger.info.assert_any_call(
            "Available external APIs in descending order of priority:"
        )
        for external_api_name in master_api_config["batch"]:
            assert external_api_name == api_config_batch.name.value.upper()
        assert fetcher.timeout == 60


@pytest.mark.parametrize(
    "api_config_fixture",
    [
        {
            "batch": "scopus_api_config_valid_batch",
        },
        {
            "batch": "openalex_api_config_valid_batch",
        },
    ],
)
def test_fetch_success(request, api_config_fixture, test_settings):
    api_config_batch = request.getfixturevalue(api_config_fixture["batch"])
    fetcher = FullTextFetcher(
        master_api_config=prepare_api_config([api_config_batch], test_settings)
    )
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"foo": "bar"}

    test_url = AnyUrl("http://test")
    with patch("httpx.Client.get", return_value=mock_response) as mock_get:
        result = fetcher.fetch(test_url, {}, {})
        assert result == {"foo": "bar"}
        mock_get.assert_called_once()


@pytest.mark.parametrize(
    "api_config_fixture",
    [
        {
            "batch": "scopus_api_config_valid_batch",
        },
        {
            "batch": "openalex_api_config_valid_batch",
        },
    ],
)
def test_fetch_http_error(request, api_config_fixture, test_settings):
    api_config_batch = request.getfixturevalue(api_config_fixture["batch"])
    fetcher = FullTextFetcher(
        master_api_config=prepare_api_config([api_config_batch], test_settings)
    )
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPError("fail")
    test_url = AnyUrl("http://test")
    with (
        patch("httpx.Client.get", return_value=mock_response),
        pytest.raises(httpx.HTTPError),
    ):
        fetcher.fetch(test_url, {}, {})


def test_traverse_non_dict_returns_none():
    # Should return None if input is not a dict
    result = FullTextFetcher._traverse("notadict", ["foo"])  # noqa: SLF001
    assert result is None


def test_traverse_missing_key_returns_none():
    # Should return None if key is missing
    d = {"foo": {"bar": 1}}
    result = FullTextFetcher._traverse(d, ["foo", "baz"])  # noqa: SLF001
    assert result is None


def test_clean_full_text_string_removes_all_tags():
    raw = "<jats:p>This is a <b>test</b> abstract.</jats:p>"
    cleaned = FullTextFetcher.clean_full_text_string(raw)
    assert cleaned == "This is a test abstract."


def test_clean_abstract_string_fallback_regex():
    # invalid XML, should trigger the regex fallback
    raw = "<notclosed>This is broken"
    cleaned = FullTextFetcher.clean_full_text_string(raw)
    assert cleaned == "This is broken"


def test_process_doi_remove_url():
    raw = "https://doi.org/10.1109/pssgt64932.2025.11033854"
    cleaned = FullTextFetcher.process_doi(raw)
    assert cleaned == "10.1109/pssgt64932.2025.11033854"


def test_process_doi_tolower():
    raw = "10.1109/PSSGT64932.2025.11033854"
    cleaned = FullTextFetcher.process_doi(raw)
    assert cleaned == "10.1109/pssgt64932.2025.11033854"
