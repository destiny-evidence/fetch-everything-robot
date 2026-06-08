import json
from pathlib import Path
from uuid import uuid5

import httpx
import pytest
from destiny_sdk.identifiers import DOIIdentifier, OpenAlexIdentifier

from fer.config import ExternalAPI
from fer.enhancement_processor import FullTextEnhancementProcessor
from fer.fetch_fulltext import FullTextResult
from fer.fetching.core import (
    DOIStudy,
    DOIStudyCollection,
    OpenAlexStudy,
    OpenAlexStudyCollection,
    RetrievedFullText,
)
from fer.local.run import (
    DOI_NAMESPACE,
    InvalidIdentifierError,
    generate_study_collection,
    generate_study_collection_from_dois,
    main,
    openalex_retrieval_short_circuit,
    prepare_processor,
    process_identifier_file,
    process_identifiers,
    resolve_openalex_identifiers,
    retrieve_fulltexts_from_external_providers,
)
from fer.utils import InvalidDOIError, validate_doi


@pytest.fixture
def test_doi_list():
    return [
        "10.1000/xyz123",
        "10.1000/xyz456",
        "10.1000/xyz789",
    ]


def test_generate_study_collection_from_dois_success(mocker, test_doi_list):
    study_collection = generate_study_collection_from_dois(test_doi_list)

    assert isinstance(study_collection, DOIStudyCollection)
    assert len(study_collection.studies) == len(test_doi_list)

    for study, doi in zip(study_collection.studies, test_doi_list, strict=True):
        expected_uuid = uuid5(DOI_NAMESPACE, validate_doi(doi))
        assert isinstance(study, DOIStudy)
        assert study.doi.identifier == doi
        assert study.uid == expected_uuid


def test_generate_study_collection_from_dois_validation_failure(
    mocker, caplog, test_doi_list
):
    mocker.patch(
        "fer.local.run.validate_doi", side_effect=InvalidDOIError("test error")
    )
    with (
        pytest.raises(SystemExit),
        caplog.at_level("ERROR"),
    ):
        generate_study_collection_from_dois(test_doi_list)
    assert "Invalid DOI encountered" in caplog.text


def test_prepare_processor(test_settings):
    processor = prepare_processor(test_settings)
    assert isinstance(processor, FullTextEnhancementProcessor)
    assert processor.settings == test_settings


@pytest.mark.parametrize(
    ("exclude_api", "expected_apis"),
    [
        (None, ["openalex", "crossref", "unpaywall", "scopus"]),
        ([ExternalAPI.CROSSREF], ["openalex", "unpaywall", "scopus"]),
        ([ExternalAPI.OPENALEX, ExternalAPI.SCOPUS], ["crossref", "unpaywall"]),
    ],
)
def test_prepare_processor_excludes_apis_success(
    test_settings, exclude_api, expected_apis
):
    processor = prepare_processor(test_settings, exclude_api=exclude_api)
    assert isinstance(processor, FullTextEnhancementProcessor)
    assert processor.settings == test_settings
    assert [api.name.value for api in processor.available_api_configs] == expected_apis


def test_prepare_processor_excludes_apis_exits_on_all_api_exclusion(test_settings):
    excluded_apis = list(ExternalAPI)
    with pytest.raises(SystemExit):
        prepare_processor(test_settings, exclude_api=excluded_apis)


@pytest.mark.asyncio
async def test_process_identifier_file_dois(test_doi_list, tmp_path):
    test_temp_dois_file = tmp_path / "test_dois.txt"
    test_temp_dois_file.write_text("\n".join(test_doi_list))

    expected_identifiers = [validate_doi(doi) for doi in test_doi_list]
    processed_dois = await process_identifier_file(test_temp_dois_file)

    assert isinstance(processed_dois, list)
    assert [
        identifier.identifier for identifier in processed_dois
    ] == expected_identifiers


@pytest.mark.asyncio
async def test_process_identifier_file_mixed_identifiers(test_doi_list, tmp_path):
    test_identifiers_file = tmp_path / "test_identifiers.txt"
    openalex_ids = ["W123456789", "W987654321"]
    all_identifiers = test_doi_list + openalex_ids
    test_identifiers_file.write_text("\n".join(all_identifiers))

    processed_dois = await process_identifier_file(test_identifiers_file)

    assert isinstance(processed_dois, list)
    assert all(
        isinstance(identifier, (DOIIdentifier | OpenAlexIdentifier))
        for identifier in processed_dois
    )


@pytest.mark.asyncio
async def test_process_identifiers_valid_dois(test_doi_list):
    processed_identifiers = await process_identifiers(test_doi_list)

    assert isinstance(processed_identifiers, list)
    assert all(
        isinstance(identifier, DOIIdentifier) for identifier in processed_identifiers
    )


@pytest.mark.asyncio
async def test_process_identifiers_valid_openalex_ids():
    openalex_ids = ["W123456789", "W987654321"]
    processed_identifiers = await process_identifiers(openalex_ids)

    assert isinstance(processed_identifiers, list)
    assert all(
        isinstance(identifier, OpenAlexIdentifier)
        for identifier in processed_identifiers
    )


@pytest.mark.asyncio
async def test_process_identifiers_mixed_ids(test_doi_list):
    openalex_ids = ["W123456789", "W987654321"]
    combined_identifiers = test_doi_list + openalex_ids
    processed_identifiers = await process_identifiers(combined_identifiers)

    assert isinstance(processed_identifiers, list)
    assert all(
        isinstance(identifier, (DOIIdentifier | OpenAlexIdentifier))
        for identifier in processed_identifiers
    )


@pytest.mark.asyncio
async def test_process_identifiers_invalid_ids():
    invalid_identifiers = ["12345", "not a valid identifier"]

    with pytest.raises(InvalidIdentifierError):
        await process_identifiers(invalid_identifiers)


@pytest.mark.asyncio
async def test_process_identifier_file_empty_file(tmp_path):
    test_temp_dois_file = tmp_path / "test_dois.txt"
    test_temp_dois_file.write_text("")

    with pytest.raises(SystemExit):
        await process_identifier_file(test_temp_dois_file)


@pytest.mark.asyncio
async def test_main_no_excluded_apis_success(mocker, tmp_path, test_doi_list):
    mock_fulltext_fetcher = mocker.AsyncMock()
    mock_fetch_return_value = [
        FullTextResult(
            doi=doi,
            uid=str(uuid5(DOI_NAMESPACE, doi)),
            openalex_id=None,
            fulltext_path=str(Path(tmp_path) / "file.pdf"),
            source="test",
        )
        for doi in test_doi_list
    ]
    mock_fulltext_fetcher.get_many_fulltext_pdfs_cycling_apis.return_value = (
        mock_fetch_return_value
    )

    mock_processor_instance = mocker.AsyncMock(spec=FullTextEnhancementProcessor)
    mock_processor_instance.fulltext_fetcher = mock_fulltext_fetcher
    mocker.patch(
        "fer.local.run.prepare_processor",
        return_value=mock_processor_instance,
    )

    test_output_directory = tmp_path / "output"
    test_output_directory.mkdir()

    test_temp_dois_file = tmp_path / "test_dois.txt"
    test_temp_dois_file.write_text("\n".join(test_doi_list))

    await main(
        identifier_file=test_temp_dois_file,
        output_directory=test_output_directory,
    )

    expected_map_file_name = "retrieved_fulltexts_map.txt"
    assert expected_map_file_name in [f.name for f in test_output_directory.glob("*")]
    mock_fulltext_fetcher.get_many_fulltext_pdfs_cycling_apis.assert_awaited_once()


@pytest.mark.parametrize(
    ("excluded_api_list", "expected_api_list"),
    [
        ([ExternalAPI.CROSSREF], ["openalex", "unpaywall", "scopus"]),
        ([ExternalAPI.OPENALEX, ExternalAPI.SCOPUS], ["crossref", "unpaywall"]),
    ],
)
@pytest.mark.asyncio
async def test_main_excluded_apis_success(
    caplog, mocker, tmp_path, test_doi_list, excluded_api_list, expected_api_list
):
    mock_fetch_return_value = [
        FullTextResult(
            doi=doi,
            uid=str(uuid5(DOI_NAMESPACE, doi)),
            openalex_id=None,
            fulltext_path=str(Path(tmp_path) / "file.pdf"),
            source="test",
        )
        for doi in test_doi_list
    ]
    mocked_get_many_fulltexts = mocker.patch(
        "fer.fetch_fulltext.FullTextBatchFetcher.get_many_fulltext_pdfs_cycling_apis",
        new=mocker.AsyncMock(return_value=mock_fetch_return_value),
    )

    test_output_directory = tmp_path / "output"
    test_output_directory.mkdir()

    test_temp_dois_file = tmp_path / "test_dois.txt"
    test_temp_dois_file.write_text("\n".join(test_doi_list))

    with caplog.at_level("INFO"):
        await main(
            identifier_file=test_temp_dois_file,
            output_directory=test_output_directory,
            exclude_api=excluded_api_list,
        )
    assert f"APIs enabled for fetching: {', '.join(expected_api_list)}" in caplog.text

    expected_map_file_name = "retrieved_fulltexts_map.txt"
    assert expected_map_file_name in [f.name for f in test_output_directory.glob("*")]
    assert (
        mocked_get_many_fulltexts.await_count == 1
    ), "get_many_fulltext_pdfs_cycling_apis should be called once"


@pytest.mark.asyncio
async def test_resolve_openalex_identifiers_empty_list(test_settings):
    resolved, without_doi, identifier_map = await resolve_openalex_identifiers(
        [], test_settings
    )
    assert resolved == []
    assert without_doi == []
    assert identifier_map == {}


@pytest.mark.asyncio
async def test_resolve_openalex_identifiers_all_resolve_success(
    mocker, test_settings, test_openalex_ids
):
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.get_work_openalex_id = mocker.AsyncMock(
        side_effect=[
            {"doi": "10.1000/xyz123"},
            {"doi": "10.1000/xyz456"},
        ]
    )
    mocker.patch("fer.local.run.OpenalexFetcher", return_value=mock_fetcher)

    resolved, without_doi, identifier_map = await resolve_openalex_identifiers(
        test_openalex_ids, test_settings
    )
    assert len(resolved) == len(test_openalex_ids)
    assert without_doi == []
    assert all(isinstance(study, DOIStudy) for study in resolved)
    assert all(study.doi is not None for study in resolved)
    assert len(identifier_map) == len(test_openalex_ids)


@pytest.mark.asyncio
async def test_resolve_openalex_identifiers_partial_resolve(
    mocker, test_settings, test_openalex_ids
):
    expected_id_resolution = [
        {"doi": "10.1000/xyz123"},
        {},
    ]
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.get_work_openalex_id = mocker.AsyncMock(
        side_effect=expected_id_resolution
    )
    mocker.patch("fer.local.run.OpenalexFetcher", return_value=mock_fetcher)

    resolved, without_doi, identifier_map = await resolve_openalex_identifiers(
        test_openalex_ids, test_settings
    )
    assert len(resolved) == len(
        [identifier for identifier in expected_id_resolution if "doi" in identifier]
    )
    assert len(without_doi) == len(
        [identifier for identifier in expected_id_resolution if "doi" not in identifier]
    )
    assert isinstance(resolved[0], DOIStudy)
    assert resolved[0].doi is not None
    assert isinstance(without_doi[0], OpenAlexStudy)
    assert without_doi[0].openalex_id == test_openalex_ids[1]
    assert without_doi[0].doi is None
    assert len(identifier_map) == len(test_openalex_ids)


@pytest.mark.asyncio
async def test_resolve_openalex_identifiers_invalid_doi(
    mocker, test_settings, test_openalex_ids, caplog
):
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.get_work_openalex_id = mocker.AsyncMock(
        return_value={"doi": "invalid_doi"}
    )
    mocker.patch("fer.local.run.OpenalexFetcher", return_value=mock_fetcher)

    with caplog.at_level("WARNING"):
        resolved, without_doi, identifier_map = await resolve_openalex_identifiers(
            test_openalex_ids, test_settings
        )
    assert len(resolved) == 0
    assert len(without_doi) == len(test_openalex_ids)
    assert all(isinstance(study, OpenAlexStudy) for study in without_doi)
    assert "Invalid DOI" in caplog.text
    assert len(identifier_map) == len(test_openalex_ids)


@pytest.mark.asyncio
async def test_resolve_openalex_identifiers_all_without_doi(
    mocker, test_settings, test_openalex_ids, caplog
):
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.get_work_openalex_id = mocker.AsyncMock(return_value={})
    mocker.patch("fer.local.run.OpenalexFetcher", return_value=mock_fetcher)

    with caplog.at_level("WARNING"):
        resolved, without_doi, identifier_map = await resolve_openalex_identifiers(
            test_openalex_ids, test_settings
        )
    assert len(resolved) == 0
    assert len(without_doi) == len(test_openalex_ids)
    assert all(isinstance(study, OpenAlexStudy) for study in without_doi)
    assert all(study.doi is None for study in without_doi)
    assert "No valid DOI found" in caplog.text
    assert len(identifier_map) == len(test_openalex_ids)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=httpx.Request("GET", "https://api.openalex.org/W123"),
            response=httpx.Response(500),
        ),
        httpx.ConnectError("Connection refused"),
        httpx.TimeoutException("Request timed out"),
        httpx.ReadError("Read error"),
        json.JSONDecodeError("Malformed JSON response", doc="", pos=0),
    ],
)
async def test_resolve_openalex_identifiers_error_treated_as_without_doi(
    mocker, test_settings, test_openalex_ids, caplog, error
):
    """

    Test that a single error doesn't cause the entire resolution to fail.

    We should resolve what we can, and treat errors as DOI not found.
    """
    test_resolution_results = [
        {"doi": "10.1000/xyz123"},
        error,
    ]
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.get_work_openalex_id = mocker.AsyncMock(
        side_effect=test_resolution_results
    )
    mocker.patch("fer.local.run.OpenalexFetcher", return_value=mock_fetcher)

    with caplog.at_level("WARNING"):
        resolved, without_doi, identifier_map = await resolve_openalex_identifiers(
            test_openalex_ids, test_settings
        )

    assert len(resolved) == len(
        [
            result
            for result in test_resolution_results
            if isinstance(result, dict) and "doi" in result
        ]
    ), "Only the successful resolution should be in the resolved list"
    assert (
        len(without_doi)
        == len(
            [
                result
                for result in test_resolution_results
                if not (isinstance(result, dict) and "doi" in result)
            ]
        )
    ), "The number of studies without DOIs should match the number of errored resolutions - i.e. 1"
    assert (
        without_doi[0].openalex_id == test_openalex_ids[1]
    ), "The second result errored, so the OpenAlex ID from the second input should be in the without_doi list"
    assert (
        without_doi[0].doi is None
    ), "DOI should be none for the OpenAlex ID that errored"
    assert (
        "Failed to fetch OpenAlex work" in caplog.text
    ), "Error during OpenAlex ID resolution should be logged as a warning"
    assert len(identifier_map) == len(test_openalex_ids)


@pytest.mark.asyncio
async def test_generate_study_collection_doi_only(mocker, test_settings, test_doi_list):
    identifier_list = [DOIIdentifier(identifier=doi) for doi in test_doi_list]
    (
        study_collection,
        openalex_study_collection,
        identifier_map,
    ) = await generate_study_collection(test_settings, identifier_list)
    assert isinstance(study_collection, DOIStudyCollection)
    assert len(study_collection.studies) == len(test_doi_list)
    assert all(isinstance(study, DOIStudy) for study in study_collection.studies)
    assert all(study.doi is not None for study in study_collection.studies)
    assert not openalex_study_collection.studies
    assert len(identifier_map) == len(test_doi_list)


@pytest.mark.asyncio
async def test_generate_study_collection_openalex_only_resolves_to_dois(
    mocker, test_settings, test_openalex_ids
):
    expected_openalex_ids = [
        test_identifier.identifier for test_identifier in test_openalex_ids
    ]
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.get_work_openalex_id = mocker.AsyncMock(
        side_effect=[{"doi": "10.1000/xyz123"}, {"doi": "10.1000/xyz456"}]
    )
    mocker.patch("fer.local.run.OpenalexFetcher", return_value=mock_fetcher)
    (
        study_collection,
        openalex_study_collection,
        identifier_map,
    ) = await generate_study_collection(test_settings, test_openalex_ids)
    assert isinstance(study_collection, DOIStudyCollection)
    assert len(study_collection.studies) == len(test_openalex_ids)
    assert all(isinstance(study, DOIStudy) for study in study_collection.studies)
    assert all(study.doi is not None for study in study_collection.studies)
    assert not openalex_study_collection.studies
    assert len(identifier_map) == len(test_openalex_ids)
    assert all(
        value for value in identifier_map.values() if value in expected_openalex_ids
    )


@pytest.mark.asyncio
async def test_generate_study_collection_openalex_only_partial_doi_resolution(
    mocker, test_settings, test_openalex_ids
):
    expected_openalex_ids = [
        test_identifier.identifier for test_identifier in test_openalex_ids
    ]
    single_doi_resolution_result = [
        {"doi": "10.1000/xyz123"},
        {},
    ]
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.get_work_openalex_id = mocker.AsyncMock(
        side_effect=single_doi_resolution_result
    )
    mocker.patch("fer.local.run.OpenalexFetcher", return_value=mock_fetcher)
    (
        study_collection,
        openalex_study_collection,
        identifier_map,
    ) = await generate_study_collection(test_settings, test_openalex_ids)
    assert isinstance(study_collection, DOIStudyCollection)
    assert len(study_collection.studies) == len(
        [result for result in single_doi_resolution_result if "doi" in result]
    )
    assert all(isinstance(study, DOIStudy) for study in study_collection.studies)
    assert all(study.doi is not None for study in study_collection.studies)
    assert isinstance(openalex_study_collection, OpenAlexStudyCollection)
    assert len(openalex_study_collection.studies) == len(
        [result for result in single_doi_resolution_result if "doi" not in result]
    )
    assert all(
        isinstance(study, OpenAlexStudy) for study in openalex_study_collection.studies
    )
    assert all(study.doi is None for study in openalex_study_collection.studies)
    assert all(
        value for value in identifier_map.values() if value in expected_openalex_ids
    )


@pytest.mark.asyncio
async def test_openalex_retrieval_short_circuit_creates_map(
    mocker, tmp_path, test_openalex_ids
):
    openalex_study_collection = OpenAlexStudyCollection(
        studies=[
            OpenAlexStudy(
                uid=uuid5(DOI_NAMESPACE, test_identifier.identifier),
                openalex_id=test_identifier,
                doi=None,
            )
            for test_identifier in test_openalex_ids
        ]
    )
    uid_to_supplied = {
        str(openalex_study.uid): openalex_study.openalex_id.identifier
        for openalex_study in openalex_study_collection.studies
    }
    expected_map_file = tmp_path / "retrieved_fulltexts_map.txt"

    mock_processor = mocker.MagicMock()
    mock_processor.fulltext_fetcher.full_text_fetcher.fetch = mocker.AsyncMock(
        return_value=[
            RetrievedFullText(
                uid=uuid5(DOI_NAMESPACE, test_identifier.identifier),
                openalex_id=f"https://openalex.org/{test_identifier.identifier}",
                fulltext_path=None,
                error="No PDF found",
            )
            for test_identifier in test_openalex_ids
        ]
    )

    assert expected_map_file.exists() is False
    await openalex_retrieval_short_circuit(
        processor=mock_processor,
        openalex_study_collection=openalex_study_collection,
        output_directory=tmp_path,
        uid_to_supplied=uid_to_supplied,
    )

    content = expected_map_file.read_text()
    content_lines = content.splitlines()
    assert [line.split("\t")[1] for line in content_lines] == [
        test_identifier.identifier for test_identifier in test_openalex_ids
    ]
    assert all(
        f"https://openalex.org/{test_identifier.identifier}" not in content
        for test_identifier in test_openalex_ids
    )
    assert all("None" in content for _ in test_openalex_ids)


@pytest.mark.asyncio
async def test_openalex_retrieval_short_circuit_appends_existing_map(
    mocker, tmp_path, test_openalex_ids
):
    existing_line = "10.1000/xyz123\tfile.pdf\topenalex\n"
    map_file = tmp_path / "retrieved_fulltexts_map.txt"
    map_file.write_text(existing_line)

    openalex_study_collection = OpenAlexStudyCollection(
        studies=[
            OpenAlexStudy(
                uid=uuid5(DOI_NAMESPACE, test_identifier.identifier),
                openalex_id=test_identifier,
                doi=None,
            )
            for test_identifier in test_openalex_ids
        ]
    )
    uid_to_supplied = {
        str(openalex_study.uid): openalex_study.openalex_id.identifier
        for openalex_study in openalex_study_collection.studies
    }

    mock_processor = mocker.MagicMock()
    mock_processor.fulltext_fetcher.full_text_fetcher.fetch = mocker.AsyncMock(
        return_value=[
            RetrievedFullText(
                uid=uuid5(DOI_NAMESPACE, test_identifier.identifier),
                openalex_id=f"https://openalex.org/{test_identifier.identifier}",
                fulltext_path=None,
                error="No PDF found",
            )
            for test_identifier in test_openalex_ids
        ]
    )
    await openalex_retrieval_short_circuit(
        processor=mock_processor,
        openalex_study_collection=openalex_study_collection,
        output_directory=tmp_path,
        uid_to_supplied=uid_to_supplied,
    )
    content = map_file.read_text()
    assert existing_line in content
    assert all(
        f"https://openalex.org/{test_identifier.identifier}" not in content
        for test_identifier in test_openalex_ids
    )
    assert all(
        test_identifier.identifier in content for test_identifier in test_openalex_ids
    )


@pytest.mark.asyncio
async def test_retrieve_fulltexts_from_external_providers_uses_study_openalex_id(
    mocker, tmp_path
):
    doi = "10.1000/xyz123"
    openalex_id = "W1234567890"
    openalex_identifier = OpenAlexIdentifier(identifier=openalex_id)
    study_collection = DOIStudyCollection(
        studies=[
            DOIStudy(
                doi=DOIIdentifier(identifier=doi),
                uid=uuid5(DOI_NAMESPACE, doi),
                openalex_id=openalex_identifier,
            )
        ]
    )
    mock_processor = mocker.MagicMock()
    mock_processor.fulltext_fetcher.get_many_fulltext_pdfs_cycling_apis = (
        mocker.AsyncMock(
            return_value=[
                FullTextResult(
                    doi=doi,
                    uid=str(uuid5(DOI_NAMESPACE, doi)),
                    openalex_id=f"https://openalex.org/{openalex_id}",
                    fulltext_path=str(tmp_path / "file.pdf"),
                    source="scopus",
                )
            ]
        )
    )

    await retrieve_fulltexts_from_external_providers(
        processor=mock_processor,
        study_collection=study_collection,
        output_directory=tmp_path,
        uid_to_supplied={str(uuid5(DOI_NAMESPACE, doi)): doi},
    )

    content = (tmp_path / "retrieved_fulltexts_map.txt").read_text()
    content_lines = content.splitlines()
    assert content_lines[0].split("\t")[1] == openalex_identifier.identifier
    assert "https://openalex.org/" not in content
    assert openalex_id in content


@pytest.mark.asyncio
async def test_main_doi_only(mocker, tmp_path, test_doi_list):
    """DOI-only input: multi-API pipeline runs, short-circuit is skipped."""
    test_identifiers_file = tmp_path / "ids.txt"
    test_identifiers_file.write_text("\n".join(test_doi_list))

    doi_studies = [
        DOIStudy(doi=DOIIdentifier(identifier=doi), uid=uuid5(DOI_NAMESPACE, doi))
        for doi in test_doi_list
    ]
    mocker.patch("fer.local.run.prepare_processor", return_value=mocker.MagicMock())
    mocker.patch(
        "fer.local.run.generate_study_collection",
        new=mocker.AsyncMock(
            return_value=(
                DOIStudyCollection(studies=doi_studies),
                OpenAlexStudyCollection(),
                {},
            )
        ),
    )
    mock_retrieve = mocker.patch(
        "fer.local.run.retrieve_fulltexts_from_external_providers",
        new=mocker.AsyncMock(),
    )
    mock_short_circuit = mocker.patch(
        "fer.local.run.openalex_retrieval_short_circuit", new=mocker.AsyncMock()
    )

    await main(identifier_file=test_identifiers_file, output_directory=tmp_path / "out")

    mock_retrieve.assert_awaited_once()
    mock_short_circuit.assert_not_awaited()


@pytest.mark.asyncio
async def test_main_openalex_only_no_doi(mocker, tmp_path, test_openalex_ids):
    """OpenAlex ID-only input with no DOIs resolved."""
    test_identifiers_file = tmp_path / "ids.txt"
    test_identifiers_file.write_text(
        "\n".join([test_identifier.identifier for test_identifier in test_openalex_ids])
    )

    openalex_studies = [
        OpenAlexStudy(
            doi=None,
            openalex_id=test_identifier,
            uid=uuid5(DOI_NAMESPACE, test_identifier.identifier),
        )
        for test_identifier in test_openalex_ids
    ]
    mocker.patch("fer.local.run.prepare_processor", return_value=mocker.MagicMock())
    mocker.patch(
        "fer.local.run.generate_study_collection",
        new=mocker.AsyncMock(
            return_value=(
                DOIStudyCollection(studies=[]),
                OpenAlexStudyCollection(studies=openalex_studies),
                {},
            )
        ),
    )
    mock_retrieve = mocker.patch(
        "fer.local.run.retrieve_fulltexts_from_external_providers",
        new=mocker.AsyncMock(),
    )
    mock_short_circuit = mocker.patch(
        "fer.local.run.openalex_retrieval_short_circuit", new=mocker.AsyncMock()
    )

    await main(identifier_file=test_identifiers_file, output_directory=tmp_path / "out")

    mock_short_circuit.assert_awaited_once()
    mock_retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_main_mixed_identifiers(
    mocker, tmp_path, test_doi_list, test_openalex_ids
):
    """Mixed DOI and OpenAlex ID input: both multi-API pipeline and short-circuit run."""
    all_identifiers = test_doi_list + [
        test_identifier.identifier for test_identifier in test_openalex_ids
    ]
    test_identifiers_file = tmp_path / "ids.txt"
    test_identifiers_file.write_text("\n".join(all_identifiers))

    doi_studies = [
        DOIStudy(doi=DOIIdentifier(identifier=doi), uid=uuid5(DOI_NAMESPACE, doi))
        for doi in test_doi_list
    ]
    openalex_studies = [
        OpenAlexStudy(
            doi=None,
            openalex_id=test_identifier,
            uid=uuid5(DOI_NAMESPACE, test_identifier.identifier),
        )
        for test_identifier in test_openalex_ids
    ]
    mocker.patch("fer.local.run.prepare_processor", return_value=mocker.MagicMock())
    mocker.patch(
        "fer.local.run.generate_study_collection",
        new=mocker.AsyncMock(
            return_value=(
                DOIStudyCollection(studies=doi_studies),
                OpenAlexStudyCollection(studies=openalex_studies),
                {},
            )
        ),
    )
    mock_retrieve = mocker.patch(
        "fer.local.run.retrieve_fulltexts_from_external_providers",
        new=mocker.AsyncMock(),
    )
    mock_short_circuit = mocker.patch(
        "fer.local.run.openalex_retrieval_short_circuit", new=mocker.AsyncMock()
    )

    await main(identifier_file=test_identifiers_file, output_directory=tmp_path / "out")

    mock_retrieve.assert_awaited_once()
    mock_short_circuit.assert_awaited_once()
