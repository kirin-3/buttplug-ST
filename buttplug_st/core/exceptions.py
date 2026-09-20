"""Domain exceptions. Every subclass carries its HTTP status and machine-readable code."""

from __future__ import annotations


class ButtplugSTException(Exception):
    """Base exception for all app-specific exceptions."""

    status_code: int = 500
    code: str = "internal_error"
    detail: str = "An internal error occurred"

    def __init__(
        self,
        detail: str | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ):
        if detail is not None:
            self.detail = detail
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.detail)

    def to_dict(self) -> dict[str, str | int]:
        """Convert exception to dictionary for API responses."""
        return {
            "error": self.code,
            "detail": self.detail,
            "status_code": self.status_code,
        }


class ValidationError(ButtplugSTException):
    """Invalid request input."""

    status_code: int = 400
    code: str = "validation_error"
    detail: str = "Invalid request parameters"


class DeviceNotFoundError(ButtplugSTException):
    """No device tracked, or the requested device index does not exist."""

    status_code: int = 404
    code: str = "device_not_found"
    detail: str = "No device found or connected"


class IntifaceUnavailableError(ButtplugSTException):
    """Intiface Central is unreachable, disconnected, or connection attempts are throttled."""

    status_code: int = 503
    code: str = "intiface_unavailable"
    detail: str = "Intiface Central is not available"


class CommandError(ButtplugSTException):
    """A device command failed at the protocol/device level."""

    status_code: int = 500
    code: str = "command_error"
    detail: str = "Failed to execute device command"
