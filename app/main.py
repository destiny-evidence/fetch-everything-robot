"""Main module for the Fetch Everything Robot."""

import asyncio
import contextlib
import signal
import sys
from types import FrameType
from typing import Final

from destiny_sdk.client import Client as DestinyClient
from destiny_sdk.robots import (
    RobotEnhancementBatch,
    RobotEnhancementBatchResult,
    RobotError,
)
from enhancement_processor import FullTextEnhancementProcessor

from app.config import Settings, get_settings
from app.data_models.openalex import get_openalex_batch_api_config
from app.data_models.scopus import get_scopus_batch_api_config
from app.enhancement_processor import BatchEnhancementGenerationError
from app.fetch_fulltext import prepare_api_config
from app.logger import logger, set_up_logger
from app.server import start_health_check_server
from app.utils import get_version_number


async def process_robot_enhancement_batch(
    client: DestinyClient,
    processor: FullTextEnhancementProcessor,
    batch: RobotEnhancementBatch,
) -> None:
    """
    Process a robot enhancement batch by creating full text enhancements.

    Args:
        client (DestinyClient): The Destiny SDK client
            to communicate with the repository.
        processor (FullTextEnhancementProcessor): Processor to generate enhancements.
        batch (RobotEnhancementBatch): The batch of enhancements to process.

    """
    try:
        await processor.process_batch(batch)
        client.send_robot_enhancement_batch_result(
            RobotEnhancementBatchResult(request_id=batch.id)
        )

        logger.success("Successfully processed robot enhancement batch {}", batch.id)

    except BatchEnhancementGenerationError as batch_enhancement_error:
        logger.error(
            "Batch enhancement generation error for batch {}: {}",
            batch.id,
            batch_enhancement_error,
        )

        client.send_robot_enhancement_batch_result(
            RobotEnhancementBatchResult(
                request_id=batch.id,
                error=RobotError(message=str(batch_enhancement_error)),
            )
        )

    except Exception as robot_enhancement_batch_process_error:
        error_message = (
            "Error processing robot enhancement batch"
            f" {batch.id}:"
            f" {robot_enhancement_batch_process_error!s}"
        )
        logger.error(error_message)

        client.send_robot_enhancement_batch_result(
            RobotEnhancementBatchResult(
                request_id=batch.id,
                error=RobotError(
                    message=(
                        "Failed to process request:"
                        f"{robot_enhancement_batch_process_error!s}"
                    ),
                ),
            )
        )
        raise


async def poll_for_batches(
    settings: Settings, client: DestinyClient, processor: FullTextEnhancementProcessor
) -> None:
    """Poll for new robot enhancement batches and process them."""
    logger.info("Starting to poll for robot enhancement batches...")

    while True:
        try:
            batch = client.poll_robot_enhancement_batch(
                robot_id=settings.robot_id, limit=settings.batch_size
            )

            if batch is None:
                logger.info(
                    "No batches available. Sleeping for {sleep_seconds} seconds.",
                    sleep_seconds=settings.poll_interval_seconds,
                )
                await asyncio.sleep(settings.poll_interval_seconds)
                continue

            logger.info("Found batch {batch_id} to process", batch_id=batch.id)

            try:
                await process_robot_enhancement_batch(client, processor, batch)

            except Exception as process_batch_error:  # noqa: BLE001
                logger.error(
                    "During polling, error processing batch {batch_id}: {batch_error}",
                    batch_id=batch.id,
                    batch_error=process_batch_error,
                )
        except Exception as poll_error:  # noqa: BLE001
            logger.error("Error polling for batches: {}", poll_error)
        await asyncio.sleep(settings.poll_interval_seconds)


shutdown_event = asyncio.Event()


def signal_handler(signum: int, _frame: FrameType | None) -> None:
    """Handle termination signals to gracefully shut down the application."""
    logger.info("Received signal {}, initiating graceful shutdown...", signum)
    shutdown_event.set()


async def main() -> None:
    """Run the polling robot."""
    set_up_logger()
    health_check_task = asyncio.create_task(
        start_health_check_server(host="0.0.0.0", port=8001)
    )
    settings = get_settings()

    title: Final[str] = settings.robot_title

    client = DestinyClient(
        base_url=settings.destiny_repository_url,
        client_id=settings.robot_id,
        secret_key=settings.robot_secret,
    )

    # configurations for all APIs we can hit to get abstracts
    available_api_configs = [
        get_openalex_batch_api_config(settings),
        get_scopus_batch_api_config(),
    ]
    global_api_config = prepare_api_config(
        api_configs=available_api_configs, settings=settings
    )

    processor = FullTextEnhancementProcessor(
        robot_version=get_version_number(),
        source_name=title,
        global_api_config=global_api_config,
        available_api_configs=available_api_configs,
    )
    logger.info("Starting {} polling loop", title)
    logger.info("Polling interval: {} seconds", settings.poll_interval_seconds)
    logger.info("Batch size: {}", settings.batch_size)

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        poll_task = asyncio.create_task(poll_for_batches(settings, client, processor))

        # Wait for either the polling task to complete or a shutdown signal
        _done, pending = await asyncio.wait(
            [poll_task, asyncio.create_task(shutdown_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel remaining tasks

        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        logger.info("Shutdown complete.")

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
        sys.exit(0)

    except Exception:  # noqa: BLE001
        logger.critical("Unexpected fatal error occurred:")
        sys.exit(1)

    finally:
        health_check_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await health_check_task
