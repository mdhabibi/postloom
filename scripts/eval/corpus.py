# ruff: noqa: E501  (the corpus is prose: one sentence per line reads better than wrapped)
"""A fictional year of LinkedIn writing, for measuring how well postloom finds answers.

Everything here is invented: the author, the people and the numbers. Each topic has
*facts* (a detail that appears in exactly one article or post, with a question asked in
other words), *near misses* (sentences that share the vocabulary but not the answer),
*comment facts* (a detail one named person wrote in one comment) and filler, so that the
right passage has to be told apart from many that look alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field

OWNER = "Alex Morgan"
OWNER_LINE = "ML engineer | Writing about LLM systems in production"


@dataclass(frozen=True)
class Fact:
    text: str
    question: str


@dataclass(frozen=True)
class CommentFact:
    person: str
    text: str
    question: str


@dataclass(frozen=True)
class Theme:
    key: str
    phrase: str
    """How a question names the subject: "semantic caching"."""
    topics: tuple[str, ...]
    """postloom topics it is filed under."""
    titles: tuple[str, str, str]
    """Its three articles, oldest first."""
    headings: tuple[str, ...]
    posts: tuple[str, ...]
    """Openings for its posts."""
    filler: tuple[str, ...]
    facts: tuple[Fact, ...]
    near_misses: tuple[str, ...]
    comment_facts: tuple[CommentFact, ...]
    comments: tuple[str, ...]
    """Ordinary comments about the subject, without a fact to find."""
    people: tuple[str, ...] = field(default=())


THEMES: tuple[Theme, ...] = (
    Theme(
        key="caching",
        phrase="semantic caching",
        topics=("LLMs", "MLOps"),
        titles=(
            "Semantic caching cut our LLM bill",
            "Choosing a cache threshold from our own logs",
            "When the cache gave the wrong answer",
        ),
        headings=(
            "Why we cached at all",
            "What we measured",
            "What we changed",
            "What I'd do again",
        ),
        posts=(
            "A quick lesson from running a semantic cache in front of our model.",
            "People keep asking how we decide what goes into the cache.",
            "One more note on caching LLM answers.",
        ),
        filler=(
            "Most of our traffic was the same twenty questions asked in slightly different words.",
            "A cache in front of the model is cheap to build and easy to get wrong.",
            "We log every hit together with the cached question it matched.",
            "The hard part is not the cache itself but deciding when two questions are the same.",
            "Invalidation matters as much as hit rate.",
            "Support teams noticed the change before our dashboards did.",
        ),
        facts=(
            Fact(
                "After replaying a week of real traffic we settled on a cosine threshold of 0.86 for cache hits.",
                "What similarity cut-off did we pick for treating two questions as the same?",
            ),
            Fact(
                "The cache brought our monthly model spend down from $5,200 to $3,100.",
                "How much money did the cache save us each month?",
            ),
            Fact(
                "We flush the whole cache every time the prompt template changes, which happened 14 times in the spring.",
                "When do we throw away everything that was cached?",
            ),
            Fact(
                "Cached answers expire after 72 hours for anything that quotes prices or stock levels.",
                "How long do we keep answers that mention prices?",
            ),
            Fact(
                "Hit rate settled at 41 percent once the support macros were included.",
                "What share of requests ended up being served from the cache?",
            ),
            Fact(
                "The worst incident was the cache serving last year's refund policy for two days.",
                "What was the most embarrassing mistake the cache made?",
            ),
        ),
        near_misses=(
            "We also use a similarity of 0.92 to drop near-duplicate documents before indexing.",
            "Our embedding cache for documents is separate and never expires.",
            "A cache threshold that looks safe on test data can still be wrong in production.",
        ),
        comment_facts=(
            CommentFact(
                "Lena Okafor",
                "Did your threshold hold for multilingual queries? Ours dropped to 0.81 for German and Polish.",
                "Who found that the threshold has to be lower for German and Polish?",
            ),
            CommentFact(
                "Samir Haddad",
                "We key the cache on the user's plan tier too, otherwise free users got answers written for enterprise customers.",
                "Who said the cache must also take the customer's plan into account?",
            ),
            CommentFact(
                "Oskar Bremer",
                "At Quillbase we cache only the retrieval step, never the final answer, and it still saved 30 percent.",
                "Which company caches retrieval results instead of final answers?",
            ),
            CommentFact(
                "Mira Castell",
                "In health questions we turned caching off entirely after one stale dosage answer.",
                "Who disabled caching because of a medical answer that went out of date?",
            ),
        ),
        comments=(
            "Great write-up, the part about invalidation is underrated.",
            "We are about to add a cache, this came at the right time.",
            "How do you monitor wrong hits without reading every log line?",
            "Saving this for our next architecture review.",
        ),
    ),
    Theme(
        key="rag-eval",
        phrase="evaluating RAG",
        topics=("RAG", "LLMs"),
        titles=(
            "Evaluating RAG without a labelled set",
            "LLM-as-a-judge, and when not to trust it",
            "The 50 questions that tell us if retrieval is broken",
        ),
        headings=("The problem", "Our setup", "Results", "Lessons"),
        posts=(
            "How do you know your retrieval is still good after you change the chunking?",
            "A short thread on judging RAG answers with a model.",
            "Our evaluation set grew again this week.",
        ),
        filler=(
            "Nobody on the team wanted to label a thousand answers by hand.",
            "Retrieval quality and answer quality fail in different ways.",
            "We check retrieval and generation separately before looking at the end result.",
            "A metric nobody looks at is not a metric.",
            "Every regression we caught came from a change that looked harmless.",
            "We run the suite on every pull request that touches prompts or chunking.",
        ),
        facts=(
            Fact(
                "Our golden set is 50 questions, each with the passage that must be retrieved for it.",
                "How many test questions are in our core retrieval benchmark?",
            ),
            Fact(
                "The model judge agreed with two human reviewers 82 percent of the time.",
                "How often did the automated grader match people?",
            ),
            Fact(
                "Switching from 1,000-character to 400-token chunks raised recall at 5 from 0.71 to 0.84.",
                "What happened to retrieval when we changed the chunk size?",
            ),
            Fact(
                "The judge consistently preferred longer answers, so we cap answers at 120 words before grading.",
                "What bias did the grading model have, and how did we correct it?",
            ),
            Fact(
                "A full evaluation run costs about $1.40 and takes six minutes.",
                "How expensive is it to run the whole test suite once?",
            ),
            Fact(
                "We found that 9 of the 50 questions had become unanswerable after a documentation cleanup.",
                "How many benchmark questions stopped having an answer after the docs were tidied?",
            ),
        ),
        near_misses=(
            "Recall at 10 hardly changed, which is why we report recall at 5.",
            "Our search team uses a separate set of 200 queries for the website.",
            "A judge model is only as good as the rubric you give it.",
        ),
        comment_facts=(
            CommentFact(
                "Ines Kowal",
                "We ask the judge to quote the sentence it relied on; it cut false passes roughly in half.",
                "Who suggested making the grader quote its evidence?",
            ),
            CommentFact(
                "Hana Lindqvist",
                "In my thesis the judge's agreement fell to 64 percent on questions with numbers in them.",
                "Who reported that automated grading is much worse on numeric questions?",
            ),
            CommentFact(
                "Tomas Arends",
                "At Copperline Labs we rotate three judge models and only trust verdicts where two agree.",
                "Which company uses a majority vote between several grading models?",
            ),
            CommentFact(
                "Priya Raman",
                "We seed the golden set from real support tickets every quarter so it does not go stale.",
                "Who refreshes their test questions from support tickets?",
            ),
        ),
        comments=(
            "This is the most practical evaluation post I have read this year.",
            "Do you publish the rubric anywhere?",
            "We struggle with exactly this, thanks for sharing numbers.",
            "Separate retrieval and generation metrics, yes, a hundred times.",
        ),
    ),
    Theme(
        key="agents",
        phrase="AI agents in production",
        topics=("AI Agents", "LLMs"),
        titles=(
            "Agents in production: what broke first",
            "Giving an agent fewer tools made it better",
            "How we let an agent write to the database, safely",
        ),
        headings=("Context", "What went wrong", "The fix", "Open questions"),
        posts=(
            "Agents look great in demos. Here is what happened in week one.",
            "One rule we added to every agent we ship.",
            "A small agent change with a big effect.",
        ),
        filler=(
            "The demo worked on the first try, which should have worried us.",
            "Most failures were not the model reasoning badly but tools returning surprises.",
            "Every tool call is logged with its arguments and how long it took.",
            "We review a sample of agent runs by hand every Friday.",
            "Timeouts caused more trouble than wrong answers.",
            "The agent is only allowed to do what a junior colleague could do unsupervised.",
        ),
        facts=(
            Fact(
                "Cutting the agent from 23 tools to 7 raised task success from 58 to 77 percent.",
                "What happened when we reduced the number of tools the agent could use?",
            ),
            Fact(
                "The first outage came from the agent retrying a failed payment lookup 400 times in a loop.",
                "What caused the agent's first production incident?",
            ),
            Fact(
                "Any tool that writes data needs a dry run first, and a person approves anything above 50 rows.",
                "When does a human have to approve what the agent changes?",
            ),
            Fact(
                "Median run time is 11 seconds, but the slowest one percent takes over two minutes.",
                "How long does a typical agent run take?",
            ),
            Fact(
                "We cap every run at 15 tool calls and stop with a clear message when it is reached.",
                "What limit did we put on how many steps an agent may take?",
            ),
            Fact(
                "The search tool returning HTML instead of JSON broke 12 percent of runs for a whole afternoon.",
                "Which tool returned the wrong format and how many runs did it break?",
            ),
        ),
        near_misses=(
            "Our older chatbot had 30 intents, which is a different kind of tool list.",
            "A retry with backoff is fine for reads and dangerous for writes.",
            "Tool descriptions matter more than the system prompt.",
        ),
        comment_facts=(
            CommentFact(
                "Ravi Thorne",
                "We give every agent a separate database user with read-only rights except for one staging table.",
                "Who restricts agents with their own read-only database account?",
            ),
            CommentFact(
                "Jonah Pike",
                "Our agents run in a sandbox with no network except an allowlist of six internal APIs.",
                "Who limits agents to a short list of internal APIs?",
            ),
            CommentFact(
                "Aiko Brandt",
                "At Fernway Retail the agent drafts refunds but a person clicks send; refunds went out 3 times faster.",
                "Which retailer lets an agent draft refunds that a person then approves?",
            ),
            CommentFact(
                "Lena Okafor",
                "Did you try letting the model pick tools from embeddings of their descriptions? It helped us past 40 tools.",
                "Who suggested choosing tools by embedding their descriptions?",
            ),
        ),
        comments=(
            "Fewer tools, better agent. I keep relearning this.",
            "What do you use for tracing agent runs?",
            "The approval step is the part most teams skip.",
            "Really honest post, thank you.",
        ),
    ),
    Theme(
        key="vector-search",
        phrase="vector search and hybrid retrieval",
        topics=("RAG",),
        titles=(
            "Hybrid search beat pure vector search for us",
            "Do you need a vector database?",
            "Reranking: the 40 milliseconds worth paying",
        ),
        headings=("Why this matters", "The experiment", "Numbers", "Recommendation"),
        posts=(
            "Hot take on vector databases.",
            "We changed how we rank search results this week.",
            "Keyword search is not dead.",
        ),
        filler=(
            "Exact product codes are where pure vector search falls over.",
            "We combine keyword and vector results instead of choosing one.",
            "Most teams overestimate how much data they have.",
            "Latency budgets decide more architecture than accuracy does.",
            "The index is rebuilt every night from the source documents.",
            "Users search with abbreviations nobody thought to embed.",
        ),
        facts=(
            Fact(
                "Combining BM25 and embeddings with reciprocal rank fusion found the right document first 74 percent of the time, against 61 percent for embeddings alone.",
                "How much better was it to mix keyword and vector search than to use vectors only?",
            ),
            Fact(
                "With 180,000 chunks, plain SQLite with brute-force cosine answered in 38 milliseconds.",
                "How fast was a simple database without a vector index on our data size?",
            ),
            Fact(
                "Adding a cross-encoder reranker over the top 30 results cost 40 ms and fixed a third of the wrong top answers.",
                "What did the reranker cost and what did it fix?",
            ),
            Fact(
                "Searches for part numbers like XR-2210 failed completely until we added keyword search.",
                "Which kind of query did pure semantic search get completely wrong?",
            ),
            Fact(
                "We moved off a hosted vector database and saved $900 a month.",
                "How much did dropping the managed vector store save?",
            ),
            Fact(
                "Our embeddings are 384 dimensions; going to 1,024 improved recall by only two points.",
                "Did larger embeddings make a real difference?",
            ),
        ),
        near_misses=(
            "Reciprocal rank fusion has one parameter, and 60 is a fine default.",
            "The hosted service was fast, it was just more than we needed.",
            "Rerankers are slower than embeddings because they read query and passage together.",
        ),
        comment_facts=(
            CommentFact(
                "Samir Haddad",
                "We saw the same with part numbers; we now boost exact matches in titles by a factor of three.",
                "Who triples the weight of exact title matches?",
            ),
            CommentFact(
                "Oskar Bremer",
                "Quillbase still runs a vector database, but only because we have 40 million chunks.",
                "Which company keeps a vector database because of its scale?",
            ),
            CommentFact(
                "Hana Lindqvist",
                "Try a multilingual reranker; ours lifted German queries by 9 points.",
                "Who recommended a multilingual reranker for German?",
            ),
            CommentFact(
                "Marco Silva",
                "We cache reranker scores for popular queries, which took p95 latency from 210 to 95 ms.",
                "Who cached reranking results to cut latency?",
            ),
        ),
        comments=(
            "Hybrid search should be the default in every tutorial.",
            "Which reranker model do you use?",
            "Nice to see real latency numbers.",
            "This matches what we found too.",
        ),
    ),
    Theme(
        key="fine-tuning",
        phrase="fine-tuning",
        topics=("LLMs", "Deep Learning"),
        titles=(
            "We fine-tuned a small model instead of prompting a big one",
            "LoRA on a single GPU: what it really takes",
            "Fine-tuning didn't fix our hallucinations",
        ),
        headings=("Starting point", "Training", "Evaluation", "Verdict"),
        posts=(
            "Is fine-tuning still worth it in 2026?",
            "A small model surprised us this week.",
            "Notes from our latest training run.",
        ),
        filler=(
            "Prompting got us 80 percent of the way in a week.",
            "Data quality mattered more than any hyperparameter.",
            "We kept a held-out set the training code never saw.",
            "The smaller model is easier to host and cheaper to run.",
            "Most of the work was cleaning examples, not training.",
            "We compared against the prompted baseline on the same questions.",
        ),
        facts=(
            Fact(
                "A 3-billion-parameter model fine-tuned on 4,200 examples matched the large model on our classification task.",
                "How many training examples did the small model need to catch up?",
            ),
            Fact(
                "Training with LoRA rank 16 took 2 hours 40 minutes on one 24 GB GPU.",
                "How long did training take and on what hardware?",
            ),
            Fact(
                "Fine-tuning lowered made-up citations only from 9 to 7 percent; retrieval fixed the rest.",
                "Did training reduce invented references much?",
            ),
            Fact(
                "Serving the small model costs about one twelfth of calling the large one.",
                "How much cheaper is it to run the tuned model?",
            ),
            Fact(
                "We threw away 30 percent of the collected examples because annotators disagreed.",
                "What fraction of the data was discarded and why?",
            ),
            Fact(
                "A learning rate of 2e-4 overfit within one epoch; 5e-5 was stable.",
                "Which learning rate turned out to be too high?",
            ),
        ),
        near_misses=(
            "Rank 8 was too small for the longer outputs.",
            "The large model is still better at open-ended writing.",
            "Our first training run used a learning rate schedule we copied without checking.",
        ),
        comment_facts=(
            CommentFact(
                "Mira Castell",
                "At Helios Health we got the same result with 2,000 examples after deduplicating them carefully.",
                "Who reached the same result with only 2,000 examples?",
            ),
            CommentFact(
                "Jonah Pike",
                "We run LoRA jobs on spot instances; one interruption cost us a whole night until we added checkpoints every 200 steps.",
                "Who lost a night of training to a spot instance interruption?",
            ),
            CommentFact(
                "Nora Feld",
                "Distilling from the big model's answers worked better for us than human labels.",
                "Who preferred training on the larger model's outputs over human labels?",
            ),
            CommentFact(
                "Tomas Arends",
                "Copperline Labs fine-tunes only the classifier head for routing and keeps the base frozen.",
                "Which company keeps the base model frozen and trains only a small head?",
            ),
        ),
        comments=(
            "The data cleaning point is the real lesson here.",
            "Which base model did you start from?",
            "Thanks for sharing the cost comparison.",
            "Bookmarked for our next planning session.",
        ),
    ),
    Theme(
        key="security",
        phrase="prompt injection and LLM security",
        topics=("LLMs",),
        titles=(
            "Prompt injection is a product problem, not a prompt problem",
            "What our red team found in one week",
            "Treat retrieved text as untrusted input",
        ),
        headings=("The risk", "What happened", "Defences", "Still unsolved"),
        posts=(
            "A reminder that every document you retrieve can talk back to your model.",
            "Our red team week is over. Some notes.",
            "Security review for LLM features, the short version.",
        ),
        filler=(
            "There is no prompt that makes injection impossible.",
            "The safest tool is the one the model cannot call.",
            "We assume any text from outside can contain instructions.",
            "Output filtering catches some attacks and misses the clever ones.",
            "Least privilege applies to models as much as to people.",
            "Logging every tool call made the investigations possible.",
        ),
        facts=(
            Fact(
                "A hidden line in a supplier PDF made the assistant email a summary to an outside address during testing.",
                "How did a document trick the assistant into sending data out?",
            ),
            Fact(
                "The red team found 17 working injections in five days; 11 came through retrieved documents.",
                "How many successful attacks did the red team find, and where did most come from?",
            ),
            Fact(
                "We removed the model's ability to send email entirely; drafts now wait in an outbox for a person.",
                "What did we take away from the assistant after the incident?",
            ),
            Fact(
                "Retrieved passages are wrapped in markers and the model is told they are data, which stopped 6 of the 17 attacks.",
                "How effective was marking retrieved text as data?",
            ),
            Fact(
                "Markdown images with tracking URLs were the quietest way data leaked.",
                "Which formatting trick leaked information without anyone noticing?",
            ),
            Fact(
                "Every new tool now needs a security review that takes about two days.",
                "How long does approving a new tool take now?",
            ),
        ),
        near_misses=(
            "Phishing emails to staff are still our most common security incident.",
            "We also scan uploaded files for malware, which is a separate problem.",
            "A system prompt is not a security boundary.",
        ),
        comment_facts=(
            CommentFact(
                "Ravi Thorne",
                "We strip all links from model output unless the domain is on an allowlist of 12 sites.",
                "Who removes links from answers unless the site is approved?",
            ),
            CommentFact(
                "Aiko Brandt",
                "Fernway Retail had a product review that told the shopping assistant to recommend a competitor.",
                "Which retailer saw a customer review hijack its shopping assistant?",
            ),
            CommentFact(
                "Priya Raman",
                "We run a canary token in every system prompt and alert if it ever appears in output.",
                "Who plants a secret marker in prompts to detect leaks?",
            ),
            CommentFact(
                "Marco Silva",
                "Our bug bounty paid out for an injection hidden in white text on a white background.",
                "Who paid a bug bounty for invisible text in a document?",
            ),
        ),
        comments=(
            "Every team building assistants should read this.",
            "The outbox pattern is such a simple fix.",
            "Did you publish the test cases?",
            "Scary and useful, thanks.",
        ),
    ),
    Theme(
        key="serving",
        phrase="GPU serving and inference cost",
        topics=("MLOps",),
        titles=(
            "Self-hosting an open model: the real bill",
            "Batching requests doubled our throughput",
            "Why our GPUs sat idle at night",
        ),
        headings=("Background", "Setup", "What it cost", "Takeaways"),
        posts=(
            "Hosting your own model is cheaper until it isn't.",
            "A throughput trick worth knowing.",
            "GPU bills, again.",
        ),
        filler=(
            "Utilisation is the number that decides the bill.",
            "Traffic follows office hours almost exactly.",
            "Quantisation was the cheapest win we had.",
            "We measure cost per thousand answers, not per hour.",
            "Cold starts are acceptable for batch jobs and painful for chat.",
            "Autoscaling on queue length worked better than on CPU.",
        ),
        facts=(
            Fact(
                "Two L4 GPUs served our 8-billion-parameter model for about $1,150 a month at 60 percent utilisation.",
                "What hardware did we run the model on and what did it cost per month?",
            ),
            Fact(
                "Continuous batching raised throughput from 14 to 31 requests per second on the same GPU.",
                "How much did batching improve the number of requests we could handle?",
            ),
            Fact(
                "Scaling to zero between 10 pm and 6 am cut the GPU bill by 38 percent.",
                "How much did switching the GPUs off at night save?",
            ),
            Fact(
                "4-bit quantisation lost 1.5 points on our evaluation and halved the memory needed.",
                "What did quantising the model cost in quality?",
            ),
            Fact(
                "Cold start for the model container is 95 seconds, mostly loading weights.",
                "How long does it take for a new model server to be ready?",
            ),
            Fact(
                "Below roughly 2 million tokens a day the hosted API was cheaper than our own GPUs.",
                "At what volume does self-hosting stop being worth it?",
            ),
        ),
        near_misses=(
            "Our training cluster uses A100s, which is a different budget.",
            "Batch size 32 was where latency started to hurt.",
            "We also tried 8-bit quantisation, which changed almost nothing.",
        ),
        comment_facts=(
            CommentFact(
                "Jonah Pike",
                "Keep one warm replica during the day; our users hated the 90-second cold start.",
                "Who recommended always keeping one model server running?",
            ),
            CommentFact(
                "Oskar Bremer",
                "Quillbase moved summarisation to a nightly batch job and cut GPU hours by half.",
                "Which company moved summaries to a night-time batch?",
            ),
            CommentFact(
                "Nora Feld",
                "Speculative decoding gave us another 1.8x on long answers.",
                "Who sped up long answers with speculative decoding?",
            ),
            CommentFact(
                "Samir Haddad",
                "Our break-even was closer to 5 million tokens a day once we counted on-call time.",
                "Who said self-hosting only pays off at a much higher volume once people's time is counted?",
            ),
        ),
        comments=(
            "Cost per thousand answers is the right unit.",
            "Which serving framework do you use?",
            "Night-time scale to zero is such an easy win.",
            "Super useful breakdown.",
        ),
    ),
    Theme(
        key="observability",
        phrase="monitoring LLM apps",
        topics=("MLOps", "LLMs"),
        titles=(
            "The three dashboards we look at every morning",
            "Tracing an LLM request end to end",
            "Alerts that actually mean something",
        ),
        headings=("Why", "What we track", "An incident", "What changed"),
        posts=(
            "What do you monitor for an LLM feature?",
            "An alert fired this morning and it was right.",
            "One dashboard I wish we had built earlier.",
        ),
        filler=(
            "Latency and cost are easy to measure; quality is not.",
            "Every request carries a trace id from the browser to the model.",
            "We sample one percent of conversations for manual review.",
            "Thumbs-down clicks are noisy but early.",
            "An alert nobody acts on gets deleted.",
            "Dashboards are for questions we already know to ask.",
        ),
        facts=(
            Fact(
                "Our morning dashboard shows p95 latency, cost per conversation and the thumbs-down rate.",
                "Which three numbers do we check first thing each day?",
            ),
            Fact(
                "An alert on answer length caught a prompt regression two hours before any user complained.",
                "How did we notice the broken prompt before customers did?",
            ),
            Fact(
                "The thumbs-down rate jumped from 3 to 9 percent the day a model version changed silently.",
                "What happened to negative feedback when the provider swapped the model?",
            ),
            Fact(
                "Traces showed 70 percent of latency was retrieval, not generation.",
                "Where did most of the waiting time actually go?",
            ),
            Fact(
                "We keep full traces for 14 days and aggregates for a year.",
                "How long do we store detailed request logs?",
            ),
            Fact(
                "We deleted 23 of our 31 alerts after a quarter in which nobody acted on them.",
                "How many alerts did we remove, and why?",
            ),
        ),
        near_misses=(
            "Our web app has its own uptime monitoring that predates the LLM features.",
            "p99 latency is too noisy for us to alert on.",
            "A dashboard per model version helped during migrations.",
        ),
        comment_facts=(
            CommentFact(
                "Ines Kowal",
                "We pin the model version in every request and alert when the provider returns a different one.",
                "Who checks that the provider did not change the model version?",
            ),
            CommentFact(
                "Priya Raman",
                "We track the share of answers that cite no source; it is our earliest quality signal.",
                "Who uses uncited answers as an early warning?",
            ),
            CommentFact(
                "Marco Silva",
                "Retrieval was 80 percent of our latency too, until we moved the index next to the app.",
                "Who fixed slow retrieval by moving the index closer?",
            ),
            CommentFact(
                "Mira Castell",
                "Helios Health reviews every flagged answer within 24 hours, by rule.",
                "Which organisation must review reported answers within a day?",
            ),
        ),
        comments=(
            "Answer length as an alert is clever.",
            "What do you use for tracing?",
            "Deleting alerts is the most underrated SRE skill.",
            "Thanks, sharing with my team.",
        ),
    ),
    Theme(
        key="vision",
        phrase="multimodal and vision models",
        topics=("Computer Vision", "LLMs"),
        titles=(
            "Reading invoices with a vision-language model",
            "When OCR still beats the big model",
            "Describing charts for search",
        ),
        headings=("The task", "Approach", "Accuracy", "Notes"),
        posts=(
            "We tried a vision model on scanned documents.",
            "Charts are text too, if you describe them.",
            "OCR is not dead either.",
        ),
        filler=(
            "Scans are rotated, stained and photographed at angles.",
            "Tables are where most models stumble.",
            "We compare every extracted field with the accounting system.",
            "Images make prompts expensive very quickly.",
            "Small fonts and stamps confuse everything.",
            "A human checks every document the model is unsure about.",
        ),
        facts=(
            Fact(
                "The vision model extracted invoice totals correctly 96.5 percent of the time, against 88 percent for our old OCR pipeline.",
                "How accurate was the new model at reading totals compared to before?",
            ),
            Fact(
                "Each invoice page costs about 1,600 tokens as an image, so we downscale scans to 1,024 pixels first.",
                "Why do we shrink scans before sending them?",
            ),
            Fact(
                "Plain OCR still wins on long tables with more than 40 rows.",
                "In which case is classic text recognition still better?",
            ),
            Fact(
                "Describing every chart in one sentence made 31 old reports findable in search.",
                "How did captions help us find old reports?",
            ),
            Fact(
                "Handwritten notes in margins were read correctly only 52 percent of the time.",
                "How well did the model handle handwriting?",
            ),
            Fact(
                "We route a page to a person whenever the model's confidence is below 0.7.",
                "When does a document go to manual review?",
            ),
        ),
        near_misses=(
            "Our photo search uses a different image model with no text output.",
            "Receipts are a separate project with their own pipeline.",
            "Accuracy on clean PDFs is almost perfect, which tells you little.",
        ),
        comment_facts=(
            CommentFact(
                "Hana Lindqvist",
                "Try asking for the table as CSV first, then the totals; it fixed most of our row mix-ups.",
                "Who suggested extracting tables as CSV before reading totals?",
            ),
            CommentFact(
                "Aiko Brandt",
                "Fernway Retail reads 20,000 delivery notes a day this way.",
                "Which company processes tens of thousands of delivery notes daily?",
            ),
            CommentFact(
                "Nora Feld",
                "Stamps over totals fooled our model until we cropped the stamp area.",
                "Who had trouble with stamps covering the amounts?",
            ),
            CommentFact(
                "Tomas Arends",
                "We keep OCR as a cross-check and flag any field where the two disagree.",
                "Who compares OCR and the vision model and flags disagreements?",
            ),
        ),
        comments=(
            "Great comparison with the old pipeline.",
            "Which model did you use for this?",
            "The confidence routing is a nice touch.",
            "We need exactly this for purchase orders.",
        ),
    ),
    Theme(
        key="multilingual",
        phrase="multilingual NLP and tokenization",
        topics=("NLP", "LLMs"),
        titles=(
            "Your tokenizer is charging you extra for German",
            "Multilingual search with one embedding model",
            "Language detection is harder than it looks",
        ),
        headings=("The observation", "Measurements", "What we did", "Open questions"),
        posts=(
            "A fun fact about tokens and languages.",
            "We added Polish support this month.",
            "Language detection, a short story.",
        ),
        filler=(
            "Most benchmarks are English, our users are not.",
            "Short messages are the hardest to classify.",
            "Mixed-language messages are common in our support chat.",
            "We test every release on five languages.",
            "Translation before search sounded simple and was not.",
            "Names and product terms should never be translated.",
        ),
        facts=(
            Fact(
                "The same support answer costs 1.6 times as many tokens in German as in English and 2.1 times in Polish.",
                "How much more does the same text cost in other languages?",
            ),
            Fact(
                "One multilingual embedding model reached 0.79 recall across five languages, against 0.83 for English alone.",
                "How close did a single model get across languages compared with English?",
            ),
            Fact(
                "Messages under 20 characters were assigned the wrong language 18 percent of the time.",
                "How often did language detection fail on very short messages?",
            ),
            Fact(
                "We stopped translating queries before search; searching in the original language was 6 points better.",
                "Did translating questions first help search?",
            ),
            Fact(
                "Polish support went live in March after adding 600 reviewed examples.",
                "When did we start supporting Polish and what did it take?",
            ),
            Fact(
                "Code-switching between English and Hindi appeared in 12 percent of chats from India.",
                "How common was mixing two languages in one message?",
            ),
        ),
        near_misses=(
            "Our website is translated by a vendor, which is unrelated to the assistant.",
            "Token counts in English vary a lot between models too.",
            "Language detection on long documents is nearly perfect.",
        ),
        comment_facts=(
            CommentFact(
                "Lena Okafor",
                "Northwind Analytics saw the same token tax in Finnish, almost 2.5 times English.",
                "Which company measured a large token cost for Finnish?",
            ),
            CommentFact(
                "Ines Kowal",
                "We let users pick their language once and never detect it again.",
                "Who avoids language detection by asking the user once?",
            ),
            CommentFact(
                "Hana Lindqvist",
                "Byte-level tokenizers make this gap much smaller; worth testing.",
                "Who pointed to byte-level tokenizers as a fix for the cost gap?",
            ),
            CommentFact(
                "Priya Raman",
                "Our Hindi-English chats needed a separate intent model; the general one scored 20 points lower.",
                "Who needed a dedicated model for mixed Hindi and English messages?",
            ),
        ),
        comments=(
            "The token tax is real and nobody talks about it.",
            "Which embedding model did you use?",
            "Short messages are the worst, agreed.",
            "Great to see non-English numbers.",
        ),
    ),
)

PEOPLE: dict[str, tuple[str, tuple[str, ...]]] = {
    # name: (headline, themes they comment on)
    "Lena Okafor": (
        "Staff ML Engineer at Northwind Analytics",
        ("caching", "agents", "multilingual"),
    ),
    "Samir Haddad": (
        "Research Engineer, retrieval and ranking",
        ("caching", "vector-search", "serving"),
    ),
    "Oskar Bremer": ("CTO at Quillbase", ("caching", "vector-search", "serving")),
    "Mira Castell": ("Data Scientist, Helios Health", ("caching", "fine-tuning", "observability")),
    "Ines Kowal": ("Product Manager, AI assistants", ("rag-eval", "observability", "multilingual")),
    "Hana Lindqvist": (
        "PhD student in NLP",
        ("rag-eval", "vector-search", "vision", "multilingual"),
    ),
    "Tomas Arends": ("Founder at Copperline Labs", ("rag-eval", "fine-tuning", "vision")),
    "Priya Raman": (
        "QA lead for conversational AI",
        ("rag-eval", "security", "observability", "multilingual"),
    ),
    "Ravi Thorne": ("Security Engineer | LLM red teaming", ("agents", "security")),
    "Jonah Pike": ("Platform Engineer | Kubernetes and GPUs", ("agents", "fine-tuning", "serving")),
    "Aiko Brandt": ("Head of AI at Fernway Retail", ("agents", "security", "vision")),
    "Marco Silva": ("Search engineer", ("vector-search", "security", "observability")),
    "Nora Feld": ("ML engineer, inference", ("fine-tuning", "serving", "vision")),
    # People who comment without giving a fact to find: the crowd every real post has.
    "Daniel Ortiz": ("Software engineer", ("caching", "agents", "serving")),
    "Sofia Lind": ("Data engineer", ("rag-eval", "vector-search", "observability")),
    "Ken Watanabe": ("Engineering manager", ("agents", "fine-tuning", "security")),
    "Amara Diallo": ("ML researcher", ("fine-tuning", "vision", "multilingual")),
    "Felix Braun": ("Backend developer", ("caching", "serving", "observability")),
    "Chloe Martin": ("Product designer, AI features", ("rag-eval", "agents", "vision")),
    "Yusuf Kaya": ("Solutions architect", ("vector-search", "security", "serving")),
    "Elena Rossi": ("Data scientist", ("rag-eval", "fine-tuning", "multilingual")),
    "Tom Becker": ("DevOps engineer", ("serving", "observability", "agents")),
    "Grace Owusu": ("Student, applied AI", ("caching", "vision", "multilingual")),
    "Liam Novak": ("Consultant, AI strategy", ("security", "observability", "vector-search")),
}

UNANSWERABLE: tuple[str, ...] = (
    "What did I write about autoscaling Spark clusters on Kubernetes?",
    "Did anyone comment about blockchain or crypto payments?",
    "What did I post about my holiday in Japan?",
    "Which robot vacuum did I recommend?",
    "What did people say about the football World Cup?",
    "How did we migrate from Oracle to PostgreSQL?",
    "What did I write about quantum computing hardware?",
    "Who asked about salary negotiation tips?",
)

GENERIC_COMMENTS: tuple[str, ...] = (
    "Congrats on another great post!",
    "Thanks for sharing this.",
    "Very insightful.",
    "Agree with every word.",
    "Following for part two.",
    "Reposting for my network.",
)
