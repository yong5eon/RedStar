from collections.abc import (
	Mapping,
	Sequence,
)
from copy import deepcopy
from time import monotonic
from re import (
	fullmatch,
	sub,
)
from typing import (
	Any,
	Optional,
	Union,
)

from yaml import safe_dump

from RedStar import (
	Application,
	Auth,
	Body,
	Content,
	Extension,
	ExtensionCleanup,
	ExtensionRequest,
	ExtensionRequestError,
	ExtensionRequestResponse,
	ExtensionStartup,
	Headers,
	Parameters,
	QueryString,
	Request,
	Response,
	ResponseSpecification,
	getLogger,
)
from RedStar.Descriptor import (
	Condition,
	OneOf,
	Schema,
	schema_value,
)
from RedStar.IO.Readers import (
	ByteStringContentReader,
	FormUrlEncodedContentReader,
	JavaScriptObjectNotationContentReader,
	TextContentReader,
)
from RedStar.Responses import ResponseJSON
from RedStar.Extensions.FileSystem import FileSystemRoute
from RedStar.Extensions.Utils.Routes import (
	http_routes,
	validate_path,
)

__all__ = (
	'SpecificationsJSON',
	'SpecificationsYAML',
	'Specifications31',
	'Specifications32',
)


_STANDARD_METHODS = frozenset((
	'get',
	'put',
	'post',
	'delete',
	'options',
	'head',
	'patch',
	'trace',
))
_SEQUENTIAL_MEDIA_TYPES = frozenset((
	'text/event-stream',
	'application/jsonl',
	'application/json-seq',
	'multipart/mixed',
))


class SpecificationsGenerator:
	version: str

	def schema(
		self,
		value: object,
		schemas: dict[str, Any],
	) -> object:
		self.validate_schema(value)
		if isinstance(value, Schema):
			name = value.name
			converted = self.schema(value.format, schemas)
			if name in schemas and schemas[name] != converted:
				raise ValueError('Conflicting schemas with the same name: ' + name)
			schemas[name] = converted
			return {'$ref': '#/components/schemas/' + name.replace('~', '~0').replace('/', '~1')}
		return schema_value(value)

	def validate_schema(
		self,
		value: object,
	) -> None:
		return

	def validate_content(
		self,
		value: Content,
	) -> None:
		return

	def contents(
		self,
		value: object,
		schemas: dict[str, Any],
	) -> dict[str, Any]:
		items = (value,) if isinstance(value, Content) else tuple(value or ())
		result: dict[str, Any] = {}
		for item in items:
			if not isinstance(item, Content):
				raise TypeError('Body specifications require Content instances')
			self.validate_content(item)
			if item.format in result:
				raise ValueError('Duplicate body format: ' + item.format)
			entry: dict[str, Any] = {}
			if item.schema is not None:
				entry['schema'] = self.schema(item.schema, schemas)
			if item.example is not None:
				entry['example'] = deepcopy(item.example)
			if item.item_schema is not None:
				entry['itemSchema'] = self.schema(item.item_schema, schemas)
			if item.item_encoding is not None:
				entry['itemEncoding'] = deepcopy(dict(item.item_encoding))
			if item.prefix_encoding is not None:
				entry['prefixEncoding'] = deepcopy([
					dict(encoding) for encoding in item.prefix_encoding
				])
			result[item.format] = entry
		return result

	def responses(
		self,
		value: object,
		schemas: dict[str, Any],
	) -> dict[str, Any]:
		if value is None:
			return {'default': {'description': 'No response specification declared'}}
		if isinstance(value, ResponseSpecification):
			items = (value,)
		elif isinstance(value, Mapping):
			result = {}
			for code, response in value.items():
				if fullmatch(r'default|[1-5](?:[0-9]{2}|XX)', str(code)) is None:
					raise ValueError('Invalid OpenAPI response status: ' + str(code))
				if isinstance(response, str):
					result[str(code)] = {'description': response}
				elif isinstance(response, Mapping):
					if not isinstance(response.get('description'), str):
						raise ValueError('OpenAPI responses require a description')
					result[str(code)] = deepcopy(dict(response))
				else:
					raise TypeError('Response mappings require description strings or OpenAPI response objects')
			if not result:
				raise ValueError('Response specification must not be empty')
			return result
		elif isinstance(value, Sequence) and not isinstance(value, str):
			items = value
		else:
			raise TypeError('response must be a ResponseSpecification or response mapping')
		result = {}
		for item in items:
			if not isinstance(item, ResponseSpecification):
				raise TypeError('Response lists must contain ResponseSpecification instances')
			if not 100 <= item.status <= 599:
				raise ValueError('Invalid response status code')
			code = str(item.status)
			if code in result:
				raise ValueError('Duplicate response status: ' + code)
			entry: dict[str, Any] = {'description': item.description}
			if item.content is not None:
				entry['content'] = self.contents(item.content, schemas)
			if item.headers is not None:
				entry['headers'] = {
					key: {'schema': self.schema(value, schemas)}
					for key, value in item.headers.items()
				}
			result[code] = entry
		if not result:
			raise ValueError('Response specification must not be empty')
		return result

	def querystring_parameter(
		self,
		check: QueryString,
		schemas: dict[str, Any],
	) -> dict[str, Any]:
		raise NotImplementedError

	def parameters(
		self,
		route: object,
		properties: object,
		schemas: dict[str, Any],
	) -> list[dict[str, Any]]:
		parameters = []
		path_names = [match.group(1) for match in route.variable.finditer(route.url)]
		if isinstance(route, FileSystemRoute):
			path_names = ['path']
		for location, check, names in (
			('path', properties.parameters, path_names),
			('query', properties.qs, ()),
			('header', properties.headers, ()),
		):
			if (
				location == 'query'
				and isinstance(check, QueryString)
				and not isinstance(check, Headers)
				and check.content is not None
			):
				parameters.append(self.querystring_parameter(check, schemas))
				continue
			if isinstance(check, Parameters):
				formats = check.format if check.format is not None else {}
				keys = list(check.keys)
				keys.extend(key for key in formats if key not in keys)
				if isinstance(check, QueryString) and not isinstance(check, Headers):
					keys.extend(key for key in check.required_keys if key not in keys)
				keys.extend(name for name in names if name not in keys)
			else:
				formats = {}
				keys = list(names)
			for key in keys:
				value = formats.get(key)
				required = location == 'path'
				if isinstance(check, QueryString):
					required = key.lower() in check.required_keys if isinstance(check, Headers) else key in check.required_keys
				entry = {
					'name': key,
					'in': location,
					'required': required,
					'schema': self.schema(value, schemas) if value is not None else {},
				}
				parameters.append(entry)
		return parameters

	def operation(
		self,
		extension: 'Specifications',
		route: object,
		schemas: dict[str, Any],
		security: dict[str, Any],
	) -> dict[str, Any]:
		properties = route.object.properties
		operation: dict[str, Any] = {
			'operationId': route.method + ':' + route.url,
			'responses': self.responses(properties.response, schemas),
		}
		for name in (
			'summary',
			'description',
		):
			value = getattr(properties, name)
			if value is not None:
				operation[name] = value
		if properties.tags is not None:
			operation['tags'] = [properties.tags] if isinstance(properties.tags, str) else list(properties.tags)
		parameters = self.parameters(route, properties, schemas)
		if isinstance(route, FileSystemRoute):
			operation['x-redstar-catch-all'] = True
		if parameters:
			operation['parameters'] = parameters
		if isinstance(properties.body, Body):
			body_content = properties.body.content
			if not body_content:
				for reader, media in (
					(JavaScriptObjectNotationContentReader, 'application/json'),
					(FormUrlEncodedContentReader, 'application/x-www-form-urlencoded'),
					(TextContentReader, 'text/*'),
					(ByteStringContentReader, '*/*'),
				):
					if isinstance(properties.body.reader, reader):
						body_content = (Content(media),)
						break
			if not body_content:
				raise ValueError('Custom readers require a Content specification: ' + route.url)
			operation['requestBody'] = {
				'required': properties.body.required,
				'content': self.contents(body_content, schemas),
			}
		if isinstance(properties.auth, Auth):
			credentials = properties.auth.credentials
			definition = credentials.format
			name = credentials.name
			index = 2
			while name in security and security[name] != definition:
				name = credentials.name + str(index)
				index += 1
			security[name] = definition
			operation['security'] = [{name: []}]
			if properties.auth.optional:
				operation['security'].append({})
		return operation

	def path(
		self,
		route: object,
	) -> str:
		path = sub(
			r':([A-Za-z_][A-Za-z_0-9]*)',
			r'{\1}',
			route.url,
		)
		if isinstance(route, FileSystemRoute):
			path = route.prefix + '{path}'
		return path

	def add_operation(
		self,
		paths: dict[str, Any],
		custom: list[dict[str, Any]],
		route: object,
		path: str,
		operation: dict[str, Any],
	) -> None:
		raise NotImplementedError

	def document(
		self,
		extension: 'Specifications',
	) -> dict[str, Any]:
		started = monotonic()
		schemas: dict[str, Any] = {}
		security: dict[str, Any] = {}
		paths: dict[str, Any] = {}
		custom: list[dict[str, Any]] = []
		for route in extension.application.router.routes:
			if any(route is extension_route for extension_route in extension.application.extension_routes):
				continue
			operation = self.operation(extension, route, schemas, security)
			self.add_operation(
				paths,
				custom,
				route,
				self.path(route),
				operation,
			)
		info = {
			'title': extension.title,
			'version': extension.version,
		}
		if extension.description is not None:
			info['description'] = extension.description
		document: dict[str, Any] = {
			'openapi': self.version,
			'info': info,
			'paths': paths,
			'components': {
				'schemas': schemas,
				'securitySchemes': security,
			},
		}
		if custom:
			document['x-redstar-operations'] = custom
		extension.logger.debug(
			'Specification generated: routes=%s duration=%.6f',
			len(extension.application.router.routes),
			monotonic() - started,
		)
		return document


class Specifications31(SpecificationsGenerator):
	"""Generate an OpenAPI 3.1 document."""

	version = '3.1.0'

	def validate_schema(
		self,
		value: object,
	) -> None:
		if isinstance(value, OneOf) and value.default_mapping is not None:
			raise ValueError('OpenAPI 3.1 does not support discriminator defaultMapping')
		if isinstance(value, Schema):
			self.validate_schema(value.format)
		elif isinstance(value, Condition):
			for item in value.args:
				self.validate_schema(item)
		elif isinstance(value, Mapping):
			discriminator = value.get('discriminator')
			if isinstance(discriminator, Mapping) and 'defaultMapping' in discriminator:
				raise ValueError('OpenAPI 3.1 does not support discriminator defaultMapping')
			for item in value.values():
				self.validate_schema(item)
		elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
			for item in value:
				self.validate_schema(item)
		return

	def validate_content(
		self,
		value: Content,
	) -> None:
		if (
			value.item_schema is not None
			or value.item_encoding is not None
			or value.prefix_encoding is not None
		):
			raise ValueError('OpenAPI 3.1 does not support sequential content fields')
		return

	def querystring_parameter(
		self,
		check: QueryString,
		schemas: dict[str, Any],
	) -> dict[str, Any]:
		raise ValueError('OpenAPI 3.1 does not support querystring parameters')

	def add_operation(
		self,
		paths: dict[str, Any],
		custom: list[dict[str, Any]],
		route: object,
		path: str,
		operation: dict[str, Any],
	) -> None:
		method = route.method.lower()
		if method in _STANDARD_METHODS:
			path_item = paths.setdefault(path, {})
			if method in path_item:
				raise ValueError('Conflicting OpenAPI path and method: ' + route.method + ' ' + path)
			path_item[method] = operation
		else:
			custom.append({
				'method': route.method,
				'path': path,
				'operation': operation,
			})
		return


class Specifications32(SpecificationsGenerator):
	"""Generate an OpenAPI 3.2 document."""

	version = '3.2.0'

	def is_array_schema(
		self,
		value: object,
	) -> bool:
		if isinstance(value, Schema):
			return self.is_array_schema(value.format)
		if isinstance(value, Mapping):
			return value.get('type') == 'array'
		return False

	def validate_content(
		self,
		value: Content,
	) -> None:
		media_type = value.format.lower()
		if value.item_schema is not None and media_type not in _SEQUENTIAL_MEDIA_TYPES:
			raise ValueError('item_schema requires a supported sequential media type')
		if value.item_encoding is not None and not isinstance(value.item_encoding, Mapping):
			raise TypeError('item_encoding must be an encoding mapping')
		if value.prefix_encoding is not None and (
			not isinstance(value.prefix_encoding, Sequence)
			or isinstance(value.prefix_encoding, (str, bytes))
			or any(not isinstance(encoding, Mapping) for encoding in value.prefix_encoding)
		):
			raise TypeError('prefix_encoding must be a sequence of encoding mappings')
		has_encoding = value.item_encoding is not None or value.prefix_encoding is not None
		if has_encoding and not media_type.startswith('multipart/'):
			raise ValueError('item and prefix encoding require a multipart media type')
		if has_encoding and value.item_schema is None and not self.is_array_schema(value.schema):
			raise ValueError('item and prefix encoding require item_schema or an array schema')
		return

	def querystring_parameter(
		self,
		check: QueryString,
		schemas: dict[str, Any],
	) -> dict[str, Any]:
		if check.name is None or check.content is None:
			raise ValueError('querystring parameters require a name and Content declaration')
		return {
			'name': check.name,
			'in': 'querystring',
			'required': bool(check.required_keys),
			'content': self.contents(check.content, schemas),
		}

	def add_operation(
		self,
		paths: dict[str, Any],
		custom: list[dict[str, Any]],
		route: object,
		path: str,
		operation: dict[str, Any],
	) -> None:
		method = route.method.lower()
		path_item = paths.setdefault(path, {})
		if method in _STANDARD_METHODS or method == 'query':
			if method in path_item:
				raise ValueError('Conflicting OpenAPI path and method: ' + route.method + ' ' + path)
			path_item[method] = operation
		else:
			additional = path_item.setdefault('additionalOperations', {})
			if route.method in additional:
				raise ValueError('Conflicting OpenAPI path and method: ' + route.method + ' ' + path)
			additional[route.method] = operation
		return


class Specifications(Extension):
	"""Build an OpenAPI document from the current shared route declarations."""

	logger = getLogger('Extension.Specifications')

	def __init__(
		self,
		path: str,
		*,
		title: str = 'RedStar',
		version: str = '1.0.0',
		description=None,
		specification: Optional[SpecificationsGenerator] = None,
		on_startup: Optional[Union[
			ExtensionStartup,
			Sequence[ExtensionStartup],
		]] = None,
		on_cleanup: Optional[Union[
			ExtensionCleanup,
			Sequence[ExtensionCleanup],
		]] = None,
		on_request: Optional[Union[
			ExtensionRequest,
			Sequence[ExtensionRequest],
		]] = None,
		on_request_response: Optional[Union[
			ExtensionRequestResponse,
			Sequence[ExtensionRequestResponse],
		]] = None,
		on_request_error: Optional[Union[
			ExtensionRequestError,
			Sequence[ExtensionRequestError],
		]] = None,
	):
		super().__init__(
			on_startup=on_startup,
			on_cleanup=on_cleanup,
			on_request=on_request,
			on_request_response=on_request_response,
			on_request_error=on_request_error,
		)
		validate_path(path)
		self.path = path
		if not isinstance(title, str) or not title or not isinstance(version, str) or not version:
			raise ValueError('Document title and version must be non-empty strings')
		if specification is None:
			specification = Specifications31()
		if not isinstance(specification, SpecificationsGenerator):
			raise TypeError('specification must be a Specifications31 or Specifications32 instance')
		self.specification = specification
		self.title = title
		self.version = version
		self.description = description
		return

	def __str__(self) -> str:
		return '{}({})'.format(type(self).__name__, self.path)

	def startup(
		self,
		application: Application,
	) -> None:
		self.application = application
		for route in http_routes(self, self.path):
			application.add_extension_route(self, route)
		super().startup(application)
		return

	def document(
		self,
	) -> dict:
		return self.specification.document(self)


class SpecificationsJSON(Specifications):
	"""Serialize the generated OpenAPI document as JSON."""

	def __call__(
		self,
		request: Request,
	) -> Response:
		response = ResponseJSON(self.document())
		return response


class SpecificationsYAML(Specifications):
	"""Serialize the generated OpenAPI document as YAML."""

	def __call__(
		self,
		request: Request,
	) -> Response:
		response = Response(
			body=safe_dump(
				self.document(),
				allow_unicode=True,
				sort_keys=False,
			).encode('utf-8'),
			format='application/yaml',
		)
		return response
