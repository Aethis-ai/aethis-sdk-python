"""Recursive shape comparison for recorded-live fixture parity.

The mocked PR-gate suite builds request/response bodies with the fixture
builders in :mod:`tests.conftest` (``make_decide_response`` etc.). Those mocks
are only trustworthy if they still match what the deployed engine actually
returns — otherwise the suite passes against a shape that no longer exists.

:func:`compare_shape` diffs a fixture body against a live body **structurally**
(key sets + value types, recursively) and returns a list of human-readable
divergences. An empty list means the fixture is a faithful superset of reality.

The comparison is deliberately asymmetric:

- Every key the **live** payload returns must exist in the fixture. A key the
  engine sends but the fixture omits means the mock is stale (or a field was
  renamed) — that is a divergence.
- A key the fixture sets but live omits is **allowed**: many response fields are
  conditional (``explanation`` only when requested, ``next_question`` null on a
  final decision), so a fixture may legitimately carry a key a given live call
  didn't populate.
- Types are compared only where both sides are non-null, so a conditional field
  left null on either side never trips a false positive.

This asymmetry still catches a deliberate fixture edit: renaming ``decision`` to
``verdict`` removes ``decision`` from the fixture, so the live ``decision`` key
trips the "missing from fixture" rule; changing ``fields_evaluated`` from an int
to a string trips the type rule.
"""

from __future__ import annotations

from typing import Any


def _type_name(value: Any) -> str:
    """Coarse JSON type name. ``bool`` is distinguished from number even though
    it is an ``int`` subclass; ``int`` and ``float`` collapse to ``number`` so an
    engine int vs a fixture float is not a false positive."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return type(value).__name__


def compare_shape(fixture: Any, live: Any, path: str = "$") -> list[str]:
    """Return the list of structural divergences of ``fixture`` from ``live``.

    Empty list ⇒ the fixture faithfully covers the live shape.
    """
    divergences: list[str] = []

    # A conditional field null on either side carries no type information.
    if fixture is None or live is None:
        return divergences

    if isinstance(live, dict):
        if not isinstance(fixture, dict):
            return [f"{path}: fixture is {_type_name(fixture)}, live is object"]
        for key, live_value in live.items():
            child = f"{path}.{key}"
            if key not in fixture:
                divergences.append(f"{child}: key present in live response but missing from fixture")
                continue
            divergences.extend(compare_shape(fixture[key], live_value, child))
        return divergences

    if isinstance(live, list):
        if not isinstance(fixture, list):
            return [f"{path}: fixture is {_type_name(fixture)}, live is list"]
        # Compare the representative (first) element of each, when both present.
        if live and fixture:
            divergences.extend(compare_shape(fixture[0], live[0], f"{path}[0]"))
        return divergences

    # Leaf: compare coarse types.
    if _type_name(fixture) != _type_name(live):
        divergences.append(
            f"{path}: fixture type {_type_name(fixture)} != live type {_type_name(live)}"
        )
    return divergences
