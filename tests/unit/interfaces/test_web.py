"""The web API, exercised in-process through ASGI."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from postloom.application.defaults import DEFAULT_TOPICS
from postloom.bootstrap import Container, Settings, build_container
from postloom.config import read_config
from postloom.interfaces.web.app import create_app
from tests.asgi import AsgiClient
from tests.fakes import FakeChat, FakeEmbedder, FakeExtractor, fixture_text, part3_extraction

ARTICLE = fixture_text("semantic_caching_part3", "article.txt")
POST = fixture_text("semantic_caching_part3", "post.txt")


def client_for(
    tmp_path: Path,
    *,
    providers: bool = True,
    env_key: bool = False,
    chat: FakeChat | None = None,
) -> AsgiClient:
    chat = chat or FakeChat()

    def load() -> Settings:
        saved = read_config(tmp_path).get("gemini_api_key")
        if env_key:
            return Settings(home=tmp_path, gemini_api_key="env", api_key_source="environment")
        return Settings(
            home=tmp_path,
            gemini_api_key=saved,
            api_key_source="config" if saved else "missing",
            min_similarity=0.0,
        )

    def make(settings: Settings) -> Container:
        offline = replace(settings, gemini_api_key=None)  # never call real Gemini in tests
        if not providers:
            container = build_container(offline)
        else:
            container = build_container(
                offline,
                extractor=FakeExtractor(part3_extraction()),
                embedder=FakeEmbedder(),
                chat=chat,
            )
        container.seed_topics().execute(DEFAULT_TOPICS)
        return container

    return AsgiClient(create_app(load, make))


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


def test_status_reports_features_without_leaking_the_key(tmp_path: Path) -> None:
    client = client_for(tmp_path, env_key=True)
    status = client.get("/api/status").json
    assert status["api_key"] == "environment"
    assert status["features"] == {"ingest": True, "semantic_search": True, "chat": True}
    assert status["articles"] == 0
    assert "RAG" in status["topics"]
    assert "env" not in str(status["models"])


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
    assert "API key" in reply.json["error"]


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


# -- settings -------------------------------------------------------------------------
def test_saving_a_key_writes_config_and_reloads(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    assert client.get("/api/status").json["api_key"] == "missing"

    reply = client.put("/api/settings", json_body={"gemini_api_key": "  new-key  "})

    assert reply.status == 200
    assert reply.json["api_key"] == "config"
    assert read_config(tmp_path)["gemini_api_key"] == "new-key"
    assert "new-key" not in reply.text


def test_clearing_the_key_removes_it(tmp_path: Path) -> None:
    client = client_for(tmp_path)
    client.put("/api/settings", json_body={"gemini_api_key": "k"})
    reply = client.put("/api/settings", json_body={"gemini_api_key": ""})
    assert reply.json["api_key"] == "missing"
    assert "gemini_api_key" not in read_config(tmp_path)


def test_environment_key_cannot_be_overridden_from_the_browser(tmp_path: Path) -> None:
    reply = client_for(tmp_path, env_key=True).put(
        "/api/settings", json_body={"gemini_api_key": "x"}
    )
    assert reply.status == 400
    assert "GEMINI_API_KEY" in reply.json["error"]


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
    reply = client.put("/api/settings", json_body={"gemini_api_key": "stolen"})
    assert reply.status == 403
    assert read_config(tmp_path) == {}


def test_responses_are_not_cached_or_sniffed(tmp_path: Path) -> None:
    headers = client_for(tmp_path).get("/api/status").headers
    assert headers["cache-control"] == "no-store"
    assert headers["x-content-type-options"] == "nosniff"
