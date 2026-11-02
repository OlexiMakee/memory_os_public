from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import socket
from typing import Any, Dict, Optional
import urllib.error
import urllib.request


@dataclass(frozen=True)
class DaemonResponse:
    ok: bool
    status_code: int
    payload: Dict[str, Any]
    transport: str
    error: str = ""


class DaemonClient:
    def __init__(self, root: Path, port: int, timeout: float = 3.0):
        self.root = root.resolve()
        self.port = int(port)
        self.timeout = float(timeout)
        self.socket_path = self.root / "data" / "memory_os.sock"

    @staticmethod
    def _payload(raw: bytes) -> Dict[str, Any]:
        if not raw:
            return {}
        decoded = json.loads(raw.decode("utf-8"))
        return decoded if isinstance(decoded, dict) else {"data": decoded}

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: Optional[Dict[str, Any]] = None,
    ) -> DaemonResponse:
        unix_response = self._request_unix(path, method=method, body=body)
        if unix_response is not None:
            return unix_response
        return self._request_tcp(path, method=method, body=body)

    def _request_unix(
        self,
        path: str,
        *,
        method: str,
        body: Optional[Dict[str, Any]],
    ) -> Optional[DaemonResponse]:
        if not hasattr(socket, "AF_UNIX") or not self.socket_path.exists():
            return None
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.settimeout(self.timeout)
            client.connect(str(self.socket_path))
            body_bytes = json.dumps(body).encode("utf-8") if body is not None else b""
            headers = [f"{method} {path} HTTP/1.1", "Host: localhost", "Connection: close"]
            if body_bytes:
                headers.extend([
                    f"Content-Length: {len(body_bytes)}",
                    "Content-Type: application/json",
                ])
            client.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("utf-8") + body_bytes)
            response = bytearray()
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response.extend(chunk)
        except OSError:
            return None
        finally:
            client.close()

        header, separator, raw_body = bytes(response).partition(b"\r\n\r\n")
        if not separator:
            return None
        try:
            status_code = int(header.splitlines()[0].split()[1])
            payload = self._payload(raw_body)
        except (IndexError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return DaemonResponse(False, 0, {}, "unix", "malformed daemon response")
        ok = 200 <= status_code < 300
        return DaemonResponse(ok, status_code, payload, "unix", "" if ok else str(payload.get("error", "")))

    def _request_tcp(
        self,
        path: str,
        *,
        method: str,
        body: Optional[Dict[str, Any]],
    ) -> DaemonResponse:
        url = f"http://127.0.0.1:{self.port}{path}"
        body_bytes = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url,
            data=body_bytes,
            headers={"Content-Type": "application/json"} if body_bytes is not None else {},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = self._payload(response.read())
                status_code = int(response.status)
                return DaemonResponse(200 <= status_code < 300, status_code, payload, "tcp")
        except urllib.error.HTTPError as exc:
            try:
                payload = self._payload(exc.read())
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = {}
            return DaemonResponse(False, int(exc.code), payload, "tcp", str(payload.get("error", exc.reason)))
        except (OSError, urllib.error.URLError) as exc:
            return DaemonResponse(False, 0, {}, "tcp", str(exc))
