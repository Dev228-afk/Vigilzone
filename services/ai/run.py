"""
Main entry point - Run from ai_module directory
Usage: python run.py
"""
import sys
from pathlib import Path

# Add src to path
ai_module_dir = Path(__file__).parent
sys.path.insert(0, str(ai_module_dir))

# Import and run
from src.app import main

if __name__ == "__main__":
    main()
