import re

with open("src/memory_os/toolkit/notion_sync.py", "r") as f:
    lines = f.readlines()

new_lines = []
inside_sync = False
sync_lines = []

for line in lines:
    if line.startswith("def sync_with_notion("):
        inside_sync = True
    if inside_sync:
        sync_lines.append(line)
    else:
        new_lines.append(line)

sync_code = "".join(sync_lines)

# We will break sync_code into `class NotionExtractor(DataExtractor): ...`
# The class will take `api_key` and `database_id`.
# The existing logic has a lot of `config.capsules_file` and `config.memory_dir`. We need to just return lists!

print("sync_with_notion length:", len(sync_lines))
