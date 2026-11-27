# How well postloom finds answers

postloom answers questions about your library from passages it finds first. If the right
passage isn't among them, the answer is incomplete; if a weak one gets in, the model may
answer from it. This page measures that step on a realistic library, and says how the
numbers were made so anyone can check them.

## The benchmark

A fictional year of LinkedIn writing, built by `scripts/eval/library.py` through
postloom's own code, the way a user would add it:

- **30 articles and 80 posts** from December 2025 to November 2026, on ten subjects
  (semantic caching, evaluating RAG, agents in production, hybrid search, fine-tuning,
  prompt injection, GPU serving, monitoring, vision models, multilingual NLP);
- **about 800 comments** from 24 invented people, most of them ordinary ("Great
  write-up", "Which model did you use?"), with author replies;
- in each subject, **6 facts** placed in exactly one article or post, **4 facts** in one
  person's comment, and **near misses**: sentences that share the vocabulary but not the
  answer ("we also use a similarity of 0.92 to drop near-duplicate documents").

**144 questions**, asked in other words than the text uses:

| Kind | n | Example |
|---|---:|---|
| A detail in one article or post | 60 | *What similarity cut-off did we pick for treating two questions as the same?* (the text says "a cosine threshold of 0.86 for cache hits") |
| A detail in one comment | 40 | *Who found that the threshold has to be lower for German and Polish?* |
| A subject in one month | 10 | *What did I write about semantic caching in March 2026?* |
| A subject across all comments | 10 | *What have people said in the comments about GPU serving and inference cost?* |
| Not in the library | 24 | *How did we handle GDPR deletion requests in the vector store?* |

Sixteen of the 24 questions without an answer are close to the library's subjects, the
hard case: the passages that come back are on topic, just not an answer.

**What is scored** is the set of articles and posts postloom would hand the model, not
the model's answer, so the numbers don't depend on which model you use and are the same
on every run. A question counts as *found* when a right article or post is among them;
*recall* is the share of right ones given (for questions with several); a question with
no answer scores when nothing is given at all.

## Results

With the default English search model (`BAAI/bge-small-en-v1.5`, on your computer):

| | postloom 0.1.0 | postloom 0.2.0 |
|---|---:|---:|
| A detail in one article or post: found | 40% | **65%** |
| A detail in one comment: found | 60% | **88%** |
| A subject in one month: recall | 0.35 | **1.00** |
| A subject across all comments: recall | 0.31 | **0.75** |
| Not in the library: correctly "not found" | 67% | **79%** |
| **All answerable questions: found** | **53%** | **78%** |

What changed, each step measured on this benchmark before it was kept:

1. **Fused search.** Keyword and meaning results are merged by reciprocal rank fusion,
   from the 40 best of each, instead of taking the 8 closest by meaning alone. Before
   any cut-off, plain meaning search already had the right article or post in its top 20
   for 94% of one-source questions; most misses were the selection, not the search.
2. **A lower bar for evidence, a separate decision for "not found".** In 0.1.0 one
   similarity cut-off (0.68) did both jobs, and was too strict for questions asked in
   other words: the right passage was often first, at 0.63 to 0.67, and was thrown away.
   Now a passage counts as evidence from 0.55, and whether the library holds an answer
   at all is decided by a **cross-encoder** (`ms-marco-MiniLM-L-6-v2`, ~80 MB, runs on
   your computer) that reads the question and the best 30 passages together. Its
   threshold was chosen on this benchmark from five rerankers tried; it adds about half
   a second per question.
3. **Breadth.** The best passage of as many articles and posts as fit comes first; a
   second passage of one only while there is room.
4. **Periods.** "In March", "last month", "since spring", "between May and July", "Q2
   2026": a question about a time is answered from what was published then
   (`src/postloom/domain/periods.py`, no model involved).
5. **Broad questions** ("what have people said about...") get 16 sources, one per
   article or post, instead of 8.

## What it doesn't show yet

- **The answers themselves.** Citations are checked mechanically (a cited passage must
  have been given; uncited answers are marked), but whether the model's sentences are
  faithful to the passages is not scored here.
- **Other languages.** The questions are English. With the multilingual search model
  the reranker is off (it reads English) and the similarity cut-off decides "not
  found", which scores 71% found and 67% correctly empty on this benchmark.
- **Your library.** The benchmark is invented, and its questions were written by the
  same person as its text. Real questions are messier; the numbers are a floor to
  improve on, not a promise.
- **Completeness for broad questions** is 0.75: an answer about everything said on a
  subject still sees about three quarters of it.

## Run it yourself

```bash
PYTHONPATH=. uv run python scripts/eval/run.py --embedder local --out .eval
```

It downloads the two local models on first run, builds the library in `.eval/home` and
writes `.eval/report.md` with every miss and where the right passage ranked. On GitHub,
the **Retrieval benchmark** workflow runs it whenever the retrieval code changes.
`scripts/eval/compare.py` records several ways of choosing passages side by side, for
trying a new idea before changing the app.
