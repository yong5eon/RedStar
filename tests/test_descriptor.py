from importlib import import_module
from importlib.util import find_spec
from unittest import TestCase

from RedStar.Descriptor import (
	AllOf,
	Integer,
	Object,
	OneOf,
	Properties,
	Schema,
	String,
	schema_to_dict,
)


class DescriptorTests(TestCase):
	def test_removed_data_object_api(self):
		descriptor = import_module('RedStar.Descriptor')
		value = import_module('RedStar.Descriptor.Value')
		for name in ('ToSchema', 'ToObject', 'DumpSchema', 'TypeMapper', 'TypeEncoder'):
			self.assertFalse(hasattr(descriptor, name), name)
			self.assertNotIn(name, descriptor.__all__)
		for name in ('TypeMapper', 'TypeEncoder'):
			self.assertFalse(hasattr(value, name), name)
			self.assertNotIn(name, value.__all__)
		self.assertIsNone(find_spec('RedStar.Descriptor.DataObject'))
		self.assertIn('schema_to_dict', descriptor.__all__)
		return

	def test_schema_to_dict_serializes_nested_conditions(self):
		schema = Schema('Example', Object(properties=Properties(
			value=OneOf(Integer(), AllOf(String(), Schema('Nested', Integer()))),
		)))
		self.assertEqual(schema_to_dict(schema), {
			'type': 'object',
			'properties': {'value': {'oneOf': [
				{'type': 'integer'},
				{'allOf': [{'type': 'string'}, {'type': 'integer'}]},
			]}},
			'required': ['value'],
		})
		return

	def test_schema_to_dict_serializes_discriminator_metadata(self):
		schema = Schema('Discriminated', OneOf(
			String(),
			discriminator='kind',
			mapping={'cat': '#/components/schemas/Cat'},
			default_mapping='#/components/schemas/Unknown',
		))
		self.assertEqual(schema_to_dict(schema), {
			'oneOf': [{'type': 'string'}],
			'discriminator': {
				'propertyName': 'kind',
				'mapping': {'cat': '#/components/schemas/Cat'},
				'defaultMapping': '#/components/schemas/Unknown',
			},
		})
		return

	def test_schema_to_dict_rejects_invalid_values(self):
		with self.assertRaisesRegex(TypeError, 'A Schema is required'):
			schema_to_dict({})
		with self.assertRaisesRegex(TypeError, 'Unsupported schema value: bytes'):
			schema_to_dict(Schema('Invalid', {'example': b'invalid'}))
		with self.assertRaises(ValueError):
			schema_to_dict(Schema('Invalid', {'example': float('nan')}))
		return
