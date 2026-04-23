from uuid import uuid4

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.errors import PyPdfError
from python_socks import ProxyConnectionError

from fer.fetching.core import (
    FullTextStreamError,
    IncompleteFullTextError,
)
from fer.fetching.elsevier import ElsevierFetcher, ElsevierRequestConfig
from tests.fixtures.fetching import fake_stream_file


@pytest.mark.asyncio
async def test_elsevier_fetcher_fetch_many_full_texts_pdf_success(
    mocker, test_settings, test_study_collection, tmp_path
):
    fetcher = ElsevierFetcher(settings=test_settings)
    mocked_stream = mocker.patch(
        "fer.fetching.elsevier.stream_file", side_effect=fake_stream_file
    )
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None

    await fetcher.fetch_many_full_texts(
        study_collection=test_study_collection,
        output_directory=tmp_path,
    )
    assert mocked_stream.call_count == len(test_study_collection.studies)


@pytest.mark.asyncio
async def test_elsevier_fetcher_fetch_many_full_texts_xml_success(
    mocker, test_settings, test_study_collection, tmp_path
):
    fetcher = ElsevierFetcher(settings=test_settings)
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None
    mock_response.content = b"<xml>content</xml>"
    mocked_get = mocker.patch(
        "fer.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )
    result = await fetcher.fetch_many_full_texts(
        study_collection=test_study_collection,
        output_directory=tmp_path,
        get_pdf=False,
        get_xml=True,
    )
    assert mocked_get.call_count == len(test_study_collection.studies)
    assert all(str(r.fulltext_path).endswith(".xml") for r in result)


@pytest.mark.asyncio
async def test_elsevier_fetcher_fetch_many_full_texts_xml_non_http_200(
    mocker, test_settings, test_study_collection, tmp_path, caplog
):
    uids = [str(study.uid).lower() for study in test_study_collection.studies]
    dois = [study.doi.identifier.lower() for study in test_study_collection.studies]
    fetcher = ElsevierFetcher(settings=test_settings)

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
            get_pdf=False,
            get_xml=True,
        )
    assert mock_get.call_count == len(test_study_collection.studies)
    assert all(uid in caplog.text for uid in uids)
    assert all(doi in caplog.text for doi in dois)
    assert str(test_status_code) in caplog.text


@pytest.mark.asyncio
async def test_elsevier_fetcher_fetch_many_full_texts_xml_http_error(
    mocker, test_settings, test_study_collection, tmp_path, caplog
):
    dois = [study.doi.identifier.lower() for study in test_study_collection.studies]
    fetcher = ElsevierFetcher(settings=test_settings)
    mocker.patch("fer.fetching.elsevier.stream_file", side_effect=fake_stream_file)

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
            get_pdf=False,
            get_xml=True,
        )
    assert mock_get.call_count == len(test_study_collection.studies)
    assert all(doi in caplog.text for doi in dois)
    assert "HTTP error fetching Elsevier data" in caplog.text


@pytest.mark.asyncio
async def test_elsevier_fetcher_fetch_many_full_texts_pdf_stream_error(
    mocker, test_settings, test_study_collection, tmp_path, caplog
):
    dois = [study.doi.identifier.lower() for study in test_study_collection.studies]
    fetcher = ElsevierFetcher(settings=test_settings)
    mocked_stream_file_call = mocker.patch(
        "fer.fetching.elsevier.stream_file",
        side_effect=FullTextStreamError("Test stream error"),
    )

    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None

    with caplog.at_level("ERROR"):
        await fetcher.fetch_many_full_texts(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )
    assert mocked_stream_file_call.call_count == len(test_study_collection.studies)
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
    mocker.patch("fer.fetching.elsevier.stream_file", side_effect=fake_stream_file)
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None
    mocker.patch(
        "fer.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    fetcher = ElsevierFetcher(settings=test_settings)
    result = await fetcher._fetch_one_fulltext(study, tmp_path, request_config)

    assert result.fulltext_path == tmp_path / f"{study.uid}.pdf"
    assert result.error is None


@pytest.mark.asyncio
async def test_fetch_one_fulltext_http_error(
    mocker, test_settings, tmp_path, test_study_collection
):
    study = test_study_collection.studies[0]
    request_config = ElsevierRequestConfig(
        headers={"Accept": "text/xml"}, file_extension=".xml"
    )
    mock_response = mocker.MagicMock()
    expected_error_text = "a test http error"
    mock_response.raise_for_status.side_effect = httpx.HTTPError(expected_error_text)
    mocker.patch(
        "fer.fetching.elsevier.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    result = await ElsevierFetcher(settings=test_settings)._fetch_one_fulltext(
        study, tmp_path, request_config
    )

    assert result.fulltext_path is None
    assert expected_error_text in result.error


@pytest.mark.asyncio
async def test_fetch_one_fulltext_proxy_connection_error(
    mocker, test_settings, tmp_path, test_study_collection
):
    study = test_study_collection.studies[0]
    request_config = ElsevierRequestConfig(
        headers={"Accept": "text/xml"}, file_extension=".xml"
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

    assert result.fulltext_path is None
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

    assert result.fulltext_path is None
    assert "Full text download error" in result.error


@pytest.mark.asyncio
async def test_fetch_many_full_texts_single_page_incomplete_pdf_falls_back_to_xml(
    mocker, test_settings, test_study_collection, tmp_path
):
    """
    Ensure a mislabelled open access item is handled correctly.

    An item mislabelled as open access, but that produces a single text PDF
    should cause us to fall back to producing XML output.
    """
    fetcher = ElsevierFetcher(settings=test_settings)
    studies = test_study_collection.studies
    for study in studies:
        pdf_path = tmp_path / f"{study.uid}.pdf"
        pdf_path.write_bytes(b"PDF content")
    interleaved_responses = [
        response
        for _ in studies
        for response in (
            httpx.Response(status_code=httpx.codes.OK, content=b"PDF content"),
            httpx.Response(status_code=httpx.codes.OK, content=b"<xml>content</xml>"),
        )
    ]
    mocked_stream = mocker.patch(
        "fer.fetching.elsevier.stream_file",
        new=mocker.AsyncMock(
            side_effect=IncompleteFullTextError("Test incomplete PDF error")
        ),
    )

    mock_fetch = mocker.patch.object(
        ElsevierFetcher,
        "_elsevier_request",
        new=mocker.AsyncMock(side_effect=interleaved_responses),
    )
    mocker.patch.object(ElsevierFetcher, "_is_single_page_pdf", return_value=True)

    results = await fetcher.fetch_many_full_texts(
        study_collection=test_study_collection, output_directory=tmp_path
    )

    elsevier_request_configs = [
        call.kwargs.get("elsevier_request_config") for call in mock_fetch.call_args_list
    ]
    stream_file_headers = [
        call.kwargs.get("headers") for call in mocked_stream.call_args_list
    ]
    pdf_calls = [
        header
        for header in stream_file_headers
        if header.get("Accept") == "application/pdf"
    ]

    xml_calls = [
        config
        for config in elsevier_request_configs
        if config.headers.get("Accept") == "text/xml"
    ]

    assert len(pdf_calls) == len(studies)
    assert len(xml_calls) == len(studies)
    assert all(str(r.fulltext_path).endswith(".xml") for r in results)


@pytest.mark.asyncio
async def test_fetch_many_full_texts_single_page_complete_pdf_returns_gracefully(
    mocker, test_settings, test_study_collection, tmp_path
):
    """
    Ensure a single page open access item is handled correctly.

    We can't just assume that single page PDFs are incomplete!
    """
    fetcher = ElsevierFetcher(settings=test_settings)
    studies = test_study_collection.studies

    pdf_responses = [
        response
        for _ in studies
        for response in (
            httpx.Response(status_code=httpx.codes.OK, content=b"PDF content"),
        )
    ]
    mocked_stream = mocker.patch(
        "fer.fetching.elsevier.stream_file",
        new=mocker.AsyncMock(
            side_effect=[
                await fake_stream_file(
                    url="http://example.com/article.pdf",
                    destination=tmp_path / f"{study.uid}.pdf",
                    pdf_content=b"PDF content",
                )
                for study in test_study_collection.studies
            ]
        ),
    )
    mock_fetch = mocker.patch.object(
        ElsevierFetcher,
        "_elsevier_request",
        new=mocker.AsyncMock(side_effect=pdf_responses),
    )
    mocker.patch.object(ElsevierFetcher, "_is_single_page_pdf", return_value=True)

    results = await fetcher.fetch_many_full_texts(
        study_collection=test_study_collection, output_directory=tmp_path
    )

    elsevier_request_configs = [
        call.kwargs.get("elsevier_request_config") for call in mock_fetch.call_args_list
    ]
    stream_file_headers = [
        call.kwargs.get("headers") for call in mocked_stream.call_args_list
    ]
    pdf_calls = [
        header
        for header in stream_file_headers
        if header.get("Accept") == "application/pdf"
    ]

    xml_calls = [
        config
        for config in elsevier_request_configs
        if config.headers.get("Accept") == "text/xml"
    ]

    assert len(pdf_calls) == len(studies)
    assert len(xml_calls) == 0
    assert all(str(r.fulltext_path).endswith(".pdf") for r in results)


@pytest.mark.asyncio
async def test_fetch_many_full_texts_multi_page_complete_pdf_returns_gracefully(
    mocker, test_settings, test_study_collection, tmp_path
):
    """Ensure that the normal case of a multi-page open access item is handled correctly."""
    fetcher = ElsevierFetcher(settings=test_settings)
    studies = test_study_collection.studies

    pdf_responses = [
        response
        for _ in studies
        for response in (
            httpx.Response(status_code=httpx.codes.OK, content=b"PDF content"),
        )
    ]
    mock_stream = mocker.patch(
        "fer.fetching.elsevier.stream_file",
        new=mocker.AsyncMock(
            side_effect=[
                await fake_stream_file(
                    url="http://example.com/article.pdf",
                    destination=tmp_path / f"{study.uid}.pdf",
                    pdf_content=b"PDF content",
                )
                for study in test_study_collection.studies
            ]
        ),
    )
    mock_fetch = mocker.patch.object(
        ElsevierFetcher,
        "_elsevier_request",
        new=mocker.AsyncMock(side_effect=pdf_responses),
    )
    mocker.patch.object(ElsevierFetcher, "_is_single_page_pdf", return_value=False)

    results = await fetcher.fetch_many_full_texts(
        study_collection=test_study_collection, output_directory=tmp_path
    )

    elsevier_request_configs = [
        call.kwargs.get("elsevier_request_config") for call in mock_fetch.call_args_list
    ]
    stream_file_headers = [
        call.kwargs.get("headers") for call in mock_stream.call_args_list
    ]
    pdf_calls = [
        header
        for header in stream_file_headers
        if header.get("Accept") == "application/pdf"
    ]

    xml_calls = [
        config
        for config in elsevier_request_configs
        if config.headers.get("Accept") == "text/xml"
    ]

    assert len(pdf_calls) == len(studies)
    assert len(xml_calls) == 0
    assert all(str(r.fulltext_path).endswith(".pdf") for r in results)


@pytest.mark.asyncio
async def test_fetch_many_full_texts_single_page_closed_access_pdf_orphan_file_is_deleted(
    mocker, test_settings, test_study_collection, tmp_path
):
    orphan_pdf = tmp_path / f"{test_study_collection.studies[0].uid}.pdf"
    orphan_pdf.write_bytes(b"placeholder")
    fetcher = ElsevierFetcher(settings=test_settings)

    sequential_responses = [
        response
        for _ in test_study_collection.studies
        for response in (
            httpx.Response(status_code=httpx.codes.OK, content=b"PDF content"),
            httpx.Response(status_code=httpx.codes.OK, content=b"<xml>content</xml>"),
        )
    ]
    mocker.patch(
        "fer.fetching.elsevier.stream_file",
        new=mocker.AsyncMock(
            side_effect=IncompleteFullTextError("Test incomplete PDF error")
        ),
    )
    mocker.patch.object(
        ElsevierFetcher,
        "_elsevier_request",
        new=mocker.AsyncMock(side_effect=sequential_responses),
    )
    mocker.patch.object(ElsevierFetcher, "_is_single_page_pdf", return_value=True)

    await fetcher.fetch_many_full_texts(
        study_collection=test_study_collection, output_directory=tmp_path
    )
    assert (
        not orphan_pdf.exists()
    ), "Orphan single page PDF should be deleted after falling back to XML fetch."


async def test_get_final_fulltext_content_happy_path_multi_page_pdf(
    mocker, test_settings, tmp_path
):
    test_uuid = uuid4()
    test_doi = "10.1234/testdoi"
    url = "http://example.com/file.pdf"
    temp_file = tmp_path / "temp.pdf"
    temp_file.write_bytes(b"PDF content")

    mock_responses = [
        httpx.Response(status_code=httpx.codes.OK, content=b"PDF content"),
    ]
    mocker.patch("fer.fetching.elsevier.stream_file", return_value=temp_file)
    fetcher = ElsevierFetcher(settings=test_settings)

    mocker.patch.object(ElsevierFetcher, "_is_single_page_pdf", return_value=False)
    mocker.patch.object(
        ElsevierFetcher,
        "_elsevier_request",
        new=mocker.AsyncMock(side_effect=mock_responses),
    )
    fulltext = await fetcher.get_final_fulltext_content(
        url, temp_file, test_doi, test_uuid
    )
    assert fulltext.fulltext_path.exists()
    assert fulltext.file_format == "pdf"
    assert fulltext.error is None


async def test_get_final_fulltext_content_happy_path_single_page_pdf(
    mocker, test_settings, tmp_path
):
    test_uuid = uuid4()
    test_doi = "10.1234/testdoi"
    url = "http://example.com/file.pdf"
    temp_file = tmp_path / "temp.pdf"
    temp_file.write_bytes(b"PDF content")

    mock_responses = [
        httpx.Response(status_code=httpx.codes.OK, content=b"PDF content"),
    ]
    mocker.patch("fer.fetching.elsevier.stream_file", return_value=temp_file)
    fetcher = ElsevierFetcher(settings=test_settings)

    mocker.patch.object(ElsevierFetcher, "_is_single_page_pdf", return_value=True)
    mocker.patch.object(
        ElsevierFetcher,
        "_elsevier_request",
        new=mocker.AsyncMock(side_effect=mock_responses),
    )
    fulltext = await fetcher.get_final_fulltext_content(
        url, temp_file, test_doi, test_uuid
    )
    assert fulltext.fulltext_path.exists()
    assert fulltext.file_format == "pdf"
    assert fulltext.error is None


async def test_get_final_fulltext_content_closed_access_single_page_pdf_returns_xml(
    mocker, test_settings, tmp_path
):
    test_uuid = uuid4()
    test_doi = "10.1234/testdoi"
    url = "http://example.com/file.pdf"
    temp_file = tmp_path / "temp.pdf"
    temp_file.write_bytes(b"PDF content")

    mock_responses = [
        httpx.Response(status_code=httpx.codes.OK, content=b"PDF content"),
    ]
    mocker.patch("fer.fetching.elsevier.stream_file", return_value=temp_file)
    fetcher = ElsevierFetcher(settings=test_settings)

    mocker.patch.object(ElsevierFetcher, "_is_single_page_pdf", return_value=True)
    mocker.patch.object(
        ElsevierFetcher,
        "_elsevier_request",
        new=mocker.AsyncMock(side_effect=mock_responses),
    )
    fulltext = await fetcher.get_final_fulltext_content(
        url, temp_file, test_doi, test_uuid, is_incomplete_pdf=True
    )
    assert fulltext.fulltext_path.exists()
    assert fulltext.file_format == "xml"
    assert fulltext.error is None


@pytest.mark.parametrize(
    "elsevier_request_error",
    [
        httpx.HTTPError("Test HTTP error"),
        ProxyConnectionError("Test proxy connection error"),
        FullTextStreamError("Test stream error"),
    ],
)
async def test_get_final_fulltext_content_fails(
    mocker, test_settings, tmp_path, elsevier_request_error
):
    test_uuid = uuid4()
    test_doi = "10.1234/testdoi"
    url = "http://example.com/file.pdf"
    temp_file = tmp_path / "temp.pdf"
    temp_file.write_bytes(b"PDF content")

    mocker.patch("fer.fetching.elsevier.stream_file", return_value=temp_file)
    fetcher = ElsevierFetcher(settings=test_settings)

    mocker.patch.object(ElsevierFetcher, "_is_single_page_pdf", return_value=True)
    mocker.patch.object(
        ElsevierFetcher,
        "_elsevier_request",
        new=mocker.AsyncMock(side_effect=elsevier_request_error),
    )
    response = await fetcher.get_final_fulltext_content(
        url, temp_file, test_doi, test_uuid, is_incomplete_pdf=True
    )

    assert response.fulltext_path is None
    assert response.error is not None
    error_text = str(elsevier_request_error)
    assert error_text in response.error
