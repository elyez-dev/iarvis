"""
GraphService — interface to the dgraph knowledge graph for iArvis.

Two query interfaces, in order of preference:
  - `query_patterns(patterns)`: NEW. Pattern-matching over (subject, predicate, object)
    with wildcards. Used by the new LIBRARIAN. Filters at DQL level, returns minimal
    relevant edges, not a 1-hop dump.
  - `query_entities(entities, time_context)`: LEGACY. Fallback when the LIBRARIAN
    only emits flat entity names (older prompt). Returns ALL outgoing edges of each
    matched entity.

Conventions
-----------
- Entity names are user-facing strings (e.g. "User", "Juan_brother", "cheese").
- All nodes carry `dgraph.type = "Entity"`. The `type` field is one of the 10 closed
  types (Person, Animal, Place, Object, Food, Event, Activity, Concept, Feeling, Other).
- Predicates of RELATION are declared on-demand the first time they appear,
  as `[uid] @reverse`. Predicate names are normalized to lowercase snake_case and
  canonicalized through PREDICATE_CANON (`owns` -> `has`, `loves` -> `likes`, ...).
- Edge facets:
  * `on`    for event-like predicates (bought, met, visited, ...).
  * `since` for state-like predicates (likes, lives_in, has_brother, ...).
  * Omitted when time_context is empty.
"""
import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import pydgraph

from core import config
from schemas.memory import GraphPattern, GraphTriplet


logger = logging.getLogger(__name__)


EVENT_PREDICATES: set[str] = {
    "bought", "purchased", "sold", "visited", "met", "attended", "received",
    "sent", "called", "wrote", "watched", "played", "ate", "drank", "happened",
    "occurred", "started", "finished", "completed", "won", "lost", "celebrated",
}


ALLOWED_ENTITY_TYPES: set[str] = {
    "Person", "Animal", "Place", "Object", "Food",
    "Event", "Activity", "Concept", "Feeling", "Other",
}


# Snake_case-friendly identifier for entity names. We accept letters, digits and
# underscores. Anything else (spaces, colons, hyphens, accented chars) is rejected
# by `_classify_slot` so we don't send broken queries to dgraph.
_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


# PREDICATE_CANON: maps surface predicate forms to canonical ones.
# Curated by hand using ConceptNet 5.7 Synonym edges (WordNet 3.1 subset) as a
# discovery guide; pruned to remove polysemic matches that WordNet bundles into
# the same synset without sense disambiguation. Entries are kept ONLY when the
# synonymy is unambiguous for autobiographical-memory predicates.
#
# Two layers:
#   - verb-level: applied as-is to single-token predicates (likes, has, ...).
#   - noun-level: applied to the suffix of compound predicates (has_grandma -> has_grandmother).
PREDICATE_CANON_VERBS: Dict[str, str] = {
    # likes
    "like": "likes", "loves": "likes", "love": "likes", "enjoys": "likes", "enjoy": "likes",
    "prefers": "likes", "prefer": "likes", "fancies": "likes", "fancy": "likes",
    "adores": "likes", "adore": "likes", "appreciates": "likes", "appreciate": "likes",
    "relishes": "likes", "relish": "likes", "is_fond_of": "likes",
    # hates
    "hate": "hates", "dislikes": "hates", "dislike": "hates", "loathes": "hates", "loathe": "hates",
    "despises": "hates", "despise": "hates", "detests": "hates", "detest": "hates",
    "abhors": "hates", "abhor": "hates",
    # knows
    "know": "knows", "recognizes": "knows", "recognize": "knows",
    "recognises": "knows", "recognise": "knows",
    # has
    "have": "has", "owns": "has", "own": "has", "possesses": "has", "possess": "has",
    "holds": "has", "hold": "has",
    # lives_in
    "lives": "lives_in", "live": "lives_in", "resides": "lives_in", "reside": "lives_in",
    "resides_in": "lives_in", "lives_at": "lives_in", "dwells": "lives_in", "dwell": "lives_in",
    "inhabits": "lives_in", "inhabit": "lives_in",
    # works_at
    "works": "works_at", "work": "works_at", "is_employed_by": "works_at",
    "employed_at": "works_at", "works_for": "works_at",
    # bought (event)
    "buy": "bought", "buys": "bought", "purchases": "bought", "purchase": "bought",
    "purchased": "bought", "acquires": "bought", "acquire": "bought",
    "acquired": "bought", "procures": "bought", "procure": "bought",
    # sold (event)
    "sell": "sold", "sells": "sold",
    # visited (event)
    "visit": "visited", "visits": "visited", "tours": "visited", "tour": "visited",
    "toured": "visited", "travelled_to": "visited", "traveled_to": "visited", "went_to": "visited",
    # met (event)
    "meet": "met", "meets": "met", "encounters": "met", "encounter": "met",
    "encountered": "met",
    # ate (event)
    "eat": "ate", "eats": "ate", "consumes": "ate", "consume": "ate", "consumed": "ate",
    "ingests": "ate", "ingest": "ate", "ingested": "ate",
    # drank (event)
    "drink": "drank", "drinks": "drank", "imbibes": "drank", "imbibe": "drank",
    # said (event)
    "say": "said", "says": "said", "tells": "said", "tell": "said", "told": "said",
    "mentions": "said", "mention": "said", "mentioned": "said",
    "states": "said", "state": "said", "stated": "said",
    "utters": "said", "utter": "said", "uttered": "said",
    "announces": "said", "announce": "said", "announced": "said",
    # did (event) — kept narrow because "do" is too polysemic
    "do": "did", "does": "did", "performs": "did", "perform": "did", "performed": "did",
    "completes": "did", "complete": "did", "completed": "did",
    "executes": "did", "execute": "did", "executed": "did",
    # attended (event)
    "attend": "attended", "attends": "attended", "participates": "attended", "participate": "attended",
    "participated": "attended",
    # played (event)
    "play": "played", "plays": "played",
    # watched (event)
    "watch": "watched", "watches": "watched", "observes": "watched", "observe": "watched",
    "observed": "watched", "views": "watched", "view": "watched", "viewed": "watched",
    # read (event)
    "reads": "read", "peruses": "read", "peruse": "read",
    # wrote (event)
    "write": "wrote", "writes": "wrote", "authors": "wrote", "author": "wrote",
    "authored": "wrote", "composes": "wrote", "compose": "wrote", "composed": "wrote",
    "pens": "wrote", "pen": "wrote",
    # called (event)
    "calls": "called", "call": "called", "phones": "called", "phone": "called",
    "phoned": "called", "telephones": "called", "telephone": "called", "telephoned": "called",
    # won
    "win": "won", "wins": "won",
    # lost
    "lose": "lost", "loses": "lost",
}

# Noun-level canonicalization (applied to suffix of compound predicates).
# Example: has_grandma -> has_grandmother.
PREDICATE_NOUN_CANON: Dict[str, str] = {
    "grandma": "grandmother", "granny": "grandmother", "gran": "grandmother",
    "nan": "grandmother", "nanna": "grandmother", "grannie": "grandmother",
    "grandpa": "grandfather", "granddad": "grandfather", "gramps": "grandfather",
    "granddaddy": "grandfather", "grandad": "grandfather",
    "auntie": "aunt", "aunty": "aunt",
    "dad": "father", "daddy": "father", "papa": "father", "pa": "father",
    "pop": "father", "dada": "father", "pappa": "father",
    "mom": "mother", "mum": "mother", "ma": "mother", "mama": "mother",
    "mommy": "mother", "mummy": "mother", "mamma": "mother",
    "hubby": "husband", "married_man": "husband",
    "married_woman": "wife",
    "boyfriend": "partner", "girlfriend": "partner", "spouse": "partner",
    "buddy": "friend", "pal": "friend", "mate": "friend", "bro": "brother",
    "sis": "sister",
    "coworker": "colleague", "co_worker": "colleague", "workmate": "colleague",
    "neighbour": "neighbor",
    "advisor": "mentor", "adviser": "mentor",
    "manager": "boss", "supervisor": "boss", "foreman": "boss",
    "doc": "doctor", "md": "doctor", "physician": "doctor", "dr": "doctor",
    "attorney": "lawyer",
    "instructor": "teacher", "instructer": "teacher",
}


# Built-in Entity-type scalar predicates we never want to render as relation edges.
_RESERVED_PREDICATES: set[str] = {
    "name", "type", "source_docs", "uid", "dgraph.type",
}


class GraphService:
    def __init__(self) -> None:
        print(f"DEBUG: GraphService.__init__ called", flush=True)
        settings = config.settings()
        print(f"DEBUG: Config loaded, grpc_url={settings.dgraph_grpc_url}", flush=True)
        self.grpc_url = settings.dgraph_grpc_url
        self._stub = pydgraph.DgraphClientStub(self.grpc_url)
        print(f"DEBUG: DgraphClientStub created", flush=True)
        self._client = pydgraph.DgraphClient(self._stub)
        print(f"DEBUG: DgraphClient created", flush=True)
        self._declared_predicates: set[str] = set()
        self._relation_predicates: set[str] = set()
        # Cache timing for predicate refresh to avoid querying schema every request
        self._predicates_last_refreshed: float = 0.0
        self._predicates_ttl_seconds: float = getattr(settings, "dgraph_predicates_ttl", 30.0)
        self._refresh_declared_predicates()
        print(f"DEBUG: Predicates refreshed", flush=True)
        logger.info(
            "GraphService initialized | grpc=%s | known_predicates=%d relations=%d",
            self.grpc_url, len(self._declared_predicates), len(self._relation_predicates),
        )
        print(f"DEBUG: GraphService.__init__ completed successfully", flush=True)

    def _refresh_declared_predicates(self, force: bool = False) -> None:
        """Refresh cached declared predicates from dgraph schema.
        Uses an in-memory TTL so frequent operations don't hammer the schema endpoint.
        Set force=True to bypass the TTL (used after declaring new predicates).
        """
        now = time.time()
        if not force and (now - self._predicates_last_refreshed) < self._predicates_ttl_seconds:
            return
        try:
            res = self._client.txn(read_only=True).query("schema {}")
            data = json.loads(res.json)
            schema_items = data.get("schema", []) or []
            self._declared_predicates = {
                p["predicate"] for p in schema_items
                if not p.get("predicate", "").startswith("dgraph.")
            }
            self._relation_predicates = {
                p["predicate"] for p in schema_items
                if p.get("type") == "uid"
                and not p.get("predicate", "").startswith("dgraph.")
            }
            self._predicates_last_refreshed = now
        except Exception as exc:
            logger.warning("Could not refresh declared predicates: %s", exc)
            # keep previous cached sets if any; don't clear them on transient error
            if not self._declared_predicates:
                self._declared_predicates = set()
            if not self._relation_predicates:
                self._relation_predicates = set()

    # =====================================================================
    # STORE
    # =====================================================================

    async def store_triplets(
        self,
        triplets: List[GraphTriplet],
        entity_types: Dict[str, str],
        time_context: str,
        source_doc_id: Optional[str],
    ) -> None:
        """Upsert entities and relations into the graph.
        Idempotent: re-running with the same input does not duplicate edges.
        A fresher `time_context` overwrites the facet on the edge.
        """
        if not triplets:
            return

        norm_triplets: List[Dict[str, str]] = []
        all_names: set[str] = set()
        for t in triplets:
            pred = self._normalize_predicate(t.predicate)
            if not pred:
                continue
            subj = t.subject.strip()
            obj = t.object.strip()
            if not subj or not obj:
                continue
            norm_triplets.append({"subject": subj, "predicate": pred, "object": obj})
            all_names.add(subj)
            all_names.add(obj)
        if not norm_triplets:
            return

        # Batch canonicalization: resolve all names in a single query when possible
        canonical: Dict[str, str] = {}
        try:
            canonical = await self._batch_canonicalize_entity_names(sorted(all_names))
        except Exception as exc:
            logger.warning("store_triplets: batch canonicalization failed, falling back to per-name: %s", exc)
            # Fallback to per-name resolution (backwards compatible)
            for name in all_names:
                try:
                    canonical[name] = await self._canonicalize_entity_name(name)
                except Exception as e:
                    logger.warning("store_triplets: per-name canonicalize failed for %r: %s", name, e)
                    canonical[name] = name

        new_predicates = {t["predicate"] for t in norm_triplets} - self._declared_predicates
        for pred in sorted(new_predicates):
            try:
                self._declare_predicate(pred)
            except Exception as exc:
                logger.error("store_triplets: failed to declare predicate %s: %s", pred, exc)
                raise

        # Build upsert parts and perform the single upsert transaction
        try:
            query_part, set_nquads = self._build_upsert_parts(
                norm_triplets=norm_triplets,
                canonical=canonical,
                entity_types=entity_types,
                time_context=time_context,
                source_doc_id=source_doc_id,
            )
        except Exception as exc:
            logger.error("store_triplets: failed to build upsert parts: %s", exc)
            raise

        def _do_upsert() -> None:
            txn = self._client.txn()
            try:
                mutation = pydgraph.Mutation(set_nquads=set_nquads.encode("utf-8"))
                req = pydgraph.Request(
                    query=query_part,
                    mutations=[mutation],
                    commit_now=True,
                )
                txn.do_request(req)
            finally:
                txn.discard()

        try:
            await asyncio.to_thread(_do_upsert)
            logger.info(
                "GraphService.store_triplets OK | triplets=%d entities=%d source=%s",
                len(norm_triplets), len(canonical), source_doc_id,
            )
        except Exception as exc:
            logger.exception("GraphService.store_triplets failed: %s", exc)

    # =====================================================================
    # QUERY — pattern matching (preferred)
    # =====================================================================

    async def query_patterns(self, patterns: List[GraphPattern]) -> str:
        """Pattern-matching query over the graph. Each pattern is (S, P, O) where
        any slot may be:
          - a concrete entity name ("User", "Juan_brother", "cheese")
          - one of the 10 EntityTypes ("Person", "Food", ...)
          - None / "" for wildcard

        Returns deduped prose lines, or 'NONE' if no patterns matched or all were
        rejected as too broad.
        """
        if not patterns:
            return "NONE"

        self._refresh_declared_predicates()

        blocks: List[str] = []
        descriptors: List[Tuple[int, GraphPattern, str]] = []  # (idx, pattern, anchor_kind)
        for i, p in enumerate(patterns):
            block, anchor = self._build_pattern_block(i, p)
            if block is None:
                logger.info(
                    "query_patterns skip | idx=%d pattern=%r reason=invalid_or_broad",
                    i, p.model_dump(),
                )
                continue
            blocks.append(block)
            descriptors.append((i, p, anchor))

        if not blocks:
            return "NONE"

        query = "{\n" + "\n".join(blocks) + "\n}"

        def _do_query() -> Dict[str, Any]:
            res = self._client.txn(read_only=True).query(query)
            return json.loads(res.json)

        try:
            data = await asyncio.to_thread(_do_query)
        except Exception as exc:
            logger.warning("query_patterns DQL failed: %s | query=%s", exc, query)
            return "NONE"

        lines = self._format_pattern_results(data, descriptors)
        if not lines:
            logger.info("query_patterns no matches | patterns=%d", len(patterns))
            return "NONE"
        logger.info("query_patterns OK | patterns=%d lines=%d", len(patterns), len(lines))
        return "\n".join(lines)

    # =====================================================================
    # QUERY — legacy entity dump (fallback)
    # =====================================================================

    async def query_entities(
        self,
        entities: List[str],
        time_context: str,
    ) -> str:
        """Legacy: fetch ALL outgoing edges of every entity. Used as fallback when
        the LIBRARIAN emits flat `graph_entities` instead of `graph_patterns`."""
        clean_entities = [e.strip() for e in entities if e and e.strip()]
        if not clean_entities:
            return "NONE"

        self._refresh_declared_predicates()
        relations = sorted(p for p in self._relation_predicates if p not in _RESERVED_PREDICATES)
        if not relations:
            logger.info("query_entities skipped — no relation predicates declared yet")
            return "NONE"

        rel_fields = "\n".join(
            f"      {p} @facets {{ uid name }}" for p in relations
        )
        blocks: List[str] = []
        for i, ent in enumerate(clean_entities):
            safe = re.escape(ent)
            blocks.append(
                f'  e_{i}(func: regexp(name, /^{safe}(_.*)?$/)) @filter(type(Entity)) {{\n'
                f'    uid\n'
                f'    name\n'
                f'    type\n'
                f'{rel_fields}\n'
                f'  }}'
            )
        query = "{\n" + "\n".join(blocks) + "\n}"

        def _do_query() -> Dict[str, Any]:
            res = self._client.txn(read_only=True).query(query)
            return json.loads(res.json)

        try:
            data = await asyncio.to_thread(_do_query)
        except Exception as exc:
            logger.warning("query_entities DQL failed: %s", exc)
            return "NONE"

        lines = self._format_entity_results(data, len(clean_entities))
        if not lines:
            logger.info("query_entities no matches | entities=%s", clean_entities)
            return "NONE"
        logger.info("query_entities OK | entities=%s lines=%d", clean_entities, len(lines))
        return "\n".join(lines)

    # =====================================================================
    # Pattern building
    # =====================================================================

    def _classify_slot(self, value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """Return (kind, value). kind is:
          - 'name'    if value is a snake_case identifier (`[A-Za-z0-9_]+`).
          - 'type'    if value is exactly one of the 10 ALLOWED_ENTITY_TYPES.
          - 'invalid' if value is non-empty but doesn't fit either form
                      (e.g. "Color: Yellow", "things I have").
          - None      if value is None / empty (wildcard).
        Callers treat 'invalid' as "reject the whole pattern"."""
        if value is None:
            return None, None
        v = value.strip()
        if not v:
            return None, None
        if v in ALLOWED_ENTITY_TYPES:
            return "type", v
        if _NAME_RE.match(v):
            return "name", v
        return "invalid", v

    def _build_pattern_block(
        self, idx: int, p: GraphPattern
    ) -> Tuple[Optional[str], Optional[str]]:
        """Build the DQL block for one pattern.
        Returns (block, anchor_kind) where anchor_kind is one of:
          - "subject" (forward edge traversal from subject)
          - "object"  (reverse edge traversal from object using ~predicate)
        Returns (None, None) for invalid or too-broad patterns."""
        s_kind, s_val = self._classify_slot(p.subject)
        o_kind, o_val = self._classify_slot(p.object)
        pred_raw = (p.predicate or "").strip()
        pred = self._normalize_predicate(pred_raw) if pred_raw else ""

        # Reject patterns with malformed name slots (e.g. "Color: Yellow", "things I have").
        # The LLM occasionally invents a descriptor string here; we don''t want to send a
        # never-matching DQL query to dgraph. Logged so prompt iterations can react.
        if s_kind == "invalid" or o_kind == "invalid":
            logger.warning(
                "_build_pattern_block reject | idx=%d malformed slot | s=%r o=%r pred=%r",
                idx, p.subject, p.object, p.predicate,
            )
            return None, None

        # If predicate given but not declared in the graph, no point querying.
        if pred and pred not in self._relation_predicates:
            return None, None

        # At least one anchor must be defined.
        if s_kind is None and o_kind is None:
            return None, None

        # ---- Anchor on subject ----
        if s_kind is not None:
            anchor = self._slot_func(s_kind, s_val)
            child_filter = self._slot_child_filter(o_kind, o_val)
            if pred:
                inner = f"{pred}{child_filter} {{ uid name type }}"
                if o_kind is None:
                    # subject + predicate, no object filter — request facets too
                    inner = f"{pred} @facets {{ uid name type }}"
                return (
                    f'  p_{idx}(func: {anchor}) @filter(type(Entity)) {{\n'
                    f'    uid name type\n'
                    f'    {inner}\n'
                    f'  }}',
                    "subject",
                )
            else:
                # No predicate: expand all known relations from subject.
                relations = sorted(r for r in self._relation_predicates if r not in _RESERVED_PREDICATES)
                if not relations:
                    return None, None
                rel_fields = "\n".join(
                    f"    {r}{child_filter} {{ uid name type }}" for r in relations
                )
                return (
                    f'  p_{idx}(func: {anchor}) @filter(type(Entity)) {{\n'
                    f'    uid name type\n'
                    f'{rel_fields}\n'
                    f'  }}',
                    "subject",
                )

        # ---- Anchor on object only (s is None) ----
        # Use reverse edge ~pred. Predicate is mandatory here; without it we'd be
        # walking the whole graph backward.
        if not pred:
            return None, None
        anchor = self._slot_func(o_kind, o_val)
        return (
            f'  p_{idx}(func: {anchor}) @filter(type(Entity)) {{\n'
            f'    uid name type\n'
            f'    ~{pred} @facets {{ uid name type }}\n'
            f'  }}',
            "object",
        )

    def _slot_func(self, kind: str, val: str) -> str:
        """Return the dgraph func() expression for a slot anchor."""
        v = val.replace("\\", "\\\\").replace('"', '\\"')
        if kind == "type":
            return f'eq(type, "{v}")'
        if "_" not in val:
            return f'regexp(name, /^{re.escape(v)}(_.*)?$/)'
        return f'eq(name, "{v}")'

    def _slot_child_filter(self, kind: Optional[str], val: Optional[str]) -> str:
        """Return the `@filter(...)` for the inner edge expansion. Empty if wildcard."""
        if kind is None or val is None:
            return ""
        v = val.replace("\\", "\\\\").replace('"', '\\"')
        if kind == "type":
            return f' @filter(eq(type, "{v}"))'
        if "_" not in val:
            return f' @filter(regexp(name, /^{re.escape(v)}(_.*)?$/))'
        return f' @filter(eq(name, "{v}"))'

    def _format_pattern_results(
        self,
        dql_result: Dict[str, Any],
        descriptors: List[Tuple[int, GraphPattern, str]],
    ) -> List[str]:
        """Walk dql_result for each pattern block, render prose lines, dedupe."""
        seen: set[str] = set()
        lines: List[str] = []
        for idx, pattern, anchor in descriptors:
            block = dql_result.get(f"p_{idx}", [])
            for node in block:
                anchor_name = node.get("name")
                if not anchor_name:
                    continue
                # Each node has predicate fields (forward) or ~pred (reverse).
                for key, value in node.items():
                    if key in {"uid", "name", "type"}:
                        continue
                    if "|" in key:
                        continue  # facet sibling
                    if key in _RESERVED_PREDICATES:
                        continue
                    if not isinstance(value, list):
                        continue
                    is_reverse = key.startswith("~")
                    pred_name = key[1:] if is_reverse else key
                    for j, neighbor in enumerate(value):
                        if not isinstance(neighbor, dict):
                            continue
                        n_name = neighbor.get("name")
                        if not n_name:
                            continue
                        # For forward edges: anchor_name pred n_name.
                        # For reverse edges: n_name pred anchor_name.
                        if is_reverse:
                            line = self._render_edge(n_name, pred_name, anchor_name, node, j, key)
                        else:
                            line = self._render_edge(anchor_name, pred_name, n_name, node, j, key)
                        if line not in seen:
                            seen.add(line)
                            lines.append(line)
        return lines

    def _format_entity_results(self, dql_result: Dict[str, Any], num_blocks: int) -> List[str]:
        """Walk legacy entity-block response and emit prose lines, deduped."""
        seen: set[str] = set()
        lines: List[str] = []
        for i in range(num_blocks):
            block = dql_result.get(f"e_{i}", [])
            for node in block:
                subj_name = node.get("name")
                if not subj_name:
                    continue
                for key, value in node.items():
                    if key in {"uid", "name", "type"}:
                        continue
                    if "|" in key:
                        continue
                    if key in _RESERVED_PREDICATES:
                        continue
                    if isinstance(value, list):
                        for j, neighbor in enumerate(value):
                            obj_name = neighbor.get("name") if isinstance(neighbor, dict) else None
                            if not obj_name:
                                continue
                            line = self._render_edge(subj_name, key, obj_name, node, j, key)
                            if line not in seen:
                                seen.add(line)
                                lines.append(line)
        return lines

    def _render_edge(
        self,
        subject: str,
        predicate: str,
        obj: str,
        node: Dict[str, Any],
        neighbor_index: int,
        facet_key_root: str,
    ) -> str:
        """Render `- subject predicate object (facet=value, ...)` for one edge.
        facet_key_root is the actual key in the node (may be `~pred` for reverse)."""
        facets: List[str] = []
        for fkey in ("since", "on", "confidence"):
            facet_key = f"{facet_key_root}|{fkey}"
            facet_data = node.get(facet_key)
            if not facet_data:
                continue
            if isinstance(facet_data, dict):
                val = facet_data.get(str(neighbor_index))
                if val is None and len(facet_data) == 1:
                    val = next(iter(facet_data.values()))
                if val is not None:
                    facets.append(f"{fkey}={val}")
            else:
                facets.append(f"{fkey}={facet_data}")
        suffix = f" ({', '.join(facets)})" if facets else ""
        return f"- {subject} {predicate} {obj}{suffix}"

    # =====================================================================
    # Helpers
    # =====================================================================

    def _normalize_predicate(self, predicate: str) -> str:
        """Lowercase + snake_case + canonicalize. Two layers:
          1) Direct verb mapping (loves -> likes).
          2) Compound predicate: split on first underscore; if the suffix is a
             known noun synonym, rewrite (has_grandma -> has_grandmother).
        Predicates not in any map are returned as-is (soft canonicalization)."""
        p = predicate.strip().lower().replace(" ", "_")
        p = re.sub(r"[^a-z0-9_]", "", p)
        if not p:
            return p
        if p in PREDICATE_CANON_VERBS:
            return PREDICATE_CANON_VERBS[p]
        if "_" in p:
            prefix, _, suffix = p.partition("_")
            if suffix in PREDICATE_NOUN_CANON:
                return f"{prefix}_{PREDICATE_NOUN_CANON[suffix]}"
        return p

    def _normalize_entity_suffix(self, name: str) -> str:
        """Normalize the qualifier suffix of a qualified entity name.
        e.g. Juan_bro -> Juan_brother, Maria_gramps -> Maria_grandfather."""
        if "_" not in name:
            return name
        prefix, _, suffix = name.partition("_")
        if suffix in PREDICATE_NOUN_CANON:
            return f"{prefix}_{PREDICATE_NOUN_CANON[suffix]}"
        return name

    async def _canonicalize_entity_name(self, name: str) -> str:
        if "_" in name:
            canonical = self._normalize_entity_suffix(name)
            if canonical != name:
                esc = canonical.replace('"', '\\"')
                query = (
                    '{ q(func: eq(name, "' + esc
                    + '")) @filter(type(Entity)) { name } }'
                )
                def _do_query() -> Dict[str, Any]:
                    res = self._client.txn(read_only=True).query(query)
                    return json.loads(res.json)

                try:
                    data = await asyncio.to_thread(_do_query)
                except Exception as exc:
                    logger.warning(
                        "Canonicalize suffix lookup failed for %r (->%r): %s",
                        name, canonical, exc,
                    )
                else:
                    matches = [r.get("name") for r in data.get("q", []) if r.get("name")]
                    if canonical in matches:
                        logger.info(
                            "Canonicalize suffix: %r -> %r (existing node reused)",
                            name, canonical,
                        )
                        return canonical
                # Canonical form doesn't exist yet — create it
                logger.info(
                    "Canonicalize suffix: %r -> %r (no existing match, using canonical)",
                    name, canonical,
                )
                return canonical
            return canonical

        safe = re.escape(name)
        query = (
            "{ q(func: regexp(name, /^"
            + safe
            + "(_.*)?$/)) @filter(type(Entity)) { name } }"
        )

        def _do_query() -> Dict[str, Any]:
            res = self._client.txn(read_only=True).query(query)
            return json.loads(res.json)

        try:
            data = await asyncio.to_thread(_do_query)
        except Exception as exc:
            logger.warning("Canonicalize query failed for %r: %s", name, exc)
            return name

        matches = [r.get("name") for r in data.get("q", []) if r.get("name")]
        if not matches:
            return name
        if name in matches:
            return name
        if len(matches) == 1:
            return matches[0]
        return name

    async def _batch_canonicalize_entity_names(self, names: List[str]) -> Dict[str, str]:
        """Resolve multiple entity names in a single DQL query.
        Returns mapping original_name -> canonical_name (or original if unknown).
        Normalizes qualifier suffixes (e.g. Juan_bro -> Juan_brother) before querying.
        """
        # Step 1: normalize qualifier suffixes
        result: Dict[str, str] = {}
        suffix_normalized: Dict[str, str] = {}
        for n in names:
            result[n] = self._normalize_entity_suffix(n)
            if result[n] != n:
                suffix_normalized[n] = result[n]

        # Step 2: for suffix-normalized names, check exact match in Dgraph
        if suffix_normalized:
            exact_query_lines = []
            normal_map: Dict[int, str] = {}
            for i, (orig, canonical) in enumerate(suffix_normalized.items()):
                esc = canonical.replace('"', '\\"')
                exact_query_lines.append(
                    f'  e_{i}(func: eq(name, "{esc}")) @filter(type(Entity)) {{ name }}'
                )
                normal_map[i] = orig
            exact_query = "{\n" + "\n".join(exact_query_lines) + "\n}"

            def _do_exact() -> Dict[str, Any]:
                res = self._client.txn(read_only=True).query(exact_query)
                return json.loads(res.json)

            try:
                exact_data = await asyncio.to_thread(_do_exact)
            except Exception as exc:
                logger.warning("Batch canonicalize exact suffix query failed: %s", exc)
            else:
                for i, orig in normal_map.items():
                    canonical = suffix_normalized[orig]
                    matches = [r.get("name") for r in exact_data.get(f"e_{i}", []) if r.get("name")]
                    if canonical in matches:
                        logger.info(
                            "Canonicalize batch suffix: %r -> %r (existing node reused)",
                            orig, canonical,
                        )
                        result[orig] = canonical

        # Step 3: resolve bare names (without underscore) via regex
        to_resolve = [n for n in names if "_" not in self._normalize_entity_suffix(n)]
        # dedupe while preserving order
        seen: set[str] = set()
        to_resolve = [n for n in to_resolve if not (n in seen or seen.add(n))]

        if not to_resolve:
            return result

        query_lines = []
        for i, n in enumerate(to_resolve):
            query_lines.append(
                f'  q_{i}(func: regexp(name, /^{re.escape(n)}(_.*)?$/)) '
                f'@filter(type(Entity)) {{ name }}'
            )
        query_block = "{\n" + "\n".join(query_lines) + "\n}"

        def _do_query() -> Dict[str, Any]:
            res = self._client.txn(read_only=True).query(query_block)
            return json.loads(res.json)

        try:
            data = await asyncio.to_thread(_do_query)
        except Exception as exc:
            logger.warning("Batch canonicalize failed during DQL regex query: %s", exc)
            return result

        for i, n in enumerate(to_resolve):
            query_name = f"q_{i}"
            matches = [r.get("name") for r in data.get(query_name, []) if r.get("name")]
            if not matches:
                pass
            elif n in matches:
                pass
            elif len(matches) == 1:
                result[n] = matches[0]
        return result

    def _declare_predicate(self, predicate: str) -> None:
        schema_line = f"{predicate}: [uid] @reverse ."
        logger.debug("_declare_predicate: declaring schema_line=%s", schema_line)
        try:
            self._client.alter(pydgraph.Operation(schema=schema_line))
            # update local cache immediately and bump refresh timestamp
            self._declared_predicates.add(predicate)
            self._relation_predicates.add(predicate)
            self._predicates_last_refreshed = time.time()
            logger.info("Declared new predicate: %s", schema_line)
        except Exception as exc:
            logger.error("Could not declare predicate %s: %s", predicate, exc, exc_info=True)
            raise

    def _resolve_entity_type(self, name: str, entity_types: Dict[str, str]) -> str:
        raw_type = entity_types.get(name) or "Other"
        return raw_type if raw_type in ALLOWED_ENTITY_TYPES else "Other"

    def _build_upsert_parts(
        self,
        norm_triplets: List[Dict[str, str]],
        canonical: Dict[str, str],
        entity_types: Dict[str, str],
        time_context: str,
        source_doc_id: Optional[str],
    ) -> Tuple[str, str]:
        logger.debug("_build_upsert_parts called | triplets=%d canonical=%d entity_types=%d time_context=%r source=%s",
                    len(norm_triplets), len(canonical), len(entity_types), time_context, source_doc_id)
        unique_names = sorted({canonical[n] for n in canonical})
        logger.debug("_build_upsert_parts: unique_names=%s", unique_names)
        aliases: Dict[str, str] = {}
        for i, cname in enumerate(unique_names):
            slug = re.sub(r"[^a-zA-Z0-9_]", "_", cname).lower()
            aliases[cname] = f"v_{i}_{slug}"
        logger.debug("_build_upsert_parts: aliases=%s", aliases)

        query_lines: List[str] = []
        for cname, alias in aliases.items():
            escaped = cname.replace("\\", "\\\\").replace('"', '\\"')
            query_lines.append(
                f'  {alias} as var(func: eq(name, "{escaped}")) @filter(type(Entity))'
            )
        query_block = "query {\n" + "\n".join(query_lines) + "\n}"
        logger.debug("_build_upsert_parts: query_block=%s", query_block)

        nquads: List[str] = []
        for cname, alias in aliases.items():
            etype = self._resolve_entity_type(cname, entity_types)
            cname_esc = cname.replace("\\", "\\\\").replace('"', '\\"')
            nquads.append(f'uid({alias}) <name> "{cname_esc}" .')
            nquads.append(f'uid({alias}) <type> "{etype}" .')
            nquads.append(f'uid({alias}) <dgraph.type> "Entity" .')
            if source_doc_id:
                doc_esc = source_doc_id.replace('"', '\\"')
                nquads.append(f'uid({alias}) <source_docs> "{doc_esc}" .')

        time_clean = (time_context or "").strip()
        for t in norm_triplets:
            sub_alias = aliases[canonical[t["subject"]]]
            obj_alias = aliases[canonical[t["object"]]]
            pred = t["predicate"]
            if time_clean:
                facet_key = "on" if pred in EVENT_PREDICATES else "since"
                tc_esc = time_clean.replace('"', '\\"')
                nquads.append(
                    f'uid({sub_alias}) <{pred}> uid({obj_alias}) ({facet_key}="{tc_esc}") .'
                )
            else:
                nquads.append(f'uid({sub_alias}) <{pred}> uid({obj_alias}) .')

        nquads_str = "\n".join(nquads)
        logger.debug("_build_upsert_parts: built %d nquads | first 300 chars=%s", len(nquads), nquads_str[:300])
        return query_block, nquads_str

    # =====================================================================
    # Infrastructure / deletion
    # =====================================================================

    async def delete_all(self) -> str:
        """Wipe all data in the dgraph instance.

        Tries `drop_all` first (resets schema + data). If the standalone
        server rejects the operation, falls back to a DQL delete of all
        Entity nodes + their edges.

        After wiping, re-applies the base scalar predicates so the schema
        is ready for subsequent store operations. Clears the in-memory
        predicate caches.

        Returns an error message string (empty on success).
        """
        errors: list[str] = []

        # 1) Drop all data
        try:
            self._client.alter(pydgraph.Operation(drop_all=True))
            logger.info("GraphService.delete_all: drop_all OK")
        except Exception as exc:
            logger.warning(
                "GraphService.delete_all: drop_all failed (%s), falling back to DQL delete",
                exc,
            )
            try:
                def _do_dql_delete():
                    txn = self._client.txn()
                    try:
                        query = "{\n  all as var(func: type(Entity))\n}"
                        mutation = pydgraph.Mutation(del_nquads="uid(all) * * .")
                        req = pydgraph.Request(
                            query=query, mutations=[mutation], commit_now=True
                        )
                        txn.do_request(req)
                    finally:
                        txn.discard()

                await asyncio.to_thread(_do_dql_delete)
                logger.info("GraphService.delete_all: DQL fallback delete OK")
            except Exception as exc2:
                msg = f"DQL fallback delete failed: {exc2}"
                logger.error("GraphService.delete_all: %s", msg)
                errors.append(msg)

        # 2) Re-apply base scalar predicates (idempotent)
        base_schema = (
            "name: string @index(exact,term,fulltext,trigram) .\n"
            "type: string @index(exact) .\n"
            "source_docs: [string] .\n"
            "\n"
            "type Entity {\n"
            "  name\n"
            "  type\n"
            "  source_docs\n"
            "}\n"
        )
        try:
            self._client.alter(pydgraph.Operation(schema=base_schema))
            logger.info("GraphService.delete_all: base schema re-applied")
        except Exception as exc:
            msg = f"Base schema re-apply failed: {exc}"
            logger.error("GraphService.delete_all: %s", msg)
            errors.append(msg)

        # 3) Clear in-memory predicate caches so they get refreshed on next access
        self._declared_predicates = {"name", "type", "source_docs", "dgraph.type"}
        self._relation_predicates = set()
        self._predicates_last_refreshed = 0.0

        return "\n".join(errors)

    def close(self) -> None:
        try:
            self._stub.close()
            logger.info("GraphService stub closed")
        except Exception as exc:
            logger.warning("GraphService.close error: %s", exc)