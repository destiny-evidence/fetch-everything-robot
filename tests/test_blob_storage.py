"""
Test blob storage interaction.

The base class and get_blob_service_client are tested upstream.
This only tests the exception mapping and return value that this subclass owns.
"""

from io import BytesIO

import pytest
from azure.core.exceptions import (
    AzureError,
    ClientAuthenticationError,
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
    ServiceRequestError,
)
from pytest_mock import MockerFixture
from refresh_requester.blob_storage import BlobUploadError

from fer.blob_storage import FetchEverythingBlobStorageClient
from fer.config import Settings


def test_blob_upload_returns_filename(
    mocker: MockerFixture,
    test_settings: Settings,
):
    storage_client = FetchEverythingBlobStorageClient(test_settings)
    blob_client = mocker.MagicMock()
    blob_client.upload_blob.side_effect = None
    mocker.patch(
        "fer.blob_storage.get_blob_service_client",
        return_value=mocker.MagicMock(
            get_blob_client=mocker.MagicMock(return_value=blob_client)
        ),
    )
    result = storage_client.blob_upload(data=BytesIO(b"pdf bytes"), filename="test.pdf")
    assert result == "test.pdf"


@pytest.mark.parametrize(
    "azure_error",
    [
        ResourceExistsError(),
        ResourceNotFoundError(),
        ClientAuthenticationError(),
        HttpResponseError(),
        ServiceRequestError(message="timeout"),
        AzureError("generic"),
        ValueError("bad value"),
    ],
)
def test_blob_upload_wraps_azure_errors_as_blob_upload_error(
    mocker: MockerFixture, azure_error: Exception, test_settings: Settings
):
    storage_client = FetchEverythingBlobStorageClient(test_settings)
    blob_client = mocker.MagicMock()
    blob_client.upload_blob.side_effect = azure_error
    mocker.patch(
        "fer.blob_storage.get_blob_service_client",
        return_value=mocker.MagicMock(
            get_blob_client=mocker.MagicMock(return_value=blob_client)
        ),
    )
    with pytest.raises(BlobUploadError):
        storage_client.blob_upload(data=BytesIO(b"pdf bytes"), filename="test.pdf")
