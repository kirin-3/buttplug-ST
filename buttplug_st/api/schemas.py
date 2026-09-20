"""Request/response schemas (Pydantic v2). GET query strings and POST JSON bodies
funnel through the same models, so validation and error text are identical."""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError


class VibrateRequest(BaseModel):
    """Request schema for vibration control."""

    speed: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Vibration intensity between 0.0 and 1.0",
    )
    position: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Position for supported devices between 0.0 and 1.0",
    )
    duration: float = Field(
        default=0.0,
        ge=0.0,
        description="Duration in seconds (0 = no limit)",
    )


class DeviceSelectionRequest(BaseModel):
    """Request schema for device selection."""

    index: int = Field(
        ge=0,
        description="Index of the device to select",
    )


class APIResponse(BaseModel):
    """Base response model for all API responses."""

    success: bool = Field(
        description="Whether the request was successful",
    )
    message: str = Field(
        description="Human-readable message describing the result",
    )
    data: dict[str, object] | None = Field(
        default=None,
        description="Optional data payload",
    )


class DeviceInfoResponse(BaseModel):
    """Response schema for device information."""

    id: str
    name: str
    index: int
    actuator_count: int
    actuator_types: list[str]


class DeviceListResponse(BaseModel):
    """Response schema for device list."""

    devices: list[DeviceInfoResponse]
    active_index: int


class ErrorResponse(BaseModel):
    """Response schema for errors."""

    error: str = Field(
        description="Error code",
    )
    detail: str = Field(
        description="Human-readable error description",
    )
    status_code: int = Field(
        description="HTTP status code",
    )


def format_validation_error(exc: PydanticValidationError) -> str:
    """Render a Pydantic error as '<parameter>: <message>' entries, naming the
    offending parameter for the API error detail."""
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "body"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)
