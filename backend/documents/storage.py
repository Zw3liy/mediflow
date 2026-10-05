from pathlib import Path

from django.conf import settings


class DocumentStorageError(Exception):
    pass


class LocalDocumentStorage:
    def __init__(self, *, root=None):
        configured_root = root or getattr(
            settings,
            "DOCUMENT_STORAGE_ROOT",
            settings.BASE_DIR / "private_documents",
        )
        self.root = Path(configured_root).resolve()

    def _resolve_path(self, object_key):
        candidate = (self.root / object_key).resolve()

        if self.root not in candidate.parents:
            raise DocumentStorageError(
                "Invalid document storage key."
            )

        return candidate

    def save(self, *, object_key, content):
        path = self._resolve_path(object_key)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        try:
            path.write_bytes(content)
        except OSError as error:
            raise DocumentStorageError(
                "Document storage write failed."
            ) from error

    def delete(self, *, object_key):
        path = self._resolve_path(object_key)

        try:
            path.unlink(
                missing_ok=True,
            )
        except OSError as error:
            raise DocumentStorageError(
                "Document storage deletion failed."
            ) from error

    def read(self, *, object_key):
        path = self._resolve_path(object_key)

        try:
            return path.read_bytes()
        except OSError as error:
            raise DocumentStorageError(
                "Document storage read failed."
            ) from error


def get_document_storage():
    return LocalDocumentStorage()
