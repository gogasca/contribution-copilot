import json
from pathlib import Path

import pytest

from contrib_pilot.errors import MissingContextError
from contrib_pilot.models import AcceptanceCriterion, ChangePlan, ProposedFile
from contrib_pilot.providers import PlanRequest, ProposalRequest
from contrib_pilot.providers.assistant import AssistantProvider, _extract_json


def _request() -> PlanRequest:
    return PlanRequest(
        issue_text="Improve error handling",
        acceptance_criteria_hint=["Empty names raise ValueError"],
        sources=[],
        source_contents={"vllm/utils/import_utils.py": "def resolve_obj_by_qualname():\n    pass\n"},
        base_commit="e0e5a7fb",
        allowed_paths=["vllm/utils/import_utils.py", "tests/utils_/test_import_utils.py"],
    )


def _valid_draft() -> dict:
    return {
        "acceptance_criteria": [
            {
                "id": "ac-1",
                "text": "Empty names raise ValueError",
                "planned_tests": [
                    "tests/utils_/test_import_utils.py::TestResolveObjByQualname::test_malformed"
                ],
            }
        ],
        "implementation_files": ["vllm/utils/import_utils.py"],
        "test_files": ["tests/utils_/test_import_utils.py"],
        "assumptions": ["tests/utils_/ is the nearest test location"],
        "ci_only_checks": ["gpu-integration"],
    }


def test_extract_json_strips_markdown_fences() -> None:
    raw = "```json\n{\"a\": 1}\n```"
    assert json.loads(_extract_json(raw)) == {"a": 1}


def test_create_plan_accepts_draft_without_engine_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AssistantProvider()
    monkeypatch.setattr(provider, "_call", lambda system, payload: json.dumps(_valid_draft()))

    plan = provider.create_plan(_request())

    assert plan.base_commit == "e0e5a7fb"
    assert plan.provider == "assistant"
    assert plan.implementation_files == [Path("vllm/utils/import_utils.py")]
    assert plan.test_files == [Path("tests/utils_/test_import_utils.py")]
    assert plan.acceptance_criteria[0].id == "ac-1"
    assert plan.ci_only_checks == ["gpu-integration"]


def test_create_plan_repairs_string_criteria(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AssistantProvider()
    calls = [
        json.dumps({"title": "Improve errors", "acceptance_criteria": ["Empty names raise ValueError"]}),
        json.dumps(_valid_draft()),
    ]
    monkeypatch.setattr(provider, "_call", lambda system, payload: calls.pop(0))

    plan = provider.create_plan(_request())
    assert plan.acceptance_criteria[0].text == "Empty names raise ValueError"
    assert calls == []


def test_create_plan_raises_after_failed_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AssistantProvider()
    monkeypatch.setattr(
        provider,
        "_call",
        lambda system, payload: json.dumps({"acceptance_criteria": ["not an object"]}),
    )

    with pytest.raises(MissingContextError, match="did not match the required schema"):
        provider.create_plan(_request())


def test_create_proposal_accepts_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AssistantProvider()
    body = {
        "files": [
            {
                "path": "vllm/utils/import_utils.py",
                "content": "def resolve_obj_by_qualname(qualname):\n    pass\n",
                "is_new_file": False,
            }
        ],
        "summary": "Guard malformed qualnames.",
    }
    monkeypatch.setattr(provider, "_call", lambda system, payload: json.dumps(body))

    plan = ChangePlan(
        issue_path=Path("issue.md"),
        base_commit="e0e5a7fb",
        base_file_hashes={},
        acceptance_criteria=[AcceptanceCriterion(id="ac-1", text="x")],
        implementation_files=[Path("vllm/utils/import_utils.py")],
        test_files=[Path("tests/utils_/test_import_utils.py")],
        sources=[],
    )
    proposal = provider.create_proposal(ProposalRequest(plan=plan, source_contents={}))
    assert proposal.summary.startswith("Guard")
    assert proposal.files[0].path == Path("vllm/utils/import_utils.py")
    assert isinstance(proposal.files[0], ProposedFile)
