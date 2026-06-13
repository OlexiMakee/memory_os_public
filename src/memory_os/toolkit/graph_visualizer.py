import json
from pathlib import Path
from memory_os import MemoryOSConfig
from memory_os.core.logger import get_logger

logger = get_logger(__name__)

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Memory OS - Premium 3D Graph Visualization</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/3d-force-graph"></script>
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    :root {
      --bg-main: #0b0f19;
      --bg-panel: rgba(15, 23, 42, 0.75);
      --border-panel: rgba(255, 255, 255, 0.08);
      --text-main: #cbd5e1;
      --text-header: #f8fafc;
      --text-muted: #64748b;
      --accent-blue: #3b82f6;
      --accent-green: #10b981;
    }
    
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background-color: var(--bg-main);
      font-family: 'Inter', sans-serif;
      color: var(--text-main);
      overflow: hidden;
      height: 100vh;
      width: 100vw;
    }
    
    #3d-graph { width: 100vw; height: 100vh; }
    
    /* Scrollbars */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.1); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.2); }
    
    /* Glassmorphic Sidebars */
    .glass-panel {
      position: absolute;
      background: var(--bg-panel);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid var(--border-panel);
      border-radius: 16px;
      z-index: 10;
      box-shadow: 0 20px 40px -15px rgba(0, 0, 0, 0.8);
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    
    #left-panel {
      position: relative;
      width: 340px;
      flex: 1;
      min-height: 0;
      padding: 24px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 20px;
      pointer-events: auto;
    }
    
    #right-panel {
      position: relative;
      width: 420px;
      flex: 1;
      min-height: 0;
      padding: 28px;
      overflow-y: auto;
      transform: translateX(460px); /* initially hidden */
      display: flex;
      flex-direction: column;
      gap: 20px;
      pointer-events: auto;
    }
    
    #right-panel.active {
      transform: translateX(0);
    }
    
    #legend-panel {
      padding: 12px 16px;
      min-width: 180px;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      max-height: 44px;
      overflow: hidden;
    }
    
    #legend-panel:hover {
      max-height: 240px;
    }
    
    #legend-panel #legend-items {
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.2s ease;
      margin-top: 4px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    
    #legend-panel:hover #legend-items {
      opacity: 1;
      pointer-events: auto;
    }
    
    #legend-panel #legend-chevron {
      transform: rotate(0deg);
      transition: transform 0.3s ease;
      font-size: 10px;
    }
    
    #legend-panel:hover #legend-chevron {
      transform: rotate(180deg);
    }
    
    #controls-panel {
      padding: 12px 16px;
      display: flex;
      align-items: center;
      gap: 12px;
      height: 44px;
    }
    
    /* Header typography */
    h1 {
      margin: 0;
      font-size: 22px;
      font-weight: 800;
      color: var(--text-header);
      background: linear-gradient(135deg, #60a5fa 0%, #3b82f6 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      letter-spacing: -0.025em;
    }
    
    h2 {
      margin: 0;
      font-size: 14px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-header);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    
    p.subtitle {
      margin: 4px 0 0 0;
      font-size: 13px;
      color: var(--text-muted);
      line-height: 1.4;
    }
    
    /* Search Box */
    .search-container {
      position: relative;
      width: 100%;
    }
    
    .search-container i {
      position: absolute;
      left: 12px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      font-size: 14px;
    }
    
    .search-input {
      width: 100%;
      background: rgba(0, 0, 0, 0.3);
      border: 1px solid var(--border-panel);
      border-radius: 8px;
      padding: 10px 12px 10px 36px;
      color: var(--text-header);
      font-size: 13px;
      outline: none;
      transition: border-color 0.2s;
    }
    
    .search-input:focus {
      border-color: var(--accent-blue);
    }
    
    /* Metrics grid */
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
    }
    
    .metric-card {
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid rgba(255, 255, 255, 0.04);
      border-radius: 10px;
      padding: 12px 8px;
      text-align: center;
    }
    
    .metric-value {
      font-size: 18px;
      font-weight: 800;
      color: var(--text-header);
    }
    
    .metric-label {
      font-size: 10px;
      text-transform: uppercase;
      font-weight: 600;
      color: var(--text-muted);
      margin-top: 4px;
    }
    
    /* Badges */
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 4px 8px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      gap: 6px;
    }
    
    /* Type Colors / Legend items */
    .legend-item {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
    }
    
    .color-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
    }
    
    /* Selector / Dropdown */
    select.dropdown {
      background: rgba(15, 23, 42, 0.9);
      border: 1px solid var(--border-panel);
      border-radius: 8px;
      color: var(--text-header);
      padding: 6px 12px;
      font-size: 12px;
      outline: none;
      cursor: pointer;
    }
    
    /* List items */
    .list-container {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    
    .list-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 12px;
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid rgba(255, 255, 255, 0.03);
      border-radius: 8px;
      font-size: 12px;
      cursor: pointer;
      transition: background 0.2s;
    }
    
    .list-item:hover {
      background: rgba(255, 255, 255, 0.06);
    }
    
    .list-item-title {
      font-weight: 600;
      color: var(--text-header);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 160px;
    }
    
    .list-item-value {
      font-weight: 700;
      color: var(--text-muted);
    }
    
    /* Close button */
    .close-btn {
      position: absolute;
      top: 24px;
      right: 24px;
      background: none;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      font-size: 18px;
      padding: 4px;
      transition: color 0.2s;
    }
    
    .close-btn:hover { color: var(--text-header); }
    
    /* Markdown summary rendering in right panel */
    .node-content-body {
      font-size: 13.5px;
      line-height: 1.6;
      color: var(--text-main);
      background: rgba(0, 0, 0, 0.2);
      border-radius: 12px;
      padding: 16px;
      border: 1px solid rgba(255, 255, 255, 0.03);
      overflow-y: auto;
      max-height: 400px;
    }
    
    .node-content-body h1, .node-content-body h2, .node-content-body h3 {
      color: var(--text-header);
      margin-top: 16px;
      margin-bottom: 8px;
      font-weight: 700;
    }
    
    .node-content-body h1 { font-size: 18px; }
    .node-content-body h2 { font-size: 15px; }
    .node-content-body h3 { font-size: 13.5px; }
    .node-content-body p { margin: 8px 0; }
    .node-content-body ul, .node-content-body ol { padding-left: 20px; margin: 8px 0; }
    .node-content-body li { margin: 4px 0; }
    .node-content-body a { color: #60a5fa; text-decoration: none; border-bottom: 1px dashed rgba(96, 165, 250, 0.4); }
    .node-content-body a:hover { color: #93c5fd; border-bottom-style: solid; }
    
    /* Related Node buttons */
    .tag-btn {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid rgba(255, 255, 255, 0.05);
      color: var(--text-main);
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }
    .tag-btn:hover {
      background: var(--accent-blue);
      color: white;
      border-color: var(--accent-blue);
    }
    
    /* Hover tooltip style overriding 3D Graph default */
    .graph-tooltip {
      background: rgba(15, 23, 42, 0.95) !important;
      border: 1px solid rgba(255, 255, 255, 0.15) !important;
      border-radius: 12px !important;
      padding: 16px !important;
      color: #f1f5f9 !important;
      font-family: 'Inter', sans-serif !important;
      font-size: 12.5px !important;
      max-width: 320px !important;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.6) !important;
    }
    
    .graph-tooltip strong {
      font-size: 14px;
      color: #fff;
    }
    
    .graph-tooltip .tooltip-meta {
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      color: var(--text-muted);
      margin: 4px 0 8px 0;
    }
  </style>
</head>
<body>
  <div id="3d-graph"></div>
  
  <!-- LEFT COLUMN -->
  <div style="position: absolute; top: 20px; left: 20px; bottom: 20px; display: flex; flex-direction: column; gap: 12px; pointer-events: none; z-index: 10;">
    <!-- LEFT SIDEBAR -->
    <div id="left-panel" class="glass-panel">
    <div>
      <h1>Memory OS</h1>
      <p class="subtitle">Interactive Knowledge Graph Visualizer</p>
    </div>
    
    <div class="search-container">
      <i class="fa-solid fa-magnifying-glass"></i>
      <input type="text" id="search-input" class="search-input" placeholder="Search nodes, tags or text...">
    </div>
    
    <div class="metrics-grid">
      <div class="metric-card">
        <div id="node-count" class="metric-value">0</div>
        <div class="metric-label">Nodes</div>
      </div>
      <div class="metric-card">
        <div id="edge-count" class="metric-value">0</div>
        <div class="metric-label">Links</div>
      </div>
      <div class="metric-card">
        <div id="unlinked-count" class="metric-value">0</div>
        <div class="metric-label">Isolated</div>
      </div>
    </div>
    
    <div>
      <h2><i class="fa-solid fa-chart-pie"></i> Type Breakdown</h2>
      <div id="type-breakdown-list" class="list-container" style="margin-top: 10px;">
        <!-- Filled dynamically -->
      </div>
    </div>
    
    <div style="display: flex; flex-direction: column; flex-grow: 1; min-height: 0; padding-bottom: 20px;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
        <h2 id="top-connected-title" style="cursor: pointer; margin: 0;" onclick="cycleConnectionFilter()"><i class="fa-solid fa-arrow-trend-up"></i> Top Connected</h2>
        <div style="display: flex; gap: 6px; align-items: center;">
          <input type="text" id="list-limit-input" value="20" style="width: 40px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); color: var(--text-main); border-radius: 4px; padding: 2px 4px; font-size: 11px; text-align: center;">
          <button onclick="document.getElementById('list-limit-input').value = 'all'; updateStatsAndPanel();" style="background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.1); color: var(--text-main); border-radius: 4px; padding: 2px 8px; font-size: 11px; cursor: pointer; transition: background 0.2s;">All</button>
        </div>
      </div>
      <div id="top-connected-list" class="list-container" style="overflow-y: auto; max-height: 35vh; padding-right: 4px;">
        <!-- Filled dynamically -->
      </div>
    </div>
    </div>
    
    <!-- BOTTOM CONTROLS (Selector & Legend side-by-side) -->
    <div style="display: flex; gap: 12px; align-items: flex-end; pointer-events: none; flex-shrink: 0;">
      <!-- COLOR SCHEME SELECTOR -->
      <div id="controls-panel" class="glass-panel" style="position: static; margin: 0; pointer-events: auto;">
        <span class="metric-label" style="margin: 0; font-size: 11px;">Color Scheme:</span>
        <select id="color-mode-select" class="dropdown">
          <option value="degree" selected>Connection Density</option>
          <option value="type">Node Type</option>
          <option value="status">Status</option>
          <option value="trust">Trust Level</option>
        </select>
      </div>
      
      <!-- LEGEND PANEL -->
      <div id="legend-panel" class="glass-panel" style="position: static; margin: 0; pointer-events: auto;">
        <h2 style="font-size: 11px; margin: 0; cursor: pointer; display: flex; align-items: center; justify-content: space-between; width: 100%;">
          <span><i class="fa-solid fa-circle-info"></i> Legend</span>
          <i class="fa-solid fa-chevron-up" id="legend-chevron"></i>
        </h2>
        <div id="legend-items">
          <!-- Filled dynamically -->
        </div>
      </div>
    </div>
  </div>
  
  <!-- RIGHT COLUMN -->
  <div style="position: absolute; top: 20px; right: 20px; bottom: 20px; display: flex; flex-direction: column; gap: 12px; pointer-events: none; z-index: 10; align-items: flex-end;">
    <!-- RIGHT SIDEBAR (DETAILS DRAWER) -->
    <div id="right-panel" class="glass-panel">
      <button class="close-btn" onclick="closeDrawer()"><i class="fa-solid fa-xmark"></i></button>
      
      <div>
        <div id="node-type-badge" class="badge">Fact</div>
        <h2 id="node-detail-id" style="font-size: 20px; margin-top: 10px; word-break: break-all;">node.id</h2>
      </div>
      
      <!-- Meta badges (Status, Trust, Freshness) -->
      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <div id="node-status-badge" class="badge" style="background: rgba(255, 255, 255, 0.05);">Status</div>
        <div id="node-trust-badge" class="badge" style="background: rgba(255, 255, 255, 0.05);">Trust</div>
        <div id="node-freshness-badge" class="badge" style="background: rgba(255, 255, 255, 0.05); text-transform: none;"><i class="fa-solid fa-calendar"></i> Date</div>
      </div>
      
      <div>
        <h2><i class="fa-solid fa-tags"></i> Tags</h2>
        <div id="node-tags-list" style="display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px;">
          <!-- Filled dynamically -->
        </div>
      </div>
      
      <div>
        <h2><i class="fa-solid fa-file-lines"></i> Content Summary</h2>
        <div id="node-content-render" class="node-content-body" style="margin-top: 8px;">
          <!-- Markdown rendered here -->
        </div>
      </div>
      
      <div>
        <h2><i class="fa-solid fa-link"></i> Evidence Links</h2>
        <div id="node-evidence-list" class="list-container" style="margin-top: 8px;">
          <!-- Filled dynamically -->
        </div>
      </div>
      
      <div>
        <h2><i class="fa-solid fa-share-nodes"></i> Connections</h2>
        <div id="node-connections-list" style="display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px;">
          <!-- Filled dynamically -->
        </div>
      </div>
    </div>

    <!-- AUDITORS PANEL -->
    <div id="auditors-panel" class="glass-panel" style="position: relative; width: 100%; box-sizing: border-box; padding: 20px; font-size: 11px; display: flex; flex-direction: column; gap: 8px; pointer-events: auto; flex: 0 0 auto; max-height: 50vh; overflow-y: auto; margin-top: auto;">
      <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-panel); padding-bottom: 4px;">
        <h2 style="margin: 0; font-size: 12px;"><i class="fa-solid fa-microchip"></i> Hardware Metrics</h2>
        <div style="display: flex; align-items: center; gap: 8px;">
          <i class="fa-solid fa-copy" style="color: var(--text-muted); cursor: pointer;" title="Copy Stop Command" onclick="navigator.clipboard.writeText('PYTHONPATH=src python3 -m memory_os daemon stop'); alert('Stop command copied to clipboard!');"></i>
          <span id="daemon-status-badge" style="color: var(--text-muted); font-size: 10px;">Offline</span>
        </div>
      </div>
      <div style="display: flex; gap: 10px;">
        <div style="flex: 1;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 2px;"><span>CPU</span><span id="cpu-val">0%</span></div>
          <div style="height: 4px; background: rgba(0,0,0,0.5); border-radius: 2px; overflow: hidden;"><div id="cpu-bar" style="height: 100%; width: 0%; background: var(--accent-blue); transition: width 0.3s;"></div></div>
        </div>
        <div style="flex: 1;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 2px;"><span>RAM</span><span id="ram-val">0%</span></div>
          <div style="height: 4px; background: rgba(0,0,0,0.5); border-radius: 2px; overflow: hidden;"><div id="ram-bar" style="height: 100%; width: 0%; background: var(--accent-green); transition: width 0.3s;"></div></div>
        </div>
      </div>
      <div style="border-bottom: 1px solid var(--border-panel); padding-bottom: 4px; margin-top: 4px;">
        <h2 style="margin: 0; font-size: 12px;"><i class="fa-solid fa-robot"></i> Background Auditors</h2>
      </div>
      <div id="auditors-list" style="display: flex; flex-direction: column; gap: 8px;">
        <div style="color: var(--text-muted); text-align: center; padding: 10px;">Daemon is not running.</div>
      </div>
    </div>
  </div>

  <script>
    const gData = {
      nodes: _NODES_JSON_,
      links: _LINKS_JSON_
    };

    // Color definitions
    const colors = {
      type: {
        rule: '#3b82f6',        // Blue
        fact: '#10b981',        // Green
        variable: '#f59e0b',    // Amber
        connector: '#ec4899',   // Pink
        config: '#8b5cf6',      // Purple
        policy: '#ef4444',      // Red
        file: '#64748b',        // Slate
        class: '#0d9488',       // Teal
        function: '#0891b2',    // Cyan
        module: '#4f46e5',      // Indigo
        default: '#94a3b8'
      },
      status: {
        draft: '#f59e0b',       // Amber
        observed: '#8b5cf6',    // Purple
        verified: '#10b981',    // Green
        stale: '#64748b',       // Slate
        superseded: '#ef4444',  // Red
        default: '#94a3b8'
      },
      trust: {
        verified: '#10b981',    // Green
        unverified: '#ef4444',  // Red
        extracted: '#3b82f6',   // Blue
        inferred: '#f59e0b',    // Amber
        default: '#94a3b8'
      }
    };

    let colorMode = 'degree';
    let searchQuery = '';
    window.connectionFilterState = 0; // 0 = Top, 1 = Lowest, 2 = Isolated

    function cycleConnectionFilter() {
      window.connectionFilterState = (window.connectionFilterState + 1) % 3;
      updateStatsAndPanel();
    }

    // Calculate node connections (degrees)
    const nodeDegrees = {};
    gData.nodes.forEach(n => { nodeDegrees[n.id] = 0; });
    gData.links.forEach(l => {
      const sId = typeof l.source === 'object' ? l.source.id : l.source;
      const tId = typeof l.target === 'object' ? l.target.id : l.target;
      if (nodeDegrees[sId] !== undefined) nodeDegrees[sId]++;
      if (nodeDegrees[tId] !== undefined) nodeDegrees[tId]++;
    });

    // Degree mapping color helper
    function getDegreeColor(deg) {
      const maxDeg = Math.max(...Object.values(nodeDegrees), 1);
      const ratio = deg / maxDeg;
      // Blue (cold, low degree) to Purple to Pink/Red (hot, high degree)
      if (ratio < 0.25) return '#3b82f6';
      if (ratio < 0.5) return '#8b5cf6';
      if (ratio < 0.75) return '#d946ef';
      return '#ef4444';
    }

    function getNodeColor(node) {
      // If there is search, dim non-matching nodes
      if (searchQuery) {
        if (!node.id.toLowerCase().includes(searchQuery) && 
            !node.type.toLowerCase().includes(searchQuery) &&
            !node.summary.toLowerCase().includes(searchQuery) &&
            !(node.tags && node.tags.some(t => t.toLowerCase().includes(searchQuery)))) {
          return 'rgba(255, 255, 255, 0.05)';
        }
      }
      
      if (window.activeAuditorTargets && window.activeAuditorTargets.has(node.id)) {
        return '#ef4444'; // Highlight active audit targets
      }

      if (colorMode === 'type') {
        return colors.type[node.type] || colors.type.default;
      } else if (colorMode === 'status') {
        return colors.status[node.status] || colors.status.default;
      } else if (colorMode === 'trust') {
        return colors.trust[node.trust] || colors.trust.default;
      } else if (colorMode === 'degree') {
        return getDegreeColor(nodeDegrees[node.id] || 0);
      }
      return '#94a3b8';
    }

    // Initialize the 3D Graph
    const Graph = ForceGraph3D({ controlType: 'trackball' })
      (document.getElementById('3d-graph'))
      .graphData(gData)
      .backgroundColor('#0b0f19')
      .nodeColor(getNodeColor)
      .nodeLabel(node => {
        const typeColor = colors.type[node.type] || '#94a3b8';
        const rawSummary = node.summary || '';
        let plainText = rawSummary.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[#*`_]/g, '');
        if (plainText.length > 150) plainText = plainText.substring(0, 147) + '...';
        return `
          <div class="graph-tooltip">
            <strong style="color: ${typeColor};">${node.id}</strong>
            <div class="tooltip-meta">Type: ${node.type} | Status: ${node.status}</div>
            <div style="color: #cbd5e1; font-size: 11.5px; line-height: 1.4;">${plainText}</div>
          </div>
        `;
      })
      .nodeVal(node => {
        const baseSize = 4;
        const deg = nodeDegrees[node.id] || 0;
        return baseSize + Math.sqrt(deg) * 2;
      })
      .linkWidth(link => {
        const sId = typeof link.source === 'object' ? link.source.id : link.source;
        const tId = typeof link.target === 'object' ? link.target.id : link.target;
        // Strong connections get 3D cylinders, weak connections get 1px constant lines
        return (nodeDegrees[sId] > 2 && nodeDegrees[tId] > 2) ? 1.0 : 0;
      })
      .linkColor(link => {
        const sId = typeof link.source === 'object' ? link.source.id : link.source;
        const tId = typeof link.target === 'object' ? link.target.id : link.target;

        if (searchQuery) {
          const sNode = gData.nodes.find(n => n.id === sId);
          const tNode = gData.nodes.find(n => n.id === tId);
          const sMatches = sNode && (sNode.id.toLowerCase().includes(searchQuery) || sNode.summary.toLowerCase().includes(searchQuery));
          const tMatches = tNode && (tNode.id.toLowerCase().includes(searchQuery) || tNode.summary.toLowerCase().includes(searchQuery));
          if (!sMatches || !tMatches) {
            return 'rgba(148, 163, 184, 0.03)';
          }
        }
        
        // Far/weak nodes get a faint but distinct line
        if (nodeDegrees[sId] <= 2 || nodeDegrees[tId] <= 2) {
          return 'rgba(255, 255, 255, 0.12)'; 
        }
        return 'rgba(148, 163, 184, 0.25)';
      })
      .linkDirectionalParticles(link => {
        const sId = typeof link.source === 'object' ? link.source.id : link.source;
        return (nodeDegrees[sId] > 3) ? 2 : 0;
      })
      .linkDirectionalParticleSpeed(0.005)
      .linkDirectionalParticleWidth(1.8)
      .onNodeClick(node => {
        focusOnNode(node);
      });

    // Camera Focus function
    function focusOnNode(node) {
      const distance = 80;
      const distRatio = 1 + distance/Math.hypot(node.x, node.y, node.z);

      Graph.cameraPosition(
        { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio }, // position
        node, // lookAt
        1800  // transition ms
      );
      
      showNodeDetails(node);
    }

    // Populate Right Details Drawer
    function showNodeDetails(node) {
      document.getElementById('node-detail-id').innerText = node.id;
      
      // Type badge
      const typeBadge = document.getElementById('node-type-badge');
      typeBadge.innerText = node.type;
      typeBadge.style.background = (colors.type[node.type] || colors.type.default) + '22';
      typeBadge.style.color = colors.type[node.type] || colors.type.default;
      typeBadge.style.border = `1px solid ${colors.type[node.type] || colors.type.default}`;
      
      // Status badge
      const statusBadge = document.getElementById('node-status-badge');
      statusBadge.innerText = `Status: ${node.status}`;
      statusBadge.style.color = colors.status[node.status] || colors.status.default;
      statusBadge.style.borderColor = (colors.status[node.status] || colors.status.default) + '44';
      
      // Trust badge
      const trustBadge = document.getElementById('node-trust-badge');
      trustBadge.innerText = `Trust: ${node.trust}`;
      trustBadge.style.color = colors.trust[node.trust] || colors.trust.default;
      trustBadge.style.borderColor = (colors.trust[node.trust] || colors.trust.default) + '44';

      // Freshness badge
      const freshnessBadge = document.getElementById('node-freshness-badge');
      if (node.freshness) {
        freshnessBadge.style.display = 'inline-flex';
        freshnessBadge.innerHTML = `<i class="fa-solid fa-calendar"></i> ${node.freshness.replace('T', ' ')}`;
      } else {
        freshnessBadge.style.display = 'none';
      }

      // Tags list
      const tagsList = document.getElementById('node-tags-list');
      tagsList.innerHTML = '';
      if (node.tags && node.tags.length > 0) {
        node.tags.forEach(tag => {
          const span = document.createElement('span');
          span.className = 'badge';
          span.style.background = 'rgba(255,255,255,0.05)';
          span.style.color = '#e2e8f0';
          span.style.textTransform = 'none';
          span.innerHTML = `<i class="fa-solid fa-tag" style="color:var(--accent-blue);"></i> ${tag}`;
          tagsList.appendChild(span);
        });
      } else {
        tagsList.innerHTML = '<span style="font-size:12px; color:var(--text-muted);">No tags</span>';
      }

      // Markdown Summary content
      const contentRender = document.getElementById('node-content-render');
      contentRender.innerHTML = marked.parse(node.summary || '*No summary content*');

      // Evidence list
      const evidenceList = document.getElementById('node-evidence-list');
      evidenceList.innerHTML = '';
      if (node.evidence && node.evidence.length > 0) {
        node.evidence.forEach(linkUrl => {
          const div = document.createElement('div');
          div.className = 'list-item';
          
          let displayTitle = linkUrl;
          if (linkUrl.length > 40) {
            displayTitle = linkUrl.substring(0, 37) + '...';
          }
          
          let icon = 'fa-arrow-up-right-from-square';
          if (linkUrl.includes('notion.com')) icon = 'fa-circle-nodes';
          else if (linkUrl.includes('drive.google.com')) icon = 'fa-folder-open';
          
          div.innerHTML = `
            <div style="display:flex; justify-content:space-between; width:100%; align-items:center;">
              <a href="${linkUrl}" target="_blank" style="color:var(--text-header); text-decoration:none; flex-grow: 1; overflow: hidden;">
                <span class="list-item-title"><i class="fa-solid ${icon}" style="margin-right:8px; color:var(--accent-blue);"></i>${displayTitle}</span>
              </a>
              <button onclick="navigator.clipboard.writeText('${linkUrl}'); this.innerHTML='<i class=\'fa-solid fa-check\' style=\'color:var(--accent-green)\'></i>'; setTimeout(()=>this.innerHTML='<i class=\'fa-regular fa-copy\'></i>', 1500);" style="background:none; border:none; color:var(--text-muted); cursor:pointer; padding:4px;" title="Copy to clipboard">
                <i class="fa-regular fa-copy"></i>
              </button>
            </div>
          `;
          evidenceList.appendChild(div);
        });
      } else {
        evidenceList.innerHTML = '<span style="font-size:12px; color:var(--text-muted); padding: 4px;">No evidence links</span>';
      }

      // Connections list (neighbors)
      const connectionsList = document.getElementById('node-connections-list');
      connectionsList.innerHTML = '';
      const neighbors = new Set();
      gData.links.forEach(l => {
        const sId = typeof l.source === 'object' ? l.source.id : l.source;
        const tId = typeof l.target === 'object' ? l.target.id : l.target;
        if (sId === node.id) neighbors.add(tId);
        if (tId === node.id) neighbors.add(sId);
      });

      if (neighbors.size > 0) {
        neighbors.forEach(nId => {
          const btn = document.createElement('button');
          btn.className = 'tag-btn';
          const neighborNode = gData.nodes.find(n => n.id === nId);
          const nType = neighborNode ? neighborNode.type : 'default';
          const dotColor = colors.type[nType] || '#94a3b8';
          btn.innerHTML = `<span class="color-dot" style="background:${dotColor};"></span> ${nId}`;
          btn.onclick = () => {
            if (neighborNode) {
              focusOnNode(neighborNode);
            }
          };
          connectionsList.appendChild(btn);
        });
      } else {
        connectionsList.innerHTML = '<span style="font-size:12px; color:var(--text-muted);">No connection edges</span>';
      }

      // Open drawer
      document.getElementById('right-panel').classList.add('active');
    }

    function closeDrawer() {
      document.getElementById('right-panel').classList.remove('active');
    }

    // Dynamic stats and breakdown calculator
    function updateStatsAndPanel() {
      const activeNodes = searchQuery ? gData.nodes.filter(node => {
        return node.id.toLowerCase().includes(searchQuery) ||
               node.summary.toLowerCase().includes(searchQuery) ||
               (node.tags && node.tags.some(t => t.toLowerCase().includes(searchQuery))) ||
               node.type.toLowerCase().includes(searchQuery);
      }) : gData.nodes;

      document.getElementById('node-count').innerText = activeNodes.length;
      
      let activeEdgeCount = 0;
      let isolatedCount = 0;
      
      const activeNodeIds = new Set(activeNodes.map(n => n.id));
      gData.links.forEach(l => {
        const sId = typeof l.source === 'object' ? l.source.id : l.source;
        const tId = typeof l.target === 'object' ? l.target.id : l.target;
        if (activeNodeIds.has(sId) && activeNodeIds.has(tId)) {
          activeEdgeCount++;
        }
      });
      document.getElementById('edge-count').innerText = activeEdgeCount;

      activeNodes.forEach(node => {
        let connected = false;
        gData.links.forEach(l => {
          const sId = typeof l.source === 'object' ? l.source.id : l.source;
          const tId = typeof l.target === 'object' ? l.target.id : l.target;
          if ((sId === node.id && activeNodeIds.has(tId)) || (tId === node.id && activeNodeIds.has(sId))) {
            connected = true;
          }
        });
        if (!connected) isolatedCount++;
      });
      document.getElementById('unlinked-count').innerText = isolatedCount;

      // Type breakdown list
      const typeCounts = {};
      activeNodes.forEach(n => {
        typeCounts[n.type] = (typeCounts[n.type] || 0) + 1;
      });
      
      const typeBreakdownList = document.getElementById('type-breakdown-list');
      typeBreakdownList.innerHTML = '';
      Object.keys(typeCounts)
        .sort((a,b) => typeCounts[b] - typeCounts[a])
        .forEach(t => {
          const dotColor = colors.type[t] || '#94a3b8';
          const item = document.createElement('div');
          item.className = 'list-item';
          item.onclick = () => {
            document.getElementById('search-input').value = t;
            searchQuery = t;
            updateStatsAndPanel();
            Graph.nodeColor(getNodeColor);
            Graph.linkColor(Graph.linkColor());
          };
          item.innerHTML = `
            <span class="legend-item"><span class="color-dot" style="background:${dotColor};"></span> ${t}</span>
            <span class="list-item-value">${typeCounts[t]}</span>
          `;
          typeBreakdownList.appendChild(item);
        });

      // Connection cycling logic
      const topConnectedList = document.getElementById('top-connected-list');
      const topConnectedTitle = document.getElementById('top-connected-title');
      topConnectedList.innerHTML = '';
      
      let sortedNodes = activeNodes.map(n => ({ node: n, deg: nodeDegrees[n.id] || 0 }));
      
      if (window.connectionFilterState === 1) {
        topConnectedTitle.innerHTML = '<i class="fa-solid fa-arrow-trend-down"></i> Lowest Connected';
        sortedNodes = sortedNodes.filter(n => n.deg > 0).sort((a,b) => a.deg - b.deg);
      } else if (window.connectionFilterState === 2) {
        topConnectedTitle.innerHTML = '<i class="fa-solid fa-link-slash"></i> Isolated Nodes';
        sortedNodes = sortedNodes.filter(n => n.deg === 0);
      } else {
        topConnectedTitle.innerHTML = '<i class="fa-solid fa-arrow-trend-up"></i> Top Connected';
        sortedNodes = sortedNodes.sort((a,b) => b.deg - a.deg);
      }
      const limitVal = document.getElementById('list-limit-input').value.toLowerCase();
      let limit = 20;
      if (limitVal === 'all') {
        limit = sortedNodes.length;
      } else {
        const parsed = parseInt(limitVal, 10);
        if (!isNaN(parsed) && parsed > 0) limit = parsed;
      }
      
      sortedNodes
        .slice(0, limit)
        .forEach(item => {
          const dotColor = colors.type[item.node.type] || '#94a3b8';
          const div = document.createElement('div');
          div.className = 'list-item';
          div.onclick = () => {
            focusOnNode(item.node);
          };
          div.innerHTML = `
            <span class="list-item-title"><span class="color-dot" style="background:${dotColor}; margin-right:6px;"></span>${item.node.id}</span>
            <span class="list-item-value"><i class="fa-solid fa-circle-nodes" style="font-size:10px;"></i> ${item.deg}</span>
          `;
          topConnectedList.appendChild(div);
        });
    }

    // Legend renderer
    function updateLegend() {
      const legendItems = document.getElementById('legend-items');
      legendItems.innerHTML = '';
      
      if (colorMode === 'type') {
        Object.keys(colors.type).forEach(key => {
          if (key === 'default') return;
          const div = document.createElement('div');
          div.className = 'legend-item';
          div.innerHTML = `<span class="color-dot" style="background:${colors.type[key]};"></span> <span style="text-transform: capitalize;">${key}</span>`;
          legendItems.appendChild(div);
        });
      } else if (colorMode === 'status') {
        Object.keys(colors.status).forEach(key => {
          if (key === 'default') return;
          const div = document.createElement('div');
          div.className = 'legend-item';
          div.innerHTML = `<span class="color-dot" style="background:${colors.status[key]};"></span> <span style="text-transform: capitalize;">${key}</span>`;
          legendItems.appendChild(div);
        });
      } else if (colorMode === 'trust') {
        Object.keys(colors.trust).forEach(key => {
          if (key === 'default') return;
          const div = document.createElement('div');
          div.className = 'legend-item';
          div.innerHTML = `<span class="color-dot" style="background:${colors.trust[key]};"></span> <span style="text-transform: capitalize;">${key}</span>`;
          legendItems.appendChild(div);
        });
      } else if (colorMode === 'degree') {
        const grads = [
          { text: 'Low Connections', color: '#3b82f6' },
          { text: 'Medium Connections', color: '#8b5cf6' },
          { text: 'High Connections', color: '#d946ef' },
          { text: 'Pillar Hub Node', color: '#ef4444' }
        ];
        grads.forEach(g => {
          const div = document.createElement('div');
          div.className = 'legend-item';
          div.innerHTML = `<span class="color-dot" style="background:${g.color};"></span> <span>${g.text}</span>`;
          legendItems.appendChild(div);
        });
      }
    }

    // Wire up events
    document.getElementById('search-input').addEventListener('input', (e) => {
      searchQuery = e.target.value.toLowerCase().trim();
      updateStatsAndPanel();
      Graph.nodeColor(getNodeColor);
      Graph.linkColor(Graph.linkColor());
    });

    document.getElementById('list-limit-input').addEventListener('input', (e) => {
      updateStatsAndPanel();
    });

    document.getElementById('color-mode-select').addEventListener('change', (e) => {
      colorMode = e.target.value;
      Graph.nodeColor(getNodeColor);
      updateLegend();
    });

    // Initial setup
    updateStatsAndPanel();
    updateLegend();

    // --- AUDITORS LOGIC ---
    window.activeAuditorTargets = new Set();
    const daemonUrl = "http://127.0.0.1:22467";

    async function fetchAuditors() {
      try {
        const resp = await fetch(`${daemonUrl}/auditors/status`);
        if (!resp.ok) throw new Error("HTTP error");
        const data = await resp.json();
        
        document.getElementById('daemon-status-badge').innerText = 'Online';
        document.getElementById('daemon-status-badge').style.color = '#10b981';
        
        document.getElementById('cpu-val').innerText = `${data.metrics.cpu_percent}%`;
        document.getElementById('cpu-bar').style.width = `${data.metrics.cpu_percent}%`;
        document.getElementById('ram-val').innerText = `${data.metrics.ram_percent}%`;
        document.getElementById('ram-bar').style.width = `${data.metrics.ram_percent}%`;

        const list = document.getElementById('auditors-list');
        list.innerHTML = '';
        
        let newActive = new Set();
        
        data.auditors.forEach(aud => {
          if (aud.current_target && aud.state === 'running') {
            newActive.add(aud.current_target[0]);
            newActive.add(aud.current_target[1]);
          }
          
          const div = document.createElement('div');
          div.style.background = 'rgba(255,255,255,0.02)';
          div.style.border = '1px solid var(--border-panel)';
          div.style.borderRadius = '6px';
          div.style.padding = '6px 8px';
          
          let stateColor = '#64748b';
          let stateIcon = 'fa-circle-pause';
          if (aud.state === 'running') { stateColor = '#10b981'; stateIcon = 'fa-circle-play fa-fade'; }
          else if (aud.state === 'paused') { stateColor = '#f59e0b'; }
          
          div.innerHTML = `
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
              <strong style="color: var(--text-header); font-size: 12px;">${aud.name}</strong>
              <span style="color: ${stateColor}; font-size: 10px;"><i class="fa-solid ${stateIcon}"></i> ${aud.state.toUpperCase()}</span>
            </div>
            <div style="font-size: 10px; color: var(--text-muted); margin-bottom: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-family: monospace; background: rgba(0,0,0,0.2); padding: 4px; border-radius: 4px;">
              > ${aud.last_log}
            </div>
            <div style="display: flex; gap: 4px;">
              <button onclick="auditorAction('${aud.name}', 'start')" style="flex: 1; background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.2); color: #10b981; border-radius: 4px; cursor: pointer; padding: 4px 2px;">Start</button>
              <button onclick="auditorAction('${aud.name}', 'pause')" style="flex: 1; background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.2); color: #f59e0b; border-radius: 4px; cursor: pointer; padding: 4px 2px;">Pause</button>
              <button onclick="auditorAction('${aud.name}', 'stop')" style="flex: 1; background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.2); color: #ef4444; border-radius: 4px; cursor: pointer; padding: 4px 2px;">Stop</button>
            </div>
          `;
          list.appendChild(div);
        });
        
        let changed = false;
        if (newActive.size !== window.activeAuditorTargets.size) changed = true;
        else {
          for (let item of newActive) if (!window.activeAuditorTargets.has(item)) changed = true;
        }
        
        if (changed) {
          window.activeAuditorTargets = newActive;
          Graph.nodeColor(getNodeColor);
        }
        
      } catch (err) {
        document.getElementById('daemon-status-badge').innerText = 'Offline';
        document.getElementById('daemon-status-badge').style.color = '#ef4444';
        document.getElementById('cpu-val').innerText = '0%';
        document.getElementById('cpu-bar').style.width = '0%';
        document.getElementById('ram-val').innerText = '0%';
        document.getElementById('ram-bar').style.width = '0%';
        document.getElementById('auditors-list').innerHTML = `
          <div style="color: var(--text-muted); text-align: center; padding: 10px;">
            <p style="margin-top: 0; margin-bottom: 8px;">Daemon is offline (or stuck).</p>
            <div style="display: flex; flex-direction: column; gap: 6px;">
              <button onclick="navigator.clipboard.writeText('PYTHONPATH=src python3 -m memory_os daemon start'); alert('Start command copied to clipboard!');" style="background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.2); color: #10b981; border-radius: 4px; cursor: pointer; padding: 6px 12px;">
                <i class="fa-solid fa-play"></i> Copy Start Command
              </button>
              <button onclick="navigator.clipboard.writeText('PYTHONPATH=src python3 -m memory_os daemon stop'); alert('Stop command copied to clipboard!');" style="background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.2); color: #ef4444; border-radius: 4px; cursor: pointer; padding: 6px 12px;">
                <i class="fa-solid fa-stop"></i> Copy Stop Command
              </button>
            </div>
          </div>
        `;
        
        if (window.activeAuditorTargets.size > 0) {
          window.activeAuditorTargets.clear();
          Graph.nodeColor(getNodeColor);
        }
      }
    }

    async function auditorAction(name, action) {
      try {
        await fetch(`${daemonUrl}/auditors/${action}?name=${encodeURIComponent(name)}`, { method: 'POST' });
        fetchAuditors();
      } catch (err) {
        console.error(err);
      }
    }

    setInterval(fetchAuditors, 1000);
    fetchAuditors();

  </script>
</body>
</html>
"""

def generate_3d_graph_visualization(config: MemoryOSConfig) -> bool:
    nodes_path = config.memory_dir / "nodes.jsonl"
    edges_path = config.memory_dir / "edges.jsonl"
    
    if not nodes_path.exists():
        logger.error(f"nodes.jsonl not found at {nodes_path}. Cannot generate graph.")
        return False
        
    nodes = []
    node_ids = set()
    with open(nodes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                node = json.loads(line)
                nodes.append({
                    "id": node["id"],
                    "type": node["type"],
                    "summary": node["summary"],
                    "evidence": node.get("evidence", []),
                    "status": node.get("status", "verified"),
                    "freshness": node.get("freshness", ""),
                    "trust": node.get("trust", "verified"),
                    "tags": node.get("tags", []),
                    "related_nodes": node.get("related_nodes", [])
                })
                node_ids.add(node["id"])
            except Exception as e:
                logger.warning(f"Failed to parse node line: {e}")
                
    links = []
    seen_links = set()
    
    # Read explicit edges
    if edges_path.exists():
        with open(edges_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    edge = json.loads(line)
                    source, target = edge["source"], edge["target"]
                    if source in node_ids and target in node_ids:
                        link_key = (source, target)
                        if link_key not in seen_links:
                            links.append({
                                "source": source,
                                "target": target,
                                "type": edge.get("type", "depends_on")
                            })
                            seen_links.add(link_key)
                except Exception as e:
                    logger.warning(f"Failed to parse edge line: {e}")
                    
    # Read implicit related_nodes links
    with open(nodes_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                node = json.loads(line)
                source = node["id"]
                for target in node.get("related_nodes", []):
                    if source in node_ids and target in node_ids:
                        link_key = (source, target)
                        reverse_key = (target, source)
                        if link_key not in seen_links and reverse_key not in seen_links:
                            links.append({
                                "source": source,
                                "target": target,
                                "type": "related_to"
                            })
                            seen_links.add(link_key)
            except Exception:
                continue
                
    # Generate HTML content
    html_content = HTML_TEMPLATE.replace("_NODES_JSON_", json.dumps(nodes, ensure_ascii=False))
    html_content = html_content.replace("_LINKS_JSON_", json.dumps(links, ensure_ascii=False))
    
    output_path = config.root_dir / "memory_graph_3d.html"
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        logger.info(f"Successfully generated 3D Graph visualization at: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to write 3D visualization HTML: {e}")
        return False
