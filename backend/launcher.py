"""Standard-library-only backend identity and port checks for local launchers."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import time
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVICE = "gis-worktable"
WORKSPACE = os.path.normcase(str(PROJECT_ROOT))


def health_identity():
    return {"status": "ok", "service": SERVICE, "workspace": WORKSPACE, "pid": os.getpid()}


def probe(port):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
            data = json.loads(response.read(8192))
        if (isinstance(data, dict) and data.get("status") == "ok"
                and data.get("service") == SERVICE and data.get("workspace") == WORKSPACE):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("select", "check", "wait", "stop"))
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
    else:
        for port in candidate_ports():
            data = probe(port)
            if data and type(data.get("pid")) is int and data["pid"] > 0:
                os.kill(data["pid"], signal.SIGTERM)
                print(f"Stopped GIS-WORKTABLE on port {port}.")


if __name__ == "__main__":
    main()
