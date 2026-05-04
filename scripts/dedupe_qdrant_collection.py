#!/usr/bin/env python3
"""
Detect and delete near-duplicate points in the Qdrant collection used by iArvis.

Two points are considered duplicates if their cosine similarity is >= RAG_DEDUPE_THRESHOLD
(or the --threshold flag). For each cluster of duplicates, keeps the point whose UUID
sorts first alphabetically and deletes the rest.

Run from inside the backend container so it picks the same env vars:

    docker cp scripts/dedupe_qdrant_collection.py iarvis_backend:/tmp/dedupe.py
    docker exec -w /app iarvis_backend python /tmp/dedupe.py            # dry-run (default)
    docker exec -w /app iarvis_backend python /tmp/dedupe.py --apply    # actually delete

Required Python packages (already in backend image): qdrant-client.
Reads from env (with fallbacks): QDRANT_URL, QDRANT_COLLECTION, RAG_DEDUPE_THRESHOLD.
"""
import argparse
import math
import os
import sys
from typing import Dict, List

from qdrant_client import QdrantClient
from qdrant_client.models import PointIdsList


def cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def find_clusters(point_ids: List[str], vectors: Dict[str, List[float]], threshold: float) -> List[List[str]]:
    """Union-find over points; group ids whose pairwise similarity >= threshold."""
    parent: Dict[str, str] = {pid: pid for pid in point_ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i, pi in enumerate(point_ids):
        for pj in point_ids[i + 1:]:
            if cosine(vectors[pi], vectors[pj]) >= threshold:
                union(pi, pj)

    groups: Dict[str, List[str]] = {}
    for pid in point_ids:
        groups.setdefault(find(pid), []).append(pid)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Dedupe Qdrant collection of iArvis.")
    parser.add_argument("--apply", action="store_true",
                        help="Actually delete duplicates. Default: dry-run.")
    parser.add_argument("--threshold", type=float,
                        default=float(os.getenv("RAG_DEDUPE_THRESHOLD", "0.95")),
                        help="Cosine similarity threshold (default: env RAG_DEDUPE_THRESHOLD or 0.95).")
    parser.add_argument("--collection", type=str,
                        default=os.getenv("QDRANT_COLLECTION", "long_term_memory"),
                        help="Qdrant collection (default: env QDRANT_COLLECTION).")
    parser.add_argument("--qdrant-url", type=str,
                        default=os.getenv("QDRANT_URL", "http://qdrant:6333"),
                        help="Qdrant URL (default: env QDRANT_URL).")
    args = parser.parse_args()

    mode = "APPLY (will delete)" if args.apply else "DRY-RUN"
    print("=== iArvis Qdrant dedupe ===")
    print(f"  Qdrant:     {args.qdrant_url}")
    print(f"  Collection: {args.collection}")
    print(f"  Threshold:  {args.threshold}")
    print(f"  Mode:       {mode}")
    print()

    client = QdrantClient(url=args.qdrant_url, timeout=30.0)

    point_ids: List[str] = []
    vectors: Dict[str, List[float]] = {}
    docs: Dict[str, str] = {}

    next_offset = None
    while True:
        page, next_offset = client.scroll(
            collection_name=args.collection,
            limit=200,
            with_payload=True,
            with_vectors=True,
            offset=next_offset,
        )
        for p in page:
            pid = str(p.id)
            point_ids.append(pid)
            vectors[pid] = p.vector
            docs[pid] = (p.payload or {}).get("rag_document", "(no doc)")
        if next_offset is None:
            break

    print(f"Loaded {len(point_ids)} points.")
    if not point_ids:
        print("Nothing to do.")
        return 0

    clusters = find_clusters(point_ids, vectors, args.threshold)
    if not clusters:
        print("No duplicate clusters found.")
        return 0

    to_delete: List[str] = []
    print(f"\nFound {len(clusters)} duplicate cluster(s):")
    for cluster in clusters:
        keeper = cluster[0]  # alphabetically first kept
        dups = cluster[1:]
        print(f"\n  KEEP   [{keeper[:8]}]  {docs[keeper][:80]}")
        for d in dups:
            sim = cosine(vectors[keeper], vectors[d])
            print(f"  DROP   [{d[:8]}]  cos={sim:.4f}  {docs[d][:80]}")
            to_delete.append(d)

    print(f"\nTotal points to delete: {len(to_delete)}")

    if not args.apply:
        print("\n[DRY-RUN] No changes made. Re-run with --apply to delete.")
        return 0

    print("\nDeleting...")
    client.delete(
        collection_name=args.collection,
        points_selector=PointIdsList(points=to_delete),
        wait=True,
    )
    print(f"Deleted {len(to_delete)} duplicate point(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
