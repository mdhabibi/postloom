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

import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

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
from postloom.application.errors import (
    ApplicationError,
    NotConfiguredError,
    ProviderAuthError,
    ProviderError,
)
from postloom.application.ports.chat import ChatMessage, Role
from postloom.application.use_cases import IngestArticleCommand
from postloom.bootstrap import Container, Settings
from postloom.config import update_config
from postloom.domain.errors import DomainError
from postloom.domain.graph import NodeId
from postloom.interfaces.web import schemas

STATIC_DIR = Path(__file__).parent / "static"
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


def create_app(load_settings: SettingsLoader, make_container: ContainerFactory) -> Starlette:
    state = AppState(load_settings, make_container)

    def status(request: Request) -> Response:
        container, settings = state.container, state.settings
        return JSONResponse(
            {
                "version": __version__,
                "home": str(settings.home),
                "vault": str(settings.vault_dir),
                "api_key": settings.api_key_source,
                "models": {
                    "extraction": settings.extraction_model,
                    "embedding": settings.embedding_model,
                    "chat": settings.chat_model,
                },
                "articles": len(container.repository.list_articles()),
                "topics": [t.name for t in container.repository.list_topics()],
                "features": {
                    "ingest": container.extractor is not None,
                    "semantic_search": container.embedder is not None,
                    "chat": container.chat is not None,
                },
            }
        )

    def update_settings(request: Request, body: schemas.SettingsUpdate) -> Response:
        if state.settings.api_key_source == "environment":
            raise ApplicationError(
                "Your API key comes from the GEMINI_API_KEY environment variable, which "
                "overrides saved settings. Change it there, or unset it to use this screen."
            )
        update_config(state.settings.home, gemini_api_key=body.gemini_api_key or None)
        state.reload()
        return status(request)

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
        try:
            indexed = container.index_article().execute(result.article.id)
            index_error = None
        except ProviderError as error:
            indexed, index_error = None, str(error)
        return JSONResponse(schemas.ingest_result(result, indexed, index_error), status_code=201)

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

    def index_page(request: Request) -> Response:
        return FileResponse(STATIC_DIR / "index.html")

    routes = [
        Route("/", index_page),
        Route("/api/status", _json(status)),
        Route("/api/settings", _json(update_settings, schemas.SettingsUpdate), methods=["PUT"]),
        Route("/api/articles", _json(list_articles)),
        Route("/api/articles", _json(ingest, schemas.IngestRequest), methods=["POST"]),
        Route("/api/article", _json(get_article)),
        Route("/api/search", _json(search)),
        Route("/api/ask", _json(ask, schemas.AskRequest), methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
    ]

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
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
        except ProviderAuthError as error:
            return _error(401, str(error))
        except ProviderError as error:
            return _error(502, str(error))
        except (ApplicationError, DomainError, ValueError) as error:
            return _error(400, str(error))

    return endpoint


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _describe(error: ValidationError) -> str:
    first = error.errors()[0]
    where = ".".join(str(part) for part in first["loc"]) or "body"
    return f"Invalid {where}: {first['msg']}"
