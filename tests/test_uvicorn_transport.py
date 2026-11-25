from asyncio import (
	Queue,
	create_task,
	get_running_loop,
	to_thread,
	wait_for,
)
from contextlib import suppress
from importlib.util import find_spec
from threading import Event
from typing import (
	Any,
	Callable,
	Mapping,
)
from unittest import (
	IsolatedAsyncioTestCase,
	skipUnless,
)
from unittest.mock import (
	AsyncMock,
	patch,
)

from RedStar import Application
from RedStar.IO.RequestReader import (
	ClientDisconnected,
	RequestReader,
)


class CompletedApplication:
	def __init__(self) -> None:
		self.disconnected = Event()
		return

	def __call__(
		self,
		environ: Mapping[str, Any],
		start_response: Callable[..., object],
	) -> tuple[bytes, ...]:
		if not self.disconnected.wait(2):
			raise TimeoutError('Disconnect was not observed')
		return ()

	async def receive(self) -> dict[str, str]:
		self.disconnected.set()
		return {'type': 'http.disconnect'}


class FailingApplication(CompletedApplication):
	def __call__(
		self,
		environ: Mapping[str, Any],
		start_response: Callable[..., object],
	) -> tuple[bytes, ...]:
		super().__call__(environ, start_response)
		raise ClientDisconnected('unrelated application failure')


class ReadingApplication(CompletedApplication):
	def __call__(
		self,
		environ: Mapping[str, Any],
		start_response: Callable[..., object],
	) -> tuple[bytes, ...]:
		super().__call__(environ, start_response)
		RequestReader(environ['wsgi.input'], size=1).read()
		return ()


@skipUnless(find_spec('a2wsgi') is not None, 'a2wsgi required')
class MiddlewareDisconnectTests(IsolatedAsyncioTestCase):
	async def test_disconnect_log_keeps_request_id_after_worker_returns(self) -> None:
		from RedStar.Adapter.Implements.Uvicorn.HTTP import Middleware

		middleware = Middleware(Application(), 1, 2)
		application = CompletedApplication()
		scope = {
			'type': 'http',
			'http_version': '1.1',
			'method': 'GET',
			'path': '/',
			'query_string': b'',
			'headers': [(b'x-request-id', b'disconnect-123')],
			'server': ('localhost', 80),
			'client': ('localhost', 1234),
		}
		try:
			with self.assertLogs('Server', level='WARNING') as logs:
				await wait_for(middleware(scope, application.receive, AsyncMock()), 3)
			record = next(record for record in logs.records if 'ASGI request stopped' in record.getMessage())
			self.assertEqual(record.request_id, 'disconnect-123')
		finally:
			middleware.executor.shutdown(wait=True)
		return

	async def test_disconnect_before_final_response_is_not_an_asgi_error(self) -> None:
		from RedStar.Adapter.Implements.Uvicorn.HTTP import Middleware

		middleware = Middleware(Application(), 1, 2)
		application = CompletedApplication()
		scope = {
			'type': 'http',
			'http_version': '1.1',
			'method': 'GET',
			'path': '/',
			'query_string': b'',
			'headers': [],
			'server': ('localhost', 80),
			'client': ('localhost', 1234),
		}
		try:
			with patch.object(middleware, 'application', application):
				with self.assertLogs('Server.Uvicorn', level='WARNING'):
					await wait_for(middleware(scope, application.receive, AsyncMock()), 3)
		finally:
			middleware.executor.shutdown(wait=True)
		return

	async def test_unrelated_disconnect_error_after_client_disconnect_propagates(self) -> None:
		from RedStar.Adapter.Implements.Uvicorn.HTTP import Middleware

		middleware = Middleware(Application(), 1, 2)
		application = FailingApplication()
		scope = {
			'type': 'http',
			'http_version': '1.1',
			'method': 'GET',
			'path': '/',
			'query_string': b'',
			'headers': [],
			'server': ('localhost', 80),
			'client': ('localhost', 1234),
		}
		try:
			with patch.object(middleware, 'application', application):
				with self.assertRaisesRegex(ClientDisconnected, 'unrelated application failure'):
					await wait_for(middleware(scope, application.receive, AsyncMock()), 3)
		finally:
			middleware.executor.shutdown(wait=True)
		return

	async def test_request_reader_disconnect_is_handled(self) -> None:
		from RedStar.Adapter.Implements.Uvicorn.HTTP import Middleware

		middleware = Middleware(Application(), 1, 2)
		application = ReadingApplication()
		scope = {
			'type': 'http',
			'http_version': '1.1',
			'method': 'GET',
			'path': '/',
			'query_string': b'',
			'headers': [],
			'server': ('localhost', 80),
			'client': ('localhost', 1234),
		}
		try:
			with patch.object(middleware, 'application', application):
				with self.assertLogs('Server.Uvicorn', level='WARNING'):
					await wait_for(middleware(scope, application.receive, AsyncMock()), 3)
		finally:
			middleware.executor.shutdown(wait=True)
		return

	async def test_unrelated_worker_exception_propagates(self) -> None:
		from RedStar.Adapter.Implements.Uvicorn.HTTP import Middleware

		scope = {
			'type': 'http',
			'http_version': '1.1',
			'method': 'GET',
			'path': '/',
			'query_string': b'',
			'headers': [],
			'server': ('localhost', 80),
			'client': ('localhost', 1234),
		}
		for error in (
			RuntimeError('worker failure'),
			ClientDisconnected('without disconnect event'),
		):
			with self.subTest(error=type(error).__name__):
				middleware = Middleware(Application(), 1, 2)
				events = Queue()
				await events.put({'type': 'http.request', 'body': b'', 'more_body': False})
				try:
					with patch.object(middleware, 'application', side_effect=error):
						with self.assertRaisesRegex(type(error), str(error)):
							await wait_for(middleware(scope, events.get, AsyncMock()), 3)
				finally:
					middleware.executor.shutdown(wait=True)
		return


@skipUnless(find_spec('a2wsgi') is not None, 'a2wsgi 필요')
class InputTests(IsolatedAsyncioTestCase):
	async def asyncSetUp(self):
		from RedStar.Adapter.Implements.Uvicorn.HTTP import Input
		from RedStar.Adapter.Implements.Uvicorn.Portal import Portal

		self.events = Queue()
		self.portal = Portal(get_running_loop())
		self.body = Input(
			self.events.get,
			self.portal,
			1,
		)
		self.pump = create_task(self.body.pump())
		return

	async def asyncTearDown(self):
		from asyncio import CancelledError

		self.portal.close()
		if self.pump is not None:
			self.pump.cancel()
			with suppress(CancelledError):
				await self.pump
		return

	async def test_lines_share_the_single_receive_pump(self):
		for data, more in (
			(b'a', True),
			(b'\nb\nc', True),
			(b'', False),
		):
			await self.events.put({
				'type': 'http.request',
				'body': data,
				'more_body': more,
			})
		self.assertEqual(await wait_for(to_thread(self.body.readline, 1), 2), b'a')
		self.assertEqual(await wait_for(to_thread(self.body.readline), 2), b'\n')
		self.assertEqual(await wait_for(to_thread(self.body.readlines), 2), [
			b'b\n',
			b'c',
		])
		self.assertFalse(self.body.has_more)
		return

	async def test_receive_failure_unblocks_reader_and_propagates(self):
		await self.events.put({'type': 'websocket.connect'})
		with self.assertRaisesRegex(RuntimeError, 'HTTP request body'):
			await wait_for(to_thread(self.body.read, 1), 2)
		pump = self.pump
		assert pump is not None
		with self.assertRaisesRegex(RuntimeError, 'HTTP request body'):
			await pump
		self.pump = None
		return

	async def test_disconnect_unblocks_reader(self):
		await self.events.put({'type': 'http.disconnect'})
		with self.assertRaises(ClientDisconnected):
			await wait_for(to_thread(self.body.read, 1), 2)
		return

	async def test_portal_close_unblocks_pending_read(self):
		from asyncio import sleep

		reader = create_task(to_thread(self.body.read, 1))
		while not self.portal.pending:
			await sleep(0)
		self.portal.close()
		with self.assertRaises(ClientDisconnected):
			await wait_for(reader, 2)
		return
