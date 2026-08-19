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

from contrib_pilot.conventions import ConventionConstraints, prompt_block
from contrib_pilot.errors import MissingContextError
from contrib_pilot.models import AcceptanceCriterion, ChangePlan, ProposedChange, ProposedFile
from contrib_pilot.providers import PlanRequest, ProposalRequest

_status_console = Console(stderr=True)

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_CREDENTIAL_ENV_VAR = "ANTHROPIC_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 900
# claude-sonnet-5 rejects anything above 128000. Keep this well below
# that so small new-file proposals finish in one streaming reply.
DEFAULT_MAX_OUTPUT_TOKENS = 32_768


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
        "(issue_path, base_commit, base_file_hashes, sources, provider, "
        "applicable_rules, observed_imports, lint_checks, lint_policy_summary). "
        f"{extra}\n\nJSON Schema:\n{schema}"
    )


_PLAN_SYSTEM_PROMPT = _schema_system_prompt(
    "You are drafting a bounded software-change plan.",
    DraftedChangePlan,
    "acceptance_criteria must be objects with id, text, and planned_tests "
    "(an array of file paths or pytest node ids), not plain strings. "
    "implementation_files and test_files must be repository-relative paths "
    "taken from allowed_paths. Follow the engine-authored convention constraints "
    "in the user payload: reuse observed_imports, prefer PEP 604 unions and "
    "builtin generics, and do not add third-party packages.",
)

_PROPOSAL_SYSTEM_PROMPT = _schema_system_prompt(
    "You are drafting a ProposedChange for an already-approved ChangePlan.",
    DraftedProposal,
    "For rewrite_paths: set `content` to the complete UTF-8 file and leave `edits` empty. "
    "For edit_paths: leave `content` null and set `edits` to unique old_string/new_string hunks "
    "copied from the provided source. Each old_string must occur exactly once in that file. "
    "New files always use complete `content`. Do not rewrite an edit_paths file in full. "
    "Focused tests must use the standard library only: do not import vllm, torch, or GPU stacks. "
    "Follow engine-authored convention constraints: reuse observed_imports; do not add "
    "third-party packages; prefer X | None and list[T] over Optional/List.",
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


def _is_timeout(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if "timeout" in type(current).__name__.lower():
            return True
        current = current.__cause__ or current.__context__
    return False


def _is_api_status_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        name = type(current).__name__
        if name in {"BadRequestError", "APIStatusError", "AuthenticationError", "RateLimitError"}:
            return True
        current = current.__cause__ or current.__context__
    return False


_TIMEOUT_REMEDIATION = (
    "Narrow the plan to smaller files (a new focused test file instead of "
    "rewriting a large existing module), then retry "
    "`scaffold --dry-run --provider assistant`. Anthropic long replies need "
    "streaming; retry this build if the timeout persists."
)


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
            # Streaming long replies still needs a generous read timeout; a
            # single number applies to connect/read/write in the SDK.
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

    def _create_message(self, client, create_kwargs: dict):
        """Prefer streaming so long JSON replies do not idle-timeout the HTTP read."""

        thinking = {"type": "disabled"}
        stream_fn = getattr(client.messages, "stream", None)
        if callable(stream_fn):
            try:
                with stream_fn(**create_kwargs, thinking=thinking) as stream:
                    return stream.get_final_message()
            except TypeError:
                with stream_fn(**create_kwargs) as stream:
                    return stream.get_final_message()

        try:
            return client.messages.create(**create_kwargs, thinking=thinking)
        except TypeError:
            return client.messages.create(**create_kwargs)

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
            message = self._create_message(client, create_kwargs)
        except Exception as exc:
            if _is_timeout(exc):
                raise MissingContextError(
                    "Assistant request timed out before a complete proposal arrived",
                    remediation=_TIMEOUT_REMEDIATION,
                ) from exc
            if _is_api_status_error(exc):
                raise MissingContextError(
                    f"Assistant API rejected the request: {exc}",
                    remediation=(
                        "Check the model name and max_tokens cap, then retry "
                        "`--provider assistant`."
                    ),
                ) from exc
            raise
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
        constraints = ConventionConstraints(
            applicable_rules=list(request.applicable_rules),
            observed_imports=list(request.observed_imports),
            lint_checks=list(request.lint_checks),
            lint_policy_summary=request.lint_policy_summary,
        )
        payload = {
            "issue_text": request.issue_text,
            "acceptance_criteria_hint": request.acceptance_criteria_hint,
            "source_contents": request.source_contents,
            "allowed_paths": request.allowed_paths,
            "convention_constraints": prompt_block(constraints),
            "applicable_rules": request.applicable_rules,
            "observed_imports": request.observed_imports,
            "lint_checks": request.lint_checks,
            "lint_policy_summary": request.lint_policy_summary,
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
        constraints = ConventionConstraints(
            applicable_rules=list(request.applicable_rules or request.plan.applicable_rules),
            observed_imports=list(request.observed_imports or request.plan.observed_imports),
            lint_checks=list(request.lint_checks or request.plan.lint_checks),
            lint_policy_summary=request.lint_policy_summary or request.plan.lint_policy_summary,
        )
        payload = {
            "plan": request.plan.model_dump(mode="json"),
            "source_contents": request.source_contents,
            "rewrite_paths": request.rewrite_paths,
            "edit_paths": request.edit_paths,
            "convention_constraints": prompt_block(constraints),
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
