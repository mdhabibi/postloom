"""LlmGateway: every model call goes through here, so none escapes metering or the budget.

The provider-neutral adapters (extractor, thread parser, chat, embeddings) depend on the
gateway, never on a backend directly. The gateway

1. refuses paid calls once the monthly budget is spent,
2. calls the backend,
3. records tokens and cost for the call's task in the usage ledger.

Calls to models running on this computer are recorded too (tokens are interesting) but
cost nothing and are never blocked by the budget.
"""

from __future__ import annotations

from collections.abc import Sequence

from postloom.adapters.llm.base import (
    Effort,
    EmbeddingKind,
    LlmBackend,
    Turn,
    Usage,
)
from postloom.adapters.llm.http import JsonObject
from postloom.application.ports.clock import Clock
from postloom.application.ports.usage import Task, UsageLedger
from postloom.application.use_cases.usage import BudgetPolicy, PriceBook


class LlmGateway:
    def __init__(
        self,
        backend: LlmBackend,
        *,
        clock: Clock,
        ledger: UsageLedger | None = None,
        prices: PriceBook | None = None,
        budget: BudgetPolicy | None = None,
    ) -> None:
        self.backend = backend
        self._clock = clock
        self._ledger = ledger
        self._prices = prices or PriceBook({})
        self._budget = budget

    @property
    def provider(self) -> str:
        return self.backend.provider

    def json(
        self,
        task: Task,
        model: str,
        *,
        system: str,
        prompt: str,
        schema: JsonObject,
        schema_name: str,
        temperature: float,
        max_output_tokens: int,
        effort: Effort = "low",
    ) -> JsonObject:
        self._check_budget()
        reply = self.backend.complete_json(
            model,
            system=system,
            prompt=prompt,
            schema=schema,
            schema_name=schema_name,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            effort=effort,
        )
        self._record(task, model, reply.usage)
        return reply.data

    def text(
        self,
        task: Task,
        model: str,
        *,
        system: str,
        turns: Sequence[Turn],
        temperature: float,
        max_output_tokens: int,
        effort: Effort = "low",
    ) -> str:
        self._check_budget()
        reply = self.backend.complete_text(
            model,
            system=system,
            turns=turns,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            effort=effort,
        )
        self._record(task, model, reply.usage)
        return reply.text

    def embed(
        self, model: str, texts: Sequence[str], *, kind: EmbeddingKind, dimensions: int | None
    ) -> list[list[float]]:
        self._check_budget()
        reply = self.backend.embed(model, texts, kind=kind, dimensions=dimensions)
        self._record(Task.EMBEDDINGS, model, reply.usage)
        return reply.vectors

    # -- metering -----------------------------------------------------------------
    def _check_budget(self) -> None:
        if self._budget is not None and not self.backend.free:
            self._budget.check()

    def _record(self, task: Task, model: str, usage: Usage) -> None:
        if self._ledger is None:
            return
        if self.backend.free:
            cost: float | None = 0.0
        elif usage.cost_usd is not None:
            cost = usage.cost_usd
        else:
            cost = self._prices.cost(model, usage.input_tokens, usage.output_tokens)
        self._ledger.record(
            at=self._clock.now(),
            provider=self.backend.provider,
            model=model,
            task=task,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost,
        )
