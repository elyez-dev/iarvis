import asyncio
import ast
import json
import logging
import re
import uuid
import time
from typing import Any, Dict, List, Sequence

import httpx
from pydantic import ValidationError
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from core import config
from schemas.memory import (
    ArchivistN8NQuery,
    ArchivistQueryResponse,
    GraphPattern,
    GraphTriplet,
    LibrarianN8NQuery,
    LibrarianQueryResponse,
)
from services.graph_service import ALLOWED_ENTITY_TYPES, GraphService


logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(self):
        settings = config.settings()
        self.qdrant_client = QdrantClient(url=settings.qdrant_url, timeout=settings.default_timeout)
        self.ollama_url = settings.ollama_url.rstrip("/")
        self.timeout = settings.default_timeout
        self.embedding_model = settings.embedding_model
        self.default_collection = settings.qdrant_collection
        self.max_results = 6
        self.collection_ready_retries = 8
        self.collection_ready_delay_seconds = 1.0
        # Cache for Qdrant collection existence to avoid frequent get_collections
        self._collection_ready: bool = False
        self._collection_checked_at: float = 0.0
        self._collection_ttl_seconds: float = getattr(settings, "qdrant_collection_ttl", 60.0)
        print("DEBUG: Attempting to initialize GraphService...")
        self.graph_service: GraphService | None = GraphService()
        print(f"DEBUG: GraphService initialized successfully: {self.graph_service}")

    async def librarian_query(self, message: str) -> LibrarianQueryResponse:
        n8n_query = self._parse_librarian_message(message)
        logger.info(
            "Librarian query received: rag_query=%r entities=%s patterns=%s time_context=%r",
            n8n_query.rag_query,
            n8n_query.graph_entities,
            [p.model_dump() for p in n8n_query.graph_patterns],
            n8n_query.time_context,
        )
        self._validate_query(n8n_query)
        # Run Qdrant search and graph lookup in parallel to reduce latency
        search_coro = self._search_qdrant(n8n_query)
        graph_coro = self._graph_lookup(n8n_query)
        try:
            matches, graph_results = await asyncio.gather(search_coro, graph_coro)
        except Exception as exc:
            # If either raises, log and try to provide partial results where possible
            logger.warning("Librarian parallel lookup: one task failed: %s", exc)
            # try to salvage search results if possible
            matches = []
            graph_results = "NONE"
            try:
                matches = await asyncio.wait_for(search_coro, timeout=1.0)
            except Exception:
                matches = []
            try:
                graph_results = await asyncio.wait_for(graph_coro, timeout=1.0)
            except Exception:
                graph_results = "NONE"

        formatted = self._format_memory_results(matches)

        return LibrarianQueryResponse(
            n8n_query=n8n_query,
            memory_results=formatted,
            graph_results=graph_results,
        )

    async def _graph_lookup(self, n8n_query: LibrarianN8NQuery) -> str:
        """Prefer graph_patterns; fall back to graph_entities for backward compat."""
        if self.graph_service is None:
            return "NONE"
        try:
            if n8n_query.graph_patterns:
                return await self.graph_service.query_patterns(n8n_query.graph_patterns)
            if n8n_query.graph_entities:
                return await self.graph_service.query_entities(
                    n8n_query.graph_entities,
                    n8n_query.time_context,
                )
            return "NONE"
        except Exception as exc:
            logger.warning("Graph lookup failed (returning NONE): %s", exc)
            return "NONE"

    async def archivist_query(self, message: str) -> ArchivistQueryResponse:
        n8n_query = self._parse_archivist_message(message)
        logger.info(
            "Archivist query received: rag_document=%r triplets=%s entity_types=%s time_context=%r",
            n8n_query.rag_document,
            len(n8n_query.graph_triplets),
            n8n_query.entity_types,
            n8n_query.time_context,
        )
        self._validate_archivist_query(n8n_query)
        stored_point_id, deduped = await self._store_in_qdrant(n8n_query)

        if self.graph_service is not None:
            try:
                await self.graph_service.store_triplets(
                    n8n_query.graph_triplets,
                    n8n_query.entity_types,
                    n8n_query.time_context,
                    source_doc_id=stored_point_id,
                )
            except Exception as exc:
                logger.warning("Graph store failed (RAG may be deduped): %s", exc)

        return ArchivistQueryResponse(n8n_query=n8n_query, stored_point_id=stored_point_id)

    def _parse_librarian_message(self, message: str) -> LibrarianN8NQuery:
        payload = self._parse_json_payload_from_message(message, "librarian")

        normalized_patterns = self._normalize_patterns(
            self._pick_first(payload, ["graph_patterns", "patterns", "graph_query"])
        )

        normalized_payload = {
            "rag_query": self._pick_first(payload, ["rag_query", "query", "search_query", "question"]),
            "graph_entities": self._normalize_string_list(
                self._pick_first(payload, ["graph_entities", "entities", "entity_list", "keywords"])
            ),
            "graph_patterns": normalized_patterns,
            "time_context": self._pick_first(payload, ["time_context", "time", "temporal_context", "date_context"]) or "",
        }

        try:
            return LibrarianN8NQuery.model_validate(normalized_payload)
        except ValidationError as exc:
            raise ValueError(
                "Librarian query must include 'rag_query' (str). Optional fields: graph_entities (list[str]), graph_patterns (list[{subject?,predicate?,object?}]), time_context (str)"
            ) from exc

    def _parse_archivist_message(self, message: str) -> ArchivistN8NQuery:
        payload = self._parse_json_payload_from_message(message, "archivist")

        normalized_triplets = self._normalize_triplets(
            self._pick_first(payload, ["graph_triplets", "triplets", "relations", "edges"])
        )

        normalized_entity_types = self._normalize_entity_types(
            self._pick_first(payload, ["entity_types", "types", "entityTypes"])
        )

        normalized_payload = {
            "rag_document": self._pick_first(payload, ["rag_document", "document", "memory_text", "content"]),
            "graph_triplets": normalized_triplets,
            "entity_types": normalized_entity_types,
            "time_context": self._pick_first(payload, ["time_context", "time", "timestamp", "date_context"]) or "",
        }

        try:
            return ArchivistN8NQuery.model_validate(normalized_payload)
        except ValidationError as exc:
            raise ValueError(
                "Archivist query must include 'rag_document' (str) and 'graph_triplets' (list[{subject,predicate,object}]). Optional: entity_types (dict[str,Type]), time_context (str)"
            ) from exc

    def _parse_json_payload_from_message(self, message: str, label: str) -> Dict[str, Any]:
        if not message or not message.strip():
            raise ValueError(f"{label.capitalize()} message is empty")

        raw_text = message.strip()
        fenced_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw_text, flags=re.IGNORECASE)
        if fenced_match:
            json_candidate = fenced_match.group(1)
        else:
            block_match = re.search(r"(\{[\s\S]*\})", raw_text)
            json_candidate = block_match.group(1) if block_match else raw_text

        parsed = self._loads_flexible_json(json_candidate)
        if not isinstance(parsed, dict):
            raise ValueError(f"Invalid {label} JSON message format")
        return parsed

    def _loads_flexible_json(self, raw_text: str) -> Any:
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass

        cleaned = raw_text.strip().replace("“", '"').replace("”", '"').replace("’", "'")
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        try:
            return ast.literal_eval(cleaned)
        except (ValueError, SyntaxError) as exc:
            raise ValueError("Invalid JSON object in AI message") from exc

    def _pick_first(self, payload: Dict[str, Any], keys: List[str]) -> Any:
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        return None

    def _normalize_string_list(self, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            candidates = re.split(r",|;|\n", value)
            return [item.strip() for item in candidates if item and item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()] if str(value).strip() else []

    def _normalize_triplets(self, value: Any) -> List[GraphTriplet]:
        if value is None:
            return []

        raw_items: List[Any]
        if isinstance(value, list):
            raw_items = value
        else:
            raw_items = [value]

        triplets: List[GraphTriplet] = []
        for item in raw_items:
            if isinstance(item, str):
                parts = [part.strip() for part in re.split(r"->|,|\|", item) if part.strip()]
                if len(parts) >= 3:
                    triplets.append(GraphTriplet(subject=parts[0], predicate=parts[1], object=parts[2]))
                continue

            if isinstance(item, dict):
                subject = item.get("subject") or item.get("s")
                predicate = item.get("predicate") or item.get("relation") or item.get("p")
                obj = item.get("object") or item.get("o")
                if subject and predicate and obj:
                    triplets.append(GraphTriplet(subject=str(subject), predicate=str(predicate), object=str(obj)))
        return triplets

    def _normalize_patterns(self, value: Any) -> List[Dict[str, Any]]:
        """Accept patterns in several shapes:
        - list of {subject,predicate,object} dicts (preferred)
        - list of "S|P|O" strings (split on | or ->)
        - empty/missing → []
        Returns a list of dicts suitable for Pydantic validation."""
        if value is None:
            return []
        raw_items: List[Any] = value if isinstance(value, list) else [value]
        patterns: List[Dict[str, Any]] = []
        for item in raw_items:
            if isinstance(item, str):
                parts = [p.strip() for p in re.split(r"\||->", item)]
                if len(parts) == 3:
                    s, p, o = parts
                    patterns.append({
                        "subject": s or None,
                        "predicate": p or None,
                        "object": o or None,
                    })
                continue
            if isinstance(item, dict):
                s = item.get("subject") or item.get("s")
                p = item.get("predicate") or item.get("relation") or item.get("p")
                o = item.get("object") or item.get("o")
                # Treat empty strings as None (wildcard).
                patterns.append({
                    "subject": (str(s).strip() or None) if s is not None else None,
                    "predicate": (str(p).strip() or None) if p is not None else None,
                    "object": (str(o).strip() or None) if o is not None else None,
                })
        return patterns

    def _normalize_entity_types(self, value: Any) -> Dict[str, str]:
        if not isinstance(value, dict):
            return {}
        result: Dict[str, str] = {}
        for k, v in value.items():
            name = str(k).strip()
            if not name:
                continue
            t = str(v).strip()
            if t not in ALLOWED_ENTITY_TYPES:
                t = "Other"
            result[name] = t
        return result

    def _validate_query(self, n8n_query: LibrarianN8NQuery) -> None:
        if not n8n_query.rag_query.strip():
            raise ValueError("'rag_query' must be a non-empty string")
        n8n_query.graph_entities = [entity.strip() for entity in n8n_query.graph_entities if entity and entity.strip()]
        # Drop patterns where all three slots are empty (would be too broad to query).
        n8n_query.graph_patterns = [
            p for p in n8n_query.graph_patterns
            if (p.subject and p.subject.strip()) or (p.predicate and p.predicate.strip()) or (p.object and p.object.strip())
        ]

    def _validate_archivist_query(self, n8n_query: ArchivistN8NQuery) -> None:
        if not n8n_query.rag_document.strip():
            raise ValueError("'rag_document' must be a non-empty string")
        if not n8n_query.graph_triplets:
            raise ValueError("'graph_triplets' must include at least one triplet")


    def _format_memory_results(self, points: list) -> str:
        threshold = config.settings().rag_score_threshold
        kept = []
        for p in points:
            score = p.get("score")
            if score is None or score < threshold:
                continue
            payload = p.get("payload") or {}
            doc = payload.get("rag_document") or payload.get("document") or ""
            doc = doc.strip()
            if doc:
                kept.append(f"- {doc}")
        if not kept:
            return "NONE"
        return chr(10).join(kept)


    async def _search_qdrant(self, n8n_query: LibrarianN8NQuery) -> List[Dict[str, Any]]:
        query_text = self._build_query_text(n8n_query)
        query_vector = await self._embed_text(query_text, is_query=True)
        await self._ensure_collection_exists(len(query_vector))

        try:
            points = await asyncio.to_thread(
                self.qdrant_client.search,
                collection_name=self.default_collection,
                query_vector=query_vector,
                limit=self.max_results,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            logger.exception(
                "Qdrant search failed for collection=%s vector_dim=%s",
                self.default_collection,
                len(query_vector),
            )
            raise ValueError(f"Failed to execute librarian query against Qdrant: {exc}") from exc

        logger.info("Qdrant search success: collection=%s hits=%s", self.default_collection, len(points))
        return self._serialize_results(points)

    async def _store_in_qdrant(self, n8n_query: ArchivistN8NQuery) -> tuple[str, bool]:
        """Returns (point_id, deduped). deduped=True means we did not actually insert."""
        document_text = self._build_document_text(n8n_query)
        document_vector = await self._embed_text(document_text)
        await self._ensure_collection_exists(len(document_vector))

        dedupe_threshold = config.settings().rag_dedupe_threshold
        try:
            similar = await asyncio.to_thread(
                self.qdrant_client.search,
                collection_name=self.default_collection,
                query_vector=document_vector,
                limit=1,
                with_payload=True,
            )
        except Exception as exc:
            logger.warning("Dedupe pre-search failed (will insert anyway): %s", exc)
            similar = []
        if similar and similar[0].score is not None and similar[0].score >= dedupe_threshold:
            existing_id = str(similar[0].id)
            existing_doc = (similar[0].payload or {}).get("rag_document", "")
            logger.info(
                "Dedupe skip: new=%r similar_score=%.4f existing_id=%s existing=%r",
                n8n_query.rag_document, similar[0].score, existing_id, existing_doc[:80]
            )
            return existing_id, True

        point_id = str(uuid.uuid4())
        payload = {
            "rag_document": n8n_query.rag_document,
            "graph_triplets": [triplet.model_dump() for triplet in n8n_query.graph_triplets],
            "time_context": n8n_query.time_context,
        }

        try:
            await asyncio.to_thread(
                self.qdrant_client.upsert,
                collection_name=self.default_collection,
                points=[PointStruct(id=point_id, vector=document_vector, payload=payload)],
                wait=True,
            )
            logger.info("Qdrant upsert success: collection=%s point_id=%s", self.default_collection, point_id)
            return point_id, False
        except Exception as exc:
            logger.exception("Qdrant upsert failed for collection=%s", self.default_collection)
            raise ValueError(f"Failed to store archivist query in Qdrant: {exc}") from exc

    async def _ensure_collection_exists(self, vector_size: int) -> None:
        """Ensure the Qdrant collection exists. Uses an in-memory TTL cache to avoid
        frequent calls to get_collections in high-throughput scenarios.
        """
        now = time.time()
        if self._collection_ready and (now - self._collection_checked_at) < self._collection_ttl_seconds:
            return

        existing = await self._get_collection_names()
        if self.default_collection in existing:
            self._collection_ready = True
            self._collection_checked_at = now
            return

        logger.warning(
            "Qdrant collection %s not found. Creating it with vector size %s.",
            self.default_collection,
            vector_size,
        )
        try:
            await asyncio.to_thread(
                self.qdrant_client.create_collection,
                collection_name=self.default_collection,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
            logger.info("Create collection request sent for %s", self.default_collection)
        except Exception as exc:
            logger.warning(
                "Create collection request raised an exception for %s: %s. Will verify existence.",
                self.default_collection,
                exc,
            )

        for attempt in range(1, self.collection_ready_retries + 1):
            existing = await self._get_collection_names()
            if self.default_collection in existing:
                self._collection_ready = True
                self._collection_checked_at = time.time()
                logger.info(
                    "Qdrant collection %s is ready (attempt %s/%s).",
                    self.default_collection,
                    attempt,
                    self.collection_ready_retries,
                )
                return
            await asyncio.sleep(self.collection_ready_delay_seconds)

        raise ValueError(
            f"Qdrant collection '{self.default_collection}' is still unavailable after create attempt"
        )

    async def _get_collection_names(self) -> set[str]:
        try:
            collections = await asyncio.to_thread(self.qdrant_client.get_collections)
            return {item.name for item in collections.collections}
        except Exception as exc:
            logger.exception("Failed to list Qdrant collections")
            raise ValueError(f"Failed to list Qdrant collections: {exc}") from exc

    async def _embed_text(self, text: str, is_query: bool = False) -> List[float]:
        if "nomic-embed-text" in self.embedding_model:
            prefix = "search_query: " if is_query else "search_document: "
            text = prefix + text
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.ollama_url}/api/embeddings",
                    json={"model": self.embedding_model, "prompt": text},
                )
                response.raise_for_status()
                data = response.json()
                logger.info("Ollama embeddings success: model=%s", self.embedding_model)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response else "unknown"
            body = exc.response.text if exc.response is not None else ""
            logger.error("Ollama embeddings HTTP error status=%s body=%s", status, body)
            raise ValueError(f"Ollama embedding request failed with status {status}") from exc
        except httpx.RequestError as exc:
            logger.error("Ollama connection error: %s", exc)
            raise ValueError(f"Unable to reach Ollama for embeddings: {exc}") from exc

        embedding = data.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise ValueError("Invalid embedding response from Ollama")

        try:
            return [float(value) for value in embedding]
        except (TypeError, ValueError) as exc:
            raise ValueError("Embedding returned by Ollama contains non-numeric values") from exc

    def _build_query_text(self, n8n_query: LibrarianN8NQuery) -> str:
        entities = ", ".join(n8n_query.graph_entities)
        return (
            f"{n8n_query.rag_query.strip()}\n"
            f"Entities: {entities}\n"
            f"Time context: {n8n_query.time_context.strip()}"
        )

    def _build_document_text(self, n8n_query: ArchivistN8NQuery) -> str:
        triplets = "\n".join(
            [f"{triplet.subject} -[{triplet.predicate}]-> {triplet.object}" for triplet in n8n_query.graph_triplets]
        )
        return (
            f"{n8n_query.rag_document.strip()}\n"
            f"Triplets:\n{triplets}\n"
            f"Time context: {n8n_query.time_context.strip()}"
        )

    async def delete_all_in_rag(self) -> str:
        """Delete all points from the default Qdrant collection.

        Drops the collection and resets the existence cache so the next
        write operation recreates it automatically.

        Returns an error message string (empty on success).
        """
        try:
            await asyncio.to_thread(
                self.qdrant_client.delete_collection,
                collection_name=self.default_collection,
            )
            logger.info("MemoryService.delete_all_in_rag: collection %s dropped", self.default_collection)
        except Exception as exc:
            msg = f"Qdrant collection delete failed: {exc}"
            logger.error("MemoryService.delete_all_in_rag: %s", msg)
            return msg

        self._collection_ready = False
        self._collection_checked_at = 0.0
        return ""

    def _serialize_results(self, matches: Sequence[Any]) -> List[Dict[str, Any]]:
        serialized: List[Dict[str, Any]] = []
        for match in matches:
            payload = getattr(match, "payload", {}) or {}
            serialized.append(
                {
                    "id": str(getattr(match, "id", "")),
                    "score": float(getattr(match, "score", 0.0)),
                    "payload": payload,
                }
            )
        return serialized