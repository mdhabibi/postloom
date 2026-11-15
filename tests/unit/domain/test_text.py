import pytest

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


def test_canonical_url_ignores_scheme_www_tracking_and_trailing_slash() -> None:
    from postloom.domain.text import canonical_url

    plain = canonical_url("linkedin.com/pulse/my-article-abc")
    assert plain == "linkedin.com/pulse/my-article-abc"
    assert canonical_url("https://www.LinkedIn.com/pulse/my-article-abc/?trk=x#top") == plain
    assert canonical_url("http://linkedin.com/pulse/other") != plain


def test_containment_tells_versions_of_one_text_from_different_texts() -> None:
    from postloom.domain.text import containment

    article = fixture_text("semantic_caching_part3", "article.txt")
    longer = article + "\n\n## A new section\n\nSomething added in a later edit of the article."
    wrapped = "Jane Example\nPublished Oct 12\n\n" + article + "\n\nLike Comment Share"
    other = "A completely different article about training convolutional networks. " * 30
    assert containment(article, longer) > 0.95
    assert containment(article, wrapped) > 0.95
    assert containment(article, other) < 0.05
    assert containment("", article) == 0.0


def test_containment_ignores_markdown_case_and_punctuation() -> None:
    from postloom.domain.text import containment

    pasted = "Hit rate matters. Measure precision and recall before you ship the cache."
    restored = (
        "## Hit rate matters\n\nMeasure **precision** and *recall* before you ship the cache!"
    )
    assert containment(pasted, restored) == 1.0


def test_only_web_links_are_accepted() -> None:
    from postloom.domain.errors import InvalidUrlError
    from postloom.domain.text import web_url

    assert web_url("linkedin.com/pulse/x") == "https://linkedin.com/pulse/x"
    assert web_url(" http://example.com/a ") == "http://example.com/a"
    assert web_url("") is None and web_url(None) is None
    for bad in (
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html,x",
        "file:///etc/x",
        "ftp://example.com/x",
        "https://",
    ):
        with pytest.raises(InvalidUrlError):
            web_url(bad)


# -- slugs: ids for every language ----------------------------------------------------
@pytest.mark.parametrize(
    ("text", "slug"),
    [  # Latin text: exactly what earlier versions produced, so stored ids stay valid
        ("Measuring What Matters - Part 3", "measuring-what-matters-part-3"),
        ("José Núñez", "jose-nunez"),
        ("Straße", "strae"),
        ("Łukasz Żółć", "ukasz-zoc"),
        ("½ price ¡now!", "12-price-now"),
        ("C++ & Rust", "c-rust"),
        ("🚀🚀", "untitled"),
        ("", "untitled"),
    ],
)
def test_latin_slugs_are_unchanged(text: str, slug: str) -> None:
    assert slugify(text) == slug


def test_names_in_other_scripts_get_ids_of_their_own() -> None:
    names = ["علی رضایی", "مریم احمدی", "王伟", "李娜", "Иван Петров", "नमस्ते दुनिया"]
    slugs = [slugify(name) for name in names]
    assert len(set(slugs)) == len(names) and "untitled" not in slugs
    assert slugify("علی رضایی") == "علی-رضایی"
    assert slugify("Иван Петров") == slugify("иван петров")  # case doesn't matter
    assert slugify("AI 智能 agents") == "ai-智能-agents"


def test_slugs_never_name_a_windows_device() -> None:
    assert slugify("Con") == "con-0" and slugify("NUL") == "nul-0"


def test_questions_in_unspaced_scripts_are_judged_by_their_subject() -> None:
    from postloom.domain.text import significant_terms, term_coverage, unspaced_pieces

    chinese = "语义缓存可以重复使用大语言模型的答案"
    assert unspaced_pieces("缓存是") == ["缓存", "存是"]
    assert significant_terms("缓存是什么\uff1f") == ["缓存"]  # "what is" is grammar
    assert term_coverage(significant_terms("缓存是什么\uff1f"), chinese) == 1.0
    assert term_coverage(significant_terms("什么是量子计算"), chinese) == 0.0
    japanese = "セマンティックキャッシュは大規模言語モデルの回答を再利用します"
    assert term_coverage(significant_terms("キャッシュとは何ですか"), japanese) >= 0.8
    assert significant_terms("how does a semantic cache work") == ["semantic", "cache", "work"]
