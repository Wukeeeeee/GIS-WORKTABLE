"""Standard-library-only backend identity and port checks for local launchers."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVICE = "gis-worktable"
WORKSPACE = os.path.normcase(str(PROJECT_ROOT))


def health_identity():
    from backend.services.cn_profile import get_profile
    return {"status": "ok", "service": SERVICE, "workspace": WORKSPACE, "pid": os.getpid(), "profile": get_profile()}


def probe(port):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
            data = json.loads(response.read(8192))
        if (isinstance(data, dict) and data.get("status") == "ok"
                and data.get("service") == SERVICE and data.get("workspace") == WORKSPACE
                and data.get("profile") == health_identity()["profile"]):
            return data
    except (OSError, ValueError):
        pass
    return None


def port_available(port):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def candidate_ports():
    explicit = os.environ.get("GIS_PORT")
    if explicit:
        port = int(explicit)
        if not 1 <= port <= 65535:
            raise ValueError("GIS_PORT must be between 1 and 65535")
        return [port]
    return [8000]


def select_port():
    ports = candidate_ports()
    # Prefer an existing instance of this checkout over starting another one.
    for port in ports:
        if not port_available(port) and probe(port):
            return port
    for port in ports:
        if port_available(port):
            return port
    raise RuntimeError(f"Port {ports[0]} is occupied by another service or checkout. "
                       "Close that service first, or explicitly set GIS_PORT. No automatic port switching.")


def start_backend(port):
    """Start backend with concurrency protection against double-clicking."""
    data = probe(port)
    if data:
        print(f"GIS-WORKTABLE is already running on port {port} (PID {data.get('pid')}).")
        return 0

    bootstrap_dir = PROJECT_ROOT / ".bootstrap"
    bootstrap_dir.mkdir(exist_ok=True)
    lock_file = bootstrap_dir / f"start_{port}.lock"

    # Acquire startup lock to prevent duplicate backend processes on double-click
    lock_fd = None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            lock_fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except FileExistsError:
            time.sleep(0.5)
            if probe(port):
                print(f"GIS-WORKTABLE was started on port {port} by concurrent launcher.")
                return 0
        except OSError:
            time.sleep(0.5)

    if lock_fd is None:
        raise RuntimeError(f"Startup lock is still held on port {port}; wait for setup to finish. If no launcher is running, remove {lock_file} and retry.")

    try:
        # Re-check probe once lock is held
        data = probe(port)
        if data:
            print(f"GIS-WORKTABLE is already running on port {port} (PID {data.get('pid')}).")
            return 0

        cmd = [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)]
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_CONSOLE | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)

        print(f"Starting GIS-WORKTABLE on port {port}...")
        proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), creationflags=flags)

        # Wait up to 90 seconds for health check
        wait_deadline = time.monotonic() + 90
        while time.monotonic() < wait_deadline:
            if probe(port):
                return 0
            if proc.poll() is not None:
                raise RuntimeError(f"Backend process exited prematurely with code {proc.returncode}.")
            time.sleep(0.5)
        raise RuntimeError(f"Backend on port {port} not ready after 90 seconds; check the backend console window.")
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError:
                pass
            try:
                lock_file.unlink(missing_ok=True)
            except OSError:
                pass


def stop_backend():
    stopped_count = 0
    for port in candidate_ports():
        data = probe(port)
        if data and type(data.get("pid")) is int and data["pid"] > 0:
            pid = data["pid"]
            try:
                os.kill(pid, signal.SIGTERM)
                # Wait up to 5 seconds for port release
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and probe(port):
                    time.sleep(0.3)
                print(f"Stopped GIS-WORKTABLE on port {port} (PID {pid}).")
                stopped_count += 1
            except ProcessLookupError:
                print(f"Process PID {pid} already stopped.")
            except Exception as e:
                print(f"Error stopping PID {pid} on port {port}: {e}")
    if stopped_count == 0:
        print("No running GIS-WORKTABLE instance found on candidate ports.")
    return 0


def open_browser(port):
    """Open browser with debounce to prevent duplicate tabs on double click."""
    bootstrap_dir = PROJECT_ROOT / ".bootstrap"
    bootstrap_dir.mkdir(exist_ok=True)
    stamp_file = bootstrap_dir / f"browser_{port}.stamp"

    now = time.time()
    if stamp_file.exists():
        try:
            last_open = float(stamp_file.read_text().strip())
            if now - last_open < 3.0:
                # Opened within 3 seconds, skip duplicate tab
                return 0
        except Exception:
            pass
    try:
        stamp_file.write_text(str(now))
    except Exception:
        pass
    webbrowser.open(f"http://127.0.0.1:{port}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("select", "check", "wait", "start", "stop", "open-browser"))
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.action == "select":
        print(select_port())
    elif args.action == "check":
        if args.port is None:
            parser.error("check requires --port")
        raise SystemExit(0 if probe(args.port) else 1)
    elif args.action == "wait":
        if args.port is None:
            parser.error("wait requires --port")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if probe(args.port):
                return
            time.sleep(1)
        raise RuntimeError("Backend not ready after 90 seconds; check the backend window.")
    elif args.action == "start":
        if args.port is None:
            parser.error("start requires --port")
        raise SystemExit(start_backend(args.port))
    elif args.action == "open-browser":
        if args.port is None:
            parser.error("open-browser requires --port")
        raise SystemExit(open_browser(args.port))
    elif args.action == "stop":
        raise SystemExit(stop_backend())


if __name__ == "__main__":
    main()
