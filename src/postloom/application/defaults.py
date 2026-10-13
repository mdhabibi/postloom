"""Defaults offered by the first-run setup. Users can edit, remove and add topics."""

from postloom.domain.content import Topic

DEFAULT_TOPICS: tuple[Topic, ...] = (
    Topic("Machine Learning", "Classical ML, training, evaluation and feature engineering."),
    Topic("Deep Learning", "Neural network architectures, training dynamics, PyTorch."),
    Topic("LLMs", "Large language models: prompting, fine-tuning, inference, evaluation."),
    Topic("RAG", "Retrieval-augmented generation, embeddings, vector and graph retrieval."),
    Topic("AI Agents", "Agentic workflows, tool use, memory, orchestration frameworks."),
    Topic("MLOps", "Deployment, observability, caching, cost and infrastructure for ML."),
    Topic("Computer Vision", "Image and video models, multimodal vision-language systems."),
    Topic("NLP", "Language processing beyond LLMs: classic NLP, tokenization, linguistics."),
)
