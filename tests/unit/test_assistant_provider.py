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


def test_create_plan_includes_convention_constraints(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AssistantProvider()
    captured: dict = {}

    def _call(system, payload, **_kwargs):
        captured.update(payload)
        return json.dumps(_valid_draft())

    monkeypatch.setattr(provider, "_call", _call)
    request = _request()
    request = request.model_copy(
        update={
            "applicable_rules": ["libs.no-new-third-party"],
            "observed_imports": ["os"],
            "lint_policy_summary": "Ruff select: UP",
        }
    )
    provider.create_plan(request)
    assert "libs.no-new-third-party" in captured["convention_constraints"]
    assert "os" in captured["observed_imports"]
    provider = AssistantProvider()
    monkeypatch.setattr(provider, "_call", lambda system, payload, **_kwargs: json.dumps(_valid_draft()))

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
    monkeypatch.setattr(provider, "_call", lambda system, payload, **_kwargs: calls.pop(0))

    plan = provider.create_plan(_request())
    assert plan.acceptance_criteria[0].text == "Empty names raise ValueError"
    assert calls == []


def test_create_plan_raises_after_failed_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AssistantProvider()
    monkeypatch.setattr(
        provider,
        "_call",
        lambda system, payload, **_kwargs: json.dumps({"acceptance_criteria": ["not an object"]}),
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
    monkeypatch.setattr(provider, "_call", lambda system, payload, **_kwargs: json.dumps(body))

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


def test_create_proposal_accepts_edits(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AssistantProvider()
    body = {
        "files": [
            {
                "path": "vllm/v1/core/sched/scheduler.py",
                "edits": [{"old_string": "input_budget -= num_new_tokens + draft_slots", "new_string": "input_budget -= num_new_tokens"}],
            }
        ],
        "summary": "Split target and draft budgets.",
    }
    monkeypatch.setattr(provider, "_call", lambda system, payload, **_kwargs: json.dumps(body))
    plan = ChangePlan(
        issue_path=Path("issue.md"),
        base_commit="e0e5a7fb",
        base_file_hashes={},
        acceptance_criteria=[AcceptanceCriterion(id="ac-1", text="x")],
        implementation_files=[Path("vllm/v1/core/sched/scheduler.py")],
        test_files=[],
        sources=[],
    )
    proposal = provider.create_proposal(
        ProposalRequest(
            plan=plan,
            source_contents={},
            rewrite_paths=[],
            edit_paths=["vllm/v1/core/sched/scheduler.py"],
        )
    )
    assert proposal.files[0].edits
    assert proposal.files[0].content is None


def test_client_raises_when_anthropic_is_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    fake = types.ModuleType("anthropic")
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    with pytest.raises(MissingContextError, match="incomplete"):
        AssistantProvider()._client()


def test_invoke_disables_thinking_and_rejects_max_tokens_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    provider = AssistantProvider()
    captured: dict = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"files": []}')],
                stop_reason="max_tokens",
            )

    monkeypatch.setattr(provider, "_client", lambda: SimpleNamespace(messages=FakeMessages()))
    with pytest.raises(MissingContextError, match="truncated at max_tokens"):
        provider._invoke("sys", {"x": 1})
    assert captured["thinking"] == {"type": "disabled"}
    assert captured["max_tokens"] == provider.max_output_tokens


def test_invoke_prefers_streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    provider = AssistantProvider()
    captured: dict = {}

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_final_message(self):
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"ok": true}')],
                stop_reason="end_turn",
            )

    class FakeMessages:
        def stream(self, **kwargs):
            captured.update(kwargs)
            return FakeStream()

        def create(self, **kwargs):
            raise AssertionError("non-streaming create should not be used")

    monkeypatch.setattr(provider, "_client", lambda: SimpleNamespace(messages=FakeMessages()))
    assert provider._invoke("sys", {"x": 1}) == '{"ok": true}'
    assert captured["thinking"] == {"type": "disabled"}


def test_invoke_maps_timeout_to_missing_context(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    class APITimeoutError(Exception):
        pass

    class FakeMessages:
        def create(self, **kwargs):
            raise APITimeoutError("Request timed out or interrupted")

    provider = AssistantProvider()
    monkeypatch.setattr(provider, "_client", lambda: SimpleNamespace(messages=FakeMessages()))
    with pytest.raises(MissingContextError, match="timed out"):
        provider._invoke("sys", {"x": 1})


def test_invoke_maps_bad_request_to_missing_context(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    class BadRequestError(Exception):
        pass

    class FakeMessages:
        def create(self, **kwargs):
            raise BadRequestError("max_tokens: 256000 > 128000")

    provider = AssistantProvider()
    monkeypatch.setattr(provider, "_client", lambda: SimpleNamespace(messages=FakeMessages()))
    with pytest.raises(MissingContextError, match="rejected the request"):
        provider._invoke("sys", {"x": 1})
