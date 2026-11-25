from time import monotonic
from typing import Callable

from ..Application import Application
from ..Error import Error
from ..IO.RequestReader import ClientDisconnected
from ..IO.ResponseWriter import ResponseWriter
from ..Logger import (
	RequestContext,
	current_request,
	getLogger,
	request_context,
)
from ..Request import Request
from ..Response import Response

__all__ = (
	'handle_request',
)

LOGGER = getLogger('Server')


def handle_request(
	application: Application,
	create_request: Callable[[], Request],
	writer: ResponseWriter,
) -> None:
	"""Handle error responses and resource cleanup independently of the transport layer."""
	context = request_context.get()
	if context is not None and context.active and context.request is None and not context.application_started:
		handle_request_in_context(application, create_request, writer)
		return
	with RequestContext(None):
		handle_request_in_context(application, create_request, writer)
	return


def handle_request_in_context(
	application: Application,
	create_request: Callable[[], Request],
	writer: ResponseWriter,
) -> None:
	logger = LOGGER
	started = monotonic()
	request = None
	response = None
	outcome = 'failed'
	try:
		try:
			request = create_request()
			current_request(request)
			response = application(request)
		except ClientDisconnected:
			raise
		except Error as error:
			if writer.started:
				raise
			logger.debug(
				'HTTP error response selected: status=%s',
				error.status,
			)
			response = Response(
				status=error.status,
				headers=error.headers,
				body=error.reason.encode('utf-8'),
				format='text/plain',
				charset='utf-8',
			)
		except Exception:
			if writer.started:
				raise
			logger.exception('Unexpected error while handling request')
			response = Response(
				status=500,
				body=b'Internal Server Error',
			)
		if response is not None:
			writer.response(
				response,
				filtered=True,
			)
		elif not writer.ended:
			raise RuntimeError('Response was neither returned nor completed successfully')
		outcome = 'completed'
	except ConnectionError:
		outcome = 'disconnected'
		logger.warning('Client disconnected')
		raise
	except Exception:
		logger.exception('Response transmission failed: closing connection without another error response')
		raise
	finally:
		duration = monotonic() - started
		logger.info(
			'HTTP transmission result: method=%s status=%s outcome=%s duration=%.6f',
			ascii(request.method[:32]) if request is not None else None,
			writer.status if writer.started else None,
			outcome,
			duration,
		)
		if response is not None:
			try:
				response.close()
			except Exception:
				logger.exception('Response body cleanup failed')
	return
