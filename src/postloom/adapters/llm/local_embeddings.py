"""Embeddings computed on this computer with fastembed (ONNX Runtime, no PyTorch).

The default for every provider: search, related-article links and the graph then cost
nothing, work offline after the first run, and behave the same whichever chat provider
the user picks (Anthropic, for one, has no embedding API).

The model (~70 MB for the default) is downloaded once into ``<home>/models`` on first
use. Loading is lazy and thread-safe, so starting postloom stays instant.
"""

from __future__ import annotations

import importlib
import importlib.util
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from postloom.adapters.llm.embeddings import document_text, normalize, query_text
from postloom.application.errors import ProviderUnavailableError
from postloom.application.ports.embeddings import DocumentText, Vector

DEFAULT_LOCAL_MODEL = "BAAI/bge-small-en-v1.5"
"""English, 384 dimensions, ~70 MB."""
MULTILINGUAL_LOCAL_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
"""50+ languages, 384 dimensions, ~220 MB."""
ENGLISH_ONLY_MODELS = frozenset({DEFAULT_LOCAL_MODEL})

_BATCH_SIZE = 32


def local_embeddings_installed() -> bool:
    """True when fastembed can be imported (it is a regular dependency of postloom)."""
    return importlib.util.find_spec("fastembed") is not None


class LocalEmbeddings:
    def __init__(self, cache_dir: Path, model: str = DEFAULT_LOCAL_MODEL) -> None:
        self._cache_dir = cache_dir
        self._model_name = model
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return f"local:{self._model_name}"

    def embed_documents(self, documents: Sequence[DocumentText]) -> list[Vector]:
        return self._embed([document_text(self._model_name, d) for d in documents])

    def embed_query(self, query: str) -> Vector:
        return self._embed([query_text(self._model_name, query)])[0]

    def _embed(self, texts: list[str]) -> list[Vector]:
        model = self._load()
        with self._lock:  # ONNX sessions are safe to share, but batching is cheaper serial
            raw: Iterable[Any] = model.embed(texts, batch_size=_BATCH_SIZE)
            return [normalize([float(x) for x in vector]) for vector in raw]

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                try:
                    fastembed = importlib.import_module("fastembed")
                except ImportError as error:
                    raise ProviderUnavailableError(
                        "Local embeddings need the fastembed package. Reinstall postloom, or "
                        "choose your provider's embeddings in Settings."
                    ) from error
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                try:
                    self._model = fastembed.TextEmbedding(
                        model_name=self._model_name, cache_dir=str(self._cache_dir)
                    )
                except Exception as error:  # download or model errors, from many libraries
                    raise ProviderUnavailableError(
                        f"Couldn't load the local embedding model {self._model_name}. The "
                        "first run downloads it (~70 MB), which needs an internet connection. "
                        f"({error})"
                    ) from error
            return self._model
