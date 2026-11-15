"""The edge journal as a JSON Lines file inside the vault (``.postloom/edges.jsonl``).

One line per edge write, in order. Plain text on purpose: it travels with the vault,
diffs cleanly under version control, and can be read without postloom.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from postloom.adapters.vault.notes import DATA_DIR, atomic_write
from postloom.domain.errors import DomainError
from postloom.domain.graph import Edge, EdgeKind, NodeId
from postloom.domain.provenance import Grade, Origin, Provenance

JOURNAL_NAME = "edges.jsonl"


class FileEdgeJournal:
    def __init__(self, vault_root: Path) -> None:
        self.path = vault_root / DATA_DIR / JOURNAL_NAME
        self._lock = threading.Lock()

    def append(self, edge: Edge) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(_line(edge))

    def read(self) -> Sequence[Edge]:
        with self._lock:
            if not self.path.is_file():
                return []
            text = self.path.read_text(encoding="utf-8")
        edges: list[Edge] = []
        for line in text.splitlines():
            edge = _parse(line)
            if edge is not None:
                edges.append(edge)
        return edges

    def rewrite(self, edges: Sequence[Edge]) -> None:
        with self._lock:
            atomic_write(self.path, "".join(_line(edge) for edge in edges))


class MemoryEdgeJournal:
    """For tests and for running without a vault folder."""

    def __init__(self) -> None:
        self.edges: list[Edge] = []

    def append(self, edge: Edge) -> None:
        self.edges.append(edge)

    def read(self) -> Sequence[Edge]:
        return list(self.edges)

    def rewrite(self, edges: Sequence[Edge]) -> None:
        self.edges = list(edges)


def _line(edge: Edge) -> str:
    p = edge.provenance
    record: dict[str, Any] = {
        "source": edge.source,
        "target": edge.target,
        "kind": edge.kind.value,
        "origin": p.origin.value,
        "grade": p.grade.value,
        "producer": p.producer,
        "recorded_at": p.recorded_at.isoformat(),
    }
    if p.evidence is not None:
        record["evidence"] = p.evidence
    if edge.weight is not None:
        record["weight"] = edge.weight
    if edge.superseded_at is not None:
        record["superseded_at"] = edge.superseded_at.isoformat()
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"


def _parse(line: str) -> Edge | None:
    """An edge, or None for a blank, torn or otherwise unreadable line."""
    if not line.strip():
        return None
    try:
        loaded: object = json.loads(line)
        if not isinstance(loaded, dict):
            return None
        data = cast(dict[str, Any], loaded)
        superseded: str | None = data.get("superseded_at")
        weight: float | None = data.get("weight")
        return Edge(
            source=NodeId(str(data["source"])),
            target=NodeId(str(data["target"])),
            kind=EdgeKind(data["kind"]),
            provenance=Provenance(
                origin=Origin(data["origin"]),
                grade=Grade(data["grade"]),
                producer=str(data["producer"]),
                recorded_at=datetime.fromisoformat(data["recorded_at"]),
                evidence=data.get("evidence"),
            ),
            weight=float(weight) if weight is not None else None,
            superseded_at=datetime.fromisoformat(superseded) if superseded else None,
        )
    except (ValueError, KeyError, TypeError, DomainError):  # torn line, unknown kind...
        return None
