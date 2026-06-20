import os
import json
import re
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime
from memory_os.core.logger import get_logger
from memory_os.core.models import MemoryNode
from memory_os.modules.validator import MemoryValidator
from memory_os import MemoryOSConfig

logger = get_logger(__name__)

NOTION_API_URL = "https://api.notion.com/v1"

def get_property_value(page: dict, property_name: str):
    properties = page.get("properties", {})
    prop = properties.get(property_name, {})
    if not isinstance(prop, dict):
        return None
    p_type = prop.get("type")
    if not p_type:
        return None
    if p_type == "title":
        parts = prop.get("title", [])
        if not isinstance(parts, list):
            return ""
        return "".join(part.get("plain_text", "") if isinstance(part, dict) else str(part) for part in parts).strip()
    elif p_type == "rich_text":
        parts = prop.get("rich_text", [])
        if not isinstance(parts, list):
            return ""
        return "".join(part.get("plain_text", "") if isinstance(part, dict) else str(part) for part in parts).strip()
    elif p_type == "select":
        select_obj = prop.get("select")
        return select_obj.get("name", "").strip() if isinstance(select_obj, dict) else str(select_obj).strip() if select_obj else None
    elif p_type == "multi_select":
        items = prop.get("multi_select", [])
        if not isinstance(items, list):
            return []
        res = []
        for item in items:
            if isinstance(item, dict):
                res.append(item.get("name", "").strip())
            else:
                res.append(str(item).strip())
        return res
    elif p_type == "status":
        status_obj = prop.get("status")
        return status_obj.get("name", "").strip() if isinstance(status_obj, dict) else str(status_obj).strip() if status_obj else None
    elif p_type == "relation":
        relations = prop.get("relation", [])
        if not isinstance(relations, list):
            return []
        res = []
        for r in relations:
            if isinstance(r, dict):
                res.append(r.get("id"))
            else:
                res.append(str(r))
        return res
    return None

def get_block_markdown(block: dict, depth: int = 0) -> str:
    b_type = block.get("type")
    if not b_type:
        return ""
    
    content_obj = block.get(b_type, {})
    rich_text = []
    if isinstance(content_obj, dict):
        rich_text = content_obj.get("rich_text", [])
        
    plain_text = "".join(part.get("plain_text", "") if isinstance(part, dict) else str(part) for part in rich_text).strip()
    indent = "  " * depth
    
    if b_type == "paragraph":
        return f"{indent}{plain_text}\n\n"
    elif b_type == "heading_1":
        return f"\n{indent}# {plain_text}\n\n"
    elif b_type == "heading_2":
        return f"\n{indent}## {plain_text}\n\n"
    elif b_type == "heading_3":
        return f"\n{indent}### {plain_text}\n\n"
    elif b_type == "bulleted_list_item":
        return f"{indent}- {plain_text}\n"
    elif b_type == "numbered_list_item":
        return f"{indent}1. {plain_text}\n"
    elif b_type == "to_do":
        checked = content_obj.get("checked", False)
        box = "[x]" if checked else "[ ]"
        return f"{indent}- {box} {plain_text}\n"
    elif b_type == "code":
        language = content_obj.get("language", "text")
        code_text = "".join(part.get("plain_text", "") for part in content_obj.get("rich_text", []))
        return f"{indent}```{language}\n{code_text}\n{indent}```\n\n"
    elif b_type == "quote":
        return f"{indent}> {plain_text}\n\n"
    elif b_type == "callout":
        return f"{indent}> 💡 {plain_text}\n\n"
    elif b_type == "image":
        file_obj = content_obj.get("file") or content_obj.get("external") or {}
        img_url = file_obj.get("url") if isinstance(file_obj, dict) else ""
        caption_list = content_obj.get("caption", [])
        caption = "".join(part.get("plain_text", "") for part in caption_list).strip() if isinstance(caption_list, list) else ""
        if img_url:
            caption_str = caption or "Image attachment"
            return f"{indent}[Image: {caption_str}]({img_url})\n\n"
    elif b_type == "video":
        file_obj = content_obj.get("file") or content_obj.get("external") or {}
        video_url = file_obj.get("url") if isinstance(file_obj, dict) else ""
        caption_list = content_obj.get("caption", [])
        caption = "".join(part.get("plain_text", "") for part in caption_list).strip() if isinstance(caption_list, list) else ""
        if video_url:
            caption_str = caption or "Video attachment"
            return f"{indent}[Video: {caption_str}]({video_url})\n\n"
    elif b_type == "audio":
        file_obj = content_obj.get("file") or content_obj.get("external") or {}
        audio_url = file_obj.get("url") if isinstance(file_obj, dict) else ""
        caption_list = content_obj.get("caption", [])
        caption = "".join(part.get("plain_text", "") for part in caption_list).strip() if isinstance(caption_list, list) else ""
        if audio_url:
            caption_str = caption or "Audio attachment"
            return f"{indent}[Audio: {caption_str}]({audio_url})\n\n"
    elif b_type == "file":
        file_obj = content_obj.get("file") or content_obj.get("external") or {}
        file_url = file_obj.get("url") if isinstance(file_obj, dict) else ""
        name = content_obj.get("name", "File attachment")
        if file_url:
            return f"{indent}[File: {name}]({file_url})\n\n"
    elif b_type == "pdf":
        file_obj = content_obj.get("file") or content_obj.get("external") or {}
        file_url = file_obj.get("url") if isinstance(file_obj, dict) else ""
        caption_list = content_obj.get("caption", [])
        caption = "".join(part.get("plain_text", "") for part in caption_list).strip() if isinstance(caption_list, list) else ""
        if file_url:
            caption_str = caption or "PDF document"
            return f"{indent}[PDF: {caption_str}]({file_url})\n\n"
    elif b_type == "bookmark":
        url = content_obj.get("url", "")
        caption_list = content_obj.get("caption", [])
        caption = "".join(part.get("plain_text", "") for part in caption_list).strip() if isinstance(caption_list, list) else ""
        caption_str = caption or "Bookmark"
        if url:
            return f"{indent}[{caption_str}]({url})\n\n"
    elif b_type == "embed":
        url = content_obj.get("url", "")
        caption_list = content_obj.get("caption", [])
        caption = "".join(part.get("plain_text", "") for part in caption_list).strip() if isinstance(caption_list, list) else ""
        caption_str = f": {caption}" if caption else ""
        if url:
            return f"{indent}[Embed{caption_str}]({url})\n\n"
    elif b_type == "toggle":
        return f"{indent}- {plain_text}\n"
    elif b_type == "divider":
        return f"{indent}---\n\n"
    elif b_type == "child_page":
        title = content_obj.get("title", "Untitled Page")
        page_url = f"https://notion.so/{block.get('id').replace('-', '')}"
        return f"{indent}[Page: {title}]({page_url})\n\n"
    elif b_type == "child_database":
        title = content_obj.get("title", "Untitled Database")
        db_url = f"https://notion.so/{block.get('id').replace('-', '')}"
        return f"{indent}[Database: {title}]({db_url})\n\n"
    elif b_type == "link_to_page":
        ref_type = content_obj.get("type")
        ref_id = content_obj.get(ref_type) if ref_type else None
        if ref_id:
            clean_ref_id = ref_id.replace("-", "")
            ref_url = f"https://notion.so/{clean_ref_id}"
            return f"{indent}[Link to Page: {clean_ref_id}]({ref_url})\n\n"
    elif b_type == "table_row":
        cells = content_obj.get("cells", [])
        row_str = " | ".join("".join(c.get("plain_text", "") for c in cell) for cell in cells)
        return f"{indent}| {row_str} |\n"
    return ""

def get_page_content_markdown_recursive(api_key: str, block_id: str, depth: int = 0, max_depth: int = 5) -> str:
    if depth > max_depth:
        return ""
        
    url = f"{NOTION_API_URL}/blocks/{block_id}/children?page_size=100"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28"
    }
    markdown_parts = []
    has_more = True
    next_cursor = None
    
    try:
        while has_more:
            query_url = f"{url}&start_cursor={next_cursor}" if next_cursor else url
            req = urllib.request.Request(query_url, headers=headers, method="GET")
            with urllib.request.urlopen(req) as response:
                res = json.loads(response.read().decode("utf-8"))
                for block in res.get("results", []):
                    block_markdown = get_block_markdown(block, depth)
                    markdown_parts.append(block_markdown)
                    
                    if block.get("has_children", False):
                        if block.get("type") not in ("child_page", "child_database"):
                            child_markdown = get_page_content_markdown_recursive(
                                api_key=api_key,
                                block_id=block.get("id"),
                                depth=depth + 1,
                                max_depth=max_depth
                            )
                            markdown_parts.append(child_markdown)
                            
                has_more = res.get("has_more", False)
                next_cursor = res.get("next_cursor")
    except Exception as e:
        logger.error(f"Failed to fetch block children for {block_id}: {e}")
        
    return "".join(markdown_parts).strip()

def find_database_in_page(api_key: str, page_id: str) -> str:
    url = f"{NOTION_API_URL}/blocks/{page_id}/children"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28"
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode("utf-8"))
            for block in res.get("results", []):
                if block.get("type") == "child_database":
                    db_id = block.get("id").replace("-", "")
                    logger.info(f"Automatically resolved child database ID: {db_id}")
                    return db_id
    except Exception as e:
        logger.error(f"Failed to find child database in page {page_id}: {e}")
    return None

def query_notion_database(api_key: str, database_id: str, cursor: str = None) -> dict:
    url = f"{NOTION_API_URL}/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    payload = {}
    if cursor:
        payload["start_cursor"] = cursor
        
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        logger.error(f"Notion API error: {error_body}")
        raise ValueError(error_body)

def sync_with_notion(config: MemoryOSConfig, notion_api_key: str = None, notion_database_id: str = None, to_capsules: bool = False) -> bool:
    api_key = notion_api_key or os.environ.get("NOTION_API_KEY")
    database_id = notion_database_id or os.environ.get("NOTION_DATABASE_ID")
    
    if not api_key:
        logger.error("NOTION_API_KEY is not set. Skipping Notion sync.")
        return False
    if not database_id:
        logger.error("NOTION_DATABASE_ID is not set. Skipping Notion sync.")
        return False
        
    logger.info(f"Querying Notion database: {database_id}...")
    
    pages = []
    has_more = True
    next_cursor = None
    
    # Try querying the database
    resolved_db_id = database_id
    try:
        res = query_notion_database(api_key, resolved_db_id, next_cursor)
        results = res.get("results", [])
        pages.extend(results)
        has_more = res.get("has_more", False)
        next_cursor = res.get("next_cursor")
    except Exception as e:
        error_msg = str(e)
        if "is a page, not a database" in error_msg:
            logger.info(f"ID {database_id} is a page. Attempting to locate nested database block...")
            child_db_id = find_database_in_page(api_key, database_id)
            if child_db_id:
                resolved_db_id = child_db_id
                try:
                    res = query_notion_database(api_key, resolved_db_id, next_cursor)
                    results = res.get("results", [])
                    pages.extend(results)
                    has_more = res.get("has_more", False)
                    next_cursor = res.get("next_cursor")
                except Exception as retry_err:
                    logger.error(f"Failed to query resolved database {resolved_db_id}: {retry_err}")
                    return False
            else:
                logger.error(f"Could not locate any child database inside page {database_id}.")
                return False
        else:
            logger.error(f"Failed to fetch pages from Notion database: {e}")
            return False
            
    try:
        while has_more:
            res = query_notion_database(api_key, resolved_db_id, next_cursor)
            results = res.get("results", [])
            pages.extend(results)
            has_more = res.get("has_more", False)
            next_cursor = res.get("next_cursor")
    except Exception as e:
        logger.error(f"Failed to fetch paginated pages from Notion database: {e}")
        return False
        
    logger.info(f"Fetched {len(pages)} pages from Notion.")
    if not pages:
        logger.warning("No pages found in Notion database.")
        return True
        
    # Temporary storage for page contents to scan links in the second pass
    page_contents = {}
    page_titles = {}
    
    if to_capsules:
        # Mode A: Sync Notion pages as Task Capsules
        capsules_file = config.capsules_file
        existing_capsules = []
        if capsules_file.exists():
            with open(capsules_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        existing_capsules.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                        
        seen_tasks = {cap.get("task") for cap in existing_capsules}
        added_count = 0
        
        logger.info("Downloading file contents and compiling task capsules...")
        
        for idx, page in enumerate(pages, 1):
            page_id = page.get("id", "").replace("-", "")
            
            title_prop = None
            for k, v in page.get("properties", {}).items():
                if isinstance(v, dict) and v.get("type") == "title":
                    title_prop = k
                    break
            
            title = get_property_value(page, title_prop) if title_prop else ""
            if not title:
                title = f"Notion Page {page_id}"
                
            if title in seen_tasks:
                continue
                
            url = page.get("url", "")
            last_edited = page.get("last_edited_time", "")
            freshness = last_edited[:19] + "Z" if last_edited else datetime.utcnow().isoformat()[:19] + "Z"
            
            node_type = get_property_value(page, "Type") or "fact"
            status = get_property_value(page, "Status") or "verified"
            trust = get_property_value(page, "Trust") or "verified"
            tags = get_property_value(page, "Tags") or []
            
            logger.info(f"[{idx}/{len(pages)}] Fetching page body for: {title}")
            page_markdown = get_page_content_markdown_recursive(api_key, page_id)
            
            resolution = f"Notion Import: Type={node_type}, Status={status}, Trust={trust}, Tags={tags}"
            
            capsule = {
                "timestamp": freshness,
                "task": title,
                "workflow": "product",
                "step": "micro",
                "files_modified": [url] if url else [],
                "files_viewed": [],
                "context_tokens": 0,
                "tools_used": ["notion_sync"],
                "hurdles_regression": "",
                "resolution": resolution,
                "lessons_learned": page_markdown
            }
            
            existing_capsules.append(capsule)
            seen_tasks.add(title)
            added_count += 1
            
        capsules_file.parent.mkdir(parents=True, exist_ok=True)
        with open(capsules_file, "w", encoding="utf-8") as f:
            for cap in existing_capsules:
                f.write(json.dumps(cap, ensure_ascii=False) + "\n")
                
        logger.info(f"Task capsules sync complete. Appended {added_count} new task capsules.")
        return True
        
    else:
        # Mode B: Sync Notion pages directly as Memory Nodes
        nodes_path = config.memory_dir / "nodes.jsonl"
        existing_nodes = {}
        if nodes_path.exists():
            with open(nodes_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        node_data = json.loads(line)
                        if "id" in node_data:
                            existing_nodes[node_data["id"]] = node_data
                    except json.JSONDecodeError:
                        continue

        updated_count = 0
        created_count = 0
        
        logger.info("Downloading file contents for direct memory nodes...")
        
        # 1. First Pass: Map properties and body content of each page to MemoryNode
        new_or_updated_nodes = {}
        for idx, page in enumerate(pages, 1):
            page_id = page.get("id", "").replace("-", "")
            
            title_prop = None
            for k, v in page.get("properties", {}).items():
                if isinstance(v, dict) and v.get("type") == "title":
                    title_prop = k
                    break
            
            title = get_property_value(page, title_prop) if title_prop else ""
            if not title:
                title = f"Notion Page {page_id}"
                
            page_titles[page_id] = title
            
            node_id = get_property_value(page, "ID") or get_property_value(page, "Id") or get_property_value(page, "Node ID")
            if not node_id:
                clean_title = "".join(c if c.isalnum() else "_" for c in title.lower())
                clean_title = "_".join(filter(None, clean_title.split("_")))
                if clean_title:
                    node_id = f"notion.{clean_title}"
                else:
                    node_id = f"notion.{page_id}"
            else:
                node_id = str(node_id).strip()
                
            node_type = get_property_value(page, "Type") or "fact"
            node_type = str(node_type).lower().strip()
            from memory_os.modules.validator import VALID_NODE_TYPES
            if node_type not in VALID_NODE_TYPES:
                node_type = "fact"
                
            status = get_property_value(page, "Status") or "verified"
            status = str(status).lower().strip()
            if status not in {"draft", "observed", "verified", "stale", "superseded"}:
                status = "verified"
                
            trust = get_property_value(page, "Trust") or "verified"
            trust = str(trust).lower().strip()
            if trust not in {"verified", "unverified", "extracted", "inferred"}:
                trust = "verified"
                
            tags = get_property_value(page, "Tags") or []
            if not isinstance(tags, list):
                tags = [str(tags)]
                
            url = page.get("url", "")
            evidence = [url] if url else []
            
            last_edited = page.get("last_edited_time", "")
            freshness = last_edited[:19] if last_edited else datetime.utcnow().isoformat()[:19]
            
            logger.info(f"[{idx}/{len(pages)}] Fetching details for: {title}")
            page_markdown = get_page_content_markdown_recursive(api_key, page_id)
            
            page_contents[page_id] = page_markdown
            
            summary = page_markdown.strip()
            if len(summary) < 20:
                summary = f"{title} (Status: {status}, Type: {node_type}). {page_markdown}".strip()
            if len(summary) < 20:
                summary = f"Notion database entry: {title}"
            if len(summary) < 20:
                summary = summary.ljust(20, ".")
                
            if len(summary) > 800:
                summary = summary[:797] + "..."
                
            node = {
                "id": node_id,
                "type": node_type,
                "summary": summary,
                "evidence": evidence,
                "status": status,
                "freshness": freshness,
                "trust": trust,
                "tags": tags,
                "related_nodes": []
            }
            
            new_or_updated_nodes[page_id] = node

        # 2. Second Pass: Resolve Relations
        page_id_to_node_id = {pid: node["id"] for pid, node in new_or_updated_nodes.items()}
        all_notion_page_ids = set(new_or_updated_nodes.keys())
        
        title_to_page_id = {}
        for pid, title in page_titles.items():
            clean_title = title.strip().lower()
            if len(clean_title) >= 4:
                title_to_page_id[clean_title] = pid

        edges_to_write = []
        uuid_pattern = re.compile(r'\b([a-f0-9]{8}-?[a-f0-9]{4}-?[a-f0-9]{4}-?[a-f0-9]{4}-?[a-f0-9]{12})\b', re.IGNORECASE)
        
        for page in pages:
            page_id = page.get("id", "").replace("-", "")
            node = new_or_updated_nodes.get(page_id)
            if not node:
                continue
                
            related_ids = set()
            
            # A. Extract explicit relations from database properties
            for prop_name, prop_val in page.get("properties", {}).items():
                if isinstance(prop_val, dict) and prop_val.get("type") == "relation":
                    relations = get_property_value(page, prop_name) or []
                    for r_id in relations:
                        clean_r_id = r_id.replace("-", "")
                        related_ids.add(clean_r_id)
                        
            # B. Extract implicit relations from UUID links/mentions
            page_text = page_contents.get(page_id, "")
            matches = uuid_pattern.findall(page_text)
            for m in matches:
                clean_m = m.replace("-", "").lower()
                if clean_m in all_notion_page_ids and clean_m != page_id:
                    related_ids.add(clean_m)
                    
            # C. Extract implicit relations from automatic wiki-linking of titles
            page_text_lower = page_text.lower()
            for title_phrase, target_pid in title_to_page_id.items():
                if target_pid == page_id:
                    continue
                
                escaped_phrase = re.escape(title_phrase)
                phrase_pattern = re.compile(rf'\b{escaped_phrase}\b')
                if phrase_pattern.search(page_text_lower):
                    related_ids.add(target_pid)
                    
            # D. Compile unique relations into edges and related_nodes
            for r_id in related_ids:
                target_node_id = page_id_to_node_id.get(r_id)
                if target_node_id:
                    if target_node_id not in node["related_nodes"]:
                        node["related_nodes"].append(target_node_id)
                    
                    edges_to_write.append({
                        "source": node["id"],
                        "target": target_node_id,
                        "type": "depends_on"
                    })

        # Write nodes back to nodes.jsonl
        final_nodes = {}
        for node_id, existing_node in existing_nodes.items():
            final_nodes[node_id] = existing_node
            
        for page_id, node in new_or_updated_nodes.items():
            node_id = node["id"]
            if node_id in final_nodes:
                final_nodes[node_id].update(node)
                updated_count += 1
            else:
                final_nodes[node_id] = node
                created_count += 1
                
        config.memory_dir.mkdir(parents=True, exist_ok=True)
        with open(nodes_path, "w", encoding="utf-8") as f:
            for node in final_nodes.values():
                f.write(json.dumps(node, ensure_ascii=False) + "\n")
                
        # Write edges back to edges.jsonl
        edges_path = config.memory_dir / "edges.jsonl"
        existing_edges = []
        if edges_path.exists():
            with open(edges_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        existing_edges.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                        
        seen_edges = set()
        for edge in existing_edges:
            seen_edges.add((edge.get("source"), edge.get("target"), edge.get("type")))
            
        new_edges_added = 0
        for edge in edges_to_write:
            edge_key = (edge["source"], edge["target"], edge["type"])
            if edge_key not in seen_edges:
                existing_edges.append(edge)
                seen_edges.add(edge_key)
                new_edges_added += 1
                
        with open(edges_path, "w", encoding="utf-8") as f:
            for edge in existing_edges:
                f.write(json.dumps(edge, ensure_ascii=False) + "\n")
                
        logger.info(f"Notion sync complete. Created {created_count} nodes, updated {updated_count} nodes, added {new_edges_added} edges.")
        
        # Run validation
        validator = MemoryValidator(config)
        errors = []
        errors.extend(validator.validate_nodes())
        errors.extend(validator.validate_edges())
        errors.extend(validator.validate_events())
        if errors:
            logger.warning("Validation warnings/errors after Notion sync:\n" + "\n".join(errors))
            
        # Run SQLite FTS sync
        logger.info("Syncing memories to SQLite search index...")
        from memory_os.core.repository import MemoryRepository
        from memory_os.core.storage import FileSystemMemoryStorage
        repo = MemoryRepository(FileSystemMemoryStorage(), config)
        repo.sync_graph_nodes()
        logger.info("SQLite search index synced successfully.")
        
        return True
