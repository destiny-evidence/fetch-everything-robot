import uuid

import pytest
from destiny_sdk.enhancements import (
    Enhancement,
    FullTextEnhancement,
)
from destiny_sdk.references import Reference
from destiny_sdk.robots import LinkedRobotError, RobotEnhancementBatch
from pytest_mock import MockerFixture

from fer.enhancement_processor import (
    BatchEnhancementGenerationError,
    FullTextEnhancementProcessor,
    MissingDOIError,
)
from fer.fetch_fulltext import FullTextResult
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
async def test_create_fulltext_enhancement_success(
    mocker: MockerFixture,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
    test_references: list[Reference],
    tmp_path,
):
    generated_fulltexts = [
        FullTextResult(
            doi=test_references[0].identifiers[0].identifier,
            uid=str(test_references[0].id),
            openalex_id=None,
            fulltext_path=str(tmp_path / "one.pdf"),
            source="OPENALEX",
        ),
        FullTextResult(
            doi=test_references[1].identifiers[0].identifier,
            uid=str(test_references[1].id),
            openalex_id=None,
            fulltext_path=str(tmp_path / "two.pdf"),
            source="OPENALEX",
        ),
    ]

    fulltext_enhancement_content = [
        FullTextEnhancement(
            file_url="http://example.com/fulltext.pdf",
            source=generated_fulltext.source,
            visibility="hidden",
        )
        for generated_fulltext in generated_fulltexts
    ]

    fulltext_enhancements = [
        Enhancement(
            id=uuid.uuid4(),
            reference_id=reference.id,
            source=fulltext.source,
            visibility="hidden",
            robot_version="test",
            content_version=f"{uuid.uuid4()}",
            content=fulltext,
        )
        for reference, fulltext in zip(
            test_references, fulltext_enhancement_content, strict=False
        )
    ]

    generate_fulltext_mock = mocker.patch.object(
        test_fulltext_enhancement_processor,
        "generate_fulltext",
        return_value=generated_fulltexts,
    )
    batch_request_mock = mocker.patch.object(
        test_fulltext_enhancement_processor,
        "generate_fulltext_enhancement_batch_request",
        return_value=fulltext_enhancements,
    )

    results = await test_fulltext_enhancement_processor.create_fulltext_enhancement(
        references=test_references,
    )

    generate_fulltext_mock.assert_awaited_once()
    batch_request_mock.assert_awaited_once()
    assert (
        results == fulltext_enhancements
    ), "Expect that the results from the batch request are returned."

    assert all(
        result.reference_id == test_references[i].id for i, result in enumerate(results)
    ), "Expect that the reference IDs in the results match the input references."
    assert all(
        result.source == generated_fulltexts[i].source
        for i, result in enumerate(results)
    ), "Expect that the sources in the results match the generated fulltext sources."


@pytest.mark.asyncio
async def test_create_fulltext_enhancement_failure_zero_fulltexts_generated(
    mocker: MockerFixture,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
    test_references: list[Reference],
):
    test_error_text = "No fulltexts generated for the given references."
    generate_fulltext_mock = mocker.patch.object(
        test_fulltext_enhancement_processor,
        "generate_fulltext",
        side_effect=BatchEnhancementGenerationError(test_error_text),
    )

    with pytest.raises(BatchEnhancementGenerationError) as error_info:
        await test_fulltext_enhancement_processor.create_fulltext_enhancement(
            references=test_references,
        )

    generate_fulltext_mock.assert_awaited_once()
    assert test_error_text in str(error_info.value)


@pytest.mark.asyncio
async def test_generate_fulltext_success(
    mocker,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
    test_fetch_two_results_success: list[RetrievedFullText],
    test_references: list[Reference],
    tmp_path,
):
    fetch_mock = mocker.patch(
        "fer.fetching.fetchers.FullTextFetcher.fetch",
        return_value=test_fetch_two_results_success,
    )

    await test_fulltext_enhancement_processor.generate_fulltext(
        references=test_references,
        output_directory=tmp_path,
    )

    assert (
        fetch_mock.call_count == 1
    ), "Expect that the fetcher is called once with success on the first API attempt"


@pytest.mark.asyncio
async def test_generate_fulltext_partial_success(
    mocker,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
    test_fetch_results_single_success: list[RetrievedFullText],
    test_fetch_results_single_failure: list[RetrievedFullText],
    test_references: list[Reference],
    tmp_path,
):
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
        output_directory=tmp_path,
    )

    assert fetch_mock.call_count == n_available_api_configs, (
        "Expect that the fetcher is called for each available API until all fulltexts"
        " are either found or all APIs are exhausted."
    )
    assert (
        results[0].fulltext_path is not None
    ), "Expect that the first reference has a fulltext path since it was successfully fetched."
    assert (
        results[1].fulltext_path is None
    ), "Expect that the second reference has no fulltext path since it failed to fetch."


@pytest.mark.asyncio
async def test_generate_fulltext_enhancement_batch_request_success(
    mocker,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
    test_references: list[Reference],
    tmp_path,
):
    full_text_results_map = {
        str(test_references[0].id): {
            "fulltext_path": tmp_path / "example.pdf",
            "source": "SCOPUS",
        }
    }
    mocker.patch.object(
        test_fulltext_enhancement_processor,
        "generate_file_url",
        return_value="http://example.com/fulltext.pdf",
    )

    result = await test_fulltext_enhancement_processor.generate_fulltext_enhancement_batch_request(
        references=[test_references[0]],
        full_text_results_map=full_text_results_map,
        available_api_configs=test_fulltext_enhancement_processor.available_api_configs,
        app_title=test_fulltext_enhancement_processor.source_name,
    )

    assert len(result) == len(
        full_text_results_map
    ), "Expect that the result list has the same length as the input references."
    assert isinstance(
        result[0], Enhancement
    ), "Expect that the result is an Enhancement instance when the fulltext path is valid."
    assert (
        result[0].reference_id == test_references[0].id
    ), "Expect that the reference ID in the Enhancement matches the input reference ID."


@pytest.mark.asyncio
async def test_generate_fulltext_enhancement_batch_request_returns_linked_robot_error_missing_file(
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
    test_references: list[Reference],
):
    full_text_results_map = {
        str(test_references[0].id): {
            "fulltext_path": None,
            "source": "SCOPUS",
        }
    }

    result = await test_fulltext_enhancement_processor.generate_fulltext_enhancement_batch_request(
        references=[test_references[0]],
        full_text_results_map=full_text_results_map,
        available_api_configs=test_fulltext_enhancement_processor.available_api_configs,
        app_title=test_fulltext_enhancement_processor.source_name,
    )

    assert len(result) == len(
        full_text_results_map
    ), "Expect that the result list has the same length as the input references."
    assert isinstance(
        result[0], LinkedRobotError
    ), "Expect that the result is a LinkedRobotError instance when the fulltext path is missing."
    assert (
        result[0].reference_id == test_references[0].id
    ), "Expect that the reference ID in the LinkedRobotError matches the input reference ID."


@pytest.mark.asyncio
async def test_generate_fulltext_enhancement_batch_request_handles_file_url_generation_failure(
    mocker: MockerFixture,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
    test_references: list[Reference],
    tmp_path,
):
    full_text_results_map = {
        str(test_references[0].id): {
            "fulltext_path": tmp_path / "example.pdf",
            "source": "SCOPUS",
        }
    }
    mocker.patch.object(
        test_fulltext_enhancement_processor,
        "generate_file_url",
        side_effect=RuntimeError("upload failed"),
    )

    result = await test_fulltext_enhancement_processor.generate_fulltext_enhancement_batch_request(
        references=[test_references[0]],
        full_text_results_map=full_text_results_map,
        available_api_configs=test_fulltext_enhancement_processor.available_api_configs,
        app_title=test_fulltext_enhancement_processor.source_name,
    )

    assert len(result) == len(
        full_text_results_map
    ), "Expect that the result list has the same length as the input references."
    assert isinstance(
        result[0], LinkedRobotError
    ), "Expect that the result is a LinkedRobotError instance when file URL generation fails."
    assert (
        result[0].reference_id == test_references[0].id
    ), "Expect that the reference ID in the LinkedRobotError matches the input reference ID."


@pytest.mark.asyncio
async def test_generate_fulltext_enhancement_batch_request_handles_validation_error(
    mocker: MockerFixture,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
    test_references: list[Reference],
    tmp_path,
):
    """Passing an invalid URL to FullTextEnhancement should raise a ValidationError, which we catch and return as a LinkedRobotError."""
    full_text_results_map = {
        str(test_references[0].id): {
            "fulltext_path": tmp_path / "example.pdf",
            "source": "SCOPUS",
        }
    }
    mocker.patch.object(
        test_fulltext_enhancement_processor,
        "generate_file_url",
        return_value="this-is-not-a-valid-url",
    )

    result = await test_fulltext_enhancement_processor.generate_fulltext_enhancement_batch_request(
        references=[test_references[0]],
        full_text_results_map=full_text_results_map,
        available_api_configs=test_fulltext_enhancement_processor.available_api_configs,
        app_title=test_fulltext_enhancement_processor.source_name,
    )

    assert len(result) == len(
        full_text_results_map
    ), "Expect that the result list has the same length as the input references."
    assert isinstance(
        result[0], LinkedRobotError
    ), "Expect that the result is a LinkedRobotError instance when validation fails."
    assert (
        result[0].reference_id == test_references[0].id
    ), "Expect that the reference ID in the LinkedRobotError matches the input reference ID."


@pytest.mark.asyncio
async def test_process_batch_upload_after_generation(
    mocker: MockerFixture,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
    test_references: list[Reference],
):
    test_robot_request = RobotEnhancementBatch(
        id=uuid.uuid4(),
        reference_storage_url="http://example.com/references",
        result_storage_url="http://example.com/results",
    )

    test_enhancements = [
        Enhancement(
            id=uuid.uuid4(),
            reference_id=reference.id,
            source="SCOPUS",
            visibility="hidden",
            robot_version="test",
            content_version=f"{uuid.uuid4()}",
            content=FullTextEnhancement(
                file_url=f"http://example.com/fulltext_{i}.pdf",
                source="SCOPUS",
                visibility="hidden",
            ),
        )
        for i, reference in enumerate(test_references)
    ]

    mocker.patch.object(
        test_fulltext_enhancement_processor,
        "download_references",
        return_value=test_references,
    )
    create_fulltext_enhancement_mock = mocker.patch.object(
        test_fulltext_enhancement_processor,
        "create_fulltext_enhancement",
        return_value=test_enhancements,
    )
    upload_enhancements_mock = mocker.patch.object(
        test_fulltext_enhancement_processor,
        "upload_enhancements",
        return_value=None,
    )

    await test_fulltext_enhancement_processor.process_batch(test_robot_request)

    create_fulltext_enhancement_mock.assert_awaited_once_with(
        references=test_references
    )
    upload_enhancements_mock.assert_awaited_once_with(
        enhancements=test_enhancements,
        result_storage_url=str(test_robot_request.result_storage_url),
    )


@pytest.mark.asyncio
async def test_generate_fulltext_total_failure_no_fulltexts_found(
    mocker,
    test_fulltext_enhancement_processor,
    test_fetch_two_results_full_error,
    test_references,
    tmp_path,
):
    fetch_mock = mocker.patch(
        "fer.fetching.fetchers.FullTextFetcher.fetch",
        return_value=test_fetch_two_results_full_error,
    )

    with pytest.raises(BatchEnhancementGenerationError):
        await test_fulltext_enhancement_processor.generate_fulltext(
            references=test_references,
            output_directory=tmp_path,
        )

    assert fetch_mock.call_count == len(
        test_fulltext_enhancement_processor.available_api_configs
    ), "Expect that all available APIs are tried."


@pytest.mark.asyncio
async def test_generate_fulltext_total_failure_single_missing_doi(
    mocker,
    test_fulltext_enhancement_processor,
    tmp_path,
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
            output_directory=tmp_path,
        )


@pytest.mark.asyncio
async def test_generate_fulltext_partial_success_empty_fulltexts_found_for_some_references(
    mocker,
    test_fulltext_enhancement_processor,
    test_references,
    test_fetch_results_single_success,
    test_fetch_results_single_failure,
    tmp_path,
):
    expected_results = [
        FullTextResult(
            doi=test_references[0].identifiers[0].identifier,
            uid=str(test_references[0].id),
            openalex_id=None,
            fulltext_path=str(test_fetch_results_single_success[0].fulltext_path),
            source=test_fulltext_enhancement_processor.available_api_configs[
                0
            ].name.value.upper(),
        ),
        FullTextResult(
            doi=test_references[1].identifiers[0].identifier,
            uid=str(test_references[1].id),
            openalex_id=None,
            fulltext_path=None,
            source=None,
        ),
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
        output_directory=tmp_path,
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
