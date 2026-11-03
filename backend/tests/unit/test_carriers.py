"""Resolución del transportista en la pregunta [D16]."""

import pytest

from app.domain.carriers import Match, resolve_carrier

KNOWN = [
    "Transportes Cóndor Andino",
    "Rápido Austral Logística",
    "Mareas del Pacífico Cargo",
    "Vientos del Sur Express",
]


@pytest.mark.parametrize(
    "question,carrier",
    [
        ("¿Plazo de reclamación con Transportes Cóndor Andino?", "Transportes Cóndor Andino"),
        ("¿plazo de reclamación con condor andino?", "Transportes Cóndor Andino"),  # distintivo
        ("Seguro de RÁPIDO AUSTRAL", "Rápido Austral Logística"),
        ("tarifas de vientos del sur", "Vientos del Sur Express"),
        ("¿seguro de Mareas Pacífico?", "Mareas del Pacífico Cargo"),  # sin «del»
        ("plazo de Condr Andno", "Transportes Cóndor Andino"),  # errata leve (0,92)
    ],
)
def test_exact_match_filters_automatically(question: str, carrier: str) -> None:
    assert resolve_carrier(question, KNOWN).match is Match.EXACT
    assert resolve_carrier(question, KNOWN).carriers == [carrier]


@pytest.mark.parametrize("question", ["¿Plazo con Candor Andina?", "¿Plazo de Cóndor?"])
def test_ambiguous_name_asks_did_you_mean(question: str) -> None:
    result = resolve_carrier(question, KNOWN)
    assert result.match is Match.SUGGESTION
    assert result.carriers[0] == "Transportes Cóndor Andino"


@pytest.mark.parametrize(
    "question",
    [
        "¿Qué transportistas aceptan mercancía refrigerada?",  # general
        "¿Plazo de reclamación con Transportes Pepe?",  # desconocido
        "¿Hay tarifas express para el sur?",  # palabras genéricas sueltas
        "¿Cuánto cuestan los envíos express?",  # «express» no basta para sugerir
        "Compara Cóndor Andino y Rápido Austral",  # comparativa: no se filtra
    ],
)
def test_no_filter_when_none_or_several(question: str) -> None:
    assert resolve_carrier(question, KNOWN).match is Match.NONE


def test_no_known_carriers() -> None:
    assert resolve_carrier("Cóndor Andino", []).match is Match.NONE
