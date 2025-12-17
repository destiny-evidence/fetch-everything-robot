"""Define local run configurations."""

import sys
from pathlib import Path
from typing import Final
from uuid import uuid4

from cyclopts import App
from destiny_sdk.identifiers import DOIIdentifier

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
from fer.fetching.core import Study, StudyCollection
from fer.fetching.registry import get_publisher_fetcher_registry
from fer.logger import logger, set_up_logger
from fer.utils import InvalidDOIError, get_version_number, validate_doi

app = App(
    name="fetch-everything",
    version=get_version_number(),
)


def generate_study_collection_from_dois(doi_list: list[str]) -> StudyCollection:
    """
    Generate a StudyCollection from a list of DOIs.

    Args:
        doi_list (list[str]): List of DOIs to generate the StudyCollection from.

    Returns:
        StudyCollection: A collection of Study objects created from the DOIs.

    """
    try:
        validated_dois = [validate_doi(doi) for doi in doi_list]
        doi_identifiers = [
            DOIIdentifier(identifier=doi) for doi in validated_dois if doi is not None
        ]
    except InvalidDOIError as invalid_doi_error:
        error_message = f"Invalid DOI encountered: {invalid_doi_error}"
        logger.error(error_message)
        sys.exit(1)
    return StudyCollection(
        studies=[Study(doi=doi, uid=uuid4()) for doi in doi_identifiers]
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


def process_incoming_dois(dois_list: Path) -> list[str]:
    """
    Process incoming DOIs from a list or a file.

    Args:
        dois_list (Path): Path to a newline-separated file containing DOIs.

    Returns:
        list[str]: A list of processed DOIs.

    """
    if isinstance(dois_list, Path):
        with dois_list.open("r") as input_file:
            doi_found = [line.strip() for line in input_file if line.strip()]
    if len(doi_found) == 0:
        error_message = f"No DOIs found in the provided file: {dois_list}. Exiting."
        logger.error(error_message)
        sys.exit(1)
    return doi_found


@app.default
async def main(
    doi_list: Path,
    output_directory: Path,
    exclude_api: list[ExternalAPI] | None = None,
) -> None:
    """
    Define the main entry point for local running.

    Args:
        doi_list (Path): Path to a newline-separated file containing DOIs.
        output_directory (Path): Path to the output directory.
        exclude_api (list[ExternalAPI] | None): List of API names to exclude
            from fetching. Defaults to None.

    """
    set_up_logger()
    settings = get_settings()
    processor = prepare_processor(settings, exclude_api)
    extracted_dois = process_incoming_dois(doi_list)
    study_collection = generate_study_collection_from_dois(extracted_dois)
    output_directory.mkdir(parents=True, exist_ok=True)

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


if __name__ == "__main__":
    app()
