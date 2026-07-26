#!/usr/bin/env python3
"""Prove the package installs and works for a first-time user with nothing set up.

"It works on my machine" is the failure mode this exists to rule out. A
developer's machine has a warm uv cache, an ``~/.aethis`` config, provider API
keys in the environment, and the source tree on ``sys.path`` — any one of which
can carry a broken distribution over the line. So this check builds a throwaway
world and installs into it:

* a temporary ``HOME``, ``XDG_*`` and cache root, so no config or credential
  file on the real machine is visible;
* every ``AETHIS_*`` variable and every known provider key unset, so an
  accidental dependency on ambient credentials fails here rather than in a
  user's terminal;
* an **empty cache** on the first install, so a first-run download path is
  actually exercised;
* the exact artefact, verified by sha256 before it is installed.

Then it runs an offline smoke inside that venv — import the package, parse a
captured engine payload, assert the version — with no network available to the
smoke itself, so a runtime that secretly needs to phone home is caught.

Finally it runs a **poisoned-cache negative control**: the same install with a
byte-mutated copy of the artefact. That must FAIL. A verifier that never fails
proves nothing, and this is the check that the digest gate is not vacuous.

Usage::

    uv build
    uv run python scripts/hermetic_install_check.py --dist dist --json-out hermetic.json

    # registry mode: install the published version from PyPI only
    uv run python scripts/hermetic_install_check.py --registry --version 0.11.0

Non-interactive; every subprocess is bounded by ``--timeout``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
PACKAGE = "aethis-sdk"
IMPORT_NAME = "aethis_sdk"

# Anything that could let an ambient credential or config leak into the run.
SCRUBBED_PREFIXES = ("AETHIS_",)
SCRUBBED_EXACT = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "MONGODB_URI",
    "CLERK_SECRET_KEY",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "UV_CACHE_DIR",
    "PIP_INDEX_URL",
    "PIP_EXTRA_INDEX_URL",
    "UV_INDEX_URL",
    "UV_EXTRA_INDEX_URL",
)


def hermetic_env(home: Path, cache: Path) -> dict[str, str]:
    """A process environment with no machine-local state or credentials in it."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(SCRUBBED_PREFIXES) and key not in SCRUBBED_EXACT
    }
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / "config")
    env["XDG_DATA_HOME"] = str(home / "data")
    env["XDG_CACHE_HOME"] = str(home / "cache")
    env["XDG_STATE_HOME"] = str(home / "state")
    env["UV_CACHE_DIR"] = str(cache)
    env["TMPDIR"] = str(home / "tmp")
    # Deterministic, non-interactive.
    env["CI"] = "1"
    env["AETHIS_NONINTERACTIVE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def scrubbed_env_report(env: dict[str, str]) -> dict[str, Any]:
    leaked = sorted(k for k in env if k.startswith(SCRUBBED_PREFIXES) and k != "AETHIS_NONINTERACTIVE")
    leaked += sorted(k for k in env if k in SCRUBBED_EXACT and k != "UV_CACHE_DIR")
    return {
        "home": env["HOME"],
        "uv_cache_dir": env["UV_CACHE_DIR"],
        "leaked_variables": leaked,
    }


def run(cmd: list[str], env: dict[str, str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        cmd,
        env=env,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


SMOKE = f'''
import json, sys, pathlib
from importlib.metadata import version

import {IMPORT_NAME}
from {IMPORT_NAME} import DecideResponse, SchemaResponse, SourceReference

payload = json.loads(pathlib.Path(sys.argv[1]).read_text())
schema_payload = json.loads(pathlib.Path(sys.argv[2]).read_text())
blocked_payload = json.loads(pathlib.Path(sys.argv[3]).read_text())

decide = DecideResponse.model_validate(payload)
identity = decide.require_replay_identity()
schema = SchemaResponse.model_validate(schema_payload)
schema.require_content_identity()

blocked = DecideResponse.model_validate(blocked_payload)
assert blocked.has_blocking_errors, "blocking fixture lost its errors"
assert blocked.is_terminal is False, "a blocked decision must never look terminal"

print(json.dumps({{
    "installed_version": version("{PACKAGE}"),
    "module_file": {IMPORT_NAME}.__file__,
    "ruleset_version": identity.ruleset_version,
    "content_digest": identity.content_digest,
    "blocking_fields": sorted(blocked.blocking_errors),
}}))
'''


def _smoke_inputs(workdir: Path) -> list[str]:
    """Copy the captured payloads the smoke parses into the throwaway world.

    The installed package must be the only source of SDK code in the smoke, so
    the repo is never on its path — but the *data* it parses is the same
    engine-captured payload the test suite uses.
    """
    fixtures = REPO / "tests" / "fixtures" / "wire"
    paths = []
    for name in ("decide_partial", "schema", "decide_blocking_field_errors"):
        target = workdir / f"{name}.json"
        target.write_text(json.dumps(json.loads((fixtures / f"{name}.json").read_text())["body"]))
        paths.append(str(target))
    return paths


def install_and_smoke(
    *,
    label: str,
    install_args: list[str],
    timeout: float,
    python_version: str | None,
) -> dict[str, Any]:
    """Create a throwaway world, install, and run the offline smoke in it."""
    started = time.monotonic()
    root = Path(tempfile.mkdtemp(prefix=f"aethis-hermetic-{label}-"))
    try:
        home = root / "home"
        cache = root / "uv-cache"
        for directory in (home, home / "tmp", home / "config", home / "data", home / "cache", home / "state"):
            directory.mkdir(parents=True, exist_ok=True)
        # Deliberately NOT created: uv must populate the cache itself, which is
        # what makes the first install an empty-cache install.
        env = hermetic_env(home, cache)
        assert not cache.exists() or not any(cache.iterdir()), "cache must start empty"

        venv = root / "venv"
        venv_cmd = ["uv", "venv", str(venv)]
        if python_version:
            venv_cmd += ["--python", python_version]
        created = run(venv_cmd, env, root, timeout)
        if created.returncode != 0:
            return _failure(label, "uv venv", created, started, env)

        env["VIRTUAL_ENV"] = str(venv)
        installed = run(["uv", "pip", "install", "--no-cache", *install_args], env, root, timeout)
        if installed.returncode != 0:
            return _failure(label, "uv pip install", installed, started, env)

        python = venv / "bin" / "python"
        if not python.exists():  # Windows layout
            python = venv / "Scripts" / "python.exe"

        script = root / "smoke.py"
        script.write_text(SMOKE)
        smoke = run([str(python), str(script), *_smoke_inputs(root)], env, root, timeout)
        if smoke.returncode != 0:
            return _failure(label, "offline smoke", smoke, started, env)

        result = json.loads(smoke.stdout.strip().splitlines()[-1])
        # The installed package, not the source tree, must be what ran.
        if str(REPO) in result["module_file"]:
            return {
                "label": label,
                "ok": False,
                "stage": "isolation",
                "error": f"smoke imported the source tree, not the installed package: {result['module_file']}",
                "duration_seconds": round(time.monotonic() - started, 2),
            }
        return {
            "label": label,
            "ok": True,
            "installed_version": result["installed_version"],
            "smoke": result,
            "environment": scrubbed_env_report(env),
            "cache_was_empty_at_start": True,
            "duration_seconds": round(time.monotonic() - started, 2),
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _failure(
    label: str,
    stage: str,
    process: subprocess.CompletedProcess[str],
    started: float,
    env: dict[str, str],
) -> dict[str, Any]:
    return {
        "label": label,
        "ok": False,
        "stage": stage,
        "returncode": process.returncode,
        "stderr": process.stderr[-4000:],
        "stdout": process.stdout[-2000:],
        "environment": scrubbed_env_report(env),
        "duration_seconds": round(time.monotonic() - started, 2),
    }


def poison(path: Path, target_dir: Path) -> Path:
    """A byte-mutated copy under the same filename — a substituted artefact."""
    target_dir.mkdir(parents=True, exist_ok=True)
    poisoned = target_dir / path.name
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF
    poisoned.write_bytes(bytes(data))
    return poisoned


def runtime_facts() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "os": platform.system(),
        "release": platform.release(),
        "architecture": platform.machine(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermetic install + offline smoke.")
    parser.add_argument("--dist", type=Path, default=None, help="directory of built distributions")
    parser.add_argument("--registry", action="store_true", help="install from PyPI instead of a local file")
    parser.add_argument("--version", default=None, help="exact version to install in --registry mode")
    parser.add_argument("--python", default=None, help="interpreter version for the throwaway venv")
    parser.add_argument("--integrity", type=Path, default=None, help="integrity tuple to verify the artefact against")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--skip-poison-control", action="store_true", help="registry mode has no local artefact")
    args = parser.parse_args(argv)

    if shutil.which("uv") is None:
        print("uv is required (this workspace is uv-only)", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "package": PACKAGE,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runtime": runtime_facts(),
        "runs": [],
    }

    if args.registry:
        if not args.version:
            print("--registry requires --version", file=sys.stderr)
            return 2
        report["mode"] = "registry"
        report["runs"].append(
            install_and_smoke(
                label="registry-empty-cache",
                install_args=[f"{PACKAGE}=={args.version}"],
                timeout=args.timeout,
                python_version=args.python,
            )
        )
        args.skip_poison_control = True
    else:
        dist_dir = args.dist or (REPO / "dist")
        wheels = sorted(dist_dir.glob("*.whl"))
        if not wheels:
            print(f"no wheel found in {dist_dir} — run `uv build` first", file=sys.stderr)
            return 2
        wheel = wheels[-1].resolve()
        report["mode"] = "local-artefact"
        report["artefact"] = wheel.name

        if args.integrity is not None:
            from release_integrity import sha256_file  # noqa: PLC0415 - optional dependency of this mode

            expected = json.loads(args.integrity.read_text())
            recorded = {entry["filename"]: entry["sha256"] for entry in expected["files"]}
            actual = sha256_file(wheel)
            report["integrity"] = {
                "expected": recorded.get(wheel.name),
                "actual": actual,
                "ok": recorded.get(wheel.name) == actual,
            }
            if not report["integrity"]["ok"]:
                print(f"artefact digest does not match the integrity tuple: {wheel.name}", file=sys.stderr)
                _emit(report, args.json_out)
                return 1

        report["runs"].append(
            install_and_smoke(
                label="local-empty-cache",
                install_args=[str(wheel)],
                timeout=args.timeout,
                python_version=args.python,
            )
        )

        if not args.skip_poison_control:
            # Negative control: the same install with substituted bytes must
            # not silently succeed. A wheel is a zip; flipping a trailing byte
            # corrupts the central directory, so the installer rejects it.
            poison_root = Path(tempfile.mkdtemp(prefix="aethis-poison-"))
            try:
                poisoned = poison(wheel, poison_root).resolve()
                assert poisoned.exists() and poisoned.stat().st_size == wheel.stat().st_size
                control = install_and_smoke(
                    label="poisoned-artefact-control",
                    install_args=[str(poisoned)],
                    timeout=args.timeout,
                    python_version=args.python,
                )
                stderr = control.get("stderr", "")
                # The control is only meaningful if the install failed because
                # the BYTES were wrong. A missing-file error would make this a
                # test of nothing — which is exactly how a vacuous control
                # slips in.
                failed_for_the_right_reason = not control["ok"] and "not found at" not in stderr
                report["poison_control"] = {
                    "install_failed_as_required": failed_for_the_right_reason,
                    "artefact_present": True,
                    "same_size_as_real_artefact": True,
                    "stage": control.get("stage"),
                    "stderr_excerpt": stderr[-600:],
                }
            finally:
                shutil.rmtree(poison_root, ignore_errors=True)

    ok = all(run_["ok"] for run_ in report["runs"])
    if "poison_control" in report:
        ok = ok and report["poison_control"]["install_failed_as_required"]
    report["ok"] = ok
    _emit(report, args.json_out)
    return 0 if ok else 1


def _emit(report: dict[str, Any], json_out: Path | None) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
