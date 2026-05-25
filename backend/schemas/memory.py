from pydantic import BaseModel, Field
from typing import Dict, List, Literal, Optional


EntityType = Literal[
	"Person", "Animal", "Place", "Object", "Food",
	"Event", "Activity", "Concept", "Feeling", "Other",
]


class GraphPattern(BaseModel):
	"""A search pattern for the knowledge graph: (subject, predicate, object).
	Each slot may be a concrete entity name (e.g. "User", "Juan_brother"), a closed
	EntityType (e.g. "Food", "Person") matching nodes of that type, or null/empty for
	wildcard. At least one of the three must be non-null."""
	subject: Optional[str] = Field(default=None, example="User")
	predicate: Optional[str] = Field(default=None, example="likes")
	object: Optional[str] = Field(default=None, example="Food")


class LibrarianN8NQuery(BaseModel):
	rag_query: str = Field(..., example="conversation with user's brother Juan about the car")
	# Legacy: kept for backward compatibility. New flow uses graph_patterns.
	graph_entities: List[str] = Field(default_factory=list, example=["Juan", "brother", "car"])
	graph_patterns: List[GraphPattern] = Field(
		default_factory=list,
		example=[{"subject": "User", "predicate": "likes", "object": "Food"}],
	)
	time_context: str = Field(default="", example="yesterday")
	tries: Optional[int] = Field(0, example=0)


class LibrarianQueryResponse(BaseModel):
	n8n_query: LibrarianN8NQuery
	memory_results: str = Field(
		default="NONE",
		example="- The user likes milk coffee.\n- The user has a dentist appointment.",
	)
	graph_results: str = Field(
		default="NONE",
		example="- User likes cheese\n- User has_brother Juan_brother\n- Juan_brother bought red_Toyota",
	)


class GraphTriplet(BaseModel):
	subject: str = Field(..., example="User")
	predicate: str = Field(..., example="has_appointment")
	object: str = Field(..., example="dentist")


class ArchivistN8NQuery(BaseModel):
	rag_document: str = Field(..., example="The user has a dentist appointment in three days.")
	graph_triplets: List[GraphTriplet] = Field(
		default_factory=list,
		example=[{"subject": "User", "predicate": "has_appointment", "object": "dentist"}],
	)
	entity_types: Dict[str, EntityType] = Field(
		default_factory=dict,
		example={"User": "Person", "dentist": "Event"},
	)
	time_context: str = Field(default="", example="2026-04-07T00:00:00.000-04:00")


class ArchivistQueryResponse(BaseModel):
	n8n_query: ArchivistN8NQuery
	stored_point_id: str = Field(..., example="2e5ab2ec-f934-4e63-9656-9f3e5f4c07cb")