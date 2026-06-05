"""Define local run configurations."""

import asyncio
import sys
from pathlib import Path
from typing import Final
from uuid import UUID, uuid5

from cyclopts import App
from destiny_sdk.identifiers import DOIIdentifier, OpenAlexIdentifier
from pydantic import ValidationError

from fer.config import ExternalAPI, Settings, get_settings
from fer.data_models.crossref import get_crossref_api_config
from fer.data_models.generic import APIConfig, prepare_api_config
from fer.data_models.openalex import get_openalex_api_config
from fer.data_models.scopus import get_scopus_batch_api_config
from fer.data_models.unpaywall import get_unpaywall_api_config
from fer.enhancement_processor import (
    FullTextEnhancementProcessor,
)
from fer.fetch_fulltext import ZeroFullTextsGeneratedError
from fer.fetching.core import DOIStudy, DOIStudyCollection, OpenAlexStudyCollection
from fer.fetching.openalex import OpenalexFetcher, OpenAlexStudy
from fer.fetching.registry import get_publisher_fetcher_registry
from fer.logger import logger, set_up_logger
from fer.utils import InvalidDOIError, get_version_number, validate_doi

app = App(
    name="fetch-everything",
    version=get_version_number(),
)

DOI_NAMESPACE = UUID("12345678-1234-5678-1234-567812345678")


class InvalidIdentifierError(Exception):
    """Raise when no valid identifier is found for a single Reference."""


async def resolve_openalex_identifiers(
    openalex_identifiers: list[OpenAlexIdentifier], settings: Settings
) -> tuple[list[DOIStudy], list[OpenAlexStudy]]:
    """
    Resolve OpenAlex IDs to DOIs where possible, splitting into two groups.

    Args:
        openalex_identifiers (list[OpenAlexIdentifier]):
            List of OpenAlex identifiers to resolve.
        settings (Settings): The settings to use for the fetcher.

    Returns:
        tuple[list[DOIStudy], list[OpenAlexStudy]]:
            A tuple containing a list of Study objects with valid DOIs and a
                list of OpenAlexStudy objects without valid DOIs.

    """
    if not openalex_identifiers:
        return [], []

    openalex_fetcher = OpenalexFetcher(settings)
    works = await asyncio.gather(
        *[
            openalex_fetcher.get_work_openalex_id(openalex_id.identifier)
            for openalex_id in openalex_identifiers
        ],
        return_exceptions=True,
    )
    resolved: list[DOIStudy] = []
    without_doi: list[OpenAlexStudy] = []

    for openalex_id, work in zip(openalex_identifiers, works, strict=False):
        if isinstance(work, BaseException):
            logger.warning(
                f"Failed to fetch OpenAlex work for {openalex_id.identifier}: {work}. "
                "Treating as having no valid DOI."
            )
            without_doi.append(
                OpenAlexStudy(
                    uid=uuid5(DOI_NAMESPACE, openalex_id.identifier),
                    openalex_id=openalex_id,
                    doi=None,
                )
            )
            continue
        raw_doi = work.get("doi", None)
        doi: DOIIdentifier | None = None
        if raw_doi:
            try:
                doi = DOIIdentifier(identifier=validate_doi(raw_doi))
            except InvalidDOIError:
                warning_message = (
                    f"Invalid DOI found for OpenAlex ID {openalex_id.identifier}: "
                    f"{raw_doi}. This item will be treated as having no valid DOI."
                )
                logger.warning(warning_message)

        if doi is not None:
            resolved.append(
                DOIStudy(
                    doi=doi,
                    uid=uuid5(DOI_NAMESPACE, doi.identifier),
                    openalex_id=openalex_id,
                )
            )
        else:
            logger.warning(
                f"No valid DOI found for OpenAlex ID {openalex_id.identifier}. "
                "This item will be treated as having no valid DOI."
                "Attempting to fetch from _only_ OpenAlex."
            )
            without_doi.append(
                OpenAlexStudy(
                    uid=uuid5(DOI_NAMESPACE, openalex_id.identifier),
                    openalex_id=openalex_id,
                    doi=None,
                )
            )
    return resolved, without_doi


async def generate_study_collection(
    settings: Settings, identifier_list: list[OpenAlexIdentifier | DOIIdentifier]
) -> tuple[DOIStudyCollection, OpenAlexStudyCollection]:
    """
    Generate a StudyCollection from a list of identifiers.

    Identifiers can be DOIs or OpenAlex IDs.
    If an OpenAlex ID is provided, this should be treated
    as a valid identifier, but can only be used with the OpenAlex API.

    If a DOI is provided, this should be validated and formatted.
    We apply additional DOI validation in this package.
    Validated DOIs can then be used with any API that accepts DOIs.

    Args:
        settings (Settings): The settings to use for the fetcher.
        identifier_list (list[OpenAlexIdentifier | DOIIdentifier]):
            List of identifiers to generate the StudyCollection from.

    Returns:
        tuple[DOIStudyCollection, OpenAlexStudyCollection]:
            A tuple containing a DOIStudyCollection and an OpenAlexStudyCollection.

    """
    extracted_dois = [
        identifier.identifier
        for identifier in identifier_list
        if isinstance(identifier, DOIIdentifier)
    ]
    extracted_openalex_ids = [
        identifier
        for identifier in identifier_list
        if isinstance(identifier, OpenAlexIdentifier)
    ]
    doi_study_collection = (
        generate_study_collection_from_dois(extracted_dois)
        if len(extracted_dois) > 0
        else DOIStudyCollection(studies=[])
    )
    (
        resolved_studies,
        openalex_id_studies_without_doi,
    ) = await resolve_openalex_identifiers(extracted_openalex_ids, settings)

    study_collection = DOIStudyCollection(
        studies=doi_study_collection.studies + resolved_studies
    )

    openalex_collection = OpenAlexStudyCollection(
        studies=openalex_id_studies_without_doi
    )
    return study_collection, openalex_collection


def generate_study_collection_from_dois(doi_list: list[str]) -> DOIStudyCollection:
    """
    Generate a DOIStudyCollection from a list of DOIs.

    Args:
        doi_list (list[str]): List of DOIs to generate the DOIStudyCollection from.

    Returns:
        DOIStudyCollection: A collection of DOIStudy objects created from the DOIs.

    """
    try:
        validated_doi_identifiers = [
            DOIIdentifier(identifier=validate_doi(doi)) for doi in doi_list
        ]

    except InvalidDOIError as invalid_doi_error:
        error_message = f"Invalid DOI encountered: {invalid_doi_error}"
        logger.error(error_message)
        sys.exit(1)
    return DOIStudyCollection(
        studies=[
            DOIStudy(doi=doi, uid=uuid5(DOI_NAMESPACE, doi.identifier))
            for doi in validated_doi_identifiers
        ]
    )


def prepare_processor(
    settings: Settings, exclude_api: list[ExternalAPI] | None = None
) -> FullTextEnhancementProcessor:
    """
    Prepare a FullTextEnhancementProcessor instance.

    Args:
        settings (Settings): The settings to use for the processor.
        exclude_api (list[ExternalAPI] | None): List of API names to exclude
            from fetching.

    Returns:
        FullTextEnhancementProcessor: The prepared processor instance.

    """
    title: Final[str] = settings.robot_title
    exclude_api_values = {api.value for api in exclude_api} if exclude_api else set()
    available_api_configs: list[APIConfig] = [
        config
        for name, config in [
            ("openalex", get_openalex_api_config(settings)),
            ("crossref", get_crossref_api_config()),
            ("unpaywall", get_unpaywall_api_config()),
            ("scopus", get_scopus_batch_api_config()),
        ]
        if name not in exclude_api_values
    ]
    if len(available_api_configs) == 0:
        logger.error("No APIs available for fetching after applying exclusions.")
        sys.exit(1)
    logger.info(
        "APIs enabled for fetching: {}",
        ", ".join([config.name for config in available_api_configs]),
    )

    global_api_config = prepare_api_config(
        api_configs=available_api_configs, settings=settings
    )

    return FullTextEnhancementProcessor(
        settings=settings,
        robot_version=get_version_number(),
        source_name=title,
        global_api_config=global_api_config,
        available_api_configs=available_api_configs,
        publisher_dict=get_publisher_fetcher_registry(settings),
    )


async def process_identifier_file(
    id_file: Path,
) -> list[DOIIdentifier | OpenAlexIdentifier]:
    """
    Process an input file containing identifiers.

    Return a list of processed identifiers.

    Args:
        id_file (Path): Path to a newline-separated file containing identifiers.

    Returns:
        list[DOIIdentifier | OpenAlexIdentifier]: A list of processed identifiers.

    """
    with id_file.open("r") as input_file:
        raw_identifiers = [str(line.strip()) for line in input_file if line.strip()]
    if len(raw_identifiers) == 0:
        error_message = (
            f"No identifiers found in the provided file: {id_file}. Exiting."
        )
        logger.error(error_message)
        sys.exit(1)

    return await process_identifiers(raw_identifiers)


async def process_identifiers(
    raw_identifiers: list[str],
) -> list[DOIIdentifier | OpenAlexIdentifier]:
    """
    Process a list of identifiers, validating DOIs and returning the processed list.

    Some items don't have a single canonical DOI, and may be presented as OpenAlex IDs.
    We should ideally use these to fetch metadata and full text from OpenAlex.
    If that's not possible we can collect metadata from OpenAlex,
    extract what OpenAlex considers to be the DOI and use that for
    fetching from other APIs.
    This function is intended to be the starting point for that process.

    Args:
        raw_identifiers (list[str]):
            A list of raw identifier strings to process.

    Returns:
        list[DOIIdentifier | OpenAlexIdentifier]: A list of processed identifiers.

    """
    processed_identifiers = []
    for raw_id in raw_identifiers:
        try:
            processed_identifiers.append(DOIIdentifier(identifier=validate_doi(raw_id)))
        except (ValidationError, InvalidDOIError):
            logger.warning(
                f"Invalid DOI encountered, treating as OpenAlex ID: {raw_id}"
            )
            try:
                processed_identifiers.append(OpenAlexIdentifier(identifier=raw_id))
            except ValidationError as no_valid_identifier_error:
                error_message = (
                    f"Identifier {raw_id} is neither a valid DOI nor "
                    f"a valid OpenAlex ID. Error: {no_valid_identifier_error}"
                )
                logger.error(f"Invalid OpenAlex ID encountered: {raw_id}")
                raise InvalidIdentifierError(
                    error_message
                ) from no_valid_identifier_error

    return processed_identifiers


async def retrieve_fulltexts_from_external_providers(
    processor: FullTextEnhancementProcessor,
    study_collection: DOIStudyCollection,
    output_directory: Path,
) -> None:
    """
    Retrieve full texts for a given DOIStudyCollection.

    Uses the provided processor and saves them to the output directory.

    Potentially uses multiple external APIs, cycling through them as needed.

    Results are saved to the output directory,
    and a results map is written to a text file in the output directory.

    Args:
        processor (FullTextEnhancementProcessor):
            The processor to use for retrieving full texts.
        study_collection (DOIStudyCollection):
            The collection of studies for which to retrieve full texts.
        output_directory (Path): The directory where the full texts should be saved.

    """
    try:
        results = await processor.fulltext_fetcher.get_many_fulltext_pdfs_cycling_apis(
            input_study_collection=study_collection,
            output_directory=output_directory,
        )
        found_results = [
            result for result in results if result["fulltext_path"] is not None
        ]
        not_found_results = [
            result for result in results if result["fulltext_path"] is None
        ]
        logger.info(f"Successfully fetched {len(found_results)} full text PDFs.")
        if len(not_found_results) > 0:
            logger.warning(
                f"Could not fetch {len(not_found_results)} full text PDFs."
                " See results map for details."
            )
    except ZeroFullTextsGeneratedError as zero_fulltexts_error:
        logger.error(f"No full texts were generated: {zero_fulltexts_error}")
        sys.exit(1)
    results_map_file = output_directory / "retrieved_fulltexts_map.txt"
    with results_map_file.open("w") as f:
        for result in results:
            doi = result["doi"]
            filename = (
                Path(result["fulltext_path"]).name
                if result["fulltext_path"]
                else "None"
            )
            source = result["source"]
            f.write(f"{doi}\t{filename}\t{source}\n")
    logger.info(f"Results map written to {results_map_file}")


async def openalex_retrieval_short_circuit(
    processor: FullTextEnhancementProcessor,
    openalex_study_collection: OpenAlexStudyCollection,
    output_directory: Path,
) -> None:
    """
    Short-circuit to fetch from OpenAlex for valid OpenAlex IDs.

    Used in instances when we have OpenAlex IDs but no corresponding DOIs are found.
    Such cases can _only_ be fetched from OpenAlex, so we need to attempt the fetch
    and exit promptly, without attempting to fetch from any other APIs.


    Args:
        processor (FullTextEnhancementProcessor):
            The processor to use for retrieving full texts.
        openalex_study_collection (OpenAlexStudyCollection):
            The collection of OpenAlex studies for which to retrieve full texts.
        output_directory (Path):
            The directory where the full texts should be saved.

    """
    logger.info("Short-circuiting to fetch from OpenAlex for valid OpenAlex IDs.")

    no_doi_openalex_results = await processor.fulltext_fetcher.full_text_fetcher.fetch(
        publisher_name="openalex",
        study_collection=openalex_study_collection,
        output_directory=output_directory,
    )
    results_map_file = output_directory / "retrieved_fulltexts_map.txt"
    with results_map_file.open("a") as f:
        for result in no_doi_openalex_results:
            identifier = result.openalex_id or result.doi
            filename = result.fulltext_path.name if result.fulltext_path else "None"
            source = "openalex"
            f.write(f"{identifier}\t{filename}\t{source}\n")


@app.default
async def main(
    identifier_file: Path,
    output_directory: Path,
    exclude_api: list[ExternalAPI] | None = None,
) -> None:
    """
    Define the main entry point for local running.

    Args:
        identifier_file (Path): Path to a newline-separated file containing identifiers
            as strings. Identifiers can be DOIs, OpenAlex IDs or a mixture of both.
        output_directory (Path): Path to the output directory.
        exclude_api (list[ExternalAPI] | None): List of API names to exclude
            from fetching. Defaults to None.

    """
    set_up_logger()
    settings = get_settings()
    processor = prepare_processor(settings, exclude_api)
    extracted_identifiers = await process_identifier_file(identifier_file)
    output_directory.mkdir(parents=True, exist_ok=True)

    study_collection, openalex_study_collection = await generate_study_collection(
        settings, extracted_identifiers
    )

    if study_collection.studies:
        logger.info(
            f"Generated DOIStudyCollection with {len(study_collection.studies)} "
            "studies with valid DOIs."
        )
        await retrieve_fulltexts_from_external_providers(
            processor, study_collection, output_directory
        )

    if openalex_study_collection.studies:
        logger.info(
            f"Fetching {len(openalex_study_collection.studies)} studies "
            "with valid OpenAlex IDs but no valid DOIs from OpenAlex."
        )

        await openalex_retrieval_short_circuit(
            processor, openalex_study_collection, output_directory
        )


if __name__ == "__main__":
    app()
