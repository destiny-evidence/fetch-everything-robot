from collections.abc import AsyncGenerator
from uuid import uuid4

import httpx2
import pytest
from destiny_sdk.identifiers import DOIIdentifier, ExternalIdentifierType

from fer.fetching.core import (
    AsyncHTTPXRetryClient,
    DOIStudy,
    DOIStudyCollection,
    FullTextStreamError,
    IncompleteFullTextError,
    OpenAlexStudy,
    OpenAlexStudyCollection,
    download_temporary_file,
    stream_file,
)
from fer.fetching.elsevier import ElsevierFetcher


async def _one_chunk_data(data: bytes) -> AsyncGenerator[bytes]:
    """
    Produce a generator for a single chunk of data.

    Args:
        data (bytes): The data to yield as a single chunk.

    Returns:
        AsyncGenerator[bytes, None]: A generator yielding the single chunk of data.

    Yields:
        Iterator[AsyncGenerator[bytes, None]]: The single chunk of data.

    """
    yield data


async def _many_chunk_data(chunks: list[bytes]) -> AsyncGenerator[bytes]:
    """
    Produce a generator for multiple chunks of data.


    Args:
        chunks (list[bytes]): The list of chunks to yield.

    Returns:
        AsyncGenerator[bytes, None]: A generator yielding the chunks of data.

    Yields:
        Iterator[AsyncGenerator[bytes, None]]: The chunks of data.

    """
    for chunk in chunks:
        yield chunk


def test_study_collection_iterable():
    test_dois = [
        DOIIdentifier(identifier=doi_string, identifier_type=ExternalIdentifierType.DOI)
        for doi_string in ["10.1000/xyz123", "10.1000/xyz456"]
    ]
    study1 = DOIStudy(doi=test_dois[0], uid=uuid4())
    study2 = DOIStudy(doi=test_dois[1], uid=uuid4())
    collection = DOIStudyCollection(studies=[study1, study2])

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
        DOIStudy(doi=test_doi, uid=test_uid)
        for test_doi, test_uid in zip(
            test_doi_identifiers, [uuid4(), uuid4()], strict=False
        )
    ]
    collection = DOIStudyCollection(studies=test_studies)

    collection.remove_study_by_identifier(test_dois[0])

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

    collection.remove_study_by_identifier(openalex_string_ids[0])

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


def test_async_httpx_retry_client_uses_proxy_transport(mocker):
    test_max_retries = 5
    test_proxy_url = "socks5://127.0.0.1:1080"
    mocked_transport = mocker.sentinel.transport

    patched_transport = mocker.patch(
        "fer.fetching.core.httpx2.AsyncHTTPTransport",
        return_value=mocked_transport,
    )
    patched_client_init = mocker.patch(
        "fer.fetching.core.httpx2.AsyncClient.__init__",
        return_value=None,
    )

    client = AsyncHTTPXRetryClient(
        max_retries=test_max_retries,
        proxy_url=test_proxy_url,
    )

    patched_transport.assert_called_once_with(
        proxy=test_proxy_url,
        retries=test_max_retries,
    )
    patched_client_init.assert_called_once()
    assert patched_client_init.call_args.kwargs["transport"] is mocked_transport
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
async def test_stream_file_success(mocker, temporary_test_file):
    test_url = "http://example.com/streamfile"
    test_content = b"streamed content"
    mock_response = mocker.MagicMock()
    mock_response.__aenter__.return_value = mock_response
    mock_response.__aexit__.return_value = None
    mock_response.raise_for_status.return_value = None
    mock_response.aiter_bytes.return_value = _many_chunk_data([test_content])

    mocker.patch("httpx2.AsyncClient.stream", return_value=mock_response)
    streamed_file_path = await stream_file(test_url, temporary_test_file)
    assert streamed_file_path.exists(), "Streamed file should exist"
    content = streamed_file_path.read_bytes()
    assert content == test_content, "Streamed content should match expected content"


@pytest.mark.asyncio
async def test_stream_file_destination_exists(mocker, caplog, temporary_test_file):
    mocked_httpx_stream = mocker.patch("httpx2.stream")
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
    ), "Expect that httpx2.stream should not be called"


@pytest.mark.asyncio
async def test_stream_file_http_error(mocker, temporary_test_file):
    test_url = "http://example.com/streamfile"
    mocked_response = mocker.MagicMock()
    request = httpx2.Request("GET", test_url)
    response = httpx2.Response(status_code=404, request=request)
    mocked_response.__aenter__.return_value = mocked_response
    mocked_response.__aexit__.return_value = None
    mocked_response.raise_for_status.side_effect = httpx2.HTTPStatusError(
        "Not Found",
        request=request,
        response=response,
    )
    mocker.patch("httpx2.AsyncClient.stream", return_value=mocked_response)

    with pytest.raises(FullTextStreamError) as error_info:
        await stream_file(test_url, temporary_test_file)
    assert "Error downloading" in str(
        error_info.value
    ), "Expect an error message about downloading"


@pytest.mark.asyncio
async def test_stream_file_stream_error(mocker, temporary_test_file):
    test_url = "http://example.com/streamfile"

    mocked_response = mocker.MagicMock()
    mocked_response.__aenter__.return_value = mocked_response
    mocked_response.__aexit__.return_value = None
    mocked_response.raise_for_status.side_effect = httpx2.StreamError("Stream failed")
    mocker.patch("httpx2.AsyncClient.stream", return_value=mocked_response)

    with pytest.raises(FullTextStreamError) as error_info:
        await stream_file(test_url, temporary_test_file)
    assert "Streaming error" in str(
        error_info.value
    ), "Expect an error message about streaming"


@pytest.mark.asyncio
async def test_stream_file_empty_downloaded_file(mocker, temporary_test_file, caplog):
    test_url = "http://example.com/streamfile"

    mocked_response = mocker.MagicMock()
    mocked_response.__aenter__.return_value = mocked_response
    mocked_response.__aexit__.return_value = None
    mocked_response.raise_for_status.side_effect = None
    mocked_response.aiter_bytes.return_value = _one_chunk_data(b"")

    mocker.patch("httpx2.AsyncClient.stream", return_value=mocked_response)

    with caplog.at_level("ERROR"):
        streamed_file_path = await stream_file(test_url, temporary_test_file)

    assert (
        "File empty - removing empty file" in caplog.text
    ), "Expect an error message about empty streamed file"
    assert not temporary_test_file.exists(), "Empty file should be deleted"
    assert streamed_file_path is None, "Function should return None for empty file"


@pytest.mark.asyncio
async def test_stream_file_response_validation_elsevier_els_status_not_ok(
    mocker, temporary_test_file, caplog
):
    test_url = "http://example.com/elsevier/streamfile"

    mocked_response = mocker.MagicMock()
    mocked_response.__aenter__.return_value = mocked_response
    mocked_response.__aexit__.return_value = None
    mocked_response.raise_for_status.side_effect = None
    mocked_response.aiter_bytes.return_value = _one_chunk_data(b"")
    mocked_response.headers = {"X-ELS-Status": "PDF_RESTRICTED"}

    mocker.patch("httpx2.AsyncClient.stream", return_value=mocked_response)
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
    mock_response.aiter_bytes.return_value = _many_chunk_data(chunks)
    mock_response.raise_for_status.return_value = None

    mocker.patch("httpx2.AsyncClient.stream", return_value=mock_response)

    streamed_file_path = await stream_file(test_url, temporary_test_file)
    assert streamed_file_path.exists(), "Streamed file should exist"
    content = streamed_file_path.read_bytes()
    assert content == b"".join(
        chunks
    ), "File should contain all concatenated chunks and not overwrite."
    assert streamed_file_path.exists()
