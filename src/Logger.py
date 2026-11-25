from contextvars import (
	ContextVar,
	Token,
)
from logging import (
	Logger as PyLogger,
	LoggerAdapter,
	getLogger as get_py_logger,
)
from typing import (
	Any,
	Optional,
	TYPE_CHECKING,
)

if TYPE_CHECKING:
	from .Request import Request


class RequestContext:
	def __init__(
		self,
		request: Optional['Request'],
	):
		self.request = request
		self.application_started = False
		self.active = False
		self.token: Optional[Token] = None
		return

	def __enter__(self) -> 'RequestContext':
		self.active = True
		self.token = request_context.set(self)
		return self

	def __exit__(
		self,
		exc_type: Any,
		exc_value: Any,
		traceback: Any,
	) -> None:
		if self.token is not None:
			self.active = False
			request_context.reset(self.token)
		return


request_context: ContextVar[Optional[RequestContext]] = ContextVar('redstar_request_context', default=None)


def current_request(request: 'Request') -> None:
	context = request_context.get()
	if context is not None and context.active:
		context.request = request
	return


class Logger(LoggerAdapter):
	def __init__(
		self,
		logger: PyLogger,
	):
		super().__init__(logger, {})
		return

	def process(
		self,
		msg: Any,
		kwargs: dict[str, Any],
	) -> tuple[Any, dict[str, Any]]:
		extra = dict(kwargs.get('extra') or {})
		context = request_context.get()
		extra.setdefault(
			'request_id',
			context.request.id if context is not None and context.active and context.request is not None else None,
		)
		kwargs['extra'] = extra
		return msg, kwargs

	def __getattr__(
		self,
		name: str,
	) -> Any:
		return getattr(self.logger, name)

	@property
	def propagate(self) -> bool:
		return self.logger.propagate

	@propagate.setter
	def propagate(
		self,
		value: bool,
	) -> None:
		self.logger.propagate = value
		return


def getLogger(name: str) -> Logger:
	return Logger(get_py_logger(name))
