"""grm: Generational Run Machine from a terminal or a script.

Results go to stdout and progress to stderr; --json makes stdout one JSON document. Exit codes: 0 done, 1 failed,
2 wrong use, 3 gave up waiting, 4 the token lacks the scope, 5 changed since you read it.
"""

from __future__ import annotations

import argparse
import json
import sys

from grm_cli import __version__, commands, edit, kit, looks, plans, snapshots
from grm_cli.errors import USAGE, GrmError, usage
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

    def which_clip(c: argparse.ArgumentParser, then: tuple[str, str, str] | None = None) -> None:
        """The clip by its id (first word), or by --match. With `then` (dest, metavar, kind), more words follow it:
        argparse can't split an optional word from those that follow once an option comes between them, so grm
        does (see _split_clip)."""
        c.add_argument("--match", help="or words of its title (then no id comes first)")
        c.add_argument("--video", help="look in this video only")
        if then is None:
            c.add_argument("clip", nargs="?", help="its id, or its first 8 characters")
            return
        dest, metavar, _ = then
        c.add_argument(
            "words",
            nargs="+",
            metavar=f"clip {metavar}",
            help=f"the clip's id (or its first 8 characters), then {metavar}; with --match, only {metavar}",
        )
        c.set_defaults(then=then)

    clip = sub.add_parser("clip", help="one clip: show, change, rewrite, history").add_subparsers(
        dest="action", metavar="<action>"
    )
    c = cmd(clip, "show", commands.clip_show, "a clip's details and its own settings")
    which_clip(c)
    c = cmd(clip, "set", edit.set_, 'change a clip\'s settings: hook="…" thumb.t=12.4 captions.preset=bold')
    which_clip(c, ("settings", "path=value…", "list"))
    c = cmd(clip, "unset", edit.unset, "put a clip's settings back to its kit's: filter captions.style")
    which_clip(c, ("paths", "path…", "list"))
    c = cmd(
        clip, "rewrite", edit.rewrite, "rewrite one of a clip's texts with an instruction (a model writes it: paid)"
    )
    which_clip(c, ("instruction", "instruction", "text"))
    c.add_argument("--field", choices=edit.FIELDS, default="tiktok", help="which text (default: tiktok)")
    c.add_argument("--variant", type=int, default=0, help="which of its variants to start from (default: the first)")
    c.add_argument("--dry-run", action="store_true", help="say what it would do, and do nothing")
    c.add_argument("--timeout", help="give up waiting after this long (90s, 30m, 2h)")
    c = cmd(clip, "history", edit.history, "every version of a clip")
    which_clip(c)
    c = cmd(clip, "restore", edit.restore, "put a clip back to one of its versions (itself a version: undoable)")
    which_clip(c, ("version", "version", "int"))

    c = cmd(sub, "bulk", edit.bulk, "the same change on every clip of a video, saved together or not at all")
    c.add_argument("video", help="its id, or its first 8 characters")
    c.add_argument("how", choices=["set", "unset"])
    c.add_argument("settings", nargs="+", metavar="path=value|path")

    kits = sub.add_parser("kit", help="a brand's kit: get, set, unset, diff, apply, history, restore")
    kits = kits.add_subparsers(dest="action", metavar="<action>")
    c = cmd(kits, "get", kit.get, "the brand's settings as they take effect, as YAML (what kit apply reads)")
    c.add_argument("brand", help="name, handle or code")
    c.add_argument("--path", help="only this setting, or set of settings (captions, writing.cta)")
    c = cmd(kits, "set", kit.set_, 'change kit settings: filter.id=instant voice.room=small writing.cta="…"')
    c.add_argument("brand", help="name, handle or code")
    c.add_argument("settings", nargs="+", metavar="path=value")
    c = cmd(kits, "unset", kit.unset, "put kit settings back to the defaults")
    c.add_argument("brand", help="name, handle or code")
    c.add_argument("paths", nargs="+", metavar="path")
    c = cmd(kits, "diff", kit.diff, "the live kit against a kit file")
    c.add_argument("brand", help="name, handle or code")
    c.add_argument("file", help="a kit file: kit:, writing:, pack:, unset:")
    c = cmd(kits, "apply", kit.apply, "make the live kit match a kit file")
    c.add_argument("brand", help="name, handle or code")
    c.add_argument("file", help="a kit file: kit:, writing:, pack:, unset:")
    c.add_argument("--dry-run", action="store_true", help="say what it would change, and change nothing")
    c = cmd(kits, "history", kit.history, "every version of the brand's settings")
    c.add_argument("brand", help="name, handle or code")
    c = cmd(kits, "restore", kit.restore, "put the brand's settings back to a version (itself a version: undoable)")
    c.add_argument("brand", help="name, handle or code")
    c.add_argument("version", type=int)

    c = cmd(sub, "apply", plans.apply, "a plan file: the kit and many clips changed in one go")
    c.add_argument("plan", help="a plan file (see grm-cli's README)")
    c.add_argument("--dry-run", action="store_true", help="print every change and paid call, and do nothing")
    c.add_argument("--wait", action="store_true", help="wait for music being made, and put it on its clip")
    c.add_argument("--timeout", help="give up waiting after this long (90s, 30m, 2h)")

    snap = sub.add_parser("snapshot", help="take, diff, restore or delete a snapshot")
    snap = snap.add_subparsers(dest="action", metavar="<brand|action>")
    c = cmd(snap, "take", snapshots.take, "keep a brand's kit and its clips' settings under a name")
    c.add_argument("brand", help="name, handle or code")
    c.add_argument("name", help='what it is before, e.g. "before kyree look"')
    c.add_argument("--video", help="only this video's clips (default: every video's)")
    c = cmd(snap, "diff", snapshots.diff, "what is different now from a snapshot")
    c.add_argument("snapshot", help="its id, or its first 8 characters")
    c = cmd(snap, "restore", snapshots.restore, "put a snapshot back (undoable: each change is a version)")
    c.add_argument("snapshot", help="its id, or its first 8 characters")
    c.add_argument("--only", choices=["brand", "clips"], help="only the kit, or only the clips")
    c = cmd(snap, "delete", snapshots.delete, "delete a snapshot (needs --yes: it can't be undone)")
    c.add_argument("snapshot", help="its id, or its first 8 characters")
    c.add_argument("--yes", action="store_true")
    c = cmd(sub, "snapshots", snapshots.list_, "a brand's snapshots")
    c.add_argument("brand", help="name, handle or code")

    c = cmd(sub, "look", looks.look, "see a clip: stills, an overview sheet, or variants side by side (not saved)")
    which_clip(c)
    c.add_argument("--at", nargs="+", type=float, metavar="SECONDS", help="moments, in seconds into the clip")
    c.add_argument(
        "--sheet",
        nargs="?",
        type=int,
        const=6,
        metavar="N",
        help="one picture: N moments picked for an overview (default 6), or the --at moments",
    )
    c.add_argument(
        "--try", dest="try_", metavar="PATH=A,B", help="variants side by side: captions.preset=bold,subtitle"
    )
    c.add_argument("--aspect", default="9:16", choices=["9:16", "1:1", "4:5", "16:9"])
    c.add_argument("--width", type=int, help="pixels across each picture (default 1080)")
    c.add_argument("--out", help=f"the folder for the files (default ./{looks.OUT})")
    c.add_argument("--timeout", help="give up waiting after this long (90s, 30m, 2h)")
    c = cmd(sub, "thumbs", looks.thumbs, "every clip's thumbnail of a video in one picture")
    c.add_argument("video", help="its id, or its first 8 characters")
    c.add_argument("--width", type=int, help="pixels across the picture (default 1600)")
    c.add_argument("--columns", type=int, help="thumbnails across (default 3)")
    c.add_argument("--out", help=f"the folder for the file (default ./{looks.OUT})")
    c.add_argument("--timeout", help="give up waiting after this long (90s, 30m, 2h)")
    c = cmd(sub, "listen", looks.listen, "a clip's sound as the export mixes it (MP3), and its levels")
    which_clip(c)
    c.add_argument("--no-music", action="store_true", help="the voices alone")
    c.add_argument("--out", help=f"the folder for the file (default ./{looks.OUT})")
    c.add_argument("--timeout", help="give up waiting after this long (90s, 30m, 2h)")

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
    # `grm job <id>` is `grm job show <id>`; `grm snapshot <brand> <name>` is `grm snapshot take …`.
    if len(argv) >= 2 and argv[0] == "job" and argv[1] not in ("show", "wait", "-h", "--help"):
        argv = ["job", "show", *argv[1:]]
    if (
        len(argv) >= 2
        and argv[0] == "snapshot"
        and argv[1] not in ("take", "diff", "restore", "delete", "-h", "--help")
    ):
        argv = ["snapshot", "take", *argv[1:]]
    # A clip command's words may come either side of its options (`clip set 3ef2 --video bf4a hook=…`); argparse
    # takes the first run of them only, and leaves the rest over.
    args, rest = p.parse_known_args(argv)
    if rest:
        if getattr(args, "then", None) and not any(r.startswith("-") for r in rest):
            args.words += rest
        else:
            p.error(f"unrecognized arguments: {' '.join(rest)}")
    if not getattr(args, "fn", None):
        p.print_help(sys.stderr)
        return USAGE
    out = Out(as_json=args.json, quiet=args.quiet)
    try:
        _split_clip(args)
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


def _split_clip(args: argparse.Namespace) -> None:
    """The words after a clip command: the clip's id first, unless --match names it; then what the command takes."""
    then = getattr(args, "then", None)
    if not then:
        return
    dest, metavar, kind = then
    words = list(args.words)
    args.clip = None if args.match else words.pop(0)
    if not words:
        raise usage(f"Say the {metavar.rstrip('…')} after the clip", f"grm clip {args.action} --help")
    if kind == "text":
        setattr(args, dest, " ".join(words))
    elif kind == "int":
        if len(words) != 1 or not words[0].isdigit():
            words_said = " ".join(words)
            raise usage(f"“{words_said}” isn't a version number", "grm clip history <clip> lists them.")
        setattr(args, dest, int(words[0]))
    else:
        setattr(args, dest, words)


if __name__ == "__main__":
    raise SystemExit(main())
