"""A cross-encoder that re-scores search results on this computer, with fastembed.

Embeddings compare a question and a passage from two separate summaries; a cross-encoder
reads them together, which is slower but much better at telling a passage that answers
the question from one that only shares its subject. postloom uses it to decide whether
the library holds an answer at all (see AskQuestion), on the 30 best candidates.

The model (``Xenova/ms-marco-MiniLM-L-6-v2``, ~80 MB, English, Apache-2.0) is downloaded
once into ``<home>/models`` the first time a question is asked. Loading is lazy and
thread-safe.
"""

from __future__ import annotations

import importlib
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from postloom.application.errors import ProviderUnavailableError

DEFAULT_RERANKER = "Xenova/ms-marco-MiniLM-L-6-v2"
RELEVANT_SCORE = -7.0
"""The lowest score at which the best passage counts as an answer, for the default model.
Chosen on the retrieval benchmark (scripts/eval): below it, questions about things the
library doesn't hold; above it, almost every answerable one."""


class LocalReranker:
    def __init__(self, cache_dir: Path, model: str = DEFAULT_RERANKER) -> None:
        self._cache_dir = cache_dir
        self._model_name = model
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return f"local:{self._model_name}"

    @property
    def relevant_score(self) -> float:
        return RELEVANT_SCORE if self._model_name == DEFAULT_RERANKER else float("-inf")

    def scores(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        model = self._load()
        with self._lock:
            return [float(s) for s in model.rerank(query, list(passages), batch_size=32)]

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                try:
                    module = importlib.import_module("fastembed.rerank.cross_encoder")
                except ImportError as error:
                    raise ProviderUnavailableError(
                        "Reranking needs the fastembed package. Reinstall postloom."
                    ) from error
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                try:
                    self._model = module.TextCrossEncoder(
                        model_name=self._model_name, cache_dir=str(self._cache_dir)
                    )
                except Exception as error:  # download or model errors, from many libraries
                    raise ProviderUnavailableError(
                        f"Couldn't load the reranking model {self._model_name}. The first "
                        "question downloads it (~80 MB), which needs an internet "
                        f"connection. ({error})"
                    ) from error
            return self._model
