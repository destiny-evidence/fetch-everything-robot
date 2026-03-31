import httpx
import pytest
from pypdf import PdfWriter
from pypdf.errors import PyPdfError
from python_socks import ProxyConnectionError

from fer.fetching.core import FullTextStreamError
from fer.fetching.elsevier import ElsevierFetcher, ElsevierRequestConfig


@pytest.mark.asyncio
async def test_elsevier_fetcher_fetch_many_full_texts_success(
    mocker, test_settings, test_study_collection, tmp_path
):
    fetcher = ElsevierFetcher(settings=test_settings)
    mocker.patch(
        "fer.fetching.elsevier.stream_file", return_value=tmp_path / "test.pdf"
    )
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None

    mock_get = mocker.patch(
        "fer.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    await fetcher.fetch_many_full_texts(
        study_collection=test_study_collection,
        output_directory=tmp_path,
    )

    assert mock_get.call_count == len(test_study_collection.studies)


@pytest.mark.asyncio
async def test_elsevier_fetcher_fetch_many_full_texts_non_http_200(
    mocker, test_settings, test_study_collection, tmp_path, caplog
):
    uids = [str(study.uid).lower() for study in test_study_collection.studies]
    dois = [study.doi.identifier.lower() for study in test_study_collection.studies]
    fetcher = ElsevierFetcher(settings=test_settings)
    mocker.patch(
        "fer.fetching.elsevier.stream_file", return_value=tmp_path / "test.pdf"
    )
    test_status_code = httpx.codes.ACCEPTED
    mock_response = mocker.MagicMock()
    mock_response.status_code = test_status_code
    mock_response.raise_for_status.return_value = None

    mock_get = mocker.patch(
        "fer.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("WARNING"):
        await fetcher.fetch_many_full_texts(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )
    assert mock_get.call_count == len(test_study_collection.studies)
    assert all(uid in caplog.text for uid in uids)
    assert all(doi in caplog.text for doi in dois)
    assert str(test_status_code) in caplog.text


@pytest.mark.asyncio
async def test_elsevier_fetcher_fetch_many_full_texts_http_error(
    mocker, test_settings, test_study_collection, tmp_path, caplog
):
    dois = [study.doi.identifier.lower() for study in test_study_collection.studies]
    fetcher = ElsevierFetcher(settings=test_settings)
    mocker.patch(
        "fer.fetching.elsevier.stream_file", return_value=tmp_path / "test.pdf"
    )

    mock_response = mocker.MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPError("Test HTTP error")

    mock_get = mocker.patch(
        "fer.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("ERROR"):
        await fetcher.fetch_many_full_texts(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )
    assert mock_get.call_count == len(test_study_collection.studies)
    assert all(doi in caplog.text for doi in dois)
    assert "HTTP error fetching Elsevier data" in caplog.text


@pytest.mark.asyncio
async def test_elsevier_fetcher_fetch_many_full_texts_stream_error(
    mocker, test_settings, test_study_collection, tmp_path, caplog
):
    dois = [study.doi.identifier.lower() for study in test_study_collection.studies]
    fetcher = ElsevierFetcher(settings=test_settings)
    mocker.patch(
        "fer.fetching.elsevier.stream_file",
        side_effect=FullTextStreamError("Test stream error"),
    )

    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None

    mock_get = mocker.patch(
        "fer.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("ERROR"):
        await fetcher.fetch_many_full_texts(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )
    assert mock_get.call_count == len(test_study_collection.studies)
    assert all(doi in caplog.text for doi in dois)
    assert "Full text download error" in caplog.text


def test_elsevier_fetcher_is_single_page_pdf_true_single_page(tmp_path):
    pdf_path = tmp_path / "single_page.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as file:
        writer.write(file)

    fetcher = ElsevierFetcher(settings=None)
    assert fetcher._is_single_page_pdf(pdf_path) is True


def test_elsevier_fetcher_is_single_page_pdf_false_multiple_pages(tmp_path):
    pdf_path = tmp_path / "multiple_pages.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as file:
        writer.write(file)

    fetcher = ElsevierFetcher(settings=None)
    assert fetcher._is_single_page_pdf(pdf_path) is False


def test_elsevier_fetcher_is_single_page_pdf_false_no_pages(tmp_path):
    pdf_path = tmp_path / "single_page.pdf"
    pdf_path.write_bytes(b"")

    fetcher = ElsevierFetcher(settings=None)
    assert fetcher._is_single_page_pdf(pdf_path) is False


def test_elsevier_fetcher_is_single_page_pdf_is_false_pypdf_error(
    mocker, caplog, tmp_path
):
    pdf_path = tmp_path / "corrupt.pdf"
    pdf_path.write_text("This is not a valid PDF file.")
    mocker.patch(
        "fer.fetching.elsevier.PdfReader", side_effect=PyPdfError("Test PDF read error")
    )

    fetcher = ElsevierFetcher(settings=None)
    with caplog.at_level("ERROR"):
        assert fetcher._is_single_page_pdf(pdf_path) is False
    assert f"Error reading PDF file {pdf_path}" in caplog.text


def test_is_single_page_pdf_is_false_file_not_found(caplog, tmp_path):
    missing = tmp_path / "missing.pdf"
    with caplog.at_level("WARNING"):
        assert ElsevierFetcher._is_single_page_pdf(missing) is False
    assert str(missing) in caplog.text


@pytest.mark.asyncio
async def test_fetch_one_fulltext_returns_retrieved_full_text_on_success(
    mocker, test_settings, tmp_path, test_study_collection
):
    study = test_study_collection.studies[0]
    request_config = ElsevierRequestConfig(
        headers={"Accept": "application/pdf"}, file_extension=".pdf"
    )
    mocker.patch(
        "fer.fetching.elsevier.stream_file", return_value=tmp_path / f"{study.uid}.pdf"
    )
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None
    mocker.patch(
        "fer.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    fetcher = ElsevierFetcher(settings=test_settings)
    result = await fetcher._fetch_one_fulltext(study, tmp_path, request_config)

    assert result.pdf_path == tmp_path / f"{study.uid}.pdf"
    assert result.error is None


@pytest.mark.asyncio
async def test_fetch_one_fulltext_http_error(
    mocker, test_settings, tmp_path, test_study_collection
):
    study = test_study_collection.studies[0]
    request_config = ElsevierRequestConfig(
        headers={"Accept": "application/pdf"}, file_extension=".pdf"
    )
    mock_response = mocker.MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPError("a test http error")
    mocker.patch(
        "fer.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    result = await ElsevierFetcher(settings=test_settings)._fetch_one_fulltext(
        study, tmp_path, request_config
    )

    assert result.pdf_path is None
    assert "HTTP error" in result.error


@pytest.mark.asyncio
async def test_fetch_one_fulltext_proxy_connection_error(
    mocker, test_settings, tmp_path, test_study_collection
):
    study = test_study_collection.studies[0]
    request_config = ElsevierRequestConfig(
        headers={"Accept": "application/pdf"}, file_extension=".pdf"
    )
    mock_response = mocker.MagicMock()
    mock_response.raise_for_status.side_effect = ProxyConnectionError(
        "a test proxy connection error"
    )
    mocker.patch(
        "fer.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    result = await ElsevierFetcher(settings=test_settings)._fetch_one_fulltext(
        study, tmp_path, request_config
    )

    assert result.pdf_path is None
    assert "proxy connection error" in result.error


@pytest.mark.asyncio
async def test_fetch_one_fulltext_stream_error(
    mocker, test_settings, tmp_path, test_study_collection
):
    study = test_study_collection.studies[0]
    request_config = ElsevierRequestConfig(
        headers={"Accept": "application/pdf"}, file_extension=".pdf"
    )
    mocker.patch(
        "fer.fetching.elsevier.stream_file",
        side_effect=FullTextStreamError("a test stream error"),
    )
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None
    mocker.patch(
        "fer.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    result = await ElsevierFetcher(settings=test_settings)._fetch_one_fulltext(
        study, tmp_path, request_config
    )

    assert result.pdf_path is None
    assert "Full text download error" in result.error
