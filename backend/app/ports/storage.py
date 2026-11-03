from typing import Protocol


class FileStorage(Protocol):
    """Dónde vive el PDF entre la subida y la ingesta. Local: volumen compartido; prod: S3."""

    def save(self, sha256: str, data: bytes) -> None: ...

    def read(self, sha256: str) -> bytes:
        """Raises: FileMissingError si no existe."""
        ...
