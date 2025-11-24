"""Unit tests for app/fetching/openalex.py."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import HTTPError, Response

from app.fetching.core import FullTextStreamError
from app.fetching.openalex import OpenalexFetcher


@pytest.fixture
def fetcher(test_settings):
    return OpenalexFetcher(settings=test_settings, wait_time_seconds=0.0)


def test_init(fetcher, test_settings):
    """Test initialization of OpenalexFetcher."""
    assert fetcher.settings == test_settings
    assert fetcher.wait_time_seconds == 0.0
    assert fetcher.base_url == "https://api.openalex.org/works/doi:"
    assert fetcher.query_params == {"mailto": "test@test.com"}
    assert fetcher.headers["User-Agent"] == "destiny-project-ucl"


@pytest.mark.asyncio
async def test_get_work_success(fetcher):
    """Test _get_work returns JSON data on success."""
    doi = "10.1234/example"
    expected_data = {"id": "W123", "doi": doi}

    mock_response = MagicMock(spec=Response)
    mock_response.json.return_value = expected_data
    mock_response.raise_for_status = MagicMock()

    with patch("app.fetching.openalex.AsyncHTTPXRetryClient") as MockClient:
        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.get.return_value = mock_response

        result = await fetcher._get_work(doi)

        assert result == expected_data
        mock_client_instance.get.assert_called_once()

        call_kwargs = mock_client_instance.get.call_args.kwargs
        assert "10.1234/example" in call_kwargs["url"]
        assert call_kwargs["params"] == fetcher.query_params
        assert call_kwargs["headers"] == fetcher.headers


@pytest.mark.asyncio
async def test_get_work_http_error(fetcher):
    """Test _get_work raises HTTPError on failure."""
    doi = "10.1234/example"
    with patch("app.fetching.openalex.AsyncHTTPXRetryClient") as MockClient:
        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__.return_value = mock_client_instance

        mock_response = MagicMock(spec=Response)
        mock_response.raise_for_status.side_effect = HTTPError("oops")
        mock_client_instance.get.return_value = mock_response

        with pytest.raises(HTTPError):
            await fetcher._get_work(doi)


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
async def test_download_one_pdf(fetcher):
    """Test download_one_pdf calls stream_file correctly."""
    url = "http://example.com/file.pdf"
    path = Path("/tmp/file.pdf")

    with patch(
        "app.fetching.openalex.stream_file", new_callable=AsyncMock
    ) as mock_stream:
        mock_stream.return_value = path
        result = await fetcher.download_one_pdf(url, path)
        assert result == path
        mock_stream.assert_called_once_with(url=url, destination=path)


@pytest.mark.asyncio
async def test_fetch_many_full_texts_success(fetcher, tmp_path):
    """Test fetch_many_full_texts successfully downloads PDFs."""
    # mock StudyCollection and Study
    mock_study = MagicMock()
    mock_study.doi.identifier = "10.1234/example"
    mock_study.uid = "uid_123"

    mock_collection = MagicMock()
    mock_collection.iterate_studies.return_value = [mock_study]

    with (
        patch.object(fetcher, "_get_work", new_callable=AsyncMock) as mock_get_work,
        patch.object(fetcher, "_get_pdf_url") as mock_get_pdf_url,
        patch.object(
            fetcher, "download_one_pdf", new_callable=AsyncMock
        ) as mock_download,
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        mock_get_work.return_value = {"some": "data"}
        mock_get_pdf_url.return_value = "http://example.com/file.pdf"
        mock_download.return_value = tmp_path / "uid_123.pdf"

        results = await fetcher.fetch_many_full_texts(mock_collection, tmp_path)

        assert results["10.1234/example"] == tmp_path / "uid_123.pdf"
        mock_get_work.assert_called_once_with("10.1234/example")
        mock_download.assert_called_once()
        mock_sleep.assert_called_once_with(0.0)


@pytest.mark.asyncio
async def test_fetch_many_full_texts_no_pdf(fetcher, tmp_path):
    """Test fetch_many_full_texts handles missing PDF URLs gracefully."""
    mock_study = MagicMock()
    mock_study.doi.identifier = "10.1234/example"
    mock_study.uid = "uid_123"
    mock_collection = MagicMock()
    mock_collection.iterate_studies.return_value = [mock_study]

    with (
        patch.object(fetcher, "_get_work", new_callable=AsyncMock) as mock_get_work,
        patch.object(fetcher, "_get_pdf_url") as mock_get_pdf_url,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_get_work.return_value = {"some": "data"}
        mock_get_pdf_url.return_value = None

        results = await fetcher.fetch_many_full_texts(mock_collection, tmp_path)

        # should be None for this DOI
        assert results["10.1234/example"] is None


@pytest.mark.asyncio
async def test_fetch_many_full_texts_http_error(fetcher, tmp_path):
    """Test fetch_many_full_texts handles HTTP errors gracefully."""
    mock_study = MagicMock()
    mock_study.doi.identifier = "10.1234/example"
    mock_collection = MagicMock()
    mock_collection.iterate_studies.return_value = [mock_study]

    with (
        patch.object(fetcher, "_get_work", new_callable=AsyncMock) as mock_get_work,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_get_work.side_effect = HTTPError("API Error")

        results = await fetcher.fetch_many_full_texts(mock_collection, tmp_path)

        # error caught, DOI not added to results
        assert "10.1234/example" not in results
        assert results == {}


@pytest.mark.asyncio
async def test_fetch_many_full_texts_stream_error(fetcher, tmp_path):
    """Test fetch_many_full_texts handles download stream errors gracefully."""
    mock_study = MagicMock()
    mock_study.doi.identifier = "10.1234/example"
    mock_study.uid = "uid_123"
    mock_collection = MagicMock()
    mock_collection.iterate_studies.return_value = [mock_study]

    with (
        patch.object(fetcher, "_get_work", new_callable=AsyncMock) as mock_get_work,
        patch.object(fetcher, "_get_pdf_url") as mock_get_pdf_url,
        patch.object(
            fetcher, "download_one_pdf", new_callable=AsyncMock
        ) as mock_download,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        mock_get_work.return_value = {}
        mock_get_pdf_url.return_value = "http://url"
        mock_download.side_effect = FullTextStreamError("Stream failed")
        results = await fetcher.fetch_many_full_texts(mock_collection, tmp_path)

        assert results == {}
