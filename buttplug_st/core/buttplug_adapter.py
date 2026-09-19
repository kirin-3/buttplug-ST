"""Single import point for the official buttplug client API (1.0.0).

All device-layer code imports the client surface from this module only, so any
future client-version drift is contained here. Names and signatures were
verified against the installed 1.0.0 package source — see the change's
design-notes.md.
"""

from buttplug import (
    ButtplugClient,
    ButtplugConnectorError,
    ButtplugDevice,
    ButtplugDeviceError,
    ButtplugError,
    DeviceOutputCommand,
    OutputType,
)

__all__ = [
    "ButtplugClient",
    "ButtplugConnectorError",
    "ButtplugDevice",
    "ButtplugDeviceError",
    "ButtplugError",
    "DeviceOutputCommand",
    "OutputType",
]
