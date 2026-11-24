"""Images and videos on articles and posts: kept in the vault, findable by their words."""

from __future__ import annotations

from pathlib import Path

import pytest

from postloom.application.errors import MediaTooLargeError, NotConfiguredError
from postloom.application.use_cases import IngestPostCommand
from postloom.domain.errors import DomainError
from postloom.domain.graph import NodeId
from postloom.domain.media import MediaKind, safe_filename, subtitle_text
from tests.fakes import FakeImageDescriber
from tests.home_support import CACHING, library, lose_index, open_home, state

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
VTT = """WEBVTT

1
00:00:00.000 --> 00:00:03.000
Today: how we <b>sharded</b> the vector index.

2
00:00:03.000 --> 00:00:06.000
Today: how we <b>sharded</b> the vector index.

00:00:06.000 --> 00:00:09.000
Recall stayed above ninety percent.
"""


NEW_SRT = b"1\n00:00:01,000 --> 00:00:02,000\nNew words\n"


def add_post(home: Path, text: str = "Three lessons from shipping agents #AI") -> NodeId:
    with open_home(home) as c:
        return c.ingest_post().execute(IngestPostCommand(text)).post.id


def found(home: Path, query: str) -> list[str]:
    with open_home(home) as c:
        results = c.search().execute(query).results
        return [p.heading for r in results for p in r.passages]


def test_an_image_is_kept_in_the_vault_and_found_by_its_caption(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    with open_home(tmp_path) as c:
        image = c.media().add(post, "Latency Chart (final).PNG", [PNG], "p99 latency after caching")

    assert image.file == "media/three-lessons-from-shipping-agents-ai/latency-chart-final.png"
    assert image.kind is MediaKind.IMAGE
    assert (tmp_path / "vault" / image.file).read_bytes() == PNG
    note = (tmp_path / "vault/posts/three-lessons-from-shipping-agents-ai.md").read_text()
    assert f"file: {image.file}" in note and "caption: p99 latency after caching" in note
    assert "Image: p99 latency after caching" in found(tmp_path, "p99 latency")

    with open_home(tmp_path) as c:
        c.media().update(post, image.file, "Throughput by shard")
    assert found(tmp_path, "p99 latency") == []
    assert "Image: Throughput by shard" in found(tmp_path, "throughput shard")


def test_a_model_describes_an_image_and_the_description_is_searchable(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    seeing = FakeImageDescriber()
    with open_home(tmp_path, image_describer=seeing) as c:
        image = c.media().add(post, "chart.png", [PNG])
        described = c.media().describe(post, image.file)

    assert seeing.seen == [(PNG, "image/png", "Three lessons from shipping agents #AI")]
    assert described.described_by == "fake-vision"
    assert "Image: chart.png" in found(tmp_path, "cache hit rate drifts")


def test_describing_needs_a_model_and_only_images(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    with open_home(tmp_path) as c:
        image = c.media().add(post, "chart.png", [PNG])
        with pytest.raises(NotConfiguredError):
            c.media().describe(post, image.file)
    with open_home(tmp_path, image_describer=FakeImageDescriber()) as c:
        video = c.media().add(post, "demo.mp4", [MP4])
        with pytest.raises(DomainError, match="Only images"):
            c.media().describe(post, video.file)


def test_a_video_is_found_by_what_is_said_in_it(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    with open_home(tmp_path) as c:
        video = c.media().add(post, "demo.mp4", [MP4], "Demo")
        with_words = c.media().add_subtitles(post, video.file, "demo.en.vtt", [VTT.encode()])
    assert with_words.transcript == (
        "Today: how we sharded the vector index. Recall stayed above ninety percent."
    )
    assert "Video: Demo" in found(tmp_path, "sharded vector index")

    with open_home(tmp_path) as c:  # new subtitles replace the old ones, which are kept
        c.media().add_subtitles(post, video.file, "demo.srt", [NEW_SRT])
    assert found(tmp_path, "sharded") == []
    assert "Video: Demo" in found(tmp_path, "new words")
    assert list((tmp_path / "vault/.postloom/trash").rglob("demo-en.vtt"))


def test_subtitles_belong_to_a_video(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    with open_home(tmp_path) as c:
        image = c.media().add(post, "chart.png", [PNG])
        with pytest.raises(DomainError, match="belong to a video"):
            c.media().add(post, "talk.vtt", [VTT.encode()])
        with pytest.raises(DomainError, match="Only videos"):
            c.media().add_subtitles(post, image.file, "talk.vtt", [VTT.encode()])


def test_removing_moves_the_file_to_the_trash(tmp_path: Path) -> None:
    post = add_post(tmp_path)
    with open_home(tmp_path) as c:
        image = c.media().add(post, "chart.png", [PNG], "latency chart")
        c.media().remove(post, image.file)
        assert c.browse().get_article(post).article.media == ()  # type: ignore[union-attr]
    assert not (tmp_path / "vault" / image.file).exists()
    assert list((tmp_path / "vault/.postloom/trash").rglob("chart.png"))
    assert found(tmp_path, "latency chart") == []


def test_the_vault_alone_rebuilds_media_with_their_words(tmp_path: Path) -> None:
    library(tmp_path)
    post = add_post(tmp_path)
    with open_home(tmp_path, image_describer=FakeImageDescriber()) as c:
        image = c.media().add(CACHING, "diagram.png", [PNG], "The cache in front of the LLM")
        c.media().describe(CACHING, image.file)
        video = c.media().add(post, "demo.mp4", [MP4])
        c.media().add_subtitles(post, video.file, "demo.vtt", [VTT.encode()])
        c.media().move(post, video.file, 0)
        before = state(c)
    lose_index(tmp_path)
    with open_home(tmp_path) as c:
        assert state(c) == before
    assert "Video: demo.mp4" in found(tmp_path, "sharded vector index")
    assert "Image: The cache in front of the LLM" in found(tmp_path, "cache hit rate")


def test_pasting_a_post_again_keeps_its_media_and_deleting_it_trashes_them(
    tmp_path: Path,
) -> None:
    post = add_post(tmp_path)
    with open_home(tmp_path) as c:
        image = c.media().add(post, "chart.png", [PNG])
    add_post(tmp_path)  # the same post, pasted again
    with open_home(tmp_path) as c:
        assert [m.file for m in c.repository.get_post(post).media] == [image.file]  # type: ignore[union-attr]
        c.delete_post().execute(post)
    assert not (tmp_path / "vault" / image.file).exists()
    assert list((tmp_path / "vault/.postloom/trash").rglob("chart.png"))


def test_files_are_named_safely_and_limited_in_size(tmp_path: Path) -> None:
    assert safe_filename("../../etc/Passwd Photo.JPG") == "passwd-photo.jpg"
    assert safe_filename("C:\\Users\\me\\Slide 1.webp") == "slide-1.webp"
    with pytest.raises(DomainError, match="is none of these"):
        safe_filename("notes.html")
    post = add_post(tmp_path)
    with open_home(tmp_path) as c:
        with pytest.raises(DomainError):
            c.media().add(post, "page.svg", [b"<svg/>"])
        with pytest.raises(MediaTooLargeError):
            c.media().add(post, "huge.png", iter([b"\x00" * 13_000_000] * 2))
        first = c.media().add(post, "chart.png", [PNG])
        second = c.media().add(post, "chart.png", [PNG])
    assert second.file == first.file.replace("chart.png", "chart-2.png")
    assert not list((tmp_path / "vault/media").rglob(".upload-*"))


def test_subtitle_text_keeps_only_the_words() -> None:
    srt = (
        "1\r\n00:00:01,000 --> 00:00:02,000\r\n<i>Hello</i> {\\an8}world\r\n\r\n"
        "2\r\n00:00:02,000 --> 00:00:03,000\r\nAgain\r\n"
    )
    assert subtitle_text(srt) == "Hello world Again"
    assert subtitle_text(VTT).startswith("Today: how we sharded")
