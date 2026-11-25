from typing import (
	Optional,
	Type,
)

from ..RequestRunner import (
	RequestProperties,
	RequestRunner,
)
from ..Request import Request
from ..Logger import (
	RequestContext,
	current_request,
	getLogger,
)
from ..Response import (
	Response,
	close_bodies,
)
from ..CrossOriginResourceSharing import CrossOriginResourceSharing

__all__ = (
	'RunRequest',
)


class RunRequest:
	"""Manage validation, handler execution, response processing, and error observation."""

	logger = getLogger('Request')

	def __init__(
		self,
		obj: Type[RequestRunner],
	):
		self.object: Type[RequestRunner] = obj
		self.properties: RequestProperties = obj.properties
		self.cross_origin_resource_sharing: CrossOriginResourceSharing = CrossOriginResourceSharing(
			self.properties,
		)
		return

	def apply_response_hooks(
		self,
		request: Request,
		response: Response,
	) -> Response:
		"""Apply configured response hooks and CORS policy to a response."""
		for hook in self.properties.on_request_response:
			previous = response
			previous_body = previous.body
			try:
				result = hook(request, previous)
				if not isinstance(result, Response):
					raise TypeError('RequestRunnerRequestResponse hooks must return a Response')
			except Exception:
				close_bodies(
					previous_body,
					previous.body,
					preserve_error=True,
				)
				raise
			response = result
			try:
				close_bodies(*(
					body for body in (
						previous_body,
						previous.body,
					)
					if body is not response.body
				))
			except Exception:
				close_bodies(
					response.body,
					preserve_error=True,
				)
				raise
		try:
			response = self.cross_origin_resource_sharing.apply_to_response(
				request,
				response,
			)
			return response
		except Exception:
			close_bodies(
				response.body,
				preserve_error=True,
			)
			raise

	def run(
		self,
		request: Request,
	) -> Optional[Response]:
		with RequestContext(request):
			return self.run_in_context(request)

	def run_in_context(
		self,
		request: Request,
	) -> Optional[Response]:
		properties = self.properties
		writer = None
		try:
			self.cross_origin_resource_sharing.validate_origin(request)
			for check in (
				properties.auth,
				properties.parameters,
				properties.qs,
				properties.headers,
			):
				if check is not None:
					check(request)
			if properties.body is not None:
				request.body = properties.body(request)
			runner = self.object()
			for hook in properties.on_request:
				previous_request = request
				previous_id = request.id
				result = hook(request)
				if not isinstance(result, Request):
					raise TypeError('RequestRunnerRequest hooks must return a Request')
				replaced = result is not previous_request
				if replaced:
					result.id = previous_id
				current_request(result)
				if replaced or previous_id != result.id:
					self.logger.debug('Request replaced: previous_request_id=%s', previous_id)
				request = result
			writer = request.response_writer
			if writer is not None:
				writer.on_request_response = None
				writer.on_request_response_with_request = self.apply_response_hooks
				writer.response_hook_request = request
			response = runner.run(request)
			if writer is not None and writer.started:
				if response is not None:
					if isinstance(response, Response):
						close_bodies(
							response.body,
							preserve_error=True,
						)
					raise RuntimeError('Cannot return a Response after starting direct output')
				writer.end()
				return None
			if not isinstance(response, Response):
				raise TypeError('run must return a Response or start a response through the writer')
			response = self.apply_response_hooks(request, response)
			return response
		except Exception as error:
			for hook in properties.on_request_error:
				response = hook(request, error)
				if response is not None and not isinstance(response, Response):
					raise TypeError('RequestRunnerRequestError hooks must return a Response or None')
				if response is not None:
					active_writer = request.response_writer
					if active_writer is not None and active_writer.started:
						close_bodies(
							response.body,
							preserve_error=True,
						)
						raise RuntimeError('Cannot return a Response after starting direct output')
					return response
			raise
		finally:
			if writer is not None:
				writer.on_request_response = None
				writer.on_request_response_with_request = None
				writer.response_hook_request = None
