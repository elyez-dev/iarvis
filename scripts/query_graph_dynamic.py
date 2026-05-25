#!/usr/bin/env python3
"""
Generate a DQL query that lists ALL entity nodes with ALL their edges,
so Ratel's graph view renders aristas (edges must be explicit for the visualizer).

Usage:
    python scripts/query_graph_dynamic.py          # print the query
    python scripts/query_graph_dynamic.py | xclip  # copy to clipboard
"""

import json, sys, urllib.request

DGRAPH_HTTP = "http://localhost:8082"

req = urllib.request.Request(f"{DGRAPH_HTTP}/query")
req.add_header("Content-Type", "application/dql")
req.data = b"schema {}"

with urllib.request.urlopen(req) as resp:
    schema = json.loads(resp.read())

edges = sorted(
    p["predicate"]
    for p in schema.get("data", {}).get("schema", [])
    if p.get("type") == "uid" and not p["predicate"].startswith("dgraph.")
)

blocks = "\n".join(f"    {e} {{ name }}" for e in edges)

query = f"""{{
  q(func: type(Entity)) {{
    name
    type
{blocks}
  }}
}}"""

print(query)
