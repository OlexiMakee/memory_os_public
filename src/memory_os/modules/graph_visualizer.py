from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.memory_graph_service import MemoryGraphService

NODE_TYPE_COLORS: Dict[str, str] = {
    "fact": "#3B82F6",
    "decision": "#8B5CF6",
    "task": "#F59E0B",
    "spec": "#10B981",
    "rule": "#EF4444",
    "policy": "#EC4899",
    "config": "#6366F1",
    "variable": "#06B6D4",
    "file": "#64748B",
    "class": "#0284C7",
    "function": "#0D9488",
    "module": "#4F46E5",
    "module_cluster": "#7C3AED",
}

EDGE_TYPE_COLORS: Dict[str, str] = {
    "relates_to": "#9CA3AF",
    "implements": "#10B981",
    "fixes": "#EF4444",
    "fixed_by": "#EF4444",
    "supersedes": "#F59E0B",
    "depends_on": "#3B82F6",
    "triggers": "#8B5CF6",
    "refutes": "#DC2626",
    "overrides": "#D97706",
    "configures": "#6366F1",
    "secures": "#059669",
    "contains": "#475569",
    "reads_from": "#0284C7",
    "writes_to": "#D97706",
    "caused_by": "#E11D48",
    "strategic_consequence": "#7C3AED",
    "co_tagged": "#64748B",
    "co_created": "#94A3B8",
}

DEFAULT_NODE_COLOR = "#6B7280"
DEFAULT_EDGE_COLOR = "#9CA3AF"


class GraphVisualizer:
    """Generates interactive standalone HTML graph visualizations for Memory OS."""

    def __init__(self, config: Optional[MemoryOSConfig] = None) -> None:
        self.config = config or MemoryOSConfig()
        self.service = MemoryGraphService(self.config)

    def _get_node_color(self, node_type: str) -> str:
        return NODE_TYPE_COLORS.get(node_type.lower(), DEFAULT_NODE_COLOR)

    def _get_edge_color(self, edge_type: str) -> str:
        return EDGE_TYPE_COLORS.get(edge_type.lower(), DEFAULT_EDGE_COLOR)

    def generate_html(self, output_path: Optional[Path] = None) -> Path:
        if output_path is None:
            output_path = self.config.memory_dir / "graph.html"
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        graph_data = self.service.export_graph()
        raw_nodes = graph_data.get("nodes", [])
        raw_edges = graph_data.get("edges", [])

        vis_nodes: List[Dict[str, Any]] = []
        for n in raw_nodes:
            nid = str(n.get("id", ""))
            ntype = str(n.get("type", "unknown"))
            summary = str(n.get("summary", nid))
            label = summary if len(summary) <= 30 else summary[:27] + "..."
            color = self._get_node_color(ntype)

            tooltip = (
                f"<b>ID:</b> {nid}<br/>"
                f"<b>Type:</b> {ntype}<br/>"
                f"<b>Status:</b> {n.get('status', 'n/a')}<br/>"
                f"<b>Trust:</b> {n.get('trust', 'n/a')}<br/>"
                f"<b>Summary:</b> {summary}"
            )

            vis_nodes.append(
                {
                    "id": nid,
                    "label": label,
                    "title": tooltip,
                    "group": ntype,
                    "color": {
                        "background": color,
                        "border": color,
                        "highlight": {"background": color, "border": "#FFFFFF"},
                    },
                    "font": {"color": "#FFFFFF"},
                    "shape": "dot",
                    "size": 16,
                }
            )

        vis_edges: List[Dict[str, Any]] = []
        for i, e in enumerate(raw_edges):
            src = str(e.get("source") or e.get("from", ""))
            tgt = str(e.get("target") or e.get("to", ""))
            etype = str(e.get("type", "relates_to"))
            color = self._get_edge_color(etype)

            vis_edges.append(
                {
                    "id": f"e_{i}",
                    "from": src,
                    "to": tgt,
                    "label": etype,
                    "title": f"<b>Relation:</b> {etype}<br/><b>Confidence:</b> {e.get('confidence', 1.0)}",
                    "color": {"color": color, "highlight": "#FFFFFF"},
                    "arrows": "to",
                    "font": {"color": "#9CA3AF", "size": 10, "align": "middle"},
                }
            )

        html_content = self._build_html(vis_nodes, vis_edges)
        output_path.write_text(html_content, encoding="utf-8")
        return output_path

    def _build_html(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> str:
        nodes_json = json.dumps(nodes, ensure_ascii=False)
        edges_json = json.dumps(edges, ensure_ascii=False)
        node_colors_json = json.dumps(NODE_TYPE_COLORS, ensure_ascii=False)
        edge_colors_json = json.dumps(EDGE_TYPE_COLORS, ensure_ascii=False)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Memory OS - Visual Graph Explorer</title>
    <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: #0f172a;
            color: #f8fafc;
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }}
        header {{
            background-color: #1e293b;
            padding: 12px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid #334155;
        }}
        h1 {{ font-size: 1.25rem; font-weight: 600; color: #38bdf8; }}
        .stats {{ font-size: 0.875rem; color: #94a3b8; }}
        #container {{ display: flex; flex: 1; height: calc(100vh - 57px); }}
        #network {{ flex: 1; height: 100%; background-color: #0f172a; }}
        #sidebar {{
            width: 320px;
            background-color: #1e293b;
            border-left: 1px solid #334155;
            padding: 16px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }}
        .section-title {{ font-size: 0.875rem; font-weight: 600; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.05em; margin-bottom: 8px; }}
        .legend-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
        .legend-item {{ display: flex; align-items: center; gap: 8px; font-size: 0.8125rem; color: #cbd5e1; }}
        .color-box {{ width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0; }}
        .search-box {{ width: 100%; padding: 8px 12px; background-color: #0f172a; border: 1px solid #334155; border-radius: 6px; color: #f8fafc; font-size: 0.875rem; }}
        .search-box:focus {{ outline: none; border-color: #38bdf8; }}
    </style>
</head>
<body>
    <header>
        <h1>Memory OS Graph Explorer</h1>
        <div class="stats">Nodes: {len(nodes)} | Edges: {len(edges)}</div>
    </header>
    <div id="container">
        <div id="network"></div>
        <div id="sidebar">
            <div>
                <div class="section-title">Search</div>
                <input type="text" id="searchInput" class="search-box" placeholder="Filter nodes..." oninput="filterNodes()">
            </div>
            <div>
                <div class="section-title">Node Types</div>
                <div class="legend-grid" id="nodeLegend"></div>
            </div>
            <div>
                <div class="section-title">Relation Types</div>
                <div class="legend-grid" id="edgeLegend"></div>
            </div>
        </div>
    </div>
    <script type="text/javascript">
        const rawNodes = {nodes_json};
        const rawEdges = {edges_json};
        const nodeColors = {node_colors_json};
        const edgeColors = {edge_colors_json};

        const container = document.getElementById('network');
        const data = {{
            nodes: new vis.DataSet(rawNodes),
            edges: new vis.DataSet(rawEdges)
        }};
        const options = {{
            nodes: {{
                shape: 'dot',
                size: 16,
                font: {{ size: 12, color: '#f8fafc' }}
            }},
            edges: {{
                width: 1.5,
                smooth: {{ type: 'continuous' }}
            }},
            physics: {{
                barnesHut: {{ gravitationalConstant: -3000, centralGravity: 0.3, springLength: 95 }}
            }},
            interaction: {{ hover: true, tooltipDelay: 200 }}
        }};

        const network = new vis.Network(container, data, options);

        function populateLegend() {{
            const nodeLegend = document.getElementById('nodeLegend');
            Object.entries(nodeColors).forEach(([type, color]) => {{
                const item = document.createElement('div');
                item.className = 'legend-item';
                item.innerHTML = `<span class="color-box" style="background-color: ${{color}}"></span>${{type}}`;
                nodeLegend.appendChild(item);
            }});

            const edgeLegend = document.getElementById('edgeLegend');
            Object.entries(edgeColors).forEach(([type, color]) => {{
                const item = document.createElement('div');
                item.className = 'legend-item';
                item.innerHTML = `<span class="color-box" style="background-color: ${{color}}"></span>${{type}}`;
                edgeLegend.appendChild(item);
            }});
        }}

        function filterNodes() {{
            const query = document.getElementById('searchInput').value.toLowerCase();
            if (!query) {{
                data.nodes.update(rawNodes);
                return;
            }}
            const updated = rawNodes.map(n => ({{
                id: n.id,
                hidden: !((n.label && n.label.toLowerCase().includes(query)) || (n.id && n.id.toLowerCase().includes(query)))
            }}));
            data.nodes.update(updated);
        }}

        populateLegend();
    </script>
</body>
</html>
"""
