"""Ports: the interfaces use cases depend on. Adapters implement them."""

from postloom.application.ports.clock import Clock
from postloom.application.ports.extraction import (
    ContentExtractor,
    ExtractedContent,
    ExtractionRequest,
)
from postloom.application.ports.repository import GraphRepository
from postloom.application.ports.vault import Vault

__all__ = [
    "Clock",
    "ContentExtractor",
    "ExtractedContent",
    "ExtractionRequest",
    "GraphRepository",
    "Vault",
]
