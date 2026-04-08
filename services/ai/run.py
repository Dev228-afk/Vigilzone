"""
Main entry point - Run from ai_module directory.
Automatically detects and uses the project's .venv if available.
Usage: python run.py
"""
import os
import sys
import subprocess
from pathlib import Path

# 1. Determine if we are already in the virtual environment
def is_venv():
    return (
        hasattr(sys, 'real_prefix') or
        (sys.base_prefix != sys.prefix)
    )

if __name__ == "__main__":
    ai_module_dir = Path(__file__).parent.resolve()
    venv_python = ai_module_dir.parent.parent / ".venv" / "Scripts" / "python.exe"

    # 2. If not in venv and .venv exists, re-launch using that python
    if not is_venv() and venv_python.exists():
        print(f"--- Detected .venv at {venv_python} ---")
        print(f"--- Re-launching using virtual environment ---")
        
        # Add src to PYTHONPATH so the sub-process can find it
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ai_module_dir) + os.pathsep + env.get("PYTHONPATH", "")
        
        try:
            # We use [sys.executable, venv_python, ...] to ensure we don't 
            # get caught in a loop if the venv itself is broken.
            # But the standard way is just to run venv_python.
            subprocess.run([str(venv_python), __file__], env=env, check=True)
            sys.exit(0)
        except subprocess.CalledProcessError as e:
            print(f"Error running in .venv: {e}")
            sys.exit(e.returncode)
        except Exception as e:
            print(f"Failed to switch to .venv: {e}")
            # Fallback to current python if switch fails

    # 3. Add src to path for direct execution
    sys.path.insert(0, str(ai_module_dir))

    # 4. Import and run
    try:
        from src.app import main
        main()
    except ImportError as e:
        print(f"Fatal Import Error: {e}")
        print("Please ensure the virtual environment (.venv) is correctly set up.")
        sys.exit(1)
