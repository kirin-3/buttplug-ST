#!/usr/bin/env python3
"""
ButtplugST launcher script

This script launches the ButtplugST server which acts as a bridge between 
SillyTavern and buttplug.io devices.
"""
import asyncio
import argparse
import os
import sys
from typing import Optional, Dict, Any


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for ButtplugST server"""
    parser = argparse.ArgumentParser(
        description='ButtplugST - Bridge between SillyTavern and buttplug.io'
    )
    parser.add_argument('--config', '-c', help='Path to config file')
    parser.add_argument('--host', '-H', help='Server host')
    parser.add_argument('--port', '-p', type=int, help='Server port')
    parser.add_argument('--debug', '-d', action='store_true', help='Enable debug mode')
    parser.add_argument('--websocket', '-w', help='Intiface websocket URL')
    return parser.parse_args()


async def main() -> None:
    """Main entry point for the application"""
    args = parse_args()
    
    # Set environment variables from command line args
    if args.host:
        os.environ['BUTTPLUG_SERVER_HOST'] = args.host
    if args.port:
        os.environ['BUTTPLUG_SERVER_PORT'] = str(args.port)
    if args.debug:
        os.environ['BUTTPLUG_SERVER_DEBUG'] = 'true'
    if args.websocket:
        os.environ['BUTTPLUG_WEBSOCKET_URL'] = args.websocket
    
    # Import here to respect environment variables
    from buttplug_st.config import Settings
    from buttplug_st.app import main as app_main
    
    settings = Settings.load(config_path=args.config if args.config else None)
    
    print(f"Starting ButtplugST server on {settings.server.host}:{settings.server.port}")
    print(f"Connecting to Intiface at {settings.websocket.url}")
    print("Press Ctrl+C to exit")
    
    await app_main()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0) 