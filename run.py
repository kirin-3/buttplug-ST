#!/usr/bin/env python3
"""Convenience launcher: `python run.py` behaves exactly like the `buttplug-st`
console script (which this project also installs)."""

import sys

from buttplug_st.app import main

if __name__ == "__main__":
    sys.exit(main())
