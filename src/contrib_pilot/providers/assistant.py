"""Live, bounded model-backed provider.

Receives only engine-assembled ``PlanRequest``/``ProposalRequest`` objects —
no filesystem access, no tool use, no independent repository reads. Output
is schema-validated; a malformed response gets exactly one repair attempt
containing only the validation errors, never a silent accept (plan.MD
"Provider contract"). Requires the ``assistant`` optional dependency group
(``anthropic``) and an API key in the configured environment variable —
never read from a prompt, an artifact, or hardcoded here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from contrib_pilot.errors import MissingContextError
from contrib_pilot.models import AcceptanceCriterion, ChangePlan, ProposedChange, ProposedFile
from contrib_pilot.providers import PlanRequest, ProposalRequest

_status_console = Console(stderr=True)

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_CREDENTIAL_ENV_VAR = "ANTHROPIC_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_MAX_OUTPUT_TOKENS = 32_000


class DraftedChangePlan(BaseModel):
    """Fields the assistant may invent. Engine-owned fields are filled after validation."""

    schema_version: str = "1"
    acceptance_criteria: list[AcceptanceCriterion]
    implementation_files: list[Path]
    test_files: list[Path]
    assumptions: list[str] = Field(default_factory=list)
    ci_only_checks: list[str] = Field(default_factory=list)


class DraftedProposal(BaseModel):
    """Assistant-authored proposal body. ``plan_hash`` is stamped by this adapter."""

    files: list[ProposedFile]
    summary: str
    plan_hash: str = "assistant"


def _schema_system_prompt(role: str, schema_cls: type[BaseModel], extra: str) -> str:
    schema = json.dumps(schema_cls.model_json_schema(), indent=2)
    return (
        f"{role} Use only the provided sources. "
        "Output must be a single JSON object matching this JSON Schema exactly. "
        "Do not emit markdown fences, commentary, or engine-owned fields "
        "(issue_path, base_commit, base_file_hashes, sources, provider). "
        f"{extra}\n\nJSON Schema:\n{schema}"
    )


_PLAN_SYSTEM_PROMPT = _schema_system_prompt(
    "You are drafting a bounded software-change plan.",
    DraftedChangePlan,
    "acceptance_criteria must be objects with id, text, and planned_tests "
    "(an array of file paths or pytest node ids), not plain strings. "
    "implementation_files and test_files must be repository-relative paths "
    "taken from allowed_paths.",
)

_PROPOSAL_SYSTEM_PROMPT = _schema_system_prompt(
    "You are drafting a ProposedChange for an already-approved ChangePlan.",
    DraftedProposal,
    "Propose complete UTF-8 file contents only for files already listed in the plan.",
)


def _extract_json(raw: str) -> str:
    """Pull a JSON object out of model text that may include fences or prose."""

    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _format_validation_errors(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:8]:
        loc = ".".join(str(part) for part in err.get("loc", ())) or "(root)"
        parts.append(f"{loc}: {err.get('msg')}")
    return "; ".join(parts)


class AssistantProvider:
    name = "assistant"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        credential_env_var: str = DEFAULT_CREDENTIAL_ENV_VAR,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        self.model = model
        self.credential_env_var = credential_env_var
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    def _client(self):
        api_key = os.environ.get(self.credential_env_var)
        if not api_key:
            raise MissingContextError(
                f"{self.credential_env_var} is not set",
                remediation=(
                    "Export the credential, or run with `--provider fixture` "
                    "for the offline demo."
                ),
            )
        try:
            import anthropic
        except ImportError as exc:
            raise MissingContextError(
                "The `anthropic` package is not installed",
                remediation="Install the `assistant` extra: `uv sync --extra assistant`.",
            ) from exc
        if not hasattr(anthropic, "Anthropic"):
            raise MissingContextError(
                "The `anthropic` package is installed but incomplete (no Anthropic client)",
                remediation=(
                    "Reinstall the `assistant` extra: `uv sync --extra assistant`. "
                    "If OneDrive reports Access denied, run `attrib -R .venv /S /D` and retry, "
                    "or use `--provider fixture` for the offline demo."
                ),
            )
        try:
            client = anthropic.Anthropic(api_key=api_key, timeout=self.timeout_seconds)
        except AttributeError as exc:
            raise MissingContextError(
                "The `anthropic` package is installed but incomplete (no Anthropic client)",
                remediation=(
                    "Reinstall the `assistant` extra: `uv sync --extra assistant`. "
                    "If OneDrive reports Access denied, run `attrib -R .venv /S /D` and retry, "
                    "or use `--provider fixture` for the offline demo."
                ),
            ) from exc
        return client

    def _invoke(self, system: str, user_payload: dict) -> str:
        client = self._client()
        create_kwargs: dict = {
            "model": self.model,
            "max_tokens": self.max_output_tokens,
            "system": system,
            "messages": [{"role": "user", "content": json.dumps(user_payload)}],
        }
        try:
            # Sonnet 5 enables adaptive thinking by default; thinking tokens
            # count against max_tokens and truncate the JSON payload.
            message = client.messages.create(
                **create_kwargs,
                thinking={"type": "disabled"},
            )
        except TypeError:
            message = client.messages.create(**create_kwargs)
        except Exception as exc:
            if "thinking" not in str(exc).lower():
                raise
            message = client.messages.create(**create_kwargs)
        text = "".join(block.text for block in message.content if block.type == "text")
        if getattr(message, "stop_reason", None) == "max_tokens":
            raise MissingContextError(
                "Assistant output was truncated at max_tokens before the JSON completed",
                remediation=(
                    "Retry with `--provider assistant`, or use `--provider fixture` "
                    "for the offline demo."
                ),
            )
        return text

    def _call(self, system: str, user_payload: dict, *, status: str = "Waiting on assistant") -> str:
        if not _status_console.is_terminal:
            return self._invoke(system, user_payload)
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.description}"),
            TimeElapsedColumn(),
            console=_status_console,
            transient=True,
        ) as progress:
            progress.add_task(status, total=None)
            return self._invoke(system, user_payload)

    def _call_with_repair(self, system: str, user_payload: dict, schema_cls: type[BaseModel], *, activity: str):
        payload = {
            **user_payload,
            "output_schema": schema_cls.model_json_schema(),
        }
        raw = self._call(system, payload, status=f"Calling {activity}…")
        try:
            return schema_cls.model_validate_json(_extract_json(raw))
        except (ValidationError, json.JSONDecodeError) as first_error:
            errors = (
                first_error.errors()
                if isinstance(first_error, ValidationError)
                else [{"msg": str(first_error)}]
            )
            repair_payload = {
                "previous_output": raw,
                "output_schema": schema_cls.model_json_schema(),
                "validation_errors": errors,
                "instruction": "Return corrected JSON only, matching the schema exactly.",
            }
            repaired_raw = self._call(system, repair_payload, status=f"Repairing {activity} JSON…")
            try:
                return schema_cls.model_validate_json(_extract_json(repaired_raw))
            except (ValidationError, json.JSONDecodeError) as second_error:
                detail = (
                    _format_validation_errors(second_error)
                    if isinstance(second_error, ValidationError)
                    else str(second_error)
                )
                raise MissingContextError(
                    "Assistant output did not match the required schema after one repair attempt. "
                    f"{detail}",
                    remediation=(
                        "Retry with `--provider assistant`, or write a schema-valid "
                        "plan.json / proposal.json under .contrib-pilot/runs/current/."
                    ),
                ) from second_error

    def create_plan(self, request: PlanRequest) -> ChangePlan:
        payload = {
            "issue_text": request.issue_text,
            "acceptance_criteria_hint": request.acceptance_criteria_hint,
            "source_contents": request.source_contents,
            "allowed_paths": request.allowed_paths,
        }
        draft = self._call_with_repair(
            _PLAN_SYSTEM_PROMPT, payload, DraftedChangePlan, activity="plan"
        )
        return ChangePlan(
            schema_version=draft.schema_version,
            issue_path=Path("issue.md"),
            base_commit=request.base_commit,
            base_file_hashes={},
            acceptance_criteria=draft.acceptance_criteria,
            implementation_files=draft.implementation_files,
            test_files=draft.test_files,
            sources=list(request.sources),
            assumptions=draft.assumptions,
            ci_only_checks=draft.ci_only_checks,
            provider=self.name,
        )

    def create_proposal(self, request: ProposalRequest) -> ProposedChange:
        payload = {
            "plan": request.plan.model_dump(mode="json"),
            "source_contents": request.source_contents,
        }
        draft = self._call_with_repair(
            _PROPOSAL_SYSTEM_PROMPT, payload, DraftedProposal, activity="scaffold proposal"
        )
        return ProposedChange(
            schema_version="1",
            plan_hash=draft.plan_hash,
            files=draft.files,
            summary=draft.summary,
        )
