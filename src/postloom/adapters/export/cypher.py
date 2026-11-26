"""A Cypher script that loads the library into Neo4j (or Memgraph).

    cypher-shell -u neo4j -p <password> -f postloom-graph.cypher

Every node gets the label ``Postloom`` plus its kind, and is MERGEd on ``id``; every
relationship is MERGEd on its ``key``. Running the same file again changes nothing, and
running a newer export updates what changed. Values are written as literals with every
string escaped, so nothing in your text can end a statement early.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import TypeVar, cast

from postloom.adapters.export.property_graph import PgNode, PgRelationship, property_graph
from postloom.application.ports.graph_export import ExportOptions
from postloom.application.ports.repository import GraphContents

_T = TypeVar("_T")

BATCH = 200
"""Rows per UNWIND: large enough to load fast, small enough for any transaction size."""

HEADER = """\
// postloom graph export for Neo4j 5 (also loads in Memgraph).
//
// Load:  cypher-shell -u neo4j -p <password> -f {filename}
//        or Neo4j Browser with "Enable multi statement query editor" turned on.
// Every node has the label :Postloom and a unique `id` (the postloom id); relationships
// carry provenance: origin, grade (verified / asserted / rejected), producer, recorded_at.
// Loading twice changes nothing. To start over first:
//   MATCH (n:Postloom) DETACH DELETE n;
//
// Try:  MATCH (p:Person)-[:AUTHORED]->(:Comment)-[:COMMENTED_ON]->(:Post)-[:ANNOUNCES]->(a:Article)
//       RETURN p.name, count(DISTINCT a) AS articles ORDER BY articles DESC LIMIT 10;
"""


class CypherFormat:
    name = "cypher"
    title = "Cypher for Neo4j"
    extension = "cypher"
    media_type = "text/plain; charset=utf-8"

    def write(self, graph: GraphContents, options: ExportOptions) -> bytes:
        return cypher_script(graph, options).encode("utf-8")


def cypher_script(graph: GraphContents, options: ExportOptions) -> str:
    pg = property_graph(graph, options)
    parts = [
        HEADER.format(filename="postloom-graph.cypher"),
        "CREATE CONSTRAINT postloom_id IF NOT EXISTS FOR (n:Postloom) REQUIRE n.id IS UNIQUE;",
        "",
    ]
    parts.extend(_node_statements(pg.nodes))
    parts.extend(_relationship_statements(pg.relationships))
    return "\n".join(parts) + "\n"


def _node_statements(nodes: Sequence[PgNode]) -> Iterable[str]:
    by_labels: dict[tuple[str, ...], list[PgNode]] = defaultdict(list)
    for node in nodes:
        by_labels[node.labels].append(node)
    for labels, group in by_labels.items():
        label_set = "".join(f":{_name(label)}" for label in labels)
        for chunk in batched(group, BATCH):
            rows = ",\n  ".join(literal(n.properties) for n in chunk)
            yield (
                f"UNWIND [\n  {rows}\n] AS row\n"
                f"MERGE (n:Postloom {{id: row.id}})\nSET n += row, n{label_set};\n"
            )


def _relationship_statements(relationships: Sequence[PgRelationship]) -> Iterable[str]:
    by_type: dict[str, list[PgRelationship]] = defaultdict(list)
    for rel in relationships:
        by_type[rel.type].append(rel)
    for rel_type, group in by_type.items():
        for chunk in batched(group, BATCH):
            rows = ",\n  ".join(
                literal({"s": r.source, "t": r.target, "key": r.key, "p": r.properties})
                for r in chunk
            )
            yield (
                f"UNWIND [\n  {rows}\n] AS row\n"
                "MATCH (a:Postloom {id: row.s})\nMATCH (b:Postloom {id: row.t})\n"
                f"MERGE (a)-[r:{_name(rel_type)} {{key: row.key}}]->(b)\nSET r += row.p;\n"
            )


def batched(items: Sequence[_T], size: int) -> Iterable[Sequence[_T]]:
    """``itertools.batched`` (Python 3.12+), for 3.11."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def literal(value: object) -> str:
    """A Cypher literal for ``value``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value) if math.isfinite(value) else "null"
    if isinstance(value, datetime):
        return f"datetime({string(value.isoformat())})"
    if isinstance(value, date):
        return f"date({string(value.isoformat())})"
    if isinstance(value, str):
        return string(value)
    if isinstance(value, dict):
        items = cast(dict[str, object], value).items()
        return "{" + ", ".join(f"{_name(k)}: {literal(v)}" for k, v in items) + "}"
    if isinstance(value, tuple | list):
        return "[" + ", ".join(literal(v) for v in cast(Sequence[object], value)) + "]"
    raise TypeError(f"no Cypher literal for {type(value).__name__}")


_ESCAPES = {
    "\\": "\\\\",
    "'": "\\'",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}


def string(text: str) -> str:
    out: list[str] = []
    for ch in text:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20 or 0x7F <= ord(ch) < 0xA0 or ord(ch) in (0x2028, 0x2029):
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "'" + "".join(out) + "'"


def _name(name: str) -> str:
    """A label, type or key: ours are plain words, but quote anything that isn't."""
    if name.replace("_", "a").isalnum() and name.isascii() and not name[0].isdigit():
        return name
    return "`" + name.replace("`", "``") + "`"
