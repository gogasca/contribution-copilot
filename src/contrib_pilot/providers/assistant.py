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

from pydantic import ValidationError

from contrib_pilot.errors import MissingContextError
from contrib_pilot.models import ChangePlan, ProposedChange
from contrib_pilot.providers import PlanRequest, ProposalRequest

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_CREDENTIAL_ENV_VAR = "ANTHROPIC_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_MAX_OUTPUT_TOKENS = 8_000

_PLAN_SYSTEM_PROMPT = (
    "You are drafting a ChangePlan for one bounded software change. "
    "Use only the provided sources. Output must be a single JSON object "
    "matching the ChangePlan schema — no prose, no markdown fences."
)

_PROPOSAL_SYSTEM_PROMPT = (
    "You are drafting a ProposedChange for an already-approved ChangePlan. "
    "Propose complete file contents only for files already listed in the "
    "plan. Output must be a single JSON object matching the ProposedChange "
    "schema — no prose, no markdown fences."
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
        return anthropic.Anthropic(api_key=api_key, timeout=self.timeout_seconds)

    def _call(self, system: str, user_payload: dict) -> str:
        client = self._client()
        message = client.messages.create(
            model=self.model,
            max_tokens=self.max_output_tokens,
            system=system,
            messages=[{"role": "user", "content": json.dumps(user_payload)}],
        )
        return "".join(block.text for block in message.content if block.type == "text")

    def _call_with_repair(self, system: str, user_payload: dict, schema_cls):
        raw = self._call(system, user_payload)
        try:
            return schema_cls.model_validate_json(raw)
        except ValidationError as first_error:
            repair_payload = {
                "previous_output": raw,
                "validation_errors": first_error.errors(),
                "instruction": "Return corrected JSON only, matching the schema exactly.",
            }
            repaired_raw = self._call(system, repair_payload)
            return schema_cls.model_validate_json(repaired_raw)

    def create_plan(self, request: PlanRequest) -> ChangePlan:
        payload = {
            "issue_text": request.issue_text,
            "acceptance_criteria_hint": request.acceptance_criteria_hint,
            "source_contents": request.source_contents,
            "base_commit": request.base_commit,
            "allowed_paths": request.allowed_paths,
        }
        return self._call_with_repair(_PLAN_SYSTEM_PROMPT, payload, ChangePlan)

    def create_proposal(self, request: ProposalRequest) -> ProposedChange:
        payload = {
            "plan": request.plan.model_dump(mode="json"),
            "source_contents": request.source_contents,
        }
        return self._call_with_repair(_PROPOSAL_SYSTEM_PROMPT, payload, ProposedChange)
