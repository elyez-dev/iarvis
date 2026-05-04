#!/usr/bin/env python3
"""
Re-index all points in the Qdrant collection by recomputing their embeddings
with the current `_embed_text` (which applies nomic-embed-text prefixes).

Useful when:
  - The embedding model changes.
  - The instruction prefix convention changes (e.g. enabling nomic prefixes).
  - The `_build_document_text` representation changes.

Run from inside the backend container:

    docker cp scripts/reindex_qdrant_collection.py iarvis_backend:/tmp/reindex.py
    docker exec -w /app iarvis_backend python /tmp/reindex.py            # dry-run (default)
    docker exec -w /app iarvis_backend python /tmp/reindex.py --apply    # actually update vectors

The script reuses MemoryService (so it picks up the same embedding model and
prefix logic). It rebuilds each document with `_build_document_text` from the
stored payload and upserts the point with the same id and same payload but the
freshly computed vector.

Caveat: this re-uses the canonical `_build_document_text`, which currently
includes "Triplets:\n..." and "Time context: ..." labels. If those labels
change in the future, the script will pick up the new format automatically.
"""
import argparse
import asyncio
import os
import sys
from typing import Dict, List

from qdrant_client.models import PointStruct

# Add /app to import path so this script runs both from /tmp and /app
sys.path.insert(0, "/app")

from services.memory_service import MemoryService
from schemas.memory import ArchivistN8NQuery, GraphTriplet


async def reindex(apply: bool, batch_size: int = 50) -> int:
    m = MemoryService()
    print("=== iArvis Qdrant re-index ===")
    print(f"  Qdrant collection: {m.default_collection}")
    print(f"  Embedding model:   {m.embedding_model}")
    print(f"  Mode:              {'APPLY (will update vectors)' if apply else 'DRY-RUN'}")
    print()

    point_ids: List[str] = []
    payloads: Dict[str, dict] = {}
    next_offset = None
    while True:
        page, next_offset = await asyncio.to_thread(
            m.qdrant_client.scroll,
            collection_name=m.default_collection,
            limit=batch_size,
            with_payload=True,
            with_vectors=False,
            offset=next_offset,
        )
        for p in page:
            pid = str(p.id)
            point_ids.append(pid)
            payloads[pid] = p.payload or {}
        if next_offset is None:
            break

    print(f"Loaded {len(point_ids)} points.")
    if not point_ids:
        return 0

    updated_points: List[PointStruct] = []
    for pid in point_ids:
        payload = payloads[pid]
        rag_doc = payload.get("rag_document", "").strip()
        triplets_raw = payload.get("graph_triplets") or []
        time_ctx = payload.get("time_context", "")

        triplets = []
        for t in triplets_raw:
            if isinstance(t, dict):
                try:
                    triplets.append(GraphTriplet(**t))
                except Exception:
                    pass

        if not rag_doc:
            print(f"  [{pid[:8]}] SKIP (empty rag_document)")
            continue

        n8n_query = ArchivistN8NQuery(
            rag_document=rag_doc,
            graph_triplets=triplets,
            time_context=time_ctx,
        )
        document_text = m._build_document_text(n8n_query)
        new_vector = await m._embed_text(document_text, is_query=False)
        updated_points.append(PointStruct(id=pid, vector=new_vector, payload=payload))
        print(f"  [{pid[:8]}] re-embedded ({len(new_vector)} dims): {rag_doc[:60]}")

    print(f"\nTotal points to re-index: {len(updated_points)}")

    if not apply:
        print("\n[DRY-RUN] No changes made. Re-run with --apply to update vectors.")
        return 0

    print("\nUpserting updated vectors...")
    await asyncio.to_thread(
        m.qdrant_client.upsert,
        collection_name=m.default_collection,
        points=updated_points,
        wait=True,
    )
    print(f"Re-indexed {len(updated_points)} point(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-embed all points in iArvis Qdrant collection.")
    parser.add_argument("--apply", action="store_true", help="Actually update vectors. Default: dry-run.")
    parser.add_argument("--batch-size", type=int, default=50, help="Scroll batch size.")
    args = parser.parse_args()
    return asyncio.run(reindex(apply=args.apply, batch_size=args.batch_size))


if __name__ == "__main__":
    sys.exit(main())
