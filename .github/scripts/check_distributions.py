from argparse import ArgumentParser
from email.parser import BytesParser
from os import environ
from pathlib import Path
from subprocess import run
from sys import executable
from tempfile import TemporaryDirectory
from venv import EnvBuilder
from zipfile import ZipFile

PROJECT = 'RedStar'
DISTRIBUTION = 'py-wsgi-redstar'
MODULES = (
	'Adapter.Implements.Python',
	'Adapter.Implements.Gunicorn',
	'Adapter.Implements.Uvicorn',
)
ROOT = Path(__file__).resolve().parents[2]


def check(
	command: list[str],
	directory: Path,
) -> None:
	result = run(
		command,
		cwd=directory,
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
	# The pip bundled with older Python versions falls back to legacy `setup.py develop`, which ignores package_dir remapping
	EnvBuilder(
		with_pip=True,
		upgrade_deps=True,
	).create(directory)
	return str(directory / ('Scripts/python.exe' if environ.get('OS') == 'Windows_NT' else 'bin/python'))


def main() -> None:
	parser = ArgumentParser(description='Verify the single distribution, its extras and the editable installation.')
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
	wheel, = dist.glob('*.whl')
	with ZipFile(wheel) as archive:
		metadata_path, = (name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))
		metadata = BytesParser().parsebytes(archive.read(metadata_path))
		names = archive.namelist()
	assert metadata['Name'] == DISTRIBUTION, metadata['Name']
	assert sorted(metadata.get_all('Provides-Extra')) == ['gunicorn', 'uvicorn']
	for module in MODULES:
		prefix = PROJECT + '/' + module.replace(
			'.',
			'/',
		) + '/'
		assert any(name.startswith(prefix) for name in names), module
	code = 'from importlib import import_module\n' + ''.join(
		f'import_module({PROJECT + "." + module!r})\n' for module in MODULES
	)
	with TemporaryDirectory() as temporary:
		directory = Path(temporary)
		python = python_in(directory / 'installed')
		check(
			[
				python,
				'-m',
				'pip',
				'install',
				f'{wheel}[Gunicorn,Uvicorn]',
			],
			directory,
		)
		check(
			[
				python,
				'-m',
				'pip',
				'check',
			],
			directory,
		)
		check(
			[
				python,
				'-I',
				'-c',
				code,
			],
			directory,
		)
		if options.editable:
			editable = python_in(directory / 'editable')
			check(
				[
					editable,
					'-m',
					'pip',
					'install',
					'-e',
					f'{ROOT}[Gunicorn,Uvicorn]',
				],
				directory,
			)
			check(
				[
					editable,
					'-m',
					'pip',
					'check',
				],
				directory,
			)
			check(
				[
					editable,
					'-I',
					'-c',
					code,
				],
				directory,
			)
	print(f'{DISTRIBUTION}: single distribution, extras and installation checks passed')
	return


if __name__ == '__main__':
	main()
