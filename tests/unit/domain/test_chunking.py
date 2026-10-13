from postloom.domain.chunking import chunk_markdown
from postloom.domain.graph import NodeId
from postloom.domain.text import excerpt

NODE = NodeId("article:leakage")

ARTICLE = """\
You hold out 20% of your data, train, and evaluate.

## 📐 The Mechanics

A test score estimates the model's true risk.

### Preprocessing

Normalization statistics computed before the split leak.

## 🛠️ Code

```python
## this comment is not a heading
mean = X[train_idx].mean(0)
```
"""


def test_chunks_follow_the_authors_sections() -> None:
    chunks = chunk_markdown(NODE, "Data Leakage", ARTICLE)
    assert [(c.index, c.heading) for c in chunks] == [
        (0, ""),
        (1, "📐 The Mechanics"),
        (2, "Preprocessing"),
        (3, "🛠️ Code"),
    ]
    assert chunks[0].text == "You hold out 20% of your data, train, and evaluate."
    assert all(c.title == "Data Leakage" and c.node == NODE for c in chunks)


def test_headings_inside_code_blocks_are_not_section_breaks() -> None:
    code = chunk_markdown(NODE, "t", ARTICLE)[-1]
    assert "## this comment is not a heading" in code.text
    assert code.text.startswith("```python") and code.text.endswith("```")


def test_long_sections_split_between_paragraphs_never_inside_code() -> None:
    code_block = "```python\n" + "\n\n".join(f"x{i} = {i}" for i in range(40)) + "\n```"
    paragraphs = "\n\n".join(f"Paragraph {i} " + "word " * 30 for i in range(6))
    chunks = chunk_markdown(NODE, "t", f"## Long\n\n{paragraphs}\n\n{code_block}", max_chars=400)

    assert len(chunks) > 2
    assert all(c.heading == "Long" for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    with_code = [c for c in chunks if "```python" in c.text]
    assert len(with_code) == 1 and with_code[0].text.endswith("```")


def test_empty_sections_produce_no_chunks() -> None:
    chunks = chunk_markdown(NODE, "t", "## Empty\n\n## Full\n\nText")
    assert [c.heading for c in chunks] == ["Full"]


def test_content_hash_changes_only_with_content() -> None:
    first = chunk_markdown(NODE, "t", "## A\n\nSame text")[0]
    again = chunk_markdown(NODE, "t", "## A\n\nSame text")[0]
    edited = chunk_markdown(NODE, "t", "## A\n\nSame text!")[0]
    renamed = chunk_markdown(NODE, "New title", "## A\n\nSame text")[0]
    assert first.content_hash == again.content_hash
    assert len({first.content_hash, edited.content_hash, renamed.content_hash}) == 3


def test_excerpt_centres_on_the_query_and_cuts_on_words() -> None:
    text = " ".join(f"filler{i}" for i in range(80)) + " MinHash finds near duplicates. " + (
        "tail " * 80
    )
    snippet = excerpt(text, "how does minhash work", width=120)
    assert "MinHash" in snippet
    assert snippet.startswith("...") and snippet.endswith("...")
    assert len(snippet) <= 126


def test_short_text_excerpt_is_the_whole_text() -> None:
    assert excerpt("Short   text\nhere", "anything") == "Short text here"
