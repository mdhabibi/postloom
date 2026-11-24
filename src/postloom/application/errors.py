"""Errors raised by use cases and ports. Interfaces map them to user-facing messages.

Adapters translate provider-specific failures (HTTP codes, SDK exceptions) into these,
so use cases and the UI never depend on a particular provider.
"""


class ApplicationError(Exception):
    """Base class for failures the user can act on. The message is shown to them."""


class NoTopicsConfiguredError(ApplicationError):
    """Ingest needs a topic taxonomy; run setup (or SeedTopics) first."""


class NotConfiguredError(ApplicationError):
    """A feature needs configuration that is missing (e.g. no API key)."""


class ProviderError(ApplicationError):
    """A model provider call failed."""


class ProviderAuthError(ProviderError):
    """The API key is missing, invalid or lacks access to the model."""


class ProviderUnavailableError(ProviderError):
    """Rate-limited, overloaded or unreachable, even after retrying."""


class ExtractionError(ProviderError):
    """The model answered, but not with usable structured content."""


class BudgetExceededError(ApplicationError):
    """The user's monthly budget is spent; no paid model calls until they raise it."""


class MediaTooLargeError(ApplicationError):
    """An uploaded image or video is bigger than postloom accepts."""
