"""grm: Generational Run Machine from a terminal or a script.

Results go to stdout and progress to stderr; --json makes stdout one JSON document. Exit codes: 0 done, 1 failed,
2 wrong use, 3 gave up waiting, 4 the token lacks the scope, 5 changed since you read it.
"""

from __future__ import annotations

import argparse
import json
import sys

from grm_cli import __version__, commands
from grm_cli.errors import USAGE, GrmError
from grm_cli.output import Out

WAIT_FOR = ["uploaded", "processing", "review", "approved", "exported"]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="grm",
        description="Generational Run Machine from a terminal or a script.",
        epilog="Exit codes: 0 done, 1 failed, 2 wrong use, 3 gave up waiting, 4 token lacks the scope, "
        "5 changed since you read it.",
    )
    p.add_argument("--version", action="version", version=f"grm {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="which sign-in to use (default: the first you made, or GRM_PROFILE)")
    common.add_argument("--json", action="store_true", help="stdout is one JSON document")
    common.add_argument("-q", "--quiet", action="store_true", help="no progress on stderr")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    def cmd(parent, name: str, fn, help: str) -> argparse.ArgumentParser:
        c = parent.add_parser(name, parents=[common], help=help, description=help)
        c.set_defaults(fn=fn)
        return c

    c = cmd(sub, "login", commands.login, "sign in with a token made on Settings, API tokens")
    c.add_argument("--url", help="the GRM server (default: GRM's own, or GRM_URL)")
    cmd(sub, "logout", commands.logout, "forget the token kept for this profile")
    cmd(sub, "whoami", commands.whoami, "who you are signed in as, where, and what the token may do")

    cmd(sub, "brands", commands.brands, "the brands in your workspace")

    c = cmd(sub, "videos", commands.videos, "a brand's videos, newest first")
    c.add_argument("brand", help="name, handle or code")
    c.add_argument("--status", help="only these: uploaded, processing, review, approved, exported, failed")
    c.add_argument("--ref", help="only the one added with this --ref")

    video = sub.add_parser("video", help="add, show or wait for a video")
    video = video.add_subparsers(dest="action", metavar="<action>")
    c = cmd(video, "add", commands.video_add, "upload a file (or have GRM fetch a link) and process it")
    c.add_argument("brand", help="name, handle or code")
    c.add_argument("source", help="a video or audio file, or a link to one")
    c.add_argument("--title", help="what it is called (default: the file's name)")
    c.add_argument("--ref", help="where it came from, in your words (drive:1AbC…): adding it again is refused")
    c.add_argument("--again", action="store_true", help="add it even if a video with this --ref is there")
    one = c.add_mutually_exclusive_group()
    one.add_argument("--clips", action="store_true", help="cut it into clips (the default for anything long)")
    one.add_argument("--one", action="store_true", help="make the whole video one clip")
    c.add_argument("--wait", choices=WAIT_FOR, metavar="STATUS", help="wait until it gets there (e.g. review)")
    c.add_argument("--timeout", help="give up waiting after this long (90s, 30m, 2h)")
    c.add_argument("--dry-run", action="store_true", help="say what it would do, and do nothing")
    c = cmd(video, "show", commands.video_show, "a video's details and status")
    c.add_argument("video", help="its id, or its first 8 characters")
    c = cmd(video, "wait", commands.video_wait, "wait until a video gets to a status")
    c.add_argument("video", help="its id, or its first 8 characters")
    c.add_argument("--until", choices=WAIT_FOR, metavar="STATUS", default="review", help="default: review")
    c.add_argument("--timeout", help="give up after this long (90s, 30m, 2h)")

    c = cmd(sub, "transcript", commands.transcript, "a video's transcript")
    c.add_argument("video", help="its id, or its first 8 characters")
    how = c.add_mutually_exclusive_group()
    how.add_argument("--words", action="store_true", help="every word with its start, end and speaker")
    how.add_argument("--srt", action="store_true", help="as subtitles")

    job = sub.add_parser("job", help="a job, or wait for one").add_subparsers(dest="action", metavar="<action|id>")
    c = cmd(job, "show", commands.job_show, "a job's status, progress and children")
    c.add_argument("job")
    c = cmd(job, "wait", commands.job_wait, "wait for a job to end")
    c.add_argument("job")
    c.add_argument("--timeout", help="give up after this long (90s, 30m, 2h)")
    c = cmd(sub, "jobs", commands.jobs_of, "every job for a video and its clips, newest first")
    c.add_argument("video", help="its id, or its first 8 characters")
    c.add_argument("--limit", type=int, default=50)

    c = cmd(sub, "clips", commands.clips, "a video's clips: id, status, length, title, hook")
    c.add_argument("video", help="its id, or its first 8 characters")
    c.add_argument("--status", help="only these: review, approved, rejected")
    clip = sub.add_parser("clip", help="one clip").add_subparsers(dest="action", metavar="<action>")
    c = cmd(clip, "show", commands.clip_show, "a clip's details and its own settings")
    c.add_argument("clip", nargs="?", help="its id, or its first 8 characters")
    c.add_argument("--match", help="or words of its title")
    c.add_argument("--video", help="look in this video only")

    c = cmd(sub, "export", commands.export, "export a video's approved assets, wait, and download them")
    c.add_argument("video", help="its id, or its first 8 characters")
    c.add_argument("--out", help="download every file into this folder and print their paths")
    c.add_argument("--ready", action="store_true", help="only what is ready now: nothing is rendered again")
    c.add_argument("--editor", action="store_true", help="with --ready: each clip's files for an editor too")
    c.add_argument("--no-wait", action="store_true", help="start it and print its job's id")
    c.add_argument("--timeout", help="give up waiting after this long (90s, 30m, 2h)")
    c = cmd(sub, "exports", commands.exports, "each asset of a video and whether its files are ready")
    c.add_argument("video", help="its id, or its first 8 characters")

    c = cmd(sub, "api", commands.api, "any route, with the token filled in (like gh api)")
    c.add_argument("method", help="GET, POST, PATCH, PUT or DELETE")
    c.add_argument("path", help="/api/…")
    c.add_argument("--json-body", help="the request's body, as JSON")
    c.add_argument("-f", "--field", action="append", help="key=value in the body (value as JSON where it is)")
    return p


def main(argv: list[str] | None = None) -> int:
    p = parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    # The options every command takes may come before the command too: grm --profile dev videos kyree.
    first: list[str] = []
    while argv and argv[0] in ("--profile", "--json", "-q", "--quiet"):
        option = argv.pop(0)
        first.append(option)
        if option == "--profile" and argv:
            first.append(argv.pop(0))
    argv += first
    # `grm job <id>` is `grm job show <id>`.
    if len(argv) >= 2 and argv[0] == "job" and argv[1] not in ("show", "wait", "-h", "--help"):
        argv = ["job", "show", *argv[1:]]
    args = p.parse_args(argv)
    if not getattr(args, "fn", None):
        p.print_help(sys.stderr)
        return USAGE
    out = Out(as_json=args.json, quiet=args.quiet)
    try:
        return args.fn(args, out)
    except GrmError as e:
        if args.json:
            print(json.dumps(e.as_json(), indent=2, ensure_ascii=False))
        print(f"grm: {e.title}", file=sys.stderr)
        if e.fix:
            print(f"     {e.fix}", file=sys.stderr)
        return e.exit
    except KeyboardInterrupt:
        print("grm: stopped", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
