"""The graph exports: RDF (Turtle, JSON-LD), Cypher and GraphML, on an invented library."""

from __future__ import annotations

import re
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

import networkx as nx
import pytest
import rdflib
from rdflib.compare import isomorphic

from postloom.adapters.export import graph_formats
from postloom.adapters.export.cypher import cypher_script, literal, string
from postloom.adapters.export.graphml import graphml
from postloom.adapters.export.rdf import (
    DATA,
    PL,
    JsonLdFormat,
    TurtleFormat,
    ontology,
    vocabulary_turtle,
)
from postloom.application.ports.graph_export import ExportOptions
from postloom.application.ports.repository import GraphContents
from postloom.domain.discussion import OWNER
from tests.graph_library import NASTY, T0, library

SITE = Path(__file__).resolve().parents[3] / "site"
SCHEMA_ORG = rdflib.Namespace("https://schema.org/")
PLNS = rdflib.Namespace(PL)

# rdflib's own JSON-LD parser uses a class it deprecated.
pytestmark = pytest.mark.filterwarnings("ignore:ConjunctiveGraph is deprecated")


def live(graph: GraphContents) -> GraphContents:
    """What ExportGraph hands a format without history."""
    from dataclasses import replace

    return replace(graph, edges=tuple(e for e in graph.edges if e.is_current))


def rdf(fmt: str, graph: GraphContents, options: ExportOptions) -> rdflib.Graph:
    writer = TurtleFormat() if fmt == "turtle" else JsonLdFormat()
    return rdflib.Graph().parse(
        data=writer.write(graph, options), format=fmt.replace("jsonld", "json-ld")
    )


def node(node_id: str) -> rdflib.URIRef:
    return rdflib.URIRef(DATA + node_id)


# -- RDF ---------------------------------------------------------------------------------
@pytest.mark.parametrize("history", [False, True])
@pytest.mark.parametrize("text", [False, True])
def test_turtle_and_json_ld_hold_the_same_graph(history: bool, text: bool) -> None:
    graph = library() if history else live(library())
    options = ExportOptions(text=text, history=history)
    turtle, json_ld = rdf("turtle", graph, options), rdf("jsonld", graph, options)
    assert len(turtle) > 200
    assert isomorphic(turtle, json_ld)


def test_rdf_keeps_every_text_exactly() -> None:
    g = rdf("turtle", library(), ExportOptions())
    notes = set(g.objects(node("person:jane-example"), PLNS.note))
    assert notes == {rdflib.Literal(NASTY)}
    body = g.value(node("article:caching-one"), SCHEMA_ORG.articleBody)
    assert str(body) == f"# Caching\n\n{NASTY}"


def test_rdf_types_nodes_with_postloom_and_schema_org_classes() -> None:
    g = rdf("turtle", live(library()), ExportOptions())
    article = node("article:caching-one")
    assert set(g.objects(article, rdflib.RDF.type)) == {PLNS.Article, SCHEMA_ORG.Article}
    assert (node("entity:example-labs"), rdflib.RDF.type, SCHEMA_ORG.Organization) in g
    jane = node("person:jane-example")
    assert (jane, SCHEMA_ORG.sameAs, rdflib.URIRef("https://www.linkedin.com/in/jane-example")) in g
    assert g.value(article, SCHEMA_ORG.datePublished).toPython() == date(2026, 3, 4)  # type: ignore[union-attr]
    # The author has no person note of their own, but their reply has an author.
    assert g.value(node(OWNER), SCHEMA_ORG.name) == rdflib.Literal("Alex Author")
    assert (node(OWNER), PLNS.isAuthor, rdflib.Literal(True)) in g


def test_live_relations_are_triples_and_history_is_only_in_records() -> None:
    g = rdf("turtle", library(), ExportOptions(history=True))
    one, two = node("article:caching-one"), node("article:caching-two")
    assert (one, PLNS.relatedTo, two) in g
    assert (two, PLNS.belongsTo, node("topic:evaluation")) not in g  # rejected
    assert (node("post:a-thought"), PLNS.linksTo, node("article:erased")) not in g  # superseded

    grades = """
        PREFIX pl: <%s> PREFIX prov: <http://www.w3.org/ns/prov#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?grade ?producer ?until WHERE {
          ?r a pl:EdgeRecord ; rdf:subject <%s> ; rdf:predicate pl:relatedTo ;
             pl:grade ?grade ; pl:producer ?producer .
          OPTIONAL { ?r prov:invalidatedAtTime ?until }
        } ORDER BY ?producer""" % (PL, one)  # noqa: UP031
    results: list[Any] = list(g.query(grades))
    rows = [(str(r[0]).removeprefix(PL), str(r[1]), r[2] is not None) for r in results]
    assert rows == [("Asserted", "embeddings", True), ("Verified", "user", False)]


def test_without_text_no_writing_leaves_the_computer() -> None:
    for writer in graph_formats():
        content = writer.write(library(), ExportOptions(text=False, history=True)).decode()
        assert "日本語" not in content
        assert "Body two" not in content
        assert "Caching, part one" in content  # titles stay


def test_every_postloom_term_used_is_defined_in_the_vocabulary() -> None:
    g = rdf("turtle", library(), ExportOptions(history=True))
    defined = {s for s, *_ in ontology() if s.value.startswith(PL)}
    used = {
        str(t)
        for triple in g
        for t in triple
        if isinstance(t, rdflib.URIRef) and str(t).startswith(PL)
    }
    assert used <= {d.value for d in defined}


def test_the_published_vocabulary_is_current() -> None:
    """site/ns.ttl is what https://postloom-app.vercel.app/ns serves."""
    assert (SITE / "ns.ttl").read_text(encoding="utf-8") == vocabulary_turtle()
    g = rdflib.Graph().parse(data=vocabulary_turtle(), format="turtle")
    assert (PLNS.authored, rdflib.OWL.inverseOf, SCHEMA_ORG.author) in g


# -- Cypher ------------------------------------------------------------------------------
def unquote(cypher: str) -> str:
    """Read back a single-quoted Cypher string literal."""
    assert cypher[0] == cypher[-1] == "'"
    escapes = {"\\": "\\", "'": "'", "n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
    out: list[str] = []
    i, body = 0, cypher[1:-1]
    while i < len(body):
        ch = body[i]
        if ch == "'":
            raise AssertionError("unescaped quote")
        if ch == "\\":
            nxt = body[i + 1]
            if nxt == "u":
                out.append(chr(int(body[i + 2 : i + 6], 16)))
                i += 6
                continue
            out.append(escapes[nxt])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


@pytest.mark.parametrize("text", [NASTY, "", "'", "\\", "\\'", "a" + chr(0x2028) + "b", "\r\n"])
def test_cypher_strings_round_trip(text: str) -> None:
    quoted = string(text)
    assert "\n" not in quoted and "\r" not in quoted
    assert unquote(quoted) == text


def test_cypher_literals() -> None:
    assert literal(True) == "true"
    assert literal(3) == "3"
    assert literal(0.5) == "0.5"
    assert literal(float("nan")) == "null"
    assert literal(date(2026, 3, 4)) == "date('2026-03-04')"
    assert literal(T0) == "datetime('2026-10-01T09:00:00+00:00')"
    assert literal(("a", "b")) == "['a', 'b']"
    assert literal({"x": 1, "bad key": "y"}) == "{x: 1, `bad key`: 'y'}"


def test_cypher_script_merges_every_node_and_relationship() -> None:
    script = cypher_script(library(), ExportOptions(history=True))
    statements = [s for s in script.split(";\n") if s.strip() and not s.lstrip().startswith("//")]
    assert statements[0].strip().startswith("CREATE CONSTRAINT postloom_id IF NOT EXISTS")
    assert all("MERGE" in s for s in statements[1:])
    ids = set(re.findall(r"\{id: '([^']+)'", script))
    assert {
        "article:caching-one",
        "person:me",
        "entity:example-labs",
        "media:caching-one/chart.png",
    } <= ids
    assert "SET n += row, n:Entity:Organisation" in script
    assert "MERGE (a)-[r:RELATED_TO {key: row.key}]->(b)" in script
    assert "article:erased" not in script  # no node to attach it to
    assert "grade: 'rejected', producer: 'user'" in script and "current: false" in script


# -- GraphML -----------------------------------------------------------------------------
def test_graphml_opens_in_networkx_with_typed_attributes() -> None:
    networkx: Any = nx  # untyped
    g = networkx.read_graphml(BytesIO(graphml(library(), ExportOptions(history=True))))
    assert g.nodes["article:caching-one"]["labels"] == ":Article"
    assert g.nodes["article:caching-one"]["series_part"] == 1
    assert g.nodes["entity:example-labs"]["labels"] == ":Entity:Organisation"
    assert g.nodes["person:jane-example"]["notes"] == NASTY.replace("\x07", "")  # XML can't hold it
    related = [d for *_, d in g.edges(data=True) if d["label"] == "RELATED_TO"]
    assert sorted((d["grade"], d["current"]) for d in related) == [
        ("asserted", False),
        ("verified", True),
    ]
    assert all(isinstance(d["weight"], float) for d in related)
    assert "article:erased" not in g


def test_every_format_names_its_file() -> None:
    names = {f.name: (f.extension, f.media_type) for f in graph_formats()}
    assert names == {
        "turtle": ("ttl", "text/turtle; charset=utf-8"),
        "jsonld": ("jsonld", "application/ld+json"),
        "cypher": ("cypher", "text/plain; charset=utf-8"),
        "graphml": ("graphml", "application/graphml+xml"),
    }
