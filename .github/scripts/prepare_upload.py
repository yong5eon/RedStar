from email.parser import BytesParser
from hashlib import sha256
from json import load
from os import environ
from pathlib import Path
from shutil import copy2
from tarfile import open as open_tar
from urllib.error import HTTPError
from urllib.request import urlopen
from zipfile import ZipFile

PROJECT = 'DefChord'


def main() -> None:
	version = environ['RELEASE_VERSION']
	new_version = environ['NEW_VERSION'] == 'true'
	paths: list[Path] = []
	wheels = list(Path('dist').glob('*.whl'))
	if len(wheels) != 1:
		raise ValueError('Expected exactly one wheel')
	wheel, = wheels
	if wheel.name.split('-')[2] != environ['WHEEL_BUILD']:
		raise ValueError('Wheel build tag does not match the release plan')
	with ZipFile(wheel) as archive:
		metadata_path, = (
			name for name in archive.namelist()
			if name.endswith('.dist-info/METADATA')
		)
		metadata = BytesParser().parsebytes(archive.read(metadata_path))
	if metadata['Name'] != PROJECT or metadata['Version'] != version:
		raise ValueError('Unexpected wheel name or version: {}'.format(wheel.name))
	paths.append(wheel)
	sources = list(Path('dist').glob('*.tar.gz'))
	if len(sources) != (1 if new_version else 0):
		raise ValueError('Unexpected source distribution count for the release plan')
	for source in sources:
		with open_tar(
			source,
			'r:gz',
		) as archive:
			metadata_file, = (
				member for member in archive.getmembers()
				if member.name.count('/') == 1 and member.name.endswith('/PKG-INFO')
			)
			stream = archive.extractfile(metadata_file)
			if stream is None:
				raise ValueError('Missing source metadata: {}'.format(source.name))
			with stream:
				metadata = BytesParser().parse(stream)
		if metadata['Name'] != PROJECT or metadata['Version'] != version:
			raise ValueError('Unexpected source name or version: {}'.format(source.name))
		paths.append(source)
	upload = Path('upload')
	upload.mkdir(parents=True)
	try:
		with urlopen(
			f'https://pypi.org/pypi/{PROJECT}/{version}/json',
			timeout=30,
		) as response:
			release = load(response)
	except HTTPError as error:
		if error.code != 404:
			raise
		published = {}
	else:
		published = {file['filename']: file['digests']['sha256'] for file in release['urls']}
	if not new_version and not published:
		raise RuntimeError('Cannot rebuild an unpublished distribution: {}'.format(PROJECT))
	for path in paths:
		if path.name in published:
			if sha256(path.read_bytes()).hexdigest() != published[path.name]:
				raise RuntimeError('Published file differs: {}'.format(path.name))
			print('Already published: {}'.format(path.name))
		else:
			copy2(
				path,
				upload / path.name,
			)
	with Path(environ['GITHUB_OUTPUT']).open(
		'a',
		encoding='utf-8',
	) as output:
		output.write('publish={}\nversion={}\n'.format(
			str(any(upload.iterdir())).lower(),
			version,
		))
	return


if __name__ == '__main__':
	main()
