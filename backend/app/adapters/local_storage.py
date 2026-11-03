from pathlib import Path

from app.domain.errors import FileMissingError


class LocalFileStorage:
    """Volumen compartido entre API y worker. El nombre es el hash: nunca el del usuario."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def save(self, sha256: str, data: bytes) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._path(sha256).with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(self._path(sha256))  # rename atómico: el worker nunca lee un archivo a medias

    def read(self, sha256: str) -> bytes:
        try:
            return self._path(sha256).read_bytes()
        except FileNotFoundError as exc:
            raise FileMissingError(sha256) from exc

    def _path(self, sha256: str) -> Path:
        if len(sha256) != 64 or not all(c in "0123456789abcdef" for c in sha256):
            raise ValueError("sha256 inválido")  # evita rutas como ../../etc/passwd
        return self.root / f"{sha256}.pdf"
