import re
import difflib
from pathlib import Path
from .search_replace import flexible_search_and_replace

def do_replace(fname, content, before_text, after_text, fence=("```", "```")):
    before_text = strip_quoted_wrapping(before_text, fname, fence)
    after_text = strip_quoted_wrapping(after_text, fname, fence)
    
    fname = Path(fname)
    if not fname.exists() and not before_text.strip():
        # This part usually happens in Aider's IO/Repo, 
        # but we'll handle basic new file creation here if content is empty
        content = ""

    if content is None:
        return None

    if not before_text.strip():
        new_content = content + after_text
    else:
        # Use our ported flexible search and replace
        texts = (before_text, after_text, content)
        new_content = flexible_search_and_replace(texts)

    return new_content

def strip_quoted_wrapping(res, fname=None, fence=("```", "```")):
    if not res:
        return res
    res_lines = res.splitlines(keepends=True)
    if not res_lines:
        return res
        
    # Remove filename if it matches
    if fname and res_lines[0].strip().endswith(Path(fname).name):
        res_lines = res_lines[1:]
    
    if not res_lines:
        return ""

    if res_lines[0].startswith(fence[0]) and res_lines[-1].strip().startswith(fence[1]):
        res_lines = res_lines[1:-1]
    
    res = "".join(res_lines)
    if res and not res.endswith("\n"):
        res += "\n"
    return res

HEAD = r"^<{5,9} SEARCH>?\s*$"
DIVIDER = r"^={5,9}\s*$"
UPDATED = r"^>{5,9} REPLACE\s*$"

def find_original_update_blocks(content, fence=("```", "```")):
    lines = content.splitlines(keepends=True)
    i = 0
    
    head_pattern = re.compile(HEAD)
    divider_pattern = re.compile(DIVIDER)
    updated_pattern = re.compile(UPDATED)

    while i < len(lines):
        line = lines[i]
        
        if head_pattern.match(line.strip()):
            try:
                # Find filename in preceding lines
                filename = find_filename(lines[max(0, i-3):i], fence)
                
                original_text = []
                i += 1
                while i < len(lines) and not divider_pattern.match(lines[i].strip()):
                    original_text.append(lines[i])
                    i += 1
                
                if i >= len(lines):
                    raise ValueError("Expected =======")
                    
                updated_text = []
                i += 1
                while i < len(lines) and not updated_pattern.match(lines[i].strip()):
                    updated_text.append(lines[i])
                    i += 1
                
                if i >= len(lines):
                    raise ValueError("Expected >>>>>>> REPLACE")
                
                yield filename, "".join(original_text), "".join(updated_text)
            except ValueError:
                pass
        i += 1

def find_filename(lines, fence):
    lines = list(lines)
    lines.reverse()
    for line in lines:
        line = line.strip()
        if not line: continue
        if line.startswith(fence[0]): continue
        # Basic cleanup similar to Aider's strip_filename
        filename = line.rstrip(":").lstrip("#").strip("`").strip("*").strip()
        if filename and ("." in filename or "/" in filename):
            return filename
    return None
