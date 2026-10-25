"""UsageLedger adapters: SQLite (in index.db) and in-memory (tests, no-disk setups)."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from postloom.adapters.storage.database import SqliteDatabase
from postloom.application.ports.usage import Task, UsageEntry, month_of


class SqliteUsageLedger:
    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def record(
        self,
        *,
        at: datetime,
        provider: str,
        model: str,
        task: Task,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float | None,
    ) -> None:
        with self._database.transaction() as db:
            db.execute(
                "INSERT INTO usage (month, provider, model, task, calls, input_tokens, "
                "output_tokens, cost_usd, unpriced_calls) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?) "
                "ON CONFLICT (month, provider, model, task) DO UPDATE SET "
                "calls = calls + 1, input_tokens = input_tokens + excluded.input_tokens, "
                "output_tokens = output_tokens + excluded.output_tokens, "
                "cost_usd = cost_usd + excluded.cost_usd, "
                "unpriced_calls = unpriced_calls + excluded.unpriced_calls",
                (
                    month_of(at),
                    provider,
                    model,
                    task.value,
                    max(input_tokens, 0),
                    max(output_tokens, 0),
                    max(cost_usd or 0.0, 0.0),
                    1 if cost_usd is None else 0,
                ),
            )

    def month(self, month: str) -> Sequence[UsageEntry]:
        rows = self._database.query(
            "SELECT * FROM usage WHERE month = ? ORDER BY provider, model, task", (month,)
        )
        return [
            UsageEntry(
                month=row["month"],
                provider=row["provider"],
                model=row["model"],
                task=Task(row["task"]),
                calls=int(row["calls"]),
                input_tokens=int(row["input_tokens"]),
                output_tokens=int(row["output_tokens"]),
                cost_usd=float(row["cost_usd"]),
                unpriced_calls=int(row["unpriced_calls"]),
            )
            for row in rows
        ]


class InMemoryUsageLedger:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, str, Task], UsageEntry] = {}
        self._lock = threading.Lock()

    def record(
        self,
        *,
        at: datetime,
        provider: str,
        model: str,
        task: Task,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float | None,
    ) -> None:
        key = (month_of(at), provider, model, task)
        with self._lock:
            old = self._entries.get(key) or UsageEntry(*key, 0, 0, 0, 0.0, 0)
            self._entries[key] = replace(
                old,
                calls=old.calls + 1,
                input_tokens=old.input_tokens + max(input_tokens, 0),
                output_tokens=old.output_tokens + max(output_tokens, 0),
                cost_usd=old.cost_usd + max(cost_usd or 0.0, 0.0),
                unpriced_calls=old.unpriced_calls + (1 if cost_usd is None else 0),
            )

    def month(self, month: str) -> Sequence[UsageEntry]:
        with self._lock:
            entries = [e for e in self._entries.values() if e.month == month]
        return sorted(entries, key=lambda e: (e.provider, e.model, e.task.value))
