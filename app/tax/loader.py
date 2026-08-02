"""Loads dated rulesets from YAML and picks the one in force on a given date.

This is the part that makes the whole project worth building. Sri Lankan
vehicle duty changes by gazette, sometimes with a few days' notice and
sometimes with a hard cut-off tied to when the L/C was opened. Because every
ruleset carries its own effective dates, this app can answer "what did this
cost in March?" and "what happens when the surcharge lapses?" -- which the
other calculators out there cannot.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

RULES_DIR = Path(__file__).parent / "rules"


class RuleError(Exception):
    """Raised when the rule files are internally inconsistent."""


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def load_rulesets(rules_dir: Path | None = None) -> list[dict[str, Any]]:
    """Read every YAML ruleset and validate that their date ranges never overlap.

    An overlap means two gazettes both claim to be in force on the same day,
    which means somebody made a mistake in a pull request. Fail loudly here so
    CI catches it instead of a customer catching it.
    """
    directory = rules_dir or RULES_DIR
    rulesets: list[dict[str, Any]] = []

    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        data["id"] = path.stem
        data["effective_from"] = _parse_date(data["effective_from"])
        data["effective_to"] = _parse_date(data.get("effective_to"))
        if data["effective_to"] and data["effective_to"] < data["effective_from"]:
            raise RuleError(f"{path.name}: effective_to is before effective_from")
        rulesets.append(data)

    rulesets.sort(key=lambda r: r["effective_from"])

    for earlier, later in zip(rulesets, rulesets[1:], strict=False):
        end = earlier["effective_to"]
        if end is None or end >= later["effective_from"]:
            raise RuleError(
                f"Ruleset {earlier['id']} overlaps {later['id']}. "
                "Two gazettes cannot both be in force on the same day."
            )

    return rulesets


def ruleset_for(as_of: date, rules_dir: Path | None = None) -> dict[str, Any]:
    """Return the ruleset in force on `as_of`, or raise if there is a gap."""
    for ruleset in load_rulesets(rules_dir):
        starts = ruleset["effective_from"]
        ends = ruleset["effective_to"]
        if starts <= as_of and (ends is None or as_of <= ends):
            return ruleset
    raise RuleError(f"No ruleset covers {as_of.isoformat()} -- is a gazette missing?")
