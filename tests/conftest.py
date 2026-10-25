"""Shared test setup.

Tests must never reach a real model provider or depend on the developer's shell, so every
postloom and provider variable is removed before any test runs. Tests that need one set
it with ``monkeypatch.setenv``, which is undone afterwards.
"""

import os

from postloom.adapters.llm.providers import PROVIDERS

ISOLATED = {name for spec in PROVIDERS.values() for name in spec.key_envs}


def isolate_environment() -> None:
    for name in list(os.environ):
        if name.startswith("POSTLOOM_") or name in ISOLATED:
            del os.environ[name]


isolate_environment()
