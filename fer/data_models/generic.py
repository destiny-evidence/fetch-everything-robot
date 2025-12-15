"""Generic data models and validators for working with external APIs."""

from loguru import logger
from pydantic import AnyUrl, BaseModel, Field, model_validator

from fer.config import (
    ExternalAPI,
    ExternalAPIPriority,
    QueryType,
    Settings,
    external_api_priority,
)


class APIKeyNotPresentError(Exception):
    """Raised when the required API key is not present in the settings."""


class FullTextUnpackError(Exception):
    """Raise when we fail to unpack a full text."""


class FullTextNotFoundError(Exception):
    """Raise when we fail to find a full text."""


class FullTextUnpackStrategy(BaseModel):
    """
    Strategy for unpacking a retrieved full text object.
    When we retrieve a full text, all we really want
    is the actual full text content in XML, plain text or
    direct link to a PDF.

    This will be hidden in different places for different
    APIs, so here we can stick all the sequential sub-keys we need
    to reference to find our full text.
    """

    source: ExternalAPI

    doi_strategy: list[str] | None = Field(
        default=None, description="Strategy for unpacking DOI from response. Optional."
    )
    pdf_link_strategy: list[str] | None = Field(
        default=None,
        description="""A list of keys to sequentially
        pass to the json response object to retrieve
        PDF link. Optional.""",
    )
    xml_strategy: list[str] | None = Field(
        default=None,
        description="""A list of keys to sequentially
        pass to the json response object to retrieve
        XML representation. Optional.""",
    )

    @model_validator(mode="before")
    @classmethod
    def validate_unpack_strategies(cls, values: dict) -> dict:
        """Ensure at least one unpacking strategy is provided."""
        if not isinstance(values, dict):
            error_message = "Invalid unpacking strategy values provided."
            raise ValueError(error_message)  # noqa: TRY004
        if (
            values.get("pdf_link_strategy") is None
            and values.get("xml_strategy") is None
        ):
            error_message = "At least one unpacking strategy must be provided!"
            raise ValueError(error_message)
        return values


class APIConfig(BaseModel):
    """
    Essential config required to use an external API to get
    full texts and make them available to a destiny Work.
    """

    name: ExternalAPI = Field(
        description="Name (we've given) to this external API service"
    )
    require_api_key: bool = Field(description="Is API key required to hit this API.")
    url: AnyUrl = Field(
        description="URL/endpoint for the given API",
    )
    api_key_env_var_name: str | None = Field(
        description="Name of the environment variable/settings field "
        "which represents an api key for this api.",
        default=None,
    )
    api_key_placement: str | None = Field(
        description="Dict key in `headers` where we should insert our API key.",
        default=None,
    )
    query_type: QueryType | None = Field(
        default=None,
        description="Type of query; i.e. batched_single or batch.",
    )
    query_params: dict | None = Field(
        default={},
        description="Query params to pass with the api call.",
    )
    headers: dict = Field(
        default={"Accept": "application/json"},
        description="Headers (or set of headers) to pass with the request.",
    )
    unpack_strategy: FullTextUnpackStrategy = Field(
        description="Unpack strategy to employ to get full texts."
    )

    @model_validator(mode="before")
    @classmethod
    def api_key_placement_in_headers(cls, values: dict) -> dict:
        """Ensure `api_key_placement` is a key in the headers dict."""
        if values["require_api_key"] and (
            values["headers"] is not None
            and values["api_key_placement"] not in values["headers"]
        ):
            error_message = (
                f"api_key_placement '{values['api_key_placement']}'"
                " must be in the values dict"
            )
            raise ValueError(error_message)
        return values

    def init_api_key(self, settings: Settings) -> None:
        """
        Populate proper request headers with API key if present.

        Raises:
            ApiKeyNotPresentError: if the API key is not present in settings.

        """
        if self.require_api_key:
            logger.debug(f"initializing API key for {self.name} API")
            api_key = (
                getattr(settings, self.api_key_env_var_name, None)
                if self.api_key_env_var_name
                else None
            )
            if api_key is None:
                error_message = f"API key for {self.name} is not present in settings."
                raise APIKeyNotPresentError(error_message)
            self.headers[self.api_key_placement] = api_key.get_secret_value()
        else:
            logger.info("API does not require an API key, skipping header population.")

    @staticmethod
    def build_query_single(doi: str, url: str) -> str:
        """
        Build a query string for single reference as part
        of QueryType.BATCHED_SINGLE.

        Args:
            doi (str): a doi string
            url (str): the URL to append to.

        Returns:
            str: url+query

        """
        if url[-1] != "/":
            url += "/"
        return f"{url}{doi}"

    @staticmethod
    def build_query_batch(
        url: AnyUrl | str, dois: list[str], max_array_length: int = 50
    ) -> str:
        """
        Build a query string for QueryType.Batch.

        Will be used for OpenAlex
        See https://blog.openalex.org/fetch-multiple-dois-in-one-openalex-api-request/
        for details, including the 50 DOI limit per request.

        Args:
            dois (list): list of dois
            max_array_length (int, optional): n DOIs to concat into query string.
                                              Defaults to 50.

        Raises:
            ValueError: If number of items in the dois list exceeds max_array_length.

        Returns:
            str: query string

        """
        # Set a hard limit on the max array length to fit within API constraints
        if len(dois) > max_array_length:
            error_message = (
                "array of items to query for is too long. max"
                f"n(items): {max_array_length}"
            )
            raise ValueError(error_message)
        pipe_separated_dois = "|".join(dois)
        return f"{url!s}?filter=doi:{pipe_separated_dois}"

    def populate_query(
        self, query: str | list[str], max_array_length: int = 15
    ) -> dict:
        """
        Populate a query string into the query params dict.

        Args:
            query (str | list[str]): the body of the query - currently a doi or
                                     list of dois.
            max_array_length (int, optional): max number of identifiers to
                                              build the query from. Defaults to 15.

        Raises:
            TypeError: If the query type does not correspond to the expected type
                for the query type.
            ValueError: If the query type is invalid.

        Returns:
            dict: a dictionary containing the url, query_params, and headers.
                   All passed to the http request for retrieving a full text
                   given target query and APIConfig.

        """
        if self.query_type == QueryType.BATCH:
            if not isinstance(query, list):
                error_message = "query_type `batch` requires a `list` type query."
                raise TypeError(error_message)
            url = self.build_query_batch(
                url=self.url, dois=query, max_array_length=max_array_length
            )
            return {
                "url": url,
                "query_params": self.query_params,
                "headers": self.headers,
            }

        if self.query_type == QueryType.BATCHED_SINGLE:
            is_multi_item_list = isinstance(query, list) and len(query) > 1
            if is_multi_item_list:
                error_message = (
                    "query_type `batched_single` requires a `str` type query, "
                    "or a single-item list."
                )
                raise TypeError(error_message)
            extracted_query = query[0] if isinstance(query, list) else query
            if not isinstance(extracted_query, str):
                error_message = f"Unable to parse query from initial query {query}."
                raise TypeError(error_message)
            url = self.build_query_single(
                doi=extracted_query, url=self.url.encoded_string()
            )
            return {
                "url": url,
                "query_params": self.query_params,
                "headers": self.headers,
            }

        error_message = "Unable to format query. Check query and query type."
        raise ValueError(error_message)


def prepare_api_config(
    api_configs: list[APIConfig],
    settings: Settings,
    external_api_priority: ExternalAPIPriority = external_api_priority,
) -> dict[str, APIConfig]:
    """
    Prepare a dict of APIConfig objects, populated with API keys.

    If API keys are not present for a given API,
    this will be omitted from the overall API config.

    Args:
        api_configs (list[APIConfig]): list of APIConfig objects to prepare.
        settings (Settings): application settings containing API keys.
        external_api_priority (ExternalAPIPriority): External API order of priority.

    Returns:
        dict[str, APIConfig]: a dictionary mapping API names to their configurations.

    """
    all_api_configs = {}  # type: dict
    api_config_map = {config.name.value: config for config in api_configs}
    logger.debug(f"external_api_priority: {external_api_priority.priorities}")
    logger.debug(f"supplied api candidates: {', '.join(api_config_map.keys())}")

    for external_api in [
        external_api_priority,
    ]:
        logger.debug(f"building api config for {external_api}")
        all_api_configs[external_api.name] = {}
        for api in external_api.priorities:
            logger.debug(f"checking if {api.name} in list of available apis...")
            if api.value not in api_config_map:
                error_message = (
                    f"{api.name=} {api.value=} not in available api configs, skipping."
                )
                logger.error(error_message)
                continue
            target_config = api_config_map[api.value]
            try:
                logger.debug(f"trying to find & init api key for {api.name}")
                target_config.init_api_key(settings=settings)
                all_api_configs[external_api_priority.name][api.name] = target_config
                logger.info(f"successfully initialised API key for {api.name}.")
            except APIKeyNotPresentError as missing_api_key_error:
                logger.info(f"no API key for {api.name}. not populating config.")
                logger.info(f"original error message: {missing_api_key_error}.")
                continue

    return all_api_configs
