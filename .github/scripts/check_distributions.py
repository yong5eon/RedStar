from argparse import ArgumentParser
from email.parser import BytesParser
from itertools import combinations
from os import environ
from pathlib import Path
from shutil import (
	copy2,
	copytree,
	ignore_patterns,
)
from subprocess import run
from sys import (
	executable,
	path as sys_path,
)
from tarfile import open as open_tar
from tempfile import TemporaryDirectory
from venv import EnvBuilder
from zipfile import ZipFile

sys_path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

from build import (
	IMPLEMENTATIONS,
	PROJECT,
	ROOT,
)


def check(
	command: list[str],
	directory: Path,
	environment: dict[str, str],
) -> None:
	result = run(
		command,
		cwd=directory,
		env=environment,
		capture_output=True,
		text=True,
	)
	if result.returncode:
		raise RuntimeError(
			'Command failed: {}\n{}\n{}'.format(
				command,
				result.stdout,
				result.stderr,
			)
		)
	return


def python_in(directory: Path) -> str:
	EnvBuilder(with_pip=True).create(directory)
	python = str(directory / ('Scripts/python.exe' if environ.get('OS') == 'Windows_NT' else 'bin/python'))
	check(
		[
			executable,
			'-m',
			'pip',
			'--python',
			python,
			'install',
			'pip>=23',
		],
		directory,
		dict(environ),
	)
	return python


def verify_install(
	python: str,
	directory: Path,
	environment: dict[str, str],
	selected: tuple[str, ...],
	editable: bool = False,
) -> None:
	# An editable core contains every implementation source; extras only add the external libraries.
	code = (
		'from importlib import import_module\n'
		'from importlib.util import find_spec\n'
		'from importlib.metadata import distribution, PackageNotFoundError\n'
		f'import_module({PROJECT!r})\n'
		f'for target, path in {IMPLEMENTATIONS!r}.items():\n'
		f'    selected = target in {selected!r}\n'
		f'    module = {PROJECT!r} + "." + path\n'
		f'    assert (find_spec(module) is not None) == ({editable!r} or selected), module\n'
		'    if selected:\n'
		'        import_module(module)\n'
		f'    if {editable!r}:\n'
		'        assert (find_spec(target.lower()) is not None) == selected, target\n'
		'    try:\n'
		f'        installed = distribution({PROJECT!r} + "-" + target)\n'
		'    except PackageNotFoundError:\n'
		f'        assert {editable!r} or not selected, target\n'
		'    else:\n'
		f'        assert not {editable!r} and selected, target\n'
	)
	check(
		[
			python,
			'-I',
			'-c',
			code,
		],
		directory,
		environment,
	)
	check(
		[
			python,
			'-m',
			'pip',
			'check',
		],
		directory,
		environment,
	)
	return


def local_requirements(
	wheels: dict[str, Path],
	selected: tuple[str, ...],
) -> list[str]:
	extras: str = '[' + ','.join(selected) + ']' if selected else ''
	return [
		f'{PROJECT}{extras} @ {wheels[PROJECT.lower()].resolve().as_uri()}',
		*(str(wheels[f'{PROJECT}-{target}'.lower()].resolve()) for target in selected),
	]


def main() -> None:
	parser = ArgumentParser(description='Verify distribution ownership, rebuilds and installation isolation.')
	parser.add_argument(
		'--dist-dir',
		default='dist',
	)
	parser.add_argument(
		'--editable',
		action='store_true',
	)
	options = parser.parse_args()
	dist = Path(options.dist_dir).resolve()
	environment: dict[str, str] = dict(environ)
	environment.pop(
		'DEF_BUILD_TARGET',
		None,
	)
	environment.pop(
		'SETUPTOOLS_SCM_PRETEND_VERSION',
		None,
	)
	wheels = sorted(dist.glob('*.whl'))
	expected = {
		PROJECT.lower(),
		*(f'{PROJECT}-{target}'.lower() for target in IMPLEMENTATIONS),
	}
	contents: dict[str, dict[str, bytes]] = {}
	local_wheels: dict[str, Path] = {}
	version = ''
	owned: set[str] = set()
	for wheel in wheels:
		with ZipFile(wheel) as archive:
			metadata_path, = (
				name for name in archive.namelist()
				if name.endswith('.dist-info/METADATA')
			)
			metadata = BytesParser().parsebytes(archive.read(metadata_path))
			name = metadata['Name'].lower()
			assert name in expected and name not in contents, name
			if version:
				assert metadata['Version'] == version
			version = metadata['Version']
			payload = {
				path: archive.read(path)
				for path in archive.namelist()
				if path.startswith(PROJECT + '/')
			}
			assert payload, name
			assert not (owned & payload.keys()), name
			owned.update(payload)
			contents[name] = payload
			local_wheels[name] = wheel
			for target, path in IMPLEMENTATIONS.items():
				prefix = PROJECT + '/' + path.replace(
					'.',
					'/',
				) + '/'
				present = any(item.startswith(prefix) for item in payload)
				assert present == (name == f'{PROJECT}-{target}'.lower()), (
					name,
					target,
				)
	assert set(contents) == expected

	with TemporaryDirectory() as temporary:
		directory = Path(temporary)
		sources = sorted(dist.glob('*.tar.gz'))
		assert len(sources) in (
			0,
			len(expected),
		)
		for index, source in enumerate(sources):
			with open_tar(source) as archive:
				root = archive.getnames()[0].split('/')[0]
				for filename in (
					'scripts/build.py',
				):
					assert archive.getmember(root + '/' + filename).isfile(), filename
			rebuilt = directory / f'rebuilt-{index}'
			check(
				[
					executable,
					'-m',
					'pip',
					'wheel',
					str(source),
					'--no-deps',
					'--no-build-isolation',
					'--no-cache-dir',
					'--wheel-dir',
					str(rebuilt),
				],
				directory,
				environment,
			)
			wheel, = rebuilt.glob('*.whl')
			with ZipFile(wheel) as archive:
				metadata_path, = (name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))
				metadata = BytesParser().parsebytes(archive.read(metadata_path))
				assert metadata['Version'] == version
				payload = {
					path: archive.read(path)
					for path in archive.namelist()
					if path.startswith(PROJECT + '/')
				}
				assert payload == contents[metadata['Name'].lower()]
		targets = tuple(IMPLEMENTATIONS)
		for count in range(len(targets) + 1):
			for selected in combinations(
				targets,
				count,
			):
				python = python_in(directory / ('installed-' + '-'.join(selected)))
				check(
					[
						python,
						'-m',
						'pip',
						'install',
						*local_requirements(
							local_wheels,
							selected,
						),
					],
					directory,
					environment,
				)
				verify_install(
					python,
					directory,
					environment,
					selected,
				)
				if not selected:
					for target in targets:
						check(
							[
								python,
								'-m',
								'pip',
								'install',
								*local_requirements(
									local_wheels,
									(target,),
								),
							],
							directory,
							environment,
						)
					verify_install(
						python,
						directory,
						environment,
						targets,
					)
					check(
						[
							python,
							'-m',
							'pip',
							'install',
							'--force-reinstall',
							'--no-deps',
							*(str(wheel) for wheel in wheels),
						],
						directory,
						environment,
					)
					verify_install(
						python,
						directory,
						environment,
						targets,
					)
					check(
						[
							python,
							'-m',
							'pip',
							'uninstall',
							'-y',
							f'{PROJECT}-{targets[0]}',
						],
						directory,
						environment,
					)
					verify_install(
						python,
						directory,
						environment,
						targets[1:],
					)
		if options.editable:
			source = directory / 'source'
			source.mkdir()
			for filename in (
				'setup.py',
				'README.setup.md',
				'LICENSE',
			):
				copy2(
					ROOT / filename,
					source / filename,
				)
			(source / 'scripts').mkdir()
			copy2(
				ROOT / 'scripts' / 'build.py',
				source / 'scripts' / 'build.py',
			)
			copytree(
				ROOT / 'src',
				source / 'src',
				ignore=ignore_patterns('__pycache__'),
			)
			probe = source / 'src' / '_editable_probe.py'
			probe.write_text(
				'VALUE = 1\n',
				encoding='utf-8',
			)
			python = python_in(directory / 'editable')
			environment['SETUPTOOLS_SCM_PRETEND_VERSION'] = version
			for selected in (
				(),
				targets[:1],
				targets,
			):
				extras = '[' + ','.join(selected) + ']' if selected else ''
				check(
					[
						python,
						'-m',
						'pip',
						'install',
						'-e',
						str(source) + extras,
					],
					directory,
					environment,
				)
				verify_install(
					python,
					directory,
					environment,
					selected,
					editable=True,
				)
			probe.write_text(
				'VALUE = 200\n',
				encoding='utf-8',
			)
			check(
				[
					python,
					'-I',
					'-c',
					f'from {PROJECT}._editable_probe import VALUE; assert VALUE == 200',
				],
				directory,
				environment,
			)
			other = python_in(directory / 'other-editable')
			check(
				[
					other,
					'-m',
					'pip',
					'install',
					'-e',
					str(source),
				],
				directory,
				environment,
			)
			verify_install(
				other,
				directory,
				environment,
				(),
				editable=True,
			)
			check(
				[
					other,
					'-m',
					'pip',
					'install',
					'-e',
					str(source) + '[' + targets[0] + ']',
				],
				directory,
				environment,
			)
			verify_install(
				other,
				directory,
				environment,
				targets[:1],
				editable=True,
			)
	print(f'{PROJECT}: ownership, sdist rebuilds and editable extras checks passed')
	return


if __name__ == '__main__':
	main()
