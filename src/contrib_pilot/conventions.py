"""Typing, lint-policy, and closed-world import conventions.

Planner stamps constraints; scaffold rechecks third-party imports; validate
emits advisory findings. Ruff itself is never invoked here — that stays a
``CHECK_REGISTRY`` command at ``validate`` (DESIGN.md "Convention constraints").
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from contrib_pilot.errors import BoundaryViolationError
from contrib_pilot.models import Finding, Severity

ImportClass = Literal["stdlib", "first_party", "third_party"]

LINT_CHECK_DEFINITIONS = frozenset({"project-pre-commit-changed-files"})

CONVENTION_SOURCE_PURPOSES: dict[str, str] = {
    "AGENTS.md": "agent instructions",
    "pyproject.toml": "ruff policy",
    ".pre-commit-config.yaml": "lint hook inventory",
}

NO_NEW_THIRD_PARTY = "libs.no-new-third-party"


@dataclass(frozen=True)
class RuleSpec:
    id: str
    severity: Severity = Severity.ADVISORY
    applies_at: tuple[str, ...] = ("validate",)


RULE_REGISTRY: dict[str, RuleSpec] = {
    "typing.pep604-union": RuleSpec(id="typing.pep604-union"),
    "typing.builtin-generics": RuleSpec(id="typing.builtin-generics"),
    "typing.any-on-new-api": RuleSpec(id="typing.any-on-new-api"),
    NO_NEW_THIRD_PARTY: RuleSpec(
        id=NO_NEW_THIRD_PARTY,
        severity=Severity.BLOCKING,
        applies_at=("scaffold", "validate"),
    ),
    "hints.google-docstring": RuleSpec(id="hints.google-docstring"),
}


@dataclass(frozen=True)
class ConventionConstraints:
    applicable_rules: list[str]
    observed_imports: list[str]
    lint_checks: list[str]
    lint_policy_summary: str


def classify_import(name: str, first_party_prefixes: tuple[str, ...]) -> ImportClass:
    root = name.split(".", 1)[0]
    if root in sys.stdlib_module_names or root == "__future__":
        return "stdlib"
    if root in first_party_prefixes:
        return "first_party"
    return "third_party"


def _top_level_imported(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        if not node.names:
            return None
        return node.names[0].name.split(".", 1)[0]
    if isinstance(node, ast.ImportFrom):
        if node.level and node.level > 0:
            return None
        if not node.module:
            return None
        return node.module.split(".", 1)[0]
    return None


def imported_top_levels(source: str) -> list[tuple[str, int]]:
    """Return (top-level-name, lineno) for absolute imports. Skip relative imports."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        name = _top_level_imported(node)
        if name:
            found.append((name, getattr(node, "lineno", 1)))
    return found


def _is_implementation_python(path: str) -> bool:
    posix = path.replace("\\", "/")
    return posix.endswith(".py") and not posix.startswith("tests/")


def inventory_imports(
    source_contents: dict[str, str], first_party_prefixes: tuple[str, ...]
) -> list[str]:
    names: set[str] = set()
    for path, text in source_contents.items():
        if not _is_implementation_python(path):
            continue
        for name, _lineno in imported_top_levels(text):
            names.add(name)
    return sorted(names)


def lint_policy_summary(pyproject_text: str | None) -> str:
    if not pyproject_text:
        return ""
    import tomllib

    try:
        raw = tomllib.loads(pyproject_text)
    except tomllib.TOMLDecodeError:
        return ""
    selected = raw.get("tool", {}).get("ruff", {}).get("lint", {}).get("select", [])
    if not isinstance(selected, list) or not selected:
        return ""
    codes = [str(item) for item in selected]
    return "Ruff select: " + ",".join(codes)


def lint_check_ids(checks: tuple) -> list[str]:
    return [check.id for check in checks if getattr(check, "definition", None) in LINT_CHECK_DEFINITIONS]


def constraints_from(
    *,
    source_contents: dict[str, str],
    convention_rules: tuple[str, ...],
    first_party_prefixes: tuple[str, ...],
    checks: tuple,
) -> ConventionConstraints:
    pyproject = None
    for path, text in source_contents.items():
        if path.replace("\\", "/") == "pyproject.toml":
            pyproject = text
            break
    return ConventionConstraints(
        applicable_rules=list(convention_rules),
        observed_imports=inventory_imports(source_contents, first_party_prefixes),
        lint_checks=lint_check_ids(checks),
        lint_policy_summary=lint_policy_summary(pyproject),
    )


def prompt_block(constraints: ConventionConstraints) -> str:
    rules = ", ".join(constraints.applicable_rules) or "(none)"
    imports = ", ".join(constraints.observed_imports) or "(none)"
    lint = constraints.lint_policy_summary or "(none)"
    checks = ", ".join(constraints.lint_checks) or "(none)"
    return (
        "Convention constraints (engine-authored; do not add rule IDs or packages):\n"
        f"- Rules: {rules}\n"
        f"- Observed imports (reuse these; do not add third-party names): {imports}\n"
        f"- Lint policy: {lint}\n"
        f"- Lint checks that validate will run: {checks}\n"
    )


def _materialized_python(path: Path, content: str) -> str | None:
    if not str(path).replace("\\", "/").endswith(".py"):
        return None
    return content


def assert_no_new_third_party(
    *,
    implementation_files: list[Path],
    proposed_texts: dict[str, str],
    observed_imports: list[str],
    first_party_prefixes: tuple[str, ...],
) -> None:
    allowed = set(observed_imports)
    planned_impl = {str(path).replace("\\", "/") for path in implementation_files}
    for path, text in proposed_texts.items():
        posix = path.replace("\\", "/")
        if posix not in planned_impl:
            continue
        parsed = _materialized_python(Path(posix), text)
        if parsed is None:
            continue
        try:
            ast.parse(parsed)
        except SyntaxError as exc:
            raise BoundaryViolationError(
                f"Proposed Python is not parseable: {posix}",
                remediation="Fix syntax in the proposal, or re-scaffold.",
            ) from exc
        for name, _lineno in imported_top_levels(parsed):
            if classify_import(name, first_party_prefixes) != "third_party":
                continue
            if name in allowed:
                continue
            raise BoundaryViolationError(
                f"New third-party import {name!r} is not in observed_imports ({posix})",
                remediation=(
                    "Reuse an import already in approved sources, or record a "
                    "justified new dependency in the plan assumptions and re-plan."
                ),
            )


def _parse(source: str) -> ast.AST | None:
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _neighbors_use_pep604(neighbor_contents: dict[str, str]) -> bool:
    for text in neighbor_contents.values():
        tree = _parse(text)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                return True
    return False


def _name_is(node: ast.AST, *names: str) -> bool:
    if isinstance(node, ast.Name) and node.id in names:
        return True
    if isinstance(node, ast.Attribute) and node.attr in names:
        return True
    return False


def _is_public_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return not node.name.startswith("_")


def evaluate(
    *,
    applicable_rules: list[str],
    observed_imports: list[str],
    first_party_prefixes: tuple[str, ...],
    changed_contents: dict[str, str],
    neighbor_contents: dict[str, str],
    implementation_files: list[Path],
) -> list[Finding]:
    findings: list[Finding] = []
    enabled = set(applicable_rules)
    neighbors_pep604 = _neighbors_use_pep604(neighbor_contents)

    for path, text in changed_contents.items():
        posix = path.replace("\\", "/")
        if not posix.endswith(".py"):
            continue
        tree = _parse(text)
        if tree is None:
            continue

        if "typing.pep604-union" in enabled and neighbors_pep604:
            for node in ast.walk(tree):
                if _name_is(node, "Optional", "Union"):
                    findings.append(
                        Finding(
                            rule_id="typing.pep604-union",
                            severity=Severity.ADVISORY,
                            message="Prefer PEP 604 unions (X | None) over Optional/Union",
                            path=Path(posix),
                            line=getattr(node, "lineno", None),
                            evidence=ast.get_source_segment(text, node) or "Optional/Union",
                            remediation="Use `X | None` (or `X | Y`) to match neighboring code.",
                        )
                    )
                    break

        if "typing.builtin-generics" in enabled:
            for node in ast.walk(tree):
                if _name_is(node, "List", "Dict", "Set", "Tuple"):
                    findings.append(
                        Finding(
                            rule_id="typing.builtin-generics",
                            severity=Severity.ADVISORY,
                            message="Prefer builtin generics (list[T], dict[K, V]) over typing.List/Dict",
                            path=Path(posix),
                            line=getattr(node, "lineno", None),
                            evidence=ast.get_source_segment(text, node) or "typing.List/Dict",
                            remediation="Use list[T], dict[K, V], set[T], tuple[T, ...].",
                        )
                    )
                    break

        if "typing.any-on-new-api" in enabled:
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not _is_public_function(node):
                    continue
                annotated = [node.returns, *[arg.annotation for arg in node.args.args]]
                if any(_name_is(item, "Any") for item in annotated if item is not None):
                    findings.append(
                        Finding(
                            rule_id="typing.any-on-new-api",
                            severity=Severity.ADVISORY,
                            message=f"Public function {node.name!r} is annotated with Any",
                            path=Path(posix),
                            line=node.lineno,
                            evidence=node.name,
                            remediation="Name a concrete type, or use object if the value is truly untyped.",
                        )
                    )

        if "hints.google-docstring" in enabled:
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not _is_public_function(node):
                    continue
                args = [arg.arg for arg in node.args.args if arg.arg not in {"self", "cls"}]
                if not args:
                    continue
                docstring = ast.get_docstring(node) or ""
                if "Args:" not in docstring and "Returns:" not in docstring:
                    findings.append(
                        Finding(
                            rule_id="hints.google-docstring",
                            severity=Severity.ADVISORY,
                            message=f"Public function {node.name!r} is missing a Google-style docstring",
                            path=Path(posix),
                            line=node.lineno,
                            evidence=node.name,
                            remediation="Add a short Google-style docstring with Args:/Returns:.",
                        )
                    )

        if NO_NEW_THIRD_PARTY in enabled:
            planned_impl = {str(p).replace("\\", "/") for p in implementation_files}
            if posix in planned_impl:
                allowed = set(observed_imports)
                for name, lineno in imported_top_levels(text):
                    if classify_import(name, first_party_prefixes) != "third_party":
                        continue
                    if name in allowed:
                        continue
                    findings.append(
                        Finding(
                            rule_id=NO_NEW_THIRD_PARTY,
                            severity=Severity.BLOCKING,
                            message=f"New third-party import {name!r} is not in observed_imports",
                            path=Path(posix),
                            line=lineno,
                            evidence=name,
                            remediation=(
                                "Reuse an import already in approved sources, or record a "
                                "justified new dependency in the plan assumptions and re-plan."
                            ),
                        )
                    )

    return findings
