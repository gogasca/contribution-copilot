"""Git hook install / status / uninstall.

Never edits ``.git/hooks`` directly (unversioned, local to one clone).
Configures a dedicated ``core.hooksPath`` pointing at the versioned
``.contrib-pilot/hooks/`` directory, and refuses to replace an existing
custom hooks path silently (plan.MD "Git Hooks: Early Feedback Without
Surprise Mutations").
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from contrib_pilot.config import Config
from contrib_pilot.errors import InvalidInputError
from contrib_pilot.git import hooks_path
from contrib_pilot.models import Finding, Severity

MANAGED_HOOKS_DIR = Path(".contrib-pilot/hooks")
_MARKER = "# managed-by: contrib-pilot"


@dataclass
class HooksStatus:
    current_hooks_path: str | None
    managed: bool
    would_install_at: str


def status(config: Config) -> HooksStatus:
    current = hooks_path(config.repo_root)
    return HooksStatus(
        current_hooks_path=current,
        managed=current == str(MANAGED_HOOKS_DIR),
        would_install_at=str(MANAGED_HOOKS_DIR),
    )


def install(config: Config, *, confirmed: bool) -> HooksStatus:
    current = status(config)
    if current.current_hooks_path and not current.managed:
        raise InvalidInputError(
            f"core.hooksPath is already set to {current.current_hooks_path!r}",
            remediation=(
                "Compose manually: add a call to "
                f"`{MANAGED_HOOKS_DIR}/pre-commit` from your existing hook, "
                "or unset core.hooksPath first if you intend to replace it."
            ),
        )
    if not confirmed:
        raise InvalidInputError(
            "Hook installation requires explicit confirmation",
            remediation=f"Re-run with confirmation to set core.hooksPath={MANAGED_HOOKS_DIR}",
        )

    subprocess.run(
        ["git", "config", "core.hooksPath", str(MANAGED_HOOKS_DIR)],
        cwd=config.repo_root,
        check=True,
        shell=False,
        timeout=5,
    )
    return status(config)


def uninstall(config: Config) -> HooksStatus:
    current = status(config)
    if current.managed:
        subprocess.run(
            ["git", "config", "--unset", "core.hooksPath"],
            cwd=config.repo_root,
            check=True,
            shell=False,
            timeout=5,
        )
    return status(config)


def staged_content_findings(config: Config, staged_paths: list[str]) -> list[Finding]:
    """Fast, deterministic checks run from ``hook pre-commit``.

    Intentionally narrow: boundary + prohibited-file checks only. No test
    execution, no generation, no file mutation.
    """

    findings: list[Finding] = []
    for path in staged_paths:
        if not config.is_allowed_change_path(path):
            findings.append(
                Finding(
                    rule_id="hooks.boundary-violation",
                    severity=Severity.BLOCKING,
                    message=f"Staged path is outside the allowed change paths: {path}",
                    path=Path(path),
                    evidence="Path did not match [changes].allowed_paths.",
                    remediation="Unstage the file or update config.toml with review.",
                )
            )
        if path.endswith((".env", ".pem", ".key")):
            findings.append(
                Finding(
                    rule_id="hooks.prohibited-file",
                    severity=Severity.BLOCKING,
                    message=f"Staged path matches a prohibited pattern: {path}",
                    path=Path(path),
                    evidence="Filename suffix suggests a secret or credential file.",
                    remediation="Remove this file from the commit.",
                )
            )
    return findings
