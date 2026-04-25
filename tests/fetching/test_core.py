from uuid import uuid4

import httpx
import pytest
from destiny_sdk.identifiers import DOIIdentifier, ExternalIdentifierType
from pytest_httpx import IteratorStream

from fer.fetching.core import (
    AsyncHTTPXRetryClient,
    FullTextStreamError,
    IncompleteFullTextError,
    OpenAlexStudy,
    OpenAlexStudyCollection,
    Study,
    StudyCollection,
    download_temporary_file,
    stream_file,
)
from fer.fetching.elsevier import ElsevierFetcher


def test_study_collection_iterable():
    test_dois = [
        DOIIdentifier(identifier=doi_string, identifier_type=ExternalIdentifierType.DOI)
        for doi_string in ["10.1000/xyz123", "10.1000/xyz456"]
    ]
    study1 = Study(doi=test_dois[0], uid=uuid4())
    study2 = Study(doi=test_dois[1], uid=uuid4())
    collection = StudyCollection(studies=[study1, study2])

    collected_dois = [study.doi.identifier for study in collection.studies]
    collected_uids = [str(study.uid) for study in collection.studies]
    assert collected_uids == [str(study.uid) for study in collection.studies]
    assert collected_dois == [doi.identifier for doi in test_dois]


def test_study_collection_remove_study_by_doi(test_dois):
    test_doi_identifiers = [
        DOIIdentifier(identifier=doi_string, identifier_type=ExternalIdentifierType.DOI)
        for doi_string in test_dois
    ]
    test_studies = [
        Study(doi=test_doi, uid=test_uid)
        for test_doi, test_uid in zip(
            test_doi_identifiers, [uuid4(), uuid4()], strict=False
        )
    ]
    collection = StudyCollection(studies=test_studies)

    collection.remove_study_by_doi(test_dois[0])

    remaining_dois = [study.doi.identifier for study in collection.studies]
    assert remaining_dois == test_dois[1:], "All but the first DOI should remain."


def test_openalex_study_collection_remove_study_by_openalex_id(test_openalex_ids):
    openalex_string_ids = [
        str(openalex_id.identifier) for openalex_id in test_openalex_ids
    ]
    test_openalex_studies = [
        OpenAlexStudy(uid=test_uid, openalex_id=openalex_id)
        for test_uid, openalex_id in zip(
            [uuid4(), uuid4()], test_openalex_ids, strict=False
        )
    ]
    collection = OpenAlexStudyCollection(studies=test_openalex_studies)

    collection.remove_study_by_openalex_id(openalex_string_ids[0])

    remaining_openalex_ids = [
        str(study.openalex_id.identifier) for study in collection.studies
    ]
    assert (
        remaining_openalex_ids == openalex_string_ids[1:]
    ), "All but the first OpenAlex ID should remain."


@pytest.mark.asyncio
async def test_async_httpx_retry_client_context_manager():
    test_max_retries = 2
    async with AsyncHTTPXRetryClient(max_retries=test_max_retries) as client:
        assert isinstance(client, AsyncHTTPXRetryClient)
        assert client.max_retries == test_max_retries


@pytest.mark.asyncio
async def test_download_temporary_file(mocker, tmp_path):
    temp_file = tmp_path / "mocked_temp_file"
    temp_file.write_bytes(b"test content")
    mocker.patch("fer.fetching.core.stream_file", return_value=temp_file)

    test_url = "http://example.com/testfile"
    temp_file_path = await download_temporary_file(test_url)

    assert temp_file_path.exists(), "Temporary file should exist"

    temp_file_path.unlink()

    assert not temp_file_path.exists(), "Temporary file should be deleted"


def test_delete_temporary_file(temporary_test_file):
    temporary_test_file.write_text("Temporary file content")

    assert temporary_test_file.exists(), "Temporary file should exist before deletion"

    temporary_test_file.unlink()

    assert not temporary_test_file.exists(), "Temporary file should be deleted"


@pytest.mark.asyncio
async def test_stream_file_success(httpx_mock, temporary_test_file):
    test_url = "http://example.com/streamfile"
    test_content = b"streamed content"
    httpx_mock.add_response(method="GET", url=test_url, content=test_content)
    streamed_file_path = await stream_file(test_url, temporary_test_file)
    assert streamed_file_path.exists(), "Streamed file should exist"
    content = streamed_file_path.read_bytes()
    assert content == test_content, "Streamed content should match expected content"


@pytest.mark.asyncio
async def test_stream_file_destination_exists(mocker, caplog, temporary_test_file):
    mocked_httpx_stream = mocker.patch("httpx.stream")
    test_url = "http://example.com/streamfile"
    temporary_test_file.write_text("Existing content")

    with caplog.at_level("INFO"):
        streamed_file_path = await stream_file(test_url, temporary_test_file)

    assert (
        streamed_file_path == temporary_test_file
    ), "Streamed file path should match existing file"
    assert (
        "File already exists" in caplog.text
    ), "Expect that we logged that the file already exists"

    assert (
        mocked_httpx_stream.call_count == 0
    ), "Expect that httpx.stream should not be called"


@pytest.mark.asyncio
async def test_stream_file_http_error(httpx_mock, temporary_test_file):
    test_url = "http://example.com/streamfile"

    httpx_mock.add_response(method="GET", url=test_url, status_code=404)

    with pytest.raises(FullTextStreamError) as error_info:
        await stream_file(test_url, temporary_test_file)
    assert "Error downloading" in str(
        error_info.value
    ), "Expect an error message about downloading"


@pytest.mark.asyncio
async def test_stream_file_stream_error(httpx_mock, temporary_test_file):
    test_url = "http://example.com/streamfile"

    httpx_mock.add_exception(
        httpx.StreamError("Stream failed"), method="GET", url=test_url
    )

    with pytest.raises(FullTextStreamError) as error_info:
        await stream_file(test_url, temporary_test_file)
    assert "Streaming error" in str(
        error_info.value
    ), "Expect an error message about streaming"


@pytest.mark.asyncio
async def test_stream_file_empty_downloaded_file(
    httpx_mock, temporary_test_file, caplog
):
    test_url = "http://example.com/streamfile"

    httpx_mock.add_response(method="GET", url=test_url, content=b"")

    with caplog.at_level("ERROR"):
        streamed_file_path = await stream_file(test_url, temporary_test_file)

    assert (
        "File empty - removing empty file" in caplog.text
    ), "Expect an error message about empty streamed file"
    assert not temporary_test_file.exists(), "Empty file should be deleted"
    assert streamed_file_path is None, "Function should return None for empty file"


@pytest.mark.asyncio
async def test_stream_file_response_validation_elsevier_els_status_not_ok(
    httpx_mock, temporary_test_file, caplog
):
    test_url = "http://example.com/elsevier/streamfile"

    httpx_mock.add_response(
        method="GET",
        url=test_url,
        content=b"",
        headers={"X-ELS-Status": "PDF_RESTRICTED"},
    )
    with (
        pytest.raises(IncompleteFullTextError) as error_info,
        caplog.at_level("WARNING"),
    ):
        await stream_file(
            test_url,
            temporary_test_file,
            response_validator=ElsevierFetcher._check_els_status,
        )

    assert "Elsevier download returned restricted response" in str(
        error_info.value
    ), "Expect a warning message about incomplete Elsevier full text"
    assert not temporary_test_file.exists(), "Incomplete file should be deleted"


@pytest.mark.asyncio
async def test_stream_file_appends_all_chunks(mocker, temporary_test_file):
    test_url = "http://example.com/streamfile"
    chunks = [b"first ", b"second ", b"third"]

    mock_response = mocker.MagicMock()
    mock_response.headers = {}
    mock_response.__aenter__.return_value = mock_response
    mock_response.__aexit__.return_value = None
    mock_response.aiter_bytes.return_value = IteratorStream(chunks)
    mock_response.raise_for_status.return_value = None

    mocker.patch("httpx.AsyncClient.stream", return_value=mock_response)

    streamed_file_path = await stream_file(test_url, temporary_test_file)
    assert streamed_file_path.exists(), "Streamed file should exist"
    content = streamed_file_path.read_bytes()
    assert content == b"".join(
        chunks
    ), "File should contain all concatenated chunks and not overwrite."
    assert streamed_file_path.exists()
