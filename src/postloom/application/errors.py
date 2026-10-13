"""Errors raised by use cases. Interfaces map them to user-facing messages."""


class ApplicationError(Exception):
    """Base class for use-case failures the user can act on."""


class NoTopicsConfiguredError(ApplicationError):
    """Ingest needs a topic taxonomy; run setup (or SeedTopics) first."""
