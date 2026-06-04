"""
Prompt Formatter Service
Memory OS — Portable Agent Memory Kernel
"""

import re
from typing import List, Dict, Any

def wrap_in_xml(tag_name: str, content: str) -> str:
    """Wraps text content inside strict XML tags."""
    return f"<{tag_name}>\n{content.strip()}\n</{tag_name}>"

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
