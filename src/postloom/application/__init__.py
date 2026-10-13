"""The application layer: use cases and the ports (interfaces) they depend on.

May import ``postloom.domain``; must never import ``postloom.adapters`` or
``postloom.interfaces``. Concrete implementations are wired in ``postloom.bootstrap``.
"""
