"""Machine-readable diagnostic output.

JSON for tooling, and a compiler-style ``path:line:column: severity:
message`` line for IDE problem matchers (plan.MD "IDE mode").
"""

from __future__ import annotations

import json

from contrib_pilot.models import Finding


def to_compiler_format(findings: list[Finding]) -> str:
    lines = []
    for finding in findings:
        path = finding.path if finding.path is not None else "<plan>"
        line = finding.line if finding.line is not None else 1
        lines.append(f"{path}:{line}:1: {finding.severity.value}: {finding.message}")
    return "\n".join(lines)


def to_json(findings: list[Finding]) -> str:
    return json.dumps([json.loads(f.model_dump_json()) for f in findings], indent=2)
