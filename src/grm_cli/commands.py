"""The commands of grm 0.1: signing in, brands, videos, jobs, clips, exports, and any route (`grm api`)."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from grm_cli import API, __version__, config, jobs, resolve
from grm_cli.client import Client
from grm_cli.errors import GrmError, usage
from grm_cli.output import Out, clock, short, size
from grm_cli.upload import upload

# How far along its life a video is: waiting for one status is done once it has got there or past it.
STAGES = ["uploading", "uploaded", "processing", "review", "approved", "exported"]


def connect(args: argparse.Namespace) -> Client:
    p = config.profile(args.profile)
    return Client(p.url, p.token)


# ---------- Signing in ----------


def login(args: argparse.Namespace, out: Out) -> int:
    """Ask for a token (made on Settings, API tokens), check it with the server, and keep it in the keychain."""
    name = config.chosen(args.profile)
    url = (args.url or config.profile(name).url).rstrip("/")
    if sys.stdin.isatty():
        out.say(f"Make a token on {url}/settings#tokens, then paste it here. It is kept in your keychain.")
        token = getpass.getpass("Token: ").strip()
    else:
        token = sys.stdin.readline().strip()  # piped in, never on the command line
    if not token:
        raise usage("No token given", "Paste the token when asked, or pipe it in: grm login < token.txt")
    client = Client(url, token)
    meta, me = client.get("/api/meta"), client.get("/api/me")
    config.remember(name, url, token)
    _warn_versions(meta, out)
    ws = (me.get("workspaces") or [{}])[0]
    out.result(
        {"profile": name, "url": url, "user": me["user"], "workspace": ws, "scopes": meta["scopes"]},
        f"Signed in to {url} as {me['user']['name']} ({me['user']['email']}), in {ws.get('name', 'no workspace')}.\n"
        f"This token may: {', '.join(meta['scopes'])}.",
    )
    return 0


def logout(args: argparse.Namespace, out: Out) -> int:
    name = config.chosen(args.profile)
    gone = config.forget(name)
    out.result({"profile": name, "forgotten": gone}, f"Signed out of {name}." if gone else f"{name} had no token kept.")
    return 0


def whoami(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    meta, me = client.get("/api/meta"), client.get("/api/me")
    _warn_versions(meta, out)
    ws = (me.get("workspaces") or [{}])[0]
    data = {
        "user": me["user"],
        "workspace": ws,
        "scopes": meta["scopes"],
        "server": {"url": client.url, "version": meta.get("server"), "api": meta.get("api")},
        "cli": __version__,
    }
    out.result(
        data,
        f"{me['user']['name']} ({me['user']['email']})\n"
        f"Workspace: {ws.get('name', '-')}\n"
        f"May: {', '.join(meta['scopes'])}\n"
        f"Server: {client.url} ({meta.get('server')}, api {meta.get('api')})",
    )
    return 0


def _warn_versions(meta: dict[str, Any], out: Out) -> None:
    def parts(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split(".") if x.isdigit())

    if meta.get("min_cli") and parts(str(meta["min_cli"])) > parts(__version__):
        out.say(
            f"This server wants grm {meta['min_cli']} or later; this is {__version__}. Upgrade: uv tool upgrade grm-cli"
        )
    if int(meta.get("api") or API) > API:
        out.say(f"This server speaks api {meta['api']}; this grm knows api {API}. Some commands may not work: upgrade.")


# ---------- Brands ----------


def brands(args: argparse.Namespace, out: Out) -> int:
    rows = connect(args).get("/api/brands")
    out.table(
        [{"name": b["name"], "code": b.get("code"), "handle": b.get("handle"), "id": short(b["id"])} for b in rows],
        [("name", "Brand"), ("code", "Code"), ("handle", "Handle"), ("id", "Id")],
        data=rows,
    )
    return 0


# ---------- Videos ----------


def _video_row(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": short(v["id"]),
        "status": v["status"],
        "length": clock((v.get("media") or {}).get("duration")),
        "title": v.get("title") or (v.get("source") or {}).get("name") or "(untitled)",
        "ref": v.get("external_ref"),
    }


VIDEO_COLUMNS = [("id", "Id"), ("status", "Status"), ("length", "Length"), ("title", "Title"), ("ref", "Ref")]


def videos(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    b = resolve.brand(client, args.brand)
    rows = resolve.videos_of(client, b["id"], args.ref)
    if args.status:
        rows = [v for v in rows if v["status"] == args.status]
    out.table([_video_row(v) for v in rows], VIDEO_COLUMNS, data=rows)
    return 0


def video_show(args: argparse.Namespace, out: Out) -> int:
    v = resolve.video(connect(args), args.video)
    text = "\n".join(
        f"{k}: {val}"
        for k, val in (
            ("Video", v["id"]),
            ("Title", v.get("title") or "(untitled)"),
            ("Brand", v.get("brand_name")),
            ("Status", v["status"]),
            ("Length", clock((v.get("media") or {}).get("duration"))),
            ("Made into", v.get("make")),
            ("Ref", v.get("external_ref")),
            ("Job", v.get("job")),
            ("Error", (v.get("error") or {}).get("title") if v.get("error") else None),
        )
        if val
    )
    out.result(v, text)
    return 0


def video_add(args: argparse.Namespace, out: Out) -> int:
    """Upload a file (or have GRM fetch a link), start processing it, and with --wait wait until it gets there."""
    client = connect(args)
    b = resolve.brand(client, args.brand)
    source = args.source
    is_link = source.startswith(("http://", "https://"))
    path = Path(source).expanduser()
    if not is_link and not path.is_file():
        raise usage(f"There's no file at {source}", "Give the path to a video or audio file, or a link to one.")
    if args.ref and not args.again:
        there = resolve.videos_of(client, b["id"], args.ref)
        if there:
            v = there[0]
            out.say(f"{b['name']} already has a video from {args.ref}: {short(v['id'])}. Add --again to add it again.")
            out.result(v, v["id"])
            return 0
    make = "one" if args.one else "clips" if args.clips else None
    if args.dry_run:
        out.say(f"Would {'have GRM fetch' if is_link else 'upload'} {source} to {b['name']} and start processing it.")
        out.say("Processing pays for transcription and the language models.")
        out.result({"brand": b["id"], "source": source, "title": args.title, "ref": args.ref, "make": make}, "")
        return 0
    body: dict[str, Any] = {"brand_id": b["id"], "title": args.title or "", "make": make, "external_ref": args.ref}
    if is_link:
        body["source_url"] = source
    else:
        body["upload_id"] = upload(client, path, out)
    v = client.post("/api/videos", {k: x for k, x in body.items() if x is not None})
    out.say(f"Added {short(v['id'])} to {b['name']}. Processing it pays for transcription and the language models.")
    # Started once its file has been checked; the same request again is the same start.
    v = client.post(f"/api/videos/{v['id']}/start", headers={"Idempotency-Key": f"grm-start-{uuid.uuid4()}"})
    if args.wait:
        v = _wait_for(client, v["id"], args.wait, out, jobs.parse_timeout(args.timeout))
    out.result(v, v["id"])
    return 0


def video_wait(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    v = resolve.video(client, args.video)
    v = _wait_for(client, v["id"], args.until, out, jobs.parse_timeout(args.timeout))
    out.result(v, f"{short(v['id'])} is {v['status']}")
    return 0


def _wait_for(client: Client, video_id: str, until: str, out: Out, timeout: float | None) -> dict[str, Any]:
    """Follow a video's jobs until it is at `until` or past it. Its file is checked first, then it is processed:
    each is a job, and each is followed in turn, at the server's pace."""
    if until not in STAGES:
        raise usage(f"“{until}” isn't a status a video waits for", f"Use one of: {', '.join(STAGES[1:])}.")
    deadline = jobs.monotonic() + timeout if timeout else None
    followed: set[str] = set()
    while True:
        v = client.get(f"/api/videos/{video_id}")
        if v["status"] == "failed":
            err = v.get("error") or {}
            raise GrmError(err.get("title") or "Processing failed", err.get("fix") or "", code="failed")
        if STAGES.index(v["status"]) >= STAGES.index(until):
            return v
        left = None if deadline is None else max(0.0, deadline - jobs.monotonic())
        if left == 0.0:
            raise GrmError(
                f"Gave up waiting: the video is {v['status']}",
                f"It carries on without you. grm video wait {short(video_id)} --until {until}",
                code="timeout",
                exit=3,
            )
        job = v.get("job")
        if job and job not in followed:
            followed.add(job)
            jobs.follow(client, job, out, left)
        else:
            jobs.sleep(5)  # between one job ending and the next starting


def transcript(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    v = resolve.video(client, args.video)
    t = client.get(f"/api/videos/{v['id']}/transcript")
    words = t.get("words") or []
    if args.words:
        out.result(words, "\n".join(f"{w['t0']:.2f}\t{w['t1']:.2f}\t{w.get('s', '')}\t{w['w']}" for w in words))
    elif args.srt:
        out.result(t, _srt(words))
    else:
        sentences = t.get("sentences") or []
        text = "\n".join(_sentence(words, s) for s in sentences) if sentences else " ".join(w["w"] for w in words)
        out.result(t, text)
    return 0


def _sentence(words: list[dict[str, Any]], s: Any) -> str:
    if isinstance(s, dict) and "text" in s:
        return str(s["text"])
    if isinstance(s, (list, tuple)) and len(s) == 2:
        return " ".join(w["w"] for w in words[int(s[0]) : int(s[1]) + 1])
    return str(s)


def _srt(words: list[dict[str, Any]], per: int = 7) -> str:
    def stamp(t: float) -> str:
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    cues = [words[i : i + per] for i in range(0, len(words), per)]
    return "\n".join(
        f"{n}\n{stamp(c[0]['t0'])} --> {stamp(c[-1]['t1'])}\n{' '.join(w['w'] for w in c)}\n"
        for n, c in enumerate(cues, 1)
    )


# ---------- Jobs ----------


def job_show(args: argparse.Namespace, out: Out) -> int:
    j = connect(args).get(f"/api/jobs/{resolve.job_id(args.job)}")
    lines = [jobs.line(j)] + [f"  {jobs.line(c)}" for c in j.get("children") or []]
    if j.get("error"):
        lines.append(f"{j['error'].get('title', '')} {j['error'].get('fix', '')}".strip())
    out.result(j, "\n".join(lines))
    return 0


def job_wait(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    j = jobs.follow(client, resolve.job_id(args.job), out, jobs.parse_timeout(args.timeout))
    out.result(j, jobs.line(j))
    return 0


def jobs_of(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    v = resolve.video(client, args.video)
    rows = client.get("/api/jobs", video=v["id"], limit=args.limit)
    out.table(
        [
            {
                "id": j["id"],
                "kind": j["kind"],
                "status": j["status"],
                "subject": ", ".join(f"{k} {short(x)}" for k, x in (j.get("subject") or {}).items() if k != "video"),
                "at": (j.get("created_at") or "")[:19].replace("T", " "),
            }
            for j in rows
        ],
        [("id", "Job"), ("kind", "Kind"), ("status", "Status"), ("subject", "For"), ("at", "Made")],
        data=rows,
    )
    return 0


# ---------- Clips ----------


def clips(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    v = resolve.video(client, args.video)
    rows = resolve.clips_of(client, v["id"])
    if args.status:
        rows = [c for c in rows if c["status"] == args.status]
    out.table(
        [
            {
                "id": short(c["id"]),
                "status": c["status"],
                "length": clock(c.get("seconds")),
                "title": c.get("title"),
                "hook": (c.get("spec") or {}).get("hook"),
            }
            for c in rows
        ],
        [("id", "Id"), ("status", "Status"), ("length", "Length"), ("title", "Title"), ("hook", "Hook")],
        data=rows,
    )
    return 0


def clip_show(args: argparse.Namespace, out: Out) -> int:
    c = resolve.clip(connect(args), args.clip, video_ref=args.video, match=args.match)
    spec = c.get("spec") or {}
    own = {k: x for k, x in spec.items() if k not in ("copy", "variants", "writing")}
    text = "\n".join(
        [
            f"Clip: {c['id']}",
            f"Title: {c.get('title')}",
            f"Status: {c['status']} (version {c.get('version')})",
            f"Length: {clock(c.get('seconds'))}",
            "Its own settings (everything else is its brand kit's):",
            *(f"  {k}: {json.dumps(x, ensure_ascii=False)}" for k, x in sorted(own.items())),
        ]
    )
    out.result(c, text)
    return 0


# ---------- Exports ----------


def export(args: argparse.Namespace, out: Out) -> int:
    """Export a video's approved assets, wait for every file, and with --out download them."""
    client = connect(args)
    v = resolve.video(client, args.video)
    e = client.post(f"/api/videos/{v['id']}/export", {"ready": args.ready, "editor": args.editor})
    ex = e.get("export") or {}
    if args.no_wait:
        out.result(e, ex.get("job") or ex.get("id") or "")
        return 0
    if ex.get("job"):
        jobs.follow(client, ex["job"], out, jobs.parse_timeout(args.timeout))
    e = client.get(f"/api/videos/{v['id']}/export")
    ex = e["export"]
    files = downloads(ex)
    failed = [r for r in ex.get("renders") or [] if r.get("status") == "failed"]
    for r in failed:
        out.say(f"Failed: {r.get('filename')}: {(r.get('error') or '')}")
    if args.out:
        root = Path(args.out).expanduser()
        paths = []
        for folder, name, url in files:
            dest = root / folder / name
            client.download(url, dest)
            paths.append(str(dest))
        out.result({"export": ex, "files": paths}, "\n".join(paths))
    else:
        out.table(
            [{"file": r["filename"], "size": size(r.get("size_bytes")), "status": r["status"]} for r in ex["renders"]],
            [("file", "File"), ("size", "Size"), ("status", "Status")],
            data=e,
        )
    return 1 if failed else 0


def downloads(ex: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Every finished file of an export, as (folder, name, link): one for each file, and each of the files a render
    made several of (a clip's SRT and VTT captions)."""
    out = []
    for r in ex.get("renders") or []:
        if r.get("status") != "done":
            continue
        folder = r.get("folder") or ""
        if r.get("url"):
            out.append((folder, r["filename"], r["url"]))
        for f in r.get("files") or []:
            if f.get("url"):
                out.append((folder, f["name"], f["url"]))
    return out


def exports(args: argparse.Namespace, out: Out) -> int:
    client = connect(args)
    v = resolve.video(client, args.video)
    data = client.get(f"/api/videos/{v['id']}/exports")
    rows = data if isinstance(data, list) else data.get("assets") or data.get("exports") or []
    out.table(
        [
            {
                "id": short(a.get("id") or a.get("asset_id")),
                "kind": a.get("kind"),
                "title": a.get("title"),
                "status": a.get("status"),
                "ready": ((a.get("export") or {}).get("ready")),
            }
            for a in rows
        ],
        [("id", "Id"), ("kind", "Kind"), ("title", "Title"), ("status", "Status"), ("ready", "Files ready")],
        data=data,
    )
    return 0


# ---------- Any route ----------


def api(args: argparse.Namespace, out: Out) -> int:
    """Any route, with the token filled in: like `gh api`. Routes outside the public API can change without notice."""
    client = connect(args)
    body = json.loads(args.json_body) if args.json_body else None
    for field in args.field or []:
        key, _, value = field.partition("=")
        body = {**(body or {}), key: _value(value)}
    answer = client.request(args.method.upper(), args.path, json=body)
    out.result(answer.body, json.dumps(answer.body, indent=2, ensure_ascii=False) if answer.body is not None else "")
    return 0


def _value(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text
