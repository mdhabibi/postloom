"""Runtime settings: which provider, which models, which limits.

Precedence for every value: environment variable > ``<home>/config.json`` > the
provider's defaults. Older configs (Gemini only, flat keys) keep working unchanged,
including their search index: a Gemini setup that predates local embeddings keeps
Gemini embeddings until the user changes it.

config.json layout (all keys optional)::

    {
      "provider": "anthropic",
      "api_keys": {"anthropic": "sk-ant-...", "gemini": "..."},
      "base_urls": {"ollama": "http://localhost:11434"},
      "models": {"anthropic": {"reply": "claude-sonnet-5-5"}},
      "embeddings": "local",                # or "provider", or "off" (keywords only)
      "local_embedding_model": "BAAI/bge-small-en-v1.5",
      "reranking": true,                    # a local model decides "not found" (English)
      "min_similarity": 0.7, "related_similarity": 0.8,
      "monthly_budget_usd": 5,
      "prices": {"my-model": [0.5, 1.5]},   # USD per million tokens, input and output
      "ollama_context": 32768,
      "owner_name": "Jane Example"
    }
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from postloom.adapters.llm.embeddings import vector_space
from postloom.adapters.llm.local_embeddings import DEFAULT_LOCAL_MODEL
from postloom.adapters.llm.ollama import DEFAULT_CONTEXT_LIMIT
from postloom.adapters.llm.providers import PROVIDERS, ProviderSpec
from postloom.application.use_cases.usage import Price
from postloom.config import read_config, write_config

HOME_ENV = "POSTLOOM_HOME"
PROVIDER_ENV = "POSTLOOM_PROVIDER"
API_KEY_ENV = "POSTLOOM_API_KEY"
BASE_URL_ENV = "POSTLOOM_BASE_URL"
MODEL_ENVS = {
    "extraction": "POSTLOOM_EXTRACTION_MODEL",
    "comments": "POSTLOOM_COMMENTS_MODEL",
    "chat": "POSTLOOM_CHAT_MODEL",
    "reply": "POSTLOOM_REPLY_MODEL",
    "embedding": "POSTLOOM_EMBEDDING_MODEL",
}
EMBEDDINGS_ENV = "POSTLOOM_EMBEDDINGS"
LOCAL_EMBEDDING_MODEL_ENV = "POSTLOOM_LOCAL_EMBEDDING_MODEL"
MIN_SIMILARITY_ENV = "POSTLOOM_MIN_SIMILARITY"
RERANKING_ENV = "POSTLOOM_RERANKING"
RELATED_SIMILARITY_ENV = "POSTLOOM_RELATED_SIMILARITY"
BUDGET_ENV = "POSTLOOM_MONTHLY_BUDGET"
OLLAMA_CONTEXT_ENV = "POSTLOOM_OLLAMA_CONTEXT"
OWNER_NAME_ENV = "POSTLOOM_OWNER_NAME"

ModelTask = Literal["extraction", "comments", "chat", "reply", "embedding"]
MODEL_TASKS: tuple[ModelTask, ...] = ("extraction", "comments", "chat", "reply", "embedding")
EmbeddingMode = Literal["local", "provider", "off"]
"""Where search vectors come from: this computer, the provider, or nowhere (keywords only)."""
KeySource = Literal["environment", "config", "missing", "not-needed"]


@dataclass(frozen=True, slots=True)
class Cutoffs:
    """Calibrated similarity thresholds for one embedding model."""

    search: float
    """A passage below this is unrelated to the query (search and library chat)."""
    related: float
    """Two articles at least this similar get a suggested link."""


CUTOFFS: dict[str, Cutoffs] = {
    # Calibrated on real articles: on-topic 0.72-0.73, near miss 0.62, unrelated 0.51.
    "gemini-embedding-2@768": Cutoffs(search=0.66, related=0.75),
    # Calibrated in CI (scripts/calibrate_embeddings.py): on-topic 0.75-0.83, near miss
    # 0.59-0.61, unrelated 0.46; related article 0.89, same field 0.60.
    "local:BAAI/bge-small-en-v1.5": Cutoffs(search=0.68, related=0.75),
    # Calibrated in CI: on-topic 0.42-0.56, near miss 0.07-0.26, unrelated under 0.08;
    # related article 0.67, same field 0.18-0.27.
    "local:sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": Cutoffs(
        search=0.34, related=0.47
    ),
}
FALLBACK_CUTOFFS = Cutoffs(search=0.35, related=0.55)
"""For models nobody calibrated yet (OpenAI-style embeddings score lower than Gemini's).
Check with `postloom search --explain` and `postloom links --explain`, then set them."""


@dataclass(frozen=True, slots=True)
class Settings:
    home: Path = field(default_factory=lambda: default_home())
    provider: str | None = None
    """None until the user picks one."""
    api_key: str | None = None
    api_key_source: KeySource = "missing"
    base_url: str | None = None
    models: Mapping[str, str] = field(default_factory=dict[str, str])
    """Explicit model choices by task; missing tasks use the provider's defaults."""
    embeddings: EmbeddingMode = "local"
    local_embedding_model: str = DEFAULT_LOCAL_MODEL
    min_similarity: float | None = None
    related_similarity: float | None = None
    reranking: bool = True
    """With the local English search model, a local cross-encoder decides whether the
    library holds an answer (AskQuestion). Off: the similarity cutoff decides."""
    monthly_budget_usd: float | None = None
    prices: Mapping[str, Price] = field(default_factory=dict[str, Price])
    ollama_context: int = DEFAULT_CONTEXT_LIMIT
    owner_name: str = ""
    locked: frozenset[str] = frozenset()
    """Settings fixed by environment variables, which the app must not try to change."""

    # -- derived ------------------------------------------------------------------
    @property
    def spec(self) -> ProviderSpec | None:
        return PROVIDERS.get(self.provider) if self.provider else None

    @property
    def configured(self) -> bool:
        """A provider is chosen and has what it needs to make calls."""
        spec = self.spec
        if spec is None:
            return False
        if spec.needs_key and not self.api_key:
            return False
        return all(self.model(task) for task in ("extraction", "comments", "chat", "reply"))

    def model(self, task: ModelTask) -> str:
        explicit = self.models.get(task, "").strip()
        if explicit:
            return explicit
        spec = self.spec
        return getattr(spec.models, task) if spec else ""

    @property
    def uses_provider_embeddings(self) -> bool:
        spec = self.spec
        return (
            self.embeddings == "provider"
            and spec is not None
            and spec.offers_embeddings
            and bool(self.model("embedding"))
        )

    @property
    def embedding_dimensions(self) -> int | None:
        """Requested vector size; Gemini supports 768 on every embedding model."""
        return 768 if self.provider == "gemini" else None

    @property
    def embedding_space(self) -> str:
        """The vector space the search index should be in ("" when embeddings are off)."""
        if self.embeddings == "off":
            return ""
        if self.uses_provider_embeddings and self.provider:
            return vector_space(self.provider, self.model("embedding"), self.embedding_dimensions)
        return f"local:{self.local_embedding_model}"

    @property
    def cutoffs(self) -> Cutoffs:
        return self.cutoffs_for(self.embedding_space)

    def cutoffs_for(self, space: str) -> Cutoffs:
        """Cutoffs for vectors in ``space``: explicit settings win over calibrated ones."""
        calibrated = CUTOFFS.get(space, FALLBACK_CUTOFFS)
        return Cutoffs(
            search=calibrated.search if self.min_similarity is None else self.min_similarity,
            related=calibrated.related
            if self.related_similarity is None
            else self.related_similarity,
        )

    @property
    def vault_dir(self) -> Path:
        return self.home / "vault"

    @property
    def index_path(self) -> Path:
        return self.home / "index.db"

    @property
    def models_dir(self) -> Path:
        return self.home / "models"

    def __repr__(self) -> str:  # never print the key
        key = "set" if self.api_key else "missing"
        return (
            f"Settings(home={self.home!s}, provider={self.provider}, api_key={key}, "
            f"models={dict(self.models)}, embeddings={self.embeddings})"
        )

    # -- loading ------------------------------------------------------------------
    @classmethod
    def load(cls, home: Path | None = None) -> Settings:
        resolved = (home or default_home()).expanduser()
        saved = read_config(resolved)
        locked: set[str] = set()

        provider = _env(PROVIDER_ENV) or _str(saved.get("provider"))
        legacy_gemini = "provider" not in saved and isinstance(saved.get("gemini_api_key"), str)
        if provider:
            if provider == _env(PROVIDER_ENV):
                locked.add("provider")
        elif legacy_gemini:
            provider = "gemini"
        else:
            provider = next(
                (p.id for p in PROVIDERS.values() if any(_env(e) for e in p.key_envs)), None
            )
        spec = PROVIDERS.get(provider) if provider else None

        api_key, source = _api_key(spec, saved)
        if source == "environment":
            locked.add("api_key")

        base_urls = _dict(saved.get("base_urls"))
        base_url = _env(BASE_URL_ENV) or (_str(base_urls.get(provider)) if provider else None)
        if spec is not None and not base_url:
            base_url = spec.base_url

        per_provider = _dict(_dict(saved.get("models")).get(provider)) if provider else {}
        models: dict[str, str] = {}
        for task in MODEL_TASKS:
            legacy = _str(saved.get(f"{task}_model")) if provider == "gemini" else None
            value = _env(MODEL_ENVS[task]) or _str(per_provider.get(task)) or legacy
            if value:
                models[task] = value
            if _env(MODEL_ENVS[task]):
                locked.add(f"model:{task}")

        if _env(OWNER_NAME_ENV):
            locked.add("owner_name")
        mode = _env(EMBEDDINGS_ENV) or _str(saved.get("embeddings"))
        if mode not in ("local", "provider", "off"):
            # Gemini setups from before local embeddings keep the index they built.
            mode = "provider" if legacy_gemini else "local"

        return cls(
            home=resolved,
            provider=provider,
            api_key=api_key,
            api_key_source=source,
            base_url=base_url,
            models=models,
            embeddings=mode,
            local_embedding_model=_env(LOCAL_EMBEDDING_MODEL_ENV)
            or _str(saved.get("local_embedding_model"))
            or DEFAULT_LOCAL_MODEL,
            min_similarity=_float(_env(MIN_SIMILARITY_ENV) or saved.get("min_similarity")),
            reranking=_switch(_env(RERANKING_ENV), saved.get("reranking"), default=True),
            related_similarity=_float(
                _env(RELATED_SIMILARITY_ENV) or saved.get("related_similarity")
            ),
            monthly_budget_usd=_float(_env(BUDGET_ENV) or saved.get("monthly_budget_usd")),
            prices=_prices(saved.get("prices")),
            ollama_context=int(
                _float(_env(OLLAMA_CONTEXT_ENV) or saved.get("ollama_context"))
                or DEFAULT_CONTEXT_LIMIT
            ),
            owner_name=_env(OWNER_NAME_ENV) or _str(saved.get("owner_name")) or "",
            locked=frozenset(locked),
        )


def default_home() -> Path:
    override = _env(HOME_ENV)
    return Path(override).expanduser() if override else Path.home() / "Postloom"


def _api_key(spec: ProviderSpec | None, saved: Mapping[str, Any]) -> tuple[str | None, KeySource]:
    if spec is None:
        return None, "missing"
    if spec.key == "none":
        return None, "not-needed"
    for name in (API_KEY_ENV, *spec.key_envs):
        value = _env(name)
        if value:
            return value, "environment"
    stored = _str(_dict(saved.get("api_keys")).get(spec.id))
    if stored is None and spec.id == "gemini":
        stored = _str(saved.get("gemini_api_key"))  # configs from before multi-provider
    if stored:
        return stored, "config"
    return None, "missing" if spec.needs_key else "not-needed"


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _str(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _dict(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _switch(env: str | None, saved: object, *, default: bool) -> bool:
    """An on/off setting: "0", "false", "off" or "no" turn it off."""
    if env:
        return env.strip().casefold() not in {"0", "false", "off", "no"}
    if isinstance(saved, bool):
        return saved
    return default


def _float(value: object) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, int | float | str):
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"Expected a number in settings, got {value!r}.") from None
    raise ValueError(f"Expected a number in settings, got {value!r}.")


def _prices(value: object) -> dict[str, Price]:
    prices: dict[str, Price] = {}
    for model, pair in _dict(value).items():
        if isinstance(pair, list | tuple) and len(cast(list[Any], pair)) == 2:
            first, second = cast(list[Any], pair)
            input_price, output_price = _float(first), _float(second)
            if input_price is not None and output_price is not None:
                prices[model] = Price(input_price, output_price)
    return prices


# -- saving -------------------------------------------------------------------------
class _Unset:
    """Marks a setting the caller didn't mention (None means "remove")."""


UNSET: Any = _Unset()


def save_settings(
    home: Path,
    *,
    provider: str | None = UNSET,
    api_key: str | None = UNSET,
    base_url: str | None = UNSET,
    models: Mapping[str, str | None] = UNSET,
    embeddings: str | None = UNSET,
    local_embedding_model: str | None = UNSET,
    monthly_budget_usd: float | None = UNSET,
    owner_name: str | None = UNSET,
    ollama_context: int | None = UNSET,
) -> None:
    """Change only the given settings in config.json. Keys, URLs and models are stored per
    provider, so switching providers and back keeps each one's setup."""
    current = Settings.load(home)
    changing_locked = [
        name
        for name, value, lock in (
            ("provider", provider, "provider"),
            ("API key", api_key, "api_key"),
            ("your name", owner_name, "owner_name"),
        )
        if value is not UNSET and lock in current.locked
    ]
    requested: Mapping[str, str | None] = {} if models is UNSET else models
    changing_locked += [f"the {t} model" for t in requested if f"model:{t}" in current.locked]
    if changing_locked:
        raise ValueError(
            f"{', '.join(changing_locked).capitalize()} is set by an environment variable, which "
            "wins over saved settings. Change it there, or unset it to use this screen."
        )

    saved = _migrated(read_config(home), current)
    chosen_provider: str | None = None if provider is UNSET else provider
    target = chosen_provider or _str(saved.get("provider"))
    if provider is not UNSET:
        if provider is not None and provider not in PROVIDERS:
            raise ValueError(f"Unknown provider {provider!r}.")
        saved["provider"] = provider
    needs_target = any(v is not UNSET for v in (api_key, base_url, models))
    if needs_target and target is None:
        raise ValueError("Choose a provider first.")
    target = target or ""
    if api_key is not UNSET:
        _set_in(saved, "api_keys", target, (api_key or "").strip() or None)
    if base_url is not UNSET:
        _set_in(saved, "base_urls", target, (base_url or "").strip().rstrip("/") or None)
    if models is not UNSET:
        chosen = _dict(_dict(saved.get("models")).get(target))
        for task, model in requested.items():
            if task not in MODEL_TASKS:
                raise ValueError(f"Unknown model task {task!r}.")
            if model and model.strip():
                chosen[task] = model.strip()
            else:
                chosen.pop(task, None)
        _set_in(saved, "models", target, chosen or None)
    if embeddings is not UNSET:
        if embeddings not in (None, "local", "provider", "off"):
            raise ValueError(f"Unknown embeddings mode {embeddings!r}.")
        saved["embeddings"] = embeddings
    if local_embedding_model is not UNSET:
        saved["local_embedding_model"] = (local_embedding_model or "").strip() or None
    if monthly_budget_usd is not UNSET:
        if monthly_budget_usd is not None and monthly_budget_usd < 0:
            raise ValueError("The monthly budget can't be negative.")
        saved["monthly_budget_usd"] = monthly_budget_usd
    if owner_name is not UNSET:
        saved["owner_name"] = (owner_name or "").strip() or None
    if ollama_context is not UNSET:
        if ollama_context is not None and ollama_context < 8192:
            raise ValueError("The Ollama context limit must be at least 8192 tokens.")
        saved["ollama_context"] = ollama_context
    write_config(home, {k: v for k, v in saved.items() if v is not None})


def _migrated(saved: dict[str, Any], current: Settings) -> dict[str, Any]:
    """Bring a pre-multi-provider config to the current layout without changing behaviour."""
    legacy_key = saved.pop("gemini_api_key", None)
    if isinstance(legacy_key, str) and legacy_key.strip():
        keys = _dict(saved.get("api_keys"))
        keys.setdefault("gemini", legacy_key.strip())
        saved["api_keys"] = keys
        saved.setdefault("provider", "gemini")
        saved.setdefault("embeddings", current.embeddings)  # keep the index it built
    legacy_models = {
        task: saved.pop(f"{task}_model")
        for task in MODEL_TASKS
        if isinstance(saved.get(f"{task}_model"), str)
    }
    if legacy_models:
        models = _dict(saved.get("models"))
        gemini = _dict(models.get("gemini"))
        for task, model in legacy_models.items():
            gemini.setdefault(task, model)
        models["gemini"] = gemini
        saved["models"] = models
    return saved


def _set_in(saved: dict[str, Any], section: str, provider: str, value: object) -> None:
    group = _dict(saved.get(section))
    if value is None:
        group.pop(provider, None)
    else:
        group[provider] = value
    saved[section] = group or None
