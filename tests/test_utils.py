"""tests for functions in fer/utils.py."""

import pytest

from fer.utils import (
    InvalidDOIError,
    VersionInfoNotFoundError,
    format_doi,
    get_version_number,
    validate_doi,
)


class DummyIdentifier:
    """A dummy identifier class to simulate an Identifier object with a DOI."""

    def __init__(self, identifier: str, identifier_type: str = "doi") -> None:
        """
        Initialize the DummyIdentifier with an identifier and type.

        Args:
            identifier (str): The identifier string, typically a DOI.
            identifier_type (str, optional): The type of identifier, default is "doi".

        """
        self.identifier = identifier
        self.identifier_type = identifier_type


class DummyReference:
    """A dummy reference class to simulate a Reference object with identifiers."""

    def __init__(self, identifiers) -> None:
        """
        Initialize the DummyReference with a list of identifiers.

        Args:
            identifiers (_type_): A list of DummyIdentifier objects.

        """
        self.identifiers = identifiers


@pytest.mark.parametrize(
    "test_full_url_doi",
    [
        "https://doi.org/10.1000/xyz123",
        "http://doi.org/10.1000/xyz123",
        "10.1000/xyz123",
        "10.1000/xyz123/abc",
    ],
)
def test_get_valid_doi_from_full_url_success(test_full_url_doi):
    """Test that we can extract a DOI from a full URL."""
    assert validate_doi(
        test_full_url_doi
    ), "Expect this list of valid DOIs to be valid."


@pytest.mark.parametrize(
    "test_full_url_doi",
    [
        "https://doi.org/foo",
        "http://doi.org/bar",
        "baz/123",
    ],
)
def test_get_invalid_doi_from_full_url_fails_properly(test_full_url_doi):
    """Test that we can extract a DOI from a full URL."""
    with pytest.raises(InvalidDOIError) as expected_error:
        validate_doi(test_full_url_doi)
    assert f"Invalid DOI: {test_full_url_doi}" in str(expected_error.value)


@pytest.mark.parametrize("non_string", [12345, None, ["10.1000/xyz123"]])
def test_validate_doi_false_for_non_string(non_string):
    with pytest.raises(InvalidDOIError) as expected_error:
        validate_doi(non_string)
    assert f"Invalid DOI {non_string}" in str(expected_error.value)


@pytest.mark.parametrize(
    "invalid_doi_string", ["bad_doi", "foo", "10.000/bar", "10./xyz", "10.1000/"]
)
def test_validate_doi_false_for_invalid_string(invalid_doi_string):
    with pytest.raises(InvalidDOIError) as expected_error:
        validate_doi(invalid_doi_string)
    assert f"Invalid DOI: {invalid_doi_string}" in str(expected_error.value)


def test_validate_doi_success():
    assert validate_doi("10.1177/02633957231191445")


def test_get_version_number_success(mocker):
    mocker.patch("fer.utils.version", return_value="1.2.3")
    version = get_version_number("fetch-everything-robot")
    assert version == "1.2.3"


def test_get_version_number_version_not_found():
    with pytest.raises(VersionInfoNotFoundError):
        get_version_number("nonexistent-package")


@pytest.mark.parametrize(
    ("candidate_doi_string", "expected_output"),
    [
        ("https://doi.org/10.1000/xyz123", "10.1000/xyz123"),
        ("http://doi.org/10.1000/xyz123", "10.1000/xyz123"),
        ("doi:10.1000/xyz123", "10.1000/xyz123"),
        ("10.1000/xyz123", "10.1000/xyz123"),
        ("10.1000/xyz123doiformat", "10.1000/xyz123doiformat"),
    ],
)
def test_format_doi_success(candidate_doi_string, expected_output):
    assert format_doi(candidate_doi_string) == expected_output
