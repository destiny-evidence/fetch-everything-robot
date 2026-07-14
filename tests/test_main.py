"""Test the main module."""

import uuid
from unittest.mock import patch

import destiny_sdk
import httpx2
import pytest

from fer.enhancement_processor import FullTextEnhancementProcessor
from fer.main import process_robot_enhancement_batch


@pytest.mark.asyncio
async def test_process_robot_enhancement_batch_happy_path(
    mocker,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
) -> None:
    """Test successful processing of a robot enhancement batch."""
    batch_id = uuid.uuid4()

    # Mock the batch data
    batch = destiny_sdk.robots.RobotEnhancementBatch(
        id=batch_id,
        reference_storage_url="https://get-references-here.com",
        result_storage_url="https://put-results-here.com",
    )

    patched_process_batch = mocker.patch.object(
        test_fulltext_enhancement_processor,
        "process_batch",
        new=mocker.AsyncMock(return_value=None),
    )

    # Mock SDK result submission
    with (
        patch("fer.main.DestinyClient") as mock_client,
    ):
        await process_robot_enhancement_batch(
            mock_client, test_fulltext_enhancement_processor, batch
        )

        patched_process_batch.assert_awaited_once_with(batch)
        mock_client.send_robot_enhancement_batch_result.assert_called_once()
        call_args = mock_client.send_robot_enhancement_batch_result.call_args[0][0]
        assert call_args.request_id == batch_id, "Request ID should match."
        assert call_args.error is None, "There should be no error."


@pytest.mark.asyncio
async def test_process_robot_enhancement_batch_with_download_error(
    mocker,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
) -> None:
    """Test handling of download errors during batch processing."""
    batch_id = uuid.uuid4()

    batch = destiny_sdk.robots.RobotEnhancementBatch(
        id=batch_id,
        reference_storage_url="https://get-references-here.com",
        result_storage_url="https://put-results-here.com",
    )

    request = httpx2.Request("GET", str(batch.reference_storage_url))
    response = httpx2.Response(status_code=404, request=request)
    patched_process_batch = mocker.patch.object(
        test_fulltext_enhancement_processor,
        "process_batch",
        new=mocker.AsyncMock(
            side_effect=httpx2.HTTPStatusError(
                "404 Not Found", request=request, response=response
            )
        ),
    )

    with patch("fer.main.DestinyClient") as mock_client:
        # Process should raise an exception due to HTTP error
        with pytest.raises(httpx2.HTTPStatusError, match="404"):
            await process_robot_enhancement_batch(
                mock_client, test_fulltext_enhancement_processor, batch
            )

        patched_process_batch.assert_awaited_once_with(batch)
        # Verify error result was sent
        mock_client.send_robot_enhancement_batch_result.assert_called_once()
        call_args = mock_client.send_robot_enhancement_batch_result.call_args[0][0]
        assert call_args.request_id == batch_id
        assert call_args.error is not None
