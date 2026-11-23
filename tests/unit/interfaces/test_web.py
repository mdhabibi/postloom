"""The web API, exercised in-process through ASGI."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

from postloom.application.defaults import DEFAULT_TOPICS
from postloom.application.errors import ProviderAuthError
from postloom.bootstrap import Container, Settings, build_container
from postloom.config import read_config, update_config
from postloom.interfaces.web.app import create_app
from tests.asgi import AsgiClient
from tests.fakes import (
    FakeBackend,
    FakeChat,
    FakeEmbedder,
    FakeExtractor,
    FakeThreadParser,
    fixture_text,
    part3_extraction,
)

ARTICLE = fixture_text("semantic_caching_part3", "article.txt")
POST = fixture_text("semantic_caching_part3", "post.txt")


def client_for(
    tmp_path: Path,
    *,
    providers: bool = True,
    chat: FakeChat | None = None,
    backend: FakeBackend | None = None,
    connect: FakeConnect | None = None,
) -> AsgiClient:
    """The app on real settings from ``tmp_path`` (with a real config.json), but never a
    real provider: either fakes per port, or a fake backend behind the real gateway."""
    chat = chat or FakeChat()

    def load() -> Settings:
        return replace(Settings.load(tmp_path), min_similarity=0.0)

    def make(settings: Settings) -> Container:
        offline = replace(settings, provider=None, api_key=None, embeddings="off")
        if backend is not None:
            container = build_container(
                replace(offline, models=FAKE_MODELS), backend=backend, embedder=FakeEmbedder()
            )
        elif providers:
            container = build_container(
                offline,
                extractor=FakeExtractor(part3_extraction()),
                embedder=FakeEmbedder(),
                chat=chat,
                thread_parser=FakeThreadParser(),
            )
        else:
            container = build_container(offline)
        container.seed_topics().execute(DEFAULT_TOPICS)
        return container

    return AsgiClient(create_app(load, make, connect=connect or FakeConnect()))


FAKE_MODELS = {
    "extraction": "fake-small",
    "comments": "fake-small",
    "chat": "fake-chat",
    "reply": "fake-chat",
}


@dataclass
class FakeConnect:
    """Stands in for build_backend in "Test connection"; records what it was asked."""

    models: list[str] = field(default_factory=lambda: ["model-a", "model-b"])
    error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def __call__(self, provider: str, **options: Any) -> FakeBackend:
        self.calls.append({"provider": provider, **options})
        if self.error is not None:
            raise self.error
        return FakeBackend(models=self.models)


def ingest(client: AsgiClient, **overrides: Any) -> dict[str, Any]:
    body = {"article_text": ARTICLE, "post_text": POST, "published_on": "2026-10-12"}
    reply = client.post("/api/articles", json_body={**body, **overrides})
    assert reply.status == 201, reply.text
    return reply.json


# -- pages and status -----------------------------------------------------------------
def test_index_page_is_served(tmp_path: Path) -> None:
    reply = client_for(tmp_path).get("/")
    assert reply.status == 200
    assert "postloom" in reply.text


def test_status_reports_features_without_leaking_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env-secret")
    client = client_for(tmp_path)
    reply = client.get("/api/status")
    status = reply.json
    assert status["provider"]["id"] == "gemini"
    assert status["provider"]["key"] == "environment"
    assert status["provider"]["configured"] is True
    assert "env-secret" not in reply.text
    assert status["features"] == {
        "ingest": True,
        "semantic_search": True,
        "chat": True,
        "comments": True,
        "reply_drafts": True,
    }
    assert status["articles"] == 0
    assert "RAG" in status["topics"]
    assert status["models"]["chat"] == "gemini-3.8-flash"
    assert {p["id"] for p in status["providers"]} >= {"gemini", "anthropic", "openai", "ollama"}


# -- articles -------------------------------------------------------------------------
def test_ingest_list_and_open_an_article(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    added = ingest(client, article_url="https://www.linkedin.com/pulse/part-3")

    assert added["topics"] == ["RAG", "AI Agents"]
    assert added["index"]["semantic"] is True
    assert added["index_error"] is None

    listed = client.get("/api/articles").json["articles"]
    assert [a["id"] for a in listed] == [added["id"]]
    assert listed[0]["published_on"] == "2026-10-12"
    assert listed[0]["topics"][0] == {"name": "RAG", "grade": "asserted"}

    detail = client.get(f"/api/article?id={added['id']}").json
    assert detail["body_markdown"].startswith("Measuring What Matters")
    assert detail["url"] == "https://www.linkedin.com/pulse/part-3"
    assert detail["posts"][0]["links"][0] == "https://lnkd.in/euyuNU9y"


def test_unknown_article_is_404(tmp_path: Path) -> None:
    reply = client_for(tmp_path).get("/api/article?id=article:nope")
    assert reply.status == 404
    assert reply.json == {"error": "Article not found."}


def test_ingest_without_api_key_explains_what_to_do(tmp_path: Path) -> None:
    client = client_for(tmp_path, providers=False)
    reply = client.post("/api/articles", json_body={"article_text": "a", "post_text": "b"})
    assert reply.status == 409
    assert "choose a provider" in reply.json["error"]


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"article_text": "", "post_text": "p"}, "article_text"),
        ({"article_text": "a"}, "post_text"),
        ({"article_text": "a", "post_text": "p", "published_on": "13/10/2026"}, "published_on"),
        ({"article_text": "a", "post_text": "p", "surprise": 1}, "surprise"),
    ],
)
def test_invalid_ingest_requests_are_rejected(
    tmp_path: Path, body: dict[str, Any], fragment: str
) -> None:
    reply = client_for(tmp_path).post("/api/articles", json_body=body)
    assert reply.status == 422
    assert fragment in reply.json["error"]


def test_non_json_body_is_rejected(tmp_path: Path) -> None:
    reply = client_for(tmp_path).post("/api/articles", raw_body=b"not json")
    assert reply.status == 400


# -- search and chat ------------------------------------------------------------------
def test_search_returns_passages(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    ingest(client)
    found = client.get("/api/search?q=cache+hit+rate").json
    assert found["methods"] == ["keyword", "semantic"]
    assert found["results"][0]["title"].startswith("Measuring What Matters")
    assert found["results"][0]["passages"][0]["excerpt"]


def test_ask_about_an_article_returns_cited_sources(tmp_path: Path) -> None:
    chat = FakeChat(reply="Track hit rate and precision [1].")
    client = client_for(tmp_path, chat=chat)
    article_id = ingest(client)["id"]

    reply = client.post(
        "/api/ask",
        json_body={
            "question": "Which metrics?",
            "article_id": article_id,
            "history": [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "hello"}],
        },
    )

    assert reply.status == 200, reply.text
    answer = reply.json
    assert answer["text"] == "Track hit rate and precision [1]."
    assert answer["grounded"] is True
    assert [s["number"] for s in answer["sources"]] == [1]
    assert [m.text for m in chat.calls[0][1][:2]] == ["hi", "hello"]


def test_chat_without_api_key_is_409(tmp_path: Path) -> None:
    reply = client_for(tmp_path, providers=False).post("/api/ask", json_body={"question": "q"})
    assert reply.status == 409


# -- comments -------------------------------------------------------------------------
def test_preview_then_save_a_comment_thread(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    article_id = ingest(client)["id"]
    pasted = fixture_text("comments", "caching_thread.txt")

    preview = client.post(
        "/api/comments/preview", json_body={"article_id": article_id, "text": pasted}
    )
    assert preview.status == 200, preview.text
    messages = preview.json["messages"]
    assert [(m["author_name"], m["thread"], m["reply_to"]) for m in messages][:3] == [
        ("Jane Example", None, None),
        ("Alex Author", 0, 0),
        ("Jane Example", 0, 1),
    ]

    review = [
        {k: v for k, v in m.items() if k not in ("already_saved", "known_person")} for m in messages
    ]
    review[0]["profile_url"] = "linkedin.com/in/jane-example"
    saved = client.post("/api/comments", json_body={"article_id": article_id, "messages": review})
    assert saved.status == 201, saved.text
    assert saved.json == {"added": 5, "already_saved": 0, "new_people": 2}

    discussion = client.get(f"/api/article?id={article_id}").json["discussion"]
    assert [(c["author_name"], c["depth"]) for c in discussion] == [
        ("Jane Example", 0),
        ("Alex Author", 1),
        ("Jane Example", 2),
        ("Alex Author", 3),
        ("John Sample", 0),
    ]
    assert discussion[1]["is_own"] and discussion[1]["reply_to_name"] == "Jane Example"
    assert discussion[0]["author_headline"] == "Senior ML Engineer at Acme Analytics"


def test_saving_a_broken_review_is_rejected(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    article_id = ingest(client)["id"]
    bad = [{"author_name": "Jane", "text": "x", "thread": 0, "reply_to": 0}]
    reply = client.post("/api/comments", json_body={"article_id": article_id, "messages": bad})
    assert reply.status == 400
    assert "invalid thread" in reply.json["error"]


def test_comments_need_an_api_key(tmp_path: Path) -> None:
    client = client_for(tmp_path, providers=False)
    reply = client.post("/api/comments/preview", json_body={"article_id": "a", "text": "x"})
    assert reply.status == 409


# -- settings -------------------------------------------------------------------------
def test_choosing_a_provider_and_saving_its_key(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    assert client.get("/api/status").json["provider"] is None

    reply = client.put(
        "/api/settings", json_body={"provider": "anthropic", "api_key": "  sk-secret  "}
    )

    assert reply.status == 200, reply.text
    provider = reply.json["provider"]
    assert (provider["id"], provider["key"], provider["configured"]) == (
        "anthropic",
        "config",
        True,
    )
    assert reply.json["models"]["reply"] == "claude-sonnet-5-5"
    assert read_config(tmp_path)["api_keys"] == {"anthropic": "sk-secret"}
    assert "sk-secret" not in reply.text


def test_keys_and_models_are_kept_per_provider(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    client.put("/api/settings", json_body={"provider": "gemini", "api_key": "g-key"})
    client.put("/api/settings", json_body={"models": {"chat": "gemini-x"}})
    client.put("/api/settings", json_body={"provider": "openai", "api_key": "o-key"})
    assert client.get("/api/status").json["models"]["chat"] == "gpt-5.6-luna"

    back = client.put("/api/settings", json_body={"provider": "gemini"}).json
    assert back["provider"]["key"] == "config"
    assert back["models"]["chat"] == "gemini-x"
    assert read_config(tmp_path)["api_keys"] == {"gemini": "g-key", "openai": "o-key"}


def test_clearing_the_key_removes_it(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    client.put("/api/settings", json_body={"provider": "gemini", "api_key": "k"})
    reply = client.put("/api/settings", json_body={"api_key": ""})
    assert reply.json["provider"]["key"] == "missing"
    assert "api_keys" not in read_config(tmp_path)


def test_a_key_needs_a_provider(tmp_path: Path) -> None:
    reply = client_for(tmp_path).put("/api/settings", json_body={"api_key": "k"})
    assert reply.status == 400
    assert "Choose a provider" in reply.json["error"]


def test_unknown_providers_are_refused(tmp_path: Path) -> None:
    reply = client_for(tmp_path).put("/api/settings", json_body={"provider": "nope"})
    assert reply.status == 400


def test_owner_name_is_saved_without_touching_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env")  # a key from the environment must not block this
    reply = client_for(tmp_path).put("/api/settings", json_body={"owner_name": "Alex Author"})
    assert reply.status == 200, reply.text
    assert read_config(tmp_path) == {"owner_name": "Alex Author"}


def test_environment_key_cannot_be_overridden_from_the_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "env")
    reply = client_for(tmp_path).put("/api/settings", json_body={"api_key": "x"})
    assert reply.status == 400
    assert "environment variable" in reply.json["error"]


def test_budget_and_embedding_mode_are_saved(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    reply = client.put(
        "/api/settings", json_body={"monthly_budget_usd": 2.5, "embeddings": "off"}
    ).json
    assert reply["budget"] == {"monthly_usd": 2.5, "spent_usd": 0.0}
    assert reply["embeddings"]["mode"] == "off"
    assert client.put("/api/settings", json_body={"monthly_budget_usd": -1}).status == 422


def test_an_old_gemini_config_keeps_working_and_is_migrated(tmp_path: Path) -> None:
    update_config(tmp_path, gemini_api_key="old-key", chat_model="gemini-old")
    client = client_for(tmp_path)
    status = client.get("/api/status").json
    assert status["provider"]["id"] == "gemini"
    assert status["models"]["chat"] == "gemini-old"
    assert status["embeddings"]["mode"] == "provider"  # keeps the index it built

    client.put("/api/settings", json_body={"owner_name": "Alex"})
    assert read_config(tmp_path) == {
        "api_keys": {"gemini": "old-key"},
        "embeddings": "provider",
        "models": {"gemini": {"chat": "gemini-old"}},
        "owner_name": "Alex",
        "provider": "gemini",
    }
    assert client.get("/api/status").json["embeddings"]["mode"] == "provider"


def test_connection_test_lists_models_without_saving(tmp_path: Path) -> None:
    connect = FakeConnect()
    client = client_for(tmp_path, connect=connect)
    reply = client.post(
        "/api/settings/test", json_body={"provider": "openrouter", "api_key": "try-me"}
    )
    assert reply.json == {
        "ok": True,
        "message": "Connected to OpenRouter: 2 models available.",
        "models": ["model-a", "model-b"],
    }
    assert connect.calls[0]["api_key"] == "try-me"
    assert connect.calls[0]["base_url"] == "https://openrouter.ai/api/v1"
    assert read_config(tmp_path) == {}


def test_connection_test_uses_the_saved_key(tmp_path: Path) -> None:
    connect = FakeConnect()
    client = client_for(tmp_path, connect=connect)
    client.put("/api/settings", json_body={"provider": "anthropic", "api_key": "saved"})
    client.post("/api/settings/test", json_body={"provider": "anthropic"})
    assert connect.calls[-1]["api_key"] == "saved"


def test_connection_test_reports_failures_plainly(tmp_path: Path) -> None:
    connect = FakeConnect(error=ProviderAuthError("Anthropic rejected the API key."))
    reply = client_for(tmp_path, connect=connect).post(
        "/api/settings/test", json_body={"provider": "anthropic", "api_key": "bad"}
    )
    assert reply.status == 200
    assert reply.json == {"ok": False, "message": "Anthropic rejected the API key.", "models": []}


def test_ollama_without_models_says_how_to_get_one(tmp_path: Path) -> None:
    reply = client_for(tmp_path, connect=FakeConnect(models=[])).post(
        "/api/settings/test", json_body={"provider": "ollama"}
    )
    assert "ollama pull" in reply.json["message"]


# -- usage and budget ---------------------------------------------------------------------
ANSWER_JSON: dict[str, object] = {
    "title": "Measuring What Matters - Part 3",
    "summary": "How to measure a semantic cache.",
    "topics": ["RAG"],
    "entities": [],
    "series_name": None,
    "series_part": None,
    "body_markdown": "## Metrics\n\nHit rate and precision.",
}


def test_model_calls_are_metered_per_task(tmp_path: Path) -> None:
    update_config(tmp_path, prices={"fake-small": [1.0, 2.0], "fake-chat": [10.0, 20.0]})
    backend = FakeBackend(json_replies={"article": ANSWER_JSON})
    client = client_for(tmp_path, backend=backend)
    article_id = ingest(client)["id"]
    client.post("/api/ask", json_body={"question": "q", "article_id": article_id})

    usage = client.get("/api/usage").json
    by_task = {t["task"]: t for t in usage["by_task"]}
    assert by_task["extraction"]["calls"] == 1
    assert by_task["extraction"]["cost_usd"] == pytest.approx(0.0014)  # 1000 in, 200 out
    assert by_task["chat"]["cost_usd"] == pytest.approx(0.014)
    assert usage["cost_usd"] == pytest.approx(0.0154)
    assert usage["unpriced_calls"] == 0


def test_models_without_a_price_are_counted_but_flagged(tmp_path: Path) -> None:
    backend = FakeBackend(json_replies={"article": ANSWER_JSON})
    client = client_for(tmp_path, backend=backend)
    ingest(client)
    usage = client.get("/api/usage").json
    assert (usage["calls"], usage["unpriced_calls"], usage["cost_usd"]) == (1, 1, 0.0)


def test_the_budget_stops_paid_calls_once_spent(tmp_path: Path) -> None:
    update_config(tmp_path, prices={"fake-chat": [10.0, 20.0]}, monthly_budget_usd=0.01)
    client = client_for(tmp_path, backend=FakeBackend(json_replies={"article": ANSWER_JSON}))
    article_id = ingest(client)["id"]  # the extraction model has no price: costs $0 here
    ask = {"question": "anything", "article_id": article_id}
    first = client.post("/api/ask", json_body=ask)
    second = client.post("/api/ask", json_body=ask)
    assert first.status == 200, first.text  # $0.014 spent, crossing the $0.01 budget
    assert second.status == 402
    assert "monthly budget of $0.01" in second.json["error"]


def test_reindex_rebuilds_the_search_index(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    ingest(client)
    reply = client.post("/api/reindex", json_body={})
    assert reply.status == 200
    assert reply.json["articles"] == 1
    assert reply.json["embedded"] == 0  # unchanged sections reuse their vectors


# -- security -------------------------------------------------------------------------
@pytest.mark.parametrize("host", ["evil.example", "postloom.attacker.net:8765", "10.0.0.5:8765"])
def test_requests_to_other_hostnames_are_refused(tmp_path: Path, host: str) -> None:
    """Defends against DNS rebinding: a hostile domain resolving to 127.0.0.1."""
    client = client_for(tmp_path)
    client.host = host
    assert client.get("/api/status").status == 403


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:8765", "[::1]:8765", "localhost"])
def test_local_hostnames_are_accepted(tmp_path: Path, host: str) -> None:
    client = client_for(tmp_path)
    client.host = host
    assert client.get("/api/status").status == 200


def test_writes_without_the_csrf_header_are_refused(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    client.default_headers = {}
    reply = client.put("/api/settings", json_body={"provider": "gemini", "api_key": "stolen"})
    assert reply.status == 403
    assert read_config(tmp_path) == {}


def test_responses_are_not_cached_or_sniffed(tmp_path: Path) -> None:
    headers = client_for(tmp_path).get("/api/status").headers
    assert headers["cache-control"] == "no-store"
    assert headers["x-content-type-options"] == "nosniff"


# -- people ---------------------------------------------------------------------------
def with_discussion(tmp_path: Path) -> tuple[AsgiClient, str]:
    client = client_for(tmp_path)
    return with_discussion_on(client, ingest(client)["id"])


def with_discussion_on(client: AsgiClient, article_id: str) -> tuple[AsgiClient, str]:
    pasted = fixture_text("comments", "caching_thread.txt")
    preview = client.post(
        "/api/comments/preview", json_body={"article_id": article_id, "text": pasted}
    ).json
    review = [
        {k: v for k, v in m.items() if k not in ("already_saved", "known_person")}
        for m in preview["messages"]
    ]
    client.post("/api/comments", json_body={"article_id": article_id, "messages": review})
    return client, article_id


def test_people_list_and_person_page(tmp_path: Path) -> None:
    client, _ = with_discussion(tmp_path)
    people = client.get("/api/people").json["people"]
    assert [(p["name"], p["messages"]) for p in people] == [("Jane Example", 2), ("John Sample", 1)]
    assert client.get("/api/status").json["people"] == 2

    jane = client.get(f"/api/person?id={people[0]['id']}").json
    assert jane["headlines"][0]["headline"] == "Senior ML Engineer at Acme Analytics"
    (conversation,) = jane["conversations"]
    assert [m["is_own"] for m in conversation["messages"]] == [False, True, False, True]


def test_adding_a_profile_link_returns_the_new_identity(tmp_path: Path) -> None:
    client, _ = with_discussion(tmp_path)
    reply = client.put(
        "/api/person",
        json_body={"id": "person:~jane-example", "profile_url": "linkedin.com/in/jane-example"},
    )
    assert reply.status == 200, reply.text
    assert reply.json == {"id": "person:jane-example"}
    assert client.get("/api/person?id=person:~jane-example").status == 404
    jane = client.get("/api/person?id=person:jane-example").json
    assert jane["profile_url"] == "https://www.linkedin.com/in/jane-example"


def test_person_notes_can_be_saved(tmp_path: Path) -> None:
    client, _ = with_discussion(tmp_path)
    client.put("/api/person", json_body={"id": "person:~john-sample", "notes": "Follow up"})
    assert client.get("/api/person?id=person:~john-sample").json["notes"] == "Follow up"


# -- reply drafts ---------------------------------------------------------------------
def test_draft_a_reply_to_a_comment(tmp_path: Path) -> None:
    chat = FakeChat(reply="Thanks John, invalidation is next.")
    client = client_for(tmp_path, chat=chat)
    article_id = ingest(client)["id"]
    with_discussion_on(client, article_id)
    discussion = client.get(f"/api/article?id={article_id}").json["discussion"]
    john = next(c for c in discussion if c["author_name"] == "John Sample")

    reply = client.post(
        "/api/reply-draft", json_body={"comment_id": john["id"], "guidance": "warmer"}
    )
    assert reply.status == 200, reply.text
    assert reply.json == {
        "comment_id": john["id"],
        "replying_to": "John Sample",
        "text": "Thanks John, invalidation is next.",
        "already_answered": False,
        "model": "llm:fake-chat",
    }
    assert "warmer" in chat.last_prompt


def test_drafting_a_reply_to_your_own_message_is_400(tmp_path: Path) -> None:
    client, article_id = with_discussion(tmp_path)
    discussion = client.get(f"/api/article?id={article_id}").json["discussion"]
    own = next(c for c in discussion if c["is_own"])
    assert client.post("/api/reply-draft", json_body={"comment_id": own["id"]}).status == 400


def test_reply_drafts_need_an_api_key(tmp_path: Path) -> None:
    client = client_for(tmp_path, providers=False)
    reply = client.post("/api/reply-draft", json_body={"comment_id": "comment:x"})
    assert reply.status == 409


# -- links and graph --------------------------------------------------------------------
def test_graph_shows_articles_topics_and_people(tmp_path: Path) -> None:
    client, article_id = with_discussion(tmp_path)
    graph = client.get("/api/graph").json
    kinds = {n["id"]: n["kind"] for n in graph["nodes"]}
    assert kinds[article_id] == "article"
    assert sorted(n["label"] for n in graph["nodes"] if n["kind"] == "person") == [
        "Jane Example",
        "John Sample",
    ]
    assert {link["kind"] for link in graph["links"]} >= {"belongs_to", "discussed"}
    assert all(link["source"] in kinds and link["target"] in kinds for link in graph["links"])


def test_article_detail_lists_related_links(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    article = client.get(f"/api/article?id={ingest(client)['id']}").json
    assert article["related"] == []


def test_reviewing_a_link_to_an_unknown_article_is_400(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    article_id = ingest(client)["id"]
    body = {"article_id": article_id, "other_id": "article:nope", "decision": "accept"}
    reply = client.post("/api/links", json_body=body)
    assert reply.status == 400
    assert "Unknown article" in reply.json["error"]


def test_link_decisions_must_be_accept_or_reject(tmp_path: Path) -> None:
    body = {"article_id": "article:a", "other_id": "article:b", "decision": "maybe"}
    assert client_for(tmp_path).post("/api/links", json_body=body).status == 422


def test_suggesting_links_reports_counts(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    ingest(client)
    reply = client.post("/api/links/suggest", json_body={})
    assert reply.status == 200
    assert reply.json == {"added": 0, "updated": 0, "retired": 0, "semantic": True}


# -- overview ---------------------------------------------------------------------------
def test_overview_lists_messages_waiting_for_a_reply(tmp_path: Path) -> None:
    client, article_id = with_discussion(tmp_path)
    data = client.get("/api/overview").json
    assert (data["articles"], data["messages"], data["people"]) == (1, 5, 2)
    # Jane's two messages were answered; John's comment wasn't.
    assert data["waiting_total"] == 1
    (waiting,) = data["waiting"]
    assert (waiting["author_name"], waiting["article_id"]) == ("John Sample", article_id)
    assert waiting["text"].startswith("Great series")
    assert [p["name"] for p in data["top_people"]] == ["Jane Example", "John Sample"]
    assert data["pending_links"] == 0


# -- curating: edit, delete, topics ------------------------------------------------------
def with_comments(client: AsgiClient) -> str:
    article = ingest(client)["id"]
    preview = client.post(
        "/api/comments/preview", json_body={"article_id": article, "text": "pasted"}
    ).json
    drafts = [
        {k: v for k, v in m.items() if k not in ("already_saved", "known_person")}
        for m in preview["messages"]
    ]
    saved = client.post("/api/comments", json_body={"article_id": article, "messages": drafts})
    assert saved.status == 201, saved.text
    return article


def test_article_details_can_be_fixed(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    article = ingest(client)["id"]
    reply = client.put(
        "/api/article",
        json_body={
            "id": article,
            "title": "Measuring a semantic cache",
            "topics": ["MLOps"],
            "series": None,
            "published_on": "2026-09-30",
        },
    )
    assert reply.status == 200, reply.text
    body = reply.json
    assert body["id"] == article  # the identity doesn't follow the title
    assert (body["title"], body["series"]) == ("Measuring a semantic cache", None)
    assert body["topics"] == [{"name": "MLOps", "grade": "verified"}]
    assert body["published_on"] == "2026-09-30"
    untouched = client.put("/api/article", json_body={"id": article, "summary": "Short."}).json
    assert (untouched["published_on"], untouched["summary"]) == ("2026-09-30", "Short.")
    assert client.put("/api/article", json_body={"id": article, "topics": ["Nope"]}).status == 400
    assert client.put("/api/article", json_body={"id": "article:missing"}).status == 400


def test_an_article_can_be_deleted(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    article = with_comments(client)
    reply = client.delete(f"/api/article?id={article}")
    assert reply.status == 200 and reply.json["deleted"] == article
    assert client.get("/api/articles").json["articles"] == []
    assert client.get(f"/api/article?id={article}").status == 404
    assert client.get("/api/overview").json["messages"] == 0
    assert client.delete(f"/api/article?id={article}").status == 400
    assert client.delete("/api/article").status == 400
    assert not list((tmp_path / "vault" / "articles").glob("*.md"))


def test_a_person_can_be_deleted(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    article = with_comments(client)
    reply = client.delete("/api/person?id=person:~jane-example")
    assert reply.status == 200 and reply.json == {"name": "Jane Example", "comments": 2}
    names = [p["name"] for p in client.get("/api/people").json["people"]]
    assert names == ["John Sample"]
    discussion = client.get(f"/api/article?id={article}").json["discussion"]
    assert "Jane Example" not in {m["author_name"] for m in discussion}
    assert client.delete("/api/person?id=person:~jane-example").status == 400


def test_topics_can_be_managed(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    ingest(client)
    listed = {t["name"]: t for t in client.get("/api/topics").json["topics"]}
    assert listed["RAG"]["articles"] == 1 and listed["RAG"]["description"]

    added = client.post("/api/topics", json_body={"name": "Vector databases"})
    assert added.status == 200
    assert "Vector databases" in {t["name"] for t in added.json["topics"]}
    assert client.post("/api/topics", json_body={"name": "vector databases"}).status == 400
    assert client.post("/api/topics", json_body={"name": ""}).status == 422

    renamed = client.put("/api/topics", json_body={"id": listed["RAG"]["id"], "name": "Retrieval"})
    after = {t["name"]: t for t in renamed.json["topics"]}
    assert "RAG" not in after and after["Retrieval"]["articles"] == 1
    assert "Retrieval" in client.get("/api/status").json["topics"]

    removed = client.delete(f"/api/topics?id={after['Retrieval']['id']}")
    assert "Retrieval" not in {t["name"] for t in removed.json["topics"]}


# -- the vault ---------------------------------------------------------------------------
def test_notes_edited_outside_are_reported_and_read_before_the_next_write(
    tmp_path: Path,
) -> None:
    client = client_for(tmp_path)
    article = ingest(client)["id"]
    assert client.get("/api/status").json["vault_changes"] == 0
    (note,) = (tmp_path / "vault" / "articles").glob("*.md")
    text = note.read_text(encoding="utf-8")
    note.write_text(text.replace("summary: How", "summary: Edited in Obsidian. How"), "utf-8")

    assert client.get("/api/status").json["vault_changes"] == 1
    assert client.get("/api/vault").json["changed"] == [f"articles/{note.name}"]
    # A write on something else must not overwrite the edit: it is read first.
    client.post("/api/topics", json_body={"name": "Vector databases"})
    status = client.get("/api/status").json
    assert status["vault_changes"] == 0 and status["vault_sync"]["reason"] == "updated"
    assert client.get(f"/api/article?id={article}").json["summary"].startswith("Edited in Obsidian")
    assert "Edited in Obsidian" in note.read_text(encoding="utf-8")


def test_the_vault_can_be_read_again_on_request(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    ingest(client)
    (note,) = (tmp_path / "vault" / "articles").glob("*.md")
    original = note.read_text("utf-8")
    note.write_text(original.replace("title: ", "title: [broken "), "utf-8")
    blocked = client.post("/api/vault/sync").json
    assert (blocked["applied"], blocked["reason"]) == (False, "blocked")
    assert blocked["problems"][0]["path"] == f"articles/{note.name}"
    assert client.get("/api/status").json["vault_sync"]["problems"]  # shown until fixed
    note.write_text(original.replace("summary: ", "summary: Fixed. "), "utf-8")
    fixed = client.post("/api/vault/sync").json
    assert fixed["applied"] and fixed["articles"] == 1
    assert client.get("/api/articles").json["articles"][0]["summary"].startswith("Fixed. ")


# -- hardening ---------------------------------------------------------------------------
def test_a_saved_key_is_never_sent_to_another_address(tmp_path: Path) -> None:
    connect = FakeConnect()
    client = client_for(tmp_path, connect=connect)
    client.put("/api/settings", json_body={"provider": "openai", "api_key": "sk-saved"})

    same = client.post("/api/settings/test", json_body={"provider": "openai"}).json
    assert same["ok"] and connect.calls[-1]["api_key"] == "sk-saved"

    elsewhere = {"provider": "openai", "base_url": "https://collector.example/v1"}
    refused = client.post("/api/settings/test", json_body=elsewhere).json
    assert not refused["ok"] and "different server address" in refused["message"]
    assert len(connect.calls) == 1  # nothing was sent anywhere

    typed = client.post("/api/settings/test", json_body={**elsewhere, "api_key": "sk-typed"}).json
    assert typed["ok"] and connect.calls[-1]["api_key"] == "sk-typed"


def test_unexpected_errors_are_reported_as_json(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class Broken(FakeChat):
        def complete(self, system: str, messages: Any) -> str:
            raise RuntimeError("a bug")

    client = client_for(tmp_path, chat=Broken())
    ingest(client)
    reply = client.post("/api/ask", json_body={"question": "How is a cache measured?"})
    assert reply.status == 500
    assert "Something went wrong inside postloom" in reply.json["error"]
    assert "a bug" not in reply.text and "a bug" in caplog.text


def test_oversized_requests_are_refused(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    reply = client.post("/api/topics", raw_body=b"{}", headers={"content-length": "999999999"})
    assert reply.status == 413


def test_refused_requests_carry_the_security_headers_too(tmp_path: Path) -> None:
    reply = client_for(tmp_path).post("/api/reindex", headers={"x-postloom": "0"})
    assert reply.status == 403
    assert "default-src 'self'" in reply.headers["content-security-policy"]


def test_saving_settings_does_not_break_a_request_that_is_still_running(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    state = client.app.state.postloom
    with state.request():
        running = state.container  # a slow request holds this container...
        other = client.put("/api/settings", json_body={"owner_name": "Alex Author"})
        assert other.status == 200  # ...while another request rewires the app
        assert len(running.repository.list_topics()) == len(DEFAULT_TOPICS)  # still open
        assert state.container is running
    assert state.container is not running and state.settings.owner_name == "Alex Author"
    with pytest.raises(Exception, match="closed"):
        running.repository.list_topics()  # released once its last request finished


def test_a_link_that_isnt_a_web_address_is_refused(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    article = ingest(client)["id"]
    reply = client.put("/api/article", json_body={"id": article, "url": "javascript:alert(1)"})
    assert reply.status == 400 and "isn't a web link" in reply.json["error"]
    assert client.get(f"/api/article?id={article}").json["url"] is None


def test_a_body_without_a_declared_length_is_still_limited(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    huge = b'{"name": "' + b"x" * 2_100_000 + b'"}'
    reply = client.post("/api/topics", raw_body=huge, headers={"content-length": ""})
    assert reply.status == 413


def test_the_search_language_can_be_chosen(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    models = client.get("/api/status").json["embeddings"]["local_models"]
    reply = client.put("/api/settings", json_body={"local_embedding_model": models["multilingual"]})
    assert reply.status == 200
    assert client.get("/api/status").json["embeddings"]["local_model"] == models["multilingual"]


STANDALONE = "Why I stopped tuning chunk sizes\n\nMeasure retrieval recall instead.\n\n#RAG"


def test_a_post_can_be_added_opened_edited_and_deleted(tmp_path: Path) -> None:
    client = client_for(tmp_path, providers=False)  # posts don't need a model
    added = client.post("/api/posts", json_body={"text": STANDALONE, "published_on": "2026-10-01"})
    assert added.status == 201, added.text
    body = added.json
    post = body["id"]
    assert (post, body["title"], body["is_update"]) == (
        "post:why-i-stopped-tuning-chunk-sizes",
        "Why I stopped tuning chunk sizes",
        False,
    )
    assert body["topics"] == [] and "No model is connected" in body["warnings"][0]
    listed = client.get("/api/articles").json["articles"]
    assert [(a["id"], a["kind"]) for a in listed] == [(post, "post")]
    detail = client.get(f"/api/article?id={post}").json
    assert (detail["kind"], detail["body_markdown"]) == ("post", STANDALONE)
    assert client.get("/api/overview").json["posts"] == 1

    edited = client.put("/api/post", json_body={"id": post, "topics": ["RAG"]})
    assert edited.status == 200, edited.text
    assert edited.json["topics"] == [{"name": "RAG", "grade": "verified"}]
    assert edited.json["published_on"] == "2026-10-01"  # unsent fields are kept
    cleared = client.put("/api/post", json_body={"id": post, "published_on": None}).json
    assert cleared["published_on"] is None
    bad_link = client.put("/api/post", json_body={"id": post, "url": "javascript:alert(1)"})
    assert bad_link.status == 400

    assert client.delete(f"/api/post?id={post}").json["deleted"] == post
    assert client.get("/api/articles").json["articles"] == []
    assert client.delete(f"/api/post?id={post}").status == 400


def test_comments_can_be_added_to_a_post(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    post = client.post("/api/posts", json_body={"text": STANDALONE}).json["id"]
    preview = client.post(
        "/api/comments/preview", json_body={"article_id": post, "text": "pasted thread"}
    )
    assert preview.status == 200, preview.text
    drafts = [
        {k: v for k, v in m.items() if k not in ("already_saved", "known_person")}
        for m in preview.json["messages"]
    ]
    saved = client.post("/api/comments", json_body={"article_id": post, "messages": drafts})
    assert saved.status == 201, saved.text
    assert len(client.get(f"/api/article?id={post}").json["discussion"]) == 5
    graph = client.get("/api/graph").json
    assert {"id": post, "kind": "post"}.items() <= next(
        n for n in graph["nodes"] if n["id"] == post
    ).items()


def test_an_announcement_post_is_not_added_twice(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    ingest(client)
    reply = client.post("/api/posts", json_body={"text": POST})
    assert reply.status == 400 and "announces the article" in reply.json["error"]


def test_a_connected_model_chooses_a_posts_topics_from_the_list(tmp_path: Path) -> None:
    backend = FakeBackend(json_replies={"post_topics": {"topics": ["RAG", "Knitting"]}})
    client = client_for(tmp_path, backend=backend)
    added = client.post("/api/posts", json_body={"text": STANDALONE})
    assert added.status == 201, added.text
    assert (added.json["topics"], added.json["warnings"]) == (["RAG"], [])
    assert backend.calls[0] == ("json", "fake-small")


def wait_for_download(client: Any) -> dict[str, Any]:
    import time

    for _ in range(100):
        download = client.get("/api/ollama").json["download"]
        if download and download["done"]:
            return download
        time.sleep(0.05)
    raise AssertionError("the download never finished")


def test_ollama_setup_says_when_it_is_missing_or_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from postloom.interfaces.desktop import ollama

    client = client_for(tmp_path)
    nowhere = "http://127.0.0.1:9"
    monkeypatch.setattr(ollama, "installed", lambda: False)
    status = client.get(f"/api/ollama?url={nowhere}").json
    assert (status["installed"], status["running"]) == (False, False)
    assert status["download_page"] == "https://ollama.com/download"
    monkeypatch.setattr(ollama, "installed", lambda: True)
    assert client.get(f"/api/ollama?url={nowhere}").json["installed"] is True
    assert client.get("/api/ollama?url=file:///etc").status == 400


def test_ollama_models_are_suggested_by_memory_and_downloaded_with_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from postloom.interfaces.desktop import ollama
    from tests.fake_ollama import fake_ollama

    monkeypatch.setattr(ollama, "memory_gb", lambda: 16.0)
    client = client_for(tmp_path)
    with fake_ollama(["llama3.2:3b"]) as url:
        client.put("/api/settings", json_body={"provider": "ollama", "base_url": url})
        status = client.get("/api/ollama").json
        assert status["running"] and status["models"] == ["llama3.2:3b"]
        assert status["memory_gb"] == 16
        picked = [s["name"] for s in status["suggestions"] if s["recommended"]]
        assert picked == ["qwen3.5:9b"]

        assert client.post("/api/ollama/pull", json_body={"model": "bad name!"}).status == 400
        started = client.post("/api/ollama/pull", json_body={"model": "qwen3.5:9b"})
        assert started.status == 202
        download = wait_for_download(client)
        assert download["error"] is None and download["completed"] == 100
        suggestions = client.get("/api/ollama").json["suggestions"]
        assert [s["installed"] for s in suggestions] == [False, True, False]


def test_a_failed_ollama_download_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.fake_ollama import fake_ollama

    client = client_for(tmp_path)
    with fake_ollama([], fail="not enough disk space") as url:
        body = {"base_url": url, "model": "qwen3.5:27b"}
        assert client.post("/api/ollama/pull", json_body=body).status == 202
        assert wait_for_download(client)["error"] == "not enough disk space"


def test_quit_is_offered_only_when_postloom_can_stop_itself(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    assert client.get("/api/status").json["can_quit"] is False
    assert client.post("/api/quit", json_body={}).status == 400
