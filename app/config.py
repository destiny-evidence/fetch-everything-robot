"""API config parsing and model."""

from enum import StrEnum
from functools import lru_cache

from pydantic import UUID4, BaseModel, EmailStr, Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExternalAPI(StrEnum):
    """
    Exhaustive list of permitted external APIs which we can hit to retrieve full texts.

    New additions here will require definition of
    new pydantic models for parsing their output and new
    implementation of retrieving their output.
    """

    CROSSREF = "crossref"
    SCOPUS = "scopus"
    UNPAYWALL = "unpaywall"


class QueryType(StrEnum):
    """
    Exhaustive list of permitted query types,
    e.g. `batched_single` or `batch`.

    """

    BATCH = "batch"
    BATCHED_SINGLE = "batched_single"


class ExternalAPIPriority(BaseModel):
    """Priority definition of APIs to call for any given DOI."""

    name: str = Field(description="name of the api priority")
    priorities: dict[ExternalAPI, int] = Field(
        ..., description="mapping of `ExternalAPIs` to their priority rank."
    )


external_api_priority = ExternalAPIPriority(
    name="fulltext",
    priorities={
        ExternalAPI.CROSSREF: 1,
        ExternalAPI.UNPAYWALL: 2,
        ExternalAPI.SCOPUS: 3,
    },
)


class Environment(StrEnum):
    """
    Environment that the Fetch Everything Robot is running in.

    **Allowed values**:
    - `local`: The robot is running locally
    - `development`: The robot is running in development
    - `staging`: The robot is running in staging
    - `test`: The robot is running as a test fixture for the repository
    - `production`: The robot is running in production
    """

    LOCAL = "local"
    DEVELOPMENT = "development"
    STAGING = "staging"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Settings model for API."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )
    robot_title: str = Field(
        default="Fetch Everything Robot (FER)",
        description="The title of the robot.",
    )
    robot_secret: str | None = Field(
        default=None,
        description="Secret needed for communicating with destiny repo.",
    )
    robot_id: UUID4 | None = Field(
        default=None,
        description="Client id needed for communicating with destiny repository.",
    )
    destiny_repository_url: HttpUrl

    mailto: EmailStr | None = Field(
        default="test@test.com",
        description="mailto param to add to crossref req headers",
    )

    env: Environment = Field(
        default=Environment.STAGING,
        description="The environment the robot is deployed in.",
    )

    poll_interval_seconds: int = Field(
        default=30,
        description=("How often to poll for new robot enhancement batches (seconds)"),
    )

    batch_size: int = Field(
        default=2,
        description=("The number of references to include per enhancement batch"),
    )

    # API keys for fulltext retrieval
    elsevier_scopus_key: SecretStr | None = Field(
        default=None, description="api key for elsevier scopus api."
    )
    elsevier_scopus_inst_token: SecretStr | None = Field(
        default=None, description="inst token for elsevier scopus api."
    )

    openalex_key: SecretStr | None = Field(
        default=None, description="api key for openalex api."
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get a cached settings object."""
    return Settings()  # type: ignore[call-arg]
