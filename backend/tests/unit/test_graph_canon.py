"""
Tests unitarios de canonicalizacion de predicates en graph_service.

Verifica que _normalize_predicate mapea sinonimos verbales y nominales
a una forma canonica, usando los mismos diccionarios que la implementacion
real de graph_service.py (snapshot sincronizado manualmente).

Dos capas de canonicalizacion:
  1. PREDICATE_CANON_VERBS: verbos directos (loves -> likes, owns -> has)
  2. PREDICATE_NOUN_CANON: sustantivos en predicados compuestos
     (has_grandma -> has_grandmother)

NOTA: estos diccionarios deben mantenerse sincronizados con los reales
de services/graph_service.py. Si anades entradas alli, actualiza aqui.
"""

import re
import pytest

pytestmark = pytest.mark.unit


# Snapshot of real graph_service dictionaries.

PREDICATE_CANON_VERBS = {
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
    # did (event)
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

PREDICATE_NOUN_CANON = {
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


def _normalize_predicate(predicate: str) -> str:
    """Copia exacta de GraphService._normalize_predicate.

    Lowercase + snake_case + canonicalize. Two layers:
      1) Direct verb mapping (loves -> likes).
      2) Compound predicate: split on first underscore; if the suffix is a
         known noun synonym, rewrite (has_grandma -> has_grandmother).
    Predicates not in any map are returned as-is (soft canonicalization).
    """
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


# -- Simple verb mapping --

class TestVerbCanonicalization:

    @pytest.mark.parametrize("input_pred,expected", [
        ("loves", "likes"),
        ("enjoys", "likes"),
        ("adores", "likes"),
        ("prefers", "likes"),
        ("owns", "has"),
        ("possesses", "has"),
        ("purchased", "bought"),
        ("resides", "lives_in"),
        ("resides_in", "lives_in"),
        ("dwells", "lives_in"),
        ("know", "knows"),
    ])
    def test_direct_verb_mapping(self, input_pred, expected):
        assert _normalize_predicate(input_pred) == expected

    def test_already_canonical(self):
        assert _normalize_predicate("likes") == "likes"
        assert _normalize_predicate("has") == "has"
        assert _normalize_predicate("bought") == "bought"
        assert _normalize_predicate("lives_in") == "lives_in"

    def test_case_insensitive(self):
        assert _normalize_predicate("Loves") == "likes"
        assert _normalize_predicate("OWNS") == "has"

    def test_unknown_predicate_passes_through(self):
        """Predicados no mapeados se devuelven tal cual (soft canonicalization)."""
        assert _normalize_predicate("runcible") == "runcible"
        assert _normalize_predicate("worksfor") == "worksfor"  # sin underscore, no en dict
        assert _normalize_predicate("located_in") == "located_in"  # no en dict
        assert _normalize_predicate("dwelleth") == "dwelleth"  # no en dict


# -- Compound predicates --

class TestCompoundPredicateCanonicalization:

    @pytest.mark.parametrize("input_pred,expected", [
        ("has_grandma", "has_grandmother"),
        ("has_granny", "has_grandmother"),
        ("has_granddad", "has_grandfather"),
        ("has_grandpa", "has_grandfather"),
        ("has_mum", "has_mother"),
        ("has_mom", "has_mother"),
        ("has_dad", "has_father"),
        ("has_daddy", "has_father"),
        ("is_neighbour", "is_neighbor"),
    ])
    def test_noun_canonicalization(self, input_pred, expected):
        assert _normalize_predicate(input_pred) == expected

    def test_compound_verb_is_not_canonicalized(self):
        """El verbo raiz de un compuesto NO se canonicaliza si la 2a parte
        no esta en PREDICATE_NOUN_CANON. El real no hace canon de verbo en compuestos."""
        assert _normalize_predicate("resides_near") == "resides_near"

    def test_compound_with_unknown_suffix(self):
        """Predicado compuesto con sufijo no canonico se devuelve tal cual."""
        assert _normalize_predicate("lives_near") == "lives_near"


# -- Format normalization --

class TestFormatNormalization:

    def test_trailing_whitespace(self):
        assert _normalize_predicate("  likes  ") == "likes"

    def test_spaces_to_underscore(self):
        assert _normalize_predicate("has brother") == "has_brother"

    def test_dashes_removed_by_regex(self):
        """Guiones se ELIMINAN (no se convierten en underscore) porque
        re.sub(r\'[^a-z0-9_]\', \'\', p) los borra. El LLM debe usar espacios
        o snake_case, no guiones."""
        assert _normalize_predicate("has-brother") == "hasbrother"

    def test_already_snake_case(self):
        assert _normalize_predicate("has_brother") == "has_brother"
        assert _normalize_predicate("lives_in") == "lives_in"
        assert _normalize_predicate("works_at") == "works_at"


# -- Edge cases --

class TestEdgeCases:

    def test_empty_string(self):
        assert _normalize_predicate("") == ""

    def test_single_word_unknown(self):
        assert _normalize_predicate("runcible") == "runcible"

    def test_numbers_in_predicate(self):
        assert _normalize_predicate("level_42") == "level_42"

    def test_only_spaces(self):
        """Solo espacios: strip + lower + re.sub deja string vacio."""
        assert _normalize_predicate("   ") == ""

    def test_mixed_case_compound(self):
        assert _normalize_predicate("Has_Grandma") == "has_grandmother"

    def test_special_chars_removed(self):
        """Caracteres especiales fuera de [a-z0-9_] se eliminan antes de canonicalizar."""
        assert _normalize_predicate("loves!") == "likes"  # ! stripped → "loves" → canon → "likes"
        assert _normalize_predicate("has.brother") == "hasbrother"
        assert _normalize_predicate("xyz!") == "xyz"  # desconocido, solo se limpia

    def test_predicate_with_apostrophe_removed(self):
        """La regex [^a-z0-9_] elimina apostrofes y otros caracteres no alfanumericos."""
        assert _normalize_predicate("user's") == "users"
