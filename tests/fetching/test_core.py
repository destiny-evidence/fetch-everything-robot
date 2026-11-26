import asyncio
from collections.abc import AsyncGenerator
from uuid import uuid4

import httpx2
import pytest
from destiny_sdk.identifiers import DOIIdentifier, ExternalIdentifierType
from pytest_mock import MockerFixture

from fer.fetching.core import (
    AsyncHTTPXRetryClient,
    DOIStudy,
    DOIStudyCollection,
    FullTextStreamError,
    IncompleteFullTextError,
    stream_file,
)
from fer.fetching.elsevier import ElsevierFetcher


async def _one_chunk_data(data: bytes) -> AsyncGenerator[bytes]:
    """
    Produce a generator for a single chunk of data.

    Args:
        data (bytes): The data to yield as a single chunk.

    Yields:
        bytes: The single chunk of data.

    """
    yield data


async def _many_chunk_data(chunks: list[bytes]) -> AsyncGenerator[bytes]:
    """
    Produce a generator for multiple chunks of data.


    Args:
        chunks (list[bytes]): The list of chunks to yield.

    Yields:
        bytes: The chunks of data.

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


def test_study_collection_remove_study_by_unique_identifier(test_dois):
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

    collection.remove_study_by_unique_identifier(test_studies[0].uid)

    remaining_dois = [study.doi.identifier for study in collection.studies]
    assert remaining_dois == test_dois[1:], "All but the first DOI should remain."


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


def _mock_stream_response(
    mocker, body: AsyncGenerator[bytes]
) -> MockerFixture.MagicMock:
    """Build a mock streaming response that yields `body` from `aiter_bytes`."""
    response = mocker.MagicMock()
    response.__aenter__.return_value = response
    response.aiter_bytes.return_value = body
    return response


@pytest.mark.asyncio
async def test_stream_file_does_not_overwrite_existing_file(mocker, tmp_path):
    destination = tmp_path / "download.pdf"
    destination.write_bytes(b"existing content")
    mocker.patch(
        "httpx2.AsyncClient.stream",
        return_value=_mock_stream_response(mocker, _one_chunk_data(b"new content")),
    )

    with pytest.raises(FullTextStreamError, match="already exists"):
        await stream_file("http://example.com/streamfile", destination)

    assert (
        destination.read_bytes() == b"existing content"
    ), "Original content in the file should not be overwritten by subsequent downloads"


@pytest.mark.asyncio
async def test_stream_file_second_overlapping_download_fails(mocker, tmp_path):
    destination = tmp_path / "download.pdf"
    first_chunk_written = asyncio.Event()
    allow_first_to_finish = asyncio.Event()

    async def first_download_body() -> AsyncGenerator[bytes]:
        """
        Async generator for the first download body.

        Downloads are resumed only after the file has been created and "first " written to it.
        """
        yield b"first "
        first_chunk_written.set()
        await allow_first_to_finish.wait()
        yield b"download"

    mocker.patch(
        "httpx2.AsyncClient.stream",
        side_effect=[
            _mock_stream_response(mocker, first_download_body()),
            _mock_stream_response(mocker, _one_chunk_data(b"second download")),
        ],
    )

    # Start the first download and pause it part-way through writing the file.
    first_download = asyncio.create_task(
        stream_file("http://example.com/first.pdf", destination)
    )
    await first_chunk_written.wait()

    # A second download to the same destination must fail, not return the
    # half-written file as a success.
    with pytest.raises(FullTextStreamError, match="already exists"):
        await stream_file("http://example.com/second.pdf", destination)

    # The first download finishes cleanly and its file is intact.
    allow_first_to_finish.set()
    assert (
        await first_download == destination
    ), "First download should complete successfully and return the destination path"
    assert (
        destination.read_bytes() == b"first download"
    ), "Downloaded file content should match the expected content"


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
@pytest.mark.parametrize(
    "error", [httpx2.StreamError("stream failed"), httpx2.ReadError("read failed")]
)
async def test_stream_file_removes_partial_file_on_failure(mocker, tmp_path, error):
    async def failing_stream() -> AsyncGenerator[bytes]:
        yield b"partial content"
        raise error

    destination = tmp_path / "download.pdf"
    response = mocker.MagicMock()
    response.__aenter__.return_value = response
    response.aiter_bytes.return_value = failing_stream()
    mocker.patch("httpx2.AsyncClient.stream", return_value=response)

    with pytest.raises(FullTextStreamError):
        await stream_file("http://example.com/hosted.pdf", destination)
    assert not destination.exists()

    response.aiter_bytes.return_value = _one_chunk_data(b"complete content")
    assert (
        await stream_file("http://example.com/external.pdf", destination) == destination
    )
    assert destination.read_bytes() == b"complete content"


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
