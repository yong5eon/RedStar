from typing import (
	Dict,
	Optional,
	Sequence,
	Tuple,
)

from .Route import Route

__all__ = (
	'Router',
)


class RouteNode:
	"""Store literal and parameter edges for one URL prefix."""

	def __init__(self) -> None:
		self.literals: Dict[str, 'RouteNode'] = {}
		self.parameter: Optional['RouteNode'] = None
		self.routes: list[Route] = []
		return


class Router:
	"""Maintain per-Application registrations and prioritize static routes."""

	def __init__(self):
		self.routes: list[Route] = []
		self.static_routes: Dict[str, list[Route]] = {}
		self.parameter_routes = RouteNode()
		self.custom_routes: list[Route] = []
		self.route_order: Dict[int, int] = {}
		return

	def add(
		self,
		route: Route,
	) -> None:
		for registered in self.routes:
			if registered.method == route.method and registered.url == route.url:
				if registered.object is route.object:
					return
				raise ValueError('Route already registered: {} {}'.format(
					route.method,
					route.url,
				))
		self.routes.append(route)
		self.routes.sort(key=lambda entry: entry.priority)
		self.route_order[id(route)] = len(self.route_order)
		self.index_route(route)
		return

	def replace(
		self,
		routes: Sequence[Route],
	) -> None:
		self.routes[:] = routes
		self.routes.sort(key=lambda entry: entry.priority)
		self.static_routes.clear()
		self.parameter_routes = RouteNode()
		self.custom_routes.clear()
		self.route_order.clear()
		for order, route in enumerate(self.routes):
			self.route_order[id(route)] = order
			self.index_route(route)
		return

	def index_route(
		self,
		route: Route,
	) -> None:
		if type(route).match is not Route.match:
			self.custom_routes.append(route)
			return
		if route.parameter_count == 0:
			routes = self.static_routes.get(route.url)
			if routes is None:
				routes = []
				self.static_routes[route.url] = routes
			routes.append(route)
			return
		node = self.parameter_routes
		for segment in route.url.split('/')[1:]:
			if Route.variable.search(segment) is None:
				child = node.literals.get(segment)
				if child is None:
					child = RouteNode()
					node.literals[segment] = child
				node = child
			else:
				if node.parameter is None:
					node.parameter = RouteNode()
				node = node.parameter
		node.routes.append(route)
		return

	def matches(
		self,
		url: str,
	) -> Dict[str, Tuple[Route, dict[str, str]]]:
		matches: Dict[str, Tuple[Route, dict[str, str]]] = {}
		candidates = list(self.static_routes.get(url, ()))
		nodes = [self.parameter_routes]
		for segment in url.split('/')[1:]:
			next_nodes: list[RouteNode] = []
			for node in nodes:
				literal = node.literals.get(segment)
				if literal is not None:
					next_nodes.append(literal)
				if segment and node.parameter is not None:
					next_nodes.append(node.parameter)
			nodes = next_nodes
			if not nodes:
				break
		for node in nodes:
			candidates.extend(node.routes)
		candidates.extend(self.custom_routes)
		candidates.sort(
			key=lambda route: (
				route.priority,
				self.route_order[id(route)],
			),
		)
		for route in candidates:
			if route.method in matches:
				continue
			parameters = (
				{}
				if route.parameter_count == 0 and type(route).match is Route.match
				else route.match(url)
			)
			if parameters is not None:
				matches[route.method] = (
					route,
					parameters,
				)
		return matches
