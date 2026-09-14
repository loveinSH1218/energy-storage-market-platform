"""Smoke tests for the initial package boundaries."""

import importlib


def test_platform_layers_are_importable() -> None:
    layers = (
        "core",
        "market",
        "strategy",
        "storage",
        "coupling",
        "experiments",
        "io",
    )

    for layer in layers:
        importlib.import_module(f"energy_storage_market_platform.{layer}")