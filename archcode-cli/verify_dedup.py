import sys
import os

# Ensure we can import from the cli directory
sys.path.insert(0, os.path.abspath('.'))

from app.agents.agent_graph import _get_all_tools
from skill_manager import skill_manager

extra_tools = skill_manager.get_research_tools()
print(f"Adding {len(extra_tools)} extra tools (which are duplicated inside agent_graph.py normally)")

tools = _get_all_tools(extra_tools=extra_tools)

print(f"Total unique tools bound: {len(tools)}")
names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools]

import collections
counter = collections.Counter(names)
duplicates = [name for name, count in counter.items() if count > 1]

if duplicates:
    print(f"FAIL: Found duplicates: {duplicates}")
else:
    print("SUCCESS: No duplicate tools found!")
    
    # Also verify that search_skills or list_available_skills is present
    if "list_available_skills" in names:
        print("list_available_skills is present.")
    else:
        print("FAIL: list_available_skills is MISSING!")
