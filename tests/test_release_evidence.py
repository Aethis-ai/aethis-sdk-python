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


@pytest.fixture
def real_wheel(tmp_path: Path) -> Path:
    """A structurally genuine wheel — a zip with a compressible member."""
    import zipfile

    wheel = tmp_path / "aethis_sdk-9.9.9-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("aethis_sdk/__init__.py", "VERSION = '9.9.9'\n" + "# padding\n" * 400)
        archive.writestr("aethis_sdk-9.9.9.dist-info/METADATA", "Name: aethis-sdk\nVersion: 9.9.9\n")
    return wheel


class TestSubstitutedArtefact:
    """The realistic attack: a *working* wheel with someone else's code in it.

    An attacker ships something that installs. So the installer can never be
    the control for this — only the digest can.
    """

    def test_substitution_keeps_the_filename_and_stays_installable(self, real_wheel: Path, tmp_path: Path) -> None:
        import zipfile

        substituted = hermetic.substitute_artefact(real_wheel, tmp_path / "sub")
        assert substituted.name == real_wheel.name
        assert substituted.read_bytes() != real_wheel.read_bytes()
        # Still a valid archive — that is the whole point.
        with zipfile.ZipFile(substituted) as archive:
            assert archive.testzip() is None
            assert b"substituted build" in archive.read("aethis_sdk/__init__.py")

    def test_the_digest_gate_rejects_it(self, real_wheel: Path, tmp_path: Path) -> None:
        substituted = hermetic.substitute_artefact(real_wheel, tmp_path / "sub")
        assert integrity.sha256_file(substituted) != integrity.sha256_file(real_wheel)


class TestCorruptedArtefact:
    """The installer control — and why the first version of it was vacuous.

    Flipping the final byte lands in the end-of-central-directory comment
    field. Strict readers reject it; lenient ones scan backwards, find the
    signature, and install happily — which is why the original control passed
    locally and silently did nothing on all six CI cells.
    """

    def test_corruption_targets_the_compressed_stream_not_the_trailer(
        self, real_wheel: Path, tmp_path: Path
    ) -> None:
        import zipfile

        corrupted = hermetic.corrupt_artefact(real_wheel, tmp_path / "bad")
        assert corrupted.stat().st_size == real_wheel.stat().st_size
        # Structurally still a zip — the directory parses...
        with zipfile.ZipFile(corrupted) as archive:
            names = archive.namelist()
            assert "aethis_sdk/__init__.py" in names
            # ...but a member no longer matches its recorded CRC.
            assert archive.testzip() is not None

    def test_the_trailing_byte_flip_is_not_what_we_do_any_more(
        self, real_wheel: Path, tmp_path: Path
    ) -> None:
        """Regression guard for the vacuous control."""
        corrupted = hermetic.corrupt_artefact(real_wheel, tmp_path / "bad")
        original = real_wheel.read_bytes()
        mutated = corrupted.read_bytes()
        assert mutated[-4:] == original[-4:], "corruption must not live in the EOCD trailer"
        differing = [i for i, (a, b) in enumerate(zip(original, mutated)) if a != b]
        assert differing, "nothing was corrupted"
        assert max(differing) < len(original) - 64, "corruption must sit inside the compressed data"

    def test_the_evidence_pattern_matches_real_installer_output_and_not_noise(self) -> None:
        for real in (
            "Failed to extract archive: invalid Zip archive",
            "I/O operation failed during extraction: corrupt deflate stream",
            "error: Bad CRC-32 for file",
            "not a valid wheel",
        ):
            assert hermetic._CORRUPTION_EVIDENCE.search(real), real
        # A control asserted only negatively would accept all of these.
        for noise in (
            "error: Operation timed out after 600s",
            "error: No space left on device",
            "error: Failed to resolve dependencies for aethis-sdk",
            "error: Distribution not found at: file:///tmp/x.whl",
        ):
            assert not hermetic._CORRUPTION_EVIDENCE.search(noise), noise


class TestReproducibilityIsRecordedHonestly:
    """The tuple must not imply more verifiability than it has.

    Three builds of the same clean tree produced three different digest pairs
    before ``SOURCE_DATE_EPOCH`` was set. With it, the *wheel* is byte-stable
    and the source leg is re-derivable; the *sdist* still is not. Both facts
    are recorded rather than glossed, because P10 reads this tuple.
    """

    def test_the_tuple_states_what_is_and_is_not_reproducible(self, fake_dist: Path) -> None:
        tuple_ = integrity.build_tuple(Path(__file__).resolve().parent.parent, fake_dist, version="9.9.9")
        repro = tuple_["reproducibility"]
        assert "reproducible" in repro["bdist_wheel"]
        assert repro["sdist"].startswith("NOT reproducible")
        assert "attestation" in repro["sdist"], "the sdist limitation must be stated, not implied"

    def test_the_expected_epoch_comes_from_the_commit(self) -> None:
        repo = Path(__file__).resolve().parent.parent
        epoch = integrity.source_date_epoch(repo)
        assert epoch is not None and epoch.isdigit()


class TestProvenanceGate:
    """`--require-clean` must fail when provenance is *unknown*, not just dirty.

    The first version returned `dirty: None` when git was unreadable and tested
    it for falsiness, so removing `.git` made the gate exit 0 while recording
    `commit: null` — a gate binding published bytes to nothing. Same vacuous
    shape as the poisoned-artefact control; found once, so swept here too.
    """

    def test_a_clean_tree_has_no_problems(self) -> None:
        tuple_ = {"source": {"commit": "a" * 40, "branch": "main", "dirty": False}}
        assert integrity.provenance_problems(tuple_) == []

    def test_a_dirty_tree_is_a_problem(self) -> None:
        tuple_ = {"source": {"commit": "a" * 40, "branch": "main", "dirty": True}}
        problems = integrity.provenance_problems(tuple_)
        assert any("dirty" in problem for problem in problems)

    def test_unreadable_git_is_a_problem_not_a_pass(self) -> None:
        tuple_ = {"source": {"commit": None, "branch": None, "dirty": None, "error": "not a repository"}}
        problems = integrity.provenance_problems(tuple_)
        assert len(problems) == 2
        assert any("pins the distribution to nothing" in problem for problem in problems)
        assert any("unknown" in problem for problem in problems)

    def test_a_missing_source_block_is_a_problem(self) -> None:
        assert integrity.provenance_problems({}) != []

    def test_require_clean_exits_non_zero_when_git_is_unreadable(
        self, fake_dist: Path, tmp_path: Path
    ) -> None:
        """End-to-end through the CLI, on a directory that is not a git repo."""
        not_a_repo = tmp_path / "not-a-repo"
        not_a_repo.mkdir()
        (not_a_repo / "pyproject.toml").write_text('[project]\nname = "aethis-sdk"\nversion = "9.9.9"\n')
        code = integrity.main(
            ["--repo", str(not_a_repo), "--dist", str(fake_dist), "--version", "9.9.9", "--require-clean"]
        )
        assert code == 1

    def test_require_clean_passes_on_this_repo_when_clean(self, fake_dist: Path) -> None:
        repo = Path(__file__).resolve().parent.parent
        tuple_ = integrity.build_tuple(repo, fake_dist, version="9.9.9")
        problems = integrity.provenance_problems(tuple_)
        # Either clean (no problems) or dirty during development — but never
        # "unknown", which is what this gate exists to catch.
        assert all("unknown" not in problem for problem in problems)


class TestRuntimeFacts:
    def test_records_the_matrix_dimensions(self) -> None:
        facts = hermetic.runtime_facts()
        for key in ("driver_python", "implementation", "os", "architecture"):
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
