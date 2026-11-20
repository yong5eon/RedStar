# -*- coding: utf-8 -*-

from pathlib import Path

from setuptools import (
	find_packages,
	setup,
)

PACKAGE = 'RedStar'
DISTRIBUTION = 'py-wsgi-redstar'
SOURCE = 'src'
DEPENDENCIES = {
	'Gunicorn': ['gunicorn>=23'],
	'Uvicorn': [
		'uvicorn>=0.30',
		'a2wsgi>=1.10',
	],
}

SCM_VERSION = {
	'git_describe_command': [
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
	'tag_regex': r'^v?(?P<version>[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:(?:rc|\.post)[0-9]+)?)$',
}
PACKAGES = [PACKAGE]
PACKAGE_DIR = {PACKAGE: SOURCE}
for package in find_packages(SOURCE):
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

setup(
	name=DISTRIBUTION,
	use_scm_version=SCM_VERSION,
	setup_requires=[
		'setuptools>=77',
		'setuptools-scm>=8,<10',
	],
	description='The Modern Synchronous Python Web Application Framework',
	long_description=Path('README.setup.md').read_text(encoding='utf-8'),
	long_description_content_type='text/markdown',
	author='Heo Yongseon',
	url='https://github.com/yong5eon/RedStar',
	project_urls={
		'Source': 'https://github.com/yong5eon/RedStar',
		'Issues': 'https://github.com/yong5eon/RedStar/issues',
		'Releases': 'https://github.com/yong5eon/RedStar/releases',
	},
	packages=PACKAGES,
	package_dir=PACKAGE_DIR,
	include_package_data=False,
	package_data={
		'RedStar.Extensions': [
			'Status.html',
			'Swagger.html',
		],
	},
	classifiers=[
		'Programming Language :: Python :: 3.9',
		'Programming Language :: Python :: 3.10',
		'Programming Language :: Python :: 3.11',
		'Programming Language :: Python :: 3.12',
		'Programming Language :: Python :: 3.13',
		'Programming Language :: Python :: 3.14',
	],
	extras_require=DEPENDENCIES,
	python_requires='>=3.9',
)
