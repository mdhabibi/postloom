"""Clean-architecture guard rails: dependencies may only point inward.

    interfaces --+
                 +--> application --> domain
    adapters ----+

bootstrap.py is the composition root and may import everything.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "postloom"

OUTER = {"postloom.interfaces", "postloom.bootstrap", "postloom.settings", "postloom.config"}
"""Composition and configuration: only interfaces and the composition root use them."""
FORBIDDEN: dict[str, set[str]] = {
    "domain": {"postloom.application", "postloom.adapters", *OUTER},
    "application": {"postloom.adapters", *OUTER},
    "adapters": OUTER,
}
DOMAIN_ALLOWED_THIRD_PARTY: set[str] = set()  # the domain is pure standard library


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_layer_does_not_import_outer_layers(layer: str) -> None:
    violations = [
        f"{path.relative_to(SRC)} imports {name}"
        for path in sorted((SRC / layer).rglob("*.py"))
        for name in imports_of(path)
        if any(name == banned or name.startswith(banned + ".") for banned in FORBIDDEN[layer])
    ]
    assert violations == []


def test_domain_depends_only_on_the_standard_library() -> None:
    import sys

    stdlib = sys.stdlib_module_names
    violations = [
        f"{path.relative_to(SRC)} imports {name}"
        for path in sorted((SRC / "domain").rglob("*.py"))
        for name in imports_of(path)
        if not name.startswith("postloom.")
        and name.split(".")[0] not in stdlib
        and name.split(".")[0] not in DOMAIN_ALLOWED_THIRD_PARTY
        and name != "__future__"
    ]
    assert violations == []
