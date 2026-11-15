"""Domain-level errors. Adapters translate their own failures into these where it matters."""


class DomainError(Exception):
    """Base class for every rule violation raised by the domain layer."""


class InvalidProfileUrlError(DomainError):
    """Raised when a string is not a LinkedIn member profile URL (``linkedin.com/in/<slug>``)."""


class InvalidEdgeError(DomainError):
    """Raised when an edge would connect node kinds that the graph schema does not allow."""


class EmptyContentError(DomainError):
    """Raised when required text (an article body, a comment) is empty."""


class InvalidUrlError(DomainError):
    """A link that isn't a web address."""


class InvalidKeyError(DomainError):
    """A key that can't be an identity: keys become file names, so they must be plain."""
