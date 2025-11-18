"""Openalex Fetcher module."""

import asyncio
from pathlib import Path

from loguru import logger
from pydantic import AnyUrl

from app.config import Settings
from app.fetching import BasePublisherFetcher
from app.fetching.core import FullTextStreamError, StudyCollection, stream_file


class OpenalexFetcher(BasePublisherFetcher):
    """Openalex fetcher impelmentation."""

    def __init__(self, settings) -> None:
        pass

    async def fetch_full_text(self, study_collection, output_directory):
        pass
