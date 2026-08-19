from pathlib import Path

import pytest

from contrib_pilot.config import load_config
from contrib_pilot.conventions import (
    NO_NEW_THIRD_PARTY,
    assert_no_new_third_party,
    classify_import,
    constraints_from,
    evaluate,
    inventory_imports,
    lint_policy_summary,
)
from contrib_pilot.errors import BoundaryViolationError, InvalidInputError
from contrib_pilot.generator import build_proposal
from contrib_pilot.models import ChangePlan, ProposedChange, ProposedFile, SourceEvidence
from contrib_pilot.planner import build_plan
from contrib_pilot.providers import PlanRequest, ProposalRequest


def test_classify_import() -> None:
    assert classify_import("os", ()) == "stdlib"
    assert classify_import("vllm", ("vllm",)) == "first_party"
    assert classify_import("requests", ("vllm",)) == "third_party"


def test_inventory_skips_tests_and_relative_imports() -> None:
    contents = {
        "vllm/sched.py": "import os\nfrom vllm.config import X\nimport requests\n",
        "tests/test_sched.py": "import pytest\n",
        "vllm/local.py": "from .foo import bar\n",
    }
    observed = inventory_imports(contents, ("vllm",))
    assert "os" in observed
    assert "vllm" in observed
    assert "requests" in observed
    assert "pytest" not in observed
    assert "foo" not in observed


def test_lint_policy_summary() -> None:
    text = """
[tool.ruff.lint]
select = ["E", "F", "UP"]
"""
    assert lint_policy_summary(text) == "Ruff select: E,F,UP"
    assert lint_policy_summary(None) == ""


def test_unknown_convention_rule_fails_config_load(tmp_path: Path) -> None:
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
[conventions]
rules = ["not.a.rule"]
""",
        encoding="utf-8",
    )
    with pytest.raises(InvalidInputError, match="Unknown convention rule"):
        load_config(tmp_path)


def test_evaluate_pep604_and_third_party() -> None:
    neighbor = {"vllm/a.py": "def f(x: int | None) -> int | None:\n    return x\n"}
    changed = {
        "vllm/a.py": (
            "from typing import Optional\n"
            "import requests\n"
            "def f(x: Optional[int]) -> Optional[int]:\n"
            "    return x\n"
        )
    }
    findings = evaluate(
        applicable_rules=["typing.pep604-union", NO_NEW_THIRD_PARTY],
        observed_imports=["typing"],
        first_party_prefixes=("vllm",),
        changed_contents=changed,
        neighbor_contents=neighbor,
        implementation_files=[Path("vllm/a.py")],
    )
    ids = {finding.rule_id for finding in findings}
    assert "typing.pep604-union" in ids
    assert NO_NEW_THIRD_PARTY in ids


def test_scaffold_rejects_new_third_party(tmp_path: Path) -> None:
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
[conventions]
rules = ["libs.no-new-third-party"]
first_party_prefixes = ["pkg"]
""",
        encoding="utf-8",
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("import os\n", encoding="utf-8")
    config = load_config(tmp_path)

    class Provider:
        name = "fake"

        def create_plan(self, request):
            raise NotImplementedError

        def create_proposal(self, request: ProposalRequest) -> ProposedChange:
            return ProposedChange(
                plan_hash="fake",
                files=[
                    ProposedFile(
                        path=Path("pkg/a.py"),
                        content="import os\nimport requests\n",
                    )
                ],
                summary="adds requests",
            )

    plan = ChangePlan(
        issue_path=Path("issue.md"),
        base_commit="abc",
        base_file_hashes={},
        acceptance_criteria=[],
        implementation_files=[Path("pkg/a.py")],
        test_files=[],
        sources=[SourceEvidence(path=Path("pkg/a.py"), sha256="x", purpose="impl")],
        applicable_rules=[NO_NEW_THIRD_PARTY],
        observed_imports=["os"],
    )
    with pytest.raises(BoundaryViolationError, match="requests"):
        build_proposal(config=config, plan=plan, provider=Provider())


def test_planner_overwrites_provider_convention_fields(tmp_path: Path) -> None:
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
[conventions]
rules = ["libs.no-new-third-party"]
first_party_prefixes = ["pkg"]
""",
        encoding="utf-8",
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("import os\nimport json\n", encoding="utf-8")
    (tmp_path / "issue.md").write_text("Fix it\n\n1. Does the thing\n", encoding="utf-8")
    config = load_config(tmp_path)

    class Provider:
        name = "fake"

        def create_plan(self, request: PlanRequest) -> ChangePlan:
            return ChangePlan(
                issue_path=Path("ignored.md"),
                base_commit="wrong",
                base_file_hashes={},
                acceptance_criteria=[],
                implementation_files=[Path("pkg/a.py")],
                test_files=[],
                sources=[],
                applicable_rules=["typing.any-on-new-api"],
                observed_imports=["requests"],
            )

        def create_proposal(self, request):
            raise NotImplementedError

    plan = build_plan(
        config=config,
        issue_path=tmp_path / "issue.md",
        base_commit="deadbeef",
        provider=Provider(),
        source_purposes={"pkg/a.py": "impl"},
    )
    assert plan.applicable_rules == [NO_NEW_THIRD_PARTY]
    assert plan.observed_imports == ["json", "os"]
    assert plan.base_commit == "deadbeef"
    assert "requests" not in plan.observed_imports


def test_assert_no_new_third_party_allows_observed() -> None:
    assert_no_new_third_party(
        implementation_files=[Path("pkg/a.py")],
        proposed_texts={"pkg/a.py": "import os\nimport requests\n"},
        observed_imports=["os", "requests"],
        first_party_prefixes=("pkg",),
    )


def test_constraints_from_reads_ruff_select() -> None:
    constraints = constraints_from(
        source_contents={
            "pkg/a.py": "import os\n",
            "pyproject.toml": "[tool.ruff.lint]\nselect = [\"UP\", \"I\"]\n",
        },
        convention_rules=(NO_NEW_THIRD_PARTY,),
        first_party_prefixes=("pkg",),
        checks=(),
    )
    assert constraints.lint_policy_summary == "Ruff select: UP,I"
    assert constraints.observed_imports == ["os"]
    assert constraints.applicable_rules == [NO_NEW_THIRD_PARTY]
