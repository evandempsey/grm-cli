"""Snapshots: a brand's kit and its clips' settings kept under a name, to put back after a batch of changes."""

from __future__ import annotations

import argparse
from typing import Any

from grm_cli import resolve
from grm_cli.commands import connect
from grm_cli.errors import usage
from grm_cli.output import Out, short
from grm_cli.settings import said


def _find(client, ref: str) -> dict[str, Any]:
    """A snapshot by its id, or the start of it (looked for in every brand)."""
    key = ref.strip().lower()
    if resolve.UUID.match(key):
        return client.get(f"/api/snapshots/{key}")
    found = [s for b in client.get("/api/brands") for s in _of(client, b["id"]) if s["id"].startswith(key)]
    if len(found) == 1:
        return found[0]
    if not found:
        raise usage(f"No snapshot has the id {ref}", "grm snapshots <brand> lists them.")
    raise usage(f"“{ref}” matches {len(found)} snapshots", "Give more of its id.")


def _of(client, brand_id: str) -> list[dict[str, Any]]:
    got = client.get(f"/api/brands/{brand_id}/snapshots")
    return got.get("snapshots", got) if isinstance(got, dict) else got


def take(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    b = resolve.brand(client, args.brand)
    body: dict[str, Any] = {"name": args.name}
    if args.video:
        body["video_id"] = resolve.video(client, args.video)["id"]
    s = client.post(f"/api/brands/{b['id']}/snapshots", body)
    what = "one video's clips" if args.video else "every video's clips"
    out.result(s, f"{short(s['id'])} “{s['name']}”: {b['name']}'s kit and {what} ({s.get('clips', 0)})")
    return 0


def list_(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    b = resolve.brand(client, args.brand)
    rows = _of(client, b["id"])
    out.table(
        [
            {
                "id": short(s["id"]),
                "name": s["name"],
                "clips": s.get("clips"),
                "by": s.get("by"),
                "at": (s.get("at") or "")[:16].replace("T", " "),
            }
            for s in rows
        ],
        [("id", "Id"), ("name", "Name"), ("clips", "Clips"), ("by", "By"), ("at", "When")],
        data=rows,
    )
    return 0


def diff(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    s = _find(client, args.snapshot)
    d = client.get(f"/api/snapshots/{s['id']}/diff")
    if out.as_json:
        out.result(d)
        return 0
    print(f"Since “{s['name']}”:")
    if not (d.get("brand") or d.get("clips") or d.get("gone") or d.get("added")):
        print("  Nothing is different.")
    for c in d.get("brand") or []:
        print(f"  kit {_path(c['path'])}: {said(c.get('now'))} (was {said(c.get('then'))})")
    for clip in d.get("clips") or []:
        for c in clip["changes"]:
            print(f"  {short(clip['asset_id'])} {_path(c['path'])}: {said(c.get('now'))} (was {said(c.get('then'))})")
    for g in d.get("gone") or []:
        print(f"  deleted since, can't be put back: {g.get('title')}")
    for a in d.get("added") or []:
        print(f"  added since, left as it is: {short(a['asset_id'])} {a.get('title')}")
    return 0


def _path(p: str) -> str:
    for prefix, said_as in (("brand_kit.", ""), ("voice.", "writing."), ("default_pack.", "pack."), ("spec.", "")):
        if p.startswith(prefix):
            return said_as + p[len(prefix) :]
    return p


def restore(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    s = _find(client, args.snapshot)
    only = [args.only] if args.only else ["brand", "clips"]
    r = client.post(f"/api/snapshots/{s['id']}/restore", {"only": only})
    if out.as_json:
        out.result(r)
        return 0
    print(f"Put back “{s['name']}”:")
    print(
        f"  kit: {'put back' if r.get('brand_restored') else 'already as it was'}" if "brand" in only else "  kit: left"
    )
    print(f"  clips put back: {len(r.get('restored') or [])}")
    for x in r.get("not_restored") or []:
        print(f"  not put back: {x.get('title', x) if isinstance(x, dict) else x}")
    if r.get("reopened"):
        print(f"  back in review, having changed: {len(r['reopened'])}")
    return 0


def delete(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    s = _find(client, args.snapshot)
    if not args.yes:
        raise usage(f"Deleting “{s['name']}” can't be undone", "Add --yes to delete it.")
    client.request("DELETE", f"/api/snapshots/{s['id']}")
    out.result({"deleted": s["id"]}, f"Deleted “{s['name']}”.")
    return 0
