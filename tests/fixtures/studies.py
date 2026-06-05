from uuid import uuid4

import pytest
from destiny_sdk.identifiers import (
    DOIIdentifier,
    ExternalIdentifierType,
    OpenAlexIdentifier,
)

from fer.fetching.core import (
    DOIStudy,
    DOIStudyCollection,
    OpenAlexStudy,
    OpenAlexStudyCollection,
)


@pytest.fixture
def test_study_collection() -> DOIStudyCollection:
    """Create a test DOIStudyCollection with sample studies."""
    studies = [
        DOIStudy(
            uid=uuid4(),
            doi=DOIIdentifier(
                identifier="10.1000/xyz123", identifier_type=ExternalIdentifierType.DOI
            ),
        ),
        DOIStudy(
            uid=uuid4(),
            doi=DOIIdentifier(
                identifier="10.1000/abc456", identifier_type=ExternalIdentifierType.DOI
            ),
        ),
    ]
    return DOIStudyCollection(studies=studies)


@pytest.fixture
def test_openalex_study_collection() -> OpenAlexStudyCollection:
    """Create a test OpenAlexStudyCollection with sample studies."""
    studies = [
        OpenAlexStudy(
            uid=uuid4(),
            openalex_id=OpenAlexIdentifier(identifier="W1234567890"),
            doi=DOIIdentifier(
                identifier="10.1000/xyz123", identifier_type=ExternalIdentifierType.DOI
            ),
        ),
        OpenAlexStudy(
            uid=uuid4(),
            openalex_id=OpenAlexIdentifier(identifier="W0987654321"),
            doi=DOIIdentifier(
                identifier="10.1000/abc456", identifier_type=ExternalIdentifierType.DOI
            ),
        ),
    ]
    return OpenAlexStudyCollection(studies=studies)
