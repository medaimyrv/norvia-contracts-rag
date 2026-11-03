"""Genera archivos para probar la aplicación a mano desde la web (no se versionan).

Uso: make manual-tests  ->  pruebas_manuales/ con los archivos y GUIA.md
"""

import shutil
import sys
from dataclasses import replace

from scripts.generate_samples import CONTRACTS, ROOT, build_contract

OUT = ROOT / "pruebas_manuales"
CONDOR_V2 = next(c for c in CONTRACTS if c.contract_code == "CA-2025" and c.version == 2)


def main() -> None:
    OUT.mkdir(exist_ok=True)

    # Transportista nuevo: aparece en el desplegable y se puede preguntar por él
    sierra = replace(
        CONDOR_V2,
        file="sierra_nevada_v1.pdf",
        carrier="Transportes Sierra Nevada",
        contract_code="SN-2026",
        version=1,
        effective_from="2026-02-01",
        damage_claim="ocho (8) días naturales",
        insurance="750.000 EUR por siniestro",
        payment_days=50,
    )
    # Versión 3 de Cóndor ya en vigor: pasa a vigente y la v2 a histórica
    condor_v3 = replace(
        CONDOR_V2,
        file="condor_andino_v3.pdf",
        version=3,
        effective_from="2026-10-01",
        damage_claim="doce (12) días naturales",
    )
    # Versión 4 con fecha futura: se procesa pero NO pasa a vigente
    condor_v4 = replace(
        CONDOR_V2,
        file="condor_andino_v4_futura.pdf",
        version=4,
        effective_from="2027-06-01",
        damage_claim="quince (15) días naturales",
    )
    # Archivo distinto que reclama ser la v2 de Cóndor (ya existe): conflicto 409
    conflicto = replace(
        CONDOR_V2, file="conflicto_version.pdf", damage_claim="nueve (9) días naturales"
    )

    for contract in (sierra, condor_v3, condor_v4, conflicto):
        (OUT / contract.file).write_bytes(build_contract(contract))

    samples = ROOT / "samples"
    shutil.copy(samples / "condor_andino_v1.pdf", OUT / "duplicado_condor_v1.pdf")
    shutil.copy(samples / "corrupt.pdf", OUT / "corrupto.pdf")
    shutil.copy(samples / "scanned.pdf", OUT / "escaneado.pdf")
    shutil.copy(samples / "injection_test.pdf", OUT / "inyeccion.pdf")
    (OUT / "no_es_pdf.pdf").write_text("Esto es texto plano con extensión .pdf\n")
    (OUT / "vacio.pdf").write_bytes(b"")
    # Cabecera de PDF válida pero 21 MB: lo rechaza el límite de tamaño, no el tipo
    (OUT / "demasiado_grande.pdf").write_bytes(b"%PDF-1.7\n" + b"0" * (21 * 1024 * 1024))
    print(f"Archivos generados en {OUT}")


if __name__ == "__main__":
    sys.exit(main())
