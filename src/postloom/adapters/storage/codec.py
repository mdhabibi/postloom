"""JSON encoding of domain entities for storage.

Explicit per-type functions instead of reflection: the stored format is a contract
(old databases must keep loading), so every field is visible and versionable here.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, cast

from postloom.domain.content import Article, Post, Series, Topic
from postloom.domain.discussion import Comment
from postloom.domain.entities import Category, Entity
from postloom.domain.graph import NodeId
from postloom.domain.people import Person, ProfileObservation, ProfileUrl

Json = dict[str, Any]


def dumps(data: Json) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def loads(text: str) -> Json:
    return cast(Json, json.loads(text))


def _date_out(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _date_in(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


# -- topic ---------------------------------------------------------------------
def topic_to_json(topic: Topic) -> Json:
    return {"name": topic.name, "description": topic.description}


def topic_from_json(data: Json) -> Topic:
    return Topic(name=data["name"], description=data.get("description", ""))


# -- entities ------------------------------------------------------------------
def entity_to_json(entity: Entity) -> Json:
    return {
        "key": entity.key,
        "name": entity.name,
        "category": entity.category.value,
        "url": entity.url,
        "aliases": list(entity.aliases),
    }


def entity_from_json(data: Json) -> Entity:
    return Entity(
        key=data["key"],
        name=data["name"],
        category=Category(data["category"]),
        url=data.get("url"),
        aliases=tuple(data.get("aliases", ())),
    )


# -- series --------------------------------------------------------------------
def series_to_json(series: Series) -> Json:
    return {"name": series.name}


def series_from_json(data: Json) -> Series:
    return Series(name=data["name"])


# -- article -------------------------------------------------------------------
def article_to_json(article: Article) -> Json:
    return {
        "title": article.title,
        "body_markdown": article.body_markdown,
        "summary": article.summary,
        "url": article.url,
        "published_on": _date_out(article.published_on),
        "series": article.series.name if article.series else None,
        "series_part": article.series_part,
        "hashtags": list(article.hashtags),
        "entities": list(article.entities),
        "key": article.key,
    }


def article_from_json(data: Json) -> Article:
    series_name: str | None = data.get("series")
    return Article(
        title=data["title"],
        body_markdown=data["body_markdown"],
        summary=data.get("summary", ""),
        url=data.get("url"),
        published_on=_date_in(data.get("published_on")),
        series=Series(series_name) if series_name else None,
        series_part=data.get("series_part"),
        hashtags=tuple(data.get("hashtags", ())),
        entities=tuple(data.get("entities", ())),
        key=data.get("key", ""),
    )


# -- post ----------------------------------------------------------------------
def post_to_json(post: Post) -> Json:
    return {
        "key": post.key,
        "text": post.text,
        "url": post.url,
        "published_on": _date_out(post.published_on),
        "hashtags": list(post.hashtags),
        "links": list(post.links),
        "banner_path": post.banner_path,
    }


def post_from_json(data: Json) -> Post:
    return Post(
        key=data["key"],
        text=data["text"],
        url=data.get("url"),
        published_on=_date_in(data.get("published_on")),
        hashtags=tuple(data.get("hashtags", ())),
        links=tuple(data.get("links", ())),
        banner_path=data.get("banner_path"),
    )


# -- comment -------------------------------------------------------------------
def comment_to_json(comment: Comment) -> Json:
    return {
        "post": comment.post,
        "author": comment.author,
        "author_name": comment.author_name,
        "text": comment.text,
        "position": comment.position,
        "thread": comment.thread,
        "reply_to": comment.reply_to,
        "posted_label": comment.posted_label,
    }


def comment_from_json(data: Json) -> Comment:
    thread: str | None = data.get("thread")
    reply_to: str | None = data.get("reply_to")
    return Comment(
        post=NodeId(data["post"]),
        author=NodeId(data["author"]),
        author_name=data["author_name"],
        text=data["text"],
        position=int(data["position"]),
        thread=NodeId(thread) if thread else None,
        reply_to=NodeId(reply_to) if reply_to else None,
        posted_label=data.get("posted_label", ""),
    )


# -- person --------------------------------------------------------------------
def person_to_json(person: Person) -> Json:
    return {
        "name": person.name,
        "profile": person.profile.slug if person.profile else None,
        "observations": [
            {
                "headline": o.headline,
                "observed_at": o.observed_at.isoformat(),
                "superseded_at": o.superseded_at.isoformat() if o.superseded_at else None,
            }
            for o in person.observations
        ],
        "notes": person.notes,
        "tags": list(person.tags),
    }


def person_from_json(data: Json) -> Person:
    slug: str | None = data.get("profile")
    observations: list[Json] = data.get("observations", [])
    return Person(
        name=data["name"],
        profile=ProfileUrl(slug) if slug else None,
        observations=tuple(
            ProfileObservation(
                headline=o["headline"],
                observed_at=datetime.fromisoformat(o["observed_at"]),
                superseded_at=(
                    datetime.fromisoformat(o["superseded_at"]) if o.get("superseded_at") else None
                ),
            )
            for o in observations
        ),
        notes=data.get("notes", ""),
        tags=tuple(data.get("tags", ())),
    )
