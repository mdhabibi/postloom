"""GraphML: opens in Gephi, yEd, Cytoscape, NetworkX, igraph, and Neo4j through
``apoc.import.graphml(..., {readLabels: true})``.

Nodes carry ``labels`` in Neo4j's ``:Article`` form and ``label`` as their display name;
edges carry ``label`` as their type, which is what both Gephi and APOC read. Lists are
written as JSON, dates as ISO 8601 text.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from datetime import date, datetime

from postloom.adapters.export.property_graph import Value, property_graph
from postloom.application.ports.graph_export import ExportOptions
from postloom.application.ports.repository import GraphContents

NS = "http://graphml.graphdrawing.org/xmlns"
SCHEMA = "http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd"
XSI = "http://www.w3.org/2001/XMLSchema-instance"


class GraphMLFormat:
    name = "graphml"
    title = "GraphML for Gephi, yEd and NetworkX"
    extension = "graphml"
    media_type = "application/graphml+xml"

    def write(self, graph: GraphContents, options: ExportOptions) -> bytes:
        return graphml(graph, options)


def graphml(graph: GraphContents, options: ExportOptions) -> bytes:
    pg = property_graph(graph, options)
    node_rows = [{"labels": "".join(f":{x}" for x in n.labels), **n.properties} for n in pg.nodes]
    edge_rows = [{"label": r.type, **r.properties} for r in pg.relationships]

    ET.register_namespace("", NS)
    ET.register_namespace("xsi", XSI)
    root = ET.Element(f"{{{NS}}}graphml", {f"{{{XSI}}}schemaLocation": f"{NS} {SCHEMA}"})
    keys: dict[tuple[str, str], str] = {}
    for domain, rows in (("node", node_rows), ("edge", edge_rows)):
        types: dict[str, str] = {}
        for row in rows:
            for name, value in row.items():
                if name == "id" and domain == "node":
                    continue
                types[name] = _widest(types.get(name), _type(value))
        for name, kind in types.items():
            key = f"{domain[0]}_{name}"
            keys[(domain, name)] = key
            attrs = {"id": key, "for": domain, "attr.name": name, "attr.type": kind}
            ET.SubElement(root, f"{{{NS}}}key", attrs)

    body = ET.SubElement(root, f"{{{NS}}}graph", {"id": "postloom", "edgedefault": "directed"})
    for row in node_rows:
        element = ET.SubElement(body, f"{{{NS}}}node", {"id": str(row["id"])})
        _data(element, keys, "node", row)
    for rel, row in zip(pg.relationships, edge_rows, strict=True):
        attrs = {"id": rel.key, "source": rel.source, "target": rel.target}
        element = ET.SubElement(body, f"{{{NS}}}edge", attrs)
        _data(element, keys, "edge", row)

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def _data(
    element: ET.Element, keys: dict[tuple[str, str], str], domain: str, row: dict[str, Value]
) -> None:
    for name, value in row.items():
        if (domain, name) in keys:
            ET.SubElement(element, f"{{{NS}}}data", {"key": keys[(domain, name)]}).text = _text(
                value
            )


def _type(value: Value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "long"
    if isinstance(value, float):
        return "double"
    return "string"


def _widest(current: str | None, new: str) -> str:
    if current is None or current == new:
        return new
    if {current, new} == {"long", "double"}:
        return "double"
    return "string"


def _text(value: Value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value) if math.isfinite(value) else "NaN"
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return json.dumps(list(value), ensure_ascii=False)
    return _xml_safe(str(value))


def _xml_safe(text: str) -> str:
    """XML 1.0 can't hold most control characters, even escaped: drop them."""
    return "".join(
        ch
        for ch in text
        if ch in "\t\n\r"
        or (0x20 <= ord(ch) <= 0xD7FF)
        or (0xE000 <= ord(ch) <= 0xFFFD)
        or ord(ch) >= 0x10000
    )
