import pytest

from fer.fetching import BasePublisherFetcher
from fer.fetching.fetchers import FullTextFetcher, FullTextFetcherError


def test_full_text_fetcher_init(mocker, test_publisher_dict):
    settings = mocker.MagicMock()
    test_timeout = 200
    fetcher = FullTextFetcher(
        settings, publisher_dict=test_publisher_dict, timeout=test_timeout
    )

    assert fetcher.settings == settings
    assert fetcher.timeout == test_timeout
    assert isinstance(fetcher.fetchers, dict)
    assert all(
        isinstance(f, BasePublisherFetcher) for f in fetcher.fetchers.values()
    ), "All fetchers should be subclasses of BasePublisherFetcher"


@pytest.mark.asyncio
async def test_fetch_calls_correct_fetcher(mocker, test_publisher_dict):
    settings = mocker.MagicMock()
    fetcher_instance = FullTextFetcher(settings, publisher_dict=test_publisher_dict)

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

    mock_publisher_fetcher.fetch_many_full_texts.assert_awaited_once_with(
        mock_study_collection,
        mock_output_directory,
    )


@pytest.mark.asyncio
async def test_fetch_raises_error_for_unknown_publisher(mocker, test_publisher_dict):
    settings = mocker.MagicMock()
    fetcher_instance = FullTextFetcher(settings, publisher_dict=test_publisher_dict)

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
