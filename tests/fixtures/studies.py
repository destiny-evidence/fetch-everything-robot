import pytest
from destiny_sdk.identifiers import DOIIdentifier

from app.fetching.core import Study, StudyCollection


@pytest.fixture
def test_study_collection() -> StudyCollection:
    """Create a test StudyCollection with sample studies."""
    studies = [
        Study(
            uid="study1",
            doi=DOIIdentifier(identifier="10.1000/xyz123", identifier_type="doi"),
        ),
        Study(
            uid="study2",
            doi=DOIIdentifier(identifier="10.1000/abc456", identifier_type="doi"),
        ),
    ]
    return StudyCollection(studies=studies)
