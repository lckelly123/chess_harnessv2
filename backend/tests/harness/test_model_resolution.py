import asyncio

import pytest

import harness.model as model_module
from harness.model import ModelResolutionError, resolve_lmstudio_model


def test_explicit_model_wins_without_discovery(monkeypatch) -> None:
    async def unexpected_discovery():
        raise AssertionError("discovery should not run")

    monkeypatch.setattr(model_module, "loaded_lmstudio_models", unexpected_discovery)
    assert asyncio.run(resolve_lmstudio_model("loaded/model")) == "loaded/model"


def test_discovers_exactly_one_loaded_model(monkeypatch) -> None:
    async def one_model():
        return ("loaded/model",)

    monkeypatch.setattr(model_module, "loaded_lmstudio_models", one_model)
    monkeypatch.delenv("LMSTUDIO_MODEL", raising=False)
    assert asyncio.run(resolve_lmstudio_model()) == "loaded/model"


@pytest.mark.parametrize("models", [(), ("one", "two")])
def test_rejects_missing_or_ambiguous_loaded_models(monkeypatch, models) -> None:
    async def discovered():
        return models

    monkeypatch.setattr(model_module, "loaded_lmstudio_models", discovered)
    monkeypatch.delenv("LMSTUDIO_MODEL", raising=False)
    with pytest.raises(ModelResolutionError):
        asyncio.run(resolve_lmstudio_model())
