"""Define utility functions to interact with Azure Blob Storage."""

from typing import TYPE_CHECKING, BinaryIO

from azure.core.exceptions import (
    AzureError,
)
from loguru import logger
from refresh_requester.blob_storage import (
    BlobUploadError,
    DestinyBlobStorageClient,
)

if TYPE_CHECKING:
    from azure.storage.blob import BlobClient


class FetchEverythingBlobStorageClient(DestinyBlobStorageClient):
    """A Blob storage client for the Fetch Everything Refresh Requester."""

    def blob_upload(self, data: BinaryIO, filename: str) -> str:
        """
        Upload data to blob storage.

        Args:
            data (BinaryIO): The data to be uploaded to blob storage.
            filename (str): The name of the file to be uploaded.

        Returns:
            str: The URL of the uploaded blob.

        """
        try:
            blob_client: BlobClient = self.blob_service_client.get_blob_client(
                container=self.settings.STORAGE_BLOB_CONTAINER, blob=filename
            )

            blob_client.upload_blob(data, overwrite=True)

            logger.info(f"Successfully uploaded {filename} to blob storage.")

        except (
            AzureError,
            ValueError,
        ) as storage_error:
            error_message = f"Error uploading refresh response: {storage_error}"
            logger.error(error_message)
            raise BlobUploadError(error_message) from storage_error
        return filename
