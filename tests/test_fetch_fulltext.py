"""tests for the core fetch_fulltext module in fer/fetch_fulltext.py."""

import httpx
import pytest

from fer.data_models.generic import prepare_api_config
from fer.fetch_fulltext import FullTextBatchFetcher, ZeroFullTextsGeneratedError
from fer.fetching.core import BaseAuthError
from fer.fetching.fetchers import FullTextFetcher


# TODO @harryjmoss: Re-Enable when multiple API configs are supported
# https://github.com/destiny-evidence/fetch-everything-robot/issues/9
@pytest.mark.parametrize(
    "expected_headers",
    [
        {
            "SCOPUS": {
                "X-API-Key": "dummy_scopus_key",
                "X-Inst-Token": "dummy_inst_token",
            }
        },
        # {"OPENALEX": {"Accept": "application/json"}},
    ],
)
def test_prepare_api_config_success(
    expected_headers,
    test_available_api_configs,
    external_api_priorities,
    test_settings,
):
    result = prepare_api_config(
        test_available_api_configs,
        test_settings,
        external_api_priority=external_api_priorities["fulltext"],
    )
    fulltext_results = result["fulltext"]
    for source, headers in expected_headers.items():
        if source in fulltext_results:
            for header, value in headers.items():
                assert fulltext_results[source].headers[header] == value


def test_prepare_api_config_missing_key(
    external_api_priorities, invalid_api_config, test_settings
):
    configs = [invalid_api_config]
    result = prepare_api_config(
        configs,
        test_settings,
        external_api_priority=external_api_priorities["fulltext"],
    )
    for value in result.values():
        assert value == {}


@pytest.mark.parametrize(
    "api_config_fixture",
    [
        {
            "fulltext": "scopus_api_config_valid_batch",
        },
    ],
)
def test_full_text_fetcher_init_logs(
    mocker, request, api_config_fixture, test_settings, test_publisher_dict
):
    api_config_fulltext = request.getfixturevalue(api_config_fixture["fulltext"])
    mock_logger = mocker.patch("fer.fetch_fulltext.logger")
    all_api_configs = prepare_api_config([api_config_fulltext], test_settings)
    fetcher = FullTextBatchFetcher(test_settings, all_api_configs, test_publisher_dict)
    mock_logger.info.assert_any_call(
        "Available external APIs in descending order of priority:"
    )
    for external_api_name in all_api_configs["fulltext"]:
        assert external_api_name == api_config_fulltext.name.value.upper()
    assert fetcher.timeout == 60


@pytest.mark.asyncio
async def test_fetch_success(
    mocker,
    test_settings,
    test_publisher_dict,
    test_study_collection,
):
    fetcher = FullTextFetcher(test_settings, publisher_dict=test_publisher_dict)
    mock_response = mocker.MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json = mocker.AsyncMock(return_value={"foo": "bar"})

    mock_get = mocker.patch("httpx.AsyncClient.get", return_value=mock_response)
    result = await fetcher.fetch(
        "test_publisher", test_study_collection, output_directory=None
    )
    assert result == {"foo": "bar"}
    mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_http_error(
    mocker, test_settings, test_publisher_dict, test_study_collection
):
    fetcher = FullTextFetcher(
        test_settings,
        test_publisher_dict,
    )
    mock_response = mocker.MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPError("fail")
    mocker.patch("httpx.AsyncClient.get", return_value=mock_response)
    with (
        pytest.raises(httpx.HTTPError),
    ):
        await fetcher.fetch(
            "test_publisher", test_study_collection, output_directory=None
        )


@pytest.mark.xfail(reason="Not implemented yet - need to adapt for full text fetcher")
def test_traverse_non_dict_returns_none():
    # Should return None if input is not a dict
    result = FullTextFetcher._traverse("notadict", ["foo"])
    assert result is None


@pytest.mark.xfail(reason="Not implemented yet - need to adapt for full text fetcher")
def test_traverse_missing_key_returns_none():
    # Should return None if key is missing
    d = {"foo": {"bar": 1}}
    result = FullTextFetcher._traverse(d, ["foo", "baz"])
    assert result is None


def test_clean_full_text_string_removes_all_tags():
    raw = "<jats:p>This is a <b>test</b> fulltext.</jats:p>"
    cleaned = FullTextBatchFetcher.clean_full_text_string(raw)
    assert cleaned == "This is a test fulltext."


def test_clean_full_text_string_fallback_regex():
    # invalid XML, should trigger the regex fallback
    raw = "<notclosed>This is broken"
    cleaned = FullTextBatchFetcher.clean_full_text_string(raw)
    assert cleaned == "This is broken"


def test_process_doi_remove_url():
    raw = "https://doi.org/10.1109/pssgt64932.2025.11033854"
    cleaned = FullTextBatchFetcher.process_doi(raw)
    assert cleaned == "10.1109/pssgt64932.2025.11033854"


def test_process_doi_tolower():
    raw = "10.1109/PSSGT64932.2025.11033854"
    cleaned = FullTextBatchFetcher.process_doi(raw)
    assert cleaned == "10.1109/pssgt64932.2025.11033854"


@pytest.mark.asyncio
async def test_get_many_fulltext_pdfs_cycling_apis_adds_only_non_none_pdf_paths(
    mocker,
    test_settings,
    test_study_collection,
    test_publisher_dict,
    scopus_api_config_valid_batch,
    temporary_test_file,
):
    test_publisher_name = "test_publisher"
    all_api_configs = {"fulltext": {test_publisher_name: scopus_api_config_valid_batch}}

    doi1 = test_study_collection.studies[0].doi.identifier
    doi2 = test_study_collection.studies[1].doi.identifier

    expected_fulltext_found_result = {doi1: temporary_test_file}
    expected_fulltext_not_found_result = {doi2: None}
    mock_fetch = mocker.patch(
        "fer.fetching.fetchers.FullTextFetcher.fetch",
        side_effect=[
            expected_fulltext_found_result,
            expected_fulltext_not_found_result,
        ],
    )

    fetcher = FullTextBatchFetcher(test_settings, all_api_configs, test_publisher_dict)

    results = await fetcher.get_many_fulltext_pdfs_cycling_apis(test_study_collection)

    mock_fetch.assert_called_once()

    found_fulltext = [
        result for result in results if result["fulltext_path"] is not None
    ]
    not_found_fulltext = [
        result for result in results if result["fulltext_path"] is None
    ]

    assert len(found_fulltext) == len(expected_fulltext_found_result.keys())
    assert len(not_found_fulltext) == len(expected_fulltext_not_found_result.keys())

    assert all(
        found_result["fulltext_path"] == str(temporary_test_file)
        for found_result in found_fulltext
    )
    assert all(
        found_result["source"] == test_publisher_name for found_result in found_fulltext
    )
    assert all(
        not_found_result["fulltext_path"] is None
        for not_found_result in not_found_fulltext
    )
    assert all(
        not_found_result["source"] is None for not_found_result in not_found_fulltext
    )


@pytest.mark.asyncio
async def test_get_many_fulltext_pdfs_cycling_apis_error_with_individual_api(
    mocker,
    test_settings,
    test_study_collection,
    test_publisher_dict,
    scopus_api_config_valid_batch,
    temporary_test_file,
    caplog,
):
    test_publisher_name = "test_publisher"
    all_api_configs = {"fulltext": {test_publisher_name: scopus_api_config_valid_batch}}

    mocker.patch.object(
        test_publisher_dict[test_publisher_name],
        "fetch_many_full_texts",
        side_effect=BaseAuthError("Authentication failed"),
    )
    fetcher = FullTextBatchFetcher(test_settings, all_api_configs, test_publisher_dict)

    with caplog.at_level("INFO"), pytest.raises(ZeroFullTextsGeneratedError):
        await fetcher.get_many_fulltext_pdfs_cycling_apis(test_study_collection)

    assert "Authentication error for publisher" in caplog.text
