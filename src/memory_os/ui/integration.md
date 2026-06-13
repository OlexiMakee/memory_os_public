# Memory OS Visualizer: Integration Guide

This guide explains how to embed the Memory OS Visualizer UI and Data Provider into other Python web servers (like FastAPI, Flask, Django) without running a separate background server.

## Architecture
The UI is strictly modular and decoupled:
- **`IGraphDataProvider`**: The core Python interface that accesses the database and safely reads local files.
- **Frontend Assets**: Pure HTML, CSS, and JS (`ui_templates/`) that fetch data from relative API paths (`/api/graph`, `/api/read_file`).

## Example: FastAPI Integration

If you want to serve Memory OS directly inside a FastAPI app on your existing port:

```python
import mimetypes
from pathlib import Path
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse

from memory_os.core.config import get_default_config
from memory_os.ui.data_provider import DefaultGraphDataProvider

app = FastAPI()
config = get_default_config()
provider = DefaultGraphDataProvider(config)

# 1. API: Serve Graph Data
@app.get("/memory/api/graph")
def get_graph():
    return JSONResponse(provider.get_graph_data())

# 2. API: Serve Local Files (Evidence)
@app.get("/memory/api/read_file")
def read_file(path: str):
    content = provider.read_evidence_file(path)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found or access denied")
    
    mime_type, _ = mimetypes.guess_type(path)
    return Response(content=content, media_type=mime_type or "text/plain")

# 3. Static: Serve Frontend Assets
TEMPLATES_DIR = Path("src/memory_os/toolkit/ui_templates")

@app.get("/memory/")
@app.get("/memory/index.html")
def serve_index():
    return FileResponse(TEMPLATES_DIR / "index.html", media_type="text/html")

@app.get("/memory/styles.css")
def serve_css():
    return FileResponse(TEMPLATES_DIR / "styles.css", media_type="text/css")

@app.get("/memory/app.js")
def serve_js():
    return FileResponse(TEMPLATES_DIR / "app.js", media_type="application/javascript")
```

With this, you can visit `http://localhost:8000/memory/` and get the full Memory OS Visualizer securely integrated into your host application.
