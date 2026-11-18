"""Names instead of ids. A brand by its name, handle or code (`kyree`, `@kyree`); a video or a clip by the first
characters of its id (8 is plenty), or a clip by words of its title. A name that matches two things is refused, with
both listed, rather than guessed."""

from __future__ import annotations

import re
from typing import Any

from grm_cli.client import Client
from grm_cli.errors import GrmError, usage

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PREFIX = re.compile(r"^[0-9a-f-]{4,36}$")
REVIEWED = ("review", "approved", "exported")


def _one(found: list[dict[str, Any]], ref: str, what: str, label) -> dict[str, Any]:
    if len(found) == 1:
        return found[0]
    if not found:
        raise usage(f"No {what} is called “{ref}”", f"grm {what}s lists them.")
    names = "; ".join(label(x) for x in found[:6])
    raise usage(f"“{ref}” matches {len(found)} {what}s: {names}", "Say more of it, or give the id.")


def brand(client: Client, ref: str) -> dict[str, Any]:
    """A brand by its id, code, handle (with or without @) or name, or the start of one of them."""
    brands = client.get("/api/brands")
    key = ref.strip().lstrip("@").lower()

    def names(b: dict[str, Any]) -> list[str]:
        return [str(x).lstrip("@").lower() for x in (b.get("id"), b.get("code"), b.get("handle"), b.get("name")) if x]

    exact = [b for b in brands if key in names(b)]
    found = exact or [b for b in brands if any(n.startswith(key) for n in names(b))]
    return _one(found, ref, "brand", lambda b: f"{b['name']} ({b.get('code')})")


def videos_of(client: Client, brand_id: str, ref: str | None = None) -> list[dict[str, Any]]:
    return client.get(f"/api/brands/{brand_id}/videos", ref=ref)


def video(client: Client, ref: str) -> dict[str, Any]:
    """A video by its id, or the start of it (looked for in every brand)."""
    key = ref.strip().lower()
    if UUID.match(key):
        return client.get(f"/api/videos/{key}")
    if not PREFIX.match(key):
        raise usage(
            f"“{ref}” isn't a video id", "Give the id, or its first 8 characters (grm videos <brand> lists them)."
        )
    found = [v for b in client.get("/api/brands") for v in videos_of(client, b["id"]) if v["id"].startswith(key)]
    return _one(found, ref, "video", lambda v: f"{v['id'][:8]} {v.get('title') or '(untitled)'}")


def clips_of(client: Client, video_id: str) -> list[dict[str, Any]]:
    return [a for a in client.get(f"/api/videos/{video_id}/assets") if a.get("kind") == "clip"]


def clip(client: Client, ref: str | None, *, video_ref: str | None = None, match: str | None = None) -> dict[str, Any]:
    """A clip by its id, the start of it, or words of its title (`match`), in one video or every reviewed one."""
    if ref and UUID.match(ref.strip().lower()):
        return client.get(f"/api/assets/{ref.strip().lower()}")
    if not ref and not match:
        raise usage("Name a clip", "Give its id (its first 8 characters will do), or --match words of its title.")
    if ref and not PREFIX.match(ref.strip().lower()):
        raise usage(f"“{ref}” isn't a clip id", "Give its first 8 characters, or use --match for words of its title.")
    if video_ref:
        vids = [video(client, video_ref)]
    else:
        vids = [v for b in client.get("/api/brands") for v in videos_of(client, b["id"]) if v["status"] in REVIEWED]
    key = (ref or "").strip().lower()
    words = (match or "").strip().lower()
    found = [
        c
        for v in vids
        for c in clips_of(client, v["id"])
        if (not key or c["id"].startswith(key)) and (not words or words in (c.get("title") or "").lower())
    ]
    return _one(found, ref or match or "", "clip", lambda c: f"{c['id'][:8]} {c.get('title') or ''}")


def job_id(ref: str) -> str:
    if not UUID.match(ref.strip().lower()):
        raise GrmError(f"“{ref}” isn't a job id", "Give the whole id, as grm jobs lists it.", code="usage", exit=2)
    return ref.strip().lower()
