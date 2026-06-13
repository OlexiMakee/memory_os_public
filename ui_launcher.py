#!/usr/bin/env python3
import sys
import os

# Add src to PYTHONPATH so we can run directly from root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from memory_os.core.config import MemoryOSConfig
from memory_os.ui.server import run_ui_server

def main():
    print("Initializing Memory OS UI Launcher...")
    
    try:
        config = MemoryOSConfig()
    except Exception as e:
        print(f"Error loading configuration: {e}")
        print("Please ensure you are running this from a valid memory_os project directory.")
        sys.exit(1)
        
    run_ui_server(config, port=8080)

if __name__ == "__main__":
    main()
