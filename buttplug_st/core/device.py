import asyncio
import logging
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from buttplug.client import (
    Client as ButtplugClient,
    Device as ButtplugClientDevice
)
from buttplug import ConnectorError
from buttplug.connectors import WebsocketConnector

from ..config import Settings
from .exceptions import (
    DeviceNotFoundError,
    DeviceConnectionError,
    IntifaceConnectionError,
    CommandError
)

logger = logging.getLogger(__name__)

@dataclass
class DeviceInfo:
    """Information about a connected device"""
    id: str
    name: str
    index: int
    actuator_count: int
    actuator_types: List[str]

class DeviceManager:
    """Manages connections to buttplug devices"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Optional[ButtplugClient] = None
        self._devices: List[ButtplugClientDevice] = []
        self._active_device_index: int = 0
        self._initialized: bool = False
        self._last_connection_attempt: float = 0
        self._connection_retry_delay: float = 5.0  # seconds
    
    @property
    def active_device(self) -> Optional[ButtplugClientDevice]:
        """Get the currently active device"""
        if not self._devices:
            return None
        return self._devices[self._active_device_index]
    
    @property
    def is_connected(self) -> bool:
        """Check if the client is connected to the server"""
        return self._client is not None and self._client.connected
    
    @property
    def has_devices(self) -> bool:
        """Check if any devices are connected"""
        return len(self._devices) > 0
    
    async def initialize(self) -> None:
        """Initialize the Buttplug client and scan for devices"""
        logger.info("Initialize called")
        
        # If already initialized and connected, just return
        if self._initialized and self.is_connected:
            logger.info("Already initialized and connected")
            return
        
        # If we recently failed to connect, don't retry too quickly
        current_time = time.time()
        if (self._last_connection_attempt > 0 and 
            current_time - self._last_connection_attempt < self._connection_retry_delay):
            logger.info(f"Connection attempt too recent, waiting {self._connection_retry_delay} seconds")
            raise IntifaceConnectionError("Connection attempt too recent, please wait a moment")
        
        self._last_connection_attempt = current_time
        
        # If we have a client but it's disconnected, clean it up
        if self._client and not self._client.connected:
            logger.info("Client exists but disconnected, cleaning up")
            self._client = None
            self._devices = []
            self._initialized = False
        
        try:
            logger.info("Creating new client")
            self._client = ButtplugClient("ButtplugST")
            connector = WebsocketConnector(self.settings.websocket.url)
            
            logger.info(f"Connecting to {self.settings.websocket.url}")
            await self._client.connect(connector)
            logger.info(f"Connected to Intiface at {self.settings.websocket.url}")
            
            # Scan for devices
            await self.scan_devices()
            self._initialized = True
            
        except ConnectorError as e:
            logger.error(f"Failed to connect to Intiface: {e}")
            raise IntifaceConnectionError(f"Failed to connect to Intiface: {str(e)}")
        except Exception as e:
            logger.error(f"Initialization error: {e}")
            raise DeviceConnectionError(f"Initialization error: {str(e)}")
    
    async def scan_devices(self) -> List[DeviceInfo]:
        """Scan for devices and update the device list"""
        logger.info("Scan devices called")
        
        if not self._client:
            logger.error("Client is None, cannot scan")
            raise IntifaceConnectionError("Client not initialized")
            
        if not self._client.connected:
            logger.error("Client not connected, cannot scan")
            raise IntifaceConnectionError("Not connected to Intiface")
            
        try:
            logger.info("Scanning for devices...")
            await self._client.start_scanning()
            await asyncio.sleep(self.settings.websocket.scan_timeout)
            await self._client.stop_scanning()
            
            self._devices = self._client.devices
            logger.info(f"Found {len(self._devices)} devices")
            
            if not self._devices:
                return []
                
            # Reset active device index
            self._active_device_index = 0
            
            # Return device info
            return [self._get_device_info(i) for i in range(len(self._devices))]
            
        except Exception as e:
            logger.error(f"Error scanning for devices: {e}")
            raise DeviceConnectionError(f"Error scanning for devices: {str(e)}")
    
    def _get_device_info(self, index: int) -> DeviceInfo:
        """Get information about a device at the specified index"""
        if index < 0 or index >= len(self._devices):
            raise DeviceNotFoundError(f"Device index {index} out of range")
            
        device = self._devices[index]
        actuator_types = []
        
        for actuator in device.actuators:
            actuator_types.append(str(type(actuator).__name__))
        
        return DeviceInfo(
            id=device.index,
            name=device.name,
            index=index,
            actuator_count=len(device.actuators),
            actuator_types=actuator_types
        )
    
    def get_all_devices(self) -> List[DeviceInfo]:
        """Get information about all connected devices"""
        return [self._get_device_info(i) for i in range(len(self._devices))]
    
    def get_active_device(self) -> Optional[DeviceInfo]:
        """Get information about the currently active device"""
        if not self._devices:
            return None
        return self._get_device_info(self._active_device_index)
    
    def set_active_device(self, index: int) -> DeviceInfo:
        """Set the active device by index"""
        if index < 0 or index >= len(self._devices):
            raise DeviceNotFoundError(f"Device index {index} out of range")
            
        self._active_device_index = index
        return self._get_device_info(index)
    
    async def vibrate(self, speed: float, position: Optional[float] = None, 
                      duration: float = 0) -> Dict[str, Any]:
        """Control vibration of the active device"""
        device = self.active_device
        if not device or not device.actuators:
            raise DeviceNotFoundError()
        
        try:
            # Clamp values
            speed = max(0.0, min(1.0, speed))
            if position is not None:
                position = max(0.0, min(1.0, position))
            
            logger.info(f"Vibrating device {device.name} at {speed*100:.0f}% power")
            
            # Get the first actuator (usually the vibration motor)
            actuator = device.actuators[0]
            
            # Try sending both speed and position if supported
            try:
                if position is not None:
                    await actuator.command(speed, position)
                else:
                    await actuator.command(speed)
            except TypeError:
                # Fallback: send only speed if position is not supported
                await actuator.command(speed)
                
            # If duration specified, schedule stop
            if duration > 0:
                asyncio.create_task(self._stop_after_delay(actuator, duration))
                
            result = {
                "success": True,
                "device": device.name,
                "speed": speed,
            }
            
            if position is not None:
                result["position"] = position
                
            if duration > 0:
                result["duration"] = duration
                
            return result
            
        except Exception as e:
            logger.error(f"Error sending vibrate command: {e}")
            raise CommandError(f"Error sending vibrate command: {str(e)}")
    
    async def _stop_after_delay(self, actuator, duration: float) -> None:
        """Stop actuator after specified duration"""
        await asyncio.sleep(duration)
        try:
            await actuator.command(0)
            logger.info(f"Stopped vibration after {duration} seconds")
        except Exception as e:
            logger.error(f"Error stopping vibration: {e}")
    
    async def stop(self) -> Dict[str, Any]:
        """Stop all actuators on the active device"""
        device = self.active_device
        if not device:
            raise DeviceNotFoundError()
            
        try:
            await device.stop()
            return {
                "success": True,
                "device": device.name,
                "status": "stopped"
            }
        except Exception as e:
            logger.error(f"Error stopping device: {e}")
            raise CommandError(f"Error stopping device: {str(e)}")
    
    async def shutdown(self) -> None:
        """Disconnect from all devices and shutdown client"""
        logger.info("Shutdown called")
        
        # First stop all devices if possible
        if self._client and self._client.connected and self._devices:
            try:
                logger.info("Stopping all devices before shutdown")
                for device in self._devices:
                    try:
                        await device.stop()
                    except Exception as e:
                        logger.warning(f"Failed to stop device {device.name}: {e}")
            except Exception as e:
                logger.warning(f"Error stopping devices during shutdown: {e}")
        
        # Then disconnect
        if self._client and self._client.connected:
            try:
                await self._client.disconnect()
                logger.info("Disconnected from Intiface")
            except Exception as e:
                logger.error(f"Error during client disconnect: {e}")
        
        self._client = None
        self._devices = []
        self._initialized = False
        logger.info("Shutdown complete") 