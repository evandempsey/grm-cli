"""How grm says things: results on stdout (a table, or one JSON document with --json), progress on stderr."""

from __future__ import annotations

import json
import sys
from typing import Any


class Out:
    def __init__(self, as_json: bool = False, quiet: bool = False):
        self.as_json, self.quiet = as_json, quiet

    def say(self, message: str) -> None:
        """Progress and notes, on stderr: never in the way of what a script reads."""
        if not self.quiet:
            print(message, file=sys.stderr, flush=True)

    def result(self, data: Any, text: str | None = None) -> None:
        """The command's result: `data` as JSON with --json, otherwise `text` (or `data` as JSON when there is none)."""
        if self.as_json or text is None:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        elif text:
            print(text)

    def table(self, rows: list[dict[str, Any]], columns: list[tuple[str, str]], data: Any = None) -> None:
        """Rows as a table with these (key, heading) columns; with --json, `data` (or the rows) as JSON."""
        if self.as_json:
            self.result(rows if data is None else data)
            return
        if not rows:
            return
        cells = [[_cell(r.get(k)) for k, _ in columns] for r in rows]
        widths = [max(len(h), *(len(c[i]) for c in cells)) for i, (_, h) in enumerate(columns)]
        print("  ".join(h.upper().ljust(widths[i]) for i, (_, h) in enumerate(columns)).rstrip())
        for c in cells:
            print("  ".join(v.ljust(widths[i]) for i, v in enumerate(c)).rstrip())


def _cell(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


def clock(seconds: float | None) -> str | None:
    """1:07, or 1:02:07."""
    if seconds is None:
        return None
    s = int(round(float(seconds)))
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def short(ident: str | None) -> str | None:
    """The first 8 characters of an id: enough to name it to grm."""
    return ident[:8] if ident else None


def size(n: int | None) -> str | None:
    if n is None:
        return None
    v = float(n)
    for unit in ("B", "KB", "MB"):
        if v < 1024:
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} GB"
