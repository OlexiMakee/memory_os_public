import os
import glob

def replace_in_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        new_content = content.replace(" memos ", " memory_os ")
        new_content = new_content.replace("`memos ", "`memory_os ")
        new_content = new_content.replace("memos.", "memory_os.")
        new_content = new_content.replace("'memos ", "'memory_os ")
        new_content = new_content.replace('"memos"', '"memory_os"')
        new_content = new_content.replace('"memos ', '"memory_os ')
        new_content = new_content.replace('memos`', 'memory_os`')
        new_content = new_content.replace('memos:', 'memory_os:')
        
        # specific cases from search results
        new_content = new_content.replace("Memos CLI", "Memory OS CLI")
        new_content = new_content.replace("Portable Memos", "Portable Memory OS")
        
        if content != new_content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Updated {filepath}")
    except Exception as e:
        print(f"Skipping {filepath}: {e}")

search_patterns = [
    "agent_context/*.md",
    "test_auto.py",
    "append_log.py",
    "src/memory_os/*.py",
    "src/memory_os/**/*.py"
]

for pattern in search_patterns:
    for filepath in glob.glob(pattern, recursive=True):
        replace_in_file(filepath)

print("Replacement complete.")
