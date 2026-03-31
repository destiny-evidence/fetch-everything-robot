import json

import pytest


@pytest.fixture
def openalex_work_dict() -> dict:
    """
    Define a representative OpenAlex work response as a dictionary.

    Returns:
        dict: OpenAlex work response as dictionary.

    """
    return {
        "id": "https://openalex.org/W1234567890",
        "doi": "https://doi.org/10.1234/example-doi",
        "title": "Test title",
        "display_name": "Test display name",
        "publication_year": 2025,
        "publication_date": "2025-01-01",
        "ids": {
            "openalex": "https://openalex.org/W1234567890",
            "doi": "https://doi.org/10.1234/example-doi",
        },
        "language": "en",
        "primary_location": {
            "is_oa": False,
            "landing_page_url": "https://doi.org/10.1234/example-doi",
            "pdf_url": None,
            "source": {
                "id": "https://openalex.org/example-source-id",
                "display_name": "Test source",
                "issn_l": "1234-5678",
                "issn": ["1234-5678"],
                "is_oa": False,
                "is_in_doaj": False,
                "is_indexed_in_scopus": True,
                "is_core": True,
                "host_organization": "https://openalex.org/example-host-organization-id",
                "host_organization_name": "Test host organization",
                "host_organization_lineage": [
                    "https://openalex.org/example-host-organization-id"
                ],
                "host_organization_lineage_names": ["Test host organization"],
                "type": "journal",
            },
            "license": None,
            "license_id": None,
            "version": None,
            "is_accepted": False,
            "is_published": False,
        },
        "type": "article",
        "type_crossref": "journal-article",
        "indexed_in": ["crossref"],
        "open_access": {
            "is_oa": False,
            "oa_status": "closed",
            "oa_url": None,
            "any_repository_has_fulltext": False,
        },
        "authorships": [
            {
                "author_position": "first",
                "author": {
                    "id": "https://openalex.org/example-first-author-id",
                    "display_name": "First Author",
                    "orcid": "https://orcid.org/example-orcid-first-author",
                },
                "institutions": [],
                "countries": [],
                "is_corresponding": False,
                "raw_author_name": "First Author",
                "raw_affiliation_strings": [],
                "affiliations": [],
            },
            {
                "author_position": "last",
                "author": {
                    "id": "https://openalex.org/example-last-author-id",
                    "display_name": "Last Author",
                    "orcid": "https://orcid.org/example-orcid-last-author",
                },
                "institutions": [],
                "countries": [],
                "is_corresponding": False,
                "raw_author_name": "Last Author",
                "raw_affiliation_strings": [],
                "affiliations": [],
            },
        ],
        "institution_assertions": [],
        "countries_distinct_count": 0,
        "institutions_distinct_count": 0,
        "corresponding_author_ids": [],
        "corresponding_institution_ids": [],
        "apc_list": None,
        "apc_paid": None,
        "fwci": None,
        "has_fulltext": False,
        "cited_by_count": 0,
        "citation_normalized_percentile": None,
        "cited_by_percentile_year": {"min": 0, "max": 97},
        "biblio": {
            "volume": "999",
            "issue": "01/2025",
            "first_page": "1",
            "last_page": "999",
        },
        "is_retracted": False,
        "is_paratext": False,
        "is_xpac": False,
        "primary_topic": {
            "id": "https://openalex.org/example-primary-topic-id",
            "display_name": "Example Primary Topic",
            "score": 0.7635,
            "subfield": {
                "id": "https://openalex.org/subfields/example-subfield-id",
                "display_name": "Test subfield",
            },
            "field": {
                "id": "https://openalex.org/fields/example-field-id",
                "display_name": "Example Field",
            },
            "domain": {
                "id": "https://openalex.org/domains/example-domain-id",
                "display_name": "Example domain",
            },
        },
        "topics": [
            {
                "id": "https://openalex.org/first-topic",
                "display_name": "First topic",
                "score": 0.7635,
                "subfield": {
                    "id": "https://openalex.org/subfields/first-subfield",
                    "display_name": "First subfield",
                },
                "field": {
                    "id": "https://openalex.org/fields/first-field",
                    "display_name": "First field",
                },
                "domain": {
                    "id": "https://openalex.org/domains/first-domain",
                    "display_name": "First domain",
                },
            }
        ],
        "keywords": [
            {
                "id": "https://openalex.org/keywords/example-keyword-id",
                "display_name": "Example keyword",
                "score": 0.9999,
            }
        ],
        "concepts": [
            {
                "id": "https://openalex.org/example-first-concept-id",
                "wikidata": "https://www.wikidata.org/wiki/example-first-concept",
                "display_name": "First concept",
                "level": 2,
                "score": 0.78613544,
            },
            {
                "id": "https://openalex.org/example-second-concept-id",
                "wikidata": "https://www.wikidata.org/wiki/example-second-concept",
                "display_name": "Second concept",
                "level": 3,
                "score": 0.6263777,
            },
        ],
        "mesh": [],
        "locations_count": 1,
        "locations": [
            {
                "is_oa": False,
                "landing_page_url": "https://doi.org/10.1234/example-doi",
                "pdf_url": None,
                "source": {
                    "id": "https://openalex.org/example-location-id",
                    "display_name": "Example Location",
                    "issn_l": "1234-5678",
                    "issn": ["1234-5678"],
                    "is_oa": False,
                    "is_in_doaj": False,
                    "is_indexed_in_scopus": True,
                    "is_core": True,
                    "host_organization": "https://openalex.org/example-host-organization-id",
                    "host_organization_name": "Example Host Organization",
                    "host_organization_lineage": [
                        "https://openalex.org/example-host-organization-lineage-id"
                    ],
                    "host_organization_lineage_names": [
                        "Example Host Organization Lineage Name"
                    ],
                    "type": "journal",
                },
                "license": None,
                "license_id": None,
                "version": None,
                "is_accepted": False,
                "is_published": False,
            }
        ],
        "best_oa_location": None,
        "sustainable_development_goals": [
            {
                "display_name": "Zero hunger",
                "score": 0.99,
                "id": "https://metadata.un.org/sdg/example-sdg-id",
            }
        ],
        "grants": [],
        "datasets": [],
        "versions": [],
        "referenced_works_count": 2,
        "referenced_works": [
            "https://openalex.org/W111111111",
            "https://openalex.org/W222222222",
        ],
        "related_works": [
            "https://openalex.org/W123456789",
            "https://openalex.org/W987654321",
        ],
        "abstract_inverted_index": {
            "This": [0],
            "is": [1],
            "an": [2],
            "example": [3],
            "abstract": [4],
        },
        "abstract_inverted_index_v3": None,
        "cited_by_api_url": "https://api.openalex.org/works?filter=cites:W1234567890",
        "counts_by_year": [],
        "updated_date": "2025-01-02T01:00:00.00",
        "created_date": "2025-01-01",
    }


@pytest.fixture
def openalex_work_json(openalex_work_dict) -> str:
    """
    Return a jsonified version of the openalex_work_dict fixture.

    Args:
        openalex_work_dict (_type_): An OpenAlex work response as a dictionary.

    Returns:
        str: A JSON string representing the OpenAlex work response.

    """
    return json.dumps(openalex_work_dict)
