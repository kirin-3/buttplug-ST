import os
import tomli
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

class Settings(BaseModel):
    class Server(BaseModel):
        host: str = Field("localhost", description="Server host")
        port: int = Field(3069, description="Server port")
        debug: bool = Field(False, description="Debug mode")

    class Websocket(BaseModel):
        url: str = Field("ws://127.0.0.1:12345", description="Intiface websocket URL")
        scan_timeout: int = Field(2, description="Device scan timeout in seconds")
        
    class Device(BaseModel):
        default_speed: float = Field(0.5, description="Default vibration speed")
        default_position: float = Field(0.5, description="Default position for linear movement")
        default_duration: float = Field(0.0, description="Default duration in seconds (0 = no limit)")

    server: Server = Server()
    websocket: Websocket = Websocket()
    device: Device = Device()

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Settings":
        """Load settings from TOML file with environment variable override"""
        # Default config file path
        if config_path is None:
            base_dir = Path(__file__).parent
            config_path = os.path.join(base_dir, "default.toml")
        
        # Load from file if exists
        if os.path.exists(config_path):
            with open(config_path, "rb") as f:
                config_data = tomli.load(f)
            settings = cls.parse_obj(config_data)
        else:
            settings = cls()
            
        # Override with environment variables
        # Format: BUTTPLUG_SERVER_HOST, BUTTPLUG_WEBSOCKET_URL, etc.
        for env_name, env_value in os.environ.items():
            if env_name.startswith("BUTTPLUG_"):
                parts = env_name.lower().split("_")[1:]  # Remove BUTTPLUG_ prefix
                if len(parts) >= 2:
                    section, key = parts[0], "_".join(parts[1:])
                    if hasattr(settings, section) and hasattr(getattr(settings, section), key):
                        section_obj = getattr(settings, section)
                        field_type = type(getattr(section_obj, key))
                        setattr(section_obj, key, field_type(env_value))
        
        return settings 