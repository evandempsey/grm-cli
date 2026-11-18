"""Uploading a file to GRM in parts, as the upload screen does (POST /api/uploads, each part, then complete).

With R2 behind it, each part goes straight to storage at an address GRM signs for it; on a GRM that keeps its files
locally, each part goes through GRM itself. A part that doesn't arrive is sent again, a few times, before giving up.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from grm_cli.client import Client
from grm_cli.errors import GrmError
from grm_cli.output import Out, size

TRIES = 3


def upload(client: Client, path: Path, out: Out) -> str:
    """Send a file, and return its upload's id."""
    total = path.stat().st_size
    kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    u = client.post("/api/uploads", {"filename": path.name, "size_bytes": total, "content_type": kind})
    count, part = int(u["part_count"]), int(u["part_bytes"])
    out.say(f"Uploading {path.name} ({size(total)}) in {count} part{'s' if count != 1 else ''}")
    with open(path, "rb") as f:
        for n in range(1, count + 1):
            data = f.read(part)
            _send(client, u, n, data)
            if count > 1 and (n == count or n % max(1, count // 10) == 0):
                out.say(f"  {round(n / count * 100)}% ({n} of {count} parts)")
    client.post(f"/api/uploads/{u['id']}/complete")
    return u["id"]


def _send(client: Client, u: dict, n: int, data: bytes) -> None:
    last: GrmError | None = None
    for _ in range(TRIES):
        try:
            if u.get("direct"):
                url = client.get(f"/api/uploads/{u['id']}/parts/{n}/url")["url"]
                client.put_bytes(url, data)
            else:
                client.request("PUT", f"/api/uploads/{u['id']}/parts/{n}", content=data)
            return
        except GrmError as e:
            if e.status is not None and 400 <= e.status < 500:
                raise  # refused, not lost: sending it again won't help
            last = e
    assert last is not None
    raise last
