import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from memory_os.core.config import MemoryOSConfig
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.repository import MemoryRepository
from memory_os.core.models import MemoryNode, MemoryEdge
from memory_os.toolkit.spec_workflow import SpecManager

DOMAIN = "spec_workflow"

def sync_specs_to_memory(config: MemoryOSConfig) -> Dict[str, Any]:
    repo = MemoryRepository(FileSystemMemoryStorage(), config)
    all_nodes = repo.get_local_nodes()
    
    # 1. Identify and clear previous spec_workflow nodes
    stale_ids = {node.id for node in all_nodes if node.domain == DOMAIN}
    existing_nodes = [node for node in all_nodes if node.domain != DOMAIN]
    
    # 2. Get list of features
    manager = SpecManager(config.root_dir)
    features = manager.list_features()
    
    new_nodes: List[MemoryNode] = []
    new_edges: List[MemoryEdge] = []
    
    total_features = 0
    total_requirements = 0
    total_scenarios = 0
    total_tasks = 0
    
    for f in features:
        feature_id = f["feature_id"]
        feature_root = manager.specs_dir / feature_id
        paths = manager._paths(feature_root)
        
        spec_text = manager._read(paths.spec)
        plan_text = manager._read(paths.plan)
        tasks_text = manager._read(paths.tasks)
        
        if not spec_text:
            continue
            
        total_features += 1
        
        # Parse Status
        status_match = re.search(r"^Status:[ \t]*(.*)$", spec_text, flags=re.MULTILINE | re.IGNORECASE)
        status = status_match.group(1).strip().lower() if status_match else "draft"
        if status not in ["draft", "verified", "archived", "stale"]:
            status = "draft"
            
        title_match = re.search(r"^# Spec:[ \t]*(.*)$", spec_text, flags=re.MULTILINE)
        title = title_match.group(1).strip() if title_match else feature_id
        
        goal = manager._section_body(spec_text, "## Goal")
        
        # Create Feature Node
        feat_node_id = f"spec:feature:{feature_id}"
        new_nodes.append(MemoryNode(
            id=feat_node_id,
            type="spec_feature",
            summary=f"Spec Feature: {title}\nGoal: {goal}",
            status=status,
            trust="verified",
            domain=DOMAIN,
            tags=["spec", "feature"],
            evidence=[str(paths.spec.relative_to(config.root_dir))]
        ))
        
        # Parse Functional Requirements
        # Look for FR-xxx in bullets
        fr_list = []
        for line in spec_text.splitlines():
            line = line.strip()
            # E.g. - FR-001: The system MUST...
            match = re.match(r"^-[ \t]*(FR-\d{3})[ \t]*:[ \t]*(.*)$", line)
            if match:
                fr_id, desc = match.group(1), match.group(2).strip()
                node_id = f"spec:requirement:{feature_id}:{fr_id}"
                new_nodes.append(MemoryNode(
                    id=node_id,
                    type="spec_requirement",
                    summary=f"Requirement {fr_id}: {desc}",
                    status=status,
                    trust="verified",
                    domain=DOMAIN,
                    tags=["spec", "requirement", "fr"],
                    evidence=[str(paths.spec.relative_to(config.root_dir))]
                ))
                new_edges.append(MemoryEdge(
                    source=feat_node_id,
                    target=node_id,
                    type="contains",
                    domain=DOMAIN,
                    confidence=1.0,
                    evidence=[str(paths.spec.relative_to(config.root_dir))],
                    reason=f"Feature contains requirement {fr_id}"
                ))
                fr_list.append((fr_id, node_id))
                total_requirements += 1
                
        # Parse Acceptance Scenarios
        # Look for SC-xxx in bullets
        for line in spec_text.splitlines():
            line = line.strip()
            match = re.match(r"^-[ \t]*(SC-\d{3})[ \t]*:[ \t]*(.*)$", line)
            if match:
                sc_id, desc = match.group(1), match.group(2).strip()
                node_id = f"spec:scenario:{feature_id}:{sc_id}"
                new_nodes.append(MemoryNode(
                    id=node_id,
                    type="spec_scenario",
                    summary=f"Acceptance Scenario {sc_id}: {desc}",
                    status=status,
                    trust="verified",
                    domain=DOMAIN,
                    tags=["spec", "scenario", "sc"],
                    evidence=[str(paths.spec.relative_to(config.root_dir))]
                ))
                # Link scenario to feature by default
                new_edges.append(MemoryEdge(
                    source=feat_node_id,
                    target=node_id,
                    type="contains",
                    domain=DOMAIN,
                    confidence=1.0,
                    evidence=[str(paths.spec.relative_to(config.root_dir))],
                    reason=f"Feature contains scenario {sc_id}"
                ))
                total_scenarios += 1
                
        # Parse Tasks
        # Look for `- [ ] T001 ...` or `- [x] T001 ...`
        task_list = []
        for line in tasks_text.splitlines():
            line = line.strip()
            match = re.match(r"^-[ \t]*\[([ xX])\][ \t]*(T\d{3})[ \t]*(.*)$", line)
            if match:
                checked, t_id, desc = match.group(1), match.group(2), match.group(3).strip()
                node_id = f"spec:task:{feature_id}:{t_id}"
                t_status = "done" if checked.lower() == "x" else "pending"
                new_nodes.append(MemoryNode(
                    id=node_id,
                    type="spec_task",
                    summary=f"Task {t_id}: {desc}",
                    status=t_status,
                    trust="verified",
                    domain=DOMAIN,
                    tags=["spec", "task"],
                    evidence=[str(paths.tasks.relative_to(config.root_dir))]
                ))
                new_edges.append(MemoryEdge(
                    source=feat_node_id,
                    target=node_id,
                    type="contains",
                    domain=DOMAIN,
                    confidence=1.0,
                    evidence=[str(paths.tasks.relative_to(config.root_dir))],
                    reason=f"Feature contains task {t_id}"
                ))
                task_list.append((t_id, node_id))
                total_tasks += 1
                
        # Parse Traceability Table in tasks.md
        # E.g. | FR-001 | T001, T002 | pending |
        for line in tasks_text.splitlines():
            line = line.strip()
            table_match = re.match(r"^\|[ \t]*(FR-\d{3})[ \t]*\|[ \t]*([T\d{3}, \t]+)\|", line)
            if table_match:
                fr_id = table_match.group(1)
                t_ids_str = table_match.group(2)
                req_node_id = f"spec:requirement:{feature_id}:{fr_id}"
                for t_id in re.findall(r"T\d{3}", t_ids_str):
                    t_node_id = f"spec:task:{feature_id}:{t_id}"
                    new_edges.append(MemoryEdge(
                        source=req_node_id,
                        target=t_node_id,
                        type="implemented_by",
                        domain=DOMAIN,
                        confidence=1.0,
                        evidence=[str(paths.tasks.relative_to(config.root_dir))],
                        reason=f"Requirement {fr_id} is implemented by task {t_id}"
                    ))
                    
    # 3. Combine with non-domain nodes/edges and save
    valid_node_ids = {node.id for node in (existing_nodes + new_nodes)}
    repo.replace_nodes(existing_nodes + new_nodes)
    
    existing_edges = [
        edge for edge in repo.get_edges()
        if edge.domain != DOMAIN and edge.source not in stale_ids and edge.target not in stale_ids
        and edge.source in valid_node_ids and edge.target in valid_node_ids
    ]
    
    # Filter new edges to valid node ids only (safety)
    valid_new_edges = [
        e for e in new_edges
        if e.source in valid_node_ids and e.target in valid_node_ids
    ]
    
    repo.replace_edges(existing_edges + valid_new_edges)
    
    return {
        "features": total_features,
        "requirements": total_requirements,
        "scenarios": total_scenarios,
        "tasks": total_tasks,
        "nodes_upserted": len(new_nodes),
        "edges_upserted": len(valid_new_edges)
    }
