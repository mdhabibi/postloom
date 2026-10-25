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
don't block other requests.
"""

from __future__ import annotations

import mimetypes
import os
import threading
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
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

from postloom import __version__
from postloom.adapters.llm.base import LlmBackend
from postloom.adapters.llm.providers import PROVIDERS, ProviderSpec, build_backend, provider_spec
from postloom.application.errors import (
    ApplicationError,
    BudgetExceededError,
    NotConfiguredError,
    ProviderAuthError,
    ProviderError,
)
from postloom.application.ports.chat import ChatMessage, Role
from postloom.application.use_cases import Decision, IngestArticleCommand
from postloom.bootstrap import Container, Settings
from postloom.config import read_config
from postloom.domain.errors import DomainError
from postloom.domain.graph import NodeId
from postloom.interfaces.web import schemas
from postloom.settings import MODEL_TASKS, save_settings

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


class AppState:
    """Holds the wired container and rebuilds it when settings change."""

    def __init__(self, load_settings: SettingsLoader, make_container: ContainerFactory) -> None:
        self._load_settings = load_settings
        self._make_container = make_container
        self._lock = threading.Lock()
        self._settings: Settings | None = None
        self._container: Container | None = None

    @property
    def settings(self) -> Settings:
        return self._wired()[1]

    @property
    def container(self) -> Container:
        return self._wired()[0]

    def _wired(self) -> tuple[Container, Settings]:
        with self._lock:
            if self._container is None or self._settings is None:
                self._settings = self._load_settings()
                self._container = self._make_container(self._settings)
            return self._container, self._settings

    def reload(self) -> None:
        with self._lock:
            if self._container is not None:
                self._container.close()
            self._container = None
            self._settings = None

    def close(self) -> None:
        with self._lock:
            if self._container is not None:
                self._container.close()
                self._container = None


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
        key = body.api_key or (current.api_key if same else _other_key(current, spec))
        url = body.base_url or (current.base_url if same else None) or spec.base_url
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
        result = state.container.ask_question().execute(
            body.question, article_id=article, history=history
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

    def index_page(request: Request) -> Response:
        return FileResponse(STATIC_DIR / "index.html")

    routes = [
        Route("/", index_page),
        Route("/api/status", _json(status)),
        Route("/api/settings", _json(update_settings, schemas.SettingsUpdate), methods=["PUT"]),
        Route(
            "/api/settings/test",
            _json(test_connection, schemas.ConnectionTest),
            methods=["POST"],
        ),
        Route("/api/usage", _json(usage)),
        Route("/api/reindex", _json(reindex), methods=["POST"]),
        Route("/api/articles", _json(list_articles)),
        Route("/api/articles", _json(ingest, schemas.IngestRequest), methods=["POST"]),
        Route("/api/article", _json(get_article)),
        Route("/api/search", _json(search)),
        Route("/api/ask", _json(ask, schemas.AskRequest), methods=["POST"]),
        Route(
            "/api/comments/preview",
            _json(preview_comments, schemas.CommentsPreviewRequest),
            methods=["POST"],
        ),
        Route("/api/comments", _json(save_comments, schemas.SaveCommentsRequest), methods=["POST"]),
        Route("/api/reply-draft", _json(draft_reply, schemas.ReplyDraftRequest), methods=["POST"]),
        Route("/api/overview", _json(overview)),
        Route("/api/graph", _json(graph)),
        Route("/api/links", _json(review_link, schemas.LinkReviewRequest), methods=["POST"]),
        Route("/api/links/suggest", _json(suggest_links), methods=["POST"]),
        Route("/api/people", _json(list_people)),
        Route("/api/person", _json(get_person)),
        Route("/api/person", _json(update_person, schemas.PersonUpdate), methods=["PUT"]),
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
            return _error(403, "postloom only accepts requests addressed to localhost.")
        if request.method not in ("GET", "HEAD") and request.headers.get(CSRF_HEADER) != "1":
            return _error(403, "Missing X-Postloom header.")
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
    handler: Callable[..., Response], body_model: type[BaseModel] | None = None
) -> Callable[[Request], Awaitable[Response]]:
    """Wrap a sync handler: parse/validate the JSON body, run it in a thread, map errors."""

    async def endpoint(request: Request) -> Response:
        args: list[Any] = [request]
        if body_model is not None:
            try:
                raw = await request.json()
                args.append(body_model.model_validate(raw))
            except ValidationError as error:
                return _error(422, _describe(error))
            except ValueError:
                return _error(400, "The request body must be JSON.")
        try:
            return await run_in_threadpool(handler, *args)
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

    return endpoint


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
