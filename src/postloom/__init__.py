"""postloom: a local-first knowledge graph of your LinkedIn writing and the people it reaches."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("postloom")
except PackageNotFoundError:  # running from a source checkout without installing
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
