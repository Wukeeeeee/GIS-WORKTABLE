"""Isolated local UI QA server; does not use the user's project/history store."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
state = Path(__file__).resolve().parent / "local-state"
state.mkdir(parents=True, exist_ok=True)
os.environ["GIS_WORKSPACE_DB_PATH"] = str(state / "workspace.db")
from backend import main
from backend.services import ai_service, project_service, task_manager

ai_service._HISTORY_DIR = str(state / "history")
project_service._PROJECT_DIR = str(state / "projects")
project_service._BLOB_DIR = str(state / "projects" / "blobs")
project_service._INDEX_PATH = str(state / "projects" / "index.json")
task_manager._BASE_DIR = str(state / "tasks")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(main.app, host="127.0.0.1", port=8031, log_level="warning")
