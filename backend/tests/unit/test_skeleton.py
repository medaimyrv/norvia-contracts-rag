"""Smoke test de T01: las capas de la arquitectura hexagonal [D0] son importables."""

import importlib

import pytest

LAYERS = ["domain", "ports", "adapters", "services", "api", "worker"]


@pytest.mark.parametrize("layer", LAYERS)
def test_layer_is_importable(layer: str) -> None:
    assert importlib.import_module(f"app.{layer}")
