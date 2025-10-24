"""Generic data models and validators for working with external APIs."""

from enum import StrEnum

from loguru import logger
from pydantic import AnyUrl, BaseModel, Field, model_validator

from app.config import Settings


class APIKeyNotPresentError(Exception):
    """Raised when the required API key is not present in the settings."""


class FullTextUnpackError(Exception):
    """Raise when we fail to unpack a full text."""


class FullTextNotFoundError(Exception):
    """Raise when we fail to find a full text."""


class ExternalAPI(StrEnum):
    """
    Exhaustive list of permitted external APIs which we can hit to retrieve full texts.

    New additions here will require definition of
    new pydantic models for parsing their output and new
    implementation of retrieving their output.
    """

    OPENALEX = "openalex"
    SCOPUS = "scopus"


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


external_api_priority_batch = ExternalAPIPriority(
    name="batch",
    priorities={
        ExternalAPI.OPENALEX: 1,
        ExternalAPI.SCOPUS: 2,
    },
)


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
    pdf_link_strategy: list[str] | list[list] | None = Field(
        default=None,
        description="""A list of keys to sequentially
        pass to the json response object to retrieve
        PDF link. Optional.""",
    )
    xml_strategy: list[str] | list[list] | None = Field(
        default=None,
        description="""A list of keys to sequentially
        pass to the json response object to retrieve
        XML representation. Optional.""",
    )


class APIConfig(BaseModel):
    """
    Essential config required to use an external API to get
    full texts and make them available to a destiny Work.
    """

    name: ExternalAPI = Field(
        description="Name (we've given) to this external API service"
    )
    url: AnyUrl = Field(description="URL/endpoint for the given API")
    require_api_key: bool = Field(description="Is API key required to hit this API.")
    api_key_env_var_name: str | None = Field(
        description="Name of the environment variable/settings field "
        "which represents an api key for this api."
    )
    api_key_placement: str | None = Field(
        description="Dict key in `headers` where we should insert our API key."
    )
    query_type: QueryType = Field(
        default=QueryType.BATCHED_SINGLE,
        description="Type of query; i.e. batched_single or batch.",
    )
    query_params: dict = Field(
        default={},
        description="Query params to pass with the api call.",
    )
    headers: dict = Field(
        default={"Accept": "application/json"},
        description="Headers (or set of headers) to pass with the request.",
    )

    @model_validator(mode="before")
    @classmethod
    def api_key_placement_in_headers(cls, values: dict) -> dict:
        """Ensure `api_key_placement` is a key in the headers dict."""
        if values["require_api_key"] and (
            values["headers"] is not None
            and values["api_key_placement"] not in values["headers"]
        ):
            error_msg = f"api_key_placement '{values['api_key_placement']}'"
            "must be in the values dict"
            raise ValueError(error_msg)
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
                error_msg = f"API key for {self.name} is not present in settings."
                raise APIKeyNotPresentError(error_msg)
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
            error_msg = (
                "array of items to query for is too long. max"
                f"n(items): {max_array_length}"
            )
            raise ValueError(error_msg)
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
                error_msg = "query_type `batch` requires a `list` type query."
                raise TypeError(error_msg)
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
                error_msg = (
                    "query_type `batched_single` requires a `str` type query, "
                    "or a single-item list."
                )
                raise TypeError(error_msg)
            extracted_query = query[0] if isinstance(query, list) else query
            if not isinstance(extracted_query, str):
                error_msg = f"Unable to parse query from initial query {query}."
                raise TypeError(error_msg)
            url = self.build_query_single(
                doi=extracted_query, url=self.url.encoded_string()
            )
            return {
                "url": url,
                "query_params": self.query_params,
                "headers": self.headers,
            }

        error_msg = (
            "Unable to format query. Ensure correct specification ",
            "of query and query type.",
        )
        raise ValueError(error_msg)
