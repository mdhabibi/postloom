"""Ports: the interfaces use cases depend on. Adapters implement them."""

from postloom.application.ports.clock import Clock
from postloom.application.ports.embeddings import DocumentText, EmbeddingProvider, Vector
from postloom.application.ports.extraction import (
    ContentExtractor,
    ExtractedContent,
    ExtractionRequest,
)
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.search_index import ChunkHit, IndexedChunk, SearchIndex
from postloom.application.ports.vault import Vault

__all__ = [
    "ChunkHit",
    "Clock",
    "ContentExtractor",
    "DocumentText",
    "EmbeddingProvider",
    "ExtractedContent",
    "ExtractionRequest",
    "GraphRepository",
    "IndexedChunk",
    "SearchIndex",
    "Vault",
    "Vector",
]
