"""Elsevier Fetcher Module."""

from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from loguru import logger
from pydantic import AnyUrl, BaseModel
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from python_socks import ProxyConnectionError

from fer.config import Settings
from fer.data_models.scopus import ScopusAPIConfig, get_scopus_batch_api_config
from fer.fetching import BasePublisherFetcher
from fer.fetching.core import (
    AsyncHTTPXRetryClient,
    BaseAuthError,
    FullTextStreamError,
    IncompleteFullTextError,
    RetrievedFullText,
    Study,
    StudyCollection,
    stream_file,
)


class ElsevierAuthError(BaseAuthError):
    """Raise when Elsevier API authentication fails."""


class ElsevierRequestConfig(BaseModel):
    """Configuration for Elsevier API requests."""

    headers: dict[str, str]
    file_extension: Literal[".pdf", ".xml"]


class ElsevierFetcher(BasePublisherFetcher):
    """Define a concrete fetcher for Elsevier full texts."""

    def __init__(self, settings: Settings) -> None:
        """
        Initialise an ElsevierFetcher.

        Args:
            settings (Settings): The settings to use for the fetcher.

        """
        self.settings = settings
        self.api_config: ScopusAPIConfig = get_scopus_batch_api_config()
        self.base_url = "https://api.elsevier.com/content/article/doi/"

    @staticmethod
    def _is_single_page_pdf(path: Path) -> bool:
        """
        Check if a PDF file is a single page.

        Args:
            path (Path): The path to the PDF file.

        Returns:
            bool: True if the PDF is a single page, False otherwise.

        """
        try:
            with path.open("rb") as file:
                reader = PdfReader(file)
                return len(reader.pages) == 1 if reader.pages is not None else False
        except PyPdfError as pdf_error:
            error_message = f"Error reading PDF file {path}: {pdf_error}"
            logger.error(error_message)
            return False
        except FileNotFoundError as file_not_found_error:
            error_message = (
                f"File not found when processing PDF file {path}:"
                f" {file_not_found_error}"
            )
            logger.warning(error_message)
            return False

    async def download_one_pdf(
        self,
        pdf_url: AnyUrl,
        filepath: Path,
        headers: dict | None = None,
    ) -> Path | None:
        """
        Download one PDF from Elsevier.

        Args:
            pdf_url (AnyUrl): The URL of the PDF to download.
            filepath (Path): Output file path.
            headers (dict | None): Optional headers to include in the download request.

        Returns:
            Path | None: The path to the downloaded PDF or None if download failed.

        """
        return await stream_file(url=pdf_url, destination=filepath, headers=headers)

    def prepare_request_config(
        self, *, get_pdf: bool = True, get_xml: bool = False
    ) -> ElsevierRequestConfig:
        """
        Prepare headers and file extension for Elsevier API requests.

        Args:
            get_pdf (bool): Whether to get PDF content. Defaults to True.
            get_xml (bool): Whether to get XML content. Defaults to False.

        Raises:
            ElsevierAuthError: If neither API key nor institution token is provided.

        Returns:
            ElsevierRequestConfig: The request configuration including
                headers and file extension.

        """
        headers: dict[str, str] = {}
        api_key = (
            self.settings.elsevier_scopus_key.get_secret_value()
            if self.settings.elsevier_scopus_key is not None
            else None
        )
        inst_token = (
            self.settings.elsevier_scopus_inst_token.get_secret_value()
            if self.settings.elsevier_scopus_inst_token is not None
            else None
        )

        if api_key is None and inst_token is None:
            error_message = (
                "No Elsevier API key or institution token provided."
                " Requests may be rate limited or fail."
            )
            logger.error(error_message)
            raise ElsevierAuthError(error_message)

        if api_key is not None and inst_token is None:
            logger.warning(
                "Using Elsevier API key without institution token"
                ", requests may fail due to network settings."
            )
        file_extension: str = ""
        if api_key is not None:
            headers["X-ELS-APIKey"] = api_key
        if inst_token is not None:
            headers["X-ELS-Insttoken"] = inst_token
        if get_pdf and not get_xml:
            headers["Accept"] = "application/pdf"
            file_extension = ".pdf"
        elif get_xml and not get_pdf:
            headers["Accept"] = "text/xml"
            file_extension = ".xml"
        else:
            headers["Accept"] = "application/json"

        return ElsevierRequestConfig(
            headers=headers,
            file_extension=file_extension,
        )

    async def get_final_fulltext_content(
        self,
        url: str,
        output_file_path: Path,
        doi: str,
        uid: UUID,
        *,
        is_incomplete_pdf: bool = False,
    ) -> RetrievedFullText:
        """
        Produce the correct format fulltext content.

        Handles cases where a PDF is returned, but it is a single page,
        which may indicate that the content is closed access.
        In this case, we should attempt to fetch the XML fulltext instead.

        Args:
            url (str): The URL of the Elsevier API.
            output_file_path (Path): The path to the downloaded fulltext file.
            doi (str): The DOI of the study.
            uid (UUID): The unique identifier of the study.
            is_incomplete_pdf (bool): Whether the downloaded PDF is incomplete.

        Returns:
            RetrievedFullText: The retrieved fulltext content.

        """
        is_single_page_pdf = self._is_single_page_pdf(output_file_path)

        if not is_single_page_pdf and not is_incomplete_pdf:
            logger.info(f"Elsevier content saved {uid}: {output_file_path}")
            return RetrievedFullText(
                doi=doi,
                uid=uid,
                fulltext_path=output_file_path,
                file_format="pdf",
                error=None,
            )
        if is_single_page_pdf and not is_incomplete_pdf:
            logger.info(
                f"Downloaded PDF for {uid} is single page. "
                "Can indicate closed access, "
                "but elsevier reports entire PDF downloaded."
            )
            return RetrievedFullText(
                doi=doi,
                uid=uid,
                fulltext_path=output_file_path,
                file_format="pdf",
                error=None,
            )

        warning_message = (
            f"Downloaded PDF for {uid} appears to be a single page and elsevier"
            " reports an incomplete download, which may indicate closed access."
            f" Removing single page PDF at {output_file_path}."
            f" Fetching XML fulltext instead for {uid=} {doi=}."
        )
        logger.warning(warning_message)

        output_file_path.unlink(missing_ok=True)

        xml_request_config = self.prepare_request_config(get_pdf=False, get_xml=True)

        try:
            response = await self._elsevier_request(
                url=url, elsevier_request_config=xml_request_config, doi=doi, uid=uid
            )
        except (
            httpx.HTTPError,
            FullTextStreamError,
            ProxyConnectionError,
        ) as elsevier_request_error:
            error_message = (
                "Elsevier request error when fetching XML after PDF fetch"
                " found closed access for "
                f"{doi=}: {elsevier_request_error}"
            )
            logger.error(error_message)
            raise

        if response.status_code == httpx.codes.OK:
            xml_file_path = output_file_path.with_suffix(".xml")
            xml_file_path.write_bytes(response.content)
            logger.info(f"Elsevier XML content saved {uid}: {xml_file_path}")
            return RetrievedFullText(
                doi=doi,
                uid=uid,
                fulltext_path=xml_file_path,
                file_format="xml",
                error=None,
            )

        warning_message = (
            f"Unexpected status code when fetching XML after"
            f" single page PDF for {uid=}, {doi=}."
            f" Status Code: {response.status_code}"
        )
        logger.warning(warning_message)
        return RetrievedFullText(
            doi=doi,
            uid=uid,
            fulltext_path=None,
            error=warning_message,
        )

    async def _elsevier_request(
        self,
        url: str,
        elsevier_request_config: ElsevierRequestConfig,
        doi: str,
        uid: UUID,
    ) -> httpx.Response:
        """
        Make an API request to Elsevier.

        Uses a retrying Async HTTPX client to handle errors and proxy issues.

        Args:
            url (str): The URL to make the request to.
            elsevier_request_config (ElsevierRequestConfig): The request configuration
                containing headers and file extension.
            doi (str): The DOI of the study.
            uid (UUID): The unique identifier of the study.

        Returns:
            httpx.Response: The HTTP response from the Elsevier API.

        """
        try:
            async with AsyncHTTPXRetryClient(
                proxy_url=self.settings.scopus_proxy_url
            ) as client:
                response = await client.get(
                    url, headers=elsevier_request_config.headers
                )
                response.raise_for_status()
                return response
        except httpx.HTTPError as http_error:
            error_message = f"HTTP error fetching Elsevier data for {doi}: {http_error}"
            logger.error(error_message)
            raise

        except ProxyConnectionError as proxy_error:
            error_message = f"Proxy connection failed for {doi}, {uid}: {proxy_error}"
            logger.error(error_message)
            raise

    async def _fetch_one_fulltext(
        self,
        study: Study,
        output_directory: Path,
        elsevier_request_config: ElsevierRequestConfig,
    ) -> RetrievedFullText:
        """
        Fetch a single full text from Elsevier.

        Args:
            study (Study): The study to fetch.
            output_directory (Path): The output directory path.
            elsevier_request_config (ElsevierRequestConfig): The request
                configuration containing headers and file extension.

        Returns:
            RetrievedFullText: A single RetrievedFullText instance.

        Raises:
            httpx.HTTPError: If an HTTP error occurs during the API request.
            ProxyConnectionError: If a proxy connection error occurs.

        """
        doi = study.doi.identifier.lower()
        uid = study.uid
        url = f"{self.base_url}{doi}/"
        try:
            response = await self._elsevier_request(
                url=url,
                elsevier_request_config=elsevier_request_config,
                doi=doi,
                uid=uid,
            )
        except (
            httpx.HTTPError,
            ProxyConnectionError,
        ) as elsevier_request_error:
            error_message = (
                f"Elsevier request error for {doi=}: {elsevier_request_error}"
            )
            logger.error(error_message)
            return RetrievedFullText(
                doi=doi, uid=uid, fulltext_path=None, error=error_message
            )

        if response.status_code == httpx.codes.OK:
            file_path = (
                output_directory / f"{uid}{elsevier_request_config.file_extension}"
            )
            is_incomplete_pdf: bool = False
            try:
                await self.download_one_pdf(
                    AnyUrl(url),
                    file_path,
                    headers=elsevier_request_config.headers,
                )

            except IncompleteFullTextError:
                logger.warning(f"Incomplete full text downloaded for {doi=}, {uid=}")
                is_incomplete_pdf = True

            except FullTextStreamError as fulltext_download_error:
                error_message = (
                    f"Full text download error for Elsevier DOI {doi}:"
                    f" {fulltext_download_error}"
                )
                logger.error(error_message)
                return RetrievedFullText(
                    doi=doi, uid=uid, fulltext_path=None, error=error_message
                )

            return await self.get_final_fulltext_content(
                url=str(url),
                output_file_path=file_path,
                doi=doi,
                uid=uid,
                is_incomplete_pdf=is_incomplete_pdf,
            )
        warning_message = (
            f"Unexpected successful status code for {uid=}, {doi=}."
            f" Status Code: {response.status_code}"
        )
        logger.warning(warning_message)
        logger.warning(f"Response Content: {response.text}")
        return RetrievedFullText(
            doi=doi, uid=uid, fulltext_path=None, error=warning_message
        )

    async def fetch_many_full_texts(
        self,
        study_collection: StudyCollection,
        output_directory: Path,
        **kwargs: object,
    ) -> list[RetrievedFullText]:
        """
        Fetch the full text of an Elsevier article.

        Args:
            study_collection (StudyCollection): The collection of studies to fetch.
            output_directory (Path): The output directory path.

        Returns:
            list[RetrievedFullText]: A list of RetrievedFullText instances
                representing the saved output files.

        """
        get_pdf: bool = bool(kwargs.get("get_pdf", True))
        get_xml: bool = bool(kwargs.get("get_xml", False))
        output_directory.mkdir(parents=True, exist_ok=True)
        request_info = self.prepare_request_config(
            get_pdf=get_pdf,
            get_xml=get_xml,
        )

        output_items: list[RetrievedFullText] = []
        for study in study_collection.studies:
            retrieved_full_text = await self._fetch_one_fulltext(
                study=study,
                output_directory=output_directory,
                elsevier_request_config=request_info,
            )
            output_items.append(retrieved_full_text)

        return output_items
