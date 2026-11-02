import json
import os
import http.server
import threading
from urllib.parse import urlparse, parse_qs

_ALLOWED_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024

class DaemonHttpHandler(http.server.BaseHTTPRequestHandler):
    # Socket-level timeout (seconds): without this, a client that opens a
    # connection, sends a Content-Length header, then never sends the body
    # blocks this single-threaded server's only thread forever (SEC-03).
    timeout = 30

    def log_message(self, format, *args):
        pass

    def _origin_allowed(self) -> bool:
        """Reject cross-origin browser requests (CSRF/CORS-exfiltration defense).

        Binding to 127.0.0.1 only stops other machines on the network, not
        other browser tabs on this machine — any malicious page open in
        another tab can otherwise fetch() /status (leaking local paths and
        the OS username) or POST /stop (killing the daemon) with zero
        authentication. Browsers always set Origin on cross-origin requests
        (including CSRF form submits), so rejecting any mismatched Origin
        blocks that without breaking the daemon's own same-origin/non-browser
        callers (the CLI uses urllib, which sends no Origin header at all).
        """
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = urlparse(origin).hostname
        return host in _ALLOWED_ORIGIN_HOSTS

    def _read_json_body(self) -> dict:
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length <= 0:
            return {}
        if content_length > MAX_REQUEST_BODY_BYTES:
            raise ValueError(f"request body exceeds {MAX_REQUEST_BODY_BYTES} bytes")
        return json.loads(self.rfile.read(content_length).decode("utf-8"))

    def do_GET(self):
        if not self._origin_allowed():
            self.send_response(403)
            self.end_headers()
            return
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/status":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                status_data = self.server.daemon.get_status_dict()
                self.wfile.write(json.dumps(status_data).encode("utf-8"))
            elif parsed.path == "/auditors/status":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()

                status_data = self.server.daemon.auditor_manager.get_status()

                try:
                    load1, load5, load15 = os.getloadavg()
                    cpu_percent = min(100.0, (load1 / os.cpu_count()) * 100)
                except Exception:
                    cpu_percent = 0.0

                resp = {
                    "auditors": status_data,
                    "metrics": {
                        "cpu_percent": round(cpu_percent, 1),
                        "ram_percent": 45.0
                    }
                }
                self.wfile.write(json.dumps(resp).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()
        except Exception:
            self.send_response(500)
            self.end_headers()

    def do_POST(self):
        if not self._origin_allowed():
            self.send_response(403)
            self.end_headers()
            return
        try:
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            name = qs.get("name", [""])[0]

            if parsed.path not in ("/sync", "/stop", "/auditors/start", "/auditors/pause", "/auditors/stop", "/space"):
                self.send_response(404)
                self.end_headers()
                return

            response_status = 200
            response_body: dict = {}
            if parsed.path == "/sync":
                self.server.daemon.logger.info("IPC request: Triggering manual sync")
                self.server.daemon.check_file(force=True)
                response_body = {"status": "sync_triggered"}
            elif parsed.path == "/stop":
                self.server.daemon.logger.info("IPC request: Shutting down daemon")
                self.server.daemon.is_running = False
                response_body = {"status": "stopping"}
            elif parsed.path == "/auditors/start":
                self.server.daemon.auditor_manager.start_auditor(name)
                response_body = {"status": "ok"}
            elif parsed.path == "/auditors/pause":
                self.server.daemon.auditor_manager.pause_auditor(name)
                response_body = {"status": "ok"}
            elif parsed.path == "/auditors/stop":
                self.server.daemon.auditor_manager.stop_auditor(name)
                response_body = {"status": "ok"}
            elif parsed.path == "/space":
                payload = self._read_json_body()
                if not payload or "space" not in payload:
                    response_status = 400
                    response_body = {"error": "Missing payload"}
                else:
                    new_space = payload.get("space", "default")
                    self.server.daemon.logger.info(f"IPC request: Switching space to '{new_space}'")
                    if self.server.daemon.switch_space(new_space):
                        response_body = {
                            "status": "space_switched",
                            "space": self.server.daemon.config.space,
                        }
                    else:
                        response_status = 400
                        response_body = {"error": "invalid space"}

            self.send_response(response_status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_body).encode("utf-8"))
        except Exception:
            self.server.daemon.logger.error("IPC request failed", exc_info=True)
            try:
                self.wfile.write(json.dumps({"error": "internal error"}).encode("utf-8"))
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()


class DaemonIPCServer:
    def __init__(self, daemon):
        self.daemon = daemon
        self.http_server = None
        self.ipc_thread = None
        self.unix_server = None
        self.unix_ipc_thread = None

    def start(self):
        port = self.daemon.config.daemon_port
        server_address = ("127.0.0.1", port)

        class CustomHttpServer(http.server.HTTPServer):
            def __init__(self, addr, handler, daemon):
                self.daemon = daemon
                super().__init__(addr, handler)

        try:
            self.http_server = CustomHttpServer(server_address, DaemonHttpHandler, self.daemon)
            self.daemon.logger.info(f"IPC Server listening on http://127.0.0.1:{port}")
            self.ipc_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
            self.ipc_thread.start()
        except Exception as e:
            self.daemon.logger.critical(f"Failed to start IPC Server (is another daemon already running?): {e}")
            self.http_server = None
            self.daemon.is_running = False
            return

        import socket
        if hasattr(socket, "AF_UNIX"):
            import socketserver
            socket_path = self.daemon.socket_path
            try:
                if os.path.exists(socket_path):
                    try:
                        os.unlink(socket_path)
                    except OSError:
                        pass
                class CustomUnixHttpServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
                    daemon_threads = True
                    def __init__(self, addr, handler, daemon):
                        self.daemon = daemon
                        super().__init__(addr, handler)

                self.unix_server = CustomUnixHttpServer(socket_path, DaemonHttpHandler, self.daemon)
                self.daemon.logger.info(f"Unix IPC Server listening on {socket_path}")
                self.unix_ipc_thread = threading.Thread(target=self.unix_server.serve_forever, daemon=True)
                self.unix_ipc_thread.start()
            except Exception as e:
                self.daemon.logger.warning(f"Failed to start Unix IPC Server at {socket_path}: {e}")
                self.unix_server = None

    def stop(self):
        if self.unix_server:
            self.daemon.logger.info("Stopping Unix IPC Server...")
            try:
                self.unix_server.shutdown()
                self.unix_server.server_close()
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)
            if self.unix_ipc_thread and self.unix_ipc_thread.is_alive():
                self.unix_ipc_thread.join(timeout=2.0)
            if os.path.exists(self.daemon.socket_path):
                try:
                    os.unlink(self.daemon.socket_path)
                except OSError:
                    pass
        if self.http_server:
            self.daemon.logger.info("Stopping IPC Server...")
            self.http_server.shutdown()
            self.http_server.server_close()
            if self.ipc_thread and self.ipc_thread.is_alive():
                self.ipc_thread.join(timeout=2.0)
