import json
from pathlib import Path
from uuid import uuid5

import httpx2
import pytest
from destiny_sdk.identifiers import DOIIdentifier, OpenAlexIdentifier
from pytest_mock import MockerFixture

from fer.config import ExternalAPI, Settings
from fer.enhancement_processor import FullTextEnhancementProcessor
from fer.fetch_fulltext import FullTextResult
from fer.fetching.core import (
    DOIStudy,
    DOIStudyCollection,
    OpenAlexStudy,
    OpenAlexStudyCollection,
    RetrievedFullText,
)
from fer.fetching.openalex import OpenalexFetcher
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
async def test_main_openalex_identifier_end_to_end(
    mocker: MockerFixture, tmp_path: Path
):
    openalex_id = "W123456789"
    doi = "10.1000/xyz123"
    pdf_content = b"Test content"
    requests = []
    mock_responses = [
        httpx2.Response(
            200,
            json={
                "id": f"https://openalex.org/{openalex_id}",
                "doi": f"https://doi.org/{doi}",
                "locations": [{"pdf_url": "https://files.example.test/test.pdf"}],
            },
        ),
        httpx2.Response(
            200,
            json={
                "id": f"https://openalex.org/{openalex_id}",
                "doi": f"https://doi.org/{doi}",
                "locations": [{"pdf_url": "https://files.example.test/test.pdf"}],
            },
        ),
        httpx2.Response(200, content=pdf_content),
    ]

    def handle_request(request: httpx2.Request) -> httpx2.Response:
        """
        Define a request handler to return corresponding mock responses.

        Args:
            request (httpx2.Request): The incoming HTTP request.

        Returns:
            httpx2.Response: The mock response corresponding to the request.

        """
        requests.append(request)
        return mock_responses[len(requests) - 1]

    original_async_client_init = httpx2.AsyncClient.__init__

    def use_mock_transport(
        client: httpx2.AsyncClient,
        *,
        timeout: float = 0.0,
        follow_redirects: bool = False,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """
        Replace the supplied transport with a mock for the given AsyncClient.

        Args:
            client (httpx2.AsyncClient): The HTTP client instance.
            transport (httpx2.AsyncBaseTransport | None): The transport supplied by
                the caller, replaced below by the mock transport.

        """
        mock_transport = httpx2.MockTransport(handle_request)

        original_async_client_init(
            client,
            timeout=timeout,
            follow_redirects=follow_redirects,
            transport=mock_transport,
        )

    mocker.patch.object(httpx2.AsyncClient, "__init__", new=use_mock_transport)

    original_openalex_fetcher_init = OpenalexFetcher.__init__

    def init_without_wait(
        fetcher: OpenalexFetcher, settings: Settings, wait_time_seconds: float = 0.0
    ) -> None:
        """
        Initialise the OpenalexFetcher without waiting between requests.

        Callable required for patching the OpenalexFetcher class constructor
        to remove delays during testing.

        Args:
            fetcher (OpenalexFetcher): The OpenalexFetcher instance being initialised.
            settings (Settings): The settings to use for the fetcher.
            wait_time_seconds (float, optional): The time to wait between requests.
                Defaults to 0.0 for this test.

        """
        original_openalex_fetcher_init(fetcher, settings, wait_time_seconds)

    mocker.patch.object(OpenalexFetcher, "__init__", new=init_without_wait)
    identifier_file = tmp_path / "identifiers.txt"
    identifier_file.write_text(openalex_id)
    output_directory = tmp_path / "output"

    await main(
        identifier_file=identifier_file,
        output_directory=output_directory,
        exclude_api=[ExternalAPI.CROSSREF, ExternalAPI.UNPAYWALL, ExternalAPI.SCOPUS],
    )

    study_uid = uuid5(DOI_NAMESPACE, doi)
    assert (
        output_directory / f"{study_uid}.pdf"
    ).read_bytes() == pdf_content, "PDF content should match the expected."
    assert (
        (output_directory / "retrieved_fulltexts_map.txt").read_text().splitlines()
        == [
            "Supplied Identifier\tOpenAlex ID\tDOI\tFilename\tSource API",
            f"{openalex_id}\t{openalex_id}\t{doi}\t{study_uid}.pdf\tOPENALEX",
        ]
    ), "Map file should contain the correct mapping of identifiers to retrieved full texts"
    assert len(requests) == len(
        mock_responses
    ), "All expected requests should have been made"


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
    mocker, test_settings, openalex_ids_factory
):
    test_openalex_ids = openalex_ids_factory(2)
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
    mocker, test_settings, openalex_ids_factory
):
    test_openalex_ids = openalex_ids_factory(2)
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
    mocker, test_settings, openalex_ids_factory, caplog
):
    test_openalex_ids = openalex_ids_factory(2)
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
    mocker, test_settings, openalex_ids_factory, caplog
):
    test_openalex_ids = openalex_ids_factory(2)
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
        httpx2.HTTPStatusError(
            "500 Internal Server Error",
            request=httpx2.Request("GET", "https://api.openalex.org/W123"),
            response=httpx2.Response(500),
        ),
        httpx2.ConnectError("Connection refused"),
        httpx2.TimeoutException("Request timed out"),
        httpx2.ReadError("Read error"),
        json.JSONDecodeError("Malformed JSON response", doc="", pos=0),
    ],
)
async def test_resolve_openalex_identifiers_error_treated_as_without_doi(
    mocker, test_settings, openalex_ids_factory, caplog, error
):
    """

    Test that a single error doesn't cause the entire resolution to fail.

    We should resolve what we can, and treat errors as DOI not found.
    """
    test_openalex_ids = openalex_ids_factory(2)
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
    mocker, test_settings, openalex_ids_factory
):
    test_openalex_ids = openalex_ids_factory(2)
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
    mocker, test_settings, openalex_ids_factory
):
    test_openalex_ids = openalex_ids_factory(2)
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
    mocker, tmp_path, openalex_ids_factory
):
    test_openalex_ids = openalex_ids_factory(2)
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
    mocker, tmp_path, openalex_ids_factory
):
    test_openalex_ids = openalex_ids_factory(2)
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
async def test_main_openalex_only_no_doi(mocker, tmp_path, openalex_ids_factory):
    """OpenAlex ID-only input with no DOIs resolved."""
    test_openalex_ids = openalex_ids_factory(2)
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
    mocker, tmp_path, test_doi_list, openalex_ids_factory
):
    """Mixed DOI and OpenAlex ID input: both multi-API pipeline and short-circuit run."""
    test_openalex_ids = openalex_ids_factory(2)
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


@pytest.mark.asyncio
async def test_main_duplicate_doi_uses_cached_file_once_while_fetching_uncached_doi(
    mocker, tmp_path, test_doi_list
):
    cached_doi = test_doi_list[0]
    uncached_doi = test_doi_list[1]
    identifier_file = tmp_path / "doi_identifiers.txt"
    identifier_file.write_text(f"{cached_doi}\n{cached_doi}\n{uncached_doi}\n")

    output_directory = tmp_path / "output"
    output_directory.mkdir()
    cached_pdf = (
        output_directory / f"{uuid5(DOI_NAMESPACE, validate_doi(cached_doi))}.pdf"
    )
    cached_pdf.write_bytes(b"cached content")
    uncached_pdf = tmp_path / "uncached.pdf"
    fetched_study_uids = []

    async def fetch_uncached_study(**kwargs) -> list[RetrievedFullText]:
        """
        Simulate fetching an uncached study and record the UIDs of studies being fetched.

        Returns:
            list[RetrievedFullText]: A list containing a single RetrievedFullText object for the uncached DOI study.

        """
        fetched_study_uids.extend(
            study.uid for study in kwargs["study_collection"].studies
        )
        return [
            RetrievedFullText.model_construct(
                doi=uncached_doi,
                uid=uuid5(DOI_NAMESPACE, uncached_doi),
                openalex_id=None,
                fulltext_path=uncached_pdf,
            )
        ]

    provider_fetch = mocker.patch(
        "fer.fetching.fetchers.FullTextFetcher.fetch",
        side_effect=fetch_uncached_study,
    )

    await main(identifier_file=identifier_file, output_directory=output_directory)

    assert (
        provider_fetch.await_count == 1
    ), "The fetcher should be called only once for the uncached DOI."
    assert fetched_study_uids == [
        uuid5(DOI_NAMESPACE, uncached_doi)
    ], "Only the uncached DOI study should be fetched, and checked by identifier."
    map_lines = (
        (output_directory / "retrieved_fulltexts_map.txt").read_text().splitlines()
    )
    assert len(map_lines) == 3, "Expect a header and one result row per unique DOI."
    result_rows = [line.split("\t") for line in map_lines[1:]]
    assert [row[0] for row in result_rows] == [
        cached_doi,
        uncached_doi,
    ], "The map file should contain both the cached and uncached DOIs."
    assert (
        [row[3] for row in result_rows] == [cached_pdf.name, uncached_pdf.name]
    ), "The map file should reference the correct PDF filenames for both cached and uncached DOIs."


@pytest.mark.asyncio
async def test_generate_study_collection_respects_input_identifier_order_dois_only(
    mocker, test_settings, test_doi_list
):
    """Ensure that the order of identifiers in the input list is preserved in the output study collections."""
    extended_test_doi_list = test_doi_list + test_doi_list
    input_doi_identifiers = [
        DOIIdentifier(identifier=doi) for doi in extended_test_doi_list
    ]

    expected_unique_output_identifiers = [
        extended_test_doi_list[0],
        extended_test_doi_list[1],
        extended_test_doi_list[2],
    ]

    (
        study_collection,
        openalex_study_collection,
        identifier_map,
    ) = await generate_study_collection(test_settings, input_doi_identifiers)

    assert (
        [study.doi.identifier for study in study_collection.studies]
        == expected_unique_output_identifiers
    ), "The DOIStudyCollection should contain all unique DOIs in the order they were first encountered in the input list. Duplicated DOIs should be dropped."
    assert (
        not openalex_study_collection.studies
    ), "The OpenAlexStudyCollection should be empty when only DOIs are provided."
    assert (
        list(identifier_map.values()) == expected_unique_output_identifiers
    ), "The identifier map should contain all unique identifiers in the order they were first encountered in the input list. Identifiers resolving to duplicated DOIs should be dropped."


@pytest.mark.asyncio
async def test_generate_study_collection_respects_input_identifier_order_resolved_openalex_ids(
    mocker, test_settings, openalex_ids_factory, test_doi_list
):
    """Ensure that the order of identifiers in the input list is preserved in the output study collections."""
    test_openalex_ids = openalex_ids_factory(3)
    duplicated_openalex_ids = test_openalex_ids + test_openalex_ids
    duplicated_test_doi_list = test_doi_list + test_doi_list

    resolved_openalex_ids_to_dois = [
        {"doi": test_doi} for test_doi in duplicated_test_doi_list
    ]

    mock_fetcher = mocker.MagicMock()
    mock_fetcher.get_work_openalex_id = mocker.AsyncMock(
        side_effect=resolved_openalex_ids_to_dois
    )
    mocker.patch("fer.local.run.OpenalexFetcher", return_value=mock_fetcher)

    expected_unique_output_identifiers = [
        duplicated_openalex_ids[0].identifier,
        duplicated_openalex_ids[1].identifier,
        duplicated_openalex_ids[2].identifier,
    ]

    (
        study_collection,
        openalex_study_collection,
        identifier_map,
    ) = await generate_study_collection(test_settings, duplicated_openalex_ids)

    assert (
        [
            (
                study.doi.identifier,
                study.openalex_id.identifier if study.openalex_id else None,
            )
            for study in study_collection.studies
        ]
        == [
            (duplicated_test_doi_list[0], duplicated_openalex_ids[0].identifier),
            (duplicated_test_doi_list[1], duplicated_openalex_ids[1].identifier),
            (duplicated_test_doi_list[2], duplicated_openalex_ids[2].identifier),
        ]
    ), "The DOIStudyCollection should contain all unique DOIs in the order they were first encountered in the input list. Duplicated openalex IDs and their duplicated DOIs should be dropped."

    assert (
        openalex_study_collection.studies == []
    ), "The OpenAlexStudyCollection should be empty since all OpenAlex IDs resolved to DOIs."
    assert (
        list(identifier_map.values()) == expected_unique_output_identifiers
    ), "The identifier map should contain all unique identifiers in the order they were first encountered in the input list. Identifiers resolving to duplicated DOIs should be dropped."


@pytest.mark.asyncio
async def test_generate_study_collection_respects_input_identifier_order_unresolved_openalex_ids(
    mocker, test_settings, openalex_ids_factory, test_doi_list
):
    """Ensure that the order of identifiers in the input list is preserved in the output study collections."""
    test_openalex_ids = openalex_ids_factory(3)
    duplicated_openalex_ids = test_openalex_ids + test_openalex_ids
    duplicated_test_doi_list = test_doi_list + test_doi_list

    resolved_openalex_ids_to_dois = [{} for _ in duplicated_test_doi_list]

    mock_fetcher = mocker.MagicMock()
    mock_fetcher.get_work_openalex_id = mocker.AsyncMock(
        side_effect=resolved_openalex_ids_to_dois
    )
    mocker.patch("fer.local.run.OpenalexFetcher", return_value=mock_fetcher)

    expected_unique_output_identifiers = [
        duplicated_openalex_ids[0].identifier,
        duplicated_openalex_ids[1].identifier,
        duplicated_openalex_ids[2].identifier,
    ]

    (
        study_collection,
        openalex_study_collection,
        identifier_map,
    ) = await generate_study_collection(test_settings, duplicated_openalex_ids)

    assert (
        study_collection.studies == []
    ), "The DOIStudyCollection should be empty since all OpenAlex IDs failed to resolve to DOIs."
    assert (
        [study.openalex_id.identifier for study in openalex_study_collection.studies]
        == expected_unique_output_identifiers
    ), "The OpenAlexStudyCollection should contain all unique OpenAlex IDs in the order they were first encountered in the input list. Duplicated OpenAlex IDs should be dropped."
    assert (
        list(identifier_map.values()) == expected_unique_output_identifiers
    ), "The identifier map should contain all unique identifiers in the order they were first encountered in the input list. Identifiers resolving to duplicated DOIs should be dropped."


@pytest.mark.asyncio
async def test_generate_study_collection_respects_input_identifier_order_mixed_list_openalex_first(
    mocker, test_settings, test_doi_list, openalex_ids_factory
):
    """
    Ensure that the order of identifiers in the input list is preserved in the output study collections.

    Provides a mixed list of DOIs and OpenAlex IDs with OpenAlex IDs first.
    The first 3 openalex IDs should resolve to DOIs.
    """
    extended_test_doi_list = [
        *test_doi_list,
        "10.1000/xyz101",
        "10.1000/xyz102",
        "10.1000/xyz103",
    ]
    test_openalex_ids = openalex_ids_factory(len(extended_test_doi_list))
    input_doi_identifiers = [
        DOIIdentifier(identifier=doi) for doi in extended_test_doi_list
    ]
    all_identifiers = test_openalex_ids + input_doi_identifiers

    three_resolved_openalex_ids_to_dois = [
        {"doi": test_doi} for test_doi in extended_test_doi_list[:3]
    ] + [{} for _ in test_openalex_ids[3:]]

    mock_fetcher = mocker.MagicMock()
    mock_fetcher.get_work_openalex_id = mocker.AsyncMock(
        side_effect=three_resolved_openalex_ids_to_dois
    )
    mocker.patch("fer.local.run.OpenalexFetcher", return_value=mock_fetcher)

    expected_unique_output_identifiers = [
        *(identifier.identifier for identifier in test_openalex_ids),
        *extended_test_doi_list[3:],
    ]

    (
        study_collection,
        openalex_study_collection,
        identifier_map,
    ) = await generate_study_collection(test_settings, all_identifiers)

    assert (
        [
            (
                study.doi.identifier,
                study.openalex_id.identifier if study.openalex_id else None,
            )
            for study in study_collection.studies
        ]
        == [
            (extended_test_doi_list[0], test_openalex_ids[0].identifier),
            (extended_test_doi_list[1], test_openalex_ids[1].identifier),
            (extended_test_doi_list[2], test_openalex_ids[2].identifier),
            (extended_test_doi_list[3], None),
            (extended_test_doi_list[4], None),
            (extended_test_doi_list[5], None),
        ]
    ), "Expect that the first three OpenAlex IDs resolve to DOIs, three do not, three DOIs are duplicated as OpenAlex IDs already resolve to them, and three DOIs are directly supplied. This makes a total of 6 studies in the DOIStudyCollection."

    assert [
        study.openalex_id.identifier for study in openalex_study_collection.studies
    ] == [identifier.identifier for identifier in test_openalex_ids[3:]], ""

    assert (
        list(identifier_map.values()) == expected_unique_output_identifiers
    ), "The identifier map should contain all unique identifiers in the order they were first encountered in the input list. Identifiers resolving to duplicated DOIs should be dropped."


@pytest.mark.asyncio
async def test_generate_study_collection_respects_input_identifier_order_mixed_list_doi_first(
    mocker, test_settings, test_doi_list, openalex_ids_factory
):
    """

    Ensure that the order of identifiers in the input list is preserved in the output study collections.

    Provides a mixed list of DOIs and OpenAlex IDs with DOIs first.
    The first 3 openalex IDs should resolve to DOIs.
    """
    extended_test_doi_list = [
        *test_doi_list,
        "10.1000/xyz101",
        "10.1000/xyz102",
        "10.1000/xyz103",
    ]
    test_openalex_ids = openalex_ids_factory(len(extended_test_doi_list))
    input_doi_identifiers = [
        DOIIdentifier(identifier=doi) for doi in extended_test_doi_list
    ]
    all_identifiers = input_doi_identifiers + test_openalex_ids

    three_resolved_openalex_ids_to_dois = [
        {"doi": test_doi} for test_doi in extended_test_doi_list[:3]
    ] + [{} for _ in test_openalex_ids[3:]]

    mock_fetcher = mocker.MagicMock()
    mock_fetcher.get_work_openalex_id = mocker.AsyncMock(
        side_effect=three_resolved_openalex_ids_to_dois
    )
    mocker.patch("fer.local.run.OpenalexFetcher", return_value=mock_fetcher)

    expected_unique_output_identifiers = [
        *extended_test_doi_list,
        *[identifier.identifier for identifier in test_openalex_ids[3:]],
    ]

    (
        study_collection,
        openalex_study_collection,
        identifier_map,
    ) = await generate_study_collection(test_settings, all_identifiers)

    assert (
        [
            (
                study.doi.identifier,
                study.openalex_id.identifier if study.openalex_id else None,
            )
            for study in study_collection.studies
        ]
        == [
            *[(doi, None) for doi in extended_test_doi_list[:6]],
        ]
    ), "Expect that the first three OpenAlex IDs resolve to DOIs, three do not, three DOIs are duplicated as OpenAlex IDs already resolve to them, and three DOIs are directly supplied. This makes a total of 6 studies in the DOIStudyCollection."

    assert [
        study.openalex_id.identifier for study in openalex_study_collection.studies
    ] == [identifier.identifier for identifier in test_openalex_ids[3:]], ""

    assert (
        list(identifier_map.values()) == expected_unique_output_identifiers
    ), "The identifier map should contain all unique identifiers in the order they were first encountered in the input list. Identifiers resolving to duplicated DOIs should be dropped."
