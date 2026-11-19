from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
from json import dumps
from os import (
	chdir as change_directory,
	environ,
	getcwd,
)
from pathlib import Path
from tarfile import (
	TarInfo,
	open as open_tar,
)
from tempfile import TemporaryDirectory
from typing import Iterator
from unittest import (
	TestCase,
	main,
)
from unittest.mock import patch
from urllib.error import HTTPError
from zipfile import ZipFile

from prepare_upload import main as prepare


@contextmanager
def chdir(directory: str) -> Iterator[None]:
	original: str = getcwd()
	change_directory(directory)
	try:
		yield
	finally:
		change_directory(original)
	return


def missing() -> HTTPError:
	return HTTPError(
		'https://pypi.org',
		404,
		'missing',
		None,
		None,
	)


class ReleaseTests(TestCase):
	def environment(self, build: str = '7', new_version: str = 'true') -> dict[str, str]:
		return {
			'RELEASE_VERSION': '1.2.3',
			'WHEEL_BUILD': build,
			'NEW_VERSION': new_version,
			'GITHUB_OUTPUT': 'output.txt',
		}

	def create_distributions(self) -> None:
		Path('dist').mkdir()
		metadata = b'Metadata-Version: 2.4\nName: RedStar\nVersion: 1.2.3\n\n'
		with ZipFile(
			'dist/redstar-1.2.3-7-py3-none-any.whl',
			'w',
		) as archive:
			archive.writestr(
				'redstar-1.2.3.dist-info/METADATA',
				metadata,
			)
		with open_tar(
			'dist/redstar-1.2.3.tar.gz',
			'w:gz',
		) as archive:
			info = TarInfo('redstar-1.2.3/PKG-INFO')
			info.size = len(metadata)
			archive.addfile(
				info,
				BytesIO(metadata),
			)
		return

	def test_new_release_stages_one_wheel_and_one_source(self) -> None:
		with TemporaryDirectory() as temporary, chdir(temporary), patch.dict(
			environ,
			self.environment(),
		):
			self.create_distributions()
			with patch(
				'prepare_upload.urlopen',
				side_effect=missing(),
			):
				prepare()
			self.assertEqual(
				len(list(Path('upload').iterdir())),
				2,
			)
			self.assertIn(
				'publish=true',
				Path('output.txt').read_text(encoding='utf-8'),
			)
		return

	def test_same_version_rebuild_uploads_wheel_when_unpublished(self) -> None:
		with TemporaryDirectory() as temporary, chdir(temporary), patch.dict(
			environ,
			self.environment(new_version='false'),
		):
			self.create_distributions()
			Path('dist/redstar-1.2.3.tar.gz').unlink()
			with patch(
				'prepare_upload.urlopen',
				side_effect=missing(),
			):
				prepare()
			self.assertEqual(
				[path.name for path in Path('upload').iterdir()],
				['redstar-1.2.3-7-py3-none-any.whl'],
			)
			self.assertIn(
				'publish=true',
				Path('output.txt').read_text(encoding='utf-8'),
			)
		return

	def test_invalid_build_number_is_rejected(self) -> None:
		with TemporaryDirectory() as temporary, chdir(temporary), patch.dict(
			environ,
			self.environment(build='8'),
		):
			self.create_distributions()
			with self.assertRaisesRegex(
				ValueError,
				'build tag',
			):
				prepare()
		return

	def test_missing_wheel_is_rejected(self) -> None:
		with TemporaryDirectory() as temporary, chdir(temporary), patch.dict(
			environ,
			self.environment(),
		):
			self.create_distributions()
			next(Path('dist').glob('*.whl')).unlink()
			with self.assertRaisesRegex(
				ValueError,
				'exactly one wheel',
			):
				prepare()
		return

	def test_published_identical_artifacts_are_not_uploaded_again(self) -> None:
		with TemporaryDirectory() as temporary, chdir(temporary), patch.dict(
			environ,
			self.environment(),
		):
			self.create_distributions()
			release = {
				'urls': [
					{
						'filename': path.name,
						'digests': {'sha256': sha256(path.read_bytes()).hexdigest()},
					}
					for path in Path('dist').iterdir()
				],
			}
			with patch(
				'prepare_upload.urlopen',
				return_value=BytesIO(dumps(release).encode()),
			):
				prepare()
			self.assertIn(
				'publish=false',
				Path('output.txt').read_text(encoding='utf-8'),
			)
		return

	def test_published_different_artifacts_are_rejected(self) -> None:
		with TemporaryDirectory() as temporary, chdir(temporary), patch.dict(
			environ,
			self.environment(),
		):
			self.create_distributions()
			release = {
				'urls': [
					{'filename': path.name, 'digests': {'sha256': 'wrong'}}
					for path in Path('dist').iterdir()
				],
			}
			with patch(
				'prepare_upload.urlopen',
				return_value=BytesIO(dumps(release).encode()),
			), self.assertRaisesRegex(
				RuntimeError,
				'Published file differs',
			):
				prepare()
		return


if __name__ == '__main__':
	main()
