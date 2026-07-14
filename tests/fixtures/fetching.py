from io import BytesIO
from pathlib import Path

import pytest
import pytest_asyncio
from pypdf import PdfWriter

from fer.fetching.core import RetrievedFullText


async def fake_stream_file(url: str, destination: Path, **kwargs) -> Path:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    destination.write_bytes(buffer.getvalue())
    return destination


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


@pytest_asyncio.fixture
async def test_fetch_two_results_success(
    test_references, tmp_path
) -> list[RetrievedFullText]:
    test_pdf_paths = [
        tmp_path / "test1.pdf",
        tmp_path / "test2.pdf",
    ]
    for pdf_path in test_pdf_paths:
        await fake_stream_file(
            url="http://example.com/article.pdf",
            destination=pdf_path,
            pdf_content=b"PDF content",
        )

    return [
        RetrievedFullText(
            doi=str(test_references[0].identifiers[0].identifier),
            uid=test_references[0].id,
            fulltext_path=test_pdf_paths[0],
        ),
        RetrievedFullText(
            doi=str(test_references[1].identifiers[0].identifier),
            uid=test_references[1].id,
            fulltext_path=test_pdf_paths[1],
        ),
    ]


@pytest_asyncio.fixture
async def test_fetch_results_single_success(
    test_references, tmp_path
) -> list[RetrievedFullText]:
    pdf_path = tmp_path / "test1.pdf"
    await fake_stream_file(
        url="http://example.com/article.pdf",
        destination=pdf_path,
        pdf_content=b"PDF content",
    )
    return [
        RetrievedFullText(
            doi=str(test_references[0].identifiers[0].identifier),
            uid=test_references[0].id,
            fulltext_path=pdf_path,
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
