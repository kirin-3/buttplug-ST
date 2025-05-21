from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator

class VibrateRequest(BaseModel):
    """Request schema for vibration control"""
    speed: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Vibration intensity between 0.0 and 1.0"
    )
    position: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Position for supported devices between 0.0 and 1.0"
    )
    duration: float = Field(
        default=0.0,
        ge=0.0,
        description="Duration in seconds (0 = no limit)"
    )


class DeviceSelectionRequest(BaseModel):
    """Request schema for device selection"""
    index: int = Field(
        ge=0,
        description="Index of the device to select"
    )


class APIResponse(BaseModel):
    """Base response model for all API responses"""
    success: bool = Field(
        description="Whether the request was successful"
    )
    message: str = Field(
        description="Human-readable message describing the result"
    )
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional data payload"
    )


class DeviceInfoResponse(BaseModel):
    """Response schema for device information"""
    id: str
    name: str
    index: int
    actuator_count: int
    actuator_types: List[str]


class DeviceListResponse(BaseModel):
    """Response schema for device list"""
    devices: List[DeviceInfoResponse]
    active_index: int


class ErrorResponse(BaseModel):
    """Response schema for errors"""
    error: str = Field(
        description="Error code"
    )
    detail: str = Field(
        description="Human-readable error description"
    )
    status_code: int = Field(
        description="HTTP status code"
    ) 