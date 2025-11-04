# ruff: noqa: E501, S106
import logging
import uuid
from collections.abc import Generator

import destiny_sdk
import pytest
from fastapi import status
from loguru import logger
from pytest_httpx import HTTPXMock, IteratorStream

from app.config import Settings
from app.data_models.generic import (
    APIConfig,
    ExternalAPI,
    FullTextUnpackStrategy,
    QueryType,
)
from app.data_models.scopus import ScopusAPIConfig
from app.enhancement_processor import FullTextEnhancementProcessor
from app.fetch_fulltext import prepare_api_config

pytest_plugins = [
    "tests.fixtures.generic",
]


@pytest.fixture(autouse=True)
def set_test_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None]:
    """Configure the pytest environment."""
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DESTINY_REPOSITORY_URL", "http://localhost:8001/enhancement/")
    monkeypatch.setenv("ROBOT_ID", "e0aba318-eee9-4b4c-b503-7f72547063d8")
    monkeypatch.setenv("ROBOT_SECRET", "dummy_secret")
    monkeypatch.setenv("ELSEVIER_SCOPUS_KEY", "dummy_scopus_key")
    monkeypatch.setenv("ELSEVIER_SCOPUS_INST_TOKEN", "dummy_inst_token")
    yield
    monkeypatch.delenv("ENV")
    monkeypatch.delenv("DESTINY_REPOSITORY_URL")
    monkeypatch.delenv("ROBOT_ID")
    monkeypatch.delenv("ROBOT_SECRET")
    monkeypatch.delenv("ELSEVIER_SCOPUS_KEY")
    monkeypatch.delenv("ELSEVIER_SCOPUS_INST_TOKEN")


@pytest.fixture
def scopus_api_config_valid_batch():
    return ScopusAPIConfig(
        name=ExternalAPI.SCOPUS,
        url="https://api.example.com/",
        require_api_key=True,
        api_key_env_var_name="elsevier_scopus_key",  # pragma: allowlist secret
        api_key_placement="X-API-Key",  # pragma: allowlist secret
        query_type=QueryType.BATCHED_SINGLE,
        query_params={},
        headers={"X-API-Key": ""},
        unpack_strategy=FullTextUnpackStrategy(
            source="scopus",
            doi_strategy=["search-results", "entry", "prism:doi"],
            pdf_link_strategy=["search-results", "entry", "pdf_url"],
            xml_strategy=["search-results", "entry", "xml"],
        ),
        api_inst_token_env_var_name="elsevier_scopus_inst_token",  # pragma: allowlist secret
        api_inst_token_placement="X-Inst-Token",  # pragma: allowlist secret
    )


@pytest.fixture
def openalex_api_config_valid_batch():
    return APIConfig(
        name=ExternalAPI.OPENALEX,
        url="https://api.example.com/",
        require_api_key=False,
        api_key_env_var_name=None,
        api_key_placement=None,
        query_type=QueryType.BATCH,
        unpack_strategy=FullTextUnpackStrategy(
            source=ExternalAPI.OPENALEX,
            doi_strategy=["message", "DOI"],
            pdf_link_strategy=["message", "pdf_url"],
            xml_strategy=["message", "xml"],
        ),
    )


@pytest.fixture
def test_global_api_config(
    scopus_api_config_valid_batch, openalex_api_config_valid_batch, test_settings
) -> dict[str, APIConfig]:
    return prepare_api_config(
        api_configs=[scopus_api_config_valid_batch, openalex_api_config_valid_batch],
        settings=test_settings,
    )


@pytest.fixture
def test_fulltext_enhancement_processor(
    scopus_api_config_valid_batch,
    openalex_api_config_valid_batch,
    test_global_api_config,
) -> FullTextEnhancementProcessor:
    return FullTextEnhancementProcessor(
        robot_version="9.9.9",
        source_name="Test Fetch Everything Robot",
        global_api_config=test_global_api_config,
        available_api_configs=[
            scopus_api_config_valid_batch,
            openalex_api_config_valid_batch,
        ],
    )


@pytest.fixture
def test_settings(set_test_environment_variables) -> Settings:
    return Settings()


@pytest.fixture
def caplog(caplog):
    class PropogateHandler(logging.Handler):
        def emit(self, record) -> None:
            logging.getLogger(record.name).handle(record)

    handler_id = logger.add(PropogateHandler(), format="{message}")
    yield caplog
    logger.remove(handler_id)


@pytest.fixture
def test_request_id() -> uuid.UUID:
    """Create a test request ID."""
    return uuid.uuid4()


@pytest.fixture
def test_reference_ids() -> list[uuid.UUID]:
    """Create a list of test reference IDs."""
    return [uuid.uuid4() for _ in range(2)]


@pytest.fixture
def test_dois() -> list[str]:
    """Create a list of test DOIs."""
    return ["10.1000/xyz123", "10.1000/xyz456"]


@pytest.fixture
def mock_reference_file_stream(
    httpx_mock: HTTPXMock, test_reference_ids: list[uuid.UUID], test_dois: list[str]
):
    """Mock a stream for a file containing references."""
    stream_response = []
    for reference_id, doi in zip(test_reference_ids, test_dois, strict=False):
        reference = destiny_sdk.references.Reference(
            id=reference_id,
            identifiers=[destiny_sdk.identifiers.DOIIdentifier(identifier=doi)],
        )
        stream_response.append(bytes(reference.to_jsonl() + "\n", "utf-8"))
    httpx_mock.add_response(stream=IteratorStream(stream_response))


@pytest.fixture
def mock_destiny_repository_response(
    httpx_mock: HTTPXMock,
    test_request_id: uuid.UUID,
    test_reference_ids: list[uuid.UUID],
):
    """Mock a successful enhancement post to destiny repository."""
    create_enhancement_response = destiny_sdk.robots.EnhancementRequestRead(
        id=test_request_id,
        reference_ids=test_reference_ids,
        enhancement_parameters={},
        robot_id=uuid.uuid4(),
        request_status=destiny_sdk.robots.EnhancementRequestStatus.COMPLETED,
    )

    # Mock out our callback
    httpx_mock.add_response(
        method="POST",
        status_code=status.HTTP_200_OK,
        json=create_enhancement_response.model_dump(mode="json"),
    )


@pytest.fixture
def mock_enhancement_put(httpx_mock: HTTPXMock):
    """Mock the putting of references to the results url."""
    httpx_mock.add_response(method="PUT", status_code=status.HTTP_200_OK)


@pytest.fixture
def test_references() -> list[destiny_sdk.references.Reference]:
    """Create a list of test references."""
    return [
        destiny_sdk.references.Reference(
            id=uuid.uuid4(),
            identifiers=[
                destiny_sdk.identifiers.DOIIdentifier(identifier="10.1000/xyz123")
            ],
        ),
        destiny_sdk.references.Reference(
            id=uuid.uuid4(),
            identifiers=[
                destiny_sdk.identifiers.DOIIdentifier(identifier="10.1000/xyz456")
            ],
        ),
    ]
