import os
import json
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime
from memory_os.core.logger import get_logger
from memory_os.modules.validator import MemoryValidator
from memory_os import MemoryOSConfig

logger = get_logger(__name__)

GDRIVE_API_URL = "https://www.googleapis.com/drive/v3"

def query_gdrive_files(access_token: str, folder_id: str, page_token: str = None) -> dict:
    query = f"'{folder_id}' in parents and trashed = false"
    fields = "nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink)"
    
    params = {
        "q": query,
        "fields": fields
    }
    if page_token:
        params["pageToken"] = page_token
        
    url = f"{GDRIVE_API_URL}/files?{urllib.parse.urlencode(params)}"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        logger.error(f"Google Drive API error: {error_body}")
        raise ValueError(f"Google Drive query failed: {error_body}")

def download_gdrive_file_content(access_token: str, file_id: str, mime_type: str) -> str:
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    if mime_type == "application/vnd.google-apps.document":
        # Google Doc: export as plain text
        params = {"mimeType": "text/plain"}
        url = f"{GDRIVE_API_URL}/files/{file_id}/export?{urllib.parse.urlencode(params)}"
    else:
        # Standard file: download alt=media
        params = {"alt": "media"}
        url = f"{GDRIVE_API_URL}/files/{file_id}?{urllib.parse.urlencode(params)}"
        
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req) as response:
            # Try to decode file content as utf-8, fallback to printable representation if binary
            content_bytes = response.read()
            try:
                return content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                return f"[Binary file of type {mime_type}]"
    except urllib.error.HTTPError as e:
        # We log and return a placeholder so the sync process doesn't fail on one unreadable file
        logger.warning(f"Could not read content for file {file_id}: {e.read().decode('utf-8')}")
        return ""

def is_media_mime_type(mime_type: str) -> bool:
    mt = mime_type.lower().strip()
    if mt.startswith("image/") or mt.startswith("video/") or mt.startswith("audio/"):
        return True
    if mt in ("application/pdf", "application/zip", "application/x-zip-compressed", "application/octet-stream"):
        return True
    if mt.startswith("application/vnd.google-apps."):
        media_apps = {
            "application/vnd.google-apps.drawing",
            "application/vnd.google-apps.photo",
            "application/vnd.google-apps.video",
            "application/vnd.google-apps.audio",
            "application/vnd.google-apps.presentation"
        }
        return mt in media_apps
    return False

def sync_with_gdrive(config: MemoryOSConfig, access_token: str = None, folder_id: str = None, to_capsules: bool = False) -> bool:
    token = access_token or os.environ.get("GDRIVE_ACCESS_TOKEN")
    folder = folder_id or os.environ.get("GDRIVE_FOLDER_ID")
    
    if not token:
        logger.error("GDRIVE_ACCESS_TOKEN is not set. Skipping Google Drive sync.")
        return False
    if not folder:
        logger.error("GDRIVE_FOLDER_ID is not set. Skipping Google Drive sync.")
        return False
        
    logger.info(f"Querying Google Drive folder: {folder}...")
    
    files = []
    has_more = True
    next_page_token = None
    
    try:
        while has_more:
            res = query_gdrive_files(token, folder, next_page_token)
            files.extend(res.get("files", []))
            next_page_token = res.get("nextPageToken")
            has_more = next_page_token is not None
    except Exception as e:
        logger.error(f"Failed to query files in Google Drive: {e}")
        return False
        
    logger.info(f"Found {len(files)} files in Google Drive folder.")
    if not files:
        logger.warning("No files found in Google Drive folder.")
        return True
        
    if to_capsules:
        # Mode A: Sync files as Task Capsules
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
        for idx, file_info in enumerate(files, 1):
            file_name = file_info.get("name", f"Google Drive File {file_info.get('id')}")
            if file_name in seen_tasks:
                continue
                
            file_id = file_info.get("id")
            mime_type = file_info.get("mimeType", "text/plain")
            modified_time = file_info.get("modifiedTime", "")
            freshness = modified_time[:19] + "Z" if modified_time else datetime.utcnow().isoformat()[:19] + "Z"
            url = file_info.get("webViewLink", "")
            
            logger.info(f"[{idx}/{len(files)}] Processing file: {file_name}")
            if is_media_mime_type(mime_type):
                logger.info(f"Skipping download of media file: {file_name}")
                file_text = f"[{file_name}]({url})"
            else:
                file_text = download_gdrive_file_content(token, file_id, mime_type)
            
            resolution = f"Google Drive Import: File ID={file_id}, mimeType={mime_type}"
            
            capsule = {
                "timestamp": freshness,
                "task": file_name,
                "workflow": "product",
                "step": "micro",
                "files_modified": [url] if url else [],
                "files_viewed": [],
                "context_tokens": 0,
                "tools_used": ["gdrive_sync"],
                "hurdles_regression": "",
                "resolution": resolution,
                "lessons_learned": file_text
            }
            
            existing_capsules.append(capsule)
            seen_tasks.add(file_name)
            added_count += 1
            
        capsules_file.parent.mkdir(parents=True, exist_ok=True)
        with open(capsules_file, "w", encoding="utf-8") as f:
            for cap in existing_capsules:
                f.write(json.dumps(cap, ensure_ascii=False) + "\n")
                
        logger.info(f"Google Drive sync complete. Appended {added_count} task capsules.")
        logger.info("You can now run 'python -m memory_os compact' to compact them via LLM.")
        return True
        
    else:
        # Mode B: Sync files directly as Memory Nodes
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
        
        for idx, file_info in enumerate(files, 1):
            file_id = file_info.get("id")
            file_name = file_info.get("name", "")
            
            # Generate clean node ID
            clean_name = "".join(c if c.isalnum() else "_" for c in file_name.lower())
            clean_name = "_".join(filter(None, clean_name.split("_")))
            node_id = f"gdrive.{clean_name}" if clean_name else f"gdrive.{file_id}"
            
            mime_type = file_info.get("mimeType", "text/plain")
            modified_time = file_info.get("modifiedTime", "")
            freshness = modified_time[:19] if modified_time else datetime.utcnow().isoformat()[:19]
            url = file_info.get("webViewLink", "")
            
            logger.info(f"[{idx}/{len(files)}] Processing file: {file_name}")
            if is_media_mime_type(mime_type):
                logger.info(f"Skipping download of media file: {file_name}")
                file_text = f"[{file_name}]({url})"
            else:
                file_text = download_gdrive_file_content(token, file_id, mime_type)
            
            # Map type based on title keywords or default to fact
            node_type = "fact"
            file_name_lower = file_name.lower()
            if "rule" in file_name_lower:
                node_type = "rule"
            elif "policy" in file_name_lower:
                node_type = "policy"
            elif "config" in file_name_lower:
                node_type = "config"
                
            summary = file_text.strip()
            if len(summary) < 20:
                summary = f"Google Drive File: {file_name}. {file_text}".strip()
            if len(summary) < 20:
                summary = summary.ljust(20, ".")
                
            if len(summary) > 800:
                summary = summary[:797] + "..."
                
            node = {
                "id": node_id,
                "type": node_type,
                "summary": summary,
                "evidence": [url] if url else [],
                "status": "verified",
                "freshness": freshness,
                "trust": "verified",
                "tags": ["gdrive"],
                "related_nodes": []
            }
            
            if node_id in existing_nodes:
                existing_nodes[node_id].update(node)
                updated_count += 1
            else:
                existing_nodes[node_id] = node
                created_count += 1
                
        config.memory_dir.mkdir(parents=True, exist_ok=True)
        with open(nodes_path, "w", encoding="utf-8") as f:
            for node in existing_nodes.values():
                f.write(json.dumps(node, ensure_ascii=False) + "\n")
                
        logger.info(f"Google Drive sync complete. Created {created_count} nodes, updated {updated_count} nodes.")
        
        # Run validation
        validator = MemoryValidator(config)
        errors = []
        errors.extend(validator.validate_nodes())
        errors.extend(validator.validate_edges())
        errors.extend(validator.validate_events())
        if errors:
            logger.warning("Validation warnings/errors after Google Drive sync:\n" + "\n".join(errors))
            
        # Run SQLite FTS sync
        logger.info("Syncing memories to SQLite search index...")
        from memory_os.core.repository import MemoryRepository
        from memory_os.core.storage import FileSystemMemoryStorage
        repo = MemoryRepository(FileSystemMemoryStorage(), config)
        repo.sync_graph_nodes()
        logger.info("SQLite search index synced successfully.")
        
        return True
