from uuid import uuid4

import pytest
from destiny_sdk.identifiers import DOIIdentifier, ExternalIdentifierType

from fer.fetching.core import Study, StudyCollection


@pytest.fixture
def test_study_collection() -> StudyCollection:
    """Create a test StudyCollection with sample studies."""
    studies = [
        Study(
            uid=uuid4(),
            doi=DOIIdentifier(
                identifier="10.1000/xyz123", identifier_type=ExternalIdentifierType.DOI
            ),
        ),
        Study(
            uid=uuid4(),
            doi=DOIIdentifier(
                identifier="10.1000/abc456", identifier_type=ExternalIdentifierType.DOI
            ),
        ),
    ]
    return StudyCollection(studies=studies)
