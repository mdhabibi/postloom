from postloom.domain.text import (
    content_size,
    detect_series_part,
    extract_hashtags,
    extract_urls,
    slugify,
)
from tests.fakes import fixture_text


def test_slugify_normalizes_case_punctuation_and_accents() -> None:
    assert slugify("Measuring What Matters: Part 3!") == "measuring-what-matters-part-3"
    assert slugify("Café Déjà Vu") == "cafe-deja-vu"
    assert slugify("!!!") == "untitled"


def test_slugify_truncates_to_max_length() -> None:
    slug = slugify("word " * 40, max_length=12)
    assert len(slug) <= 12
    assert not slug.startswith("-")


def test_long_titles_differing_only_at_the_end_do_not_collide() -> None:
    prefix = "Measuring What Matters: Observability, Metrics, and Building a Semantic Caching Agent"
    part1, part3 = slugify(prefix + " - Part 1"), slugify(prefix + " - Part 3")
    assert part1 != part3
    assert len(part1) <= 80
    assert part1.startswith("measuring-what-matters")


def test_hashtags_are_deduplicated_case_insensitively_in_order() -> None:
    assert extract_hashtags("#RAG and #LLM, then #rag again") == ["RAG", "LLM"]


def test_hashtags_ignore_numbers_and_html_entities() -> None:
    assert extract_hashtags("issue #123 and &#39; but #AI2") == ["AI2"]


def test_hashtag_glued_to_a_link_is_still_found() -> None:
    assert extract_hashtags("https://lnkd.in/erGaGnNp#ArtificialIntelligence") == [
        "ArtificialIntelligence"
    ]


def test_urls_strip_trailing_punctuation_and_duplicates() -> None:
    text = "See https://example.com/a. Also (https://example.com/b) and https://example.com/a"
    assert extract_urls(text) == ["https://example.com/a", "https://example.com/b"]


def test_glued_lnkd_in_links_are_repaired_from_real_paste() -> None:
    post = fixture_text("semantic_caching_part3", "post.txt")
    assert extract_urls(post) == [
        "https://lnkd.in/euyuNU9y",
        "https://lnkd.in/e-fJ7GXi",
        "https://lnkd.in/erGaGnNp",
    ]


def test_real_post_hashtags() -> None:
    post = fixture_text("semantic_caching_part3", "post.txt")
    assert extract_hashtags(post) == [
        "ArtificialIntelligence",
        "MachineLearning",
        "LLM",
        "SoftwareArchitecture",
        "RAG",
        "AIAgents",
        "LangGraph",
        "Observability",
    ]


def test_series_part_detection() -> None:
    assert detect_series_part("Semantic Caching in LangGraph - Part 3") == 3
    assert detect_series_part("part-12: the end") == 12
    assert detect_series_part("A departure from the norm") is None


def test_content_size_ignores_markup_links_and_hashtags() -> None:
    plain = "Hit rate matters"
    marked = "## **Hit rate** matters\n\n- https://lnkd.in/abcdefgh #RAG"
    assert content_size(marked) == content_size(plain) == 14
