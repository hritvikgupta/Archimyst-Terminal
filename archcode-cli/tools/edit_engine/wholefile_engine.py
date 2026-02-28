from pathlib import Path

def apply_whole_file_edits(content, fence=("```", "```")):
    lines = content.splitlines(keepends=True)
    edits = []
    
    fname = None
    new_lines = []
    
    for i, line in enumerate(lines):
        if line.startswith(fence[0]) or line.startswith(fence[1]):
            if fname is not None:
                # Ending a block
                edits.append((fname, "".join(new_lines)))
                fname = None
                new_lines = []
                continue
            
            # Starting a new block - look at previous line for filename
            if i > 0:
                fname = lines[i-1].strip().strip("*").rstrip(":").strip("`").lstrip("#").strip()
                if len(fname) > 250: fname = None
        elif fname is not None:
            new_lines.append(line)
            
    return edits
