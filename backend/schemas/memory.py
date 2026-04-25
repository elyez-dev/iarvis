from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional


class LibrarianN8NQuery(BaseModel):
	rag_query: str = Field(..., example="conversation with user's brother Juan about the car")
	graph_entities: List[str] = Field(..., example=["Juan", "brother", "car"])
	time_context: str = Field(..., example="yesterday")
	tries: Optional[int] = Field(0, example=0)


class LibrarianQueryResponse(BaseModel):
	n8n_query: LibrarianN8NQuery
	memory_results: List[Dict[str, Any]] = Field(
		default_factory=list,
		example=[{"id": "123", "score": 2.4, "payload": {"text": "Juan asked about the car yesterday."}}],
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
	time_context: str = Field(..., example="2026-04-07T00:00:00.000-04:00")


class ArchivistQueryResponse(BaseModel):
	n8n_query: ArchivistN8NQuery
	stored_point_id: str = Field(..., example="2e5ab2ec-f934-4e63-9656-9f3e5f4c07cb")
