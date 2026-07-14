"""tests for the core fetch_fulltext module in fer/fetch_fulltext.py."""

import httpx2
import pytest

from fer.data_models.generic import prepare_api_config
from fer.fetch_fulltext import FullTextBatchFetcher, ZeroFullTextsGeneratedError
from fer.fetching.core import BaseAuthError
from fer.fetching.fetchers import FullTextFetcher


@pytest.mark.parametrize(
    "expected_headers",
    [
        {
            "SCOPUS": {
                "X-API-Key": "dummy_scopus_key",
                "X-Inst-Token": "dummy_inst_token",
            }
        },
        {"OPENALEX": {"Accept": "application/json"}},
        {"CROSSREF": {"Accept": "application/json"}},
        {"UNPAYWALL": {"Accept": "application/json"}},
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


def test_full_text_fetcher_init_logs(
    mocker, request, test_available_api_configs, test_settings, test_publisher_dict
):
    mock_logger = mocker.patch("fer.fetch_fulltext.logger")
    all_api_configs = prepare_api_config(test_available_api_configs, test_settings)
    fetcher = FullTextBatchFetcher(test_settings, all_api_configs, test_publisher_dict)
    mock_logger.info.assert_any_call(
        "Available external APIs in descending order of priority:"
    )
    assert all(
        external_api_name.upper() == api_config.name.value.upper()
        for external_api_name, api_config in zip(
            all_api_configs["fulltext"].keys(),
            test_available_api_configs,
            strict=False,
        )
    )

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
    mock_response.json = mocker.MagicMock(return_value={"foo": "bar"})

    mock_get = mocker.patch("httpx2.AsyncClient.get", return_value=mock_response)
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
    mock_response.raise_for_status.side_effect = httpx2.HTTPError("fail")
    mocker.patch("httpx2.AsyncClient.get", return_value=mock_response)
    with (
        pytest.raises(httpx2.HTTPError),
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
async def test_get_many_fulltext_pdfs_cycling_apis_adds_only_non_none_fulltext_paths(
    mocker,
    test_prepared_available_api_configs,
    test_settings,
    test_study_collection,
    test_publisher_dict,
    test_fetch_results_single_success,
    test_fetch_results_single_failure,
):
    n_available_api_configs = len(test_prepared_available_api_configs["fulltext"])
    expected_fetch_results_array = [test_fetch_results_single_success] + [
        test_fetch_results_single_failure
    ] * (n_available_api_configs - 1)

    unique_expected_successes = len(
        [
            result[0]
            for result in expected_fetch_results_array
            if result[0].fulltext_path is not None
        ]
    )
    expected_failure_array = [
        result[0]
        for result in expected_fetch_results_array
        if result[0].fulltext_path is None
    ]
    unique_expected_failures = len(
        {result.doi: result for result in expected_failure_array}
    )
    mock_fetch = mocker.patch(
        "fer.fetching.fetchers.FullTextFetcher.fetch",
        side_effect=expected_fetch_results_array,
    )

    fetcher = FullTextBatchFetcher(
        test_settings, test_prepared_available_api_configs, test_publisher_dict
    )

    results = await fetcher.get_many_fulltext_pdfs_cycling_apis(test_study_collection)

    assert mock_fetch.call_count == len(
        test_prepared_available_api_configs["fulltext"]
    ), (
        "Expect that the fetcher is called for each available API until all fulltexts"
        " are either found or all APIs are exhausted."
    )

    found_fulltext = [result for result in results if result.fulltext_path is not None]
    not_found_fulltext = [result for result in results if result.fulltext_path is None]

    assert len(found_fulltext) == unique_expected_successes
    assert len(not_found_fulltext) == unique_expected_failures

    assert all(
        found_result.fulltext_path
        == str(test_fetch_results_single_success[0].fulltext_path)
        for found_result in found_fulltext
    )
    assert all(
        found_result.source in test_prepared_available_api_configs["fulltext"]
        for found_result in found_fulltext
    )
    assert all(
        not_found_result.fulltext_path is None
        for not_found_result in not_found_fulltext
    )
    assert all(
        not_found_result.source is None for not_found_result in not_found_fulltext
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
