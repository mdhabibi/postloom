"""Pending mention reviews, in the index database (a cache that can be found again)."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from postloom.adapters.storage.database import SqliteDatabase
from postloom.application.ports.reviews import Review, Suggestion, TopicSuggestion
from postloom.domain.graph import NodeId


class SqliteReviewStore:
    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def get(self, item: NodeId) -> Review | None:
        rows = self._database.query("SELECT data FROM mention_reviews WHERE item = ?", (item,))
        return _review(json.loads(rows[0]["data"])) if rows else None

    def put(self, review: Review) -> None:
        data = json.dumps(asdict(review), default=str, ensure_ascii=False)
        with self._database.transaction() as db:
            db.execute(
                "INSERT INTO mention_reviews (item, found_at, data) VALUES (?, ?, ?) "
                "ON CONFLICT(item) DO UPDATE SET found_at = excluded.found_at, "
                "data = excluded.data",
                (review.item, review.found_at.isoformat(), data),
            )

    def remove(self, item: NodeId) -> None:
        with self._database.transaction() as db:
            db.execute("DELETE FROM mention_reviews WHERE item = ?", (item,))

    def pending(self) -> list[Review]:
        rows = self._database.query("SELECT data FROM mention_reviews ORDER BY found_at DESC")
        reviews = [_review(json.loads(r["data"])) for r in rows]
        return [r for r in reviews if not r.is_empty]


class InMemoryReviewStore:
    def __init__(self) -> None:
        self._reviews: dict[NodeId, Review] = {}

    def get(self, item: NodeId) -> Review | None:
        return self._reviews.get(item)

    def put(self, review: Review) -> None:
        self._reviews[review.item] = review

    def remove(self, item: NodeId) -> None:
        self._reviews.pop(item, None)

    def pending(self) -> list[Review]:
        reviews = sorted(self._reviews.values(), key=lambda r: r.found_at, reverse=True)
        return [r for r in reviews if not r.is_empty]


def _review(data: dict[str, Any]) -> Review:
    return Review(
        item=NodeId(data["item"]),
        suggestions=tuple(_suggestion(s) for s in data["suggestions"]),
        topics=tuple(TopicSuggestion(**t) for t in data["topics"]),
        found_at=datetime.fromisoformat(data["found_at"]),
        finder=data.get("finder"),
        dismissed=tuple(data.get("dismissed", ())),
    )


def _suggestion(data: dict[str, Any]) -> Suggestion:
    return Suggestion(
        name=str(data["name"]),
        category=str(data["category"]),
        evidence=str(data.get("evidence") or ""),
        url=data.get("url"),
        match=NodeId(data["match"]) if data.get("match") else None,
        match_name=data.get("match_name"),
        match_note=data.get("match_note"),
    )
