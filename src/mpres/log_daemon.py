from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from mpres.util import MPresError, read_json, task_path, utc_now, write_json_atomic

MAX_REQUEST_BYTES = 4 * 1024 * 1024
START_TIMEOUT_SECONDS = 10.0


def runtime_dir(root: Path) -> Path:
    path = root / ".mpres"
    path.mkdir(parents=True, exist_ok=True)
    return path


def daemon_state_path(root: Path) -> Path:
    return runtime_dir(root) / "log-daemon.json"


def daemon_socket_path(root: Path) -> Path:
    return runtime_dir(root) / "log-daemon.sock"


def daemon_stderr_path(root: Path) -> Path:
    return runtime_dir(root) / "log-daemon.stderr.log"


def project_log_path(root: Path, slug: str) -> Path:
    return task_path(root, slug) / "logs" / "project.jsonl"


def _endpoint_from_state(state: dict[str, Any]) -> tuple[str, Any]:
    transport = str(state.get("transport") or "")
    if transport == "unix":
        return transport, str(state.get("socket_path") or "")
    if transport == "tcp":
        return transport, (str(state.get("host") or "127.0.0.1"), int(state.get("port") or 0))
    raise MPresError("Malformed log-daemon endpoint state.")


def _connect(state: dict[str, Any], timeout: float = 3.0) -> socket.socket:
    transport, endpoint = _endpoint_from_state(state)
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while True:
        if transport == "unix":
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        else:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(max(0.05, deadline - time.monotonic()))
        try:
            client.connect(endpoint)
            return client
        except OSError as exc:
            client.close()
            last_error = exc
            if time.monotonic() >= deadline:
                raise last_error
            if exc.errno not in {11, 35, 111, 61}:
                raise
            time.sleep(0.01)


def _request(root: Path, payload: dict[str, Any], *, timeout: float = 5.0) -> dict[str, Any]:
    state = read_json(daemon_state_path(root))
    raw = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > MAX_REQUEST_BYTES:
        raise MPresError("Log request is too large.")
    try:
        with _connect(state, timeout=timeout) as client:
            client.sendall(raw)
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_REQUEST_BYTES:
                    raise MPresError("Log daemon returned an oversized response.")
                if b"\n" in chunk:
                    break
    except (OSError, ValueError, KeyError) as exc:
        raise MPresError(f"Cannot communicate with the project log daemon: {exc}") from exc
    text = b"".join(chunks).split(b"\n", 1)[0].decode("utf-8", errors="replace")
    try:
        response = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MPresError("Project log daemon returned malformed JSON.") from exc
    if not isinstance(response, dict) or response.get("ok") is not True:
        raise MPresError(str(response.get("error") if isinstance(response, dict) else response))
    return response


def daemon_status(root: Path) -> dict[str, Any]:
    state_path = daemon_state_path(root)
    if not state_path.is_file():
        return {"running": False, "reason": "state_missing", "state_path": str(state_path)}
    try:
        state = read_json(state_path)
        response = _request(root, {"op": "ping"}, timeout=1.5)
    except MPresError as exc:
        return {
            "running": False,
            "reason": "unreachable",
            "error": str(exc),
            "state_path": str(state_path),
        }
    return {"running": True, **state, **response}


def _cleanup_stale_runtime(root: Path) -> None:
    state = daemon_state_path(root)
    socket_path = daemon_socket_path(root)
    if state.exists():
        try:
            current = read_json(state)
            pid = int(current.get("pid") or 0)
            if pid > 0:
                try:
                    os.kill(pid, 0)
                except OSError:
                    pass
                else:
                    return
        except Exception:
            pass
        state.unlink(missing_ok=True)
    if socket_path.exists():
        socket_path.unlink(missing_ok=True)


def _acquire_start_claim(root: Path, timeout: float = START_TIMEOUT_SECONDS) -> int:
    claim = runtime_dir(root) / "log-daemon.starting"
    deadline = time.monotonic() + timeout
    while True:
        try:
            return os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            status = daemon_status(root)
            if status.get("running"):
                return -1
            if time.monotonic() >= deadline:
                try:
                    age = time.time() - claim.stat().st_mtime
                    if age > timeout:
                        claim.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                raise MPresError("Timed out waiting for another log-daemon startup.")
            time.sleep(0.05)


def start_log_daemon(root: Path, *, timeout: float = START_TIMEOUT_SECONDS) -> dict[str, Any]:
    root = root.resolve()
    status = daemon_status(root)
    if status.get("running"):
        return status
    claim_fd = _acquire_start_claim(root, timeout=timeout)
    if claim_fd == -1:
        return daemon_status(root)
    claim = runtime_dir(root) / "log-daemon.starting"
    try:
        # Another caller may have completed startup after this caller acquired the transient
        # startup claim. Recheck before spawning so there is exactly one persistent writer.
        status = daemon_status(root)
        if status.get("running"):
            return status
        _cleanup_stale_runtime(root)
        stderr = daemon_stderr_path(root).open("ab", buffering=0)
        command = [sys.executable, "-m", "mpres.log_daemon", "serve", "--root", str(root)]
        environment = os.environ.copy()
        package_src = str(Path(__file__).resolve().parents[1])
        existing_pythonpath = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = (
            package_src if not existing_pythonpath else package_src + os.pathsep + existing_pythonpath
        )
        try:
            subprocess.Popen(
                command,
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            stderr.close()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = daemon_status(root)
            if status.get("running"):
                return status
            time.sleep(0.05)
        raise MPresError(f"Project log daemon did not start; inspect {daemon_stderr_path(root)}")
    finally:
        try:
            os.close(claim_fd)
        except OSError:
            pass
        claim.unlink(missing_ok=True)


def ensure_log_daemon(root: Path) -> dict[str, Any]:
    status = daemon_status(root)
    return status if status.get("running") else start_log_daemon(root)


def submit_log_record(root: Path, slug: str, record: dict[str, Any]) -> dict[str, Any]:
    ensure_log_daemon(root)
    try:
        return _request(root, {"op": "append", "slug": slug, "record": record})
    except MPresError:
        # One retry handles a daemon that died between status and append.
        _cleanup_stale_runtime(root)
        start_log_daemon(root)
        return _request(root, {"op": "append", "slug": slug, "record": record})


def stop_log_daemon(root: Path) -> dict[str, Any]:
    status = daemon_status(root)
    if not status.get("running"):
        _cleanup_stale_runtime(root)
        return {"stopped": True, "already_stopped": True}
    response = _request(root, {"op": "stop"}, timeout=3.0)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not daemon_status(root).get("running"):
            _cleanup_stale_runtime(root)
            return {"stopped": True, "already_stopped": False, **response}
        time.sleep(0.05)
    return {"stopped": False, "error": "daemon did not exit within five seconds"}


class _UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


class _TcpServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


class _RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            self._reply({"ok": False, "error": "request too large"})
            return
        try:
            request = json.loads(raw.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            operation = request.get("op")
            server = self.server
            if operation == "ping":
                self._reply(
                    {
                        "ok": True,
                        "pid": os.getpid(),
                        "started_utc": getattr(server, "started_utc"),
                        "last_sequence": getattr(server, "last_sequence"),
                    }
                )
                return
            if operation == "append":
                slug = str(request.get("slug") or "")
                record = request.get("record")
                if not isinstance(record, dict):
                    raise ValueError("record must be an object")
                response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
                getattr(server, "write_queue").put((slug, record, response_queue))
                response = response_queue.get(timeout=10.0)
                self._reply(response)
                return
            if operation == "stop":
                self._reply({"ok": True, "stopping": True})
                threading.Thread(target=server.shutdown, daemon=True).start()
                return
            raise ValueError(f"unknown operation: {operation!r}")
        except Exception as exc:
            self._reply({"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def _reply(self, response: dict[str, Any]) -> None:
        self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        self.wfile.flush()


def _last_sequence(root: Path) -> int:
    maximum = 0
    tasks = root / "tasks"
    if not tasks.is_dir():
        return 0
    for path in tasks.glob("*/logs/project.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]
        except OSError:
            continue
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            value = record.get("daemon_sequence") if isinstance(record, dict) else None
            if isinstance(value, int):
                maximum = max(maximum, value)
                break
    return maximum


def _writer_loop(server: Any, root: Path) -> None:
    while True:
        item = server.write_queue.get()
        if item is None:
            return
        slug, record, response_queue = item
        try:
            path = project_log_path(root, slug)
            path.parent.mkdir(parents=True, exist_ok=True)
            server.last_sequence += 1
            output = dict(record)
            output["daemon_sequence"] = server.last_sequence
            output["recorded_by"] = "mpres-log-daemon"
            line = json.dumps(output, ensure_ascii=False, sort_keys=True) + "\n"
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            response_queue.put(
                {
                    "ok": True,
                    "sequence": server.last_sequence,
                    "path": str(path),
                    "record": output,
                }
            )
        except Exception as exc:
            response_queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def serve(root: Path) -> int:
    root = root.resolve()
    runtime = runtime_dir(root)
    socket_path = daemon_socket_path(root)
    use_unix_socket = os.name != "nt" and len(str(socket_path).encode("utf-8")) < 96
    if use_unix_socket:
        socket_path.unlink(missing_ok=True)
        server: Any = _UnixServer(str(socket_path), _RequestHandler)
        endpoint = {
            "transport": "unix",
            "socket_path": str(socket_path),
        }
    else:
        server = _TcpServer(("127.0.0.1", 0), _RequestHandler)
        host, port = server.server_address
        endpoint = {"transport": "tcp", "host": host, "port": int(port)}
    server.started_utc = utc_now()
    server.last_sequence = _last_sequence(root)
    server.write_queue = queue.Queue()
    writer = threading.Thread(target=_writer_loop, args=(server, root), daemon=True)
    writer.start()
    state = {
        "schema_version": 1,
        "pid": os.getpid(),
        "root": str(root),
        "started_utc": server.started_utc,
        **endpoint,
    }
    write_json_atomic(daemon_state_path(root), state)

    def request_shutdown(signum: int, frame: Any) -> None:
        del signum, frame
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.write_queue.put(None)
        writer.join(timeout=5.0)
        server.server_close()
        daemon_state_path(root).unlink(missing_ok=True)
        if use_unix_socket:
            socket_path.unlink(missing_ok=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mpres.log_daemon")
    sub = parser.add_subparsers(dest="command", required=True)
    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--root", type=Path, required=True)
    for name in ("start", "status", "stop"):
        item = sub.add_parser(name)
        item.add_argument("--root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return serve(args.root)
    if args.command == "start":
        result = start_log_daemon(args.root)
    elif args.command == "status":
        result = daemon_status(args.root)
    else:
        result = stop_log_daemon(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("running") or result.get("stopped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
