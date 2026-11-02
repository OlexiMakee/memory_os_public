import os
import json
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.core.logger import get_logger
from memory_os.core.safe_id import validate_safe_id
from memory_os.ui.data_provider import DefaultGraphDataProvider
from memory_os.toolkit.memory_graph_service import MemoryGraphService

logger = get_logger(__name__)

# Setup mimetypes for UI assets
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('text/html', '.html')

_ALLOWED_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024
LINK_INFER_METHODS = {"cascade", "text", "llm", "both"}
LINK_INFER_RESOURCE_MODES = {"quiet", "normal", "max"}



def _find_federated_spaces(base_dir: Path) -> list:
    federated = []
    ignore_dirs = {".git", "node_modules", "venv", "venv_auto", "__pycache__", ".venv"}
    try:
        search_root = base_dir.parent
        for d1 in search_root.iterdir():
            if d1.is_dir() and d1.name not in ignore_dirs:
                cfg = d1 / "memory_os.config.json"
                if cfg.exists() and d1 != base_dir:
                    federated.append(f"federated:{d1.resolve()}")
                else:
                    try:
                        for d2 in d1.iterdir():
                            if d2.is_dir() and d2.name not in ignore_dirs:
                                cfg2 = d2 / "memory_os.config.json"
                                if cfg2.exists() and d2 != base_dir:
                                    federated.append(f"federated:{d2.resolve()}")
                    except Exception as _e:
                        import sys as _sys
                        print(f'Ignored exception: {_e}', file=_sys.stderr)
    except Exception as _e:
        import sys as _sys
        print(f'Ignored exception: {_e}', file=_sys.stderr)
    return sorted(list(set(federated)))

class UIHTTPRequestHandler(BaseHTTPRequestHandler):
    """
    Zero-dependency HTTP handler for Memory OS Visualizer.
    Serves static UI templates and exposes REST API for the graph.
    """

    def _origin_allowed(self) -> bool:
        """Reject cross-origin browser requests (CSRF/CORS-exfiltration defense).

        Binding to 127.0.0.1 only stops other machines on the network, not
        other browser tabs on this machine. A malicious page open in another
        tab can still fetch() this server. Browsers always set an Origin
        header on cross-origin requests (including form-submit CSRF), so
        rejecting any Origin that isn't this loopback server blocks that
        class of attack without breaking the UI's own same-origin requests
        (same-origin requests often omit Origin entirely) or non-browser
        tools like curl (no Origin header at all).
        """
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = urlparse(origin).hostname
        return host in _ALLOWED_ORIGIN_HOSTS

    def _reject_cross_origin(self) -> bool:
        if not self._origin_allowed():
            self.send_error(403, "Cross-origin requests are not allowed")
            return True
        return False

    def _read_json_body(self) -> dict:
        """Read and parse a POST body, capped to MAX_REQUEST_BODY_BYTES."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length <= 0:
            return {}
        if content_length > MAX_REQUEST_BODY_BYTES:
            raise ValueError(f"request body exceeds {MAX_REQUEST_BODY_BYTES} bytes")
        return json.loads(self.rfile.read(content_length).decode("utf-8"))

    def _send_cors_headers(self):
        # No Access-Control-Allow-Origin header: this UI only needs to be
        # called from pages it itself serves (same-origin), which browsers
        # don't apply CORS to. Cross-origin callers are rejected outright by
        # _reject_cross_origin() before this is ever sent.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _memory_service(self) -> MemoryGraphService:
        return MemoryGraphService(self.server.provider.config)

    def _memory_write_read_only(self) -> bool:
        config = self.server.provider.config
        cwd = Path.cwd().resolve()
        return (
            getattr(config, 'is_federated_ui_mode', False)
            or getattr(self.server.provider, 'is_federated', False)
            or (config.root_dir != cwd and str(config.root_dir) not in str(cwd))
        )

    def _reject_memory_write_if_read_only(self) -> bool:
        if self._memory_write_read_only():
            self.send_error(403, 'Read-only in federated mode')
            return True
        return False

    def _json_not_found_status(self, payload: dict) -> int:
        return 404 if payload.get("status") == "not_found" else 200

    def _handle_memory_write_action(self, action_fn, use_not_found_status: bool = True) -> None:
        """Shared skeleton for the /api/nodes|edges write endpoints: read-only
        guard, payload parse, ValueError->400, JSON response."""
        if self._reject_memory_write_if_read_only():
            return
        payload = self._read_json_body()
        if not payload:
            self.send_error(400, "Missing payload")
            return
        try:
            result = action_fn(payload)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        status = self._json_not_found_status(result) if use_not_found_status else 200
        self._json_response(result, status=status)

    def do_GET(self):
        if self._reject_cross_origin():
            return
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/system/load':
            try:
                from memory_os.core.resource_guard import ResourceGuard
                snap = ResourceGuard().snapshot()
                self._json_response(snap.to_dict())
            except Exception as exc:
                self._json_response({"cpu": 0, "ram": 0, "temp": None,
                                     "level": "unknown", "error": str(exc)})
            return

        # --- API ROUTES ---
        if path == '/api/graph':
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            
            data = self.server.provider.get_graph_data()
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        if path == '/api/memory/health':
            service = self._memory_service()
            self._json_response(service.health())
            return

        if path == '/api/memory/curate':
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", ["10"])[0] or 10)
            service = self._memory_service()
            self._json_response(service.curate(limit=limit))
            return

        if path == '/api/memory/merge-preview':
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", ["10"])[0] or 10)
            service = self._memory_service()
            self._json_response(service.merge_preview(limit=limit))
            return

        if path == '/api/memory/merge-apply':
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", ["10"])[0] or 10)
            dry_run = qs.get("dry_run", ["false"])[0].lower() in {"1", "true", "yes", "on"}
            service = self._memory_service()
            self._json_response(service.merge_apply(limit=limit, dry_run=dry_run))
            return

        if path == '/api/memory/browse':
            qs = parse_qs(parsed.query)
            service = self._memory_service()
            payload = service.browse(
                query=qs.get("query", [""])[0],
                node_id=qs.get("node_id", [None])[0],
                depth=int(qs.get("depth", ["1"])[0] or 1),
                limit=int(qs.get("limit", ["3"])[0] or 3),
                neighbors=int(qs.get("neighbors", ["8"])[0] or 8),
                edges_limit=int(qs.get("edges", ["12"])[0] or 12),
            )
            self._json_response(payload)
            return

        if path == '/api/memory/timeline':
            qs = parse_qs(parsed.query)
            service = self._memory_service()
            self._json_response(service.timeline(
                days=qs.get("days", ["30"])[0],
                node_type=qs.get("type", [""])[0],
                status=qs.get("status", [""])[0],
            ))
            return

        if path == '/api/memory/export':
            service = self._memory_service()
            body = json.dumps(service.export_graph()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Disposition", 'attachment; filename="memory_export.json"')
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        if path == '/api/memory/nodes':
            qs = parse_qs(parsed.query)
            service = self._memory_service()
            self._json_response(service.list_nodes(
                query=qs.get("query", [""])[0],
                node_type=qs.get("type", [""])[0],
                status=qs.get("status", [""])[0],
                trust=qs.get("trust", [""])[0],
                tag=qs.get("tag", [""])[0],
                limit=qs.get("limit", ["100"])[0],
                offset=qs.get("offset", ["0"])[0],
            ))
            return

        if path == '/api/memory/node':
            qs = parse_qs(parsed.query)
            node_id = qs.get("id", [""])[0]
            if not node_id:
                self.send_error(400, "Missing 'id' parameter")
                return
            payload = self._memory_service().get_node(node_id)
            self._json_response(payload, status=self._json_not_found_status(payload))
            return

        if path == '/api/memory/edges':
            qs = parse_qs(parsed.query)
            service = self._memory_service()
            self._json_response(service.list_edges(
                source=qs.get("source", [""])[0],
                target=qs.get("target", [""])[0],
                edge_type=qs.get("type", [""])[0],
                limit=qs.get("limit", ["100"])[0],
                offset=qs.get("offset", ["0"])[0],
            ))
            return

        if path == '/api/memory/events':
            qs = parse_qs(parsed.query)
            service = self._memory_service()
            self._json_response(service.list_events(
                node_id=qs.get("node_id", [""])[0],
                limit=qs.get("limit", ["50"])[0],
            ))
            return
            
        elif path == '/api/spaces':
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            
            memory_dir = self.server.provider.config.root_dir / self.server.provider.config.data.get("memory_dir", "memory")
            spaces = []
            if memory_dir.exists():
                for item in memory_dir.iterdir():
                    if item.is_dir():
                        spaces.append(item.name)
            if "default" not in spaces:
                spaces.append("default")
            
            # Add federated spaces
            try:
                federated = _find_federated_spaces(self.server.provider.config.root_dir)
                spaces.extend(federated)
            except Exception as e:
                print("Federated error:", e)
            
            data = {
                "active": getattr(self.server.provider, 'federated_active_space', self.server.provider.config.space),
                "spaces": sorted(list(set(spaces)))
            }
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return
            
        elif path == '/api/tasks':
            qs = parse_qs(parsed.query)
            status_filter = qs.get('status', [None])[0]
            try:
                from memory_os.toolkit.task_kernel import TaskKernel
                kernel = TaskKernel(self.server.provider.config.root_dir)
                tasks = kernel.list_tasks(status=status_filter)
                tasks_sorted = sorted(tasks, key=lambda t: t.get("updated_at", ""), reverse=True)
            except Exception as exc:
                logger.error("GET /api/tasks failed: %s", exc, exc_info=True)
                self._json_response({"tasks": [], "total": 0, "error": str(exc)}, status=500)
                return
            self._json_response({"tasks": tasks_sorted, "total": len(tasks_sorted)})
            return

        elif path == '/api/read_file':
            qs = parse_qs(parsed.query)
            file_path = qs.get('path', [''])[0]
            
            if not file_path:
                self.send_error(400, "Missing 'path' parameter")
                return
                
            content = self.server.provider.read_evidence_file(file_path)
            if content is None:
                self.send_error(403, "File not found or access denied")
                return
                
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = "text/plain"
                
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(content)
            return

        # --- STATIC ROUTES ---
        templates_dir = Path(__file__).parent.parent / "toolkit" / "ui_templates"
        
        if path == '/' or path == '/index.html':
            target_file = templates_dir / "index.html"
            mime_type = "text/html"
            if not target_file.exists():
                self.send_error(404, f"Template {target_file.name} not found")
                return
            
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self._send_cors_headers()
            self.end_headers()
            
            with open(target_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            cfg = self.server.provider.config
            root_path = str(cfg.root_dir)
            project_name = cfg.data.get("name") or cfg.root_dir.name
            script_injection = (
                f'<script>'
                f'window.WORKSPACE_ROOT = {json.dumps(root_path)};'
                f'window.PROJECT_NAME = {json.dumps(project_name)};'
                f'</script>\n</head>'
            )
            content = content.replace('</head>', script_injection)
            
            self.wfile.write(content.encode('utf-8'))
            return

        elif path == '/styles.css':
            target_file = templates_dir / "styles.css"
            mime_type = "text/css"
        elif path == '/app.js':
            target_file = templates_dir / "app.js"
            mime_type = "application/javascript"
        else:
            self.send_error(404, "Not Found")
            return
            
        if not target_file.exists():
            self.send_error(404, f"Template {target_file.name} not found")
            return
            
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self._send_cors_headers()
        self.end_headers()
        with open(target_file, 'rb') as f:
            self.wfile.write(f.read())

    def do_POST(self):
        if self._reject_cross_origin():
            return
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            if path == '/api/switch_space':
                payload = self._read_json_body()
                if not payload:
                    self.send_error(400, "Missing payload")
                    return
                new_space = payload.get("space", "default")
                
                is_federated = new_space.startswith("federated:")
                
                if not is_federated:
                    try:
                        validate_safe_id(new_space, "space")
                    except ValueError:
                        new_space = "default"

                from memory_os.core.storage import FileSystemMemoryStorage
                from memory_os.core.repository import MemoryRepository
                
                if is_federated:
                    fed_path_str = new_space.split("federated:", 1)[1]
                    fed_path = Path(fed_path_str)
                    if fed_path.exists() and (fed_path / "memory_os.config.json").exists():
                        from memory_os.core.config import MemoryOSConfig
                        fed_config = MemoryOSConfig(fed_path)
                        # Ensure we default to the federated instance's default space
                        fed_config.space = "default"
                        self.server.provider.config = fed_config
                        self.server.provider.repo = MemoryRepository(FileSystemMemoryStorage(), fed_config)
                        self.server.provider.federated_active_space = new_space
                        # Note: We do NOT send a space switch to the daemon because federated is read-only for the UI
                    else:
                        new_space = "default"
                        is_federated = False
                
                if getattr(self.server.provider, 'federated_active_space', None) and not is_federated:
                    delattr(self.server.provider, 'federated_active_space')
                
                if not is_federated:
                    # Validate: non-default spaces must have an existing directory with data
                    if new_space != "default":
                        memory_base = self.server.provider.config.root_dir / self.server.provider.config.data.get("memory_dir", "memory")
                        space_dir = memory_base / new_space
                        if not space_dir.exists() or not (space_dir / "nodes.jsonl").exists():
                            new_space = "default"

                    from memory_os.toolkit.daemon_client import DaemonClient

                    daemon_response = DaemonClient(
                        self.server.provider.config.root_dir,
                        self.server.provider.config.daemon_port,
                        timeout=1,
                    ).request(
                        "/space",
                        method="POST",
                        body={"space": new_space},
                    )
                    if not daemon_response.ok or daemon_response.payload.get("status") != "space_switched":
                        error = daemon_response.payload.get("error") or daemon_response.error or "daemon rejected space switch"
                        status = daemon_response.status_code if 400 <= daemon_response.status_code < 600 else 503
                        self._json_response({"status": "error", "error": error}, status=status)
                        return

                    self.server.provider.config.space = new_space
                    self.server.provider.repo = MemoryRepository(FileSystemMemoryStorage(), self.server.provider.config)

                self._json_response({"status": "ok", "space": new_space})
                return

            elif path == '/api/nodes/verify':
                self._handle_memory_write_action(
                    lambda p: self._memory_service().verify_node(p.get("id", ""))
                )
                return

            elif path == '/api/edges/create':
                def _create_edge(p):
                    p.setdefault("confidence", 1.0)
                    p.setdefault("reason", "Manual link created by user via UI")
                    return self._memory_service().upsert_edge(p)
                self._handle_memory_write_action(_create_edge, use_not_found_status=False)
                return

            elif path == '/api/nodes/merge':
                self._handle_memory_write_action(
                    lambda p: self._memory_service().merge_nodes(p.get("source", ""), p.get("target", ""))
                )
                return

            elif path == '/api/nodes/update':
                self._handle_memory_write_action(
                    lambda p: self._memory_service().update_node(
                        p.get("id", ""),
                        summary=p.get("summary") if "summary" in p else None,
                        tags=p.get("tags") if "tags" in p else None,
                    )
                )
                return

            elif path == '/api/nodes/delete':
                self._handle_memory_write_action(
                    lambda p: self._memory_service().delete_node(p.get("id", ""))
                )
                return

            elif path == '/api/nodes/pin':
                self._handle_memory_write_action(
                    lambda p: self._memory_service().pin_node(p.get("id", ""), bool(p.get("pinned", False)))
                )
                return

            elif path == '/api/nodes/upsert':
                self._handle_memory_write_action(
                    lambda p: self._memory_service().upsert_node(p)
                )
                return

            elif path == '/api/nodes/archive':
                self._handle_memory_write_action(
                    lambda p: self._memory_service().archive_node(p.get("id") or p.get("node_id", ""), p.get("reason", ""))
                )
                return

            elif path == '/api/edges/upsert':
                self._handle_memory_write_action(
                    lambda p: self._memory_service().upsert_edge(p), use_not_found_status=False
                )
                return

            elif path == '/api/edges/delete':
                self._handle_memory_write_action(
                    lambda p: self._memory_service().delete_edge(p.get("source", ""), p.get("target", ""), p.get("type", ""))
                )
                return

            elif path == '/api/link-infer':
                payload = self._read_json_body()
                method        = payload.get("method", "cascade")
                resource_mode = payload.get("resource_mode", "quiet")
                dry_run       = payload.get("dry_run", False)
                if method not in LINK_INFER_METHODS or resource_mode not in LINK_INFER_RESOURCE_MODES:
                    self.send_error(400, "Invalid method or resource_mode")
                    return

                import subprocess, sys as _sys
                root = str(self.server.provider.config.root_dir)
                cmd  = [_sys.executable, "-m", "memory_os", "--root", root,
                        "link-infer", "--method", method, "--resource-mode", resource_mode]
                if dry_run:
                    cmd.append("--dry-run")

                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                    output = (result.stdout + result.stderr).strip()
                    self._json_response({
                        "status": "ok" if result.returncode == 0 else "error",
                        "output": output,
                        "returncode": result.returncode,
                    })
                except subprocess.TimeoutExpired:
                    self._json_response({"status": "timeout",
                                         "output": "Link inference timed out after 180s."})
                except Exception as exc:
                    self._json_response({"status": "error", "output": str(exc)}, status=500)
                return

            self.send_error(404, "Not Found")
        except ValueError as exc:
            self.send_error(413, str(exc))
        except Exception as exc:
            logger.error("POST %s failed: %s", self.path, exc, exc_info=True)
            self.send_error(500, "Internal Server Error")

class MemoryOSServer(HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, provider):
        super().__init__(server_address, RequestHandlerClass)
        self.provider = provider

def run_ui_server(config: MemoryOSConfig, port: int | None = None):
    """Starts the built-in HTTP server for the UI."""
    if port is None:
        port = getattr(config, "ui_port", 8080)
    provider = DefaultGraphDataProvider(config)
    server_address = ('127.0.0.1', port)
    
    try:
        httpd = MemoryOSServer(server_address, UIHTTPRequestHandler, provider)
        print(f"Memory OS Visualizer running at: http://127.0.0.1:{port}/")
        print("Press Ctrl+C to stop.")
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Memory OS Visualizer...")
        httpd.server_close()
