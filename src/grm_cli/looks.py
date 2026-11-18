"""Seeing and hearing a clip without a browser: stills, an overview sheet, variants side by side (not saved), every
thumbnail in one picture, and the clip's sound with its levels.

GRM draws each one from what the export draws from, as a job; grm waits for it and downloads the files into
`./grm-out/` (or `--out`), named `<clip title>_<what>.png`, and prints their paths, one per line, so an agent can open
them straight away.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from grm_cli import jobs, resolve
from grm_cli.client import Client
from grm_cli.commands import connect
from grm_cli.errors import usage
from grm_cli.output import Out
from grm_cli.settings import value

OUT = "grm-out"


def slug(text: str | None, most: int = 50) -> str:
    """Words as a file name: lower case, joined by _, letters and digits only."""
    words = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return words[:most].rstrip("_") or "untitled"


def _follow(client: Client, answer: Any, out: Out, timeout: str | None) -> dict[str, Any]:
    """The look's job, waited for at the server's pace; its result, with links signed now."""
    job = answer.get("job") if isinstance(answer, dict) else None
    if not job:
        raise usage("GRM didn't answer with a job", "Is this GRM older than grm? grm whoami says its api.")
    return jobs.follow(client, job["id"], out, jobs.parse_timeout(timeout))["result"] or {}


def _fetch(client: Client, url: str | None, dest: Path) -> str:
    if not url:
        raise usage(f"{dest.name} is no longer kept", "Looks are kept for a day: ask for it again.")
    client.download(url, dest)
    return str(dest)


def look(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    c = resolve.clip(client, args.clip, video_ref=args.video, match=args.match)
    body: dict[str, Any] = {"aspect": args.aspect}
    if args.width:
        body["width"] = args.width
    if args.at:
        body["at"] = args.at
    else:
        body["count"] = args.sheet or 6
    variants = _variants(args.try_) if args.try_ else None
    if variants:
        body["variants"] = variants
    # An overview, and variants, are one picture unless asked otherwise; moments named are each their own.
    body["sheet"] = bool(args.sheet is not None or variants or not args.at)
    out.say("GRM is drawing it (it pays no provider).")
    result = _follow(client, client.post(f"/api/assets/{c['id']}/stills", body), out, args.timeout)
    folder = Path(args.out or OUT).expanduser()
    name = slug(c.get("title"))
    what = "_try_" + "_".join(slug(v["label"], 20) for v in variants) if variants else ""
    paths = []
    if result.get("sheet_url") or result.get("sheet_key"):
        when = "_at_" + "_".join(f"{t:g}" for t in args.at) if args.at else "_sheet"
        paths.append(_fetch(client, result.get("sheet_url"), folder / f"{name}{when}{what}.png"))
    else:
        for s in result.get("stills") or []:
            label = f"_{slug(s['label'], 20)}" if s.get("label") else ""
            paths.append(_fetch(client, s.get("url"), folder / f"{name}_at_{s['at']:g}{label}.png"))
    out.result({"clip": c["id"], "files": paths, "stills": result.get("stills")}, "\n".join(paths))
    return 0


def _variants(text: str) -> list[dict[str, Any]]:
    """`captions.preset=bold,serif,neon`: one setting, a value for each variant, each labelled by its value."""
    path, eq, values = text.partition("=")
    options = [v.strip() for v in values.split(",") if v.strip()]
    if not eq or not path or not 2 <= len(options) <= 4:
        raise usage(
            f"“{text}” isn't a setting to try", "Give one setting and 2 to 4 values: captions.preset=bold,serif"
        )
    p = path if path.startswith("spec.") else f"spec.{path}"
    return [{"label": o, "set": {p: value(o)}} for o in options]


def thumbs(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    v = resolve.video(client, args.video)
    params = {"width": args.width, "columns": args.columns}
    answer = client.request(
        "GET", f"/api/videos/{v['id']}/thumbnails/sheet", params={k: x for k, x in params.items() if x}
    ).body
    out.say("GRM is drawing every thumbnail (it pays no provider).")
    result = _follow(client, answer, out, args.timeout)
    dest = Path(args.out or OUT).expanduser() / f"{slug(v.get('title') or v['id'][:8])}_thumbnails.png"
    path = _fetch(client, result.get("url"), dest)
    out.result({"video": v["id"], "file": path, "clips": result.get("clips")}, path)
    return 0


LEVELS = [
    ("lufs", "Loudness of the mix", "LUFS"),
    ("voice_lufs", "Voices", "LUFS"),
    ("music_lufs", "Music", "LUFS"),
    ("music_under_voice_db", "Music under the voices", "dB"),
    ("true_peak_db", "True peak", "dBTP"),
    ("music_starts", "Music from", "s"),
    ("music_ends", "Music to", "s"),
    ("clipped", "Clipped", ""),
]


def listen(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    c = resolve.clip(client, args.clip, video_ref=args.video, match=args.match)
    out.say("GRM is mixing it as the export will (it pays no provider).")
    answer = client.post(f"/api/assets/{c['id']}/sound", {"music": not args.no_music})
    result = _follow(client, answer, out, args.timeout)
    dest = Path(args.out or OUT).expanduser() / f"{slug(c.get('title'))}_sound.mp3"
    path = _fetch(client, result.get("url"), dest)
    levels = {k: result.get(k) for k, _, _ in LEVELS}
    lines = [path] + [
        f"{label}: {_level(levels[k])}{(' ' + unit) if unit and levels[k] is not None else ''}"
        for k, label, unit in LEVELS
        if levels[k] is not None or k in ("music_lufs",)
    ]
    out.result({"clip": c["id"], "file": path, "seconds": result.get("seconds"), **levels}, "\n".join(lines))
    return 0


def _level(v: Any) -> str:
    if v is None:
        return "no music"
    if isinstance(v, bool):
        return "yes" if v else "no"
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)
