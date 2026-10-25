"""The real local embedding model. Downloads it (~70 MB), so it only runs when asked:

RUN_LOCAL_MODEL_TESTS=1 uv run pytest tests/integration
"""

import os
from pathlib import Path

import pytest

from postloom.adapters.llm.local_embeddings import LocalEmbeddings, local_embeddings_installed
from postloom.application.ports.embeddings import DocumentText

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LOCAL_MODEL_TESTS") != "1" or not local_embeddings_installed(),
    reason="set RUN_LOCAL_MODEL_TESTS=1 to download and test the local model",
)

CACHE = Path(os.environ.get("POSTLOOM_TEST_MODEL_CACHE", Path.home() / ".cache" / "postloom-test"))


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_local_vectors_are_unit_length_and_meaningful() -> None:
    model = LocalEmbeddings(CACHE)
    cache, leak, pasta = model.embed_documents(
        [
            DocumentText("Semantic caching", "Reuse an LLM answer when a new question is similar."),
            DocumentText("Data leakage", "Test information reaching training inflates scores."),
            DocumentText("Dinner", "Boil the pasta and stir in tomato sauce with basil."),
        ]
    )
    query = model.embed_query("when can I reuse a cached model answer?")
    assert len(query) == 384
    assert abs(dot(query, query) - 1.0) < 1e-4
    assert dot(query, cache) > dot(query, leak) > dot(query, pasta)
    assert model.name == "local:BAAI/bge-small-en-v1.5"
