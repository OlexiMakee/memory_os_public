import os
import json
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.ui.data_provider import DefaultGraphDataProvider

# Setup mimetypes for UI assets
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('text/html', '.html')

class UIHTTPRequestHandler(BaseHTTPRequestHandler):
    """
    Zero-dependency HTTP handler for Memory OS Visualizer.
    Serves static UI templates and exposes REST API for the graph.
    """
    
    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
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
            
            root_path = str(self.server.provider.config.root_dir)
            script_injection = f'<script>window.WORKSPACE_ROOT = {json.dumps(root_path)};</script>\n</head>'
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
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == '/api/switch_space':
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                post_data = self.rfile.read(content_length)
                payload = json.loads(post_data.decode("utf-8"))
                new_space = payload.get("space", "default")
                
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
            else:
                self.send_error(400, "Missing payload")
            return
        
        self.send_error(404, "Not Found")

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
