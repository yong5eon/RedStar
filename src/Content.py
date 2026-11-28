from dataclasses import dataclass
from typing import (
	Any,
	Mapping,
	Optional,
	Sequence,
)

__all__ = (
	'Content',
)


@dataclass(frozen=True)
class Content:
	"""Describe input or output content formats, schemas, and examples."""

	format: str
	schema: Optional[object] = None
	example: Any = None
	item_schema: Optional[object] = None
	item_encoding: Optional[Mapping[str, object]] = None
	prefix_encoding: Optional[Sequence[Mapping[str, object]]] = None
