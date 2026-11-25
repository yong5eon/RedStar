from logging import (
	Logger as PyLogger,
	LoggerAdapter,
	getLogger as get_py_logger,
)
from typing import (
	Any,
	Optional,
)

__all__ = (
	'Logger',
	'getLogger',
)

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
		return msg, kwargs

	def log(
		self,
		level: int,
		msg: Any,
		*args: Any,
		id: Optional[str] = None,
		**kwargs: Any,
	) -> None:
		if id is not None:
			extra = dict(kwargs.get('extra') or {})
			extra['request_id'] = id
			kwargs['extra'] = extra
		super().log(level, msg, *args, **kwargs)
		return

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
