"""Ports: the interfaces use cases depend on. Adapters implement them."""

from postloom.application.ports.chat import ChatMessage, ChatModel, Role
from postloom.application.ports.clock import Clock
from postloom.application.ports.embeddings import DocumentText, EmbeddingProvider, Vector
from postloom.application.ports.extraction import (
    ContentExtractor,
    ExtractedContent,
    ExtractionRequest,
)
from postloom.application.ports.journal import EdgeJournal
from postloom.application.ports.repository import GraphContents, GraphRepository
from postloom.application.ports.search_index import ChunkHit, IndexedChunk, SearchIndex
from postloom.application.ports.usage import Task, UsageEntry, UsageLedger
from postloom.application.ports.vault import (
    ArticleNote,
    NoteProblem,
    NoteStamps,
    PostNote,
    Vault,
    VaultChanges,
    VaultSnapshot,
)

__all__ = [
    "ArticleNote",
    "ChatMessage",
    "ChatModel",
    "ChunkHit",
    "Clock",
    "ContentExtractor",
    "DocumentText",
    "EdgeJournal",
    "EmbeddingProvider",
    "ExtractedContent",
    "ExtractionRequest",
    "GraphContents",
    "GraphRepository",
    "IndexedChunk",
    "NoteProblem",
    "NoteStamps",
    "PostNote",
    "Role",
    "SearchIndex",
    "Task",
    "UsageEntry",
    "UsageLedger",
    "Vault",
    "VaultChanges",
    "VaultSnapshot",
    "Vector",
]
