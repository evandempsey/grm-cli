# grm-cli

The command line for [Generational Run Machine](https://app.generationalrunmachine.com) (GRM): add a video, wait for
its clips, change the brand kit and the clips, see and hear them, and export them, from a terminal or a script. Results go to stdout and progress to stderr,
`--json` makes stdout one JSON document, and the exit code says how it went, so a script (or an agent) can drive it.

## Install and sign in

```sh
uv tool install grm-cli          # or: pipx install grm-cli
grm login                        # asks for a token, and keeps it in your keychain
grm whoami                       # who you are, which workspace, what the token may do, which server
```

Make the token in GRM, on **Settings, API tokens**: tick what it may do (Read and Edit to start; Generate to process
videos, which pays for transcription and models; Approve; Export). A token belongs to one person and one workspace.

- The token is kept in the operating system's keychain. It is never taken as a command argument, which would land in
  shell history: `grm login` asks for it, or reads it from stdin (`grm login < token.txt`).
- `GRM_TOKEN` (and `GRM_URL`) in the environment are for CI and win over the keychain.
- The server is GRM's own unless `--url` at login, `GRM_URL` or a profile says otherwise. Profiles keep more than one:
  `grm login --profile dev --url http://localhost:8000`, then `grm … --profile dev` (or `GRM_PROFILE=dev`).
- Python 3.11 or later.

## Commands

```text
grm brands                                       the brands in your workspace
grm videos <brand> [--status review] [--ref …]   a brand's videos
grm video add <brand> <file|link> [--title …] [--ref drive:1AbC…] [--clips|--one] [--wait review] [--dry-run]
grm video show <video>
grm video wait <video> [--until review] [--timeout 30m]
grm transcript <video> [--words|--srt]
grm job <job> | grm job wait <job> [--timeout 10m] | grm jobs <video>
grm clips <video> [--status review]              id, status, length, title, hook
grm clip show <clip> | --match "words of its title" [--video <video>]
grm export <video> [--out ./export/] [--ready] [--no-wait] [--timeout 1h]
grm exports <video>                              each asset, and whether its files are ready
grm api GET /api/videos/<id>/spares              any route, with the token filled in (like gh api)
grm api POST /api/assets/<id>/status -f status=approved
```

Changing things (0.2):

```text
grm kit get <brand> [--path captions]            the brand's settings as they take effect, as YAML
grm kit set <brand> filter.id=instant voice.room=small writing.cta="Follow for more"
grm kit unset <brand> voice.room                 back to the default
grm kit diff <brand> kit.yaml                    the live kit against a kit file
grm kit apply <brand> kit.yaml [--dry-run]       make the live kit match the file
grm kit history <brand> | grm kit restore <brand> <version>
grm clip set <clip> hook="Your wife isn't a spreadsheet" thumb.t=12.4 captions.preset=bold
grm clip unset <clip> thumb captions.preset      back to the kit's
grm clip rewrite <clip> [--field tiktok] make it shorter      a language model rewrites it (paid)
grm clip history <clip> | grm clip restore <clip> <version>
grm bulk <video> set captions.preset=bold        every clip of a video, saved together or not at all
grm bulk <video> unset music.track
grm apply plan.yaml [--dry-run] [--wait]         the kit and many clips in one go (see Plan files)
grm snapshot <brand> "before the look" [--video <video>]       keep the kit and the clips' settings
grm snapshots <brand> | grm snapshot diff <snapshot> | grm snapshot restore <snapshot> [--only brand|clips]
grm snapshot delete <snapshot> --yes
```

Seeing and hearing without a browser (drawn by GRM, nothing paid for; files go to `./grm-out/`, named for the clip):

```text
grm look <clip> --at 3 9.5                       stills at those moments
grm look <clip> --sheet [6]                      an overview: N moments on one picture
grm look <clip> --at 3 --try captions.preset=bold,subtitle,neon      variants side by side, not saved
grm thumbs <video>                               every clip's thumbnail on one picture
grm listen <clip> [--no-music]                   the clip's sound as the export mixes it (MP3), and its levels
```

- **Names instead of ids.** A brand by its name, code or handle (`shopfloor`, `@shopfloor`, or the start of its
  name). A video or a clip by the first 8 characters of its id, as the lists show it, or a clip by words of its title
  (`--match`). A name that matches two things is refused, with both listed.
- **Waiting is done by grm.** `video add --wait`, `video wait`, `job wait` and `export` ask after the work at the pace
  the server sets (its `Retry-After`), say how it stands on stderr (each stage of processing on a line of its own),
  and end when it does. `--timeout` gives up (exit 3) and leaves the work running.
- **Adding the same file twice.** `video add --ref <where it came from>` with a ref already there says so, prints
  that video's id and adds nothing, unless `--again`.
- **Paying.** Processing a video pays for transcription and the language models: `video add` says so, and
  `--dry-run` says what it would do and does nothing.
- **Exports.** `export --out <folder>` waits for every file, downloads them into the folders the pack uses (TikTok,
  Instagram, …), each clip's SRT and VTT captions included, and prints their paths, one per line.

- **Settings by path.** A path names one setting: `captions.preset`, `thumb.t`, `music.on`. A value is JSON where it
  is JSON (`12.4`, `true`, `null`, `["a","b"]`, `{"id":"x"}`) and words otherwise. The kit's paths are its own
  (`captions.preset`, `filter.id`, `voice.room`); the brand's writing settings are `writing.…` and its default pack
  `pack.…`. A clip's paths are its own, and `title` is its title. Every change is printed path by path, before and
  after.
- **Nothing is written over.** A change is saved only if what it changes is still at the version grm read; if someone
  changed it meanwhile (in review, say), grm stops with exit 5 and changes nothing. Every change is a version:
  `history` lists them and `restore` puts one back, itself as a new version, so a restore can be undone too.
- **Compared as it takes effect.** `kit get` prints the settings with the defaults filled in, and `kit diff` and
  `kit apply` compare on those, so a setting left at its default and the same value written down are the same.
  `grm kit get <brand> > kit.yaml` is a kit file: keep it in git, edit it, `kit apply` it.

### Kit files

```yaml
kit:                       # the brand kit, nested or with dotted keys
  filter: {id: instant}
  captions: {preset: shadow}
  voice.room: small
writing:                   # the brand's writing settings
  cta: Follow Kyree
pack:                      # the brand's default pack
  clips: 8
unset: [titleRule]         # back to the defaults
```

`kit apply` changes only what differs from the live kit, in one save.

### Plan files

```yaml
brand: kyree
video: bf4a1894
snapshot: before kyree look          # taken first; leave it out to skip it
kit:
  set: {filter.id: instant, voice.room: small}
  unset: [titleRule]
clips:                               # each clip by the start of its id
  3ef224f9:
    hook: The worst marriage advice I ever got
    thumb.t: 3.2
  f200fa5c:
    music: {make: "low strings, minor key, no drums"}
  c213c79d:
    music: off
```

`grm apply plan.yaml --dry-run` prints every change and every paid call (music made by ElevenLabs), and does nothing.
Without it, the snapshot is taken first, then the kit is changed in one save, then every clip in one save: all are
checked before any is saved, so a clip that fails leaves every clip as it was (and the error says how to put the kit
back from the snapshot). Music to make is started last; with `--wait`, each clip gets the first of its two new tracks
when they are made. Applying the same plan again changes nothing and takes no snapshot. `apply` needs a GRM that
speaks api 2.

Exit codes:

| Code | Means |
|---|---|
| 0 | Done |
| 1 | Failed (the error's title and fix on stderr; its `code` in `--json`) |
| 2 | Wrong use of the command (including a name that matches nothing, or two things) |
| 3 | Gave up waiting (`--timeout`) |
| 4 | The token lacks the scope |
| 5 | Changed since you read it |

`grm api` reaches any route. The ones grm calls are GRM's public API (tagged `public` in its `/openapi.json`); what
they take changes only with the `api` version in `/api/meta`, which `grm whoami` shows. Other routes can change without
notice.

## Try the whole loop for free

GRM runs with stand-ins for every paid service (transcription, models, pictures, music, rendering), so the whole loop
costs nothing on a local GRM. In a checkout of GRM, start its test stack:

```sh
scripts/e2e_stack.sh start       # GRM's API on http://localhost:8010 and its web app on :5183, with the stand-ins
```

Sign up at http://localhost:5183, make a brand and a token (Settings, API tokens), then:

```sh
grm login --profile local --url http://localhost:8010
grm video add "My brand" episode.mp4 --wait review --profile local
grm clips <video> --profile local
grm api POST /api/assets/<clip>/status -f status=approved --profile local
grm export <video> --out ./export/ --profile local
```

Rewrites on the test stack are written by a stand-in, so they cost nothing there either.

## Working on grm

```sh
uv sync
uv run pytest                          # unit tests: grm against answers a real GRM gave (tests/answers/)
uv run ruff check src tests && uv run ruff format src tests
```

- **The smoke test** runs grm's whole loop against a local GRM. It makes its own account, workspace, brand and
  token, so sign-up must be open, as it is on the test stack:

  ```sh
  uv run python tests/smoke.py --url http://localhost:8010 --file path/to/video.mp4
  ```

  GRM's own CI runs it against GRM's test stack, so a change to GRM can't quietly break grm.
- **Recorded answers.** `tests/answers/` is what a real GRM answered to each route grm calls. Record them again after
  GRM's public API changes: `uv run python tests/record.py --url http://localhost:8010 --file path/to/video.mp4`.
- **Releasing.** Push a tag matching the version in `pyproject.toml` (`v0.2.0`): GitHub Actions tests it, builds it and
  publishes it to PyPI with trusted publishing, so no PyPI token is stored anywhere. Versions stay `0.x` until GRM's
  public API has held for a month.

## Licence

MIT: see [LICENSE](LICENSE).
