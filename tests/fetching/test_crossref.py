import pytest
from habanero import RequestError

from app.fetching.crossref import CrossrefFetcher


def test_crossref_get_content_type_success(test_settings):
    fetcher = CrossrefFetcher(settings=test_settings)
    test_pdf_url = "http://example.com/article.pdf"
    test_html_url = "http://example.com/article.html"
    pdf_content_type = "application/pdf"
    html_content_type = "text/html"
    test_crossref_output = {
        "message": {
            "link": [
                {
                    "URL": test_pdf_url,
                    "content-type": pdf_content_type,
                },
                {
                    "URL": test_html_url,
                    "content-type": html_content_type,
                },
            ]
        }
    }

    content_info = fetcher.get_url_from_pdf_content_type(test_crossref_output)

    assert content_info["content_type"] == pdf_content_type
    assert content_info["url"] == test_pdf_url


def test_crossref_get_content_type_unique_url_but_not_pdf(test_settings):
    fetcher = CrossrefFetcher(settings=test_settings)
    test_html_url = "http://example.com/article.html"
    html_content_type = "text/html"
    test_crossref_output = {
        "message": {
            "link": [
                {
                    "URL": test_html_url,
                    "content-type": html_content_type,
                },
            ]
        }
    }

    content_info = fetcher.get_url_from_pdf_content_type(test_crossref_output)

    assert content_info["content_type"] == html_content_type
    assert content_info["url"] == test_html_url


def test_crossref_get_content_type_no_urls_found(test_settings):
    fetcher = CrossrefFetcher(settings=test_settings)
    test_crossref_output = {"message": {"link": []}}

    content_info = fetcher.get_url_from_pdf_content_type(test_crossref_output)

    assert content_info["content_type"] is None
    assert content_info["url"] is None


def test_pdf_url_is_valid_success(test_settings):
    fetcher = CrossrefFetcher(settings=test_settings)
    content_info = {
        "content_type": "application/pdf",
        "url": "http://example.com/article.pdf",
    }

    assert fetcher.pdf_url_is_valid(content_info) is True


def test_pdf_url_is_valid_invalid_content_type(test_settings):
    fetcher = CrossrefFetcher(settings=test_settings)
    content_info = {
        "content_type": "text/html",
        "url": "http://example.com/article.html",
    }

    assert fetcher.pdf_url_is_valid(content_info) is False


@pytest.mark.parametrize(
    ("content_type", "publisher"),
    [
        ("application/pdf", "wiley"),
        ("application/pdf", "elsevier"),
        ("application/pdf", "tandfonline"),
    ],
)
def test_pdf_url_is_valid_invalid_publisher_keyword(
    test_settings, content_type, publisher
):
    fetcher = CrossrefFetcher(settings=test_settings)
    content_info = {
        "content_type": content_type,
        "url": f"http://{publisher}.com/article.pdf",
    }

    assert fetcher.pdf_url_is_valid(content_info) is False


@pytest.mark.asyncio
async def test_fetch_full_text_no_valid_pdfs(
    mocker, test_settings, test_study_collection, tmp_path
):
    fetcher = CrossrefFetcher(settings=test_settings)
    patched_crossref_works = mocker.patch("app.fetching.crossref.Crossref.works")
    patched_url_get_call = mocker.patch.object(
        fetcher,
        "get_url_from_pdf_content_type",
        return_value={
            "content_type": "text/html",
            "url": "http://example.com/article.html",
        },
    )
    patched_pdf_url_is_valid = mocker.patch.object(
        fetcher, "pdf_url_is_valid", return_value=False
    )
    patched_stream_file = mocker.patch(
        "app.fetching.crossref.stream_file", return_value=None
    )
    await fetcher.fetch_full_text(
        study_collection=test_study_collection, output_directory=tmp_path
    )

    assert patched_crossref_works.call_count == len(test_study_collection.studies)
    assert patched_url_get_call.call_count == len(test_study_collection.studies)
    assert patched_pdf_url_is_valid.call_count == len(test_study_collection.studies)
    patched_stream_file.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_full_text_with_valid_pdf(
    mocker, test_settings, test_study_collection, tmp_path
):
    fetcher = CrossrefFetcher(settings=test_settings)
    mocker.patch("asyncio.sleep")
    patched_crossref_works = mocker.patch("app.fetching.crossref.Crossref.works")
    patched_url_get_call = mocker.patch.object(
        fetcher,
        "get_url_from_pdf_content_type",
        return_value={
            "content_type": "application/pdf",
            "url": "http://example.com/article.pdf",
        },
    )
    patched_pdf_url_is_valid = mocker.patch.object(
        fetcher, "pdf_url_is_valid", return_value=True
    )
    patched_stream_file = mocker.patch(
        "app.fetching.crossref.stream_file", return_value=tmp_path / "dummy.pdf"
    )
    await fetcher.fetch_full_text(
        study_collection=test_study_collection, output_directory=tmp_path
    )

    assert patched_crossref_works.call_count == len(test_study_collection.studies)
    assert patched_url_get_call.call_count == len(test_study_collection.studies)
    assert patched_pdf_url_is_valid.call_count == len(test_study_collection.studies)
    assert patched_stream_file.call_count == len(test_study_collection.studies)


@pytest.mark.asyncio
async def test_fetch_full_text_fails_request_error(
    mocker, test_settings, test_study_collection, tmp_path, caplog
):
    uids = [str(study.uid) for study in test_study_collection.studies]
    dois = [study.doi.identifier for study in test_study_collection.studies]
    fetcher = CrossrefFetcher(settings=test_settings)
    mocker.patch("asyncio.sleep")
    patched_crossref_works = mocker.patch(
        "app.fetching.crossref.Crossref.works",
        side_effect=RequestError(404, "Not Found"),
    )
    patched_url_get_call = mocker.patch.object(
        fetcher,
        "get_url_from_pdf_content_type",
    )
    patched_pdf_url_is_valid = mocker.patch.object(fetcher, "pdf_url_is_valid")
    patched_stream_file = mocker.patch(
        "app.fetching.crossref.stream_file",
    )
    with caplog.at_level("ERROR"):
        await fetcher.fetch_full_text(
            study_collection=test_study_collection, output_directory=tmp_path
        )
    assert "CrossRef request error" in caplog.text
    assert all(uid in caplog.text for uid in uids)
    assert all(doi in caplog.text for doi in dois)
    assert patched_crossref_works.call_count == len(test_study_collection.studies)
    patched_url_get_call.assert_not_called()
    patched_pdf_url_is_valid.assert_not_called()
    patched_stream_file.assert_not_called()
