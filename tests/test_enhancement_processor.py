import uuid

import pytest
from destiny_sdk.references import Reference
from destiny_sdk.robots import RobotEnhancementBatch
from pytest_mock import MockerFixture

from fer.enhancement_processor import (
    BatchEnhancementGenerationError,
    FullTextEnhancementProcessor,
    MissingDOIError,
)
from fer.fetching.core import RetrievedFullText


@pytest.mark.asyncio
async def test_process_batch_full_batch_failure(
    mocker: MockerFixture,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
    test_references: list[Reference],
):
    test_robot_request = RobotEnhancementBatch(
        id=uuid.uuid4(),
        reference_storage_url="http://example.com/references",
        result_storage_url="http://example.com/results",
    )

    download_references_mock = mocker.patch(
        "fer.enhancement_processor.FullTextEnhancementProcessor.download_references",
        return_value=test_references,
    )

    create_fulltext_enhancement_mock = mocker.patch(
        "fer.enhancement_processor.FullTextEnhancementProcessor.create_fulltext_enhancement",
        side_effect=BatchEnhancementGenerationError("Test batch generation error."),
    )

    upload_enhancements_mock = mocker.patch(
        "fer.enhancement_processor.FullTextEnhancementProcessor.upload_enhancements",
        return_value=None,
    )

    with pytest.raises(BatchEnhancementGenerationError) as error_info:
        await test_fulltext_enhancement_processor.process_batch(test_robot_request)

    assert str(error_info.value) == "Test batch generation error."

    (
        download_references_mock.assert_called_once(),
        "Expect that the references are downloaded via a single call.",
    )
    (
        create_fulltext_enhancement_mock.assert_called_once(),
        "Expect that the fulltext creation is attempted once for the batch.",
    )
    (
        upload_enhancements_mock.assert_not_called(),
        "Expect that no upload is attempted in this method if the batch generation fails.",
    )


@pytest.mark.asyncio
async def test_generate_fulltext_success(
    mocker,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
    test_fetch_two_results_success: list[RetrievedFullText],
    test_references: list[Reference],
):
    fetch_mock = mocker.patch(
        "fer.fetching.fetchers.FullTextFetcher.fetch",
        return_value=test_fetch_two_results_success,
    )

    await test_fulltext_enhancement_processor.generate_fulltext(
        references=test_references,
    )

    assert (
        fetch_mock.call_count == 1
    ), "Expect that the fetcher is called once with success on the first API attempt"


@pytest.mark.asyncio
async def test_generate_fulltext_total_failure_no_fulltexts_found(
    mocker,
    test_fulltext_enhancement_processor,
    test_fetch_two_results_full_error,
    test_references,
):
    fetch_mock = mocker.patch(
        "fer.fetching.fetchers.FullTextFetcher.fetch",
        return_value=test_fetch_two_results_full_error,
    )

    with pytest.raises(BatchEnhancementGenerationError):
        await test_fulltext_enhancement_processor.generate_fulltext(
            references=test_references,
        )

    assert fetch_mock.call_count == len(
        test_fulltext_enhancement_processor.available_api_configs
    ), "Expect that all available APIs are tried."


@pytest.mark.asyncio
async def test_generate_fulltext_total_failure_single_missing_doi(
    mocker,
    test_fulltext_enhancement_processor,
):
    test_good_reference_id = uuid.uuid4()
    test_bad_reference_id = uuid.uuid4()
    test_two_references = [
        Reference(
            id=test_good_reference_id,
            identifiers=[
                {"identifier": "10.1093/ajae/aaq063", "identifier_type": "doi"}
            ],
            enhancements=[],
        ),
        Reference(
            id=test_bad_reference_id,
            identifiers=[{"identifier": "W123456789", "identifier_type": "open_alex"}],
            enhancements=[],
        ),
    ]

    with pytest.raises(BatchEnhancementGenerationError):
        await test_fulltext_enhancement_processor.generate_fulltext(
            references=test_two_references,
        )


@pytest.mark.asyncio
async def test_generate_fulltext_partial_success_empty_fulltexts_found_for_some_references(
    mocker,
    test_fulltext_enhancement_processor,
    test_references,
    test_fetch_results_single_success,
    test_fetch_results_single_failure,
):
    expected_results = [
        {
            "doi": test_references[0].identifiers[0].identifier,
            "fulltext_path": str(test_fetch_results_single_success[0].fulltext_path),
            "source": test_fulltext_enhancement_processor.available_api_configs[
                0
            ].name.value.upper(),
        },
        {
            "doi": test_references[1].identifiers[0].identifier,
            "fulltext_path": None,
            "source": None,
        },
    ]

    n_available_api_configs = len(
        test_fulltext_enhancement_processor.available_api_configs
    )
    expected_fetch_results_array = [test_fetch_results_single_success] + [
        test_fetch_results_single_failure
    ] * (n_available_api_configs - 1)
    fetch_mock = mocker.patch(
        "fer.fetching.fetchers.FullTextFetcher.fetch",
        side_effect=expected_fetch_results_array,
    )

    results = await test_fulltext_enhancement_processor.generate_fulltext(
        references=test_references,
    )

    assert fetch_mock.call_count == n_available_api_configs, (
        "Expect that the fetcher is called for each available API until all fulltexts"
        " are either found or all APIs are exhausted."
    )

    assert results == expected_results


@pytest.mark.xfail(
    reason="Not implemented yet - we need to map the source to visibility"
)
def test_generate_fulltext_request_appropriate_visibility(
    mocker,
    test_settings,
    test_fulltext_enhancement_processor,
    scopus_api_config_valid_batch,
):
    test_two_references = [
        Reference(
            id=uuid.uuid4(),
            identifiers=[
                {"identifier": "10.1093/ajae/aaq063", "identifier_type": "doi"}
            ],
            enhancements=[],
        ),
        Reference(
            id=uuid.uuid4(),
            identifiers=[
                {"identifier": "10.1093/ajae/aaq064", "identifier_type": "doi"}
            ],
            enhancements=[],
        ),
    ]

    test_enhancement_references_map = [
        {
            "id": test_two_references[0].id,
            "fulltext": f"This is a mocked fulltext for {test_two_references[0].id}.",
            "source": "SCOPUS",
        },
    ]
    available_api_configs = [scopus_api_config_valid_batch]
    test_app_title = "A test app for batch requests."

    with pytest.raises(NotImplementedError):
        test_fulltext_enhancement_processor.generate_fulltext_enhancement_batch_request(
            references=test_two_references,
            enhancements_references_map=test_enhancement_references_map,
            available_api_configs=available_api_configs,
            app_title=test_app_title,
        )


def test_get_study_collection_from_references_raises_error_missing_doi():
    test_good_reference_id = uuid.uuid4()
    test_bad_reference_id = uuid.uuid4()
    reference_with_doi = Reference(
        id=test_good_reference_id,
        identifiers=[{"identifier": "10.1000/xyz123", "identifier_type": "doi"}],
        enhancements=[],
    )

    reference_without_doi = Reference(
        id=test_bad_reference_id,
        identifiers=[{"identifier": "W123456789", "identifier_type": "open_alex"}],
        enhancements=[],
    )

    with pytest.raises(MissingDOIError) as error_info:
        FullTextEnhancementProcessor.get_study_collection_from_references(
            references=[reference_with_doi, reference_without_doi]
        )
    assert str(test_bad_reference_id) in str(error_info.value)
