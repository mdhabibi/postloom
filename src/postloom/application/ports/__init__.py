"""Ports: the interfaces use cases depend on. Adapters implement them."""

from postloom.application.ports.chat import ChatMessage, ChatModel, Role
from postloom.application.ports.clock import Clock
from postloom.application.ports.embeddings import DocumentText, EmbeddingProvider, Vector
from postloom.application.ports.extraction import (
    ContentExtractor,
    ExtractedContent,
    ExtractionRequest,
)
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.search_index import ChunkHit, IndexedChunk, SearchIndex
from postloom.application.ports.usage import Task, UsageEntry, UsageLedger
from postloom.application.ports.vault import Vault

__all__ = [
    "ChatMessage",
    "ChatModel",
    "ChunkHit",
    "Clock",
    "ContentExtractor",
    "DocumentText",
    "EmbeddingProvider",
    "ExtractedContent",
    "ExtractionRequest",
    "GraphRepository",
    "IndexedChunk",
    "Role",
    "SearchIndex",
    "Task",
    "UsageEntry",
    "UsageLedger",
    "Vault",
    "Vector",
]
