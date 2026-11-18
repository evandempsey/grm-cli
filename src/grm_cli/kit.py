"""A brand's kit from the command line: read it, change part of it, keep it in a file and make the live kit match.

Paths are the kit's own (`captions.preset`, `filter.id`, `voice.room`); the brand's writing settings are `writing.…`
and its default pack `pack.…`. Everything is compared as it takes effect (defaults filled in), so a setting left at its
default and the same value written down are the same.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml

from grm_cli import resolve
from grm_cli.commands import connect
from grm_cli.errors import usage
from grm_cli.output import Out
from grm_cli.settings import MISSING, assignments, at, changes, flatten, said, tell

# The parts of a brand's settings, as grm names them and as GRM stores them.
PARTS = {"kit": "brand_kit", "writing": "voice", "pack": "default_pack"}


def api_path(path: str) -> str:
    """grm's path for a setting as GRM names it: `captions.preset` → `brand_kit.captions.preset`,
    `writing.cta` → `voice.cta`, `pack.clips` → `default_pack.clips`."""
    top, _, rest = path.partition(".")
    if top in ("brand_kit", "default_pack"):
        return path
    if top in PARTS and rest:
        return f"{PARTS[top]}.{rest}"
    return f"brand_kit.{path}"


def own_path(path: str) -> str:
    """GRM's path as grm says it: the kit's without a prefix, the others with theirs."""
    top, _, rest = path.partition(".")
    if top == "brand_kit":
        return rest
    return {"voice": "writing", "default_pack": "pack"}.get(top, top) + "." + rest


def in_effect(b: dict[str, Any]) -> dict[str, Any]:
    """A brand's settings as they take effect, as GRM stores them: {brand_kit, voice, default_pack}."""
    return {"brand_kit": b.get("kit") or {}, "voice": b.get("voice") or {}, "default_pack": b.get("default_pack") or {}}


def as_file(b: dict[str, Any]) -> dict[str, Any]:
    """A brand's settings in a kit file's shape (what `kit apply` reads)."""
    e = in_effect(b)
    return {"kit": e["brand_kit"], "writing": e["voice"], "pack": e["default_pack"]}


def _save(client, b: dict[str, Any], set_: dict[str, Any], unset: list[str]) -> list[dict[str, Any]]:
    """Change the brand's settings by path, if it is still at the version read; say what changed."""
    paths = [*set_, *unset]
    after = client.request(
        "PATCH",
        f"/api/brands/{b['id']}/settings",
        json={"set": set_, "unset": unset, "if_version": b.get("version")},
    ).body
    return [{**c, "path": own_path(c["path"])} for c in changes(in_effect(b), in_effect(after), paths)]


def get(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    b = client.get(f"/api/brands/{resolve.brand(client, args.brand)['id']}")
    doc: Any = as_file(b)
    if args.path:
        doc = at(in_effect(b), api_path(args.path))
        if doc is MISSING:
            raise usage(f"{b['name']}'s kit has no setting {args.path}", "grm kit get <brand> lists every setting.")
    out.result(doc, yaml.safe_dump(doc, sort_keys=True, allow_unicode=True).rstrip())
    return 0


def set_(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    b = client.get(f"/api/brands/{resolve.brand(client, args.brand)['id']}")
    wanted = {api_path(p): v for p, v in assignments(args.settings).items()}
    found = _save(client, b, wanted, [])
    if out.as_json:
        out.result(found)
    else:
        tell(out, found, f"{b['name']}:")
    return 0


def unset(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    b = client.get(f"/api/brands/{resolve.brand(client, args.brand)['id']}")
    found = _save(client, b, {}, [api_path(p) for p in args.paths])
    if out.as_json:
        out.result(found)
    else:
        tell(out, found, f"{b['name']} (back to the defaults):")
    return 0


def _wanted(path: str) -> tuple[dict[str, Any], list[str]]:
    """What a kit file asks for: {GRM path: value} to set, and GRM paths to take back to the defaults."""
    try:
        doc = yaml.safe_load(Path(path).expanduser().read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        raise usage(f"Couldn't read {path}", str(e)) from None
    if not isinstance(doc, dict) or not set(doc) <= {*PARTS, "unset"}:
        raise usage(
            f"{path} isn't a kit file",
            "Its settings go under kit:, writing: and pack:, and settings to take back to the defaults under unset:.",
        )
    want: dict[str, Any] = {}
    for part, stored in PARTS.items():
        for p, v in flatten(doc.get(part) or {}).items():
            want[f"{stored}.{p}"] = v
    return want, [api_path(p) for p in doc.get("unset") or []]


def _differences(b: dict[str, Any], want: dict[str, Any]) -> dict[str, Any]:
    live = in_effect(b)
    return {p: v for p, v in want.items() if at(live, p) != v}


def diff(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    b = client.get(f"/api/brands/{resolve.brand(client, args.brand)['id']}")
    want, unset_ = _wanted(args.file)
    found = [
        {"path": own_path(p), "live": None if at(in_effect(b), p) is MISSING else at(in_effect(b), p), "file": v}
        for p, v in _differences(b, want).items()
    ] + [{"path": own_path(p), "live": at(in_effect(b), p), "file": "(the default)"} for p in unset_]
    if out.as_json:
        out.result(found)
    elif not found:
        print(f"{b['name']}'s live kit matches {args.file}.")
    else:
        print(f"{b['name']}: live → {args.file}")
        for d in found:
            print(f"  {d['path']}: {said(d['live'])} → {said(d['file'])}")
    return 0


def apply(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    b = client.get(f"/api/brands/{resolve.brand(client, args.brand)['id']}")
    want, unset_ = _wanted(args.file)
    todo = _differences(b, want)
    if args.dry_run:
        found = [{"path": own_path(p), "before": at(in_effect(b), p), "after": v} for p, v in todo.items()]
        found += [{"path": own_path(p), "before": at(in_effect(b), p), "after": "(the default)"} for p in unset_]
        if out.as_json:
            out.result({"dry_run": True, "changes": found})
        else:
            tell(
                out,
                [{**c, "before": None if c["before"] is MISSING else c["before"]} for c in found],
                f"Would change {b['name']} (nothing is saved):",
            )
        return 0
    found = _save(client, b, todo, unset_) if todo or unset_ else []
    if out.as_json:
        out.result(found)
    else:
        tell(out, found, f"{b['name']} now matches {args.file}:")
    return 0


def history(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    b = resolve.brand(client, args.brand)
    h = client.get(f"/api/brands/{b['id']}/history")
    rows = [
        {
            "n": v["n"],
            "current": "←" if v.get("current") else "",
            "summary": _paths_said(v["summary"]),
            "by": v.get("by") or "GRM",
            "through": v.get("through"),
            "at": (v.get("at") or "")[:16].replace("T", " "),
        }
        for v in h["versions"]
    ]
    out.table(
        rows,
        [
            ("n", "Version"),
            ("current", ""),
            ("summary", "What changed"),
            ("by", "By"),
            ("through", "Through"),
            ("at", "When"),
        ],
        data=h,
    )
    return 0


def _paths_said(summary: str) -> str:
    """GRM's summary of a version, with its paths as grm says them: `brand_kit.filter.id` → `filter.id`."""
    return re.sub(r"\b(?:brand_kit|voice|default_pack)\.[\w.]+", lambda m: own_path(m.group(0)), summary or "")


def restore(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    b = client.get(f"/api/brands/{resolve.brand(client, args.brand)['id']}")
    after = client.post(f"/api/brands/{b['id']}/versions/{args.version}/restore")
    found = [{**c, "path": own_path(c["path"])} for c in changes(in_effect(b), in_effect(after), _all_paths(b, after))]
    if out.as_json:
        out.result({"version": after.get("version"), "changes": found})
    else:
        tell(out, found, f"{b['name']} is back to version {args.version} (as version {after.get('version')}):")
    return 0


def _all_paths(*brands: dict[str, Any]) -> list[str]:
    seen: dict[str, None] = {}
    for b in brands:
        for p in flatten(in_effect(b)):
            seen.setdefault(p, None)
    return list(seen)
