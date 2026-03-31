"""Unit tests for fer/fetching/openalex.py."""

import pytest
from httpx import HTTPError, Response

from fer.fetching.core import FullTextStreamError
from fer.fetching.openalex import OpenalexFetcher


@pytest.fixture
def fetcher(test_settings):
    return OpenalexFetcher(settings=test_settings, wait_time_seconds=0.0)


def test_init(fetcher, test_settings):
    """Test initialization of OpenalexFetcher."""
    assert fetcher.settings == test_settings
    assert fetcher.wait_time_seconds == 0.0
    assert str(fetcher.base_url) == "https://api.openalex.org/works/"
    assert fetcher.query_params == {"mailto": "test@test.com"}
    assert fetcher.headers["User-Agent"] == "destiny-project-ucl"


@pytest.mark.asyncio
async def test_get_work_success(mocker, fetcher):
    """Test _get_work returns JSON data on success."""
    doi = "10.1234/example"
    expected_data = {"id": "W123", "doi": doi}

    mock_response = mocker.MagicMock(spec=Response)
    mock_response.json.return_value = expected_data
    mock_response.raise_for_status = mocker.MagicMock()

    mock_client = mocker.patch("fer.fetching.openalex.AsyncHTTPXRetryClient")
    mock_client_instance = mocker.AsyncMock()
    mock_client.return_value.__aenter__.return_value = mock_client_instance
    mock_client_instance.get.return_value = mock_response

    result = await fetcher._get_work_doi(doi)

    assert result == expected_data
    mock_client_instance.get.assert_called_once()

    call_kwargs = mock_client_instance.get.call_args.kwargs
    assert "10.1234/example" in call_kwargs["url"]
    assert call_kwargs["params"] == fetcher.query_params
    assert call_kwargs["headers"] == fetcher.headers


@pytest.mark.asyncio
async def test_get_work_http_error(mocker, fetcher):
    """Test _get_work raises HTTPError on failure."""
    doi = "10.1234/example"
    mock_client = mocker.patch("fer.fetching.openalex.AsyncHTTPXRetryClient")
    mock_client_instance = mocker.AsyncMock()
    mock_client.return_value.__aenter__.return_value = mock_client_instance

    mock_response = mocker.MagicMock(spec=Response)
    mock_response.raise_for_status.side_effect = HTTPError("oops")
    mock_client_instance.get.return_value = mock_response

    with pytest.raises(HTTPError):
        await fetcher._get_work_doi(doi)


def test_get_pdf_url_success(fetcher):
    """Test _get_pdf_url extracts the correct URL."""
    response_object = {
        "locations": [{"pdf_url": None}, {"pdf_url": "http://example.com/file.pdf"}]
    }
    url = fetcher._get_pdf_url(response_object)
    assert url == "http://example.com/file.pdf"


def test_get_pdf_url_none(fetcher):
    """Test _get_pdf_url returns None when no PDF is available."""
    # scenario 1: locations exist but no pdf_url
    response_object = {"locations": [{"pdf_url": None}]}
    assert fetcher._get_pdf_url(response_object) is None

    # scenario 2: no locations key
    assert fetcher._get_pdf_url({}) is None


@pytest.mark.asyncio
async def test_download_one_pdf(mocker, fetcher, temporary_test_file):
    """Test download_one_pdf calls stream_file correctly."""
    url = "http://example.com/file.pdf"

    mock_stream = mocker.patch(
        "fer.fetching.openalex.stream_file", new_callable=mocker.AsyncMock
    )
    mock_stream.return_value = temporary_test_file
    result = await fetcher.download_one_pdf(url, temporary_test_file)
    assert result == temporary_test_file
    mock_stream.assert_called_once_with(
        url=url, destination=temporary_test_file, headers=None
    )


@pytest.mark.asyncio
async def test_fetch_many_full_texts_success(
    mocker, fetcher, test_study_collection, tmp_path
):
    """Test fetch_many_full_texts successfully downloads PDFs."""
    test_uuids = [study.uid for study in test_study_collection.studies]
    mock_get_work = mocker.patch.object(
        fetcher, "_get_work_doi", new_callable=mocker.AsyncMock
    )
    mock_get_pdf_url = mocker.patch.object(fetcher, "_get_pdf_url")
    mock_download = mocker.patch.object(
        fetcher, "download_one_pdf", new_callable=mocker.AsyncMock
    )
    mock_sleep = mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)

    mock_get_work.side_effect = [{"some": "data"}, {"more": "data"}]
    mock_get_pdf_url.side_effect = [
        "http://example.com/file_one.pdf",
        "http://example.com/file_two.pdf",
    ]
    mock_download.side_effect = [
        tmp_path / f"{test_uuids[0]}.pdf",
        tmp_path / f"{test_uuids[1]}.pdf",
    ]
    results = await fetcher.fetch_many_full_texts(test_study_collection, tmp_path)

    assert all(
        result.doi == study.doi.identifier.lower()
        for result, study in zip(results, test_study_collection.studies, strict=False)
    )
    assert all(
        result.uid == study.uid
        for result, study in zip(results, test_study_collection.studies, strict=False)
    )
    assert all(
        result.fulltext_path == tmp_path / f"{study.uid}.pdf"
        for result, study in zip(results, test_study_collection.studies, strict=False)
    )

    assert mock_get_work.call_count == len(test_study_collection.studies)
    assert mock_download.call_count == len(test_study_collection.studies)
    assert mock_sleep.call_count == len(test_study_collection.studies)
    assert mock_sleep.call_args_list == [mocker.call(0.0), mocker.call(0.0)]


@pytest.mark.asyncio
async def test_fetch_many_full_texts_no_pdf(
    mocker, fetcher, test_study_collection, tmp_path
):
    """Test fetch_many_full_texts handles missing PDF URLs gracefully."""
    mock_get_work = mocker.patch.object(
        fetcher, "_get_work_doi", new_callable=mocker.AsyncMock
    )
    mock_get_pdf_url = mocker.patch.object(fetcher, "_get_pdf_url")
    mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
    mock_get_work.side_effect = [{"some": "data"}, {"more": "data"}]
    mock_get_pdf_url.side_effect = [None, None]
    results = await fetcher.fetch_many_full_texts(test_study_collection, tmp_path)

    assert all(
        result.doi == study.doi.identifier.lower()
        for result, study in zip(results, test_study_collection.studies, strict=False)
    )
    assert all(
        result.uid == study.uid
        for result, study in zip(results, test_study_collection.studies, strict=False)
    )
    assert all(
        result.fulltext_path is None for result in results
    ), "PDF path should be None when no PDF URL is available"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("is_open_access", "expected_oa_status"),
    [
        ("true", True),
        ("false", False),
    ],
)
async def test_fetch_many_full_texts_success_updates_open_access_status(
    mocker,
    fetcher,
    test_study_collection,
    tmp_path,
    is_open_access,
    expected_oa_status,
    openalex_work_dict,
):
    """Test fetch_many_full_texts handles missing PDF URLs gracefully."""
    test_uuids = [study.uid for study in test_study_collection.studies]

    test_openalex_work = openalex_work_dict.copy()
    test_openalex_work.get("open_access", {}).update({"is_oa": is_open_access})

    mock_get_work = mocker.patch.object(
        fetcher, "_get_work_doi", new_callable=mocker.AsyncMock
    )
    mock_get_work.side_effect = [
        test_openalex_work for _ in test_study_collection.studies
    ]

    mock_get_pdf_url = mocker.patch.object(fetcher, "_get_pdf_url")

    mock_download = mocker.patch.object(
        fetcher, "download_one_pdf", new_callable=mocker.AsyncMock
    )

    mock_get_pdf_url.side_effect = [
        "http://example.com/file_one.pdf",
        "http://example.com/file_two.pdf",
    ]
    mock_download.side_effect = [
        tmp_path / f"{test_uuids[0]}.pdf",
        tmp_path / f"{test_uuids[1]}.pdf",
    ]

    mock_get_pdf_url = mocker.patch.object(fetcher, "_get_pdf_url")
    mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
    mock_get_pdf_url.side_effect = [None, None]

    assert all(
        study.is_open_access is None for study in test_study_collection.studies
    ), "Initial open access status should be None before population via OpenAlex"

    results = await fetcher.fetch_many_full_texts(test_study_collection, tmp_path)

    assert all(
        result.doi == study.doi.identifier.lower()
        for result, study in zip(results, test_study_collection.studies, strict=False)
    )
    assert all(
        result.uid == study.uid
        for result, study in zip(results, test_study_collection.studies, strict=False)
    )
    assert all(
        result.fulltext_path is None for result in results
    ), "PDF path should be None when no PDF URL is available"

    assert all(
        study.is_open_access == expected_oa_status
        for study in test_study_collection.studies
    ), "Open access status should be updated based on work data even when no PDF URL is available"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("is_open_access", "expected_oa_status"),
    [
        ("true", True),
        ("false", False),
    ],
)
async def test_fetch_many_full_texts_no_pdf_updates_open_access_status(
    mocker,
    fetcher,
    test_study_collection,
    tmp_path,
    is_open_access,
    expected_oa_status,
    openalex_work_dict,
):
    """Test fetch_many_full_texts handles missing PDF URLs gracefully."""
    test_openalex_work = openalex_work_dict.copy()
    test_openalex_work.get("open_access", {}).update({"is_oa": is_open_access})

    mock_get_work = mocker.patch.object(
        fetcher, "_get_work_doi", new_callable=mocker.AsyncMock
    )
    mock_get_work.side_effect = [test_openalex_work, test_openalex_work]

    mock_get_pdf_url = mocker.patch.object(fetcher, "_get_pdf_url")
    mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
    mock_get_pdf_url.side_effect = [None, None]

    assert all(
        study.is_open_access is None for study in test_study_collection.studies
    ), "Initial open access status should be None before population via OpenAlex"

    results = await fetcher.fetch_many_full_texts(test_study_collection, tmp_path)

    assert all(
        result.doi == study.doi.identifier.lower()
        for result, study in zip(results, test_study_collection.studies, strict=False)
    )
    assert all(
        result.uid == study.uid
        for result, study in zip(results, test_study_collection.studies, strict=False)
    )
    assert all(
        result.fulltext_path is None for result in results
    ), "PDF path should be None when no PDF URL is available"

    assert all(
        study.is_open_access == expected_oa_status
        for study in test_study_collection.studies
    ), "Open access status should be updated based on work data even when no PDF URL is available"


@pytest.mark.asyncio
async def test_fetch_many_full_texts_http_error(
    mocker, fetcher, test_study_collection, tmp_path
):
    """Test fetch_many_full_texts handles HTTP errors gracefully."""
    mock_get_work = mocker.patch.object(
        fetcher, "_get_work_doi", new_callable=mocker.AsyncMock
    )
    mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)

    mock_get_work.side_effect = HTTPError("API Error")

    results = await fetcher.fetch_many_full_texts(test_study_collection, tmp_path)

    assert all(
        result.fulltext_path is None for result in results
    ), "PDF path should be None when HTTP error occurs"
    assert all(
        result.error is not None for result in results
    ), "Error message should be present when HTTP error occurs"


@pytest.mark.asyncio
async def test_fetch_many_full_texts_stream_error(
    mocker, fetcher, test_study_collection, tmp_path
):
    """Test fetch_many_full_texts handles download stream errors gracefully."""
    mock_get_work = mocker.patch.object(
        fetcher, "_get_work_doi", new_callable=mocker.AsyncMock
    )
    mock_get_pdf_url = mocker.patch.object(fetcher, "_get_pdf_url")
    mock_download = mocker.patch.object(
        fetcher, "download_one_pdf", new_callable=mocker.AsyncMock
    )
    mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)

    mock_get_work.return_value = {}
    mock_get_pdf_url.return_value = "http://url"
    mock_download.side_effect = FullTextStreamError("Stream failed")
    results = await fetcher.fetch_many_full_texts(test_study_collection, tmp_path)

    assert all(
        result.fulltext_path is None for result in results
    ), "PDF path should be None when stream error occurs"
    assert all(
        result.error is not None for result in results
    ), "Error message should be present when stream error occurs"
