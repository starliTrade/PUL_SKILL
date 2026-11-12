"""The external-audit package must be complete, and must not lie about itself.

`scripts/build_audit_package.sh` is the release gate for "hand this to an audit
firm". Its first version failed both halves of that job, and neither failure was
visible without building the package and reading it:

  * it shipped SIX server files (`oracle, onchain, store, match_engine, main,
    auth`) out of the 22 the server imports. An auditor would have received
    `main.py` with no `metrics.py`, `eventlog.py`, `timebase.py`, `limits.py`,
    `privacy.py`, `signer.py`, `economy.py` — code that cannot even be read.
    The README told them to start with `api/store.py`, which was shipped, so the
    omission looked intentional.
  * its provenance block recorded the commit but not the WORKING TREE state, so
    a package built from uncommitted edits claimed to be a package of the
    commit; and it carried no integrity manifest, so nothing proved the files
    arrived unmodified.

These tests build the package for real (with `AUDIT_PACKAGE_FAST=1`, which
skips the slow `forge coverage` and `verify.sh` evidence — and marks itself
incomplete on purpose) and read what came out. They are deliberately not a
snapshot test: every assertion is a property the package must have at any
commit.
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_audit_package.sh"


@pytest.fixture(scope="module")
def package(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("audit-package")
    env = {"AUDIT_PACKAGE_FAST": "1", "PATH": "/usr/local/bin:/usr/bin:/bin"}
    result = subprocess.run(
        ["bash", str(SCRIPT), str(out)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, f"the package script failed:\n{result.stderr[-2000:]}"
    stage = out / "pulsar-audit"
    assert stage.is_dir()
    return stage


def _imported_local_modules(files: list[Path]) -> set[str]:
    """Every `api/*.py` module reachable from the given entry points, transitively."""
    names: set[str] = set()
    queue = list(files)
    seen: set[Path] = set()
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module.split(".")[0]]
            for mod in mods:
                candidate = ROOT / "api" / f"{mod}.py"
                if candidate.is_file():
                    names.add(candidate.name)
                    queue.append(candidate)
    return names


def test_every_module_the_money_path_imports_is_in_the_package(package: Path) -> None:
    """The defect that made the first package unusable, pinned forever.

    Starts at the four files the auditor is told to read first and walks their
    imports, so adding a module to the server automatically adds it to this
    assertion — the test cannot go stale in the direction that matters.
    """
    entries = [ROOT / "api" / name for name in ("main.py", "oracle.py", "onchain.py", "store.py")]
    required = _imported_local_modules(entries)
    assert len(required) >= 15, f"the import walk found only {sorted(required)}"

    shipped = {p.name for p in (package / "server").glob("*.py")}
    missing = sorted(required - shipped)
    assert not missing, (
        f"the audit package omits {missing} — an auditor receives main.py that "
        f"imports modules they do not have"
    )
    # And the package is not allowed to silently shrink below the whole API.
    assert shipped == {p.name for p in (ROOT / "api").glob("*.py")}


def test_the_server_tests_and_the_dependency_pins_ship_with_it(package: Path) -> None:
    # An auditor who cannot run the tests has to take every claim on trust.
    assert (package / "server" / "requirements.txt").is_file()
    assert (package / "server" / "mypy.ini").is_file()
    assert (package / "server" / ".coveragerc-hermetic").is_file()
    assert (package / "pytest.ini").is_file()
    tests = list((package / "tests").rglob("test_*.py"))
    assert len(tests) > 30, f"only {len(tests)} test files shipped"
    assert not list((package / "tests").rglob("__pycache__")), "build artefacts shipped"


def test_the_contract_package_can_actually_be_compiled(package: Path) -> None:
    # `MockUSDT.sol` and `BlacklistingUSDT.sol` define the adversarial token
    # behaviour; a suite without them does not compile. The deploy script is
    # part of the review surface too.
    contracts = {p.name for p in (package / "contracts").glob("*.sol")}
    for name in ("PulsarEscrow.sol", "MockUSDT.sol", "BlacklistingUSDT.sol"):
        assert name in contracts, f"{name} missing from the package"
    assert (package / "contracts" / "foundry.toml").is_file()
    assert list((package / "contracts" / "script").glob("*.sol")), "no deploy script shipped"


def test_provenance_names_the_real_commit_and_its_tree_state(package: Path) -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    text = (package / "evidence" / "PROVENANCE.md").read_text(encoding="utf-8")
    assert f"`{head}`" in text, "the package does not name the commit it was built from"

    # Not "it says something about the tree" — it must say the TRUE thing. A
    # build that always claims "clean" would pass a weaker assertion, so the
    # recorded state is compared against `git status` right here.
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    if status.strip():
        assert "Working tree: DIRTY" in text, (
            "the working tree has uncommitted changes and the package claims it "
            "was built from the commit — the two are different code"
        )
        first = status.splitlines()[0].strip().split(maxsplit=1)[1]
        assert first in text, f"the dirty listing does not name {first!r}"
    else:
        assert "Working tree: clean" in text and "DIRTY" not in text


def test_a_fast_package_admits_it_is_incomplete(package: Path) -> None:
    text = (package / "evidence" / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "INCOMPLETE" in text and "AUDIT_PACKAGE_FAST=1" in text, (
        "a package built without the coverage/verify evidence must say so, or it "
        "will be sent to an auditor as if it were the full one"
    )


def test_the_integrity_manifest_covers_every_file(package: Path) -> None:
    manifest = (package / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    listed = {Path(line.split(maxsplit=1)[1]).as_posix() for line in manifest if line.strip()}
    present = {
        p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file() and p.name != "SHA256SUMS"
    }
    assert listed == present, (
        f"manifest mismatch — unlisted: {sorted(present - listed)}, "
        f"listed but absent: {sorted(listed - present)}"
    )
    # And the hashes are real, not placeholders: spot-check the custody contract.
    line = next(ln for ln in manifest if ln.endswith("./contracts/PulsarEscrow.sol"))
    digest = line.split()[0]
    assert digest == hashlib.sha256((package / "contracts" / "PulsarEscrow.sol").read_bytes()).hexdigest()


def test_the_orientation_document_does_not_carry_stale_counts() -> None:
    """`PACKAGE-README.md` quoted four numbers, and all four went stale.

    They are now asserted-against rather than refreshed: the gate count comes
    from `verify.sh` at run time, and everything else lives in documents that a
    test already enforces (`docs/COVERAGE-REPORT.md`, `README.md`).
    """
    text = (ROOT / "docs" / "audit" / "PACKAGE-README.md").read_text(encoding="utf-8")
    for stale in ("334 tests", "80 test functions", "21 gates", "no issues in 22 files"):
        assert stale not in text, f"the audit package README still claims {stale!r}"
    assert "mypy api" not in text.replace("mypy api/", ""), (
        "the README still tells the auditor to run `mypy api`, which no longer "
        "covers the scripts that move money"
    )
    assert "docs/COVERAGE-REPORT.md" in text, (
        "the README must point at the one document that carries the measured counts"
    )


def test_the_python_that_ships_is_the_python_that_runs(package: Path) -> None:
    # A cheap consistency check that the copy is not truncated: every shipped
    # module parses, and the total line count is within 1% of the repository's.
    shipped = list((package / "server").glob("*.py"))
    for path in shipped:
        ast.parse(path.read_text(encoding="utf-8"))
    repo_lines = sum(len(p.read_text(encoding="utf-8").splitlines()) for p in (ROOT / "api").glob("*.py"))
    pkg_lines = sum(len(p.read_text(encoding="utf-8").splitlines()) for p in shipped)
    assert abs(repo_lines - pkg_lines) <= max(5, repo_lines // 100)


if __name__ == "__main__":  # pragma: no cover - convenience
    sys.exit(pytest.main([__file__, "-q"]))
