"""Helpers for testing provider backends without a network."""

from __future__ import annotations

from dataclasses import dataclass, field

from postloom.adapters.llm.base import LlmBackend
from postloom.adapters.llm.gateway import LlmGateway
from postloom.adapters.llm.http import HttpResponse, JsonObject
from postloom.adapters.storage.usage import InMemoryUsageLedger
from postloom.application.use_cases.usage import BudgetPolicy, Price, PriceBook
from tests.fakes import FixedClock


@dataclass
class Call:
    method: str
    url: str
    payload: JsonObject
    headers: dict[str, str]


@dataclass
class FakeTransport:
    """Answers requests from a queue and records them."""

    responses: list[HttpResponse | OSError]
    calls: list[Call] = field(default_factory=list[Call])

    def post_json(
        self, url: str, payload: JsonObject, headers: dict[str, str], timeout: float
    ) -> HttpResponse:
        return self._answer(Call("POST", url, payload, headers))

    def get_json(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        return self._answer(Call("GET", url, {}, headers))

    def _answer(self, call: Call) -> HttpResponse:
        self.calls.append(call)
        response = self.responses.pop(0)
        if isinstance(response, OSError):
            raise response
        return response

    @property
    def last(self) -> Call:
        return self.calls[-1]


@dataclass
class Sleeps:
    seconds: list[float] = field(default_factory=list[float])

    def __call__(self, value: float) -> None:
        self.seconds.append(value)


def ok(body: JsonObject) -> HttpResponse:
    return HttpResponse(200, body)


def metered(
    backend: LlmBackend,
    *,
    prices: dict[str, Price] | None = None,
    budget: float | None = None,
) -> tuple[LlmGateway, InMemoryUsageLedger]:
    ledger = InMemoryUsageLedger()
    clock = FixedClock()
    gateway = LlmGateway(
        backend,
        clock=clock,
        ledger=ledger,
        prices=PriceBook(prices or {}),
        budget=BudgetPolicy(ledger, clock, budget),
    )
    return gateway, ledger
