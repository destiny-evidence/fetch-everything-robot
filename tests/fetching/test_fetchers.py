import pytest

from fer.fetching import BasePublisherFetcher
from fer.fetching.fetchers import FullTextFetcher, FullTextFetcherError
from fer.fetching.openalex import OpenalexFetcher


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
async def test_fetch_calls_correct_fetcher_doi_study_collection(
    mocker, tmp_path, test_publisher_dict, test_study_collection
):
    settings = mocker.MagicMock()
    fetcher_instance = FullTextFetcher(settings, publisher_dict=test_publisher_dict)

    publisher_name = "test_publisher"

    mock_publisher_fetcher = mocker.MagicMock(spec=BasePublisherFetcher)
    fetcher_instance.fetchers[publisher_name] = mock_publisher_fetcher

    await fetcher_instance.fetch(
        publisher_name,
        test_study_collection,
        tmp_path,
    )

    mock_publisher_fetcher.fetch_many_full_texts.assert_awaited_once_with(
        test_study_collection,
        tmp_path,
    )


@pytest.mark.asyncio
async def test_fetch_calls_correct_fetcher_openalex_study_collection(
    mocker, tmp_path, test_publisher_dict, test_openalex_study_collection
):
    settings = mocker.MagicMock()
    fetcher_instance = FullTextFetcher(settings, publisher_dict=test_publisher_dict)

    publisher_name = "openalex"
    mock_openalex_fetcher = mocker.MagicMock(spec=OpenalexFetcher)
    fetcher_instance.fetchers[publisher_name] = mock_openalex_fetcher

    await fetcher_instance.fetch(
        publisher_name,
        test_openalex_study_collection,
        tmp_path,
    )

    mock_openalex_fetcher.fetch_many_full_texts.assert_awaited_once_with(
        test_openalex_study_collection,
        tmp_path,
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
