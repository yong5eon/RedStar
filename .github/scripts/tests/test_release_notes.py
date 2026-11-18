from json import dumps
from os import environ
from pathlib import Path
from subprocess import CalledProcessError
from tempfile import TemporaryDirectory
from textwrap import dedent
from typing import Optional
from unittest import TestCase
from unittest.mock import (
	MagicMock,
	patch,
)


class ReleaseNotesTests(TestCase):
	def setUp(self) -> None:
		self.directory: TemporaryDirectory = TemporaryDirectory()
		self.addCleanup(self.directory.cleanup)
		self.notes: Path = Path(self.directory.name) / 'release-notes' / 'README.md'
		workflow: str = (Path(__file__).resolve().parents[3] / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
		step: str = workflow.split('      - name: Collect release notes from change tag\n', 1)[1]
		script: str = step.split("          python - <<'PY'\n", 1)[1].split('\n          PY', 1)[0]
		self.script: str = dedent(script)
		self.check_output: MagicMock = MagicMock()
		return

	def pull(
		self,
		head_sha: str = 'pr-head',
		repository: Optional[str] = 'fork/project',
	) -> dict[str, object]:
		return {
			'merged_at': '2026-01-01T00:00:00Z',
			'merge_commit_sha': 'test-head',
			'base': {'ref': 'master', 'repo': {'full_name': 'example/project'}},
			'head': {
				'ref': 'task/12',
				'sha': head_sha,
				'repo': {'full_name': repository} if repository is not None else None,
			},
		}

	def tag_calls(self, message: str = 'Release notes\n') -> list[object]:
		return [
			dumps({'object': {'type': 'tag', 'sha': 'tag-object'}}).encode(),
			dumps({'message': message}).encode(),
		]

	def run_collector(self, version: str = 'true') -> bytes:
		env: dict[str, str] = {
			'GITHUB_SHA': 'test-head',
			'GITHUB_REPOSITORY': 'example/project',
			'AFTER': 'test-head',
			'NEW_VERSION': version,
			'RELEASE_TAG': 'v1',
			'RUNNER_TEMP': self.directory.name,
		}
		with patch.dict(environ, env), patch('subprocess.check_output', self.check_output):
			exec(self.script, {})
		return self.notes.read_bytes()

	def api_paths(self) -> list[str]:
		return [call.args[0][-1] for call in self.check_output.call_args_list[1:]]

	def test_direct_push_reads_tag_of_last_pushed_commit_in_origin(self) -> None:
		self.check_output.side_effect = [dumps([[]]).encode(), *self.tag_calls()]
		self.assertEqual(self.run_collector(), b'Release notes\n')
		self.assertEqual(
			self.api_paths(),
			[
				'repos/example/project/git/ref/tags/changes/test-head',
				'repos/example/project/git/tags/tag-object',
			],
		)
		return

	def test_merged_pr_reads_tag_of_pr_head_in_head_repository(self) -> None:
		self.check_output.side_effect = [dumps([[self.pull()]]).encode(), *self.tag_calls()]
		self.assertEqual(self.run_collector(), b'Release notes\n')
		self.assertEqual(
			self.api_paths(),
			[
				'repos/fork/project/git/ref/tags/changes/pr-head',
				'repos/fork/project/git/tags/tag-object',
			],
		)
		return

	def test_missing_tag_reports_repository_and_tag_name(self) -> None:
		for pulls, repository, tag in (
			([], 'example/project', 'changes/test-head'),
			([self.pull()], 'fork/project', 'changes/pr-head'),
		):
			with self.subTest(repository=repository):
				self.check_output.reset_mock()
				self.check_output.side_effect = [
					dumps([pulls]).encode(),
					CalledProcessError(1, 'gh'),
				]
				with self.assertRaises(ValueError) as caught:
					self.run_collector()
				self.assertIn(repository, str(caught.exception))
				self.assertIn(tag, str(caught.exception))
		return

	def test_lightweight_tag_and_empty_message_fail(self) -> None:
		for results in (
			[dumps({'object': {'type': 'commit', 'sha': 'test-head'}}).encode()],
			self.tag_calls(' \n'),
		):
			with self.subTest(results=results):
				self.check_output.reset_mock()
				self.check_output.side_effect = [dumps([[]]).encode(), *results]
				with self.assertRaises(ValueError):
					self.run_collector()
		return

	def test_pr_without_head_repository_fails(self) -> None:
		self.check_output.side_effect = [dumps([[self.pull(repository=None)]]).encode()]
		with self.assertRaises(ValueError):
			self.run_collector()
		self.assertEqual(self.check_output.call_count, 1)
		return

	def test_existing_release_notes_are_reused_without_tag(self) -> None:
		self.check_output.side_effect = [
			dumps([[self.pull()]]).encode(),
			dumps({'tag_name': 'v1', 'body': 'existing notes'}).encode(),
		]
		self.assertEqual(self.run_collector('false'), b'existing notes')
		self.assertEqual(self.check_output.call_count, 2)
		return
