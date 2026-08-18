from pathlib import Path

import pytest

from contrib_pilot.config import load_config
from contrib_pilot.errors import StaleStateError
from contrib_pilot.models import ChangePlan, ProposedChange, ProposedFile
from contrib_pilot.patches import apply_proposal, check_base_state, proposal_hash, render_unified_diff


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".contrib-pilot").mkdir()
    (tmp_path / ".contrib-pilot" / "config.toml").write_text(
        """
schema_version = "1"
working_directory = ".contrib-pilot/runs"
max_changed_files = 6
max_changed_lines = 250

[context]
allowed_sources = ["pkg/a.py"]

[changes]
allowed_paths = ["pkg/a.py"]
""",
        encoding="utf-8",
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def _plan(repo: Path, base_hash: str) -> ChangePlan:
    return ChangePlan(
        issue_path=Path("issue.md"),
        base_commit="deadbeef",
        base_file_hashes={"pkg/a.py": base_hash},
        acceptance_criteria=[],
        implementation_files=[Path("pkg/a.py")],
        test_files=[],
        sources=[],
    )


def _current_hash(repo: Path) -> str:
    import hashlib

    return hashlib.sha256((repo / "pkg" / "a.py").read_bytes()).hexdigest()


def test_render_unified_diff_shows_change(repo: Path) -> None:
    config = load_config(repo)
    proposal = ProposedChange(
        plan_hash="x", files=[ProposedFile(path=Path("pkg/a.py"), content="x = 2\n")], summary="bump"
    )
    diff = render_unified_diff(config, proposal)
    assert "-x = 1" in diff
    assert "+x = 2" in diff


def test_proposal_hash_is_stable() -> None:
    proposal = ProposedChange(
        plan_hash="x", files=[ProposedFile(path=Path("a.py"), content="1")], summary="s"
    )
    assert proposal_hash(proposal) == proposal_hash(proposal)


def test_check_base_state_detects_drift(repo: Path) -> None:
    config = load_config(repo)
    plan = _plan(repo, base_hash="not-the-real-hash")
    result = check_base_state(config, plan)
    assert not result.ok
    assert "pkg/a.py" in result.changed_paths


def test_apply_proposal_rejects_stale_base(repo: Path) -> None:
    config = load_config(repo)
    plan = _plan(repo, base_hash="not-the-real-hash")
    proposal = ProposedChange(
        plan_hash="x", files=[ProposedFile(path=Path("pkg/a.py"), content="x = 2\n")], summary="bump"
    )
    with pytest.raises(StaleStateError):
        apply_proposal(config, plan, proposal)


def test_apply_proposal_writes_file_and_never_overwrites_without_matching_base(repo: Path) -> None:
    config = load_config(repo)
    plan = _plan(repo, base_hash=_current_hash(repo))
    proposal = ProposedChange(
        plan_hash="x", files=[ProposedFile(path=Path("pkg/a.py"), content="x = 2\n")], summary="bump"
    )
    result = apply_proposal(config, plan, proposal)
    assert result.error is None
    assert (repo / "pkg" / "a.py").read_text() == "x = 2\n"
