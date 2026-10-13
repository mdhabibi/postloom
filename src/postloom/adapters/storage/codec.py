"""JSON encoding of domain entities for storage.

Explicit per-type functions instead of reflection: the stored format is a contract
(old databases must keep loading), so every field is visible and versionable here.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, cast

from postloom.domain.content import Article, Post, Series, Topic

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
