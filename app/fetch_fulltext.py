"""
Core module containing the `FullTextBatchFetcher` class to get fulltexts
from various APIs.
"""

import re
from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import ParseError, fromstring
from destiny_sdk.identifiers import DOIIdentifier
from fetching import BasePublisherFetcher
from loguru import logger

from app.config import Settings
from app.data_models.generic import (
    APIConfig,
    FullTextUnpackStrategy,
)
from app.fetching.core import StudyCollection
from app.fetching.fetchers import FullTextFetcher
from app.utils import InvalidDOIError, validate_doi


class ZeroFullTextsGeneratedError(Exception):
    """Custom exception for no full texts being generated."""


class FullTextBatchFetcherError(Exception):
    """Custom exception for errors occurring during full text fetching."""


class FullTextBatchFetcher:
    """
    Handles the fetching of full texts from target APIs.
    Can fetch either a `single` full text, or a `batch` of full texts.
    Single full texts are treated as a batch of one.

    Will _cycle_ through available API configurations
    in order to retrieve full texts by DOI.
    Will unpack and, if required, clean full text.
    """

    def __init__(
        self,
        settings: Settings,
        all_api_configs: dict,
        publisher_dict: dict[str, BasePublisherFetcher],
        timeout: int = 60,
    ) -> None:
        """
        Init our FullTextBatchFetcher instance.

        Args:
            settings (Settings): application settings.
            all_api_configs (dict): retrieved from `prepare_api_config`
                using all provided API configs.
            publisher_dict (dict[str, BasePublisherFetcher]):
                Dictionary of publisher fetchers.
            timeout (int, optional): Network timeout. Defaults to 60.

        """
        self.settings = settings
        self.all_api_configs = all_api_configs  # type: dict
        self.timeout = timeout
        self.full_text_fetcher = FullTextFetcher(
            settings=settings, publisher_dict=publisher_dict, timeout=timeout
        )

        logger.info("Available external APIs in descending order of priority:")
        logger.info(", ".join(all_api_configs["fulltext"].keys()))

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

    @staticmethod
    def process_doi_list(
        input_dois: list[DOIIdentifier | str],
    ) -> tuple[list[str], list[str]]:
        """
        Process a list of DOIs, validating each one.

        Args:
            input_dois (list[DOIIdentifier | str]): List of DOIs to process.

        Returns:
            tuple[list[str], list[str]]: A tuple containing two lists:
                - A list of valid DOI strings.
                - A list of invalid DOI strings.

        """
        valid_dois = []
        invalid_dois = []
        for doi in input_dois:
            try:
                doi_string = FullTextBatchFetcher.process_doi(doi)
                valid_dois.append(doi_string)
            except InvalidDOIError as invalid_doi_error:
                logger.error(f"Invalid DOI found: {invalid_doi_error}")
                if isinstance(doi, DOIIdentifier):
                    invalid_dois.append(doi.identifier.lower())
                else:
                    invalid_dois.append(str(doi).lower())
                continue
        return valid_dois, invalid_dois

    async def get_many_fulltext_pdfs_cycling_apis(
        self, input_study_collection: StudyCollection
    ) -> list[dict[str, Path | None]]:
        """
        Get many full texts from a list of DOIs, cycling APIs in order of priority.

        Args:
            input_study_collection (StudyCollection): Input collection of studies.

        Returns:
            list[dict]: a list of dicts of full texts and DOIs.

        """
        input_dois = [study.doi for study in input_study_collection.studies]
        valid_dois, invalid_dois = self.process_doi_list(input_dois)

        invalid_doi_response = [
            {"doi": doi, "fulltext": None, "source": None} for doi in invalid_dois
        ]
        valid_references_provided = len(valid_dois)
        logger.info(
            f"Valid references provided: {valid_references_provided} "
            f"of {len(input_study_collection.studies)} studies."
        )
        retrieved_fulltexts = []

        for api_name in self.all_api_configs["fulltext"]:
            if len(valid_dois) == 0:
                logger.info("All full texts retrieved, breaking API cycle.")
                break
            logger.info(f"Fetching full texts from API: {api_name}")
            api_count = 0
            api_config: APIConfig = self.all_api_configs["fulltext"][api_name]

            retrieved_responses: dict[
                str, Path | None
            ] = await self.full_text_fetcher.fetch(
                publisher_name=api_name,
                study_collection=input_study_collection,
            )

            found_responses = False
            if retrieved_responses:
                for doi, pdf_path in retrieved_responses.items():
                    if pdf_path is not None:
                        found_responses = True
                        doi_to_remove = doi

                        logger.info(f"Full text found for {doi} from {api_name}.")
                        valid_dois.remove(self.process_doi(doi_to_remove))
                        logger.info(
                            f"Got full text for doi {doi_to_remove} from {api_name}. "
                            "Removing from master list."
                        )
                        api_count += 1
                        retrieved_fulltexts.append(
                            {"doi": doi, "fulltext": str(pdf_path), "source": api_name}
                        )
            if not found_responses:
                error_message = (
                    f"No full texts found in {api_name} with"
                    f" query type {api_config.query_type.value}."
                )
                logger.error(error_message)

            logger.debug(f"Found {api_count} full texts for api {api_name}.")
            logger.info(f"Found {len(retrieved_fulltexts)} total from valid DOIs.")
            logger.info(
                f"Remaining valid DOIs to collect full texts: {len(valid_dois)}"
            )

        logger.info(
            f"{len(retrieved_fulltexts)} full texts"
            f" retrieved of {valid_references_provided} valid DOIs requested."
        )
        if len(retrieved_fulltexts) == 0:
            error_message = "No full texts were retrieved from any API."
            logger.error(error_message)
            raise ZeroFullTextsGeneratedError(error_message)

        logger.info(f"{len(invalid_dois)} invalid DOIs provided.")
        if len(valid_dois) > 0:
            logger.info(f"Full texts not retrieved for {len(valid_dois)} valid DOIs.")
        fulltexts_not_found = [
            {"doi": doi, "fulltext": None, "source": None} for doi in valid_dois
        ]
        retrieved_fulltexts.extend(invalid_doi_response)
        retrieved_fulltexts.extend(fulltexts_not_found)

        return retrieved_fulltexts

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
        Unpack plain text of the full text using an unpack strategy.

        If our `FullTextUnpackStrategy` has field `clean_full_text_string`
        set to `True`, we will run the `clean_full_text_string` method.

        Args:
            response_obj (dict): JSON response object from the API.
            strategy (FullTextUnpackStrategy): Unpack strategy to use.

        Returns:
            str: The plain text extracted from the response object.

        Raises:
            FullTextUnpackError: If unpacking the full text fails.

        """
        raise NotImplementedError

    @staticmethod
    def _traverse(nested_full_text_dict: dict, path: list[str]) -> list | str | None:
        """
        Traverse a nested dictionary using a list of keys.

        TODO @harryjmoss: Re-write for full text cases.
        https://github.com/destiny-evidence/fetch-everything-robot/issues/9

        Args:
            nested_full_text_dict (dict): The nested dictionary to traverse.
            path (list[str]): A list of keys representing the path to traverse.

        Returns:
            list | str | None: A list found in the response with corresponding key, or a
            string if found in the case of individual DOIs and full texts.
            Returns None if not found.

        """
        raise NotImplementedError

    def unpack_many_full_texts(
        self, response_obj: dict | list, strategy: FullTextUnpackStrategy
    ) -> list[dict]:
        """Unpack many full texts using strategy and doi_strategy."""
        raise NotImplementedError
