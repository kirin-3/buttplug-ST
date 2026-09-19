"""
ButtplugST - REST bridge between SillyTavern and buttplug.io devices via Intiface Central.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("buttplug-st")
except PackageNotFoundError:  # package not installed (e.g. running from a raw checkout)
    __version__ = "0.0.0.dev0"
