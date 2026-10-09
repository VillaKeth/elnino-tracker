#!/usr/bin/env python3
"""Publish the pages of the last run as the El Nino site on GitHub Pages.

    python publish.py                  publish what output/ holds now
    python publish.py --dry-run        check all of it; push nothing
    python publish.py --allow-older    publish a run older than the site's

The site is the gh-pages branch of this project's repository on GitHub, served
at SITE. Each publish replaces that branch with one commit holding the last
run's pages, and the assets they name, byte for byte: generated output keeps
no history there, as output/ keeps none here.

Nothing of this machine's git setup goes up with them. The commit is made in a
throwaway repository that reads none of this machine's git configuration (no
hooks, no signing, no line-ending conversion, no ignore rules), under the
site's own name and GitHub no-reply address; and git may reach the repository
over HTTPS only, so no rewrite of its address can send the push over SSH under
another account. Refused before anything is pushed: a missing, empty or cut-off
page, an asset a page names that is missing or is not the file its name was
taken from, a page or an asset that names this machine's home folder in any
spelling, a page of another run than latest.json's or naming none, and a run
older than the one the site shows.

Exit codes: 0 published (or checked, with --dry-run), 2 could not publish.

Pure standard library, like track.py. git does the committing and the push,
with the credential git has for GitHub (`gh auth setup-git`), and never waits
at a prompt for one.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from elnino import assets

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "output"
REMOTE = "https://github.com/VillaKeth/elnino-tracker.git"
BRANCH = "gh-pages"
SITE = "https://villaketh.github.io/elnino-tracker/"
IDENTITY = ("VillaKeth", "170055060+VillaKeth@users.noreply.github.com")

# Each page as the site serves it, from the file in output/ it is copied from.
# The site opens on the dashboard, which is also kept under its own name: the
# other pages link back to dashboard.html.
PAGES = {
    "index.html": "dashboard.html",
    "dashboard.html": "dashboard.html",
    "storms.html": "storms.html",
    "map.html": "map.html",
    "atlas.html": "atlas.html",
    "latest.json": "latest.json",
    "storms.json": "storms.json",
    # The beacon an open page asks which run the site serves (elnino/live.py).
    "run.json": "run.json",
    # The service worker that keeps the assets (elnino/assets.py).
    assets.WORKER: assets.WORKER,
}
# Branches that hold code, which a publish must never replace.
CODE_BRANCHES = ("main", "master")

# What git clears on entering another repository (`git rev-parse
# --local-env-vars`), none of which may steer the throwaway one. Without
# GIT_CONFIG_COUNT, git reads no GIT_CONFIG_KEY_n or GIT_CONFIG_VALUE_n either.
_LOCAL_ENV = frozenset((
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT", "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE", "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX",
    "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
))
# The throwaway repository's own settings. Its commit is made with no global or
# system configuration at all, so these only hold the same line for a git too
# old to honour GIT_CONFIG_GLOBAL, and for the push and the fetch, which read
# the global configuration for their credential. A hook or a signing key of
# this machine's would put its owner's name in the site's commit.
_SEALED = (
    ("commit.gpgsign", "false"),
    ("core.autocrlf", "false"),
    ("core.fsmonitor", "false"),
)
# Git may reach the site's repository over HTTPS only, or a local path (the
# tests' stand-in): an address rewritten to SSH fails before it connects.
_WIRE = ("-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
         "-c", "protocol.file.allow=always")
_SLASHES = re.compile(r"[\\/]+")
# Where each page names the run it is of: an HTML page in a mark in its head,
# a data file under a key of its own. latest.json is the run's own record.
_MARK = re.compile(rb'<meta name="elnino-run" content="([^"]*)">')
_NAMED = {"storms.json": "built", "run.json": "run_at"}


class PublishError(Exception):
    """The site cannot be published as it stands; nothing was pushed."""


def _environment() -> dict[str, str]:
    """This process's environment, less whatever could steer git into another
    repository or configuration, with the site's identity; and no prompt, so a
    push with no credential fails at once instead of waiting for someone."""
    env = {key: value for key, value in os.environ.items() if key not in _LOCAL_ENV}
    name, email = IDENTITY
    env.update(GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_NAME=name,
               GIT_COMMITTER_EMAIL=email, GIT_TERMINAL_PROMPT="0")
    return env


def _moment(text: str) -> datetime:
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _run_at(latest: bytes | str) -> str:
    """The run's time as latest.json writes it."""
    try:
        text = str(json.loads(latest)["run_at"])
        _moment(text)
    except (ValueError, KeyError, TypeError):
        raise PublishError("latest.json gives no run time: run track.py first") from None
    return text


def _complete(name: str, data: bytes) -> bool:
    """Whether a page was written to its end: JSON that parses, HTML that
    closes, the service worker this code writes. A run that dies while
    writing leaves none of them."""
    if name == assets.WORKER:
        return data == assets.WORKER_JS.encode("utf-8")
    if name.endswith(".json"):
        try:
            json.loads(data)
        except ValueError:
            return False
        return True
    return data.rstrip().lower().endswith(b"</html>")


def _read(out_dir: Path) -> dict[str, bytes]:
    """Each of the last run's pages, read once: what is checked is what goes up."""
    pages, faults = {}, []
    for name in sorted(set(PAGES.values())):
        try:
            data = (out_dir / name).read_bytes()
        except FileNotFoundError:
            faults.append(f"{name} is missing")
            continue
        except OSError as exc:
            raise PublishError(f"{name} could not be read: {exc.strerror or exc}") from None
        if not data.strip():
            faults.append(f"{name} is empty")
        elif not _complete(name, data):
            faults.append(f"{name} is not the service worker this code writes" if name == assets.WORKER
                          else f"{name} is cut off")
        pages[name] = data
    if faults:
        raise PublishError(f"{'; '.join(faults)} in {out_dir}: run track.py first")
    return pages


def _read_assets(out_dir: Path, pages: dict[str, bytes]) -> dict[str, bytes]:
    """The assets the pages name (elnino/assets.py), read once from out_dir's
    assets folder, each the very file its name was taken from."""
    naming: dict[str, list[str]] = {}
    for name, data in pages.items():
        if name.endswith(".html"):
            for file in assets.page_assets(data.decode("utf-8", "replace")):
                naming.setdefault(file, []).append(name)
    found, faults = {}, []
    for file, names in sorted(naming.items()):
        where = f"{assets.FOLDER}/{file}"
        try:
            data = (out_dir / assets.FOLDER / file).read_bytes()
        except FileNotFoundError:
            faults.append(f"{where}, named by {', '.join(names)}, is missing")
            continue
        except OSError as exc:
            raise PublishError(f"{where} could not be read: {exc.strerror or exc}") from None
        if not assets.whole(file, data):
            faults.append(f"{where} is not the file its name was taken from")
        found[file] = data
    if faults:
        raise PublishError(f"{'; '.join(faults)} in {out_dir}: run track.py first")
    return found


def _plain(text: str) -> str:
    """Text as the home check reads it: percent escapes decoded, case folded,
    and every run of slashes and backslashes one slash. A path escaped once or
    twice, written as a file address, or as Git Bash or a network share writes
    it, then reads alike."""
    return _SLASHES.sub("/", unquote(text).casefold())


def _home_mark(home: Path) -> re.Pattern[str] | None:
    """The home folder as _plain reads it, less its drive, and not merely the
    start of a longer name; None when it is too short to tell anything by."""
    tail = _plain(home.as_posix()[len(home.drive):])
    if tail.count("/") < 2:
        return None
    return re.compile(re.escape(tail) + r"(?![\w.-])")


def _check_home(pages: dict[str, bytes], home: Path) -> None:
    mark = _home_mark(home)
    named = [name for name, data in pages.items()
             if mark and mark.search(_plain(data.decode("utf-8", "replace")))]
    if named:
        raise PublishError(f"{', '.join(named)} name{'s' if len(named) == 1 else ''} "
                           f"this machine's home folder ({home})")


def _named_run(name: str, data: bytes) -> str | None:
    """The run a page names, as it names it; None when it names none, or names
    it in words no time can be read from."""
    if name.endswith(".html"):
        head, closed, _ = data.partition(b"</head>")
        found = _MARK.search(head) if closed else None
        run = html.unescape(found.group(1).decode("utf-8", "replace")) if found else None
    else:
        try:
            run = json.loads(data).get(_NAMED[name])
        except (ValueError, AttributeError):
            run = None
    if not isinstance(run, str):
        return None
    try:
        _moment(run)
    except ValueError:
        return None
    return run


def _check_one_run(pages: dict[str, bytes], when: str) -> None:
    """Every page names latest.json's run, compared as moments. A page of
    another run is half of two runs, and a page that names a run run.json
    never names would load again for ever, looking for it."""
    faults = []
    for name, data in pages.items():
        # latest.json is what they are checked against; the worker is every run's.
        if name in ("latest.json", assets.WORKER):
            continue
        run = _named_run(name, data)
        if run is None:
            faults.append(f"{name} names no run")
        elif _moment(run) != _moment(when):
            faults.append(f"{name} names the run of {run}")
    if faults:
        raise PublishError(f"{'; '.join(faults)}, where latest.json names the run of {when}: "
                           "run track.py again")


def lay_out(out_dir: Path, site: Path, home: Path | None = None) -> str:
    """Write the last run's pages, and the assets they name, into site as the
    site serves them, and return the run's time as latest.json gives it.
    Raises PublishError, having written nothing, when a page is missing, empty
    or cut off, an asset a page names is missing or is not the file its name
    was taken from, latest.json gives no run time, a page or an asset names
    this machine's home folder, or a page is of another run or names none."""
    pages = _read(out_dir)
    when = _run_at(pages["latest.json"])
    shared = _read_assets(out_dir, pages)
    _check_home({**pages, **{f"{assets.FOLDER}/{file}": data for file, data in shared.items()}},
                Path.home() if home is None else home)
    _check_one_run(pages, when)
    for name, source in PAGES.items():
        (site / name).write_bytes(pages[source])
    if shared:
        (site / assets.FOLDER).mkdir()
        for file, data in shared.items():
            (site / assets.FOLDER / file).write_bytes(data)
    # Served as written: without this file GitHub puts the pages through Jekyll.
    (site / ".nojekyll").write_bytes(b"")
    return when


def _site_files(site: Path) -> list[str]:
    """What the site is, file by file: its pages, the worker and .nojekyll,
    and the assets its pages name, read from the pages laid out in site. The
    commit is checked against this, not against whatever was laid out."""
    named = set()
    for name in PAGES:
        if name.endswith(".html") and (site / name).is_file():
            named.update(assets.page_assets((site / name).read_bytes().decode("utf-8", "replace")))
    return sorted([*PAGES, ".nojekyll", *(f"{assets.FOLDER}/{file}" for file in named)])


def _git(args: list[str], cwd: Path, env: dict[str, str]) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True,
                              encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise PublishError("git is not installed") from None
    if done.returncode:
        verb = next(arg for arg in args if not arg.startswith("-") and "=" not in arg)
        raise PublishError(f"git {verb} failed: {(done.stderr or done.stdout).strip()}")
    return done.stdout.strip()


def _shown_run(site: Path, env: dict[str, str], sealed: dict[str, str],
               remote: str, branch: str) -> str | None:
    """The run the site shows now, from its latest.json; None when nothing is
    published there yet, or what is there gives no run time."""
    ref = f"refs/heads/{branch}"
    if not _git([*_WIRE, "ls-remote", remote, ref], site, env):
        return None
    _git([*_WIRE, "fetch", "-q", "--depth=1", "--no-tags", remote, ref], site, env)
    try:
        return _run_at(_git(["cat-file", "blob", "FETCH_HEAD:latest.json"], site, sealed))
    except PublishError:
        return None


def _utc(text: str) -> str:
    return _moment(text).astimezone(timezone.utc).strftime("%d %b %Y %H:%M UTC")


def _age(text: str, now: datetime | None = None) -> str:
    hours = ((now or datetime.now(timezone.utc)) - _moment(text)).total_seconds() / 3600
    if hours < 1:
        return "under an hour old"
    if hours < 48:
        return f"{hours:.0f} h old"
    return f"{hours / 24:.0f} days old"


def publish(out_dir: Path = OUT_DIR, remote: str = REMOTE, branch: str = BRANCH, *,
            push: bool = True, allow_older: bool = False, home: Path | None = None) -> str:
    """Put the last run's pages up as the site: one commit, under IDENTITY,
    replacing `branch` of `remote`, unless the site already shows a later run
    (allow_older publishes it all the same). Returns the run's time as
    latest.json gives it. With push=False everything is checked, the site's own
    run included, and nothing is pushed."""
    if branch in CODE_BRANCHES:
        raise PublishError(f"{branch} holds the code; the site is published to {BRANCH}")
    env = _environment()
    try:
        with tempfile.TemporaryDirectory(prefix="elnino-site-", ignore_cleanup_errors=True) as tmp:
            work = Path(tmp)
            site = work / "site"
            site.mkdir()
            when = lay_out(out_dir, site, home)
            expected = _site_files(site)
            empty = work / "empty.gitconfig"
            empty.write_bytes(b"")
            sealed = dict(env, GIT_CONFIG_GLOBAL=str(empty), GIT_CONFIG_NOSYSTEM="1")
            _git(["init", "-q"], site, sealed)
            _git(["symbolic-ref", "HEAD", f"refs/heads/{branch}"], site, sealed)
            for key, value in (("core.hooksPath", str(work / "no-hooks")), *_SEALED):
                _git(["config", key, value], site, sealed)
            _git(["add", "--all", "--force"], site, sealed)
            _git(["commit", "-q", "-m", f"Publish the run of {when}"], site, sealed)
            listed = sorted(_git(["ls-tree", "-r", "--name-only", "HEAD"], site, sealed).split("\n"))
            if listed != expected:
                raise PublishError(f"the commit holds {', '.join(listed)}, not the site")
            shown = _shown_run(site, env, sealed, remote, branch)
            if shown is not None and _moment(when) < _moment(shown) and not allow_older:
                raise PublishError(f"{out_dir} holds the run of {_utc(when)}, older than the run "
                                   f"of {_utc(shown)} the site shows: run track.py first, or pass "
                                   "--allow-older")
            if push:
                _git([*_WIRE, "push", "-q", "--force", remote, f"HEAD:refs/heads/{branch}"], site, env)
    except OSError as exc:
        raise PublishError(f"the site could not be laid out: {exc}") from None
    return when


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish the pages of the last run as the El Nino site on GitHub Pages.")
    parser.add_argument("--out", type=Path, default=OUT_DIR,
                        help="the pages to publish (default: output/)")
    parser.add_argument("--remote", default=REMOTE, help="the repository the site lives in")
    parser.add_argument("--branch", default=BRANCH, help="the branch GitHub Pages serves")
    parser.add_argument("--dry-run", action="store_true",
                        help="check all of it, the site's own run included; push nothing")
    parser.add_argument("--allow-older", action="store_true",
                        help="publish a run older than the one the site shows")
    args = parser.parse_args(argv)
    try:
        when = publish(args.out, args.remote, args.branch, push=not args.dry_run,
                       allow_older=args.allow_older)
    except PublishError as exc:
        print(f"Not published: {exc}", file=sys.stderr)
        return 2
    run = f"the run of {_utc(when)} ({_age(when)})"
    if args.dry_run:
        print(f"Checked {run}: the site is ready, and nothing was pushed.")
        return 0
    where = SITE if (args.remote, args.branch) == (REMOTE, BRANCH) else f"{args.branch} of {args.remote}"
    print(f"Published {run} to {where}")
    print("GitHub serves it a minute or two after the push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
