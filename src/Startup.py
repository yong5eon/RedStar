from os import environ
import sys
from .Application import Application

__all__ = (
	'LOGO',
	'supports_color',
	'colorize_logo',
	'startup',
)


LOGO_ROWS = 5
LOGO_GRADIENT = (
	'\033[38;5;196m',
	'\033[38;5;202m',
	'\033[38;5;208m',
	'\033[38;5;214m',
	'\033[38;5;220m',
	'\033[38;5;226m',
)


# Coder Mini Style
# https://patorjk.com/software/taag/#p=display&f=Coder+Mini&t=RedStar&x=none&v=4&h=4&w=80&we=false
LOGO = r"""
▄▄▄▄▄▄▄            ▄▄  ▄▄▄▄▄▄▄                      ▄
███▀▀███▄          ██ █████▀▀▀  ██                ▀███▀
███▄▄███▀ ▄█▀█▄ ▄████  ▀████▄  ▀██▀▀ ▀▀█▄ ████▄    ▀ ▀
███▀▀██▄  ██▄█▀ ██ ██    ▀████  ██  ▄█▀██ ██ ▀▀
███  ▀███ ▀█▄▄▄ ▀████ ███████▀  ██  ▀█▄██ ██

Just def. Define your code. Compose your chord. You don't need to await this.
"""


def supports_color() -> bool:
	"""Use colors only for terminal output and honor NO_COLOR."""
	return (
		getattr(sys.stdout, 'isatty', lambda: False)()
		and 'NO_COLOR' not in environ
	)


def colorize_logo(logo: str) -> str:
	"""Apply a red-to-yellow gradient from left to right to the five banner lines."""
	art = [
		line for line in logo.splitlines()
		if line.strip()
	][:LOGO_ROWS]
	width = max(len(line) for line in art)
	lines = []
	art_line = 0
	for line in logo.splitlines(keepends=True):
		if line.strip() and art_line < LOGO_ROWS:
			newline = line[len(line.rstrip('\r\n')):]
			text = line[:len(line) - len(newline)]
			colored = []
			current = None
			for column, character in enumerate(text):
				if character == ' ':
					colored.append(character)
					continue
				color = LOGO_GRADIENT[column * len(LOGO_GRADIENT) // width]
				if color != current:
					colored.append(color)
					current = color
				colored.append(character)
			lines.append(''.join(colored) + '\033[0m' + newline)
			art_line += 1
		else:
			lines.append(line)
	return ''.join(lines)


def startup(
	application: Application,
	server: str,
	host: str,
	port: int,
) -> None:
	"""Log the application's registration details, adapter name, and listening address."""
	if not isinstance(host, str):
		raise TypeError('HTTP listen address must be a string')
	address = f'[{host}]' if ':' in host else host
	logo = LOGO.rstrip()
	starting = 'Starting'
	if supports_color():
		logo = colorize_logo(logo)
		starting = f'\033[1;38;5;51m{starting}\033[0m'
	routes = [
		route for route in application.router.routes
		if route not in application.extension_routes
	]
	lines = [
		logo,
		'',
		starting,
		f'  Server: {server}',
		f'  Listen: http://{address}:{port}',
		f'  Applications: {len(routes)} applications',
	]
	for route in routes:
		lines.extend((
			f'    - {route.object.properties.name if route.object.properties.name is not None else route.object.__qualname__}',
			f'      {route.method} {route.url}',
		))
	if application.exts:
		lines.append(f'  Extensions: {len(application.exts)} extensions')
		for extension in application.exts:
			lines.append(
				f'    - {extension}',
			)
	lines.append('\n')
	text = '\n'.join(lines)
	encoding = getattr(sys.stdout, 'encoding', None)
	if encoding is not None:
		# Escape only unprintable characters to preserve the startup details.
		text = text.encode(encoding, errors='backslashreplace').decode(encoding)
	print(
		text,
		flush=True,
	)
	return
