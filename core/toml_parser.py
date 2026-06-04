"""
TOML Parser Utility
Memory OS — Portable Agent Memory Kernel
"""

from typing import Dict, Any

def parse_toml(toml_str: str) -> Dict[str, Any]:
    """
    Parses a simple TOML string into a nested Python dictionary.
    Supports comments, sections, nested sections, strings, integers, floats, booleans, and arrays.
    """
    result: Dict[str, Any] = {}
    current_section = None
    
    for line in toml_str.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
            
        # Parse section header e.g. [section] or [section.subsection]
        if line.startswith('[') and line.endswith(']'):
            section_name = line[1:-1].strip()
            parts = [p.strip() for p in section_name.split('.')]
            current_section = result
            for part in parts:
                current_section = current_section.setdefault(part, {})
            continue
            
        # Parse key = value
        if '=' in line:
            key, val = line.split('=', 1)
            key = key.strip()
            val = val.strip()
            
            # Remove inline comment if present (check outside of quotes)
            if '#' in val:
                in_quote = False
                quote_char = None
                comment_idx = -1
                for idx, char in enumerate(val):
                    if char in ('"', "'"):
                        if not in_quote:
                            in_quote = True
                            quote_char = char
                        elif char == quote_char:
                            in_quote = False
                            quote_char = None
                    elif char == '#' and not in_quote:
                        comment_idx = idx
                        break
                if comment_idx != -1:
                    val = val[:comment_idx].strip()
            
            # Parse value
            parsed_val: Any = None
            if val.startswith('"') and val.endswith('"'):
                parsed_val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                parsed_val = val[1:-1]
            elif val.lower() in ('true', 'yes'):
                parsed_val = True
            elif val.lower() in ('false', 'no'):
                parsed_val = False
            elif val.startswith('[') and val.endswith(']'):
                items = []
                raw_items = []
                current_item = []
                in_q = False
                q_c = None
                for char in val[1:-1]:
                    if char in ('"', "'"):
                        if not in_q:
                            in_q = True
                            q_c = char
                        elif char == q_c:
                            in_q = False
                            q_c = None
                        current_item.append(char)
                    elif char == ',' and not in_q:
                        raw_items.append(''.join(current_item).strip())
                        current_item = []
                    else:
                        current_item.append(char)
                if current_item:
                    raw_items.append(''.join(current_item).strip())
                
                for item in raw_items:
                    if not item:
                        continue
                    if item.startswith('"') and item.endswith('"'):
                        items.append(item[1:-1])
                    elif item.startswith("'") and item.endswith("'"):
                        items.append(item[1:-1])
                    else:
                        try:
                            if '.' in item:
                                items.append(float(item))
                            else:
                                items.append(int(item))
                        except ValueError:
                            items.append(item)
                parsed_val = items
            else:
                try:
                    if '.' in val:
                        parsed_val = float(val)
                    else:
                        parsed_val = int(val)
                except ValueError:
                    parsed_val = val
                    
            if current_section is not None:
                current_section[key] = parsed_val
            else:
                result[key] = parsed_val
                
    return result

def load_toml_file(file_path: str) -> Dict[str, Any]:
    """Utility to load and parse a TOML file path."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return parse_toml(f.read())
