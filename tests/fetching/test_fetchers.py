import pytest

from app.fetching import BasePublisherFetcher
from app.fetching.fetchers import FullTextFetcher, FullTextFetcherError


def test_full_text_fetcher_init(mocker):
    settings = mocker.MagicMock()
    test_timeout = 200
    fetcher = FullTextFetcher(settings, timeout=test_timeout)

    assert fetcher.settings == settings
    assert fetcher.timeout == test_timeout
    assert isinstance(fetcher.fetchers, dict)
    assert all(
        issubclass(type(f), BasePublisherFetcher) for f in fetcher.fetchers.values()
    ), "All fetchers should be instances of BasePublisherFetcher"


def test_format_identifiers_for_uri():
    input_identifier = "10.1000/xyz123"
    expected_output = "10.1000%2Fxyz123"
    formatted_identifier = FullTextFetcher.format_identifiers_for_uri(input_identifier)
    assert (
        formatted_identifier == expected_output
    ), "Identifier should be formatted correctly"


@pytest.mark.asyncio
async def test_fetch_calls_correct_fetcher(mocker):
    settings = mocker.MagicMock()
    fetcher_instance = FullTextFetcher(settings)

    mock_study_collection = mocker.MagicMock()
    mock_output_directory = mocker.MagicMock()
    publisher_name = "test_publisher"

    mock_publisher_fetcher = mocker.MagicMock(spec=BasePublisherFetcher)
    fetcher_instance.fetchers[publisher_name] = mock_publisher_fetcher

    await fetcher_instance.fetch(
        publisher_name,
        mock_study_collection,
        mock_output_directory,
    )

    mock_publisher_fetcher.fetch_full_text.assert_awaited_once_with(
        mock_study_collection,
        mock_output_directory,
    )


@pytest.mark.asyncio
async def test_fetch_raises_error_for_unknown_publisher(mocker):
    settings = mocker.MagicMock()
    fetcher_instance = FullTextFetcher(settings)

    mock_study_collection = mocker.MagicMock()
    mock_output_directory = mocker.MagicMock()
    unknown_publisher_name = "unknown_publisher"

    with pytest.raises(FullTextFetcherError) as error_info:
        await fetcher_instance.fetch(
            unknown_publisher_name,
            mock_study_collection,
            mock_output_directory,
        )

    assert str(error_info.value) == f"Unknown publisher: {unknown_publisher_name}"
