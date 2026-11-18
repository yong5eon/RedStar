# -*- coding: utf-8 -*-

from os import environ
from pathlib import Path
from typing import Optional

from setuptools import (
	Distribution,
	find_packages,
	setup,
)
from setuptools.command.build import build
from setuptools.command.egg_info import egg_info
from setuptools.command.sdist import sdist

PACKAGE = 'DefChord'
SOURCE = 'src'
IMPLEMENTATIONS = {
	'Gunicorn': 'Adapter.Implements.Gunicorn',
	'Uvicorn': 'Adapter.Implements.Uvicorn',
}
DEPENDENCIES = {
	'Gunicorn': ['gunicorn>=23'],
	'Uvicorn': [
		'uvicorn>=0.30',
		'a2wsgi>=1.10',
	],
}
TARGET_FILE = Path('.distribution-target')
ARCHIVE_TARGET: Optional[str] = (
	TARGET_FILE.read_text(encoding='utf-8').strip()
	if TARGET_FILE.is_file() else None
)
TARGET: str = environ.get(
	'DEF_BUILD_TARGET',
	ARCHIVE_TARGET or 'core',
)
if TARGET not in (
	'core',
	*IMPLEMENTATIONS,
):
	raise ValueError('Unknown DEF_BUILD_TARGET: {!r}'.format(TARGET))
if ARCHIVE_TARGET is not None and TARGET != ARCHIVE_TARGET:
	raise ValueError('Cannot change the build target of a source distribution')
# Release builds always set the target explicitly; a bare checkout build (pip install -e .) is a development build.
EDITABLE: bool = 'DEF_BUILD_TARGET' not in environ and ARCHIVE_TARGET is None

NAME = PACKAGE if TARGET == 'core' else '{}-{}'.format(
	PACKAGE,
	TARGET,
)
PACKAGES = [PACKAGE] if TARGET == 'core' else []
PACKAGE_DIR = {PACKAGE: SOURCE} if TARGET == 'core' else {}

for package in find_packages(SOURCE):
	selected = (
		EDITABLE or not any(
			package == path or package.startswith(path + '.')
			for path in IMPLEMENTATIONS.values()
		)
		if TARGET == 'core' else (
			package == IMPLEMENTATIONS[TARGET]
			or package.startswith(IMPLEMENTATIONS[TARGET] + '.')
		)
	)
	if not selected:
		continue
	qualified = '{}.{}'.format(
		PACKAGE,
		package,
	)
	PACKAGES.append(qualified)
	PACKAGE_DIR[qualified] = '{}/{}'.format(
		SOURCE,
		package.replace(
			'.',
			'/',
		),
	)


class TargetBuild(build):
	def initialize_options(self) -> None:
		super().initialize_options()
		self.build_base = 'build/{}'.format(TARGET)
		return


class TargetEggInfo(egg_info):
	def find_sources(self) -> None:
		super().find_sources()
		self.filelist.extend([
			'.github/scripts/build_distributions.py',
		])
		self.filelist.sort()
		self.filelist.remove_duplicates()
		self.write_file(
			'manifest file',
			str(Path(self.egg_info) / 'SOURCES.txt'),
			'\n'.join(self.filelist.files) + '\n',
		)
		return

	def finalize_options(self) -> None:
		if self.egg_base is None:
			self.egg_base = 'build/{}'.format(TARGET)
		Path(self.egg_base).mkdir(
			parents=True,
			exist_ok=True,
		)
		super().finalize_options()
		return


class TargetSdist(sdist):
	def make_release_tree(
		self,
		base_dir: str,
		files: list[str],
	) -> None:
		super().make_release_tree(
			base_dir,
			files,
		)
		(Path(base_dir) / TARGET_FILE).write_text(
			TARGET + '\n',
			encoding='utf-8',
		)
		return


class TargetDistribution(Distribution):
	def finalize_options(self) -> None:
		super().finalize_options()
		from setuptools_scm import get_version

		version: str = get_version(
			dist_name=PACKAGE,
			git_describe_command=[
				'git',
				'describe',
				'--dirty',
				'--tags',
				'--long',
				'--match',
				'[0-9]*.[0-9]*',
				'--match',
				'v[0-9]*.[0-9]*',
			],
			tag_regex=r'^v?(?P<version>[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:(?:rc|\.post)[0-9]+)?)$',
		)
		self.metadata.version = version
		self.install_requires = [] if TARGET == 'core' else [
			'{}=={}'.format(
				PACKAGE,
				version,
			),
			*DEPENDENCIES[TARGET],
		]
		self.extras_require = {
			target: (
				DEPENDENCIES[target] if EDITABLE else ['{}-{}=={}'.format(
					PACKAGE,
					target,
					version,
				)]
			)
			for target in IMPLEMENTATIONS
		} if TARGET == 'core' else {}
		return


setup(
	name=NAME,
	setup_requires=[
		'setuptools>=77',
		'setuptools-scm>=8,<10',
		'wheel',
	],
	distclass=TargetDistribution,
	description='The Modern Synchronous Python Web Application Framework',
	long_description=Path('README.setup.md').read_text(encoding='utf-8'),
	long_description_content_type='text/markdown',
	author='Heo Yongseon',
	url='https://github.com/yong5eon/DefChord',
	project_urls={
		'Source': 'https://github.com/yong5eon/DefChord',
		'Issues': 'https://github.com/yong5eon/DefChord/issues',
		'Releases': 'https://github.com/yong5eon/DefChord/releases',
	},
	cmdclass={
		'build': TargetBuild,
		'egg_info': TargetEggInfo,
		'sdist': TargetSdist,
	},
	packages=PACKAGES,
	package_dir=PACKAGE_DIR,
	include_package_data=False,
	package_data={
		'DefChord.Extensions': [
			'Status.html',
			'Swagger.html',
		],
	} if TARGET == 'core' else {},
	classifiers=[
		'Programming Language :: Python :: 3.9',
		'Programming Language :: Python :: 3.10',
		'Programming Language :: Python :: 3.11',
		'Programming Language :: Python :: 3.12',
		'Programming Language :: Python :: 3.13',
		'Programming Language :: Python :: 3.14',
	],
	python_requires='>=3.9',
)
