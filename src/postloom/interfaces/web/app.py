"""The local web app: a JSON API plus a static single-page frontend.

Security model (the server only ever listens on 127.0.0.1):
- **DNS rebinding**: requests whose Host header isn't localhost are refused, so a website
  that points its own domain at 127.0.0.1 can't talk to postloom.
- **CSRF**: every state-changing request must carry ``X-Postloom: 1``. Browsers won't let
  another site add a custom header to a cross-origin request without a CORS preflight,
  and postloom answers no preflights, so other sites can't trigger ingests (which cost
  API credits) or change settings.
- The API key is never sent back to the browser; the status endpoint only says whether
  one is configured and where it came from.

Handlers are plain functions: Starlette runs them in a thread pool, so slow model calls
don't block other requests. Each request borrows the wired container for its whole
duration, so saving settings (which rewires the app) never closes a database under a
request that is still running.

The vault can be edited outside postloom while the app is open. Before any request that
writes, edited notes are read first, so the app never overwrites an edit it hasn't seen.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import threading
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from postloom import __version__, how_to_run
from postloom.adapters.llm.base import LlmBackend
from postloom.adapters.llm.local_embeddings import DEFAULT_LOCAL_MODEL, MULTILINGUAL_LOCAL_MODEL
from postloom.adapters.llm.providers import PROVIDERS, ProviderSpec, build_backend, provider_spec
from postloom.application.errors import (
    ApplicationError,
    BudgetExceededError,
    NotConfiguredError,
    ProviderAuthError,
    ProviderError,
)
from postloom.application.ports.chat import ChatMessage, Role
from postloom.application.use_cases import UNSET, Decision, IngestArticleCommand, SyncReport
from postloom.bootstrap import Container, Settings
from postloom.config import read_config
from postloom.domain.errors import DomainError
from postloom.domain.graph import NodeId
from postloom.domain.text import canonical_url
from postloom.interfaces.web import schemas
from postloom.settings import MODEL_TASKS, save_settings

log = logging.getLogger("postloom.web")
MAX_BODY_BYTES = 2_000_000
"""Far above the largest article; stops a runaway request from filling memory."""

STATIC_DIR = Path(__file__).parent / "static"
mimetypes.add_type("font/woff2", ".woff2")  # missing from some platforms' tables
CSRF_HEADER = "x-postloom"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})
# Everything is served by postloom itself; no inline scripts, nothing from the internet.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'"
)

SettingsLoader = Callable[[], Settings]
ContainerFactory = Callable[[Settings], Container]


@dataclass
class _Wiring:
    """One wired container and how many running requests are using it."""

    container: Container
    settings: Settings
    users: int = 0
    retired: bool = False
    """Replaced by newer settings: close it once the last request using it finishes."""


class AppState:
    """Holds the wired container and rebuilds it when settings change."""

    def __init__(self, load_settings: SettingsLoader, make_container: ContainerFactory) -> None:
        self._load_settings = load_settings
        self._make_container = make_container
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._wiring: _Wiring | None = None
        self._borrowed = threading.local()
        self._report: SyncReport | None = None

    @property
    def settings(self) -> Settings:
        return self._wired().settings

    @property
    def container(self) -> Container:
        return self._wired().container

    @property
    def vault_report(self) -> SyncReport | None:
        """What the last sync with the vault did, if there was one."""
        self._wired()
        return self._report

    @contextmanager
    def request(self) -> Generator[None, None, None]:
        """Borrow the current wiring for one request, on the thread that handles it."""
        with self._lock:
            wiring = self._current()
            wiring.users += 1
        self._borrowed.wiring = wiring
        try:
            yield
        finally:
            self._release(self._borrowed.wiring)
            self._borrowed.wiring = None

    def reload(self) -> None:
        """Rewire with fresh settings. Requests still running keep the wiring they have."""
        with self._lock:
            old, self._wiring = self._wiring, None
            if old is not None:
                old.retired = True
                if old.users == 0:
                    old.container.close()
            mine: _Wiring | None = getattr(self._borrowed, "wiring", None)
            if mine is not None and mine is old:
                # The request that changed the settings sees their effect straight away.
                self._release(mine)
                fresh = self._current()
                fresh.users += 1
                self._borrowed.wiring = fresh

    def sync_if_changed(self) -> SyncReport | None:
        """Read notes that were edited outside postloom, if any were."""
        with self._sync_lock:
            container = self.container
            if not container.vault.changes():
                return None
            self._report = container.sync_vault().execute()
            return self._report

    def sync(self) -> SyncReport:
        with self._sync_lock:
            self._report = self.container.sync_vault().execute()
            return self._report

    def close(self) -> None:
        with self._lock:
            if self._wiring is not None:
                self._wiring.container.close()
                self._wiring = None

    def _wired(self) -> _Wiring:
        mine: _Wiring | None = getattr(self._borrowed, "wiring", None)
        if mine is not None:
            return mine
        with self._lock:
            return self._current()

    def _current(self) -> _Wiring:
        if self._wiring is None:
            settings = self._load_settings()
            container = self._make_container(settings)
            self._wiring = _Wiring(container, settings)
            if container.vault_report is not None:
                self._report = container.vault_report
        return self._wiring

    def _release(self, wiring: _Wiring) -> None:
        with self._lock:
            wiring.users -= 1
            if wiring.retired and wiring.users == 0:
                wiring.container.close()


BackendFactory = Callable[..., LlmBackend]


def create_app(
    load_settings: SettingsLoader,
    make_container: ContainerFactory,
    *,
    connect: BackendFactory = build_backend,
) -> Starlette:
    """``connect`` builds a backend for "Test connection"; tests pass a fake one."""
    state = AppState(load_settings, make_container)

    def status(request: Request) -> Response:
        container, settings = state.container, state.settings
        spec = settings.spec
        index_spaces = container.search_index.vector_spaces()
        articles = len(container.repository.list_articles())
        space = container.embedder.name if container.embedder else ""
        spent = container.usage().execute().cost_usd if container.usage_ledger else 0.0
        return JSONResponse(
            {
                "version": __version__,
                "home": str(settings.home),
                "vault": str(settings.vault_dir),
                "owner_name": settings.owner_name,
                "provider": None
                if spec is None
                else {
                    "id": spec.id,
                    "label": spec.label,
                    "configured": settings.configured,
                    "key": settings.api_key_source,
                    "base_url": settings.base_url,
                    "local": spec.local,
                },
                "providers": [schemas.provider_spec(p) for p in PROVIDERS.values()],
                "models": {task: settings.model(task) for task in MODEL_TASKS},
                "embeddings": {
                    "mode": settings.embeddings,
                    "space": space,
                    "local_model": settings.local_embedding_model,
                    "local_models": {
                        "english": DEFAULT_LOCAL_MODEL,
                        "multilingual": MULTILINGUAL_LOCAL_MODEL,
                    },
                    "available": container.embedder is not None,
                    "needs_reindex": bool(
                        container.embedder is not None and articles and not index_spaces.get(space)
                    ),
                },
                "budget": {"monthly_usd": settings.monthly_budget_usd, "spent_usd": spent},
                "ollama_context": settings.ollama_context,
                "locked": sorted(settings.locked),
                "articles": articles,
                "people": len(container.repository.list_people()),
                "topics": [t.name for t in container.repository.list_topics()],
                "vault_changes": container.vault.changes().count,
                "start_command": how_to_run("start"),
                "vault_sync": schemas.sync_report(state.vault_report),
                "features": {
                    "ingest": container.extractor is not None,
                    "semantic_search": container.embedder is not None,
                    "chat": container.chat is not None,
                    "comments": container.thread_parser is not None,
                    "reply_drafts": (container.reply_chat or container.chat) is not None,
                },
            }
        )

    def update_settings(request: Request, body: schemas.SettingsUpdate) -> Response:
        changes = {name: getattr(body, name) for name in body.model_fields_set}
        try:
            save_settings(state.settings.home, **changes)
        except ValueError as error:
            raise ApplicationError(str(error)) from error
        state.reload()
        return status(request)

    def test_connection(request: Request, body: schemas.ConnectionTest) -> Response:
        current = state.settings
        spec = provider_spec(body.provider)
        same = current.provider == spec.id
        saved_url = (current.base_url if same else _saved_url(current, spec)) or spec.base_url
        url = body.base_url or saved_url
        key = body.api_key
        if not key and _same_address(url, saved_url):
            # A saved key is only ever sent to the address it was saved for.
            key = current.api_key if same else _other_key(current, spec)
        if not key and spec.needs_key:
            hint = (
                "Enter the API key to test a different server address."
                if not _same_address(url, saved_url)
                else f"Enter your {spec.label} API key first."
            )
            return JSONResponse({"ok": False, "message": hint, "models": []})
        try:
            backend = connect(
                spec.id, api_key=key, base_url=url, ollama_context=current.ollama_context
            )
            models = backend.list_models()
        except (ProviderError, NotConfiguredError) as error:
            return JSONResponse({"ok": False, "message": str(error), "models": []})
        label = "model" if len(models) == 1 else "models"
        message = (
            f"Connected to {spec.label}: {len(models)} {label} available."
            if models
            else f"Connected to {spec.label}."
        )
        if spec.local and not models:
            message = f"{spec.label} is running but has no models yet. Run `ollama pull <model>`."
        return JSONResponse({"ok": True, "message": message, "models": models})

    def usage(request: Request) -> Response:
        month = request.query_params.get("month") or None
        return JSONResponse(schemas.usage_summary(state.container.usage().execute(month)))

    def reindex(request: Request) -> Response:
        container = state.container
        result = container.reindex_all().execute()
        links = container.suggest_links().execute()
        return JSONResponse(
            {
                "articles": result.articles,
                "chunks": result.chunks,
                "embedded": result.embedded,
                "reused": result.reused,
                "suggested_links": links.added,
            }
        )

    def list_articles(request: Request) -> Response:
        articles = state.container.browse().list_articles()
        return JSONResponse({"articles": [schemas.article_summary(a) for a in articles]})

    def get_article(request: Request) -> Response:
        article_id = request.query_params.get("id", "")
        detail = state.container.browse().get_article(NodeId(article_id))
        if detail is None:
            return _error(404, "Article not found.")
        return JSONResponse(schemas.article_detail(detail))

    def ingest(request: Request, body: schemas.IngestRequest) -> Response:
        container = state.container
        command = IngestArticleCommand(
            article_text=body.article_text,
            post_text=body.post_text,
            article_url=body.article_url or None,
            post_url=body.post_url or None,
            published_on=body.published_on,
        )
        result = container.ingest_article().execute(command)
        suggested = 0
        try:
            indexed = container.index_article().execute(result.article.id)
            index_error = None
        except (ProviderError, BudgetExceededError) as error:
            indexed, index_error = None, str(error)
        else:
            suggested = container.suggest_links().execute().added
        view = schemas.ingest_result(result, indexed, index_error, suggested)
        return JSONResponse(view, status_code=201)

    def search(request: Request) -> Response:
        query = request.query_params.get("q", "")
        limit = min(max(int(request.query_params.get("limit", "10") or 10), 1), 50)
        found = state.container.search().execute(query, limit=limit)
        return JSONResponse(schemas.search_results(found))

    def ask(request: Request, body: schemas.AskRequest) -> Response:
        history = [ChatMessage(Role(m.role), m.text) for m in body.history]
        article = NodeId(body.article_id) if body.article_id else None
        person = NodeId(body.person_id) if body.person_id else None
        result = state.container.ask_question().execute(
            body.question, article_id=article, person_id=person, history=history
        )
        return JSONResponse(schemas.answer(result))

    def preview_comments(request: Request, body: schemas.CommentsPreviewRequest) -> Response:
        owner = state.settings.owner_name or None
        preview = state.container.preview_comments().execute(
            NodeId(body.article_id), body.text, owner
        )
        return JSONResponse(schemas.comments_preview(preview))

    def save_comments(request: Request, body: schemas.SaveCommentsRequest) -> Response:
        drafts = [m.to_draft() for m in body.messages]
        result = state.container.save_comments().execute(NodeId(body.article_id), drafts)
        return JSONResponse(schemas.comments_saved(result), status_code=201)

    def draft_reply(request: Request, body: schemas.ReplyDraftRequest) -> Response:
        draft = state.container.draft_reply().execute(
            NodeId(body.comment_id), guidance=body.guidance
        )
        return JSONResponse(schemas.reply_draft(draft))

    def overview(request: Request) -> Response:
        return JSONResponse(schemas.overview(state.container.overview().execute()))

    def graph(request: Request) -> Response:
        return JSONResponse(schemas.graph_data(state.container.graph().execute()))

    def review_link(request: Request, body: schemas.LinkReviewRequest) -> Response:
        link = state.container.review_link().execute(
            NodeId(body.article_id), NodeId(body.other_id), Decision(body.decision)
        )
        return JSONResponse(schemas.related_link(link))

    def suggest_links(request: Request) -> Response:
        result = state.container.suggest_links().execute()
        return JSONResponse(schemas.suggest_result(result))

    def list_people(request: Request) -> Response:
        people = state.container.people().list_people()
        return JSONResponse({"people": [schemas.person_summary(p) for p in people]})

    def get_person(request: Request) -> Response:
        person_id = request.query_params.get("id", "")
        detail = state.container.people().get_person(NodeId(person_id))
        if detail is None:
            return _error(404, "Person not found.")
        return JSONResponse(schemas.person_detail(detail))

    def update_person(request: Request, body: schemas.PersonUpdate) -> Response:
        new_id = state.container.update_person().execute(
            NodeId(body.id), profile_url=body.profile_url, notes=body.notes, tags=body.tags
        )
        return JSONResponse({"id": new_id})

    def update_article(request: Request, body: schemas.ArticleUpdate) -> Response:
        sent = body.model_fields_set
        container = state.container
        article = container.update_article().execute(
            NodeId(body.id),
            title=body.title,
            summary=body.summary,
            topics=body.topics,
            series=body.series if "series" in sent else UNSET,
            series_part=body.series_part if "series_part" in sent else UNSET,
            url=body.url if "url" in sent else UNSET,
            published_on=body.published_on if "published_on" in sent else UNSET,
        )
        detail = container.browse().get_article(article.id)
        assert detail is not None
        return JSONResponse(schemas.article_detail(detail))

    def delete_article(request: Request) -> Response:
        article = state.container.delete_article().execute(NodeId(_id(request)))
        return JSONResponse({"deleted": article.id, "title": article.title})

    def delete_person(request: Request) -> Response:
        deleted = state.container.delete_person().execute(NodeId(_id(request)))
        return JSONResponse({"name": deleted.name, "comments": deleted.comments})

    def list_topics(request: Request) -> Response:
        topics = state.container.topics().list()
        return JSONResponse({"topics": [schemas.topic_usage(t) for t in topics]})

    def add_topic(request: Request, body: schemas.TopicCreate) -> Response:
        state.container.topics().add(body.name, body.description)
        return list_topics(request)

    def update_topic(request: Request, body: schemas.TopicUpdate) -> Response:
        state.container.topics().update(
            NodeId(body.id), name=body.name, description=body.description
        )
        return list_topics(request)

    def delete_topic(request: Request) -> Response:
        state.container.topics().delete(NodeId(_id(request)))
        return list_topics(request)

    def vault(request: Request) -> Response:
        container = state.container
        changes = container.vault.changes()
        return JSONResponse(
            {
                "path": str(state.settings.vault_dir),
                "changed": [*changes.added, *changes.modified, *changes.removed],
                "last_sync": schemas.sync_report(state.vault_report),
            }
        )

    def sync_vault(request: Request) -> Response:
        return JSONResponse(schemas.sync_report(state.sync()))

    def index_page(request: Request) -> Response:
        return FileResponse(STATIC_DIR / "index.html")

    def api(
        handler: Callable[..., Response],
        body_model: type[BaseModel] | None = None,
        *,
        reads_vault: bool = True,
    ) -> Callable[[Request], Awaitable[Response]]:
        return _json(state, handler, body_model, reads_vault=reads_vault)

    routes = [
        Route("/", index_page),
        Route("/api/status", api(status)),
        Route(
            "/api/settings",
            api(update_settings, schemas.SettingsUpdate, reads_vault=False),
            methods=["PUT"],
        ),
        Route(
            "/api/settings/test",
            api(test_connection, schemas.ConnectionTest, reads_vault=False),
            methods=["POST"],
        ),
        Route("/api/usage", api(usage)),
        Route("/api/reindex", api(reindex), methods=["POST"]),
        Route("/api/articles", api(list_articles)),
        Route("/api/articles", api(ingest, schemas.IngestRequest), methods=["POST"]),
        Route("/api/article", api(get_article)),
        Route("/api/article", api(update_article, schemas.ArticleUpdate), methods=["PUT"]),
        Route("/api/article", api(delete_article), methods=["DELETE"]),
        Route("/api/search", api(search)),
        Route("/api/ask", api(ask, schemas.AskRequest), methods=["POST"]),
        Route(
            "/api/comments/preview",
            api(preview_comments, schemas.CommentsPreviewRequest),
            methods=["POST"],
        ),
        Route("/api/comments", api(save_comments, schemas.SaveCommentsRequest), methods=["POST"]),
        Route("/api/reply-draft", api(draft_reply, schemas.ReplyDraftRequest), methods=["POST"]),
        Route("/api/overview", api(overview)),
        Route("/api/graph", api(graph)),
        Route("/api/links", api(review_link, schemas.LinkReviewRequest), methods=["POST"]),
        Route("/api/links/suggest", api(suggest_links), methods=["POST"]),
        Route("/api/people", api(list_people)),
        Route("/api/person", api(get_person)),
        Route("/api/person", api(update_person, schemas.PersonUpdate), methods=["PUT"]),
        Route("/api/person", api(delete_person), methods=["DELETE"]),
        Route("/api/topics", api(list_topics)),
        Route("/api/topics", api(add_topic, schemas.TopicCreate), methods=["POST"]),
        Route("/api/topics", api(update_topic, schemas.TopicUpdate), methods=["PUT"]),
        Route("/api/topics", api(delete_topic), methods=["DELETE"]),
        Route("/api/vault", api(vault)),
        Route("/api/vault/sync", api(sync_vault, reads_vault=False), methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
    ]

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        yield
        state.close()

    app = Starlette(routes=routes, middleware=[Middleware(LocalOnlyMiddleware)], lifespan=lifespan)
    app.state.postloom = state
    return app


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if _hostname(request.headers.get("host") or "") not in LOCAL_HOSTS:
            response: Response = _error(
                403, "postloom only accepts requests addressed to localhost."
            )
        elif request.method not in ("GET", "HEAD") and request.headers.get(CSRF_HEADER) != "1":
            response = _error(403, "Missing X-Postloom header.")
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = CSP
        return response


# -- plumbing -----------------------------------------------------------------------
def _hostname(host: str) -> str:
    """'localhost:8765' -> 'localhost', '[::1]:8765' -> '[::1]'."""
    host = host.strip().lower()
    if host.startswith("["):
        return host.split("]", 1)[0] + "]"
    return host.rsplit(":", 1)[0]


def _json(
    state: AppState,
    handler: Callable[..., Response],
    body_model: type[BaseModel] | None = None,
    *,
    reads_vault: bool = True,
) -> Callable[[Request], Awaitable[Response]]:
    """Wrap a sync handler: parse/validate the JSON body, run it in a thread, map errors.

    A request that writes first reads any notes edited outside postloom (``reads_vault``),
    so it works on what the vault says now.
    """

    def run(request: Request, args: list[Any]) -> Response:
        with state.request():
            if reads_vault and request.method not in ("GET", "HEAD"):
                state.sync_if_changed()
            return handler(*args)

    async def endpoint(request: Request) -> Response:
        args: list[Any] = [request]
        if body_model is not None:
            if _content_length(request) > MAX_BODY_BYTES:
                return _error(413, TOO_LARGE)
            try:
                raw = await _read_json(request)
                args.append(body_model.model_validate(raw))
            except _TooLarge:
                return _error(413, TOO_LARGE)
            except ValidationError as error:
                return _error(422, _describe(error))
            except ValueError:
                return _error(400, "The request body must be JSON.")
        try:
            return await run_in_threadpool(run, request, args)
        except NotConfiguredError as error:
            return _error(409, str(error))
        except BudgetExceededError as error:
            return _error(402, str(error))
        except ProviderAuthError as error:
            return _error(401, str(error))
        except ProviderError as error:
            return _error(502, str(error))
        except (ApplicationError, DomainError, ValueError) as error:
            return _error(400, str(error))
        except Exception:
            # A bug, not something the user did. Say so plainly and keep the details in
            # the terminal, where they can be copied into a report.
            log.exception("Unexpected error in %s %s", request.method, request.url.path)
            return _error(
                500,
                "Something went wrong inside postloom. The terminal it runs in has the details.",
            )

    return endpoint


TOO_LARGE = "That is too much text for one request."


class _TooLarge(Exception):
    pass


async def _read_json(request: Request) -> object:
    """The JSON body, read with a size limit even when no length was declared."""
    received = bytearray()
    async for chunk in request.stream():
        received += chunk
        if len(received) > MAX_BODY_BYTES:
            raise _TooLarge
    return json.loads(received or b"null")


def _id(request: Request) -> str:
    value = request.query_params.get("id", "")
    if not value:
        raise ApplicationError("Missing id.")
    return value


def _content_length(request: Request) -> int:
    try:
        return int(request.headers.get("content-length") or 0)
    except ValueError:
        return 0


def _same_address(first: str | None, second: str | None) -> bool:
    return canonical_url(first or "") == canonical_url(second or "")


def _saved_url(settings: Settings, spec: ProviderSpec) -> str | None:
    """The address saved for a provider other than the current one."""
    urls: object = read_config(settings.home).get("base_urls")
    value = cast(dict[str, object], urls).get(spec.id) if isinstance(urls, dict) else None
    return value if isinstance(value, str) and value else None


def _other_key(settings: Settings, spec: ProviderSpec) -> str | None:
    """The key for a provider other than the current one, to test a switch before saving."""
    for name in spec.key_envs:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    keys: object = read_config(settings.home).get("api_keys")
    value = cast(dict[str, object], keys).get(spec.id) if isinstance(keys, dict) else None
    return value if isinstance(value, str) and value else None


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _describe(error: ValidationError) -> str:
    first = error.errors()[0]
    where = ".".join(str(part) for part in first["loc"]) or "body"
    return f"Invalid {where}: {first['msg']}"
