import os
import json
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.core.safe_id import validate_safe_id
from memory_os.ui.data_provider import DefaultGraphDataProvider

# Setup mimetypes for UI assets
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('text/html', '.html')

_ALLOWED_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024
LINK_INFER_METHODS = {"cascade", "text", "llm", "both"}
LINK_INFER_RESOURCE_MODES = {"quiet", "normal", "max"}


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
            
            data = {
                "active": self.server.provider.config.space,
                "spaces": sorted(list(set(spaces)))
            }
            self.wfile.write(json.dumps(data).encode("utf-8"))
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
                try:
                    validate_safe_id(new_space, "space")
                except ValueError:
                    new_space = "default"

                # Validate: non-default spaces must have an existing directory with data
                if new_space != "default":
                    memory_base = self.server.provider.config.root_dir / self.server.provider.config.data.get("memory_dir", "memory")
                    space_dir = memory_base / new_space
                    if not space_dir.exists() or not (space_dir / "nodes.jsonl").exists():
                        new_space = "default"

                self.server.provider.config.space = new_space
                from memory_os.core.storage import FileSystemMemoryStorage
                from memory_os.core.repository import MemoryRepository
                self.server.provider.repo = MemoryRepository(FileSystemMemoryStorage(), self.server.provider.config)

                import urllib.request
                url = f"http://127.0.0.1:{self.server.provider.config.daemon_port}/space"
                req = urllib.request.Request(
                    url,
                    data=json.dumps({"space": new_space}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                try:
                    with urllib.request.urlopen(req, timeout=1):
                        pass
                except Exception:
                    pass

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "space": new_space}).encode("utf-8"))
                return

            elif path == '/api/nodes/verify':
                payload = self._read_json_body()
                if not payload:
                    self.send_error(400, "Missing payload")
                    return
                node_id = payload.get("id")
                repo = self.server.provider.repo
                nodes = repo.get_nodes()
                for n in nodes:
                    if n.id == node_id:
                        n.trust = "verified"
                        n.protocol_level = 99
                        break
                repo.save_nodes(nodes)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
                return

            elif path == '/api/edges/create':
                payload = self._read_json_body()
                if not payload:
                    self.send_error(400, "Missing payload")
                    return
                from memory_os.core.models import MemoryEdge
                edge = MemoryEdge(
                    source=payload.get("source"),
                    target=payload.get("target"),
                    type=payload.get("type", "depends_on"),
                    confidence=1.0,
                    reason="Manual link created by user via UI"
                )
                repo = self.server.provider.repo
                repo.add_edge(edge)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
                return

            elif path == '/api/nodes/merge':
                payload = self._read_json_body()
                if not payload:
                    self.send_error(400, "Missing payload")
                    return
                source_id = payload.get("source") # node to delete
                target_id = payload.get("target") # node to keep
                repo = self.server.provider.repo
                
                nodes = repo.get_nodes()
                edges = repo.get_edges()
                
                source_node = next((n for n in nodes if n.id == source_id), None)
                target_node = next((n for n in nodes if n.id == target_id), None)
                
                if source_node and target_node:
                    target_node.evidence = list(set(target_node.evidence + source_node.evidence))
                    target_node.tags = list(set(target_node.tags + source_node.tags))
                    if source_node.summary not in target_node.summary:
                        target_node.summary += " | Merged from: " + source_node.summary
                        
                # Delete source node
                new_nodes = [n for n in nodes if n.id != source_id]
                
                # Reroute edges
                new_edges = []
                for e in edges:
                    if e.source == source_id:
                        e.source = target_id
                    if e.target == source_id:
                        e.target = target_id
                    
                    if e.source != e.target:
                        new_edges.append(e)
                
                # Remove duplicate edges
                unique_edges = []
                seen = set()
                for e in new_edges:
                    key = (e.source, e.target, e.type)
                    if key not in seen:
                        seen.add(key)
                        unique_edges.append(e)
                        
                repo.save_nodes(new_nodes)
                repo.save_edges(unique_edges)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
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
        except Exception:
            self.send_error(500, "Internal Server Error")

class MemoryOSServer(HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, provider):
        super().__init__(server_address, RequestHandlerClass)
        self.provider = provider

def run_ui_server(config: MemoryOSConfig, port: int = 8080):
    """Starts the built-in HTTP server for the UI."""
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
