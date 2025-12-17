import pytest

from fer.config import ExternalAPI
from fer.enhancement_processor import FullTextEnhancementProcessor
from fer.fetching.core import Study, StudyCollection
from fer.local.run import (
    generate_study_collection_from_dois,
    main,
    prepare_processor,
    process_incoming_dois,
)
from fer.utils import InvalidDOIError


@pytest.fixture
def test_doi_list():
    return [
        "10.1000/xyz123",
        "10.1000/xyz456",
        "10.1000/xyz789",
    ]


def test_generate_study_collection_from_dois_success(mocker, test_doi_list):
    mock_uuid = "123e4567-e89b-12d3-a456-426614174000"
    mocker.patch("fer.local.run.uuid4", return_value=mock_uuid)

    study_collection = generate_study_collection_from_dois(test_doi_list)

    assert isinstance(study_collection, StudyCollection)
    assert len(study_collection.studies) == len(test_doi_list)

    for study, doi in zip(study_collection.studies, test_doi_list, strict=False):
        assert isinstance(study, Study)
        assert study.doi.identifier == doi
        assert str(study.uid) == mock_uuid


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


def test_process_incoming_dois_from_file(test_doi_list, tmp_path):
    test_temp_dois_file = tmp_path / "test_dois.txt"
    test_temp_dois_file.write_text("\n".join(test_doi_list))

    processed_dois = process_incoming_dois(test_temp_dois_file)

    assert isinstance(processed_dois, list)
    assert processed_dois == test_doi_list


def test_process_incoming_dois_from_file_empty_file(tmp_path):
    test_temp_dois_file = tmp_path / "test_dois.txt"
    test_temp_dois_file.write_text("")

    with pytest.raises(SystemExit):
        process_incoming_dois(test_temp_dois_file)


@pytest.mark.asyncio
async def test_main_no_excluded_apis_success(mocker, tmp_path, test_doi_list):
    mock_fulltext_fetcher = mocker.AsyncMock()
    mock_fetch_return_value = [
        {"doi": doi, "fulltext_path": str(tmp_path / "file.pdf"), "source": "test"}
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
        doi_list=test_temp_dois_file,
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
        {"doi": doi, "fulltext_path": str(tmp_path / "file.pdf"), "source": "test"}
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
            doi_list=test_temp_dois_file,
            output_directory=test_output_directory,
            exclude_api=excluded_api_list,
        )
    assert f"APIs enabled for fetching: {', '.join(expected_api_list)}" in caplog.text

    expected_map_file_name = "retrieved_fulltexts_map.txt"
    assert expected_map_file_name in [f.name for f in test_output_directory.glob("*")]
    assert (
        mocked_get_many_fulltexts.await_count == 1
    ), "get_many_fulltext_pdfs_cycling_apis should be called once"
