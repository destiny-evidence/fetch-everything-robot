"""Misc/Utility functions for our fetch everything robot."""

import re
from importlib.metadata import PackageNotFoundError, version

from destiny_sdk.identifiers import DOIIdentifier, ExternalIdentifierType
from destiny_sdk.references import Reference
from loguru import logger
from pydantic import ValidationError


class VersionInfoNotFoundError(Exception):
    """Custom exception to throw when version info is not found."""


class InvalidDOIError(Exception):
    """Custom exception to throw when DOI is invalid."""


class MissingDOIError(Exception):
    """Exception for when a reference doesn't contain a DOI."""


def format_doi(doi_candidate: str) -> str:
    """
    Format a DOI candidate string by removing common prefixes and URL encodings.

    This is additional DOI formatting taken from the previous work by Kaitlyn.

    Args:
        doi_candidate (str): The DOI candidate string to format.

    Returns:
        str: The formatted DOI string.

    """
    doi_candidate = doi_candidate.lower()
    replacements = [
        (r"%28", "("),
        (r"%29", ")"),
        (r"http://dx.doi.org/", ""),
        (r"https://doi.org/", ""),
        (r"https://dx.doi.org/", ""),
        (r"http://doi.org/", ""),
        (r"doi:\s*", ""),
        (r"^doi", ""),
    ]
    for pattern, replacement in replacements:
        doi_candidate = re.sub(pattern, replacement, doi_candidate)
    return doi_candidate


def validate_doi(doi_string: str) -> str:
    """
    Validate a DOI string against the DESTINY DOI Identifier model
    and return the cleaned, validated DOI string.

    Args:
        doi_string (str): The DOI string to validate.

    Returns:
        str: The validated DOI string.

    """
    if not isinstance(doi_string, str):
        error_message = f"Invalid DOI {doi_string}. DOI must be a string."
        logger.error(error_message)
        raise InvalidDOIError(error_message)
    try:
        return DOIIdentifier(
            identifier=doi_string, identifier_type=ExternalIdentifierType.DOI
        ).remove_doi_url(doi_string)
    except ValidationError as invalid_doi_error:
        error_message = f"Invalid DOI: {doi_string}. Error: {invalid_doi_error}"
        logger.error(error_message)
        raise InvalidDOIError(error_message) from invalid_doi_error


def get_doi_from_reference(reference: Reference) -> str:
    """
    Extract DOI from a Reference object.

    Args:
        reference (Reference): The reference object containing identifiers.

    Returns:
        str: The DOI string if found.

    """
    for _id in reference.identifiers:
        if _id.identifier_type == ExternalIdentifierType.DOI:
            return _id.identifier
    error_message = f"No DOI found for reference {reference}"
    raise MissingDOIError(error_message)


def get_version_number(package_name: str = "fetch-everything-robot") -> str:
    """
    Retrieve the version number of an installed package.

    Args:
        package_name (str): The name of the package to retrieve the version for.

    Returns:
        str: The version string.

    Raises:
        PackageNotFoundError: If the package is not found.

    """
    try:
        return version(package_name)
    except PackageNotFoundError as package_error:
        error_message = f"Package not found: {package_name}"
        logger.error(error_message)
        raise VersionInfoNotFoundError(error_message) from package_error
