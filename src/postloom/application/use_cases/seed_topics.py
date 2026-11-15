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

    def execute(self, topics: Iterable[Topic], *, only_when_empty: bool = False) -> list[Topic]:
        """Create the topics that are missing.

        With ``only_when_empty``, do nothing once the author has any topics: the defaults
        are a starting point, and one the author removed must not come back on restart.
        """
        existing = {t.id for t in self._repository.list_topics()}
        if only_when_empty and existing:
            return []
        created: list[Topic] = []
        for topic in topics:
            if topic.id in existing:
                continue
            self._repository.save_topic(topic)
            self._vault.write_topic(topic)
            existing.add(topic.id)
            created.append(topic)
        return created
