"""The library as RDF: Turtle and JSON-LD, with provenance in PROV-O.

Modelling choices:

- **Vocabulary.** Nodes are typed with postloom's own classes *and* the schema.org (or
  SKOS) class they correspond to, and described with schema.org properties, so tools that
  know schema.org understand them without reasoning. Relations use postloom properties
  (``pl:belongsTo``...), each mapped to schema.org or Dublin Core by
  ``rdfs:subPropertyOf`` or ``owl:inverseOf``. The vocabulary is written into every export
  and published at https://postloom-app.vercel.app/ns.
- **Identifiers.** A node's IRI is ``urn:postloom:`` + its postloom id, e.g.
  ``urn:postloom:article:measuring-what-matters``: stable, and never pretending to resolve
  on the web. People with a LinkedIn profile are ``schema:sameAs`` that profile.
- **Provenance.** Every live relation is a plain triple, so queries stay simple. Each
  recorded edge is also a ``pl:EdgeRecord`` (an ``rdf:Statement`` and a ``prov:Entity``)
  naming its subject, predicate and object, how it was made (``pl:origin``), how far it
  is trusted (``pl:grade``), who made it and when (``prov:generatedAtTime``), and when it
  stopped being true (``prov:invalidatedAtTime``). Superseded and rejected edges exist only
  as records, never as triples. Standard RDF 1.1 reification: no RDF-star needed, so it
  loads in any triple store.

The serializers are small and exact on purpose (no rdflib at run time); the tests check
that rdflib parses both formats into the same graph.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote

from postloom.adapters.export.property_graph import author_name, record_key
from postloom.application.ports.graph_export import ExportOptions
from postloom.application.ports.repository import GraphContents
from postloom.domain.content import Article, Post
from postloom.domain.discussion import OWNER
from postloom.domain.entities import Category
from postloom.domain.graph import Edge, EdgeKind
from postloom.domain.media import Media, MediaKind
from postloom.domain.provenance import Grade, Origin

ONTOLOGY = "https://postloom-app.vercel.app/ns"
PL = ONTOLOGY + "#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
XSD = "http://www.w3.org/2001/XMLSchema#"
OWL = "http://www.w3.org/2002/07/owl#"
SCHEMA = "https://schema.org/"
SKOS = "http://www.w3.org/2004/02/skos/core#"
PROV = "http://www.w3.org/ns/prov#"
DCTERMS = "http://purl.org/dc/terms/"
DATA = "urn:postloom:"

PREFIXES: dict[str, str] = {
    "pl": PL,
    "rdf": RDF,
    "rdfs": RDFS,
    "xsd": XSD,
    "owl": OWL,
    "schema": SCHEMA,
    "skos": SKOS,
    "prov": PROV,
    "dcterms": DCTERMS,
}


# -- a tiny RDF model --------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class IRI:
    value: str


@dataclass(frozen=True, slots=True)
class Literal:
    value: str
    datatype: str | None = None
    """None means xsd:string."""


Term = IRI | Literal
Triple = tuple[IRI, IRI, Term]

TYPE = IRI(RDF + "type")


def pl(name: str) -> IRI:
    return IRI(PL + name)


def schema(name: str) -> IRI:
    return IRI(SCHEMA + name)


def node(node_id: str) -> IRI:
    """``article:x`` -> ``urn:postloom:article:x``, percent-encoding anything an IRI can't
    hold (keys are already restricted; this is a second line of defence)."""
    return IRI(DATA + quote(node_id, safe=":~-._!$&'()*+,;=@/", encoding="utf-8"))


def text(value: str) -> Literal:
    return Literal(value)


def typed(value: object) -> Literal:
    if isinstance(value, bool):
        return Literal("true" if value else "false", XSD + "boolean")
    if isinstance(value, int):
        return Literal(str(value), XSD + "integer")
    if isinstance(value, float):
        return Literal(repr(value), XSD + "double")
    if isinstance(value, datetime):
        return Literal(value.isoformat(), XSD + "dateTime")
    if isinstance(value, date):
        return Literal(value.isoformat(), XSD + "date")
    return Literal(str(value))


# -- the vocabulary ----------------------------------------------------------------------
EDGE_PROPERTIES: dict[EdgeKind, str] = {
    EdgeKind.BELONGS_TO: "belongsTo",
    EdgeKind.PART_OF: "partOf",
    EdgeKind.ANNOUNCES: "announces",
    EdgeKind.COMMENTED_ON: "commentedOn",
    EdgeKind.REPLIED_TO: "repliedTo",
    EdgeKind.AUTHORED: "authored",
    EdgeKind.RELATED_TO: "relatedTo",
    EdgeKind.LINKS_TO: "linksTo",
    EdgeKind.MENTIONS: "mentions",
}
CATEGORY_CLASSES: dict[Category, str] = {
    Category.ORGANISATION: SCHEMA + "Organization",
    Category.PLACE: SCHEMA + "Place",
    Category.EVENT: SCHEMA + "Event",
    Category.PROJECT: SCHEMA + "CreativeWork",
    Category.DATASET: SCHEMA + "Dataset",
    Category.METHOD: SCHEMA + "DefinedTerm",
    Category.LINK: SCHEMA + "WebPage",
    Category.OTHER: SCHEMA + "Thing",
}
GRADES: dict[Grade, str] = {
    Grade.VERIFIED: "Confirmed by a deterministic rule or by the author.",
    Grade.ASSERTED: "Stated by a model or a heuristic, not reviewed yet.",
    Grade.REJECTED: "Reviewed by the author and declined; kept so it isn't suggested again.",
}
ORIGINS: dict[Origin, str] = {
    Origin.STRUCTURAL: "Parsed deterministically from the content.",
    Origin.TAXONOMY: "A model classified content into the author's own topics.",
    Origin.SEMANTIC: "Similarity of meaning (embeddings) above a threshold.",
    Origin.MANUAL: "Made by the author, in the app or in the vault.",
}

# (name, label, equivalent classes, comment)
_CLASSES: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("Topic", "Topic", (SKOS + "Concept",), "One of the author's own subjects."),
    ("Series", "Series", (SCHEMA + "CreativeWorkSeries",), "A multi-part series of articles."),
    ("Article", "Article", (SCHEMA + "Article",), "A long-form LinkedIn article."),
    (
        "Post",
        "Post",
        (SCHEMA + "SocialMediaPosting",),
        "A feed post: announcing an article, or standing on its own.",
    ),
    ("Comment", "Comment", (SCHEMA + "Comment",), "A comment or reply under a post."),
    (
        "Person",
        "Person",
        (SCHEMA + "Person",),
        "Someone who commented or was mentioned; the author is one too.",
    ),
    (
        "Entity",
        "Mentioned thing",
        (SCHEMA + "Thing",),
        "An organisation, place, event, project, dataset, method or link the author's "
        "writing names, confirmed by the author.",
    ),
    (
        "EdgeRecord",
        "Edge record",
        (RDF + "Statement", PROV + "Entity"),
        "One recorded relation with its provenance; superseded and rejected ones too.",
    ),
    ("Grade", "Grade", (), "How far a relation is trusted."),
    ("Origin", "Origin", (), "Which mechanism produced a relation."),
)

# (name, label, (domain, range), mapping predicate, mapped IRI, comment)
_RELATIONS: tuple[tuple[str, str, tuple[str | None, str | None], str, str, str], ...] = (
    ("belongsTo", "belongs to", (None, "Topic"), "sub", SCHEMA + "about", "Filed under a topic."),
    ("partOf", "part of", ("Article", "Series"), "sub", SCHEMA + "isPartOf", "A part of a series."),
    (
        "announces",
        "announces",
        ("Post", "Article"),
        "sub",
        SCHEMA + "sharedContent",
        "The post that shared an article.",
    ),
    (
        "commentedOn",
        "commented on",
        ("Comment", None),
        "inverse",
        SCHEMA + "comment",
        "The post (or article) a comment is under.",
    ),
    (
        "repliedTo",
        "replied to",
        ("Comment", "Comment"),
        "sub",
        SCHEMA + "parentItem",
        "The message a reply answers.",
    ),
    (
        "authored",
        "authored",
        ("Person", "Comment"),
        "inverse",
        SCHEMA + "author",
        "Who wrote a comment.",
    ),
    (
        "relatedTo",
        "related to",
        ("Article", "Article"),
        "sub",
        DCTERMS + "relation",
        "Articles about the same thing; symmetric, stored once per pair.",
    ),
    (
        "linksTo",
        "links to",
        (None, "Article"),
        "sub",
        SCHEMA + "citation",
        "A link in the text to another of the author's articles.",
    ),
    (
        "mentions",
        "mentions",
        (None, None),
        "sub",
        SCHEMA + "mentions",
        "A person or thing the text names, confirmed by the author.",
    ),
)

# (name, label, kind, range, comment)
_DATA: tuple[tuple[str, str, str, str | None, str], ...] = (
    ("origin", "origin", "object", "Origin", "How a relation was made."),
    ("grade", "grade", "object", "Grade", "How far a relation is trusted."),
    (
        "producer",
        "producer",
        "data",
        XSD + "string",
        'Who made it: "user", "parser", "llm:<model>".',
    ),
    ("evidence", "evidence", "data", XSD + "string", "The passage or reason behind a relation."),
    ("weight", "weight", "data", XSD + "double", "Strength, e.g. cosine similarity."),
    ("headline", "headline", "data", XSD + "string", "A person's LinkedIn headline, latest seen."),
    ("note", "note", "data", XSD + "string", "The author's private notes about a person."),
    ("isAuthor", "is the author", "data", XSD + "boolean", "The person whose library this is."),
    (
        "provisional",
        "provisional",
        "data",
        XSD + "boolean",
        "Known by name only, no LinkedIn profile yet.",
    ),
    ("category", "category", "data", XSD + "string", "What kind of thing an entity is."),
    ("vaultPath", "vault path", "data", XSD + "string", "Where a file is, inside the vault."),
    ("postedLabel", "posted", "data", XSD + "string", 'LinkedIn\'s relative age, e.g. "2w".'),
)


def ontology() -> list[Triple]:
    """postloom's vocabulary as RDFS/OWL, with its mappings to schema.org, SKOS and PROV."""
    out: list[Triple] = []
    onto = IRI(ONTOLOGY)

    def add(s: IRI, p: str, o: Term) -> None:
        out.append((s, IRI(p), o))

    add(onto, RDF + "type", IRI(OWL + "Ontology"))
    add(onto, RDFS + "label", text("postloom vocabulary"))
    add(
        onto,
        RDFS + "comment",
        text(
            "Classes and relations of a postloom library: articles, posts, comments, the "
            "people in them and what they mention, with the provenance of every relation."
        ),
    )
    add(onto, OWL + "versionInfo", text("1"))
    add(onto, DCTERMS + "creator", text("Dr. Mahdi Habibi"))
    add(onto, RDFS + "seeAlso", IRI("https://github.com/mdhabibi/postloom"))
    for name, label, equivalents, comment in _CLASSES:
        cls = pl(name)
        add(cls, RDF + "type", IRI(OWL + "Class"))
        add(cls, RDFS + "label", text(label))
        add(cls, RDFS + "comment", text(comment))
        add(cls, RDFS + "isDefinedBy", onto)
        for parent in equivalents:
            add(cls, RDFS + "subClassOf", IRI(parent))
    for name, label, (domain, range_), mapping, mapped, comment in _RELATIONS:
        prop = pl(name)
        add(prop, RDF + "type", IRI(OWL + "ObjectProperty"))
        if name == "relatedTo":
            add(prop, RDF + "type", IRI(OWL + "SymmetricProperty"))
        add(prop, RDFS + "label", text(label))
        add(prop, RDFS + "comment", text(comment))
        add(prop, RDFS + "isDefinedBy", onto)
        if domain:
            add(prop, RDFS + "domain", pl(domain))
        if range_:
            add(prop, RDFS + "range", pl(range_))
        add(prop, RDFS + "subPropertyOf" if mapping == "sub" else OWL + "inverseOf", IRI(mapped))
    for name, label, kind, range_, comment in _DATA:
        prop = pl(name)
        kind_iri = OWL + ("ObjectProperty" if kind == "object" else "DatatypeProperty")
        add(prop, RDF + "type", IRI(kind_iri))
        add(prop, RDFS + "label", text(label))
        add(prop, RDFS + "comment", text(comment))
        add(prop, RDFS + "isDefinedBy", onto)
        if range_:
            add(prop, RDFS + "range", IRI(range_) if "/" in range_ else pl(range_))
    for grade, comment in GRADES.items():
        individual = pl(grade.value.capitalize())
        add(individual, RDF + "type", pl("Grade"))
        add(individual, RDFS + "label", text(grade.value))
        add(individual, RDFS + "comment", text(comment))
    for origin, comment in ORIGINS.items():
        individual = pl(origin.value.capitalize())
        add(individual, RDF + "type", pl("Origin"))
        add(individual, RDFS + "label", text(origin.value))
        add(individual, RDFS + "comment", text(comment))
    return out


# -- the data ----------------------------------------------------------------------------
def library_triples(graph: GraphContents, options: ExportOptions) -> list[Triple]:
    return [*ontology(), *_nodes(graph, options), *_edges(graph, options)]


def _nodes(graph: GraphContents, options: ExportOptions) -> Iterator[Triple]:
    label = IRI(RDFS + "label")
    keep_text = options.text
    scheme = IRI(DATA + "topics")
    if graph.topics:
        yield scheme, TYPE, IRI(SKOS + "ConceptScheme")
        yield scheme, label, text("Topics")
    for topic in graph.topics:
        s = node(topic.id)
        yield from _typed(s, "Topic", SKOS + "Concept")
        yield s, label, text(topic.name)
        yield s, IRI(SKOS + "prefLabel"), text(topic.name)
        yield s, IRI(SKOS + "inScheme"), scheme
        if topic.description:
            yield s, IRI(SKOS + "definition"), text(topic.description)
    for series in graph.series:
        s = node(series.id)
        yield from _typed(s, "Series", SCHEMA + "CreativeWorkSeries")
        yield s, label, text(series.name)
        yield s, schema("name"), text(series.name)
    for article in graph.articles:
        s = node(article.id)
        yield from _typed(s, "Article", SCHEMA + "Article")
        yield s, label, text(article.title)
        yield s, schema("headline"), text(article.title)
        yield from _published(s, article)
        if article.series_part is not None:
            yield s, schema("position"), typed(article.series_part)
        if keep_text and article.summary:
            yield s, schema("abstract"), text(article.summary)
        if keep_text:
            yield s, schema("articleBody"), text(article.body_markdown)
        yield from _media(s, article, options)
    for post in graph.posts:
        s = node(post.id)
        yield from _typed(s, "Post", SCHEMA + "SocialMediaPosting")
        yield s, label, text(post.title)
        yield s, schema("headline"), text(post.title)
        yield from _published(s, post)
        for link in post.links:
            if _web(link):
                yield s, schema("citation"), IRI(_web(link))
        if keep_text:
            yield s, schema("text"), text(post.text)
        yield from _media(s, post, options)
    for comment in graph.comments:
        s = node(comment.id)
        yield from _typed(s, "Comment", SCHEMA + "Comment")
        yield s, label, text(f"Comment by {comment.author_name}")
        yield s, schema("position"), typed(comment.position)
        if comment.posted_label:
            yield s, pl("postedLabel"), text(comment.posted_label)
        if keep_text:
            yield s, schema("text"), text(comment.text)
    for person in graph.people:
        s = node(person.id)
        yield from _typed(s, "Person", SCHEMA + "Person")
        yield s, label, text(person.name)
        yield s, schema("name"), text(person.name)
        if person.profile is not None:
            yield s, schema("sameAs"), IRI(person.profile.url)
        if person.headline:
            yield s, pl("headline"), text(person.headline)
        for tag in person.tags:
            yield s, schema("keywords"), text(tag)
        if person.id == OWNER:
            yield s, pl("isAuthor"), typed(True)
        if person.is_provisional:
            yield s, pl("provisional"), typed(True)
        if keep_text and person.notes:
            yield s, pl("note"), text(person.notes)
    author = author_name(graph)
    if author is not None:
        s = node(OWNER)
        yield from _typed(s, "Person", SCHEMA + "Person")
        yield s, label, text(author)
        yield s, schema("name"), text(author)
        yield s, pl("isAuthor"), typed(True)
    for entity in graph.entities:
        s = node(entity.id)
        yield from _typed(s, "Entity", CATEGORY_CLASSES[entity.category])
        yield s, label, text(entity.name)
        yield s, schema("name"), text(entity.name)
        yield s, pl("category"), text(entity.category.value)
        for alias in entity.aliases:
            yield s, schema("alternateName"), text(alias)
        if entity.url and _web(entity.url):
            yield s, schema("url"), IRI(_web(entity.url))


def _typed(s: IRI, cls: str, mapped: str) -> Iterator[Triple]:
    yield s, TYPE, pl(cls)
    yield s, TYPE, IRI(mapped)


def _published(s: IRI, item: Article | Post) -> Iterator[Triple]:
    if item.url and _web(item.url):
        yield s, schema("url"), IRI(_web(item.url))
    if item.published_on is not None:
        yield s, schema("datePublished"), typed(item.published_on)
    for tag in item.hashtags:
        yield s, schema("keywords"), text(tag)


def _media(s: IRI, item: Article | Post, options: ExportOptions) -> Iterator[Triple]:
    for media in item.media:
        m = _media_iri(media)
        cls = "ImageObject" if media.kind is MediaKind.IMAGE else "VideoObject"
        yield s, schema("associatedMedia"), m
        yield m, TYPE, schema(cls)
        yield m, IRI(RDFS + "label"), text(media.label())
        yield m, schema("encodingFormat"), text(media.mime)
        yield m, pl("vaultPath"), text(media.file)
        if options.text and media.caption:
            yield m, schema("caption"), text(media.caption)
        if options.text and media.description:
            yield m, schema("description"), text(media.description)
        if options.text and media.transcript:
            yield m, schema("transcript"), text(media.transcript)


def _media_iri(media: Media) -> IRI:
    return node(media.file.replace("/", ":", 1))


def _edges(graph: GraphContents, options: ExportOptions) -> Iterator[Triple]:
    seen: set[str] = set()
    for edge in graph.edges:
        key = record_key(edge)
        if key in seen:
            continue
        seen.add(key)
        s, p, o = node(edge.source), pl(EDGE_PROPERTIES[edge.kind]), node(edge.target)
        if edge.is_current:
            yield s, p, o
        yield from _record(IRI(DATA + "edge:" + key), edge, (s, p, o), options)


def _record(r: IRI, edge: Edge, triple: Triple, options: ExportOptions) -> Iterator[Triple]:
    s, p, o = triple
    prov = edge.provenance
    yield r, TYPE, pl("EdgeRecord")
    yield r, IRI(RDF + "subject"), s
    yield r, IRI(RDF + "predicate"), p
    yield r, IRI(RDF + "object"), o
    yield r, pl("origin"), pl(prov.origin.value.capitalize())
    yield r, pl("grade"), pl(prov.grade.value.capitalize())
    yield r, pl("producer"), text(prov.producer)
    yield r, IRI(PROV + "generatedAtTime"), typed(prov.recorded_at)
    if edge.superseded_at is not None:
        yield r, IRI(PROV + "invalidatedAtTime"), typed(edge.superseded_at)
    if edge.weight is not None:
        yield r, pl("weight"), typed(float(edge.weight))
    if options.text and prov.evidence:
        yield r, pl("evidence"), text(prov.evidence)


_WEB = re.compile(r"^https?://[^\s<>\"{}|\\^`]+$", re.IGNORECASE)


def _web(url: str) -> str:
    """The URL if it is a web address an IRI can hold as it is, else empty."""
    url = url.strip()
    return url if _WEB.match(url) else ""


# -- Turtle ------------------------------------------------------------------------------
_LOCAL = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def turtle(triples: Iterable[Triple]) -> str:
    lines = [f"@prefix {p}: <{iri}> ." for p, iri in PREFIXES.items()]
    lines.append("")
    by_subject: dict[IRI, list[tuple[IRI, Term]]] = {}
    for s, p, o in triples:
        pairs = by_subject.setdefault(s, [])
        if (p, o) not in pairs:
            pairs.append((p, o))
    for s, pairs in by_subject.items():
        grouped: dict[IRI, list[Term]] = {}
        for p, o in pairs:
            grouped.setdefault(p, []).append(o)
        body = " ;\n    ".join(
            f"{'a' if p == TYPE else _iri(p)} {', '.join(_term(o) for o in objects)}"
            for p, objects in grouped.items()
        )
        lines.append(f"{_iri(s)}\n    {body} .\n")
    return "\n".join(lines)


def _iri(iri: IRI) -> str:
    for prefix, base in PREFIXES.items():
        if iri.value.startswith(base) and _LOCAL.match(iri.value[len(base) :]):
            return f"{prefix}:{iri.value[len(base) :]}"
    return "<" + _escape_iri(iri.value) + ">"


def _escape_iri(value: str) -> str:
    return "".join(
        f"\\u{ord(ch):04X}" if ch in '<>"{}|^`\\' or ord(ch) <= 0x20 else ch for ch in value
    )


def _term(term: Term) -> str:
    if isinstance(term, IRI):
        return _iri(term)
    quoted = '"' + _escape_string(term.value) + '"'
    return quoted if term.datatype is None else f"{quoted}^^{_iri(IRI(term.datatype))}"


_STRING_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _escape_string(value: str) -> str:
    out: list[str] = []
    for ch in value:
        if ch in _STRING_ESCAPES:
            out.append(_STRING_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return "".join(out)


# -- JSON-LD -----------------------------------------------------------------------------
def json_ld(triples: Iterable[Triple]) -> dict[str, object]:
    """Flattened JSON-LD: one object per subject in ``@graph``, with a context of prefixes."""
    types: dict[IRI, list[str]] = {}
    values: dict[IRI, dict[str, list[object]]] = {}
    for s, p, o in triples:
        types.setdefault(s, [])
        properties = values.setdefault(s, {})
        if p == TYPE and isinstance(o, IRI):
            if _compact(o) not in types[s]:
                types[s].append(_compact(o))
            continue
        found = properties.setdefault(_compact(p), [])
        value = _json_value(o)
        if value not in found:
            found.append(value)
    graph: list[dict[str, object]] = []
    for s, properties in values.items():
        obj: dict[str, object] = {"@id": _compact(s)}
        if types[s]:
            obj["@type"] = types[s]
        obj.update(properties)
        graph.append(obj)
    return {"@context": dict(PREFIXES), "@graph": graph}


def _compact(iri: IRI) -> str:
    for prefix, base in PREFIXES.items():
        if iri.value.startswith(base) and _LOCAL.match(iri.value[len(base) :]):
            return f"{prefix}:{iri.value[len(base) :]}"
    return iri.value


def _json_value(term: Term) -> object:
    if isinstance(term, IRI):
        return {"@id": _compact(term)}
    if term.datatype is None:
        return term.value
    return {"@value": term.value, "@type": _compact(IRI(term.datatype))}


# -- formats -----------------------------------------------------------------------------
class TurtleFormat:
    name = "turtle"
    title = "RDF (Turtle)"
    extension = "ttl"
    media_type = "text/turtle; charset=utf-8"

    def write(self, graph: GraphContents, options: ExportOptions) -> bytes:
        return turtle(library_triples(graph, options)).encode("utf-8")


class JsonLdFormat:
    name = "jsonld"
    title = "RDF (JSON-LD)"
    extension = "jsonld"
    media_type = "application/ld+json"

    def write(self, graph: GraphContents, options: ExportOptions) -> bytes:
        document = json_ld(library_triples(graph, options))
        return (json.dumps(document, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def vocabulary_turtle() -> str:
    """The vocabulary on its own, as published on the website (``site/ns.ttl``)."""
    return turtle(ontology())
