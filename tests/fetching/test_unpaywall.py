import httpx
import pytest

from app.fetching.core import FullTextStreamError
from app.fetching.unpaywall import UnpaywallFetcher


@pytest.mark.asyncio
async def test_unpaywall_fetcher_fetch_many_full_texts_success_pdf_found(
    mocker, test_settings, test_study_collection, tmp_path, caplog
):
    test_dois = [study.doi.identifier for study in test_study_collection.studies]
    test_uids = [str(study.uid) for study in test_study_collection.studies]
    test_data = {
        "best_oa_location": {"url_for_pdf": "http://example.com/article.pdf"},
        "publisher": "Test Publisher",
    }
    fetcher = UnpaywallFetcher(settings=test_settings)
    mocker.patch("app.fetching.unpaywall.stream_file")
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None
    mock_response.json = mocker.AsyncMock(return_value=test_data)

    mock_get = mocker.patch(
        "app.fetching.unpaywall.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("INFO"):
        await fetcher.fetch_many_full_texts(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )

    assert mock_get.call_count == len(test_study_collection.studies)
    assert "Unpaywall download success" in caplog.text
    assert all(uid in caplog.text for uid in test_uids)
    assert all(doi in caplog.text for doi in test_dois)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "publisher",
    [
        "Wiley",
        "Elsevier BV",
        "SAGE Publications",
    ],
)
async def test_unpaywall_fetcher_fetch_many_full_texts_no_pdf_found_publisher(
    mocker, test_settings, test_study_collection, tmp_path, caplog, publisher
):
    test_dois = [study.doi.identifier for study in test_study_collection.studies]
    test_uids = [str(study.uid) for study in test_study_collection.studies]
    test_data = {
        "best_oa_location": {"url_for_pdf": "http://example.com/article.pdf"},
        "publisher": publisher,
    }
    fetcher = UnpaywallFetcher(settings=test_settings)
    mocker.patch("app.fetching.unpaywall.stream_file")
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None
    mock_response.json = mocker.AsyncMock(return_value=test_data)

    mock_get = mocker.patch(
        "app.fetching.unpaywall.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("WARNING"):
        await fetcher.fetch_many_full_texts(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )

    assert mock_get.call_count == len(test_study_collection.studies)
    assert "PDF not found" in caplog.text
    assert publisher in caplog.text
    assert all(uid in caplog.text for uid in test_uids)
    assert all(doi in caplog.text for doi in test_dois)


@pytest.mark.asyncio
async def test_unpaywall_fetcher_fetch_many_full_texts_no_pdf_found_taylor_and_francis_in_url(
    mocker,
    test_settings,
    test_study_collection,
    tmp_path,
    caplog,
):
    test_dois = [study.doi.identifier for study in test_study_collection.studies]
    test_uids = [str(study.uid) for study in test_study_collection.studies]
    test_data = {
        "best_oa_location": {
            "url_for_pdf": "http://example.com/tandfonline/article.pdf"
        },
        "publisher": "Test Publisher",
    }
    fetcher = UnpaywallFetcher(settings=test_settings)
    mocker.patch("app.fetching.unpaywall.stream_file")
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None
    mock_response.json = mocker.AsyncMock(return_value=test_data)

    mock_get = mocker.patch(
        "app.fetching.unpaywall.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("WARNING"):
        await fetcher.fetch_many_full_texts(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )

    assert mock_get.call_count == len(test_study_collection.studies)
    assert "PDF not found" in caplog.text
    assert "taylor_and_francis_in_url=True" in caplog.text
    assert all(uid in caplog.text for uid in test_uids)
    assert all(doi in caplog.text for doi in test_dois)


@pytest.mark.asyncio
async def test_unpaywall_fetcher_fetch_many_full_texts_http_error(
    mocker, test_settings, test_study_collection, tmp_path, caplog
):
    test_dois = [study.doi.identifier for study in test_study_collection.studies]
    fetcher = UnpaywallFetcher(settings=test_settings)

    mock_response = mocker.MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPError("HTTP error occurred")

    mock_get = mocker.patch(
        "app.fetching.unpaywall.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("ERROR"):
        await fetcher.fetch_many_full_texts(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )

    assert mock_get.call_count == len(test_study_collection.studies)
    assert "HTTP error fetching Unpaywall data" in caplog.text
    assert all(doi in caplog.text for doi in test_dois)


@pytest.mark.asyncio
async def test_unpaywall_fetcher_fetch_many_full_texts_fulltextstreamerror(
    mocker, test_settings, test_study_collection, tmp_path, caplog
):
    test_dois = [study.doi.identifier for study in test_study_collection.studies]
    test_uids = [str(study.uid) for study in test_study_collection.studies]
    test_data = {
        "best_oa_location": {"url_for_pdf": "http://example.com/article.pdf"},
        "publisher": "Test Publisher",
    }
    fetcher = UnpaywallFetcher(settings=test_settings)
    mock_stream_file = mocker.patch(
        "app.fetching.unpaywall.stream_file",
        side_effect=FullTextStreamError("test error"),
    )
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None
    mock_response.json = mocker.AsyncMock(return_value=test_data)

    mock_get = mocker.patch(
        "app.fetching.unpaywall.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("ERROR"):
        await fetcher.fetch_many_full_texts(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )

    assert mock_get.call_count == len(test_study_collection.studies)
    assert mock_stream_file.call_count == len(test_study_collection.studies)
    assert "Error streaming Unpaywall data" in caplog.text
    assert all(uid in caplog.text for uid in test_uids)
    assert all(doi in caplog.text for doi in test_dois)


@pytest.mark.asyncio
async def test_unpaywall_fetcher_fetch_many_full_texts_no_best_oa_location(
    mocker, test_settings, test_study_collection, tmp_path, caplog
):
    test_dois = [study.doi.identifier for study in test_study_collection.studies]
    test_uids = [str(study.uid) for study in test_study_collection.studies]
    test_data = {
        "best_oa_location": None,
        "publisher": "Test Publisher",
    }
    fetcher = UnpaywallFetcher(settings=test_settings)
    mocker.patch("app.fetching.unpaywall.stream_file")
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None
    mock_response.json = mocker.AsyncMock(return_value=test_data)

    mock_get = mocker.patch(
        "app.fetching.unpaywall.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("WARNING"):
        await fetcher.fetch_many_full_texts(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )

    assert mock_get.call_count == len(test_study_collection.studies)
    assert "Unpaywall PDF not found" in caplog.text
    assert all(uid in caplog.text for uid in test_uids)
    assert all(doi in caplog.text for doi in test_dois)
