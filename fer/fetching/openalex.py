"""Openalex Fetcher module."""

import asyncio
from pathlib import Path

from destiny_sdk.identifiers import OpenAlexIdentifier
from httpx2 import HTTPError
from loguru import logger
from pydantic import AnyUrl, ValidationError

from fer.config import Settings
from fer.data_models.generic import APIConfig, APIKeyNotPresentError
from fer.data_models.openalex import get_openalex_api_config
from fer.fetching import BasePublisherFetcher
from fer.fetching.core import (
    AsyncHTTPXRetryClient,
    DOIStudy,
    DOIStudyCollection,
    FullTextStreamError,
    OpenAlexStudy,
    OpenAlexStudyCollection,
    RetrievedFullText,
    stream_file,
)
from fer.utils import format_doi, validate_doi


class OpenAlexAPIError(Exception):
    """Raise when OA API response status code is not 200."""


class PDFUnavailableError(Exception):
    """Raise when we can't find a PDF."""


class OpenalexFetcher(BasePublisherFetcher):
    """Openalex fetcher implementation."""

    def __init__(self, settings: Settings, wait_time_seconds: float = 2.0) -> None:
        """
        Initialise an OpenAlex fetcher instance.

        Args:
            settings (Settings): The settings to use for the fetcher.
            wait_time_seconds (float, optional): Wait time between requests.

        """
        self.settings = settings
        self.wait_time_seconds = wait_time_seconds
        self.api_config: APIConfig = get_openalex_api_config(settings)
        try:
            self.api_config.init_api_key(settings)
        except APIKeyNotPresentError as openalex_api_key_error:
            error_message = (
                f"Failed to initialise OpenAlex API key: {openalex_api_key_error}. "
                "OpenAlex-hosted PDF downloads disabled."
            )
            logger.error(error_message)

        self.base_url: AnyUrl = self.api_config.url
        self.query_params: dict | None = self.api_config.query_params
        self.headers: dict = self.api_config.headers

    async def get_work_openalex_id(self, openalex_id: str) -> dict:
        """
        Retrieve a Work from an OpenAlex ID.

        Args:
            openalex_id (str): The OpenAlex ID to look up, as a string.

        Returns:
            dict: The JSON response from the OA API.

        """
        async with AsyncHTTPXRetryClient() as client:
            response = await client.get(
                url=f"{self.base_url!s}{openalex_id}",
                headers=self.headers,
                params=self.query_params,
            )
            response.raise_for_status()

        return response.json()

    async def _get_work_doi(self, doi: str) -> dict:
        """
        Run a GET request from OA API to get one work by DOI.

        Args:
            doi (str): The DOI to look up.

        Returns:
            dict: The JSON response from the OA API.

        """
        doi_fmtd = format_doi(doi)
        doi_valid = validate_doi(doi_fmtd)

        async with AsyncHTTPXRetryClient() as client:
            response = await client.get(
                url=f"{self.base_url!s}doi:{doi_valid}",
                headers=self.headers,
                params=self.query_params,
            )
            response.raise_for_status()

        return response.json()

    def _get_pdf_urls(self, response_object: dict) -> list[AnyUrl] | None:
        """
        Extract the PDF URL from the OpenAlex response object.

        Retrieves the best pdf URL, if available.
        This prefers OpenAlex-hosted material first, and then falls back
        to external URLs provided by OpenAlex.

        Args:
            response_object (dict): The response object from OpenAlex API.

        Returns:
            list[AnyUrl] | None: The PDF URL(s) if found, else None.

        """
        url_candidates = []
        has_content: dict[str, bool] = response_object.get("has_content", {})
        locations = response_object.get("best_oa_location") or {}
        has_openalex_hosted_pdf = has_content.get("pdf", False)
        key_header = self.api_config.api_key_placement or "api_key"
        api_key_available = bool(self.api_config.headers.get(key_header))

        if not has_openalex_hosted_pdf and not locations:
            logger.debug("No full-text content or locations found in response object.")
            return None

        if has_openalex_hosted_pdf and api_key_available:
            logger.info("Found OpenAlex-hosted PDF.")
            full_openalex_id = response_object.get("id")
            pdf_service_base_url = "https://content.openalex.org/works/"
            if full_openalex_id:
                try:
                    openalex_identifier = OpenAlexIdentifier(
                        identifier=full_openalex_id
                    )
                except ValidationError as bad_openalex_identifier:
                    error_message = (
                        f"Malformed OpenAlex identifier: {bad_openalex_identifier}"
                    )
                    logger.error(error_message)
                else:
                    try:
                        url_candidates.append(
                            AnyUrl(
                                f"{pdf_service_base_url}{openalex_identifier.identifier}.pdf"
                            )
                        )
                    except ValidationError as bad_openalex_url:
                        logger.error(
                            f"Malformed OpenAlex-hosted PDF URL: {bad_openalex_url}"
                        )

        if not url_candidates:
            logger.debug("No OpenAlex-hosted PDF found, checking external locations.")

        if locations.get("pdf_url"):
            logger.info("Found external PDF URL from OpenAlex.")
            try:
                url_candidates.append(AnyUrl(locations["pdf_url"]))
            except ValidationError as bad_external_url:
                logger.error(f"Malformed external PDF URL: {bad_external_url}")
        return url_candidates if url_candidates else None

    async def download_one_pdf(
        self,
        pdf_url: AnyUrl,
        filepath: Path,
        headers: dict | None = None,
    ) -> Path | None:
        """
        Download one PDF from Openalex.

        Args:
            pdf_url (AnyUrl): The URL of the PDF to download.
            filepath (Path): Output file path.
            headers (dict | None, optional): Optional headers for the request.
                Defaults to None.

        Returns:
            Path | None: The path to the downloaded PDF or None if download failed.

        """
        key_header = self.api_config.api_key_placement or "api_key"
        download_headers = dict(headers) if headers else {}
        parsed_url = AnyUrl(pdf_url)
        is_openalex_content = (
            parsed_url.scheme == "https" and parsed_url.host == "content.openalex.org"
        )
        download_headers = dict(headers) if headers and is_openalex_content else {}
        sends_key = any(
            name.lower() == key_header.lower() and bool(value)
            for name, value in download_headers.items()
        )
        return await stream_file(
            url=pdf_url,
            destination=filepath,
            headers=download_headers or None,
            follow_redirects=not sends_key,
        )

    async def _openalex_retrieval(
        self, study: DOIStudy | OpenAlexStudy, output_directory: Path
    ) -> RetrievedFullText:
        """
        Retrieve full text for a single Study using OpenAlex API.

        Args:
            study (DOIStudy | OpenAlexStudy):
                The study for which to retrieve the full text.
            output_directory (Path): The directory where the full text should be saved.

        Returns:
            RetrievedFullText: The retrieved full text information.

        """
        doi = study.doi.identifier.lower() if study.doi else None
        uid = study.uid
        openalex_id = study.openalex_id.identifier if study.openalex_id else None
        if openalex_id:
            work = await self.get_work_openalex_id(openalex_id)
        else:
            if not doi:
                error_message = (
                    f"Study {uid} has neither DOI nor OpenAlex ID. "
                    "Cannot retrieve full text."
                )
                logger.error(error_message)
                return RetrievedFullText(
                    doi=None,
                    uid=uid,
                    openalex_id=None,
                    fulltext_path=None,
                    error=error_message,
                )
            work = await self._get_work_doi(doi)
        openalex_id = work.get("id", None)
        pdf_url_candidates = self._get_pdf_urls(work)
        pdf_path: Path | None = None
        if pdf_url_candidates:
            for candidate_url in pdf_url_candidates:
                try:
                    pdf_path = await self.download_one_pdf(
                        pdf_url=candidate_url,
                        filepath=output_directory / f"{uid}.pdf",
                        headers=self.api_config.headers,
                    )
                except FullTextStreamError as stream_error:
                    logger.error(
                        f"Failed to download PDF from {candidate_url}: {stream_error}"
                    )
                    continue

                if pdf_path:
                    return RetrievedFullText(
                        doi=doi,
                        uid=uid,
                        openalex_id=openalex_id,
                        fulltext_path=pdf_path,
                        file_format="pdf",
                    )

        warning_message = (
            f"All PDF downloads failed for {doi=} {openalex_id=}."
            if pdf_url_candidates
            else f"No PDF URLs found for {doi=} {openalex_id=}."
        )
        return RetrievedFullText(
            doi=doi,
            uid=uid,
            openalex_id=openalex_id,
            fulltext_path=None,
            error=warning_message,
        )

    async def fetch_many_full_texts(
        self,
        study_collection: DOIStudyCollection | OpenAlexStudyCollection,
        output_directory: Path,
        **kwargs: object,
    ) -> list[RetrievedFullText]:
        """
        Fetch full text for a collection of studies and save them to output_directory.

        Args:
            study_collection (DOIStudyCollection | OpenAlexStudyCollection):
                The study collection for which to fetch the full text.
            output_directory (Path): The directory where the full text should be saved.

        Returns:
            list[RetrievedFullText]: A list of RetrievedFullText instances
                representing the saved PDF files.

        """
        _ = kwargs
        output_directory.mkdir(parents=True, exist_ok=True)
        output_items: list[RetrievedFullText] = []
        for study in study_collection.studies:
            doi = study.doi.identifier.lower() if study.doi is not None else None
            uid = study.uid
            openalex_id = (
                study.openalex_id.identifier if study.openalex_id is not None else None
            )
            try:
                output_items.append(
                    await self._openalex_retrieval(
                        study=study, output_directory=output_directory
                    )
                )
            except OpenAlexAPIError as openalex_error:
                error_message = (
                    f"Openalex API error fetching data for {doi=} "
                    f"{openalex_id=}: {openalex_error}"
                )
                logger.error(error_message)
                output_items.append(
                    RetrievedFullText(
                        doi=doi,
                        uid=uid,
                        openalex_id=openalex_id,
                        fulltext_path=None,
                        error=error_message,
                    )
                )
            except HTTPError as http_error:
                error_message = (
                    f"HTTP error fetching Openalex data for {doi=} "
                    f"{openalex_id=}: {http_error}"
                )
                logger.error(error_message)
                output_items.append(
                    RetrievedFullText(
                        doi=doi,
                        uid=uid,
                        openalex_id=openalex_id,
                        fulltext_path=None,
                        error=error_message,
                    )
                )
            except FullTextStreamError as fulltext_download_error:
                error_message = (
                    f"Full text download error for Openalex DOI {doi=} {openalex_id=}:"
                    f" {fulltext_download_error}"
                )
                logger.error(error_message)
                output_items.append(
                    RetrievedFullText(
                        doi=doi,
                        uid=uid,
                        openalex_id=openalex_id,
                        fulltext_path=None,
                        error=error_message,
                    )
                )

            logger.debug(
                f"Sleeping {self.wait_time_seconds} seconds before next request..."
            )
            await asyncio.sleep(self.wait_time_seconds)

        return output_items
