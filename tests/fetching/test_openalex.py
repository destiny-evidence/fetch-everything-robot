"""Unit tests for fer/fetching/openalex.py."""

import pytest
from destiny_sdk.identifiers import DOIIdentifier
from httpx2 import AsyncClient, HTTPError, MockTransport, Request, Response

from fer.fetching.core import DOIStudyCollection, FullTextStreamError
from fer.fetching.openalex import OpenalexFetcher
from tests.fixtures.fetching import fake_stream_file


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
async def test_openalex_retrieval_download_one_pdf_fails_returns_none(
    mocker, test_study_collection, fetcher, temporary_test_file
):
    """Test download_one_pdf returns None when stream_file fails."""
    test_study = test_study_collection.studies[0]
    test_study_doi = test_study.doi.identifier.lower()
    mock_download_one_pdf = mocker.patch.object(
        fetcher, "download_one_pdf", new_callable=mocker.AsyncMock
    )
    mock_download_one_pdf.return_value = None
    mock_get_work_doi_value = {
        "id": "W1234567890",
        "locations": [{"pdf_url": "http://example.com/file.pdf"}],
    }
    mocker.patch.object(
        fetcher,
        "_get_work_doi",
        new_callable=mocker.AsyncMock,
        return_value=mock_get_work_doi_value,
    )
    result = await fetcher._openalex_retrieval(
        study=test_study, output_directory=temporary_test_file
    )
    assert mock_download_one_pdf.call_count == 1
    assert result.fulltext_path is None
    assert result.doi == test_study_doi
    assert result.uid == test_study.uid
    assert "No PDF found for" in result.error


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
        fetcher,
        "download_one_pdf",
        new=mocker.AsyncMock(
            side_effect=[
                await fake_stream_file(
                    url="http://example.com/article.pdf",
                    destination=tmp_path / f"{uid}.pdf",
                )
                for uid in test_uuids
            ]
        ),
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


@pytest.mark.asyncio
async def test_fetch_many_full_texts_empty_pdf_download_does_not_abort_a_batch(
    mocker, test_study_collection, fetcher, tmp_path
):
    test_dois = ["10.1000/empty", "10.1000/good"]
    empty_study, good_study = (
        study.model_copy(update={"doi": DOIIdentifier(identifier=doi)})
        for study, doi in zip(
            test_study_collection.studies[:2], test_dois, strict=False
        )
    )
    expected_good_study_fulltext_path = tmp_path / f"{good_study.uid}.pdf"
    expected_nonexistent_empty_study_fulltext_path = tmp_path / f"{empty_study.uid}.pdf"
    modified_test_study_collection = DOIStudyCollection(
        studies=[empty_study, good_study]
    )
    uid_by_doi = {
        study.doi.identifier.lower(): study.uid for study in (empty_study, good_study)
    }

    fetcher.wait_time_seconds = 0
    mocker.patch.object(
        fetcher,
        "_get_work_doi",
        side_effect=lambda doi: {
            "id": "W123456",
            "doi": doi,
            "locations": [{"pdf_url": f"https://example.org/{uid_by_doi[doi]}.pdf"}],
        },
    )

    def respond(request: Request) -> Response:
        is_empty = request.url.path == f"/{empty_study.uid}.pdf"
        return Response(200, content=b"" if is_empty else b"%PDF-1.4 test")

    real_client = AsyncClient
    mocker.patch(
        "fer.fetching.core.httpx2.AsyncClient",
        lambda **kwargs: real_client(transport=MockTransport(respond), **kwargs),
    )

    results = await fetcher.fetch_many_full_texts(
        modified_test_study_collection, tmp_path
    )
    by_uid = {result.uid: result for result in results}
    assert by_uid[empty_study.uid].fulltext_path is None
    assert by_uid[empty_study.uid].error is not None
    assert not expected_nonexistent_empty_study_fulltext_path.exists()
    assert by_uid[good_study.uid].fulltext_path == expected_good_study_fulltext_path
    assert by_uid[good_study.uid].error is None


@pytest.mark.asyncio
async def test_get_work_openalex_id_success(mocker, fetcher):
    """Test get_work_openalex_id returns JSON data on success."""
    openalex_id = "W1234567890"
    expected_data = {"id": openalex_id}

    mock_response = mocker.MagicMock(spec=Response)
    mock_response.json.return_value = expected_data
    mock_response.raise_for_status = mocker.MagicMock()

    mock_client = mocker.patch("fer.fetching.openalex.AsyncHTTPXRetryClient")
    mock_client_instance = mocker.AsyncMock()
    mock_client.return_value.__aenter__.return_value = mock_client_instance
    mock_client_instance.get.return_value = mock_response

    result = await fetcher.get_work_openalex_id(openalex_id)

    assert result == expected_data
    mock_client_instance.get.assert_called_once()

    call_kwargs = mock_client_instance.get.call_args.kwargs
    assert openalex_id in call_kwargs["url"]
    assert "doi" not in call_kwargs["url"]


@pytest.mark.asyncio
async def test_get_work_openalex_id_http_error(mocker, fetcher):
    mock_client = mocker.patch("fer.fetching.openalex.AsyncHTTPXRetryClient")
    mock_client_instance = mocker.AsyncMock()
    mock_client.return_value.__aenter__.return_value = mock_client_instance

    mock_response = mocker.MagicMock(spec=Response)
    mock_response.raise_for_status.side_effect = HTTPError("A test error")
    mock_client_instance.get.return_value = mock_response

    with pytest.raises(HTTPError):
        await fetcher.get_work_openalex_id("W1234567890")


@pytest.mark.asyncio
async def test_fetch_many_full_texts_openalex_collection_success(
    mocker, fetcher, test_openalex_study_collection, tmp_path
):
    mock_get_work_openalex = mocker.patch.object(
        fetcher,
        "get_work_openalex_id",
        new_callable=mocker.AsyncMock,
        side_effect=[{"id": "W1234567890"}, {"id": "W0987654321"}],
    )
    mock_get_work_doi = mocker.patch.object(
        fetcher, "_get_work_doi", new_callable=mocker.AsyncMock
    )
    mocker.patch.object(
        fetcher, "_get_pdf_url", return_value="http://example.com/file.pdf"
    )

    test_uuids = [s.uid for s in test_openalex_study_collection.studies]
    mocker.patch.object(
        fetcher,
        "download_one_pdf",
        new_callable=mocker.AsyncMock,
        side_effect=[tmp_path / f"{uid}.pdf" for uid in test_uuids],
    )

    for uid in test_uuids:
        (tmp_path / f"{uid}.pdf").write_bytes(b"test")
    mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)

    results = await fetcher.fetch_many_full_texts(
        test_openalex_study_collection, tmp_path
    )

    assert len(results) == len(test_openalex_study_collection.studies)
    mock_get_work_doi.assert_not_called()
    assert mock_get_work_openalex.call_count == len(
        test_openalex_study_collection.studies
    )
    assert all(
        result.fulltext_path == tmp_path / f"{study.uid}.pdf"
        for result, study in zip(
            results, test_openalex_study_collection.studies, strict=False
        )
    )
    assert all(
        result.openalex_id == study.openalex_id.identifier
        for result, study in zip(
            results, test_openalex_study_collection.studies, strict=False
        )
    )
    assert all(
        result.doi == study.doi.identifier.lower()
        for result, study in zip(
            results, test_openalex_study_collection.studies, strict=False
        )
    )


@pytest.mark.asyncio
async def test_fetch_many_full_texts_openalex_collection_no_pdf(
    mocker, fetcher, test_openalex_study_collection, tmp_path
):
    mocker.patch.object(
        fetcher,
        "get_work_openalex_id",
        new_callable=mocker.AsyncMock,
        return_value={"id": "W1234567890"},
    )
    mocker.patch.object(fetcher, "_get_pdf_url", return_value=None)
    mocker.patch("asyncio.sleep", new_callable=mocker.AsyncMock)
    results = await fetcher.fetch_many_full_texts(
        test_openalex_study_collection, tmp_path
    )

    assert all(result.fulltext_path is None for result in results)
    assert all(result.error is not None for result in results)
