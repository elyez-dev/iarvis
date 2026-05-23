#!/usr/bin/env python3
"""
Initialize the dgraph schema for iArvis.

Idempotent: dgraph applies schema additively, so re-running this is a no-op.

What this declares
------------------
- `name`, `type`, `source_docs` predicates with appropriate indexes.
- A `dgraph.type` named `Entity` that groups them.

What this does NOT declare
--------------------------
Predicates of RELATION (`likes`, `has_brother`, `bought`, etc.). Those are
declared on demand by `services/graph_service.py` when the ARCHIVIST emits a
new predicate name. Reason: the relation vocabulary grows with the corpus and
hardcoding a closed list would defeat the purpose of dynamic, LLM-driven KGs.

Usage
-----
From inside the backend container (where pydgraph is in requirements.txt):

    docker cp scripts/init_dgraph_schema.py iarvis_backend:/tmp/init_schema.py
    docker exec -w /app iarvis_backend python /tmp/init_schema.py

Or stand-alone (pip install pydgraph; DGRAPH_GRPC_URL=... python ...).

Reads the gRPC endpoint from env var DGRAPH_GRPC_URL (default dgraph:9080).
"""
import os
import sys

import pydgraph


SCHEMA = """
name: string @index(exact, term, fulltext, trigram) @upsert .
type: string @index(exact) .
source_docs: [string] @index(exact) .

type Entity {
    name
    type
    source_docs
}
"""


def main() -> int:
    grpc_url = os.getenv("DGRAPH_GRPC_URL", "dgraph:9080")
    print(f"Connecting to dgraph at {grpc_url}...")

    client_stub = pydgraph.DgraphClientStub(grpc_url)
    client = pydgraph.DgraphClient(client_stub)

    try:
        op = pydgraph.Operation(schema=SCHEMA.strip())
        client.alter(op)
        print("Schema applied successfully:")
        print(SCHEMA)
    except Exception as exc:
        print(f"Failed to apply schema: {exc}", file=sys.stderr)
        return 1
    finally:
        client_stub.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
