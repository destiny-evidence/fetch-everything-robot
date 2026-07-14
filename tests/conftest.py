# ruff: noqa: E501, S106, ANN002, ANN003, ARG002
import logging
import os
import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import destiny_sdk
import httpx2
import pytest
from loguru import logger
from pydantic import AnyUrl

from fer.config import ExternalAPIPriority, Settings
from fer.data_models.generic import (
    APIConfig,
    ExternalAPI,
    FullTextUnpackStrategy,
    QueryType,
    prepare_api_config,
)
from fer.data_models.scopus import ScopusAPIConfig
from fer.enhancement_processor import FullTextEnhancementProcessor
from fer.fetching import BasePublisherFetcher
from fer.fetching.core import DOIStudyCollection, RetrievedFullText, stream_file

pytest_plugins = [
    "tests.fixtures.generic",
    "tests.fixtures.studies",
    "tests.fixtures.fetching",
    "tests.fixtures.works",
]


@pytest.fixture(scope="session", autouse=True)
def anyio_backend() -> tuple[str, dict]:
    """Specify the anyio backend for async tests."""
    return "asyncio", {"use_uvloop": True}


@pytest.fixture
def temporary_test_file(tmp_path):
    file_path = tmp_path / "temporary_test_file.txt"
    yield file_path
    if file_path.exists():
        file_path.unlink()


@pytest.fixture(autouse=True)
def set_test_environment_variables(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None]:
    """Configure the pytest environment, skipping for evaluation benchmarks."""
    if request.node.get_closest_marker("eval"):
        yield
        return

    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DESTINY_REPOSITORY_URL", "http://localhost:8001/enhancement/")
    monkeypatch.setenv("ROBOT_ID", "e0aba318-eee9-4b4c-b503-7f72547063d8")
    monkeypatch.setenv("ROBOT_SECRET", "dummy_secret")
    monkeypatch.setenv("OPENALEX_KEY", "dummy_openalex_key")
    monkeypatch.setenv("ELSEVIER_SCOPUS_KEY", "dummy_scopus_key")
    monkeypatch.setenv("ELSEVIER_SCOPUS_INST_TOKEN", "dummy_inst_token")
    monkeypatch.setenv("MAILTO", "test@test.com")
    yield
    monkeypatch.delenv("ENV")
    monkeypatch.delenv("DESTINY_REPOSITORY_URL")
    monkeypatch.delenv("ROBOT_ID")
    monkeypatch.delenv("ROBOT_SECRET")
    monkeypatch.delenv("OPENALEX_KEY")
    monkeypatch.delenv("ELSEVIER_SCOPUS_KEY")
    monkeypatch.delenv("ELSEVIER_SCOPUS_INST_TOKEN")
    monkeypatch.delenv("MAILTO")


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
            doi_strategy=["doi"],
            pdf_link_strategy=["best_oa_location", "pdf_url"],
            xml_strategy=None,
        ),
    )


@pytest.fixture
def crossref_api_config_valid_batch():
    return APIConfig(
        name=ExternalAPI.CROSSREF,
        url="https://api.example.com/",
        require_api_key=False,
        api_key_env_var_name=None,
        api_key_placement=None,
        query_type=QueryType.BATCH,
        unpack_strategy=FullTextUnpackStrategy(
            source=ExternalAPI.CROSSREF,
            doi_strategy=["doi"],
            pdf_link_strategy=["message", "link"],
            xml_strategy=None,
        ),
    )


@pytest.fixture
def unpaywall_api_config_valid_batch():
    return APIConfig(
        name=ExternalAPI.UNPAYWALL,
        url="https://api.example.com/",
        require_api_key=False,
        api_key_env_var_name=None,
        api_key_placement=None,
        query_type=QueryType.BATCH,
        unpack_strategy=FullTextUnpackStrategy(
            source=ExternalAPI.UNPAYWALL,
            doi_strategy=["doi"],
            pdf_link_strategy=["best_oa_location", "pdf_url"],
            xml_strategy=None,
        ),
    )


@pytest.fixture
def test_available_api_configs(
    scopus_api_config_valid_batch,
    openalex_api_config_valid_batch,
    crossref_api_config_valid_batch,
    unpaywall_api_config_valid_batch,
) -> list[APIConfig]:
    return [
        openalex_api_config_valid_batch,
        crossref_api_config_valid_batch,
        unpaywall_api_config_valid_batch,
        scopus_api_config_valid_batch,
    ]


@pytest.fixture
def test_external_api_priority() -> ExternalAPIPriority:
    return ExternalAPIPriority(
        name="fulltext",
        priorities={
            ExternalAPI.OPENALEX: 1,
            ExternalAPI.CROSSREF: 2,
            ExternalAPI.UNPAYWALL: 3,
            ExternalAPI.SCOPUS: 4,
        },
    )


@pytest.fixture
def test_prepared_available_api_configs(
    test_available_api_configs, test_settings, test_external_api_priority
) -> dict[str, APIConfig]:
    return prepare_api_config(
        test_available_api_configs,
        test_settings,
        external_api_priority=test_external_api_priority,
    )


@pytest.fixture
def test_global_api_config(
    test_available_api_configs, test_settings
) -> dict[str, APIConfig]:
    return prepare_api_config(
        api_configs=test_available_api_configs,
        settings=test_settings,
    )


class DummyPublisherFetcher(BasePublisherFetcher):
    """Define dummy publisher fetcher for testing purposes."""

    TEST_PUBLISHER = "test_publisher"

    async def download_one_pdf(
        self,
        pdf_url: AnyUrl,
        filepath: Path,
        headers: dict | None = None,
    ) -> Path | None:
        """
        Define a dummy method to simulate downloading a PDF.

        Args:
            pdf_url (AnyUrl): The URL of the PDF to download.
            filepath (Path): Output file path.
            headers (dict | None, optional): Optional headers for the request. Defaults to None.

        Returns:
            Path | None: The path to the downloaded PDF or None if download failed.

        """
        async with httpx2.AsyncClient() as client:
            response = await client.get(pdf_url)
        response.raise_for_status()
        await stream_file(url=pdf_url, destination=filepath)
        return filepath

    async def fetch_many_full_texts(
        self,
        study_collection: DOIStudyCollection,
        output_directory: Path,
        **kwargs: object,
    ) -> list[RetrievedFullText]:
        """
        Define a dummy method to simulate fetching full text.

        Returns:
            dict: A dummy response.

        """
        async with httpx2.AsyncClient() as client:
            response = await client.get("https://example.com/test")
        response.raise_for_status()
        return response.json()


@pytest.fixture
def test_publisher_dict() -> dict[str, BasePublisherFetcher]:
    return {"test_publisher": DummyPublisherFetcher()}


@pytest.fixture
def test_fulltext_enhancement_processor(
    test_available_api_configs,
    test_global_api_config,
    test_settings,
    test_publisher_dict,
) -> FullTextEnhancementProcessor:
    return FullTextEnhancementProcessor(
        settings=test_settings,
        robot_version="9.9.9",
        source_name="Test Fetch Everything Robot",
        global_api_config=test_global_api_config,
        available_api_configs=test_available_api_configs,
        publisher_dict=test_publisher_dict,
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
def test_openalex_ids() -> list[destiny_sdk.identifiers.OpenAlexIdentifier]:
    """Create a list of test OpenAlex IDs."""
    test_ids = ["W1234567890", "W0987654321"]
    return [
        destiny_sdk.identifiers.OpenAlexIdentifier(identifier=test_id)
        for test_id in test_ids
    ]


@pytest.fixture
def mock_reference_file_stream(
    test_reference_ids: list[uuid.UUID], test_dois: list[str]
):
    """Mock a stream for a file containing references."""
    stream_response = []
    for reference_id, doi in zip(test_reference_ids, test_dois, strict=False):
        reference = destiny_sdk.references.Reference(
            id=reference_id,
            identifiers=[destiny_sdk.identifiers.DOIIdentifier(identifier=doi)],
        )
        stream_response.append(bytes(reference.to_jsonl() + "\n", "utf-8"))
    return stream_response


@pytest.fixture
def test_references() -> list[destiny_sdk.references.Reference]:
    """Create a list of test references."""
    return [
        destiny_sdk.references.Reference(
            id=uuid.uuid4(),
            identifiers=[
                destiny_sdk.identifiers.DOIIdentifier(
                    identifier="10.1000/xyz123",
                    identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.DOI,
                )
            ],
        ),
        destiny_sdk.references.Reference(
            id=uuid.uuid4(),
            identifiers=[
                destiny_sdk.identifiers.DOIIdentifier(
                    identifier="10.1000/xyz456",
                    identifier_type=destiny_sdk.identifiers.ExternalIdentifierType.DOI,
                )
            ],
        ),
    ]


@pytest.fixture(scope="session")
def eval_config():
    """
    Generate sampling parameters for evaluation.

    Default to a daily rotating seed and small sample size.
    """
    daily_seed = int(datetime.now(UTC).strftime("%Y%m%d"))

    env_seed = os.environ.get("FER_EVAL_SEED", "").strip()
    env_size = os.environ.get("FER_EVAL_SAMPLE_SIZE", "").strip()

    seed = int(env_seed) if env_seed else daily_seed
    sample_size = int(env_size) if env_size else 10

    return {"seed": seed, "sample_size": sample_size}
