"""The release-evidence tooling, unit-tested offline.

``scripts/release_integrity.py`` and ``scripts/hermetic_install_check.py``
produce the evidence P10 pins a candidate on. Evidence tooling that has never
been shown to *fail* is decoration, so the tests that matter most here are the
negative ones: a substituted artefact must be rejected, a registry serving
different bytes must be rejected, and the environment scrubber must actually
scrub.

The full hermetic install (which builds a venv and downloads) runs from CI and
by hand — see the ``hermetic`` job in ``.github/workflows/ci.yml``. These tests
cover its logic without paying for a network round-trip on every PR.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import hermetic_install_check as hermetic  # noqa: E402
import release_integrity as integrity  # noqa: E402


@pytest.fixture
def fake_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "aethis_sdk-9.9.9-py3-none-any.whl").write_bytes(b"wheel-bytes")
    (dist / "aethis_sdk-9.9.9.tar.gz").write_bytes(b"sdist-bytes")
    return dist


class TestIntegrityTuple:
    def test_records_both_distributions_with_digests(self, fake_dist: Path) -> None:
        tuple_ = integrity.build_tuple(Path.cwd(), fake_dist, version="9.9.9")
        assert tuple_["package"] == "aethis-sdk"
        assert tuple_["version"] == "9.9.9"
        kinds = {entry["packagetype"] for entry in tuple_["files"]}
        assert kinds == {"sdist", "bdist_wheel"}
        for entry in tuple_["files"]:
            assert len(entry["sha256"]) == 64

    def test_maps_the_release_to_a_source_commit(self, fake_dist: Path) -> None:
        tuple_ = integrity.build_tuple(Path(__file__).resolve().parent.parent, fake_dist, version="9.9.9")
        assert tuple_["source"]["commit"], "the tuple must pin the source commit P10 verifies against"
        assert len(tuple_["source"]["commit"]) == 40
        assert tuple_["source"]["branch"]
        assert isinstance(tuple_["source"]["dirty"], bool)

    def test_an_incomplete_build_is_rejected(self, tmp_path: Path) -> None:
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "aethis_sdk-9.9.9-py3-none-any.whl").write_bytes(b"wheel-only")
        with pytest.raises(SystemExit, match="incomplete build"):
            integrity.build_tuple(Path.cwd(), dist, version="9.9.9")

    def test_no_matching_version_is_rejected(self, fake_dist: Path) -> None:
        with pytest.raises(SystemExit, match="no distributions"):
            integrity.build_tuple(Path.cwd(), fake_dist, version="1.2.3")


class TestSubstitutedArtefactsAreCaught:
    """The negative control: this is what makes the digest gate non-vacuous."""

    def test_a_mutated_file_fails_verification(self, fake_dist: Path) -> None:
        tuple_ = integrity.build_tuple(Path.cwd(), fake_dist, version="9.9.9")
        assert integrity.verify_files(tuple_, fake_dist) == []

        wheel = fake_dist / "aethis_sdk-9.9.9-py3-none-any.whl"
        wheel.write_bytes(b"wheel-bytez")  # same name, same version, other bytes
        problems = integrity.verify_files(tuple_, fake_dist)
        assert len(problems) == 1
        assert "sha256" in problems[0]

    def test_a_missing_file_fails_verification(self, fake_dist: Path) -> None:
        tuple_ = integrity.build_tuple(Path.cwd(), fake_dist, version="9.9.9")
        (fake_dist / "aethis_sdk-9.9.9.tar.gz").unlink()
        problems = integrity.verify_files(tuple_, fake_dist)
        assert any("missing" in problem for problem in problems)

    def test_a_registry_serving_other_bytes_fails(self, fake_dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        tuple_ = integrity.build_tuple(Path.cwd(), fake_dist, version="9.9.9")
        served = {
            entry["filename"]: {"digests": {"sha256": "0" * 64}}
            for entry in tuple_["files"]
        }
        monkeypatch.setattr(integrity, "registry_files", lambda *a, **k: served)
        problems = integrity.verify_registry(tuple_, timeout=1.0)
        assert len(problems) == 2
        assert all("registry sha256" in problem for problem in problems)

    def test_a_matching_registry_passes(self, fake_dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        tuple_ = integrity.build_tuple(Path.cwd(), fake_dist, version="9.9.9")
        served = {
            entry["filename"]: {"digests": {"sha256": entry["sha256"]}}
            for entry in tuple_["files"]
        }
        monkeypatch.setattr(integrity, "registry_files", lambda *a, **k: served)
        assert integrity.verify_registry(tuple_, timeout=1.0) == []

    def test_the_real_project_version_is_what_gets_pinned(self) -> None:
        repo = Path(__file__).resolve().parent.parent
        assert integrity.project_version(repo).count(".") == 2

    def test_a_release_absent_from_the_registry_fails(self, fake_dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        tuple_ = integrity.build_tuple(Path.cwd(), fake_dist, version="9.9.9")
        monkeypatch.setattr(integrity, "registry_files", lambda *a, **k: {})
        problems = integrity.verify_registry(tuple_, timeout=1.0)
        assert all("not served" in problem for problem in problems)


class TestIntegrityCli:
    def test_emits_json_and_verifies_it(self, fake_dist: Path, tmp_path: Path) -> None:
        out = tmp_path / "integrity.json"
        assert integrity.main(["--dist", str(fake_dist), "--version", "9.9.9", "--out", str(out)]) == 0
        emitted = json.loads(out.read_text())
        assert emitted["version"] == "9.9.9"
        assert {entry["packagetype"] for entry in emitted["files"]} == {"sdist", "bdist_wheel"}
        assert integrity.main(["--expect", str(out), "--dist", str(fake_dist), "--verify-files"]) == 0

    def test_verification_exits_non_zero_on_a_mismatch(self, fake_dist: Path, tmp_path: Path) -> None:
        out = tmp_path / "integrity.json"
        integrity.main(["--dist", str(fake_dist), "--version", "9.9.9", "--out", str(out)])
        (fake_dist / "aethis_sdk-9.9.9.tar.gz").write_bytes(b"different")
        assert integrity.main(["--expect", str(out), "--dist", str(fake_dist), "--verify-files"]) == 1


class TestHermeticEnvironment:
    def test_home_and_caches_are_redirected(self, tmp_path: Path) -> None:
        env = hermetic.hermetic_env(tmp_path / "home", tmp_path / "cache")
        assert env["HOME"] == str(tmp_path / "home")
        assert env["UV_CACHE_DIR"] == str(tmp_path / "cache")
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
            assert env[key].startswith(str(tmp_path / "home"))

    def test_aethis_and_provider_credentials_are_scrubbed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for leak in ("AETHIS_API_KEY", "AETHIS_BASE_URL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MONGODB_URI"):
            monkeypatch.setenv(leak, "leaked")
        monkeypatch.setenv("PYTHONPATH", "/somewhere/with/a/source/tree")
        monkeypatch.setenv("PIP_INDEX_URL", "https://internal.example/simple")

        env = hermetic.hermetic_env(tmp_path / "home", tmp_path / "cache")
        for leak in ("AETHIS_API_KEY", "AETHIS_BASE_URL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MONGODB_URI"):
            assert leak not in env
        assert "PYTHONPATH" not in env
        assert "PIP_INDEX_URL" not in env, "an alternate index would defeat registry-only installation"
        assert hermetic.scrubbed_env_report(env)["leaked_variables"] == []

    def test_the_run_is_marked_non_interactive(self, tmp_path: Path) -> None:
        env = hermetic.hermetic_env(tmp_path / "home", tmp_path / "cache")
        assert env["CI"] == "1"
        assert env["AETHIS_NONINTERACTIVE"] == "1"


class TestPoisonedArtefact:
    def test_poison_keeps_the_name_and_size_but_changes_the_bytes(self, tmp_path: Path) -> None:
        real = tmp_path / "aethis_sdk-9.9.9-py3-none-any.whl"
        real.write_bytes(b"authentic-artefact-bytes")
        poisoned = hermetic.poison(real, tmp_path / "poison")
        assert poisoned.name == real.name
        assert poisoned.stat().st_size == real.stat().st_size
        assert poisoned.read_bytes() != real.read_bytes()
        assert integrity.sha256_file(poisoned) != integrity.sha256_file(real)


class TestRuntimeFacts:
    def test_records_the_matrix_dimensions(self) -> None:
        facts = hermetic.runtime_facts()
        for key in ("python", "implementation", "os", "architecture"):
            assert facts[key]


class TestScriptsAreNonInteractive:
    @pytest.mark.parametrize("script", ["release_integrity.py", "hermetic_install_check.py"])
    def test_help_exits_cleanly_with_no_stdin(self, script: str) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / script), "--help"],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )
        assert result.returncode == 0
        assert "usage" in result.stdout.lower()
