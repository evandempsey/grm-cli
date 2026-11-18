"""Plan files: many clips and the kit changed in one go (CLI_SPEC.md, "Plan files").

    brand: kyree
    video: bf4a1894
    snapshot: before kyree look          # taken first; leave out to skip
    kit:
      set: {filter.id: instant, voice.room: small}
      unset: [titleRule]
    clips:
      3ef224f9:
        hook: The worst marriage advice I ever got
        thumb.t: 3.2
      f200fa5c:
        music: {make: "low strings, minor key, no drums"}
      c213c79d:
        music: off

`grm apply plan.yaml --dry-run` prints every change and every provider call it would pay for, and does nothing.
Without it: the snapshot is taken, then the kit is changed (one save), then every clip (one save: all checked before
any is saved, so a change that fails a check leaves every clip as it was). Music to make is started last; with --wait,
each clip gets the first of its two new tracks once they are made.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from grm_cli import jobs, kit, resolve
from grm_cli.client import Client
from grm_cli.commands import connect
from grm_cli.edit import api_path as clip_path
from grm_cli.edit import doc as clip_doc
from grm_cli.errors import GrmError, usage
from grm_cli.output import Out, short
from grm_cli.settings import MISSING, at, changes, flatten, said

NEEDS_API = 2  # each clip's own change in one save (POST /api/videos/{id}/bulk with `clips`)


def read(path: str) -> dict[str, Any]:
    try:
        plan = yaml.safe_load(Path(path).expanduser().read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        raise usage(f"Couldn't read {path}", str(e)) from None
    if not isinstance(plan, dict) or not plan.get("brand"):
        raise usage(f"{path} isn't a plan", "A plan names its brand: (and its video: for clips). grm apply --help")
    stray = set(plan) - {"brand", "video", "snapshot", "kit", "clips"}
    if stray:
        raise usage(
            f"{path} has parts grm doesn't know: {', '.join(sorted(stray))}", "brand, video, snapshot, kit, clips"
        )
    if plan.get("clips") and not plan.get("video"):
        raise usage(f"{path} changes clips but names no video", "Add video: <its id, or its first 8 characters>.")
    return plan


def _clip_changes(entry: Any, ref: str) -> tuple[dict[str, Any], list[str], str | None, bool]:
    """A plan's entry for one clip: (set, unset) as GRM's paths, music to make, and whether its music goes off."""
    if not isinstance(entry, dict):
        raise usage(f"Clip {ref}: its changes go under it, as path: value", "hook: Your wife isn't a spreadsheet")
    entry = dict(entry)
    make, off = None, False
    music = entry.pop("music", None)
    if music == "off" or music is False:
        off = True
    elif isinstance(music, dict):
        music = dict(music)
        make = music.pop("make", None)
        entry.update({f"music.{k}": v for k, v in flatten(music).items()})
    elif music is not None:
        raise usage(f'Clip {ref}: music is off, or {{make: "a description"}}, or its settings', "music: off")
    unset = [clip_path(p) for p in entry.pop("unset", None) or []]
    set_ = {clip_path(p): v for p, v in flatten(entry).items()}
    if off:
        set_["spec.music.on"] = False
    return set_, unset, make, off


def apply(args: argparse.Namespace, out: Out) -> int:
    plan = read(args.plan)
    client = connect(args)
    b = client.get(f"/api/brands/{resolve.brand(client, str(plan['brand']))['id']}")

    # The kit: what differs from the file, as the kit takes effect.
    k = plan.get("kit") or {}
    k_set = {kit.api_path(p): v for p, v in flatten(k.get("set") or {}).items()}
    k_unset = [kit.api_path(p) for p in k.get("unset") or []]
    live = kit.in_effect(b)
    k_set = {p: v for p, v in k_set.items() if at(live, p) != v}
    kit_lines = [(kit.own_path(p), at(live, p), v) for p, v in k_set.items()] + [
        (kit.own_path(p), at(live, p), "(the default)") for p in k_unset
    ]

    # The clips: each by the start of its id, in the plan's video.
    v = resolve.video(client, str(plan["video"])) if plan.get("video") else None
    if v is not None and v.get("brand_id") != b["id"]:
        raise usage(f"Video {short(v['id'])} isn't {b['name']}'s", "Name the brand the video belongs to.")
    clips = resolve.clips_of(client, v["id"]) if v else []
    vid = v["id"] if v else ""
    edits: dict[str, dict[str, Any]] = {}
    makes: list[tuple[dict[str, Any], str]] = []
    clip_lines: list[tuple[dict[str, Any], str, Any, Any]] = []
    for ref, entry in (plan.get("clips") or {}).items():
        ref = str(ref).lower()
        found = [c for c in clips if c["id"].startswith(ref)]
        if len(found) != 1:
            raise usage(
                f"Clip {ref}: {'no clip' if not found else f'{len(found)} clips'} of {short(vid)} start with it",
                "grm clips <video> lists them.",
            )
        c = found[0]
        set_, unset, make, _ = _clip_changes(entry, ref)
        set_ = {p: x for p, x in set_.items() if at(clip_doc(c), p) != x}
        if set_ or unset:
            edits[c["id"]] = {"set": set_, "unset": unset}
            for p, x in set_.items():
                clip_lines.append((c, p, at(clip_doc(c), p), x))
            for p in unset:
                clip_lines.append((c, p, at(clip_doc(c), p), "(the kit's)"))
        if make:
            makes.append((c, str(make)))

    if not out.as_json:
        _say_plan(plan, b, v, kit_lines, clip_lines, makes)
    if args.dry_run:
        out.result(
            {
                "dry_run": True,
                "snapshot": plan.get("snapshot"),
                "kit": [_c(*x) for x in kit_lines],
                "clips": [{"clip": c["id"], **_c(p, before, after)} for c, p, before, after in clip_lines],
                "music_to_make": [{"clip": c["id"], "description": d} for c, d in makes],
            },
            "Nothing was saved (--dry-run).",
        )
        return 0
    if edits:
        meta = client.get("/api/meta")
        if int(meta.get("api") or 1) < NEEDS_API:
            raise GrmError(
                "This GRM is older than grm apply needs",
                f"It speaks api {meta.get('api')}; changing clips in one save needs api {NEEDS_API}.",
                code="server_too_old",
            )

    done: dict[str, Any] = {}
    if not (k_set or k_unset or edits or makes):
        out.result(done, "Done: nothing to change, so no snapshot either.")
        return 0
    if plan.get("snapshot"):
        body: dict[str, Any] = {"name": str(plan["snapshot"])}
        if v is not None:
            body["video_id"] = v["id"]
        s = client.post(f"/api/brands/{b['id']}/snapshots", body)
        done["snapshot"] = s["id"]
        out.say(
            f"Took snapshot {short(s['id'])} “{s['name']}”: grm snapshot restore {short(s['id'])} puts it all back."
        )
    if k_set or k_unset:
        after = client.request(
            "PATCH",
            f"/api/brands/{b['id']}/settings",
            json={"set": k_set, "unset": k_unset, "if_version": b.get("version")},
        ).body
        done["kit"] = changes(live, kit.in_effect(after), [*k_set, *k_unset])
        out.say(f"Changed {b['name']}'s kit.")
    if edits:
        try:
            r = client.post(f"/api/videos/{vid}/bulk", {"clips": edits})
        except GrmError as e:
            if done.get("kit") or done.get("snapshot"):
                e.fix = (e.fix + " " if e.fix else "") + (
                    "The kit was changed; no clip was. "
                    + (
                        f"grm snapshot restore {short(done['snapshot'])} puts the kit back."
                        if done.get("snapshot")
                        else ""
                    )
                ).strip()
            raise
        done["clips_changed"] = r.get("changed")
        n = r.get("changed", 0)
        out.say(f"Changed {n} clip{'' if n == 1 else 's'}.")
    if makes:
        done["music"] = _make_music(client, makes, out, args)
    out.result(done, "Done.")
    return 0


def _c(path: str, before: Any, after: Any) -> dict[str, Any]:
    return {"path": path, "before": None if before is MISSING else before, "after": after}


def _say_plan(plan, b, v, kit_lines, clip_lines, makes) -> None:
    print(f"Plan for {b['name']}" + (f", video {short(v['id'])} {v.get('title') or ''}" if v else "") + ":")
    if plan.get("snapshot"):
        print(f"  snapshot first: “{plan['snapshot']}”")
    for p, before, after in kit_lines:
        print(f"  kit {p}: {said(before)} → {said(after)}")
    for c, p, before, after in clip_lines:
        print(f"  {short(c['id'])} {p.removeprefix('spec.')}: {said(before)} → {said(after)}")
    for c, d in makes:
        print(f"  {short(c['id'])} music: make two tracks, “{d}” (paid: ElevenLabs)")
    if not (kit_lines or clip_lines or makes):
        print("  Nothing to change: everything is already as the plan says.")


def _make_music(client: Client, makes: list[tuple[dict[str, Any], str]], out: Out, args) -> list[dict[str, Any]]:
    """Start making music for each clip (paid); with --wait, wait and put the first new track on the clip."""
    started = []
    for c, description in makes:
        out.say(f"Making music for {short(c['id'])} (paid: ElevenLabs).")
        a = client.post(f"/api/assets/{c['id']}/music/make", {"description": description})
        started.append((c, (a.get("job") or {}).get("id")))
    results = []
    for c, job_id in started:
        if not args.wait or not job_id:
            results.append({"clip": c["id"], "job": job_id})
            continue
        job = jobs.follow(client, job_id, out, jobs.parse_timeout(args.timeout))
        new = ((job.get("result") or {}).get("with") or {}).get("new") or []
        if new:
            fresh = client.get(f"/api/assets/{c['id']}")
            client.request(
                "PATCH",
                f"/api/assets/{c['id']}",
                json={
                    "set": {"spec.music.on": True, "spec.music.track": {"source": "made", "id": new[0]}},
                    "if_version": fresh.get("version"),
                },
            )
            out.say(f"  {short(c['id'])} plays the first of its two new tracks; the other is there to pick instead.")
        results.append({"clip": c["id"], "job": job_id, "tracks": new})
    return results
