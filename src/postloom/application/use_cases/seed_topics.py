from __future__ import annotations

from collections.abc import Iterable

from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.vault import Vault
from postloom.domain.content import Topic


class SeedTopics:
    """Create topic nodes (and their vault notes) that do not exist yet. Idempotent."""

    def __init__(self, repository: GraphRepository, vault: Vault) -> None:
        self._repository = repository
        self._vault = vault

    def execute(self, topics: Iterable[Topic]) -> list[Topic]:
        existing = {t.id for t in self._repository.list_topics()}
        created: list[Topic] = []
        for topic in topics:
            if topic.id in existing:
                continue
            self._repository.save_topic(topic)
            self._vault.write_topic(topic)
            existing.add(topic.id)
            created.append(topic)
        return created
