import httpx
import pytest
from pydantic import HttpUrl

from fer.fetching.core import FullTextStreamError
from fer.fetching.unpaywall import UnpaywallFetcher


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
    mocker.patch(
        "fer.fetching.unpaywall.stream_file", return_value=tmp_path / "dummy.pdf"
    )
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None
    mock_response.json = mocker.AsyncMock(return_value=test_data)

    mock_get = mocker.patch(
        "fer.fetching.unpaywall.AsyncHTTPXRetryClient.get",
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
    test_uids = [study.uid for study in test_study_collection.studies]
    test_data = {
        "best_oa_location": {"url_for_pdf": "http://example.com/article.pdf"},
        "publisher": publisher,
    }
    fetcher = UnpaywallFetcher(settings=test_settings)
    mocker.patch("fer.fetching.unpaywall.stream_file")
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None
    mock_response.json = mocker.AsyncMock(return_value=test_data)

    mock_get = mocker.patch(
        "fer.fetching.unpaywall.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("WARNING"):
        await fetcher.fetch_many_full_texts(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )

    assert mock_get.call_count == len(test_study_collection.studies)
    assert all(
        f"Unpaywall PDF not found for {uid=}, {doi=}" in caplog.text
        for uid, doi in zip(test_uids, test_dois, strict=False)
    )
    assert publisher in caplog.text
    assert all(str(uid) in caplog.text for uid in test_uids)
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
    test_uids = [study.uid for study in test_study_collection.studies]
    test_data = {
        "best_oa_location": {
            "url_for_pdf": "http://example.com/tandfonline/article.pdf"
        },
        "publisher": "Test Publisher",
    }
    fetcher = UnpaywallFetcher(settings=test_settings)
    mocker.patch("fer.fetching.unpaywall.stream_file")
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None
    mock_response.json = mocker.AsyncMock(return_value=test_data)

    mock_get = mocker.patch(
        "fer.fetching.unpaywall.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("WARNING"):
        await fetcher.fetch_many_full_texts(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )

    assert mock_get.call_count == len(test_study_collection.studies)
    assert all(
        f"Unpaywall PDF not found for {uid=}, {doi=}" in caplog.text
        for uid, doi in zip(test_uids, test_dois, strict=False)
    )
    assert "taylor_and_francis_in_url=True" in caplog.text
    assert all(str(uid) in caplog.text for uid in test_uids)
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
        "fer.fetching.unpaywall.AsyncHTTPXRetryClient.get",
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
        "fer.fetching.unpaywall.stream_file",
        side_effect=FullTextStreamError("test error"),
    )
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None
    mock_response.json = mocker.AsyncMock(return_value=test_data)

    mock_get = mocker.patch(
        "fer.fetching.unpaywall.AsyncHTTPXRetryClient.get",
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
    mocker.patch(
        "fer.fetching.unpaywall.stream_file", return_value=tmp_path / "dummy.pdf"
    )
    mock_response = mocker.MagicMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status.return_value = None
    mock_response.json = mocker.AsyncMock(return_value=test_data)

    mock_get = mocker.patch(
        "fer.fetching.unpaywall.AsyncHTTPXRetryClient.get",
        new=mocker.AsyncMock(return_value=mock_response),
    )

    with caplog.at_level("WARNING"):
        await fetcher.fetch_many_full_texts(
            study_collection=test_study_collection,
            output_directory=tmp_path,
        )

    assert mock_get.call_count == len(test_study_collection.studies)
    assert "Unpaywall PDF URL not found" in caplog.text
    assert all(uid in caplog.text for uid in test_uids)
    assert all(doi in caplog.text for doi in test_dois)


@pytest.mark.parametrize(
    ("data", "expected_url"),
    [
        (
            {"best_oa_location": {"url_for_pdf": "http://example.com/article.pdf"}},
            None,
        ),
        (
            "https://example.com/article.pdf",
            HttpUrl("https://example.com/article.pdf"),
        ),
        (
            None,
            None,
        ),
    ],
)
def test_validate_pdf_url(data, expected_url):
    fetcher = UnpaywallFetcher(settings={})

    validated_url = fetcher.validate_pdf_url("10.1000/testdoi", data)
    assert validated_url == expected_url


@pytest.mark.parametrize(
    ("pdf_strategy", "data", "expected_url"),
    [
        (
            ["best_oa_location", "url_for_pdf"],
            {"best_oa_location": {"url_for_pdf": "http://example.com/case_1.pdf"}},
            HttpUrl("http://example.com/case_1.pdf"),
        ),
        (
            ["best_oa_location", "url_for_pdf"],
            {"best_oa_location": {"url_for_html": "http://example.com/case_1.html"}},
            None,
        ),
        (
            ["alternative_location", "pdf_url"],
            {"best_oa_location": {"url_for_pdf": "http://example.com/case_3.pdf"}},
            None,
        ),
        (
            "invalid_strategy",
            {"best_oa_location": {"url_for_pdf": "http://example.com/case_4.pdf"}},
            None,
        ),
        (
            ["best_oa_location"],
            {"best_oa_location": {"url_for_pdf": "http://example.com/case_5.pdf"}},
            None,
        ),
        (
            ["best_oa_location", "url_for_pdf"],
            {"best_oa_location": {"url_for_pdf": "not-a-valid-url"}},
            None,
        ),
    ],
)
@pytest.mark.asyncio
async def test_retrieve_pdf_url(pdf_strategy, data, expected_url):
    fetcher = UnpaywallFetcher(settings={})

    result_url = await fetcher.retrieve_pdf_url(pdf_strategy, "10.1000/testdoi", data)
    assert result_url == expected_url


@pytest.mark.asyncio
async def test_process_single_study_response_pdf_found(
    mocker, test_settings, tmp_path, test_study_collection
):
    test_doi = test_study_collection.studies[0].doi.identifier
    test_uid = test_study_collection.studies[0].uid

    fetcher = UnpaywallFetcher(settings=test_settings)
    mock_response_data = {
        "best_oa_location": {"url_for_pdf": "http://example.com/article.pdf"},
        "publisher": "Test Publisher",
    }
    mock_response = mocker.AsyncMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status = mocker.MagicMock(return_value=None)
    mock_response.json = mocker.AsyncMock(return_value=mock_response_data)

    mocker.patch(
        "fer.fetching.unpaywall.AsyncHTTPXRetryClient.get", return_value=mock_response
    )
    mocker.patch(
        "fer.fetching.unpaywall.stream_file", return_value=tmp_path / "dummy.pdf"
    )

    retrieved_fulltext = await fetcher.process_single_study_response(
        study=test_study_collection.studies[0],
        output_directory=tmp_path,
    )

    assert retrieved_fulltext.doi == test_doi
    assert retrieved_fulltext.uid == test_uid
    assert retrieved_fulltext.pdf_path == tmp_path / "dummy.pdf"


@pytest.mark.asyncio
async def test_process_single_study_response_fails_no_pdf_strategy(
    mocker, test_settings, tmp_path, test_study_collection
):
    test_doi = test_study_collection.studies[0].doi.identifier
    test_uid = test_study_collection.studies[0].uid

    fetcher = UnpaywallFetcher(settings=test_settings)
    fetcher.api_config.unpack_strategy.pdf_link_strategy = None
    mock_response_data = {
        "best_oa_location": {"url_for_pdf": "http://example.com/article.pdf"},
        "publisher": "Test Publisher",
    }
    mock_response = mocker.AsyncMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status = mocker.MagicMock(return_value=None)
    mock_response.json = mocker.AsyncMock(return_value=mock_response_data)

    mocker.patch(
        "fer.fetching.unpaywall.AsyncHTTPXRetryClient.get", return_value=mock_response
    )
    retrieved_fulltext = await fetcher.process_single_study_response(
        study=test_study_collection.studies[0],
        output_directory=tmp_path,
    )

    assert retrieved_fulltext.doi == test_doi
    assert retrieved_fulltext.uid == test_uid
    assert retrieved_fulltext.pdf_path is None


@pytest.mark.asyncio
async def test_process_single_study_response_fails_no_pdf_url(
    mocker, test_settings, tmp_path, test_study_collection
):
    test_doi = test_study_collection.studies[0].doi.identifier
    test_uid = test_study_collection.studies[0].uid

    fetcher = UnpaywallFetcher(settings=test_settings)
    fetcher.api_config.unpack_strategy.pdf_link_strategy = None
    mock_response_data = {
        "best_oa_location": {"url_for_pdf": None},
        "publisher": "Test Publisher",
    }
    mock_response = mocker.AsyncMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status = mocker.MagicMock(return_value=None)
    mock_response.json = mocker.AsyncMock(return_value=mock_response_data)

    mocker.patch(
        "fer.fetching.unpaywall.AsyncHTTPXRetryClient.get", return_value=mock_response
    )
    retrieved_fulltext = await fetcher.process_single_study_response(
        study=test_study_collection.studies[0],
        output_directory=tmp_path,
    )

    assert retrieved_fulltext.doi == test_doi
    assert retrieved_fulltext.uid == test_uid
    assert retrieved_fulltext.pdf_path is None


@pytest.mark.parametrize(
    ("publisher", "url"),
    [
        ("Wiley", "http://example.com/article.pdf"),
        ("Elsevier BV", "http://example.com/article.pdf"),
        ("SAGE Publications", "http://example.com/article.pdf"),
        ("Test Publisher", "http://example.com/tandfonline/article.pdf"),
    ],
)
@pytest.mark.asyncio
async def test_process_single_study_response_fails_pdf_not_found_publisher_url(
    mocker, test_settings, tmp_path, test_study_collection, publisher, url
):
    test_doi = test_study_collection.studies[0].doi.identifier
    test_uid = test_study_collection.studies[0].uid

    fetcher = UnpaywallFetcher(settings=test_settings)
    fetcher.api_config.unpack_strategy.pdf_link_strategy = None
    mock_response_data = {
        "best_oa_location": {"url_for_pdf": url},
        "publisher": publisher,
    }
    mock_response = mocker.AsyncMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status = mocker.MagicMock(return_value=None)
    mock_response.json = mocker.AsyncMock(return_value=mock_response_data)

    mocker.patch(
        "fer.fetching.unpaywall.AsyncHTTPXRetryClient.get", return_value=mock_response
    )
    retrieved_fulltext = await fetcher.process_single_study_response(
        study=test_study_collection.studies[0],
        output_directory=tmp_path,
    )

    assert retrieved_fulltext.doi == test_doi
    assert retrieved_fulltext.uid == test_uid
    assert retrieved_fulltext.pdf_path is None


@pytest.mark.asyncio
async def test_process_single_study_response_fails_no_output_file_path(
    mocker, test_settings, tmp_path, test_study_collection
):
    test_doi = test_study_collection.studies[0].doi.identifier
    test_uid = test_study_collection.studies[0].uid

    fetcher = UnpaywallFetcher(settings=test_settings)
    mock_response_data = {
        "best_oa_location": {"url_for_pdf": "http://example.com/article.pdf"},
        "publisher": "Test Publisher",
    }
    mock_response = mocker.AsyncMock()
    mock_response.status_code = httpx.codes.OK
    mock_response.raise_for_status = mocker.MagicMock(return_value=None)
    mock_response.json = mocker.AsyncMock(return_value=mock_response_data)

    mocker.patch(
        "fer.fetching.unpaywall.AsyncHTTPXRetryClient.get", return_value=mock_response
    )
    mocker.patch("fer.fetching.unpaywall.stream_file", return_value=None)

    retrieved_fulltext = await fetcher.process_single_study_response(
        study=test_study_collection.studies[0],
        output_directory=tmp_path,
    )

    assert retrieved_fulltext.doi == test_doi
    assert retrieved_fulltext.uid == test_uid
    assert retrieved_fulltext.pdf_path is None


@pytest.mark.asyncio
async def test_process_single_study_response_fails_http_error(
    mocker, test_settings, tmp_path, test_study_collection
):
    test_doi = test_study_collection.studies[0].doi.identifier
    test_uid = test_study_collection.studies[0].uid

    fetcher = UnpaywallFetcher(settings=test_settings)

    mocker.patch(
        "fer.fetching.unpaywall.AsyncHTTPXRetryClient.get",
        side_effect=httpx.HTTPError("Test HTTP error"),
    )

    retrieved_fulltext = await fetcher.process_single_study_response(
        study=test_study_collection.studies[0],
        output_directory=tmp_path,
    )

    assert retrieved_fulltext.doi == test_doi
    assert retrieved_fulltext.uid == test_uid
    assert retrieved_fulltext.pdf_path is None


@pytest.mark.asyncio
async def test_process_single_study_response_fails_full_text_stream_error(
    mocker, test_settings, tmp_path, test_study_collection
):
    test_doi = test_study_collection.studies[0].doi.identifier
    test_uid = test_study_collection.studies[0].uid

    fetcher = UnpaywallFetcher(settings=test_settings)

    mocker.patch(
        "fer.fetching.unpaywall.AsyncHTTPXRetryClient.get",
        side_effect=FullTextStreamError("Test HTTP error"),
    )

    retrieved_fulltext = await fetcher.process_single_study_response(
        study=test_study_collection.studies[0],
        output_directory=tmp_path,
    )

    assert retrieved_fulltext.doi == test_doi
    assert retrieved_fulltext.uid == test_uid
    assert retrieved_fulltext.pdf_path is None
