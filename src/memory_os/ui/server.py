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
