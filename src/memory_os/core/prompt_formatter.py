"""
Prompt Formatter Service
Memory OS — Portable Agent Memory Kernel
"""

import re
from typing import List, Dict, Any
from xml.sax.saxutils import escape

def wrap_in_xml(tag_name: str, content: str) -> str:
    """Wraps text content inside strict XML tags.

    Escapes '<', '>', and '&' in content first — otherwise a literal
    '</tag_name>' inside content (e.g. attacker-controlled transcript text)
    closes the wrapper early, leaving the rest of content outside it from
    the model's perspective.
    """
    return f"<{tag_name}>\n{escape(content.strip())}\n</{tag_name}>"

def format_user_profile(profile_dict: Dict[str, Any]) -> str:
    """
    Formats a dictionary of user preferences into dense key=value format.
    Example:
      proj=local_rag_chatbot
      stack=python,ollama,qdrant
    """
    lines = []
    for k, v in profile_dict.items():
        if isinstance(v, list):
            val_str = ",".join(str(x) for x in v)
        else:
            val_str = str(v)
        lines.append(f"{k}={val_str}")
    return "\n".join(lines)

def markdown_table_to_html(md_table: str) -> str:
    """
    Converts a Markdown table structure into minified HTML table format.
    Strips out markdown divider lines and yields a single-line minified table.
    """
    lines = [line.strip() for line in md_table.splitlines() if line.strip()]
    if not lines:
        return ""
        
    html_parts = ["<table>"]
    is_first = True
    
    for line in lines:
        # Skip markdown table dividers e.g. |---|---|
        if re.match(r"^\|?\s*:?-+:?\s*(\|?\s*:?-+:?\s*)*\|?$", line):
            continue
            
        # Parse columns
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
            
        cols = [col.strip() for col in line.split("|")]
        
        row_tag = "th" if is_first else "td"
        row_str = "<tr>" + "".join(f"<{row_tag}>{c}</{row_tag}>" for c in cols) + "</tr>"
        html_parts.append(row_str)
        is_first = False
        
    html_parts.append("</table>")
    return "".join(html_parts)

def compress_dialog(dialog_list: List[Dict[str, str]]) -> str:
    """
    Compresses multi-turn dialogue lists into a sequence of concise statements
    for the model prompt context, stripping formatting overhead.
    """
    statements = []
    for turn in dialog_list:
        role = turn.get("role", "user")
        content = turn.get("content", "").strip()
        if content:
            # Flatten statement
            flat_content = re.sub(r"\s+", " ", content)
            statements.append(f"{role}: {flat_content}")
    return "\n".join(statements)

def strip_whitespace_noise(text: str) -> str:
    """Strips excessive indentation, pretty-print spaces, and double newlines."""
    # Remove leading/trailing spaces on each line first
    lines = [line.strip() for line in text.splitlines()]
    joined = "\n".join(lines)
    # Replace 3 or more newlines with exactly 2 newlines
    cleaned = re.sub(r"\n{3,}", "\n\n", joined)
    return cleaned.strip()

def format_memory_tier_status(current_ram_items: int, max_ram_items: int = 20) -> str:
    """
    Injects a system prompt payload informing the agent of its current Memory OS RAM usage.
    Gives the agent OS-level memory management awareness to prevent context bloat.
    """
    status_lines = [
        f"RAM Usage: {current_ram_items} / {max_ram_items} items."
    ]
    
    if current_ram_items >= max_ram_items * 0.8:
        status_lines.append(
            "WARNING: Close to capacity. You MUST explicitly use your tool `page_out_to_disk` "
            "(deprecate/upsert) to free up context space or you will lose information."
        )
    elif current_ram_items >= max_ram_items:
        status_lines.append(
            "CRITICAL: RAM Overload. Page out immediately to Disk."
        )
    else:
        status_lines.append(
            "RAM state healthy. You have space for more context."
        )
        
    return wrap_in_xml("memory_tier_status", "\n".join(status_lines))
