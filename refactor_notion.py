import re

with open("src/memory_os/toolkit/notion_sync.py", "r") as f:
    content = f.read()

# Replace config and file I/O imports
content = content.replace("from memory_os import MemoryOSConfig", "from memory_os import MemoryOSConfig\nfrom memory_os.toolkit.base_extractor import DataExtractor, DocumentIngestor")

# We want to replace `def sync_with_notion(` with `class NotionExtractor(DataExtractor):`
# but it's easier to just write the new class and replace the function.

new_class_str = """
class NotionExtractor(DataExtractor):
    def __init__(self, api_key: str, database_id: str):
        self.api_key = api_key
        self.database_id = database_id

    def _get_all_pages(self):
        pages = []
        has_more = True
        next_cursor = None
        logger.info(f"Querying Notion database: {self.database_id}...")
        try:
            while has_more:
                res = query_notion_database(self.api_key, self.database_id, next_cursor)
                pages.extend(res.get("results", []))
                next_cursor = res.get("next_cursor")
                has_more = res.get("has_more", False)
        except Exception as e:
            logger.error(f"Failed to query Notion database: {e}")
            return []
            
        logger.info(f"Found {len(pages)} pages in Notion database.")
        return pages

    def extract_capsules(self) -> List[Dict[str, Any]]:
        pages = self._get_all_pages()
        capsules = []
        
        for idx, page in enumerate(pages, 1):
            page_id = page.get("id")
            logger.info(f"[{idx}/{len(pages)}] Processing Notion page as capsule: {page_id}")
            
            props = page.get("properties", {})
            title_text = "Untitled Notion Page"
            for k, v in props.items():
                if v.get("type") == "title":
                    title_arr = v.get("title", [])
                    if title_arr:
                        title_text = "".join([t.get("plain_text", "") for t in title_arr])
                    break
                    
            page_content = fetch_page_content(self.api_key, page_id)
            url = page.get("url", "")
            modified_time = page.get("last_edited_time", "")
            freshness = modified_time[:19] + "Z" if modified_time else datetime.utcnow().isoformat()[:19] + "Z"
            
            resolution = f"Notion Import: Page ID={page_id}"
            
            capsule = {
                "timestamp": freshness,
                "task": title_text,
                "workflow": "product",
                "step": "micro",
                "files_modified": [url] if url else [],
                "files_viewed": [],
                "context_tokens": 0,
                "tools_used": ["notion_sync"],
                "hurdles_regression": "",
                "resolution": resolution,
                "lessons_learned": page_content
            }
            capsules.append(capsule)
            
        return capsules

    def extract_nodes_and_edges(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        pages = self._get_all_pages()
        nodes = []
        edges = []
        
        # We need the relations logic from sync_with_notion.
        # I'll let the user logic from original sync_with_notion remain intact, just append to `nodes` and `edges` lists.
"""

import sys
# It's better to just manually edit `notion_sync.py` by removing the file I/O part.
# But it's too big and complex.
