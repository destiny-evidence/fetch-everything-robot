"""
Core module containing the `FullTextFetcher` class to get abstracts
from various APIs.
"""

import re
from collections.abc import Generator
from xml.etree.ElementTree import Element

import httpx
from defusedxml.ElementTree import ParseError, fromstring
from destiny_sdk.identifiers import DOIIdentifier
from loguru import logger
from pydantic import AnyUrl

from app.config import Settings
from app.data_models.generic import (
    APIConfig,
    APIKeyNotPresentError,
    ExternalAPIPriority,
    FullTextUnpackStrategy,
    external_api_priority_batch,
)
from app.utils import InvalidDOIError, validate_doi


class FetchFullTextError(Exception):
    """Custom exception for errors occurring during full text fetching."""


def prepare_api_config(
    api_configs: list[APIConfig],
    settings: Settings,
    external_api_priority_batch: ExternalAPIPriority = external_api_priority_batch,
) -> dict[str, APIConfig]:
    """
    Prepare a dict of APIConfig objects, populated with API keys.

    If API keys are not present for a given API,
    this will be omitted from the overall API config.

    NOTE: Right now, we can pass a list of APIConfigs.
    An API config will only be allowed if it's in
    the list of permitted APIs in generic.ExternalAPI.

    Args:
        api_configs (list[APIConfig]): list of APIConfig objects to prepare.
        settings (Settings): application settings containing API keys.
        external_api_priority_batch (ExternalAPIPriority): priority for batch queries.

    Returns:
        dict[str, APIConfig]: a dictionary mapping API names to their configurations.

    """
    master_api_config = {}  # type: dict
    api_config_map = {config.name.value: config for config in api_configs}
    logger.debug(
        f"external_api_priority_batch: {external_api_priority_batch.priorities}"
    )
    logger.debug(f"supplied api candidates: {', '.join(api_config_map.keys())}")

    for external_api_priority in [
        external_api_priority_batch,
    ]:
        logger.debug(f"building api config for {external_api_priority}")
        master_api_config[external_api_priority.name] = {}
        for api in external_api_priority.priorities:
            logger.debug(f"checking if {api.name} in list of available apis...")
            if api not in api_config_map:
                continue
            target_config = api_config_map[api]
            try:
                logger.debug(f"trying to find & init api key for {api.name}")
                target_config.init_api_key(settings=settings)
                master_api_config[external_api_priority.name][api.name] = target_config
                logger.info(f"successfully initialised API key for {api.name}.")
            except APIKeyNotPresentError as missing_api_key_error:
                logger.info(f"no API key for {api.name}. not populating config.")
                logger.info(f"original error message: {missing_api_key_error}.")
                continue

    return master_api_config


class FullTextFetcher:
    """
    Handles the fetching of full texts from target APIs. Can fetch either a `single`
    full text, or a `batch` of full texts.
    Single full texts are treated as a batch of one.

    Will _cycle_ through available API configurations
    in order to retrieve abstracts by DOI.
    Will unpack and, if required, clean abstract.
    """

    def __init__(self, master_api_config: dict, timeout: int = 60) -> None:
        """
        Init our FullTextFetcher instance.

        Args:
            master_api_config (dict): retrieved from `prepare_api_config`
                using all provided API configs.
            timeout (int, optional): Network timeout. Defaults to 60.

        """
        self.master_api_config = master_api_config  # type: dict
        self.timeout = timeout

        logger.info("Available external APIs in descending order of priority:")
        logger.info(", ".join(master_api_config["batch"].keys()))

    @staticmethod
    def process_doi(doi: DOIIdentifier | str) -> str:
        """
        Validate a DOI and return the DOI string in lowercase.

        Args:
            doi (DOIIdentifier | str): DOI to process.

        Returns:
            str: Validated DOI string in lowercase.

        """
        if isinstance(doi, DOIIdentifier):
            return doi.identifier.lower()
        try:
            doi_string = validate_doi(doi)
            return doi_string.lower()
        except InvalidDOIError as invalid_doi_error:
            logger.error(
                f"Invalid DOI {doi} provided."
                f"Original error message: {invalid_doi_error}"
            )
            raise

    def get_many_fulltexts_cycling_apis(
        self, input_dois: list[str], *, verbose: bool = False
    ) -> list[dict]:
        """
        Get many full texts from a list of DOIs, cycling APIs in order of priority.

        Args:
            input_dois (list[str]): Input list of DOIs, as strings.
            verbose (bool, optional): whether to provide very verbose logging for debug.
                                      Defaults to False.

        Returns:
            list[dict]: a list of dicts of full texts and DOIs.

        """
        raise NotImplementedError

    def fetch(
        self, url: AnyUrl, params: dict, headers: dict, *, verbose: bool = False
    ) -> dict:
        """
        Fetch a response from one of the APIs (generic).

        Args:
            url (AnyUrl): The URL to fetch from.
            params (dict): Query parameters to include in the request.
            headers (dict): Headers to include in the request.
            verbose (bool, optional): Whether to provide very verbose logging for debug.
                                      Defaults to False.

        Returns:
            dict: The JSON response from the API.

        Raises:
            httpx.HTTPStatusError: If an HTTP error occurs during the request.

        """
        client = httpx.Client(follow_redirects=True)
        response = client.get(
            url=str(url), params=params, headers=headers, timeout=self.timeout
        )
        if verbose:
            request_actual_headers = f"request headers: {response.request.headers}"
            request_url = f"request url: {response.request.url}"
            request_body = f"request body: {response.request.body!s}"
            response_status_code = f"status code: {response.status_code}"
            response_headers = f"headers: {response.headers}"
            response_cookies = f"cookies: {response.cookies}"

            logger.debug(request_actual_headers)
            logger.debug(request_url)
            logger.debug(request_body)

            logger.debug(response_status_code)
            logger.debug(response_headers)
            logger.debug(response_cookies)

        response.raise_for_status()

        logger.debug(f"response json: {response.json()}")
        return response.json()

    def fetch_many_fulltexts(
        self,
        dois: list[str],
        api_config: APIConfig,
        doi_batch_size: int = 15,
        *,
        chunk: bool = False,
        verbose: bool = False,
        **kwargs: dict,
    ) -> Generator[list]:
        """
        Fetch many full texts from a target API given a list of DOIs.

        Args:
            dois (list[str]): List of DOIs to fetch full texts for.
            api_config (APIConfig): API configuration object containing
                                    the API details and unpack strategy.
            doi_batch_size (int, optional): Number of DOIs to batch together
                                        in a single request. Defaults to 15.
            chunk (bool, optional): Whether to chunk the DOIs into batches.
                                    Defaults to False.
            verbose (bool, optional): Whether to provide very verbose logging for debug.
                                      Defaults to False.
            **kwargs: Additional keyword arguments to pass to the `fetch` method.

        """
        raise NotImplementedError

    @staticmethod
    def clean_full_text_string(full_text_xml: str) -> str:
        """
        Remove all XML/JATS/HTML tags from the full text string.

        Rather than the builtin `xml` module, we leverage `defusedxml`
        which should hopefully protect us from malicious xml.

        Args:
            full_text_xml (str): The full text string to clean.

        Returns:
            The cleaned full text string (currently still contains latex
                and newlines)

        """
        logger.debug("removing xml/jats tags from full text string...")
        try:
            # wrap in a root tag in case the input is a fragment
            wrapped = f"<root>{full_text_xml}</root>"
            root = fromstring(wrapped)

            def _get_text(element: Element) -> str:
                """recursively join text and tail content."""
                text = element.text or ""
                for child in element:
                    text += _get_text(child)
                    text += child.tail or ""
                return text

            cleaned = _get_text(root)
            return cleaned.strip()

        except ParseError:
            # fallback: strip tags with regex
            cleaned = re.sub(r"<[^>]+>", "", full_text_xml)
            return cleaned.strip()

    def unpack_one_full_text(
        self,
        response_obj: dict,
        strategy: FullTextUnpackStrategy,
    ) -> str:
        """
        Unpack the plain text of the abstract using an unpack strategy.

        If our `AbstractUnpackStrategy` has field `clean_abstract_string`
        set to `True`, we will run the `clean_abstract_string` method.

        Args:
            response_obj (dict): JSON response object from the API.
            strategy (AbstractUnpackStrategy): Unpack strategy to use.

        Returns:
            str: The plain text abstract extracted from the response object.

        Raises:
            FullTextUnpackError: If unpacking the abstract fails.

        """
        raise NotImplementedError

    @staticmethod
    def _traverse(nested_abstract_dict: dict, path: list[str]) -> list | str | None:
        """
        Traverse a nested dictionary using a list of keys.

        TODO: Consider rewriting for the full text extraction.

        Args:
            nested_abstract_dict (dict): The nested dictionary to traverse.
            path (list[str]): A list of keys representing the path to traverse.

        Returns:
            list | str | None: A list found in the response with corresponding key, or a
            string if found in the case of individual DOIs and abstracts.
            Returns None if not found.

        """
        logger.debug(f"traversing object with path: {path}")
        for i, key in enumerate(path):
            logger.debug(
                f"level {i}: object type: {type(nested_abstract_dict)}, key: {key}"
            )
            if isinstance(nested_abstract_dict, dict):
                obj = nested_abstract_dict.get(key)
            else:
                try:
                    warning_msg = (
                        f"level {i}: expected dict, got {type(obj)}. returning None."
                    )
                except NameError:
                    warning_msg = (
                        "level {i}: expected dict, got.",
                        f"{type(nested_abstract_dict)}returning None.",
                    )
                logger.warning(warning_msg)
                return None
            if obj is None:
                obj_is_none_warning_msg = (
                    f"level {i}: key '{key}' not found. returning None."
                )
                logger.warning(obj_is_none_warning_msg)
                return None
            nested_abstract_dict = obj
        return obj

    def unpack_many_full_texts(
        self, response_obj: dict | list, strategy: FullTextUnpackStrategy
    ) -> list[dict]:
        """Unpack many full texts using strategy and doi_strategy."""
        raise NotImplementedError
