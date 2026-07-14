"""Define local run configurations."""

import asyncio
import sys
from pathlib import Path
from typing import Annotated, Final
from uuid import UUID, uuid5

from cyclopts import App, Parameter
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
) -> tuple[list[DOIStudy], list[OpenAlexStudy], dict[str, str]]:
    """
    Resolve OpenAlex IDs to DOIs where possible, splitting into two groups.

    Args:
        openalex_identifiers (list[OpenAlexIdentifier]):
            List of OpenAlex identifiers to resolve.
        settings (Settings): The settings to use for the fetcher.

    Returns:
        tuple[list[DOIStudy], list[OpenAlexStudy], dict[str, str]]:
            A tuple containing a list of Study objects with valid DOIs, a
                list of OpenAlexStudy objects without valid DOIs,and a dictionary
                mapping UIDs to the original supplied identifiers.

    """
    if not openalex_identifiers:
        return [], [], {}

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
    uid_to_supplied: dict[str, str] = {}

    for openalex_id, work in zip(openalex_identifiers, works, strict=False):
        if isinstance(work, BaseException):
            logger.warning(
                f"Failed to fetch OpenAlex work for {openalex_id.identifier}: {work}. "
                "Treating as having no valid DOI."
            )
            openalex_study = OpenAlexStudy(
                uid=uuid5(DOI_NAMESPACE, openalex_id.identifier),
                openalex_id=openalex_id,
                doi=None,
            )
            without_doi.append(openalex_study)
            uid_to_supplied[str(openalex_study.uid)] = openalex_id.identifier
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
            doi_study = DOIStudy(
                doi=doi,
                uid=uuid5(DOI_NAMESPACE, doi.identifier),
                openalex_id=openalex_id,
            )
            resolved.append(doi_study)
            logger.debug(
                f"Resolved OpenAlex ID {openalex_id.identifier} "
                f"to DOI {doi.identifier}."
            )
            logger.debug(
                "Preserving the original supplied identifier in "
                "the UID to supplied map."
            )
            uid_to_supplied[str(doi_study.uid)] = openalex_id.identifier
        else:
            logger.warning(
                f"No valid DOI found for OpenAlex ID {openalex_id.identifier}. "
                "This item will be treated as having no valid DOI."
                "Attempting to fetch from _only_ OpenAlex."
            )
            openalex_study = OpenAlexStudy(
                uid=uuid5(DOI_NAMESPACE, openalex_id.identifier),
                openalex_id=openalex_id,
                doi=None,
            )
            without_doi.append(openalex_study)
            uid_to_supplied[str(openalex_study.uid)] = openalex_id.identifier
    return resolved, without_doi, uid_to_supplied


async def generate_study_collection(
    settings: Settings, identifier_list: list[OpenAlexIdentifier | DOIIdentifier]
) -> tuple[DOIStudyCollection, OpenAlexStudyCollection, dict[str, str]]:
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
        tuple[DOIStudyCollection, OpenAlexStudyCollection, dict[str, str]]:
            A tuple containing a DOIStudyCollection,an OpenAlexStudyCollection,
            and a dictionary mapping UIDs to the original supplied identifiers.

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
    uid_to_supplied: dict[str, str] = {}

    doi_study_collection = (
        generate_study_collection_from_dois(extracted_dois)
        if len(extracted_dois) > 0
        else DOIStudyCollection(studies=[])
    )
    logger.debug("Mapping DOI inputs to their study UIDs -> supplied DOI string")
    for study in doi_study_collection.studies:
        if getattr(study, "doi", None):
            d = study.doi
            uid_to_supplied[str(study.uid)] = (
                d.identifier if hasattr(d, "identifier") else str(d)
            )

    (
        resolved_studies,
        openalex_id_studies_without_doi,
        oa_uid_map,
    ) = await resolve_openalex_identifiers(extracted_openalex_ids, settings)

    logger.debug("Merging uid->supplied mappings from OpenAlex resolution")
    uid_to_supplied.update(oa_uid_map)

    study_collection = DOIStudyCollection(
        studies=doi_study_collection.studies + resolved_studies
    )

    openalex_collection = OpenAlexStudyCollection(
        studies=openalex_id_studies_without_doi
    )
    return study_collection, openalex_collection, uid_to_supplied


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


def build_uid_to_supplied_map(
    study_collection: DOIStudyCollection | OpenAlexStudyCollection,
) -> dict[str, str]:
    """
    Build a mapping from study UID to the supplied identifier (DOI or OpenAlex ID).

    Args:
        study_collection (DOIStudyCollection | OpenAlexStudyCollection):
            The collection of studies for which to build the mapping.

    Returns:
        dict[str, str]: A dictionary mapping study UIDs to their corresponding
            supplied identifiers.

    """
    uid_to_supplied: dict[str, str] = {}
    for study in study_collection.studies:
        supplied: str | None = None
        oa = getattr(study, "openalex_id", None)
        if oa is not None:
            supplied = getattr(oa, "identifier", str(oa))
        else:
            d = getattr(study, "doi", None)
            if d is not None:
                supplied = getattr(d, "identifier", str(d))
        supplied = supplied or str(getattr(study, "uid", ""))
        uid_to_supplied[str(study.uid)] = supplied

    return uid_to_supplied


async def retrieve_fulltexts_from_external_providers(
    processor: FullTextEnhancementProcessor,
    study_collection: DOIStudyCollection,
    output_directory: Path,
    uid_to_supplied: dict[str, str],
    result_file_name: str = "retrieved_fulltexts_map.txt",
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
        uid_to_supplied (dict[str, str]): A dictionary mapping study UIDs to their
            corresponding supplied identifiers.
        result_file_name (str): The name of the results map file to write.
             Defaults to "retrieved_fulltexts_map.txt".

    """
    try:
        results = await processor.fulltext_fetcher.get_many_fulltext_pdfs_cycling_apis(
            input_study_collection=study_collection,
            output_directory=output_directory,
        )
        found_results = [
            result for result in results if result.fulltext_path is not None
        ]
        not_found_results = [
            result for result in results if result.fulltext_path is None
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
    results_map_file = output_directory / result_file_name

    with results_map_file.open("a") as output_results_file:
        for result in results:
            uid = result.uid
            supplied_identifier = None
            if uid is not None:
                supplied_identifier = uid_to_supplied.get(str(uid))
            if not supplied_identifier:
                oa = result.openalex_id
                if oa is not None:
                    supplied_identifier = (
                        oa.identifier if hasattr(oa, "identifier") else str(oa)
                    )
                else:
                    doi_r = result.doi
                    supplied_identifier = doi_r if doi_r else "None"

            matched_study = (
                next(
                    (
                        study
                        for study in study_collection.studies
                        if str(study.uid) == str(uid)
                    ),
                    None,
                )
                if uid is not None
                else None
            )
            work_id = (
                matched_study.openalex_id
                if matched_study and matched_study.openalex_id
                else ""
            )
            if not work_id:
                work_id = result.openalex_id or ""
            if hasattr(work_id, "identifier"):
                work_id = work_id.identifier

            doi_value = result.doi or "None"

            filename = (
                Path(result.fulltext_path).name if result.fulltext_path else "None"
            )
            source = result.source or ""
            output_results_file.write(
                f"{supplied_identifier}\t{work_id}\t{doi_value}\t{filename}\t{source}\n"
            )
    logger.info(f"Results map written to {results_map_file}")


async def openalex_retrieval_short_circuit(
    processor: FullTextEnhancementProcessor,
    openalex_study_collection: OpenAlexStudyCollection,
    output_directory: Path,
    uid_to_supplied: dict[str, str],
    result_file_name: str = "retrieved_fulltexts_map.txt",
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
        uid_to_supplied (dict[str, str]):
            A dictionary mapping study UIDs to their corresponding supplied identifiers,
            for logging and results mapping purposes.
        result_file_name (str):
            The name of the results map file to write.
            Defaults to "retrieved_fulltexts_map.txt".

    """
    logger.info("Short-circuiting to fetch from OpenAlex for valid OpenAlex IDs.")

    no_doi_openalex_results = await processor.fulltext_fetcher.full_text_fetcher.fetch(
        publisher_name="openalex",
        study_collection=openalex_study_collection,
        output_directory=output_directory,
    )
    results_map_file = output_directory / result_file_name
    with results_map_file.open("a") as output_results_file:
        for result in no_doi_openalex_results:
            supplied_identifier = uid_to_supplied.get(str(getattr(result, "uid", "")))
            if not supplied_identifier:
                oa = getattr(result, "openalex_id", None)
                if oa is not None:
                    supplied_identifier = (
                        oa.identifier if hasattr(oa, "identifier") else str(oa)
                    )
                else:
                    d = getattr(result, "doi", None)
                    if d is not None:
                        supplied_identifier = (
                            d.identifier if hasattr(d, "identifier") else str(d)
                        )

                supplied_identifier = supplied_identifier or str(
                    getattr(result, "uid", "")
                )

            matched_study = next(
                (
                    study
                    for study in openalex_study_collection.studies
                    if str(study.uid) == str(getattr(result, "uid", ""))
                ),
                None,
            )
            work_id = (
                matched_study.openalex_id
                if matched_study is not None and matched_study.openalex_id is not None
                else ""
            )
            if not work_id:
                work_id = getattr(result, "openalex_id", "")
            if hasattr(work_id, "identifier"):
                work_id = work_id.identifier

            result_doi: DOIIdentifier | None = getattr(result, "doi", None)

            doi_value: str | None = None
            if result_doi is not None:
                doi_value = (
                    result_doi.identifier
                    if hasattr(result_doi, "identifier")
                    else str(result_doi)
                )

            filename = result.fulltext_path.name if result.fulltext_path else "None"
            source = "openalex"
            output_results_file.write(
                f"{supplied_identifier}\t{work_id}\t{doi_value}\t{filename}\t{source}\n"
            )


@app.default
async def main(
    identifier_file: Annotated[
        Path,
        Parameter(
            name=["--identifier-file", "-i"],
            help=(
                "Path to a newline-separated file containing "
                "identifiers as strings.",
            ),
        ),
    ],
    output_directory: Annotated[
        Path,
        Parameter(
            name=["--output-directory", "-o"],
            help=(
                "Path to the output directory where full texts "
                "and results map will be saved.",
            ),
        ),
    ],
    exclude_api: list[ExternalAPI] | None = None,
    result_file_name: Annotated[
        str,
        Parameter(
            name=["--result-file-name", "-r"],
            help="Name of the results map file to write.",
        ),
    ] = "retrieved_fulltexts_map.txt",
) -> None:
    """
    Define the main entry point for local running.

    Args:
        identifier_file (Path): Path to a newline-separated file containing identifiers
            as strings. Identifiers can be DOIs, OpenAlex IDs or a mixture of both.
        output_directory (Path): Path to the output directory.
        exclude_api (list[ExternalAPI] | None): List of API names to exclude
            from fetching. Defaults to None.
        result_file_name (str): The name of the results map file to write.
             Defaults to "retrieved_fulltexts_map.txt".

    """
    set_up_logger()
    settings = get_settings()
    processor = prepare_processor(settings, exclude_api)
    extracted_identifiers = await process_identifier_file(identifier_file)
    output_directory.mkdir(parents=True, exist_ok=True)
    output_results_map_file = output_directory / result_file_name
    with output_results_map_file.open("w") as output_results_file:
        output_results_file.write(
            "Supplied Identifier\tOpenAlex ID\tDOI\tFilename\tSource API\n"
        )

    (
        study_collection,
        openalex_study_collection,
        uid_to_supplied,
    ) = await generate_study_collection(settings, extracted_identifiers)

    if study_collection.studies:
        logger.info(
            f"Generated DOIStudyCollection with {len(study_collection.studies)} "
            "studies with valid DOIs."
        )
        await retrieve_fulltexts_from_external_providers(
            processor, study_collection, output_directory, uid_to_supplied
        )

    if openalex_study_collection.studies:
        logger.info(
            f"Fetching {len(openalex_study_collection.studies)} studies "
            "with valid OpenAlex IDs but no valid DOIs from OpenAlex."
        )

        await openalex_retrieval_short_circuit(
            processor, openalex_study_collection, output_directory, uid_to_supplied
        )


if __name__ == "__main__":
    app()
