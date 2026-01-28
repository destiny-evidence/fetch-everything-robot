"""
Core module containing the `FullTextBatchFetcher` class to get fulltexts
from various APIs.
"""

import re
from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import ParseError, fromstring
from destiny_sdk.identifiers import DOIIdentifier
from loguru import logger
from pydantic import BaseModel

from fer.config import Settings
from fer.fetching import BasePublisherFetcher
from fer.fetching.core import DOIStudyCollection, RetrievedFullText
from fer.fetching.fetchers import FullTextFetcher, FullTextFetcherError
from fer.utils import InvalidDOIError, validate_doi


class ZeroFullTextsGeneratedError(Exception):
    """Custom exception for no full texts being generated."""


class FullTextBatchFetcherError(Exception):
    """Custom exception for errors occurring during full text fetching."""


class FullTextResult(BaseModel):
    """A Pydantic model representing the result of a full text fetch attempt."""

    doi: str
    uid: str
    openalex_id: str | None
    fulltext_path: str | None
    source: str | None


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
        self,
        input_study_collection: DOIStudyCollection,
        output_directory: Path,
        *,
        get_pdf: bool = True,
        get_xml: bool = False,
    ) -> list[FullTextResult]:
        """
        Get many full texts from a list of DOIs, cycling APIs in order of priority.

        Args:
            input_study_collection (DOIStudyCollection): Input study collection.
            output_directory (Path): Directory to save full texts.
            get_pdf (bool, optional): Whether to fetch PDF files. Defaults to True.
            get_xml (bool, optional): Whether to fetch XML files. Defaults to False.

        Returns:
            list[FullTextResult]: A list of FullTextResult objects.

        """
        input_dois = [study.doi for study in input_study_collection.studies]
        valid_dois, invalid_dois = self.process_doi_list(input_dois)

        invalid_doi_set = set(invalid_dois)
        invalid_doi_response = [
            FullTextResult(
                doi=study.doi.identifier,
                uid=str(study.uid),
                openalex_id=(
                    study.openalex_id.identifier if study.openalex_id else None
                ),
                fulltext_path=None,
                source=None,
            )
            for study in input_study_collection.studies
            if study.doi.identifier.lower() in invalid_doi_set
        ]
        valid_references_provided = len(valid_dois)
        logger.info(
            f"Valid references provided: {valid_references_provided} "
            f"of {len(input_study_collection.studies)} studies."
        )
        valid_study_collection = DOIStudyCollection(
            studies=[
                study
                for study in input_study_collection.studies
                if self.process_doi(study.doi) in valid_dois
            ]
        )
        retrieved_fulltexts: list[FullTextResult] = []

        for study in list(valid_study_collection.studies):
            fulltext_path = next(
                (
                    output_directory / f"{study.uid}{ext}"
                    for ext in [".pdf", ".xml"]
                    if (output_directory / f"{study.uid}{ext}").exists()
                ),
                None,
            )
            if fulltext_path is not None:
                logger.info(f"File already exists, skipping DOI {study.doi.identifier}")
                retrieved_fulltexts.append(
                    FullTextResult(
                        doi=study.doi.identifier,
                        uid=str(study.uid),
                        openalex_id=(
                            study.openalex_id.identifier if study.openalex_id else None
                        ),
                        fulltext_path=str(fulltext_path),
                        source="Already downloaded",
                    )
                )
                doi_to_remove = self.process_doi(study.doi.identifier)
                valid_dois.remove(doi_to_remove)
                valid_study_collection.remove_study_by_identifier(doi_to_remove)

        for api_name in self.all_api_configs["fulltext"]:
            if len(valid_dois) == 0:
                logger.info("All full texts retrieved, breaking API cycle.")
                break
            logger.info(f"Fetching full texts from API: {api_name}")
            api_count = 0

            try:
                retrieved_responses: list[
                    RetrievedFullText
                ] = await self.full_text_fetcher.fetch(
                    publisher_name=api_name,
                    study_collection=valid_study_collection,
                    output_directory=output_directory,
                    get_pdf=get_pdf,
                    get_xml=get_xml,
                )
            except FullTextFetcherError as fetcher_error:
                error_message = (
                    f"Error fetching full texts from {api_name}: {fetcher_error}"
                )
                logger.error(error_message)
                continue

            found_responses = False
            if retrieved_responses:
                for item in retrieved_responses:
                    if item.fulltext_path is not None:
                        found_responses = True
                        doi_to_remove = self.process_doi(item.doi)
                        matched_study = next(
                            (
                                s
                                for s in valid_study_collection.studies
                                if self.process_doi(s.doi) == doi_to_remove
                            ),
                            None,
                        )
                        logger.info(f"Full text found for {item.doi} from {api_name}.")
                        valid_dois.remove(doi_to_remove)
                        valid_study_collection.remove_study_by_identifier(doi_to_remove)
                        logger.info(
                            f"Got full text for doi {doi_to_remove} from {api_name}. "
                            "Removing from master list."
                        )
                        api_count += 1
                        retrieved_fulltexts.append(
                            FullTextResult(
                                doi=item.doi,
                                uid=str(item.uid),
                                openalex_id=(
                                    matched_study.openalex_id.identifier
                                    if matched_study and matched_study.openalex_id
                                    else None
                                ),
                                fulltext_path=str(item.fulltext_path),
                                source=api_name,
                            )
                        )
            if not found_responses:
                error_message = f"No full texts found in {api_name}."
                logger.warning(error_message)

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
            FullTextResult(
                doi=study.doi.identifier,
                uid=str(study.uid),
                openalex_id=(
                    study.openalex_id.identifier if study.openalex_id else None
                ),
                fulltext_path=None,
                source=None,
            )
            for study in valid_study_collection.studies
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
