"""Config constants for SCOPUS API; single & batch."""

from loguru import logger
from pydantic import Field

from app.config import Settings
from app.data_models.generic import (
    APIConfig,
    APIKeyNotPresentError,
    FullTextUnpackStrategy
)


SCOPUS_URL = "https://api.elsevier.com/content/article/doi"
SCOPUS_QUERY_PARAMS = {"next_cursor": "*", "view": "FULL"}

SCOPUS_PDF_LINK_HEADERS = {
    "Accept": "application/json",
    "X-ELS-APIKey": "",
    "X-ELS-Insttoken": "",
}

SCOPUS_XML_HEADERS = {
    "Accept": "text/xml",
    "X-ELS-APIKey": "",
    "X-ELS-Insttoken": "",
}

SCOPUS_HEADERS = {
    "pdf_link": SCOPUS_PDF_LINK_HEADERS,
    "xml": SCOPUS_XML_HEADERS,
}

SCOPUS_FULLTEXT_UNPACK_STRATEGY = FullTextUnpackStrategy(
    source="scopus",
    doi_strategy=["full-text-retrieval-response", "coredata", "prism:doi"],
    pdf_link_strategy=["full-text-retrieval-response", "objects", "object"],
    xml_strategy=["full-text-retrieval-response", "originalText"],
)


class ScopusAPIConfig(APIConfig):
    """
    Configuration for the SCOPUS API.

    Extends the base APIConfig to add Insttoken handling.
    """

    api_inst_token_placement: str | None = Field(
        description="Inst token for Scopus API", default="X-ELS-Insttoken"
    )
    api_inst_token_env_var_name: str | None = Field(
        description="Environment variable for Inst token",
        default="elsevier_scopus_inst_token",
    )

    def init_api_key(self, settings: Settings) -> None:
        """
        Populate proper request headers with API key if present.

        Raises:
            ApiKeyNotPresentError: If the API key is not present in settings.

        """
        logger.debug(f"initializing API key for {self.name} API")
        api_key = (
            getattr(settings, self.api_key_env_var_name, None)
            if self.api_key_env_var_name
            else None
        )
        inst_token = (
            getattr(settings, self.api_inst_token_env_var_name, None)
            if self.api_inst_token_env_var_name
            else None
        )
        if api_key is None:
            error_message = f"API key for {self.name} is not present in settings."
            raise APIKeyNotPresentError(error_message)
        if inst_token is None:
            error_message = (
                f"Inst token for {self.name} is not present in settings"
                " skipping header population."
            )
            logger.warning(error_message)
        self.headers[self.api_key_placement] = api_key.get_secret_value()
        self.headers[self.api_inst_token_placement] = (
            inst_token.get_secret_value() if inst_token else ""
        )


def get_scopus_batch_api_config() -> ScopusAPIConfig:
    """
    Define and return the Scopus batch API configuration.

    Returns:
        ScopusAPIConfig: The configuration for the Scopus batch API.

    """
    return ScopusAPIConfig(
        name="scopus_batch",
        url=SCOPUS_URL,
        require_api_key=True,
        api_key_env_var_name="elsevier_scopus_key",  # pragma: allowlist secret
        api_key_placement="X-ELS-APIKey",  # pragma: allowlist secret
        query_type="batched_single",
        query_params=SCOPUS_QUERY_PARAMS,
        headers=SCOPUS_HEADERS,
        unpack_strategy=SCOPUS_FULLTEXT_UNPACK_STRATEGY,
    )
