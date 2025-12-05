"""Test the main module."""

import uuid
from unittest.mock import patch

import destiny_sdk
import httpx
import pytest
from pytest_httpx import HTTPXMock, IteratorStream

from app.enhancement_processor import FullTextEnhancementProcessor
from app.main import process_robot_enhancement_batch


@pytest.mark.xfail(reason="Needs to be updated to handle full text enhancements.")
@pytest.mark.asyncio
async def test_process_robot_enhancement_batch_happy_path(
    mocker,
    httpx_mock: HTTPXMock,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
) -> None:
    """Test successful processing of a robot enhancement batch."""
    batch_id = uuid.uuid4()
    reference_ids = [uuid.uuid4() for _ in range(3)]
    dois = [f"10.1000/{i}" for i in range(3)]

    # Mock the batch data
    batch = destiny_sdk.robots.RobotEnhancementBatch(
        id=batch_id,
        reference_storage_url="https://get-references-here.com",
        result_storage_url="https://put-results-here.com",
    )

    # Mock reference file download
    mock_reference_file_stream(httpx_mock, reference_ids, dois)

    # Mock result upload
    httpx_mock.add_response(method="PUT", status_code=200)

    # Mock SDK result submission
    with (
        patch("app.main.DestinyClient") as mock_client,
    ):
        await process_robot_enhancement_batch(
            mock_client, test_fulltext_enhancement_processor, batch
        )

        mock_client.send_robot_enhancement_batch_result.assert_called_once()
        call_args = mock_client.send_robot_enhancement_batch_result.call_args[0][0]
        assert call_args.request_id == batch_id, "Request ID should match."
        assert call_args.error is None, "There should be no error."


@pytest.mark.asyncio
async def test_process_robot_enhancement_batch_with_download_error(
    httpx_mock: HTTPXMock,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
) -> None:
    """Test handling of download errors during batch processing."""
    batch_id = uuid.uuid4()

    batch = destiny_sdk.robots.RobotEnhancementBatch(
        id=batch_id,
        reference_storage_url="https://get-references-here.com",
        result_storage_url="https://put-results-here.com",
    )

    # Mock download failure
    httpx_mock.add_response(method="GET", status_code=404)

    with patch("app.main.DestinyClient") as mock_client:
        # Process should raise an exception due to HTTP error
        with pytest.raises(httpx.HTTPStatusError, match="404"):
            await process_robot_enhancement_batch(
                mock_client, test_fulltext_enhancement_processor, batch
            )

        # Verify error result was sent
        mock_client.send_robot_enhancement_batch_result.assert_called_once()
        call_args = mock_client.send_robot_enhancement_batch_result.call_args[0][0]
        assert call_args.request_id == batch_id
        assert call_args.error is not None


def mock_reference_file_stream(
    httpx_mock: HTTPXMock, reference_ids: list[uuid.UUID], dois: list[str]
):
    """Mock a stream for a file containing references."""
    stream_response = []
    for reference_id, doi in zip(reference_ids, dois, strict=False):
        reference = destiny_sdk.references.Reference(
            id=reference_id,
            identifiers=[destiny_sdk.identifiers.DOIIdentifier(identifier=doi)],
        )
        stream_response.append(bytes(reference.to_jsonl() + "\n", "utf-8"))
    httpx_mock.add_response(stream=IteratorStream(stream_response))
