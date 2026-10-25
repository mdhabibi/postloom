"""Metering, budget, embeddings text conventions and the provider factory."""

import pytest

from postloom.adapters.llm.base import EmbeddingKind, parse_json_object
from postloom.adapters.llm.embeddings import document_text, query_text, vector_space
from postloom.adapters.llm.providers import PROVIDERS, build_backend, is_local_url
from postloom.application.errors import BudgetExceededError, NotConfiguredError
from postloom.application.ports.embeddings import DocumentText
from postloom.application.ports.usage import Task
from postloom.application.use_cases.usage import Price, PriceBook
from tests.fakes import FakeBackend
from tests.llm_support import metered


def ask(gateway: object) -> str:
    from postloom.adapters.llm.gateway import LlmGateway

    assert isinstance(gateway, LlmGateway)
    return gateway.text(
        Task.CHAT, "paid", system="s", turns=[("user", "q")], temperature=0, max_output_tokens=9
    )


def test_calls_are_priced_from_the_table() -> None:
    gateway, ledger = metered(
        FakeBackend(usage=(2_000_000, 1_000_000)), prices={"paid": Price(1, 2)}
    )
    ask(gateway)
    (entry,) = ledger.month("2026-10")
    assert (entry.calls, entry.cost_usd, entry.unpriced_calls) == (1, 4.0, 0)


def test_unknown_prices_are_flagged_not_guessed() -> None:
    gateway, ledger = metered(FakeBackend())
    ask(gateway)
    assert (ledger.month("2026-10")[0].cost_usd, ledger.month("2026-10")[0].unpriced_calls) == (
        0,
        1,
    )


def test_budget_refuses_the_call_after_the_limit_is_reached() -> None:
    backend = FakeBackend(usage=(1_000_000, 0))
    gateway, _ = metered(backend, prices={"paid": Price(1, 0)}, budget=1.5)
    ask(gateway)  # $1 spent
    ask(gateway)  # $2 spent: this call started under the limit
    with pytest.raises(BudgetExceededError, match=r"\$1\.50"):
        ask(gateway)
    assert len(backend.calls) == 2


def test_no_budget_means_no_limit() -> None:
    gateway, _ = metered(FakeBackend(usage=(10**9, 0)), prices={"paid": Price(100, 0)})
    for _ in range(3):
        ask(gateway)


def test_embedding_calls_are_metered_as_embeddings() -> None:
    gateway, ledger = metered(FakeBackend())
    gateway.embed("e", ["a", "b"], kind=EmbeddingKind.DOCUMENT, dimensions=None)
    entry = ledger.month("2026-10")[0]
    assert (entry.task, entry.input_tokens) == (Task.EMBEDDINGS, 20)


def test_user_prices_override_the_built_in_table() -> None:
    book = PriceBook({"m": Price(1, 1)}, {"m": Price(2, 2)})
    assert book.cost("m", 1_000_000, 0) == 2.0
    assert book.cost("other", 1, 1) is None


@pytest.mark.parametrize(
    ("model", "document", "query"),
    [
        ("nomic-embed-text", "search_document: T\n\nbody", "search_query: q"),
        ("intfloat/multilingual-e5-small", "passage: T\n\nbody", "query: q"),
        (
            "BAAI/bge-small-en-v1.5",
            "T\n\nbody",
            "Represent this sentence for searching relevant passages: q",
        ),
        ("text-embedding-3-small", "T\n\nbody", "q"),
    ],
)
def test_embedding_models_get_their_task_markers(model: str, document: str, query: str) -> None:
    assert document_text(model, DocumentText("T", "body")) == document
    assert query_text(model, "q") == query


def test_vector_spaces_are_namespaced_by_provider() -> None:
    assert vector_space("gemini", "gemini-embedding-2", 768) == "gemini-embedding-2@768"
    assert vector_space("openai", "text-embedding-3-small", None) == (
        "openai:text-embedding-3-small@native"
    )


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Here you go: {"a": 1} hope it helps',
        '<think>x</think>{"a": 1}',
    ],
)
def test_json_answers_are_parsed_leniently(text: str) -> None:
    assert parse_json_object(text, "M") == {"a": 1}


def test_providers_that_need_a_key_refuse_to_start_without_one() -> None:
    with pytest.raises(NotConfiguredError, match=r"console\.anthropic\.com"):
        build_backend("anthropic", api_key="")
    with pytest.raises(NotConfiguredError, match="Unknown provider"):
        build_backend("nope", api_key="k")


def test_every_provider_with_defaults_has_all_four_task_models() -> None:
    for spec in PROVIDERS.values():
        models = (spec.models.extraction, spec.models.comments, spec.models.chat, spec.models.reply)
        assert all(models) or not any(models), spec.id
        assert spec.offers_embeddings == bool(spec.models.embedding) or not any(models), spec.id


def test_local_urls_are_recognised() -> None:
    assert is_local_url("http://localhost:1234/v1") and is_local_url("http://127.0.0.1:8080")
    assert not is_local_url("https://api.groq.com/openai/v1")
