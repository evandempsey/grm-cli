"""Changing clips: one clip's settings by path, every clip of a video at once, a rewrite of its words, its history.

Paths are the clip's own (`hook`, `thumb.t`, `captions.preset`; `title` is its title). A clip changes only if it is
still at the version read, so a change made meanwhile (in review, by someone else) is never written over: exit 5.
"""

from __future__ import annotations

import argparse
from typing import Any

from grm_cli import jobs, resolve
from grm_cli.commands import connect
from grm_cli.errors import usage
from grm_cli.output import Out, short
from grm_cli.settings import assignments, changes, flatten, said, tell

FIELDS = ("tiktok", "shorts_title", "shorts_description", "x", "linkedin")


def api_path(path: str) -> str:
    """A clip's path as GRM names it: `hook` → `spec.hook`; `title` is the clip's title."""
    return path if path == "title" or path.startswith("spec.") else f"spec.{path}"


def own_path(path: str) -> str:
    return path.removeprefix("spec.")


def doc(c: dict[str, Any]) -> dict[str, Any]:
    """A clip as GRM's paths read it."""
    return {"title": c.get("title"), "spec": c.get("spec") or {}}


def _clip(client, args: argparse.Namespace) -> dict[str, Any]:
    return resolve.clip(client, args.clip, video_ref=getattr(args, "video", None), match=getattr(args, "match", None))


def _save(client, c: dict[str, Any], set_: dict[str, Any], unset: list[str]) -> list[dict[str, Any]]:
    after = client.request(
        "PATCH", f"/api/assets/{c['id']}", json={"set": set_, "unset": unset, "if_version": c.get("version")}
    ).body
    return [{**x, "path": own_path(x["path"])} for x in changes(doc(c), doc(after), [*set_, *unset])]


def set_(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    c = _clip(client, args)
    found = _save(client, c, {api_path(p): v for p, v in assignments(args.settings).items()}, [])
    out.result(found) if out.as_json else tell(out, found, f"{short(c['id'])} {c.get('title')}:")
    return 0


def unset(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    c = _clip(client, args)
    if "title" in args.paths:
        raise usage("A title can't be unset", 'Set it to the words it should have: grm clip set <clip> title="…"')
    found = _save(client, c, {}, [api_path(p) for p in args.paths])
    out.result(found) if out.as_json else tell(out, found, f"{short(c['id'])} {c.get('title')} (back to the kit's):")
    return 0


def rewrite(args: argparse.Namespace, out: Out) -> int:
    """Rewrite one of a clip's texts with an instruction: a language model writes it, so it is paid for."""
    client = connect(args)
    c = _clip(client, args)
    if args.dry_run:
        out.result(
            {"dry_run": True, "clip": c["id"], "field": args.field, "instruction": args.instruction},
            f"Would rewrite {short(c['id'])}'s {args.field} text: “{args.instruction}”. A language model writes it "
            "(paid for). Nothing was sent.",
        )
        return 0
    out.say("Rewriting with a language model (paid for).")
    answer = client.request(
        "POST",
        f"/api/assets/{c['id']}/rewrite",
        json={"instruction": args.instruction, "field": args.field, "variant": args.variant},
    )
    job = answer.body.get("job") if isinstance(answer.body, dict) else None
    made = None
    if job:
        done = jobs.follow(client, job["id"], out, jobs.parse_timeout(args.timeout))
        made = ((done.get("result") or {}).get("with") or {}).get("new_variant")
    after = client.get(f"/api/assets/{c['id']}")
    variants = (((after.get("spec") or {}).get("copy") or {}).get(args.field) or {}).get("variants") or []
    # The variant the rewrite made, as its job says; the last one, from a GRM that doesn't say.
    newest = variants[made] if isinstance(made, int) and made < len(variants) else variants[-1] if variants else {}
    out.result({"clip": after, "field": args.field, "text": newest.get("text")}, newest.get("text") or "")
    return 0


def history(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    c = _clip(client, args)
    h = client.get(f"/api/assets/{c['id']}/history")
    rows = [
        {
            "n": v["n"],
            "summary": v["summary"],
            "by": v.get("by") or "GRM",
            "through": v.get("through"),
            "at": (v.get("at") or "")[:16].replace("T", " "),
        }
        for v in h["versions"]
    ]
    out.table(
        rows,
        [("n", "Version"), ("summary", "What changed"), ("by", "By"), ("through", "Through"), ("at", "When")],
        data=h,
    )
    return 0


def restore(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    c = _clip(client, args)
    after = client.post(f"/api/assets/{c['id']}/versions/{args.version}/restore")
    after = after.get("asset", after) if isinstance(after, dict) else after
    paths = sorted({*flatten(doc(c)), *flatten(doc(after))})
    found = [{**x, "path": own_path(x["path"])} for x in changes(doc(c), doc(after), paths)]
    out.result(found) if out.as_json else tell(out, found, f"{short(c['id'])} is back to version {args.version}:")
    return 0


def bulk(args: argparse.Namespace, out: Out) -> int:
    """The same change on every clip of a video: all checked before any is saved, and saved together."""
    client = connect(args)
    v = resolve.video(client, args.video)
    before = {c["id"]: c for c in resolve.clips_of(client, v["id"])}
    if args.how == "set":
        body = {"set": {api_path(p): x for p, x in assignments(args.settings).items()}}
        paths = list(body["set"])
    else:
        body = {"unset": [api_path(p) for p in args.settings]}
        paths = body["unset"]
    answer = client.post(f"/api/videos/{v['id']}/bulk", body)
    found = []
    for a in answer.get("assets") or []:
        for x in changes(doc(before.get(a["id"], {})), doc(a), paths):
            found.append({"clip": a["id"], "title": a.get("title"), **x, "path": own_path(x["path"])})
    if out.as_json:
        out.result({"changed": answer.get("changed"), "changes": found})
        return 0
    print(f"{answer.get('changed', 0)} of {len(before)} clips changed:")
    for x in found:
        print(f"  {short(x['clip'])} {x['path']}: {said(x['before'])} → {said(x['after'])}")
    return 0
