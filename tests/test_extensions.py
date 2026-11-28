from contextlib import redirect_stdout
from http.client import HTTPConnection
from importlib import import_module
from io import StringIO
from json import loads
from threading import Event
from typing import Any
from unittest import TestCase
from unittest.mock import patch
from yaml import safe_load

from RedStar import (
	Application,
	ApplicationRequestResponse,
	Auth,
	Body,
	ClientError,
	Content,
	Extension,
	Headers,
	Parameters,
	QueryString,
	RequestRunner,
	Response,
	ResponseSpecification,
)
from RedStar.Credentials import (
	Header,
	HTTP,
	OAuth2Password,
)
from RedStar.Descriptor import (
	Array,
	Integer,
	Object,
	OneOf,
	Properties,
	Schema,
	String,
)
from RedStar.Extensions import (
	Status,
	Ping,
	Metrics,
	SpecificationsJSON,
	SpecificationsYAML,
	Specifications31,
	Specifications32,
	Swagger,
)
from RedStar.IO.Readers import (
	JavaScriptObjectNotationContentReader,
	StreamContentReader,
)
from RedStar.Runners.RunFactory import RunFactory
from RedStar.Runners.RunExtension import RunExtensionFactory
from RedStar.Validator.Patterns import ToInteger
from RedStar.IO.Writers import ChunkedStreamWriter

from test_features import (
	SessionAuthorization,
	request,
)
from test_server import running


class Echo(
	RequestRunner,
	method='GET',
	url='/echo/:id',
):
	def run(
		self,
		req,
	):
		return Response(body=req.parameters['id'].encode())


class ExtensionTests(TestCase):
	def started(self, app):
		app.start()
		self.addCleanup(app.stop)
		return app

	def test_status_metrics_uri_and_independent_use(self):
		status = Status('/status', metrics_uri='/custom-metrics?x=1&y=2')
		app = self.started(Application(exts=(status,)))
		with self.assertLogs(level='DEBUG') as logs:
			response = app(request('/status', headers={'Accept': 'application/json'}))
		assert isinstance(response, Response)
		assert isinstance(response.body, bytes)
		self.assertIn(b'data-metrics-uri="/custom-metrics?x=1&amp;y=2"', response.body)
		self.assertIn(b'fetch(document.body.dataset.metricsUri', response.body)
		self.assertEqual(response.header('Content-Type'), 'text/html; charset=utf-8')
		self.assertFalse(any(
			'Status page' in record.getMessage()
			for record in logs.records
		))
		app = self.started(Application(exts=(
			Metrics('/a'),
			Metrics('/b'),
			Status('/status', metrics_uri='/b'),
		)))
		response = app(request('/status'))
		assert isinstance(response, Response)
		assert isinstance(response.body, bytes)
		self.assertIn(b'data-metrics-uri="/b"', response.body)
		return

	def test_status_invalid_metrics_uri(self):
		invalid_uris: tuple[Any, ...] = (
			None,
			'',
			'metrics',
			'https://example.com/metrics',
			'//example.com/metrics',
			'/\\example.com/metrics',
			'/metrics\n',
		)
		for uri in invalid_uris:
			with self.subTest(uri=uri):
				with self.assertRaises(ValueError):
					Status('/status', metrics_uri=uri)
		return

	def test_extension_handler_factory_contract(self):
		with self.assertRaises(TypeError):
			RunFactory()
		extension = Ping('/ping')
		app = Application(exts=(extension,))
		app.start()
		app.stop()
		factory = RunExtensionFactory(
			extension,
			'HEAD',
			'/ping',
		)
		self.assertIsInstance(factory, RunFactory)
		first = factory()
		second = factory()
		self.assertIsNot(first, second)
		self.assertTrue(issubclass(first, RequestRunner))
		self.assertEqual(first.properties.method, 'HEAD')
		self.assertEqual(first.properties.url, '/ping')
		self.assertEqual(first().run(request('/ping')).status, 503)
		return

	def test_call_is_the_required_extension_contract(self):
		class Legacy(Extension):
			def handle(self, app, request):
				return Response()

		with self.assertRaises(TypeError):
			Legacy()
		extension = Ping('/ping')
		self.assertTrue(callable(extension))
		self.assertFalse(hasattr(extension, 'handle'))
		return

	def get(
		self,
		address,
		path,
		headers=None,
	):
		connection = HTTPConnection(
			*address,
			timeout=3,
		)
		try:
			connection.request(
				'GET',
				path,
				headers=headers or {},
			)
			response = connection.getresponse()
			return response.status, dict(response.getheaders()), response.read()
		finally:
			connection.close()

	def test_real_http_extensions_startup_and_application_isolation(self):
		metrics = Metrics('/metrics')
		collector = metrics.collector
		spec = SpecificationsJSON('/spec')
		app = Application(
			exts=(
				Status('/status', metrics_uri='/metrics', title='<RedStar>'),
				Swagger('/swagger', spec_uri='/spec'),
				metrics,
				spec,
				Ping('/ping'),
			),
		)
		app.add(Echo)
		other = Application(exts=(SpecificationsJSON('/spec'),))
		with redirect_stdout(StringIO()) as output:
			with running(app) as address:
				for path, expected in (
					('/ping', 'application/json'),
					('/metrics', 'text/plain'),
					('/spec', 'application/json'),
					('/status', 'text/html'),
					('/swagger', 'text/html'),
				):
					status, headers, body = self.get(address, path)
					self.assertEqual(status, 200, body)
					self.assertTrue(headers['Content-Type'].startswith(expected))
				self.assertTrue(app.running)
				status, headers, body = self.get(address, '/echo/hello')
				self.assertEqual(body, b'hello')
				status, headers, body = self.get(address, '/metrics', {'Accept': 'application/json'})
				self.assertEqual(status, 200)
				self.assertTrue(headers['Content-Type'].startswith('application/json'))
				self.assertEqual(headers['Cache-Control'], 'no-store')
				self.assertIn('GET /echo/:id', loads(body)['requests'])
				status, headers, body = self.get(address, '/swagger')
				self.assertIn(b'data-spec-url="/spec"', body)
				self.assertIn(b'SwaggerUIBundle', body)
				status, headers, body = self.get(address, '/status')
				self.assertIn(b'&lt;RedStar&gt;', body)
				self.assertIn(b'<title>&lt;RedStar&gt; Status</title>', body)
				self.assertIn(b'data-metrics-uri="/metrics"', body)
				self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
				status, headers, body = self.get(address, '/ping')
				self.assertEqual(status, 200)
				self.assertEqual(loads(body), {'status': 'running'})
		self.assertFalse(app.running)
		self.assertIn('Extensions: 5 extensions', output.getvalue())
		self.assertIn(
			'  Extensions: 5 extensions\n' + '\n'.join(
				'    - ' + str(extension) for extension in app.exts
			),
			output.getvalue(),
		)
		self.assertNotIn(f'Swagger: http://127.0.0.1:{address[1]}', output.getvalue())
		self.started(other)
		other_spec = next(extension for extension in other.exts if isinstance(extension, SpecificationsJSON))
		self.assertEqual(other_spec.document()['paths'], {})
		specification = next(extension for extension in app.exts if isinstance(extension, SpecificationsJSON))
		self.assertNotIn('/spec', specification.document()['paths'])
		self.assertNotIn('/status', specification.document()['paths'])
		ping_extension = Ping('/state')
		state = Application(exts=(ping_extension,))
		state.start()
		state.stop()
		ping = ping_extension(request())
		assert isinstance(ping.body, bytes)
		self.assertEqual(ping.status, 503)
		self.assertEqual(loads(ping.body)['status'], 'stopped')
		return

	def test_dependency_collision_and_instance_ownership(self):
		for extensions in (
			(SpecificationsJSON('/same'), SpecificationsJSON('/same')),
		):
			with self.assertRaises(ValueError):
				Application(exts=extensions).start()
		extension = Ping('/ping')
		app = Application(exts=(extension,))
		self.assertEqual(app.exts, (extension,))
		with self.assertRaises(ValueError):
			Application(exts=(extension,))
		self.started(app)

		class Conflict(
			RequestRunner,
			method='GET',
			url='/metrics',
		):
			def run(self, req):
				return Response()

		app = Application(exts=(SpecificationsJSON('/metrics'),))
		app.add(Conflict)
		with self.assertRaises(ValueError):
			app.start()
		with self.assertRaises(ValueError):
			SpecificationsJSON('/:variable')
		return

	def test_lifecycle_order_rollback_and_failures_are_explicit(self):
		events = []

		class Lifecycle(Extension):
			def __init__(self, path, fail=False):
				super().__init__()
				self.path = path
				self.fail = fail
				return

			def startup(self, app):
				if self.fail:
					raise ValueError('시작 실패')
				events.append('start:' + self.path)
				super().startup(app)
				return

			def cleanup(self):
				events.append('stop:' + self.path)
				super().cleanup()
				return

			def __call__(self, req):
				return Response()

		app = Application(exts=(
			Lifecycle('/first'),
			Lifecycle('/last'),
		))
		app.start()
		with self.assertRaises(RuntimeError):
			app.start()
		with self.assertRaises(RuntimeError):
			app.add(Echo)
		app.stop()
		app.stop()
		self.assertEqual(events, ['start:/first', 'start:/last', 'stop:/last', 'stop:/first'])
		events.clear()
		app = Application(exts=(
			Lifecycle('/first'),
			Lifecycle('/fail', fail=True),
		))
		with self.assertRaises(ValueError):
			app.start()
		self.assertFalse(app.running)
		self.assertEqual(events, ['start:/first', 'stop:/first'])
		return

	def test_swagger_spec_uri_escaping_headers_and_head(self):
		swagger = Swagger('/swagger', spec_uri='/custom-spec', title='<RedStar>', description='</script>')
		spec = SpecificationsJSON('/custom-spec')
		app = self.started(Application(exts=(
			swagger,
			spec,
		)))
		response = app(request('/swagger'))
		assert isinstance(response, Response)
		assert isinstance(response.body, bytes)
		self.assertIn(b'data-spec-url="/custom-spec"', response.body)
		self.assertIn(b'&lt;RedStar&gt;', response.body)
		self.assertIn(b'&lt;/script&gt;', response.body)
		self.assertIn(b'validatorUrl: null', response.body)
		self.assertIn(b'persistAuthorization: false', response.body)
		self.assertIn(b'swagger-ui-dist@5.32.0/', response.body)
		self.assertNotIn(b'<header>', response.body)
		self.assertNotIn(b'<h1>', response.body)
		self.assertIn(b'--ui-font:', response.body)
		self.assertIn(b'--code-font:', response.body)
		self.assertIn(b'id="error-message"', response.body)
		self.assertEqual(response.header('Cache-Control'), 'no-store')
		policy = response.header('Content-Security-Policy')
		assert isinstance(policy, str)
		self.assertIn("connect-src 'self'", policy)
		self.assertIn("img-src 'self' data: blob:", policy)
		self.assertIn('https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.0/', policy)
		specification = next(extension for extension in app.exts if isinstance(extension, SpecificationsJSON))
		self.assertNotIn('/swagger', specification.document()['paths'])
		response = app(request('/swagger', headers={'Accept': 'application/json'}))
		assert isinstance(response, Response)
		content_type = response.header('Content-Type')
		assert isinstance(content_type, str)
		self.assertTrue(content_type.startswith('text/html'))
		app.stop()
		with redirect_stdout(StringIO()):
			with running(app) as address:
				connection = HTTPConnection(*address, timeout=3)
				try:
					connection.request('HEAD', '/swagger')
					response = connection.getresponse()
					self.assertEqual(response.status, 200)
					self.assertEqual(response.read(), b'')
				finally:
					connection.close()
		return

	def test_swagger_invalid_settings_and_independent_use(self):
		invalid_settings: tuple[dict[str, Any], ...] = (
			{'title': ''},
			{'title': None},
			{'description': None},
		)
		for settings in invalid_settings:
			with self.subTest(settings=settings):
				with self.assertRaises(ValueError):
					Swagger('/swagger', spec_uri='/spec', **settings)
		for uri in (
			None,
			'',
			'spec.json',
			'https://example.com/spec',
			'//example.com/spec',
			'/\\example.com/spec',
			'/spec\n',
		):
			with self.subTest(uri=uri):
				with self.assertRaises(ValueError):
					Swagger('/swagger', spec_uri=uri)
		swagger = Swagger('/swagger', spec_uri='/external-spec?format=json&version=1')
		response = swagger(request('/swagger'))
		assert isinstance(response.body, bytes)
		self.assertIn(b'data-spec-url="/external-spec?format=json&amp;version=1"', response.body)
		app = self.started(Application(exts=(
			SpecificationsJSON('/a'),
			SpecificationsJSON('/b'),
			Swagger('/swagger', spec_uri='/b'),
		)))
		response = app(request('/swagger'))
		assert isinstance(response, Response)
		assert isinstance(response.body, bytes)
		self.assertIn(b'data-spec-url="/b"', response.body)
		return

	def test_metrics_windows_and_unmatched_cardinality(self):
		metrics_module = import_module('RedStar.Extensions.Metrics')
		extension = Metrics('/metrics')
		metrics = extension.collector
		app = Application(exts=(extension,))
		app.add(Echo)
		with patch.object(metrics_module, 'monotonic', return_value=100.0):
			app.start()
			req = request('/echo/one')
			metrics.begin(req)
			self.assertEqual(metrics.snapshot()['requests']['GET /echo/:id']['active'], 1)
		with patch.object(metrics_module, 'monotonic', return_value=102.0):
			metrics.end(req, 200, None)
		with patch.object(metrics_module, 'monotonic', return_value=103.0):
			stats = metrics.snapshot()['requests']['GET /echo/:id']
			self.assertEqual(stats['windows']['1']['success'], 1)
			self.assertEqual(stats['windows']['1']['max_duration'], 2.0)
			self.assertEqual(stats['duration'], 2.0)
		for uri in (
			'/unknown-one',
			'/unknown-two',
		):
			req = request(uri)
			metrics.begin(req)
			metrics.end(req, 404, None)
		self.assertEqual(metrics.snapshot()['requests']['<unmatched>']['failure'], 2)
		self.assertNotIn('/unknown-one', metrics.requests)
		rendered = metrics.render()
		self.assertIn('route="GET /echo/:id"', rendered)
		self.assertIn('# HELP redstar_requests_total', rendered)
		app.stop()
		return

	def test_metrics_stream_completes_at_application_return_and_observes_processing_error(self):
		release = Event()
		extension = Metrics('/metrics')
		metrics = extension.collector

		class Stream(
			RequestRunner,
			method='GET',
			url='/stream',
		):
			def run(self, req):
				def parts():
					yield b'first'
					if not release.wait(3):
						raise TimeoutError('테스트 스트림 종료 신호 없음')
					yield b'last'
				return Response(body=parts())

		class Invalid(
			RequestRunner,
			method='GET',
			url='/error',
		):
			def run(self, req):
				raise ClientError('요청 오류')

		app = Application(
			exts=(extension,),
		)
		app.add(Stream)
		app.add(Invalid)
		with redirect_stdout(StringIO()):
			with running(app) as address:
				connection = HTTPConnection(*address, timeout=3)
				try:
					connection.request('GET', '/stream')
					response = connection.getresponse()
					self.assertEqual(response.read(5), b'first')
					self.assertEqual(metrics.snapshot()['requests']['GET /stream']['active'], 0)
					release.set()
					self.assertEqual(response.read(), b'last')
					self.assertEqual(metrics.snapshot()['requests']['GET /stream']['success'], 1)
					self.assertEqual(self.get(address, '/error')[0], 400)
					self.assertEqual(metrics.snapshot()['requests']['GET /error']['failure'], 1)
				finally:
					release.set()
					connection.close()
		return

	def test_metrics_direct_output_status_and_failed_stream(self):
		done = Event()

		class Completion(ApplicationRequestResponse):
			def __call__(self, req, response):
				done.set()
				return response

		class Direct(
			RequestRunner,
			method='GET',
			url='/direct',
		):
			def run(self, req):
				writer = ChunkedStreamWriter(req.writer)
				writer.begin(status=400)
				writer.chunk(b'bad')
				return None

		extension = Metrics('/metrics')
		metrics = extension.collector
		app = Application(
			exts=(extension,),
			on_request_response=Completion(),
		)
		app.add(Direct)
		with redirect_stdout(StringIO()):
			with running(app) as address:
				self.assertEqual(self.get(address, '/direct')[0], 400)
				self.assertTrue(done.wait(3))
				self.assertEqual(metrics.snapshot()['requests']['GET /direct']['failure'], 1)
		return

	def test_metrics_does_not_reclassify_later_stream_failure(self):
		class Broken(
			RequestRunner,
			method='GET',
			url='/broken',
		):
			def run(self, req):
				def parts():
					yield b'partial'
					raise ValueError('스트림 생성 오류')
				return Response(body=parts())

		extension = Metrics('/metrics')
		metrics = extension.collector
		app = Application(
			exts=(extension,),
		)
		app.add(Broken)
		with redirect_stdout(StringIO()):
			with self.assertLogs('Server', level='ERROR'):
				with running(app) as address:
					self.assertEqual(self.get(address, '/broken')[2], b'partial')
					stats = metrics.snapshot()['requests']['GET /broken']
					self.assertEqual(stats['failure'], 0)
					self.assertEqual(stats['success'], 1)
					self.assertEqual(stats['active'], 0)
		return


class SpecTests(TestCase):
	def test_live_extension_ownership_does_not_hide_general_methods_at_same_path(self):
		class Submit(
			RequestRunner,
			method='POST',
			url='/shared',
		):
			def run(
				self,
				req,
			):
				return Response()

		app = Application(exts=(
			SpecificationsJSON('/spec'),
			Ping('/shared'),
		))
		app.add(Submit)
		app.start()
		self.addCleanup(app.stop)
		specification = next(extension for extension in app.exts if isinstance(extension, SpecificationsJSON))
		document = specification.document()
		self.assertEqual(set(document['paths']['/shared']), {'post'})
		self.assertNotIn('/spec', document['paths'])
		return

	def test_openapi_metadata_schema_auth_and_custom_methods(self):
		class Documented(
			RequestRunner,
			method='POST',
			url='/items/:id',
			summary='항목 생성',
			description='본문을 검증한다',
			tags=(
				'Items',
				'Write',
			),
			parameters=Parameters(
				{'id': ToInteger()},
				format={'id': Integer(min=1)},
			),
			qs=QueryString(
				{},
				requires='limit',
				format={'limit': Integer(default=5, required=False)},
			),
			headers=Headers(
				{},
				requires='X-Required',
				format={'X-Required': String(min=2, max=8, enum=('yes', 'no'))},
			),
			body=Body(
				JavaScriptObjectNotationContentReader(),
				content=Content(
					'application/json',
					Object(properties=Properties(value=Integer(min=0, max=10))),
					{
						'value': 1,
						'strings': [
							'yes',
							'true',
							'null',
							'01',
							'2026-11-25',
							'한글',
						],
						'values': [
							None,
							True,
							False,
							3,
							3.5,
						],
						'nested': {'text': 'café'},
					},
				),
			),
			response=ResponseSpecification(
				201,
				'생성됨',
				Content('application/json', Schema(
					'Model',
					Object(description='Model', properties=Properties(value=Integer(description='값'))),
				)),
			),
			auth=Auth(
				SessionAuthorization(),
				HTTP('Bearer'),
				optional=True,
			),
		):
			def run(self, req):
				return Response(status=201)

		class Custom(
			RequestRunner,
			method='CUSTOM',
			url='/custom',
		):
			def run(self, req):
				return Response()

		class Upload(
			RequestRunner,
			method='PUT',
			url='/upload',
			body=Body(StreamContentReader()),
		):
			def run(self, req):
				return Response()

		specification = SpecificationsJSON('/spec')
		yaml_specification = SpecificationsYAML('/spec.yaml')
		app = Application(exts=(
			specification,
			yaml_specification,
		))
		app.add(Documented)
		app.add(Custom)
		app.add(Upload)
		app.start()
		self.addCleanup(app.stop)
		spec = next(extension for extension in app.exts if isinstance(extension, SpecificationsJSON))
		document = spec.document()
		self.assertEqual(document['openapi'], '3.1.0')
		self.assertEqual(
			list(document['paths']['/upload']['put']['requestBody']['content']),
			['*/*'],
		)
		operation = document['paths']['/items/{id}']['post']
		self.assertEqual(operation['summary'], '항목 생성')
		self.assertEqual(operation['description'], '본문을 검증한다')
		self.assertEqual(operation['tags'], ['Items', 'Write'])
		self.assertEqual(operation['security'], [{'HTTP': []}, {}])
		self.assertEqual(
			operation['responses']['201']['content']['application/json']['schema']['$ref'],
			'#/components/schemas/Model',
		)
		parameters = {(item['in'], item['name']): item for item in operation['parameters']}
		self.assertTrue(parameters['path', 'id']['required'])
		self.assertEqual(parameters['path', 'id']['schema']['minimum'], 1)
		self.assertTrue(parameters['query', 'limit']['required'])
		self.assertEqual(parameters['query', 'limit']['schema']['default'], 5)
		self.assertTrue(parameters['header', 'X-Required']['required'])
		self.assertEqual(parameters['header', 'X-Required']['schema']['minLength'], 2)
		self.assertEqual(parameters['header', 'X-Required']['schema']['maxLength'], 8)
		self.assertEqual(parameters['header', 'X-Required']['schema']['enum'], ['yes', 'no'])
		expected_example = {
			'value': 1,
			'strings': ['yes', 'true', 'null', '01', '2026-11-25', '한글'],
			'values': [None, True, False, 3, 3.5],
			'nested': {'text': 'café'},
		}
		self.assertEqual(
			operation['requestBody']['content']['application/json']['example'],
			expected_example,
		)
		self.assertEqual(document['components']['schemas']['Model'], {
			'type': 'object',
			'properties': {'value': {'type': 'integer', 'description': '값'}},
			'description': 'Model',
			'required': ['value'],
		})
		self.assertEqual(document['x-redstar-operations'][0]['method'], 'CUSTOM')
		json_response = app(request('/spec'))
		with patch(
			'RedStar.Extensions.Specifications.ResponseJSON',
			side_effect=AssertionError('YAML serialization must not use a JSON response'),
		):
			yaml_response = app(request('/spec.yaml'))
		assert isinstance(json_response, Response)
		assert isinstance(yaml_response, Response)
		self.assertIsInstance(json_response.body, bytes)
		self.assertIsInstance(yaml_response.body, bytes)
		self.assertEqual(json_response.header('Content-Type'), 'application/json; charset=utf-8')
		self.assertEqual(yaml_response.header('Content-Type'), 'application/yaml')
		self.assertIn('한글'.encode('utf-8'), yaml_response.body)
		yaml_document = safe_load(yaml_response.body)
		self.assertEqual(yaml_document, document)
		content = yaml_document['paths']['/items/{id}']['post']['requestBody']['content']
		example = content['application/json']['example']
		self.assertEqual(example, expected_example)
		return

	def test_openapi_32_query_custom_methods_and_sequential_content(self):
		class Search(
			RequestRunner,
			method='QUERY',
			url='/search',
			qs=QueryString(
				{'filter': ToInteger()},
				requires='filter',
				name='advancedQuery',
				content=Content(
					'application/x-www-form-urlencoded',
					Object(properties=Properties(filter=Integer())),
				),
			),
			body=Body(
				StreamContentReader(),
				content=Content(
					'application/jsonl',
					item_schema=Schema(
						'SearchItem',
						Object(properties=Properties(id=Integer())),
					),
				),
			),
			response=ResponseSpecification(
				200,
				'Search results',
				(
					Content(
						'text/event-stream',
						item_schema=Object(properties=Properties(id=Integer())),
					),
					Content(
						'multipart/mixed',
						item_schema=Object(properties=Properties(id=Integer())),
						item_encoding={'contentType': 'application/json'},
						prefix_encoding=({'contentType': 'text/plain'},),
					),
					Content(
						'multipart/form-data',
						Array(format=Object(properties=Properties(id=Integer()))),
						item_encoding={'contentType': 'application/json'},
						prefix_encoding=({'contentType': 'text/plain'},),
					),
					Content(
						'application/vnd.redstar.animal+json',
						Schema(
							'Animal',
							OneOf(
								Object(properties=Properties(kind=String())),
								discriminator='kind',
								mapping={'fallback': '#/components/schemas/Unknown'},
								default_mapping='#/components/schemas/Unknown',
							),
						),
					),
					Content(
						'application/vnd.redstar.unknown+json',
						Schema(
							'Unknown',
							Object(properties=Properties(kind=String())),
						),
					),
				),
			),
		):
			def run(self, req):
				return Response()

		class Link(
			RequestRunner,
			method='LINK',
			url='/search',
		):
			def run(self, req):
				return Response()

		specification = SpecificationsJSON(
			'/spec',
			specification=Specifications32(),
		)
		yaml_specification = SpecificationsYAML(
			'/spec.yaml',
			specification=Specifications32(),
		)
		app = Application(exts=(
			specification,
			yaml_specification,
		))
		app.add(Search)
		app.add(Link)
		app.start()
		self.addCleanup(app.stop)
		document = specification.document()
		self.assertEqual(document['openapi'], '3.2.0')
		path_item = document['paths']['/search']
		self.assertIn('query', path_item)
		self.assertEqual(path_item['additionalOperations']['LINK']['operationId'], 'LINK:/search')
		operation = path_item['query']
		self.assertEqual(operation['parameters'], [{
			'name': 'advancedQuery',
			'in': 'querystring',
			'required': True,
			'content': {
				'application/x-www-form-urlencoded': {
					'schema': {
						'type': 'object',
						'properties': {'filter': {'type': 'integer'}},
						'required': ['filter'],
					},
				},
			},
		}])
		self.assertEqual(
			operation['requestBody']['content']['application/jsonl']['itemSchema'],
			{'$ref': '#/components/schemas/SearchItem'},
		)
		self.assertEqual(
			operation['responses']['200']['content']['text/event-stream']['itemSchema'],
			{
				'type': 'object',
				'properties': {'id': {'type': 'integer'}},
				'required': ['id'],
			},
		)
		multipart = operation['responses']['200']['content']['multipart/mixed']
		self.assertEqual(multipart['itemEncoding'], {'contentType': 'application/json'})
		self.assertEqual(multipart['prefixEncoding'], [{'contentType': 'text/plain'}])
		form_data = operation['responses']['200']['content']['multipart/form-data']
		self.assertEqual(form_data['schema']['type'], 'array')
		self.assertEqual(form_data['itemEncoding'], {'contentType': 'application/json'})
		self.assertEqual(form_data['prefixEncoding'], [{'contentType': 'text/plain'}])
		self.assertNotIn('x-redstar-operations', document)
		self.assertEqual(document['components']['schemas']['SearchItem'], {
			'type': 'object',
			'properties': {'id': {'type': 'integer'}},
			'required': ['id'],
		})
		self.assertEqual(document['components']['schemas']['Animal']['discriminator'], {
			'propertyName': 'kind',
			'mapping': {'fallback': '#/components/schemas/Unknown'},
			'defaultMapping': '#/components/schemas/Unknown',
		})
		json_response = app(request('/spec'))
		yaml_response = app(request('/spec.yaml'))
		self.assertEqual(loads(json_response.body), document)
		self.assertEqual(safe_load(yaml_response.body), document)
		return

	def test_openapi_31_rejects_32_only_declarations(self):
		class Streaming(
			RequestRunner,
			method='GET',
			url='/stream',
			response=ResponseSpecification(
				200,
				'Events',
				Content(
					'text/event-stream',
					item_schema=Object(properties=Properties(id=Integer())),
				),
			),
		):
			def run(self, req):
				return Response()

		specification = SpecificationsJSON('/spec')
		app = Application(exts=(specification,))
		app.add(Streaming)
		app.start()
		self.addCleanup(app.stop)
		with self.assertRaisesRegex(ValueError, 'sequential content fields'):
			specification.document()

		class Query(
			RequestRunner,
			method='GET',
			url='/query',
			qs=QueryString(
				{},
				name='filters',
				content=Content(
					'application/x-www-form-urlencoded',
					Object(properties=Properties()),
				),
			),
		):
			def run(self, req):
				return Response()

		query_specification = SpecificationsJSON('/query-spec')
		query_app = Application(exts=(query_specification,))
		query_app.add(Query)
		query_app.start()
		self.addCleanup(query_app.stop)
		with self.assertRaisesRegex(ValueError, 'querystring parameters'):
			query_specification.document()

		class Discriminator(
			RequestRunner,
			method='GET',
			url='/discriminator',
			response=ResponseSpecification(
				200,
				'Discriminated',
				Content(
					'application/json',
					Schema(
						'Animal',
						OneOf(
							Object(properties=Properties(kind=String())),
							discriminator='kind',
							default_mapping='#/components/schemas/Animal',
						),
					),
				),
			),
		):
			def run(self, req):
				return Response()

		discriminator_specification = SpecificationsJSON('/discriminator-spec')
		discriminator_app = Application(exts=(discriminator_specification,))
		discriminator_app.add(Discriminator)
		discriminator_app.start()
		self.addCleanup(discriminator_app.stop)
		with self.assertRaisesRegex(ValueError, 'defaultMapping'):
			discriminator_specification.document()
		return

	def test_openapi_31_allows_schema_property_named_default_mapping(self):
		class Example(
			RequestRunner,
			method='GET',
			url='/example',
			response=ResponseSpecification(
				200,
				'Example',
				Content(
					'application/json',
					Schema('Example', {
						'type': 'object',
						'properties': {
							'defaultMapping': {'type': 'string'},
						},
					}),
				),
			),
		):
			def run(self, req):
				return Response()

		specification = SpecificationsJSON('/spec')
		app = Application(exts=(specification,))
		app.add(Example)
		app.start()
		self.addCleanup(app.stop)
		document = specification.document()
		self.assertEqual(
			document['components']['schemas']['Example']['properties']['defaultMapping'],
			{'type': 'string'},
		)
		return

	def test_openapi_31_rejects_32_content_fields_in_raw_response_mappings(self):
		class RawResponse(
			RequestRunner,
			method='GET',
			url='/raw-response',
			response={
				'200': {
					'description': 'Events',
					'content': {
						'multipart/mixed': {
							'itemSchema': {'type': 'object'},
							'itemEncoding': {'contentType': 'application/json'},
							'prefixEncoding': [
								{'contentType': 'text/plain'},
							],
						},
					},
				},
			},
		):
			def run(self, req):
				return Response()

		specification = SpecificationsJSON('/spec')
		app = Application(exts=(specification,))
		app.add(RawResponse)
		app.start()
		self.addCleanup(app.stop)
		with self.assertRaisesRegex(ValueError, 'sequential content fields'):
			specification.document()
		return

	def test_openapi_31_rejects_default_mapping_in_raw_response_schema(self):
		class RawResponse(
			RequestRunner,
			method='GET',
			url='/raw-response',
			response={
				'200': {
					'description': 'Animals',
					'content': {
						'application/json': {
							'schema': {
								'oneOf': [{'type': 'object'}],
								'discriminator': {
									'propertyName': 'kind',
									'defaultMapping': '#/components/schemas/Unknown',
								},
							},
						},
					},
				},
			},
		):
			def run(self, req):
				return Response()

		specification = SpecificationsJSON('/spec')
		app = Application(exts=(specification,))
		app.add(RawResponse)
		app.start()
		self.addCleanup(app.stop)
		with self.assertRaisesRegex(ValueError, 'defaultMapping'):
			specification.document()
		return

	def test_openapi_31_does_not_validate_example_data_as_schema(self):
		class RawResponse(
			RequestRunner,
			method='GET',
			url='/raw-response',
			response={
				'200': {
					'description': 'Example',
					'content': {
						'application/json': {
							'schema': {
								'type': 'object',
								'example': {
									'discriminator': {
										'defaultMapping': 'example data',
									},
								},
							},
						},
					},
				},
			},
		):
			def run(self, req):
				return Response()

		specification = SpecificationsJSON('/spec')
		app = Application(exts=(specification,))
		app.add(RawResponse)
		app.start()
		self.addCleanup(app.stop)
		document = specification.document()
		schema = document['paths']['/raw-response']['get']['responses']['200']['content']['application/json']['schema']
		self.assertEqual(
			schema['example'],
			{'discriminator': {'defaultMapping': 'example data'}},
		)
		return

	def test_openapi_32_validates_raw_response_content(self):
		class RawResponse(
			RequestRunner,
			method='GET',
			url='/raw-response',
			response={
				'200': {
					'description': 'Events',
					'content': {
						'multipart/mixed': {
							'itemSchema': {'type': 'object'},
							'itemEncoding': {'contentType': 'application/json'},
							'prefixEncoding': [
								{'contentType': 'text/plain'},
							],
						},
						'application/json': {
							'schema': {
								'oneOf': [{'type': 'object'}],
								'discriminator': {
									'propertyName': 'kind',
									'defaultMapping': '#/components/schemas/Unknown',
								},
							},
						},
					},
				},
			},
		):
			def run(self, req):
				return Response()

		specification = SpecificationsJSON(
			'/spec',
			specification=Specifications32(),
		)
		app = Application(exts=(specification,))
		app.add(RawResponse)
		app.start()
		self.addCleanup(app.stop)
		document = specification.document()
		content = document['paths']['/raw-response']['get']['responses']['200']['content']
		self.assertEqual(
			content['multipart/mixed']['itemSchema'],
			{'type': 'object'},
		)
		self.assertEqual(
			content['multipart/mixed']['itemEncoding'],
			{'contentType': 'application/json'},
		)
		self.assertEqual(
			content['multipart/mixed']['prefixEncoding'],
			[{'contentType': 'text/plain'}],
		)
		self.assertEqual(
			content['application/json']['schema']['discriminator']['defaultMapping'],
			'#/components/schemas/Unknown',
		)
		return

	def test_openapi_32_rejects_invalid_raw_response_content(self):
		class RawResponse(
			RequestRunner,
			method='GET',
			url='/raw-response',
			response={
				'200': {
					'description': 'Events',
					'content': {
						'multipart/mixed': {
							'itemEncoding': {'contentType': 'application/json'},
						},
					},
				},
			},
		):
			def run(self, req):
				return Response()

		specification = SpecificationsJSON(
			'/spec',
			specification=Specifications32(),
		)
		app = Application(exts=(specification,))
		app.add(RawResponse)
		app.start()
		self.addCleanup(app.stop)
		with self.assertRaisesRegex(
			ValueError,
			'require item_schema or an array schema',
		):
			specification.document()
		return

	def test_openapi_32_rejects_multipart_encoding_without_array_schema(self):
		class Invalid(
			RequestRunner,
			method='GET',
			url='/invalid',
			response=ResponseSpecification(
				200,
				'Invalid',
				Content(
					'multipart/form-data',
					Object(properties=Properties(id=Integer())),
					item_encoding={'contentType': 'application/json'},
				),
			),
		):
			def run(self, req):
				return Response()

		specification = SpecificationsJSON(
			'/spec',
			specification=Specifications32(),
		)
		app = Application(exts=(specification,))
		app.add(Invalid)
		app.start()
		self.addCleanup(app.stop)
		with self.assertRaisesRegex(ValueError, 'require item_schema or an array schema'):
			specification.document()
		return

	def test_specifications_base_class_is_not_exported(self):
		extensions = import_module('RedStar.Extensions')
		specifications = import_module('RedStar.Extensions.Specifications')
		self.assertEqual(
			extensions.__all__.count('SpecificationsJSON'),
			1,
		)
		self.assertEqual(
			extensions.__all__.count('SpecificationsYAML'),
			1,
		)
		self.assertNotIn('Specifications', extensions.__all__)
		self.assertIs(extensions.Specifications, specifications)
		self.assertNotIn('Specifications', specifications.__all__)
		self.assertEqual(specifications.Specifications.__name__, 'Specifications')
		for name in ('Specifications31', 'Specifications32'):
			self.assertEqual(extensions.__all__.count(name), 1)
			self.assertIs(getattr(extensions, name), getattr(specifications, name))
			self.assertIn(name, specifications.__all__)
		return

	def test_auth_schemes_with_same_kind_remain_distinct(self):
		def handler(path, credentials):
			class Secured(
				RequestRunner,
				method='GET',
				url=path,
				auth=Auth(SessionAuthorization(), credentials),
			):
				def run(self, req):
					return Response()
			return Secured

		app = Application(exts=(SpecificationsJSON('/spec'),))
		app.add(handler('/one', Header('X-One')))
		app.add(handler('/two', Header('X-Two')))
		app.add(handler('/oauth', OAuth2Password('/token')))
		app.start()
		self.addCleanup(app.stop)
		spec = next(extension for extension in app.exts if isinstance(extension, SpecificationsJSON))
		document = spec.document()
		schemes = document['components']['securitySchemes']
		self.assertEqual(schemes['Header']['name'], 'X-One')
		self.assertEqual(schemes['Header2']['name'], 'X-Two')
		self.assertEqual(schemes['OAuth2Password']['flows']['password']['tokenUrl'], '/token')
		return

	def test_conflicting_named_schemas_raise_instead_of_overwriting(self):
		class Conflicting(
			RequestRunner,
			method='GET',
			url='/conflict',
			response=(
				ResponseSpecification(
					200,
					'정상',
					Content('application/json', Schema('Same', String())),
				),
				ResponseSpecification(
					400,
					'오류',
					Content('application/json', Schema('Same', Integer())),
				),
			),
		):
			def run(self, req):
				return Response()

		app = Application(exts=(SpecificationsJSON('/spec'),))
		app.add(Conflicting)
		app.start()
		self.addCleanup(app.stop)
		spec = next(extension for extension in app.exts if isinstance(extension, SpecificationsJSON))
		with self.assertRaises(ValueError):
			spec.document()
		return

	def test_yaml_serialization_errors_propagate(self):
		specification = SpecificationsYAML('/spec')
		app = Application(exts=(specification,))
		app.start()
		self.addCleanup(app.stop)
		with patch.object(
			specification,
			'document',
			side_effect=ValueError('document generation failed'),
		):
			with self.assertRaisesRegex(ValueError, 'document generation failed'):
				app(request('/spec'))
		with patch(
			'RedStar.Extensions.Specifications.safe_dump',
			side_effect=ValueError('serialization failed'),
		):
			with self.assertRaisesRegex(ValueError, 'serialization failed'):
				app(request('/spec'))
		return
