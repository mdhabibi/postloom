# Contributing to postloom

Thanks for your interest! The project is pre-alpha; issues and ideas are very welcome, and
pull requests will be easier to accept once the MVP (milestone 1) lands.

## Setup

```bash
uv sync --group dev
uv run pre-commit install
```

## Before you push

```bash
uv run ruff check . && uv run ruff format .
uv run pyright
uv run pytest
RUN_LOCAL_MODEL_TESTS=1 uv run pytest tests/integration   # downloads the local model once
```

CI runs the same checks on Linux, macOS (Apple Silicon and Intel) and Windows with Python
3.11-3.14, and a separate job tests the real local embedding model.

## Ground rules

- **Respect the layers.** `domain` uses only the standard library; `application` never
  imports `adapters` or `interfaces`. `tests/architecture` enforces this.
- **New backend = new adapter.** Implement the port, add the factory to the matching suite
  in `tests/contract/`, wire it in `bootstrap.py`. Don't change use cases to fit an adapter.
- **Adding a model provider.** If it speaks the OpenAI format, add an entry to
  `adapters/llm/providers.py`. Otherwise write a backend implementing `LlmBackend`
  (`adapters/llm/base.py`) with tests against `tests/llm_support.FakeTransport`, then add
  the entry. Prompts and schemas stay in `prompts.py`; don't fork them per provider.
- **Rules before models.** If something can be parsed deterministically, don't ask an LLM.
- **Provenance on every fact.** New edges need an origin, a grade and a producer.
- **Never commit real people's data.** Use invented names in fixtures
  (`Jane Example`, `linkedin.com/in/jane-example`).
- **Tests describe behaviour.** Name them as sentences:
  `test_reingest_never_overrides_the_users_decisions`.
