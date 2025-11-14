import httpx
import pytest

from app.fetching.core import FullTextStreamError
from app.fetching.elsevier import ElsevierFetcher


@pytest.mark.asyncio
async def test_elsevier_fetcher_fetch_full_text_success(
    mocker, test_settings, test_study_collection, tmp_path
):
    fetcher = ElsevierFetcher(settings=test_settings)
    mocker.patch("app.fetching.elsevier.stream_file")
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None

    mock_get = mocker.patch(
        "app.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    await fetcher.fetch_full_text(
        study_collection=test_study_collection,
        output_directory=tmp_path,
    )

    assert mock_get.call_count == len(test_study_collection.studies)


@pytest.mark.asyncio
async def test_elsevier_fetcher_fetch_full_text_non_http_200(
    mocker, test_settings, test_study_collection, tmp_path, caplog
):
    uids = [study.uid.lower() for study in test_study_collection.iterate_studies()]
    dois = [
        study.doi.identifier.lower()
        for study in test_study_collection.iterate_studies()
    ]
    fetcher = ElsevierFetcher(settings=test_settings)
    mocker.patch("app.fetching.elsevier.stream_file")
    test_status_code = httpx.codes.ACCEPTED
    mock_response = mocker.MagicMock()
    mock_response.status_code = test_status_code
    mock_response.raise_for_status.return_value = None

    mock_get = mocker.patch(
        "app.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("WARNING"):
        await fetcher.fetch_full_text(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )
    assert mock_get.call_count == len(test_study_collection.studies)
    assert all(uid in caplog.text for uid in uids)
    assert all(doi in caplog.text for doi in dois)
    assert str(test_status_code) in caplog.text


@pytest.mark.asyncio
async def test_elsevier_fetcher_fetch_full_text_http_error(
    mocker, test_settings, test_study_collection, tmp_path, caplog
):
    dois = [
        study.doi.identifier.lower()
        for study in test_study_collection.iterate_studies()
    ]
    fetcher = ElsevierFetcher(settings=test_settings)
    mocker.patch("app.fetching.elsevier.stream_file")

    mock_response = mocker.MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPError("Test HTTP error")

    mock_get = mocker.patch(
        "app.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("ERROR"):
        await fetcher.fetch_full_text(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )
    assert mock_get.call_count == len(test_study_collection.studies)
    assert all(doi in caplog.text for doi in dois)
    assert "HTTP error fetching Elsevier data" in caplog.text


@pytest.mark.asyncio
async def test_elsevier_fetcher_fetch_full_text_stream_error(
    mocker, test_settings, test_study_collection, tmp_path, caplog
):
    dois = [
        study.doi.identifier.lower()
        for study in test_study_collection.iterate_studies()
    ]
    fetcher = ElsevierFetcher(settings=test_settings)
    mocker.patch(
        "app.fetching.elsevier.stream_file",
        side_effect=FullTextStreamError("Test stream error"),
    )

    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None

    mock_get = mocker.patch(
        "app.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("ERROR"):
        await fetcher.fetch_full_text(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )
    assert mock_get.call_count == len(test_study_collection.studies)
    assert all(doi in caplog.text for doi in dois)
    assert "Full text download error" in caplog.text
