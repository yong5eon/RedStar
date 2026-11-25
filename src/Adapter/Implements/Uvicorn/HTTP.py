from asyncio import (
	CancelledError,
	Queue,
	create_task,
	get_running_loop,
	shield,
)
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from typing import Optional
from a2wsgi.asgi_typing import (
	Receive,
	Scope,
	Send,
)
from a2wsgi.wsgi import (
	Body,
	build_environ,
)

from RedStar import (
	Application,
	getLogger,
)
from RedStar.Adapter.WSGI import WSGIApplication
from RedStar.IO.RequestReader import ClientDisconnected
from .Portal import Portal

__all__ = (
	'Input',
	'Middleware',
)


class Input(Body):
	"""Read ASGI request bodies without waiting for the full upload and monitor disconnects."""

	def __init__(
		self,
		receive: Receive,
		portal: Portal,
		capacity: int,
	):
		super().__init__(
			portal.loop,
			receive,
		)
		self.portal = portal
		self.messages: Queue[bytes] = Queue(maxsize=capacity)
		self.finished = False
		self.disconnected = False
		self.failure: Optional[Exception] = None
		self.disconnect_errors: list[ClientDisconnected] = []
		return

	def disconnect_error(self, message: str) -> ClientDisconnected:
		error = ClientDisconnected(message)
		self.disconnect_errors.append(error)
		return error

	def caused_by_disconnect(self, error: BaseException) -> bool:
		current: Optional[BaseException] = error
		while current is not None:
			if any(current is original for original in self.disconnect_errors):
				return True
			current = current.__cause__
		return False

	async def pump(self) -> None:
		try:
			while True:
				message = await self.receive()
				if message['type'] == 'http.disconnect':
					self.disconnected = True
					await self.messages.put(b'')
					return
				if message['type'] != 'http.request':
					raise RuntimeError('Expected an HTTP request body event')
				if message['body']:
					await self.messages.put(message['body'])
				if not message.get('more_body', False):
					await self.messages.put(b'')
		except Exception as error:
			self.failure = error
			await self.messages.put(b'')
			raise

	async def take(
		self,
		size: int,
	) -> bytes:
		if self.failure is not None:
			raise self.failure
		if self.disconnected:
			raise self.disconnect_error('Client disconnected while receiving request')
		while not self.buffer and not self.finished:
			data = await self.messages.get()
			if not data:
				if self.failure is not None:
					raise self.failure
				if self.disconnected:
					raise self.disconnect_error('Client disconnected while receiving request')
				self.finished = True
			else:
				self.buffer.extend(data)
		if size < 0:
			while not self.finished:
				data = await self.messages.get()
				if not data:
					if self.failure is not None:
						raise self.failure
					if self.disconnected:
						raise self.disconnect_error('Client disconnected while receiving request')
					self.finished = True
				else:
					self.buffer.extend(data)
			size = len(self.buffer)
		data = bytes(self.buffer[:size])
		del self.buffer[:size]
		return data

	def read(
		self,
		size: int = -1,
	) -> bytes:
		if size == 0:
			return b''
		return self.portal.call(self.take(size))

	@property
	def has_more(self) -> bool:
		return bool(self.buffer) or not self.finished

	def readline(
		self,
		limit: int = -1,
	) -> bytes:
		data = bytearray()
		while limit < 0 or len(data) < limit:
			part = self.read(1)
			if not part:
				break
			data.extend(part)
			if part == b'\n':
				break
		return bytes(data)

	def readlines(
		self,
		hint: int = -1,
	) -> list[bytes]:
		lines = []
		total = 0
		while self.has_more:
			line = self.readline()
			if not line:
				break
			lines.append(line)
			total += len(line)
			if hint > 0 and total >= hint:
				break
		return lines


class Middleware:
	"""Use a2wsgi for environment conversion and apply backpressure during byte transmission."""

	def __init__(
		self,
		application: Application,
		workers: int,
		queue_size: int,
	):
		self.application = WSGIApplication(application)
		self.executor = ThreadPoolExecutor(
			max_workers=workers,
			thread_name_prefix='RedStar.Uvicorn',
		)
		self.queue_size = queue_size
		return

	async def __call__(
		self,
		scope: Scope,
		receive: Receive,
		send: Send,
	) -> None:
		if scope['type'] == 'lifespan':
			while True:
				message = await receive()
				if message['type'] == 'lifespan.startup':
					await send({'type': 'lifespan.startup.complete'})
				elif message['type'] == 'lifespan.shutdown':
					await send({'type': 'lifespan.shutdown.complete'})
					return
				else:
					raise RuntimeError('Unexpected lifespan event')
		if scope['type'] != 'http':
			raise RuntimeError('WebSocket connections require the native protocol')
		portal = Portal(get_running_loop())
		body = Input(
			receive,
			portal,
			self.queue_size,
		)
		environ = build_environ(
			scope,
			body,
		)
		pump = create_task(body.pump())

		async def transmit(message) -> None:
			if body.failure is not None:
				raise body.failure
			if body.disconnected:
				raise body.disconnect_error('Client disconnected while sending response')
			await send(message)
			return

		def write(data: bytes) -> None:
			portal.call(transmit({
				'type': 'http.response.body',
				'body': data,
				'more_body': True,
			}))
			return

		def start_response(
			status: str,
			headers: list[tuple[str, str]],
		):
			portal.call(transmit({
				'type': 'http.response.start',
				'status': int(status.split(' ', 1)[0]),
				'headers': [
					(
						key.lower().encode('latin-1'),
						value.encode('latin-1'),
					) for key, value in headers
				],
			}))
			return write

		def run() -> None:
			for data in self.application(
				environ,
				start_response,
			):
				write(data)
			return

		worker = portal.loop.run_in_executor(
			self.executor,
			run,
		)
		try:
			await shield(worker)
			await transmit({
				'type': 'http.response.body',
				'body': b'',
				'more_body': False,
			})
		except ClientDisconnected as error:
			if not body.caused_by_disconnect(error):
				raise
			getLogger('Server.Uvicorn').warning('ASGI request stopped after client disconnect')
		except CancelledError:
			portal.close()
			with suppress(ClientDisconnected):
				await worker
			raise
		finally:
			portal.close()
			pump.cancel()
			with suppress(CancelledError):
				await pump
		return
