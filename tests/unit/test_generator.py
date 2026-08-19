from pathlib import Path

from contrib_pilot.config import load_config
from contrib_pilot.generator import MAX_COMPLETE_REWRITE_BYTES, build_proposal
from contrib_pilot.models import ChangePlan, FileEdit, ProposedChange, ProposedFile
from contrib_pilot.providers import ProposalRequest


class _FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.last_request: ProposalRequest | None = None

    def create_plan(self, request):  # pragma: no cover - unused
        raise NotImplementedError

    def create_proposal(self, request: ProposalRequest) -> ProposedChange:
        self.last_request = request
        files = [
            ProposedFile(
                path=Path(path),
                edits=[FileEdit(old_string="token_budget", new_string="input_budget")],
            )
            for path in request.edit_paths
        ]
        files.extend(
            ProposedFile(path=Path(path), content="def test_ok():\n    assert True\n", is_new_file=True)
            for path in request.rewrite_paths
        )
        return ProposedChange(plan_hash="fake", files=files, summary="mixed")


def test_large_existing_files_are_routed_to_edits(tmp_path: Path) -> None:
    large = "x" * (MAX_COMPLETE_REWRITE_BYTES + 10)
    (tmp_path / ".contrib-pilot").mkdir()
    (tmp_path / ".contrib-pilot" / "config.toml").write_text(
        """
schema_version = "1"
working_directory = ".contrib-pilot/runs"
max_changed_files = 6
max_changed_lines = 250

[context]
allowed_sources = ["pkg/big.py"]

[changes]
allowed_paths = ["pkg/big.py", "tests/test_big.py"]
""",
        encoding="utf-8",
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "big.py").write_text(large + "token_budget\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    config = load_config(tmp_path)
    plan = ChangePlan(
        issue_path=Path("issue.md"),
        base_commit="deadbeef",
        base_file_hashes={},
        acceptance_criteria=[],
        implementation_files=[Path("pkg/big.py")],
        test_files=[Path("tests/test_big.py")],
        sources=[],
    )
    # Discoverable source so generator can size the file.
    from contrib_pilot.models import SourceEvidence

    plan = plan.model_copy(
        update={
            "sources": [
                SourceEvidence(path=Path("pkg/big.py"), sha256="abc", purpose="impl"),
            ]
        }
    )
    provider = _FakeProvider()
    proposal = build_proposal(config=config, plan=plan, provider=provider)

    assert provider.last_request is not None
    assert provider.last_request.edit_paths == ["pkg/big.py"]
    assert provider.last_request.rewrite_paths == ["tests/test_big.py"]
    assert proposal.files[0].edits
    assert proposal.files[1].content is not None
