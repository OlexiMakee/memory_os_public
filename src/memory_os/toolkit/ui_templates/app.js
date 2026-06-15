let gData = { nodes: [], links: [] };
let gDataFull = { nodes: [], links: [] };

function applyNodeTypeFilter() {
  const hidden = window.hiddenNodeTypes || new Set();
  if (hidden.size === 0) {
    gData = { nodes: [...gDataFull.nodes], links: [...gDataFull.links] };
  } else {
    const visibleIds = new Set(gDataFull.nodes.filter(n => !hidden.has(n.type)).map(n => n.id));
    gData = {
      nodes: gDataFull.nodes.filter(n => visibleIds.has(n.id)),
      links: gDataFull.links.filter(l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source;
        const t = typeof l.target === 'object' ? l.target.id : l.target;
        return visibleIds.has(s) && visibleIds.has(t);
      }),
    };
  }
  if (Graph) {
    Graph.graphData(gData);
    updateStatsAndPanel();
  }
}

function buildNodeTypeToggles() {
  const container = document.getElementById('node-type-toggles');
  if (!container) return;
  const allTypes = [...new Set(gDataFull.nodes.map(n => n.type))].sort();
  const hidden = window.hiddenNodeTypes || new Set();
  container.innerHTML = '';
  allTypes.forEach(type => {
    const isHidden = hidden.has(type);
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;';
    const color = (colors.type && colors.type[type]) ? colors.type[type] : '#94a3b8';
    const count = gDataFull.nodes.filter(n => n.type === type).length;
    row.innerHTML = `
      <span style="font-size:11px;color:var(--text-main);display:flex;align-items:center;gap:6px;">
        <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block;"></span>
        ${type} <span style="color:var(--text-muted)">(${count})</span>
      </span>
      <label class="switch" style="position:relative;display:inline-block;width:34px;height:20px;">
        <input type="checkbox" data-node-type="${type}" ${isHidden ? '' : 'checked'} style="opacity:0;width:0;height:0;">
        <span class="slider" style="position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background-color:${isHidden ? 'rgba(255,255,255,0.2)' : color + '99'};transition:.4s;border-radius:20px;">
          <span class="slider-dot" style="position:absolute;height:14px;width:14px;left:${isHidden ? '3' : '17'}px;bottom:3px;background-color:white;transition:.4s;border-radius:50%;"></span>
        </span>
      </label>`;
    const checkbox = row.querySelector('input[type=checkbox]');
    checkbox.addEventListener('change', (e) => {
      if (!e.target.checked) hidden.add(type); else hidden.delete(type);
      window.hiddenNodeTypes = hidden;
      saveSetting('hiddenNodeTypes', [...hidden]);
      applyNodeTypeFilter();
      buildNodeTypeToggles();
    });
    container.appendChild(row);
  });
}

let Graph;

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
const nodeDegrees = {};

async function fetchSpaces() {
  try {
    const res = await fetch('/api/spaces');
    if (res.ok) {
      const data = await res.json();
      const select = document.getElementById('space-select');
      select.innerHTML = '';
      data.spaces.forEach(sp => {
        const opt = document.createElement('option');
        opt.value = sp;
        opt.innerText = sp;
        if (sp === data.active) opt.selected = true;
        select.appendChild(opt);
      });
    }
  } catch (err) {
    console.error('Failed to fetch spaces:', err);
  }
}

window.switchSpace = async function(newSpace) {
  try {
    const res = await fetch('/api/switch_space', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ space: newSpace })
    });
    if (res.ok) {
      // Reload graph
      initApp();
    } else {
      console.error('Failed to switch space');
    }
  } catch (err) {
    console.error('Error switching space:', err);
  }
};

let drawEdgeMode = false;
let drawEdgeSource = null;

let mergeMode = false;
let mergeSource = null;

window.toggleDrawEdgeMode = function() {
  drawEdgeMode = !drawEdgeMode;
  drawEdgeSource = null;
  const btn = document.getElementById('btn-draw-edge');
  if (drawEdgeMode) {
    btn.style.color = '#4ade80';
    alert("Draw Link Mode: Select the source node, then select the target node to create a link.");
  } else {
    btn.style.color = 'var(--text-muted)';
  }
};

window.verifyCurrentNode = async function() {
  if (!window.focusedNode) return;
  try {
    const res = await fetch('/api/nodes/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: window.focusedNode.id })
    });
    if (res.ok) {
      alert(`Node ${window.focusedNode.id} has been verified and locked.`);
      initApp();
    } else {
      alert("Failed to verify node.");
    }
  } catch (err) {
    console.error(err);
  }
};

window.initiateMerge = function() {
  if (!window.focusedNode) return;
  mergeMode = true;
  mergeSource = window.focusedNode.id;
  alert(`Merge Mode: Select the target node to merge "${window.focusedNode.id}" INTO.`);
};

async function initApp() {
  try {
    const res = await fetch('/api/graph');
    if (!res.ok) throw new Error('Failed to fetch graph data');
    gDataFull = await res.json();
    applyNodeTypeFilter();
    buildNodeTypeToggles();
  } catch (err) {
    console.error(err);
    alert('Failed to load Memory OS graph data. Is the UI server running in a valid project?');
    return;
  }

  window.getLinkWidth = function(link) {
    const sId = typeof link.source === 'object' ? link.source.id : link.source;
    const tId = typeof link.target === 'object' ? link.target.id : link.target;
    
    if (window.showLeafLinks) return 1.0;
    return (nodeDegrees[sId] > 2 && nodeDegrees[tId] > 2) ? 1.0 : 0;
  };

  window.getLinkColor = function(link) {
    const sId = typeof link.source === 'object' ? link.source.id : link.source;
    const tId = typeof link.target === 'object' ? link.target.id : link.target;

    if (searchQuery) {
      const sNode = gData.nodes.find(n => n.id === sId);
      const tNode = gData.nodes.find(n => n.id === tId);
      const sMatches = sNode && (sNode.id.toLowerCase().includes(searchQuery) || (sNode.summary && sNode.summary.toLowerCase().includes(searchQuery)));
      const tMatches = tNode && (tNode.id.toLowerCase().includes(searchQuery) || (tNode.summary && tNode.summary.toLowerCase().includes(searchQuery)));
      
      if (sMatches && tMatches) return 'rgba(255, 255, 255, 0.8)';
      if (sMatches || tMatches) return 'rgba(148, 163, 184, 0.3)';
      return 'rgba(148, 163, 184, 0.02)';
    }
    
    if (nodeDegrees[sId] <= 2 || nodeDegrees[tId] <= 2) return 'rgba(255, 255, 255, 0.12)'; 
    return 'rgba(148, 163, 184, 0.25)';
  };

  // Calculate node connections (degrees)
  gData.nodes.forEach(n => { nodeDegrees[n.id] = 0; });
  gData.links.forEach(l => {
    const sId = typeof l.source === 'object' ? l.source.id : l.source;
    const tId = typeof l.target === 'object' ? l.target.id : l.target;
    if (nodeDegrees[sId] !== undefined) nodeDegrees[sId]++;
    if (nodeDegrees[tId] !== undefined) nodeDegrees[tId]++;
  });

  // Initialize the 3D Graph
  Graph = ForceGraph3D({ controlType: 'trackball' })
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
      let baseSize = 4;
      if (node.file_size) {
        const sizeBonus = Math.min(Math.sqrt(node.file_size) / 10, 25);
        baseSize += sizeBonus;
      }
      const deg = nodeDegrees[node.id] || 0;
      return baseSize + Math.sqrt(deg) * 2;
    })
    .linkWidth(link => getLinkWidth(link))
    .linkColor(link => window.getLinkColor(link))
    .linkDirectionalParticles(link => {
      const sId = typeof link.source === 'object' ? link.source.id : link.source;
      return (nodeDegrees[sId] > 3) ? 2 : 0;
    })
    .linkDirectionalParticleSpeed(0.005)
    .linkDirectionalParticleWidth(1.8)
    .onNodeClick(node => focusOnNode(node));

  updateStatsAndPanel();
  updateLegend();
  if (window.applyAllSettingsSafely) {
    setTimeout(() => { window.applyAllSettingsSafely(); }, 100);
  }
}

function cycleConnectionFilter() {
  window.connectionFilterState = (window.connectionFilterState + 1) % 3;
  updateStatsAndPanel();
}

function getDegreeColor(deg) {
  const maxDeg = Math.max(...Object.values(nodeDegrees), 1);
  const ratio = deg / maxDeg;
  if (ratio < 0.25) return '#3b82f6';
  if (ratio < 0.5) return '#8b5cf6';
  if (ratio < 0.75) return '#d946ef';
  return '#ef4444';
}

function getNodeColor(node) {
  if (searchQuery) {
    if (!node.id.toLowerCase().includes(searchQuery) && 
        !node.type.toLowerCase().includes(searchQuery) &&
        !node.summary.toLowerCase().includes(searchQuery) &&
        !(node.tags && node.tags.some(t => t.toLowerCase().includes(searchQuery)))) {
      return 'rgba(255, 255, 255, 0.05)';
    }
  }
  
  if (window.activeAuditorTargets && window.activeAuditorTargets.has(node.id)) {
    return '#ef4444';
  }

  if (colorMode === 'type') return colors.type[node.type] || colors.type.default;
  if (colorMode === 'status') return colors.status[node.status] || colors.status.default;
  if (colorMode === 'trust') return colors.trust[node.trust] || colors.trust.default;
  if (colorMode === 'degree') return getDegreeColor(nodeDegrees[node.id] || 0);
  return '#94a3b8';
}

function focusOnNode(node) {
  if (drawEdgeMode) {
    if (!drawEdgeSource) {
      drawEdgeSource = node;
      alert(`Source selected: ${node.id}. Now select target node.`);
    } else {
      if (node.id === drawEdgeSource.id) {
        alert("Cannot link to self.");
        drawEdgeSource = null;
        return;
      }
      fetch('/api/edges/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: drawEdgeSource.id, target: node.id })
      }).then(res => {
        if (res.ok) {
           alert("Link created!");
           drawEdgeSource = null;
           toggleDrawEdgeMode();
           initApp();
        }
      });
    }
    return;
  }
  
  if (mergeMode) {
    if (node.id === mergeSource) {
       alert("Cannot merge to self.");
       mergeMode = false; mergeSource = null;
       return;
    }
    if (confirm(`Are you sure you want to merge "${mergeSource}" INTO "${node.id}"? This will delete ${mergeSource}.`)) {
      fetch('/api/nodes/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: mergeSource, target: node.id })
      }).then(res => {
        if (res.ok) {
           alert("Nodes merged!");
           mergeMode = false; mergeSource = null;
           initApp();
        }
      });
    } else {
      mergeMode = false; mergeSource = null;
    }
    return;
  }

  window.focusedNode = node;
  window.lastFocusTime = Date.now();

  // Keep current position, only change lookAt target
  Graph.cameraPosition(
    Graph.cameraPosition(),
    node,
    1800
  );
  
  showNodeDetails(node);
}

function getAbsolutePath(path) {
  if (path.startsWith('file:')) path = path.substring(5);
  if (path.startsWith('/')) return path;
  if (window.WORKSPACE_ROOT) {
    return window.WORKSPACE_ROOT + (window.WORKSPACE_ROOT.endsWith('/') ? '' : '/') + path;
  }
  return path;
}

function showNodeDetails(node) {
  document.getElementById('node-detail-id').innerText = node.id;
  
  const typeBadge = document.getElementById('node-type-badge');
  typeBadge.innerText = node.type;
  typeBadge.style.background = (colors.type[node.type] || colors.type.default) + '22';
  typeBadge.style.color = colors.type[node.type] || colors.type.default;
  typeBadge.style.border = `1px solid ${colors.type[node.type] || colors.type.default}`;
  
  const statusBadge = document.getElementById('node-status-badge');
  statusBadge.innerText = `Status: ${node.status}`;
  statusBadge.style.color = colors.status[node.status] || colors.status.default;
  statusBadge.style.borderColor = (colors.status[node.status] || colors.status.default) + '44';
  
  const trustBadge = document.getElementById('node-trust-badge');
  trustBadge.innerText = `Trust: ${node.trust}`;
  trustBadge.style.color = colors.trust[node.trust] || colors.trust.default;
  trustBadge.style.borderColor = (colors.trust[node.trust] || colors.trust.default) + '44';

  const freshnessBadge = document.getElementById('node-freshness-badge');
  if (node.freshness) {
    freshnessBadge.style.display = 'inline-flex';
    freshnessBadge.innerHTML = `<i class="fa-solid fa-calendar"></i> ${node.freshness.replace('T', ' ')}`;
  } else {
    freshnessBadge.style.display = 'none';
  }

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

  const contentRender = document.getElementById('node-content-render');
  contentRender.innerHTML = marked.parse(node.summary || '*No summary content*');

  const contentActions = document.getElementById('node-content-actions');
  contentActions.innerHTML = '';
  
  // Show file actions only for actual file-type nodes
  let isNodeLocalFile = node.type === 'file' || node.id.startsWith('file:');
  if (isNodeLocalFile) {
    const absPath = getAbsolutePath(node.id);
    contentActions.innerHTML = `
      <button onclick="openFileViewer('${node.id}')" style="background:rgba(59, 130, 246, 0.1); border:1px solid rgba(59, 130, 246, 0.3); color:#3b82f6; border-radius:4px; padding:2px 8px; font-size:10px; cursor:pointer;">View File</button>
      <button onclick="navigator.clipboard.writeText('${absPath}'); this.innerHTML='<i class=\\'fa-solid fa-check\\' style=\\'color:var(--accent-green)\\'></i>'; setTimeout(()=>this.innerHTML='<i class=\\'fa-regular fa-copy\\'></i>', 1500);" style="background:none; border:none; color:var(--text-muted); cursor:pointer; padding:4px;" title="Copy Absolute Path">
        <i class="fa-regular fa-copy"></i>
      </button>
    `;
  }

  const evidenceList = document.getElementById('node-evidence-list');
  evidenceList.innerHTML = '';
  if (node.evidence && node.evidence.length > 0) {
    node.evidence.forEach(linkUrl => {
      const div = document.createElement('div');
      div.className = 'list-item';
      
      let displayTitle = linkUrl;
      if (linkUrl.length > 40) displayTitle = linkUrl.substring(0, 37) + '...';
      
      let icon = 'fa-arrow-up-right-from-square';
      let isLocalFile = false;

      if (linkUrl.includes('notion.com')) icon = 'fa-circle-nodes';
      else if (linkUrl.includes('drive.google.com')) icon = 'fa-folder-open';
      else if (!linkUrl.startsWith('http')) {
        icon = 'fa-file-code';
        isLocalFile = true;
      }
      
      let actionHtml = isLocalFile ? 
        `<button onclick="openFileViewer('${linkUrl}')" style="background:rgba(59, 130, 246, 0.1); border:1px solid rgba(59, 130, 246, 0.3); color:#3b82f6; border-radius:4px; padding:2px 8px; font-size:10px; cursor:pointer; margin-right:4px;">View File</button>` 
        : '';
      let pathToCopy = isLocalFile ? getAbsolutePath(linkUrl) : linkUrl;

      div.innerHTML = `
        <div style="display:flex; justify-content:space-between; width:100%; align-items:center;">
          <a ${!isLocalFile ? `href="${linkUrl}" target="_blank"` : `href="#" onclick="openFileViewer('${linkUrl}'); return false;"`} style="color:var(--text-header); text-decoration:none; flex-grow: 1; overflow: hidden;">
            <span class="list-item-title"><i class="fa-solid ${icon}" style="margin-right:8px; color:var(--accent-blue);"></i>${displayTitle}</span>
          </a>
          <div style="display:flex; align-items:center;">
            ${actionHtml}
            <button onclick="navigator.clipboard.writeText('${pathToCopy}'); this.innerHTML='<i class=\\'fa-solid fa-check\\' style=\\'color:var(--accent-green)\\'></i>'; setTimeout(()=>this.innerHTML='<i class=\\'fa-regular fa-copy\\'></i>', 1500);" style="background:none; border:none; color:var(--text-muted); cursor:pointer; padding:4px;" title="Copy Absolute Path">
              <i class="fa-regular fa-copy"></i>
            </button>
          </div>
        </div>
      `;
      evidenceList.appendChild(div);
    });
  } else {
    evidenceList.innerHTML = '<span style="font-size:12px; color:var(--text-muted); padding: 4px;">No evidence links</span>';
  }

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
      btn.onclick = () => { if (neighborNode) focusOnNode(neighborNode); };
      connectionsList.appendChild(btn);
    });
  } else {
    connectionsList.innerHTML = '<span style="font-size:12px; color:var(--text-muted);">No connection edges</span>';
  }

  document.getElementById('right-panel').classList.add('active');
}

function closeDrawer() {
  window.focusedNode = null;
  window.lastFocusTime = Date.now();
  document.getElementById('right-panel').classList.remove('active');
  if (Graph) {
    Graph.cameraPosition(Graph.cameraPosition(), {x: 0, y: 0, z: 0}, 1800);
  }
}

// File Viewer Logic
let currentViewerPath = '';

async function openFileViewer(path) {
  currentViewerPath = path;
  document.getElementById('file-viewer-overlay').style.display = 'flex';
  document.getElementById('file-viewer-title').innerText = path;
  const contentDiv = document.getElementById('file-viewer-content');
  
  contentDiv.innerHTML = '<div style="text-align:center; padding:40px; color:var(--text-muted);"><i class="fa-solid fa-circle-notch fa-spin fa-2x"></i><br>Loading...</div>';

  try {
    const res = await fetch(`/api/read_file?path=${encodeURIComponent(path)}`);
    if (!res.ok) {
      if (res.status === 404) throw new Error('File not found or access denied outside workspace root.');
      throw new Error(`HTTP error! status: ${res.status}`);
    }
    
    const contentType = res.headers.get('content-type') || '';
    
    if (contentType.includes('image/')) {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      contentDiv.innerHTML = `<div style="display:flex; justify-content:center; align-items:center; height:100%;"><img src="${url}" style="max-width:100%; max-height:100%; object-fit:contain; border-radius:8px;"></div>`;
    } else {
      const text = await res.text();
      // Basic syntax escaping, more advanced highlighting can be added later
      const escaped = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      contentDiv.innerHTML = `<pre><code>${escaped}</code></pre>`;
    }
  } catch (err) {
    contentDiv.innerHTML = `<div style="text-align:center; padding:40px; color:#ef4444;"><i class="fa-solid fa-triangle-exclamation fa-2x"></i><br>Error loading file: ${err.message}</div>`;
  }
}

function closeFileViewer() {
  document.getElementById('file-viewer-overlay').style.display = 'none';
  document.getElementById('file-viewer-content').innerHTML = '';
}

function copyViewerPath() {
  navigator.clipboard.writeText(currentViewerPath);
  const btn = document.getElementById('file-viewer-copy-btn');
  btn.innerHTML = '<i class="fa-solid fa-check" style="color:var(--accent-green)"></i>';
  setTimeout(() => btn.innerHTML = '<i class="fa-solid fa-copy"></i>', 1500);
}

function updateStatsAndPanel() {
  if (!Graph) return;

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
    if (activeNodeIds.has(sId) && activeNodeIds.has(tId)) activeEdgeCount++;
  });
  document.getElementById('edge-count').innerText = activeEdgeCount;

  activeNodes.forEach(node => {
    let connected = false;
    gData.links.forEach(l => {
      const sId = typeof l.source === 'object' ? l.source.id : l.source;
      const tId = typeof l.target === 'object' ? l.target.id : l.target;
      if ((sId === node.id && activeNodeIds.has(tId)) || (tId === node.id && activeNodeIds.has(sId))) connected = true;
    });
    if (!connected) isolatedCount++;
  });
  document.getElementById('unlinked-count').innerText = isolatedCount;

  const typeCounts = {};
  activeNodes.forEach(n => typeCounts[n.type] = (typeCounts[n.type] || 0) + 1);
  
  const typeBreakdownList = document.getElementById('type-breakdown-list');
  typeBreakdownList.innerHTML = '';
  Object.keys(typeCounts).sort((a,b) => typeCounts[b] - typeCounts[a]).forEach(t => {
    const dotColor = colors.type[t] || '#94a3b8';
    const item = document.createElement('div');
    item.className = 'list-item';
    item.onclick = () => {
      searchInput.value = t;
      applySearch(t);
    };
    item.innerHTML = `<span class="legend-item"><span class="color-dot" style="background:${dotColor};"></span> ${t}</span><span class="list-item-value">${typeCounts[t]}</span>`;
    typeBreakdownList.appendChild(item);
  });

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
  if (limitVal === 'all') limit = sortedNodes.length;
  else {
    const parsed = parseInt(limitVal, 10);
    if (!isNaN(parsed) && parsed > 0) limit = parsed;
  }
  
  sortedNodes.slice(0, limit).forEach(item => {
    const dotColor = colors.type[item.node.type] || '#94a3b8';
    const div = document.createElement('div');
    div.className = 'list-item';
    div.onclick = () => focusOnNode(item.node);
    div.innerHTML = `<span class="list-item-title"><span class="color-dot" style="background:${dotColor}; margin-right:6px;"></span>${item.node.id}</span><span class="list-item-value"><i class="fa-solid fa-circle-nodes" style="font-size:10px;"></i> ${item.deg}</span>`;
    topConnectedList.appendChild(div);
  });
}

function updateLegend() {
  const legendItems = document.getElementById('legend-items');
  legendItems.innerHTML = '';
  
  if (colorMode === 'type' || colorMode === 'status' || colorMode === 'trust') {
    Object.keys(colors[colorMode]).forEach(key => {
      if (key === 'default') return;
      const div = document.createElement('div');
      div.className = 'legend-item';
      div.innerHTML = `<span class="color-dot" style="background:${colors[colorMode][key]};"></span> <span style="text-transform: capitalize;">${key}</span>`;
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

const searchInput = document.getElementById('search-input');
const searchClearBtn = document.getElementById('search-clear-btn');

function applySearch(value) {
  searchQuery = value.toLowerCase().trim();
  searchClearBtn.style.display = searchQuery ? 'block' : 'none';
  updateStatsAndPanel();
  if (Graph) {
    Graph.nodeColor(getNodeColor);
    Graph.linkColor(link => window.getLinkColor(link));
  }
}

searchInput.addEventListener('input', (e) => applySearch(e.target.value));

searchClearBtn.addEventListener('click', () => {
  searchInput.value = '';
  searchInput.focus();
  applySearch('');
});

document.getElementById('list-limit-input').addEventListener('input', () => updateStatsAndPanel());

document.getElementById('color-mode-select').addEventListener('change', (e) => {
  colorMode = e.target.value;
  if (Graph) Graph.nodeColor(getNodeColor);
  updateLegend();
});

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
      if (Graph) Graph.nodeColor(getNodeColor);
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
      if (Graph) Graph.nodeColor(getNodeColor);
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

// Start everything
initApp();
fetchSpaces();
setInterval(fetchAuditors, 1000);
fetchAuditors();

// Settings Widget Interactivity
// Settings Widget Interactivity (Accordion)
window.toggleSettingsAccordion = function() {
  const body = document.getElementById('settings-accordion-body');
  const chevron = document.getElementById('settings-accordion-chevron');
  
  if (body.style.display === 'none') {
    body.style.display = 'block';
    chevron.style.transform = 'rotate(180deg)';
  } else {
    body.style.display = 'none';
    chevron.style.transform = 'rotate(0deg)';
  }
};

// Settings Config
const defaultSettings = {
  nodeRes: 8,
  particleDensity: 2,
  particleSpeed: 0.005,
  particleWidth: 1.8,
  linkDist: 40,
  chargeForce: -120,
  velocityDecay: 0.4,
  autoRotate: false,
  autoRotateSpeed: 1.0,
  showLeafLinks: false,
  hiddenNodeTypes: []
};

const SETTINGS_KEY = 'memory_os_graph_settings';

function loadSettings() {
  let saved = { ...defaultSettings };
  try {
    const data = localStorage.getItem(SETTINGS_KEY);
    if (data) saved = { ...saved, ...JSON.parse(data) };
  } catch(e) {}
  return saved;
}

function saveSetting(key, val) {
  let saved = loadSettings();
  saved[key] = val;
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(saved));
  } catch(e) {}
}

function applySettingsToUI(s) {
  if (document.getElementById('node-res-slider')) {
    document.getElementById('node-res-slider').value = s.nodeRes;
    document.getElementById('node-res-val').innerText = s.nodeRes;
  }
  if (document.getElementById('particle-density-slider')) {
    document.getElementById('particle-density-slider').value = s.particleDensity;
    document.getElementById('particle-density-val').innerText = s.particleDensity;
  }
  if (document.getElementById('particle-speed-slider')) {
    document.getElementById('particle-speed-slider').value = s.particleSpeed;
    document.getElementById('particle-speed-val').innerText = s.particleSpeed;
  }
  if (document.getElementById('particle-width-slider')) {
    document.getElementById('particle-width-slider').value = s.particleWidth;
    document.getElementById('particle-width-val').innerText = s.particleWidth;
  }
  if (document.getElementById('link-dist-slider')) {
    document.getElementById('link-dist-slider').value = s.linkDist;
    document.getElementById('link-dist-val').innerText = s.linkDist;
  }
  if (document.getElementById('charge-force-slider')) {
    document.getElementById('charge-force-slider').value = s.chargeForce;
    document.getElementById('charge-force-val').innerText = s.chargeForce;
  }
  if (document.getElementById('velocity-decay-slider')) {
    document.getElementById('velocity-decay-slider').value = s.velocityDecay;
    document.getElementById('velocity-decay-val').innerText = s.velocityDecay;
  }
  if (document.getElementById('auto-rotate-toggle')) {
    document.getElementById('auto-rotate-toggle').checked = s.autoRotate;
    isAutoRotate = s.autoRotate;
  }
  if (document.getElementById('auto-rotate-speed-slider')) {
    document.getElementById('auto-rotate-speed-slider').value = s.autoRotateSpeed;
    document.getElementById('auto-rotate-speed-val').innerText = s.autoRotateSpeed;
    window.currentAutoRotateSpeed = Number(s.autoRotateSpeed);
  }
  if (document.getElementById('show-leaf-links-toggle')) {
    document.getElementById('show-leaf-links-toggle').checked = s.showLeafLinks;
    window.showLeafLinks = s.showLeafLinks;
  }
  window.hiddenNodeTypes = new Set(Array.isArray(s.hiddenNodeTypes) ? s.hiddenNodeTypes : []);
}

function applySettingsToGraph(s) {
  if (!Graph) return;
  try { if (typeof Graph.nodeResolution === 'function') Graph.nodeResolution(Number(s.nodeRes)); } catch(e){}
  try { if (typeof Graph.linkDirectionalParticles === 'function') Graph.linkDirectionalParticles(link => {
    const sId = typeof link.source === 'object' ? link.source.id : link.source;
    return (nodeDegrees[sId] > 3) ? Number(s.particleDensity) : 0;
  }); } catch(e){}
  try { if (typeof Graph.linkDirectionalParticleSpeed === 'function') Graph.linkDirectionalParticleSpeed(Number(s.particleSpeed)); } catch(e){}
  try { if (typeof Graph.linkDirectionalParticleWidth === 'function') Graph.linkDirectionalParticleWidth(Number(s.particleWidth)); } catch(e){}
  
  // Re-trigger link width function to apply showLeafLinks
  try { if (typeof Graph.linkWidth === 'function') Graph.linkWidth(link => window.getLinkWidth(link)); } catch(e){}

  try { 
    if (Graph.d3Force('link')) { 
      Graph.d3Force('link').distance(Number(s.linkDist)); 
      if (Graph.graphData() && Graph.graphData().nodes && Graph.graphData().nodes.length > 0) Graph.d3ReheatSimulation(); 
    } 
  } catch(e){}
  try { 
    if (Graph.d3Force('charge')) { 
      Graph.d3Force('charge').strength(Number(s.chargeForce)); 
      if (Graph.graphData() && Graph.graphData().nodes && Graph.graphData().nodes.length > 0) Graph.d3ReheatSimulation(); 
    } 
  } catch(e){}
  try { if (typeof Graph.d3VelocityDecay === 'function') Graph.d3VelocityDecay(Number(s.velocityDecay)); } catch(e){}
}

window.applyAllSettingsSafely = function() {
  const s = loadSettings();
  applySettingsToUI(s);
  applySettingsToGraph(s);
};

// Listeners
if (document.getElementById('node-res-slider')) {
  document.getElementById('node-res-slider').addEventListener('input', (e) => {
    const val = parseInt(e.target.value);
    document.getElementById('node-res-val').innerText = val;
    saveSetting('nodeRes', val);
    if (Graph) { try { Graph.nodeResolution(val); } catch(e){} }
  });
}

if (document.getElementById('particle-density-slider')) {
  document.getElementById('particle-density-slider').addEventListener('input', (e) => {
    const val = parseInt(e.target.value);
    document.getElementById('particle-density-val').innerText = val;
    saveSetting('particleDensity', val);
    if (Graph) {
      try {
        Graph.linkDirectionalParticles(link => {
          const sId = typeof link.source === 'object' ? link.source.id : link.source;
          return (nodeDegrees[sId] > 3) ? val : 0;
        });
      } catch(e){}
    }
  });
}

if (document.getElementById('particle-speed-slider')) {
  document.getElementById('particle-speed-slider').addEventListener('input', (e) => {
    const val = parseFloat(e.target.value);
    document.getElementById('particle-speed-val').innerText = val;
    saveSetting('particleSpeed', val);
    if (Graph) { try { Graph.linkDirectionalParticleSpeed(val); } catch(e){} }
  });
}

if (document.getElementById('particle-width-slider')) {
  document.getElementById('particle-width-slider').addEventListener('input', (e) => {
    const val = parseFloat(e.target.value);
    document.getElementById('particle-width-val').innerText = val;
    saveSetting('particleWidth', val);
    if (Graph) { try { Graph.linkDirectionalParticleWidth(val); } catch(e){} }
  });
}

if (document.getElementById('link-dist-slider')) {
  document.getElementById('link-dist-slider').addEventListener('input', (e) => {
    const val = parseFloat(e.target.value);
    document.getElementById('link-dist-val').innerText = val;
    saveSetting('linkDist', val);
    if (Graph) {
      try {
        if (Graph.d3Force('link')) Graph.d3Force('link').distance(val);
        if (Graph.graphData() && Graph.graphData().nodes && Graph.graphData().nodes.length > 0) Graph.d3ReheatSimulation();
      } catch(e){}
    }
  });
}

if (document.getElementById('charge-force-slider')) {
  document.getElementById('charge-force-slider').addEventListener('input', (e) => {
    const val = parseFloat(e.target.value);
    document.getElementById('charge-force-val').innerText = val;
    saveSetting('chargeForce', val);
    if (Graph) {
      try {
        if (Graph.d3Force('charge')) Graph.d3Force('charge').strength(val);
        if (Graph.graphData() && Graph.graphData().nodes && Graph.graphData().nodes.length > 0) Graph.d3ReheatSimulation();
      } catch(e){}
    }
  });
}

if (document.getElementById('velocity-decay-slider')) {
  document.getElementById('velocity-decay-slider').addEventListener('input', (e) => {
    const val = parseFloat(e.target.value);
    document.getElementById('velocity-decay-val').innerText = val;
    saveSetting('velocityDecay', val);
    if (Graph) {
      try {
        if (typeof Graph.d3VelocityDecay === 'function') Graph.d3VelocityDecay(val);
      } catch(e){}
    }
  });
}

let isAutoRotate = false;
window.currentAutoRotateSpeed = 1.0;

if (document.getElementById('auto-rotate-toggle')) {
  document.getElementById('auto-rotate-toggle').addEventListener('change', (e) => {
    isAutoRotate = e.target.checked;
    saveSetting('autoRotate', isAutoRotate);
  });
}

if (document.getElementById('auto-rotate-speed-slider')) {
  document.getElementById('auto-rotate-speed-slider').addEventListener('input', (e) => {
    const val = parseFloat(e.target.value);
    document.getElementById('auto-rotate-speed-val').innerText = val;
    window.currentAutoRotateSpeed = val;
    saveSetting('autoRotateSpeed', val);
  });
}

if (document.getElementById('show-leaf-links-toggle')) {
  document.getElementById('show-leaf-links-toggle').addEventListener('change', (e) => {
    window.showLeafLinks = e.target.checked;
    saveSetting('showLeafLinks', window.showLeafLinks);
    if (Graph && typeof Graph.linkWidth === 'function') Graph.linkWidth(link => window.getLinkWidth(link));
  });
}

if (document.getElementById('reset-settings-btn')) {
  document.getElementById('reset-settings-btn').addEventListener('click', () => {
    try { localStorage.removeItem(SETTINGS_KEY); } catch(e){}
    window.applyAllSettingsSafely();
  });
}

// Custom auto-rotation that respects user zoom (dynamic radius)
window.lastUserInteraction = 0;

const graphElem = document.getElementById('3d-graph');
if (graphElem) {
  graphElem.addEventListener('wheel', () => window.lastUserInteraction = Date.now(), {passive: true});
  graphElem.addEventListener('mousedown', () => window.lastUserInteraction = Date.now(), {passive: true});
  graphElem.addEventListener('touchstart', () => window.lastUserInteraction = Date.now(), {passive: true});
}

setInterval(() => {
  if (isAutoRotate && Graph) {
    if (window.lastFocusTime && Date.now() - window.lastFocusTime < 1850) return;
    if (window.lastUserInteraction && Date.now() - window.lastUserInteraction < 600) return;
    
    // Pause auto-rotate if user is actively dragging/panning
    if (Graph.controls && Graph.controls().state !== undefined && Graph.controls().state !== -1) return;

    const camPos = Graph.cameraPosition();
    if (!camPos) return;

    const target = window.focusedNode || { x: 0, y: 0, z: 0 };
    
    const dx = camPos.x - target.x;
    const dz = camPos.z - target.z;
    const dist = Math.hypot(dx, dz);
    
    // If the camera is extremely close to the center axis, don't rotate to avoid NaN jumping
    if (dist > 0.1) {
      const currentAngle = Math.atan2(dx, dz);
      const baseSpeed = Math.PI / 600;
      const newAngle = currentAngle + (baseSpeed * window.currentAutoRotateSpeed);
      
      Graph.cameraPosition({
        x: target.x + dist * Math.sin(newAngle),
        y: camPos.y, // preserve user's vertical angle/height
        z: target.z + dist * Math.cos(newAngle)
      }, target);
    }
  }
}, 30);
