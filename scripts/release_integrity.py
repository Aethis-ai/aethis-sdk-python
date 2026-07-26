#!/usr/bin/env python3
"""Emit the distribution-integrity tuple that pins a release to its source.

A version number alone proves nothing: anyone can publish ``0.11.0``. What a
release candidate needs is the mapping

    (package, version) -> exact sdist/wheel sha256 -> source commit

so a downstream verifier can download the file the registry serves, hash it,
and confirm both that it is the artefact the release built and which commit on
protected ``main`` produced it.

This script emits exactly that as JSON, and can re-check it later against a
freshly downloaded file (``--verify-file``) or against what PyPI is serving
(``--verify-registry``).

Usage::

    uv build
    uv run python scripts/release_integrity.py --dist dist --out dist/integrity.json

    # after publication, prove the registry serves the same bytes
    uv run python scripts/release_integrity.py \
        --verify-registry --expect dist/integrity.json

Non-interactive; every network call is bounded by ``--timeout``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PACKAGE = "aethis-sdk"
PYPI_JSON = "https://pypi.org/pypi/{package}/{version}/json"
CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return result.stdout.strip()


def project_version(repo: Path) -> str:
    import tomllib

    with (repo / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def source_provenance(repo: Path) -> dict[str, Any]:
    """Where the built bytes came from, and whether the tree was clean.

    ``dirty`` matters: an integrity tuple computed from a modified working tree
    pins a commit that does not contain the code that was built.

    When git cannot be read at all, ``dirty`` is ``None`` — **unknown**, which
    is not the same as clean. ``--require-clean`` must treat it as a failure:
    see :func:`provenance_problems`. (An earlier version returned ``None`` here
    and tested it for falsiness, so removing ``.git`` made the gate binding
    PyPI bytes to a protected-main commit exit 0 while recording
    ``commit: null`` — a gate that binds to nothing.)
    """
    try:
        commit = _git(repo, "rev-parse", "HEAD")
        branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        dirty = bool(_git(repo, "status", "--porcelain"))
    except Exception as exc:  # provenance unreadable — recorded, never assumed clean
        return {"commit": None, "branch": None, "dirty": None, "error": str(exc)}
    return {"commit": commit, "branch": branch, "dirty": dirty}


def provenance_problems(tuple_: dict[str, Any]) -> list[str]:
    """Why this tuple cannot be trusted to pin a source commit — empty when it can.

    Checked positively. ``dirty is not False`` catches both the modified tree
    (``True``) and the unreadable-git case (``None``); a missing commit is
    caught in its own right so the failure names what is actually wrong.
    """
    source = tuple_.get("source") or {}
    problems: list[str] = []
    if not source.get("commit"):
        problems.append(
            "no source commit recorded"
            + (f" ({source['error']})" if source.get("error") else "")
            + " — this tuple pins the distribution to nothing"
        )
    if source.get("dirty") is not False:
        state = "unknown" if source.get("dirty") is None else "dirty"
        problems.append(
            f"working tree state is {state}, not verified clean — the recorded commit "
            "may not contain the code that was built"
        )
    return problems


def source_date_epoch(repo: Path) -> str | None:
    """The commit timestamp, for a reproducible build.

    Setting ``SOURCE_DATE_EPOCH`` to this before ``uv build`` makes the **wheel**
    byte-identical across rebuilds of the same commit, which is what turns the
    "this commit produced these bytes" leg of the tuple from an unverifiable
    assertion by the build job into something a third party can re-derive.
    (The sdist is *not* yet reproducible — see ``reproducibility`` in the
    emitted tuple.)
    """
    try:
        return _git(repo, "log", "-1", "--pretty=%ct")
    except Exception:  # pragma: no cover - best effort
        return None


def build_tuple(repo: Path, dist_dir: Path, version: str | None = None) -> dict[str, Any]:
    version = version or project_version(repo)
    files: list[dict[str, Any]] = []
    for path in sorted(dist_dir.iterdir()):
        if path.suffix not in (".whl", ".gz") or version not in path.name:
            continue
        files.append(
            {
                "filename": path.name,
                "packagetype": "bdist_wheel" if path.suffix == ".whl" else "sdist",
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not files:
        raise SystemExit(f"no distributions for version {version} found in {dist_dir}")
    kinds = {entry["packagetype"] for entry in files}
    missing = {"bdist_wheel", "sdist"} - kinds
    if missing:
        raise SystemExit(f"incomplete build: missing {sorted(missing)} for {version}")
    return {
        "package": PACKAGE,
        "version": version,
        "registry": "https://pypi.org/project/aethis-sdk/",
        "registry_release_url": f"https://pypi.org/project/{PACKAGE}/{version}/",
        "source": source_provenance(repo),
        "files": files,
        "reproducibility": {
            # Be precise about which leg of the tuple a third party can check.
            "source_date_epoch": os.environ.get("SOURCE_DATE_EPOCH"),
            "expected_source_date_epoch": source_date_epoch(repo),
            "bdist_wheel": (
                "reproducible when SOURCE_DATE_EPOCH is set to the commit timestamp "
                "and the same builder/Python is used"
            ),
            "sdist": (
                "NOT reproducible — setuptools varies the archive between runs, so the "
                "sdist digest is an attestation by the emitting job, not independently "
                "re-derivable"
            ),
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def registry_files(package: str, version: str, timeout: float) -> dict[str, dict[str, Any]]:
    url = PYPI_JSON.format(package=package, version=version)
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - constant https url
        payload = json.load(response)
    return {entry["filename"]: entry for entry in payload["urls"]}


def verify_registry(expected: dict[str, Any], timeout: float) -> list[str]:
    """Compare the recorded digests against what the registry actually serves."""
    problems: list[str] = []
    try:
        served = registry_files(expected["package"], expected["version"], timeout)
    except Exception as exc:
        return [f"could not read the registry: {exc}"]
    for entry in expected["files"]:
        name = entry["filename"]
        if name not in served:
            problems.append(f"{name}: not served by the registry")
            continue
        actual = served[name]["digests"]["sha256"]
        if actual != entry["sha256"]:
            problems.append(f"{name}: registry sha256 {actual} != recorded {entry['sha256']}")
    return problems


def verify_files(expected: dict[str, Any], dist_dir: Path) -> list[str]:
    """Re-hash local files against the recorded tuple.

    This is the check a substituted artefact fails: same filename, same
    version, different bytes.
    """
    problems: list[str] = []
    for entry in expected["files"]:
        path = dist_dir / entry["filename"]
        if not path.exists():
            problems.append(f"{entry['filename']}: missing from {dist_dir}")
            continue
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            problems.append(f"{entry['filename']}: sha256 {actual} != recorded {entry['sha256']}")
    return problems


def _tree_state_note(dirty: bool | None) -> str:
    if dirty is True:
        return "  (DIRTY WORKING TREE)"
    if dirty is None:
        return "  (TREE STATE UNKNOWN)"
    return ""


def render_summary(tuple_: dict[str, Any]) -> str:
    lines = [
        f"package:        {tuple_['package']}",
        f"version:        {tuple_['version']}",
        f"source commit:  {tuple_['source'].get('commit') or '<UNREADABLE — pins nothing>'}"
        + _tree_state_note(tuple_["source"].get("dirty")),
        f"registry:       {tuple_['registry_release_url']}",
    ]
    for entry in tuple_["files"]:
        lines.append(f"{entry['packagetype']:<14} {entry['filename']}")
        lines.append(f"{'sha256':<14} {entry['sha256']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit or verify the release integrity tuple.")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--dist", type=Path, default=None, help="directory holding the built distributions")
    parser.add_argument("--out", type=Path, default=None, help="write the tuple as JSON here")
    parser.add_argument("--version", default=None, help="override the version read from pyproject.toml")
    parser.add_argument("--expect", type=Path, default=None, help="a previously emitted tuple to verify against")
    parser.add_argument("--verify-registry", action="store_true")
    parser.add_argument("--verify-files", action="store_true")
    parser.add_argument("--require-clean", action="store_true", help="fail if the working tree is dirty")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)

    if args.expect is not None:
        expected = json.loads(args.expect.read_text(encoding="utf-8"))
    else:
        dist = args.dist or (args.repo / "dist")
        expected = build_tuple(args.repo, dist, version=args.version)
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(render_summary(expected))

    if args.require_clean:
        problems = provenance_problems(expected)
        if problems:
            for problem in problems:
                print(f"UNTRUSTWORTHY PROVENANCE: {problem}", file=sys.stderr)
            return 1

    problems: list[str] = []
    if args.verify_files:
        problems += verify_files(expected, args.dist or (args.repo / "dist"))
    if args.verify_registry:
        problems += verify_registry(expected, args.timeout)

    if problems:
        for problem in problems:
            print(f"INTEGRITY MISMATCH: {problem}", file=sys.stderr)
        return 1
    if args.verify_files or args.verify_registry:
        print("integrity verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
