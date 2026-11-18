"""Settings by path: `captions.preset=bold` on the command line, nested YAML in a file, and every change said path by
path, before and after."""

from __future__ import annotations

import json
from typing import Any

from grm_cli.errors import usage
from grm_cli.output import Out

MISSING = object()


def value(text: str) -> Any:
    """A value as typed: JSON where it is JSON (12.4, true, null, ["a"], {"id": "x"}), otherwise the words."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def assignments(items: list[str]) -> dict[str, Any]:
    """`path=value` arguments as {path: value}."""
    out: dict[str, Any] = {}
    for item in items:
        path, eq, text = item.partition("=")
        if not eq or not path.strip():
            raise usage(f"“{item}” isn't a setting to change", "Write it as path=value, such as captions.preset=bold.")
        out[path.strip()] = value(text)
    return out


def flatten(doc: Any, at: str = "") -> dict[str, Any]:
    """A nested document as {dotted.path: value}: a set of settings is followed key by key; anything else (a value, a
    list) is one setting. Keys may themselves be dotted (`voice.room: small`)."""
    if isinstance(doc, dict) and doc:
        out: dict[str, Any] = {}
        for k, v in doc.items():
            out.update(flatten(v, f"{at}.{k}" if at else str(k)))
        return out
    return {at: doc} if at else {}


def at(doc: Any, path: str) -> Any:
    """The value at a dotted path, or MISSING."""
    for part in path.split("."):
        if isinstance(doc, dict) and part in doc:
            doc = doc[part]
        elif isinstance(doc, list) and part.isdigit() and int(part) < len(doc):
            doc = doc[int(part)]
        else:
            return MISSING
    return doc


def said(v: Any) -> str:
    if v is MISSING or v is None:
        return "(none)"
    if isinstance(v, str):
        return v if len(v) <= 70 else v[:67] + "…"
    text = json.dumps(v, ensure_ascii=False)
    if len(text) > 70 and isinstance(v, list):
        return f"({len(v)} {'item' if len(v) == 1 else 'items'})"
    return text if len(text) <= 70 else text[:67] + "…"


def changes(before: Any, after: Any, paths: list[str], show: str = "") -> list[dict[str, Any]]:
    """What changed at each path, from `before` to `after` (documents), as {path, before, after}; paths that didn't
    change are left out. `show` is put before each path as it is said (`kit.`)."""
    out = []
    for p in paths:
        b, a = at(before, p), at(after, p)
        if b != a:
            out.append({"path": show + p, "before": None if b is MISSING else b, "after": None if a is MISSING else a})
    return out


def tell(out: Out, found: list[dict[str, Any]], title: str = "") -> None:
    """Every change, path by path, before and after: on stdout, as the command's result."""
    if title:
        print(title)
    if not found:
        print("  Nothing changed: each setting already was as asked.")
    for c in found:
        print(f"  {c['path']}: {said(c['before'])} → {said(c['after'])}")
