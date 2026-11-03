"""Carga inicial: sube por la API los PDFs de samples/ marcados seed=true [R14].

Uso: python -m scripts.seed --api http://api:8000 --samples /samples
Idempotente: una segunda ejecución recibe 200 (duplicado) en vez de 202.
Solo librería estándar: se ejecuta dentro de la imagen de producción.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def multipart(fields: dict[str, str], filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields.items()
    ]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/pdf\r\n\r\n".encode()
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def upload(api: str, item: dict[str, object], samples: Path) -> int:
    fields = {k: str(item[k]) for k in ("carrier", "contract_code", "version", "effective_from")}
    pdf = (samples / str(item["file"])).read_bytes()
    body, content_type = multipart(fields, str(item["file"]), pdf)
    request = urllib.request.Request(  # noqa: S310 (URL interna fijada por el operador)
        f"{api}/api/documents", data=body, headers={"Content-Type": content_type}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--samples", type=Path, default=Path("samples"))
    args = parser.parse_args()

    manifest = json.loads((args.samples / "manifest.json").read_text(encoding="utf-8"))
    try:
        for item in (i for i in manifest if i["seed"]):
            status = upload(args.api, item, args.samples)
            label = {202: "registrado", 200: "ya existía", 409: "conflicto"}.get(status, "error")
            print(f"{status} {label:<11} {item['file']}")
    except urllib.error.URLError as exc:
        print(f"API no disponible: {exc.reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
