import pytest

from fer.fetching.core import RetrievedFullText


@pytest.fixture
def test_fetch_two_results_full_error(test_references) -> list[RetrievedFullText]:
    return [
        RetrievedFullText(
            doi=str(test_references[0].identifiers[0].identifier),
            uid=test_references[0].id,
            fulltext_path=None,
            error="A test error occurred.",
        ),
        RetrievedFullText(
            doi=str(test_references[1].identifiers[0].identifier),
            uid=test_references[1].id,
            fulltext_path=None,
            error="A second test error occurred.",
        ),
    ]


@pytest.fixture
def test_fetch_two_results_success(
    test_references, tmp_path
) -> list[RetrievedFullText]:
    return [
        RetrievedFullText(
            doi=str(test_references[0].identifiers[0].identifier),
            uid=test_references[0].id,
            fulltext_path=tmp_path / "test1.pdf",
        ),
        RetrievedFullText(
            doi=str(test_references[1].identifiers[0].identifier),
            uid=test_references[1].id,
            fulltext_path=tmp_path / "test2.pdf",
        ),
    ]


@pytest.fixture
def test_fetch_results_single_success(
    test_references, tmp_path
) -> list[RetrievedFullText]:
    return [
        RetrievedFullText(
            doi=str(test_references[0].identifiers[0].identifier),
            uid=test_references[0].id,
            fulltext_path=tmp_path / "test1.pdf",
        )
    ]


@pytest.fixture
def test_fetch_results_single_failure(test_references) -> list[RetrievedFullText]:
    return [
        RetrievedFullText(
            doi=str(test_references[1].identifiers[0].identifier),
            uid=test_references[1].id,
            fulltext_path=None,
            error="A test error occurred.",
        )
    ]
