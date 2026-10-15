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
from tests.fakes import (
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
            owner_name=read_config(tmp_path).get("owner_name") or "",
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
                thread_parser=FakeThreadParser(),
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
    assert status["features"] == {
        "ingest": True,
        "semantic_search": True,
        "chat": True,
        "comments": True,
        "reply_drafts": True,
    }
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


def test_owner_name_is_saved_without_touching_the_key(tmp_path: Path) -> None:
    client = client_for(tmp_path, env_key=True)  # key from env must not block this
    reply = client.put("/api/settings", json_body={"owner_name": "Alex Author"})
    assert reply.status == 200, reply.text
    assert read_config(tmp_path) == {"owner_name": "Alex Author"}


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
