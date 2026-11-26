from collections.abc import (
	Mapping,
	Sequence,
)
from enum import Enum
from json import (
	dumps,
	loads,
)
from typing import Any

from .Value import (
	Value,
	Condition,
	Schema,
	OneOf,
	AllOf,
)
from .Types import (
	Boolean,
	IntegerFormat,
	Integer,
	NumberFormat,
	Number,
	StringFormat,
	String,
	Binary,
	BinaryBase64Encoded,
	Array,
	Object,
	Properties,
)

__all__ = (
	'Value',
	'Condition',
	'Schema',
	'OneOf',
	'AllOf',
	'Boolean',
	'IntegerFormat',
	'Integer',
	'NumberFormat',
	'Number',
	'StringFormat',
	'String',
	'Binary',
	'BinaryBase64Encoded',
	'Array',
	'Object',
	'Properties',
	'schema_to_dict',
)


def schema_value(
	value: Any,
) -> Any:
	if isinstance(
		value,
		Schema,
	):
		return schema_value(value.format)
	if isinstance(
		value,
		Condition,
	):
		if isinstance(
			value,
			OneOf,
		):
			key = 'oneOf'
		elif isinstance(
			value,
			AllOf,
		):
			key = 'allOf'
		else:
			raise TypeError('Unsupported schema condition: ' + type(value).__name__)
		return {key: [schema_value(arg) for arg in value.args]}
	if isinstance(
		value,
		Mapping,
	):
		return {
			key: schema_value(item) for key, item in value.items()
		}
	if isinstance(
		value,
		Sequence,
	) and not isinstance(
		value,
		(
			str,
			bytes,
			bytearray,
		),
	):
		return [schema_value(item) for item in value]
	if isinstance(value, Enum):
		return schema_value(value.value)
	if value is None or isinstance(
		value,
		(
			str,
			int,
			float,
			bool,
		),
	):
		return value
	raise TypeError('Unsupported schema value: ' + type(value).__name__)


def schema_to_dict(
	o: Schema,
) -> dict:
	if not isinstance(
		o,
		Schema,
	):
		raise TypeError('A Schema is required')
	result = schema_value(o)
	if not isinstance(
		result,
		dict,
	):
		raise TypeError('A schema must describe an object, value or condition')
	return loads(dumps(
		result,
		allow_nan=False,
	))
