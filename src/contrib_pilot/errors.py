"""CLI exit codes and the exceptions that map to them.

See DESIGN.md "Exit codes" for the contract these implement.
"""

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    INVALID_INPUT = 2
    MISSING_CONTEXT = 3
    BOUNDARY_VIOLATION = 4
    STALE_OR_UNSAFE_WRITE = 5
    VALIDATION_FAILED = 6
    INTERNAL_ERROR = 7


class ContribPilotError(Exception):
    """Base class for errors that carry a specific CLI exit code."""

    exit_code: ExitCode = ExitCode.INTERNAL_ERROR

    def __init__(self, message: str, *, remediation: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.remediation = remediation

    def __str__(self) -> str:
        if self.remediation:
            return f"{self.message}\nRemediation: {self.remediation}"
        return self.message


class InvalidInputError(ContribPilotError):
    exit_code = ExitCode.INVALID_INPUT


class MissingContextError(ContribPilotError):
    exit_code = ExitCode.MISSING_CONTEXT


class BoundaryViolationError(ContribPilotError):
    exit_code = ExitCode.BOUNDARY_VIOLATION


class StaleStateError(ContribPilotError):
    exit_code = ExitCode.STALE_OR_UNSAFE_WRITE


class ValidationFailedError(ContribPilotError):
    exit_code = ExitCode.VALIDATION_FAILED


class InternalError(ContribPilotError):
    exit_code = ExitCode.INTERNAL_ERROR
