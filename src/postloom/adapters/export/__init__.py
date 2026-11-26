"""Formats the graph can be exported in."""

from __future__ import annotations

from postloom.adapters.export.cypher import CypherFormat
from postloom.adapters.export.graphml import GraphMLFormat
from postloom.adapters.export.rdf import JsonLdFormat, TurtleFormat
from postloom.application.ports.graph_export import GraphFormat


def graph_formats() -> tuple[GraphFormat, ...]:
    return (TurtleFormat(), JsonLdFormat(), CypherFormat(), GraphMLFormat())


__all__ = ["CypherFormat", "GraphMLFormat", "JsonLdFormat", "TurtleFormat", "graph_formats"]
