from re import (
	compile,
	escape,
)
from typing import (
	Optional,
	Type,
)

from .CrossOriginResourceSharing import CrossOriginResourceSharing
from .RequestRunner import RequestRunner
from .Runners.RunRequest import RunRequest

__all__ = (
	'Route',
)


class Route:
	"""Represent a route using the existing :name path parameter syntax."""

	variable = compile(r':([A-Za-z_][A-Za-z_0-9]*)')

	def __init__(
		self,
		method: str,
		url: str,
		obj: Type[RequestRunner],
	):
		self.method = method
		self.url = url
		self.object = obj
		self.run_request: Optional[RunRequest] = None
		self.cross_origin_resource_sharing: Optional[CrossOriginResourceSharing] = None
		parts = []
		position = 0
		for match in self.variable.finditer(url):
			parts.append(escape(url[position:match.start()]))
			parts.append('(?P<{}>[^/]+)'.format(match.group(1)))
			position = match.end()
		parts.append(escape(url[position:]))
		self.pattern = compile(''.join(parts))
		self.parameter_count = self.pattern.groups
		return

	def prepare_request(self) -> None:
		"""Prepare reusable request execution and CORS policy for a registered route."""
		if self.run_request is not None:
			return
		self.run_request = RunRequest(self.object)
		self.cross_origin_resource_sharing = self.run_request.cross_origin_resource_sharing
		return

	@property
	def priority(self) -> tuple[int, int, int]:
		return (
			0,
			self.parameter_count,
			0,
		)

	def match(
		self,
		url: str,
	) -> Optional[dict[str, str]]:
		match = self.pattern.fullmatch(url)
		return match.groupdict() if match is not None else None
