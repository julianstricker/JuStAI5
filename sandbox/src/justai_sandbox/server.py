"""Sandbox runner service.

Runs untrusted plugins and tests of generated tools. Isolation layers:

1. the container: non-root, read-only root FS, all capabilities dropped,
   no-new-privileges, memory/CPU/PID limits, *internal* network (only the core
   is reachable - no internet, no LAN, no Docker socket, no database);
2. one OS process per plugin / test run with rlimits (CPU time, address space,
   open files, processes, file size), started with ``python -I`` and a minimal
   environment;
3. every capability is an RPC to the core gateway, which checks permissions.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import resource
import secrets
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from justai_sandbox.rpc import RpcPeer

WORK = Path(os.environ.get("SANDBOX_WORK_DIR", tempfile.gettempdir())) / "justai-sandbox"
CORE_URL = os.environ.get("SANDBOX_CORE_URL", "http://core:8080")
TOKEN_FILE = Path(os.environ.get("SANDBOX_TOKEN_FILE", "/run/secrets-shared/sandbox_token"))
MAX_FILES_BYTES = 2_000_000


def _token() -> str:
    if os.environ.get("SANDBOX_TOKEN"):
        return os.environ["SANDBOX_TOKEN"]
    return TOKEN_FILE.read_text().strip()


def _limits(cpu_s: int, mem_mb: int) -> Any:
    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 2**20, mem_mb * 2**20))
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
        resource.setrlimit(resource.RLIMIT_FSIZE, (20 * 2**20, 20 * 2**20))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.setsid()

    return apply


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1",
           "LANG": "C.UTF-8", "NO_PROXY": "*"}
    env.update(extra or {})
    return env


def _write_files(target: Path, files: dict[str, str]) -> None:
    total = 0
    for rel, content in files.items():
        path = (target / rel).resolve()
        if target.resolve() not in path.parents:
            raise ValueError(f"unsafe path {rel}")
        total += len(content.encode())
        if total > MAX_FILES_BYTES:
            raise ValueError("files too large")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


class PluginProcess:
    def __init__(self, plugin_id: str, proc: asyncio.subprocess.Process, gateway_token: str,
                 directory: Path) -> None:
        self.plugin_id = plugin_id
        self.proc = proc
        self.gateway_token = gateway_token
        self.directory = directory
        assert proc.stdout is not None and proc.stdin is not None
        self.peer = RpcPeer(proc.stdout, proc.stdin, self._upcall)
        self.peer.start()
        self._http = httpx.AsyncClient(base_url=CORE_URL, timeout=60)

    async def _upcall(self, method: str, params: dict[str, Any]) -> Any:
        if method != "gateway":
            raise ValueError("unknown upcall")
        r = await self._http.post(f"/internal/plugin-gateway/{self.plugin_id}", json=params,
                                  headers={"authorization": f"Bearer {self.gateway_token}"})
        data = r.json()
        if r.status_code >= 400:
            raise PermissionError(data.get("message") or data.get("error") or r.text)
        return data.get("result")

    async def stop(self) -> None:
        with contextlib.suppress(Exception):
            await self.peer.call("stop", {}, timeout=5)
        with contextlib.suppress(ProcessLookupError):
            self.proc.kill()
        await self.proc.wait()
        await self._http.aclose()
        shutil.rmtree(self.directory, ignore_errors=True)


PLUGINS: dict[str, PluginProcess] = {}


def _auth(request: Request) -> None:
    if not secrets.compare_digest(request.headers.get("x-sandbox-token", ""), _token()):
        raise PermissionError("invalid sandbox token")


async def start_plugin(request: Request) -> JSONResponse:
    _auth(request)
    body = await request.json()
    plugin_id = str(body["plugin_id"])
    if plugin_id in PLUGINS:
        await PLUGINS.pop(plugin_id).stop()
    directory = WORK / "plugins" / f"{plugin_id}-{uuid.uuid4().hex[:8]}"
    directory.mkdir(parents=True)
    _write_files(directory, body["files"])
    mem = int(body.get("memory_mb", 256))
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-I", "-m", "justai_sandbox.host", str(directory),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=None,
        cwd=str(directory), env=_env(), preexec_fn=_limits(cpu_s=3600, mem_mb=mem + 200))
    plugin = PluginProcess(plugin_id, proc, body["gateway_token"], directory)
    PLUGINS[plugin_id] = plugin
    try:
        result = await plugin.peer.call("start", {"manifest": body["manifest"], "config": body.get("config") or {},
                                                  "permissions": body.get("permissions") or []}, timeout=60)
    except Exception as exc:
        await PLUGINS.pop(plugin_id).stop()
        return JSONResponse({"error": f"plugin start failed: {exc}"}, status_code=500)
    return JSONResponse(result)


async def call_tool(request: Request) -> JSONResponse:
    _auth(request)
    plugin = PLUGINS.get(request.path_params["plugin_id"])
    if plugin is None:
        return JSONResponse({"error": "plugin not running"}, status_code=404)
    body = await request.json()
    try:
        result = await plugin.peer.call("tool", {"name": request.path_params["tool"], "args": body["args"],
                                                 "context": body["context"]},
                                        timeout=float(body.get("timeout_s", 30)))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return JSONResponse(result)


async def stop_plugin(request: Request) -> JSONResponse:
    _auth(request)
    plugin = PLUGINS.pop(request.path_params["plugin_id"], None)
    if plugin:
        await plugin.stop()
    return JSONResponse({"ok": True})


async def plugin_health(request: Request) -> JSONResponse:
    _auth(request)
    plugin = PLUGINS.get(request.path_params["plugin_id"])
    if plugin is None or plugin.proc.returncode is not None:
        return JSONResponse({"state": "failed", "detail": "process not running"})
    try:
        return JSONResponse(await plugin.peer.call("health", {}, timeout=10))
    except Exception as exc:
        return JSONResponse({"state": "failed", "detail": str(exc)})


async def run_tests(request: Request) -> JSONResponse:
    """Run pytest on generated code (no network, rlimits, timeout)."""
    _auth(request)
    body = await request.json()
    timeout = min(float(body.get("timeout_s", 60)), 180)
    directory = WORK / "tests" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    try:
        _write_files(directory, body["files"])
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(directory),
            "-x", str(directory), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            cwd=str(directory), env=_env({"PYTHONPATH": str(directory)}),
            preexec_fn=_limits(cpu_s=int(timeout), mem_mb=512))
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
            code = proc.returncode
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, 9)
            out, code = b"timeout", -1
        return JSONResponse({"ok": code == 0, "exit_code": code,
                             "output": out.decode(errors="replace")[-12000:]})
    finally:
        shutil.rmtree(directory, ignore_errors=True)


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "plugins": sorted(PLUGINS)})


def create_app() -> Starlette:
    async def on_error(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=403 if isinstance(exc, PermissionError) else 500)

    return Starlette(routes=[
        Route("/health", health),
        Route("/tests/run", run_tests, methods=["POST"]),
        Route("/plugins/start", start_plugin, methods=["POST"]),
        Route("/plugins/{plugin_id}/tools/{tool}", call_tool, methods=["POST"]),
        Route("/plugins/{plugin_id}/stop", stop_plugin, methods=["POST"]),
        Route("/plugins/{plugin_id}/health", plugin_health),
    ], exception_handlers={Exception: on_error})


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("SANDBOX_PORT", "8090")),
                log_level="info")


if __name__ == "__main__":
    main()
