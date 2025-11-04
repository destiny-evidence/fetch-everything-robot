import uuid

import pytest
from destiny_sdk.references import Reference
from destiny_sdk.robots import RobotEnhancementBatch
from pytest_mock import MockerFixture

from app.config import Settings
from app.enhancement_processor import (
    BatchEnhancementGenerationError,
    FullTextEnhancementProcessor,
)


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
        "app.enhancement_processor.FullTextEnhancementProcessor.download_references",
        return_value=test_references,
    )

    create_fulltext_enhancement_mock = mocker.patch(
        "app.enhancement_processor.FullTextEnhancementProcessor.create_fulltext_enhancement",
        side_effect=BatchEnhancementGenerationError("Test batch generation error."),
    )

    upload_enhancements_mock = mocker.patch(
        "app.enhancement_processor.FullTextEnhancementProcessor.upload_enhancements",
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


def test_generate_fulltext_enhancement_batch_request_success(
    mocker,
    test_settings: Settings,
    test_fulltext_enhancement_processor: FullTextEnhancementProcessor,
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
            "id": ref.id,
            "fulltext": f"This is a mocked fulltext for {ref.id}.",
        }
        for ref in test_two_references
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


def test_generate_fulltext_enhancement_batch_request_total_failure_empty_reference_id_in_map(
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
            "id": None,
            "fulltext": f"This is a mocked fulltext for {ref.id}.",
        }
        for ref in test_two_references
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


def test_generate_fulltext_enhancement_batch_request_partial_success_empty_fulltexts_found_for_some_references(
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
        },
        {
            "id": test_two_references[1].id,
            "fulltext": None,
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


def test_generate_fulltext_enhancement_batch_request_appropriate_visibility(
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
        {
            "id": test_two_references[1].id,
            "fulltext": f"This is a mocked fulltext for {test_two_references[1].id}.",
            "source": "crossref",
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


def test_generate_fulltext_enhancement_batch_request_total_failure_no_fulltexts_found_for_any_reference(
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
            "id": ref.id,
            "fulltext": None,
            "source": None,
        }
        for ref in test_two_references
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
