from json import dumps
from unittest import TestCase
from unittest.mock import patch

from plan_release import (
	classify,
	plan,
	read_names,
)


class PlanReleaseTests(TestCase):
	def test_issue_type_selects_bump_case_insensitively(self) -> None:
		for names, bump in (
			(['Feature'], 'minor'),
			(['FEATURE'], 'minor'),
			(['BUG'], 'patch'),
			(['Fix'], 'patch'),
			(['feature', 'bug', 'fix'], 'minor'),
			(['task', 'documentation'], 'none'),
			([], 'none'),
		):
			with self.subTest(names=names):
				self.assertEqual(classify(names), bump)
		return

	def test_minor_bump_resets_patch_and_later_patch_follows_new_series(self) -> None:
		tags = ['v0.1.28', '0.1.29']
		self.assertEqual(plan('0.1', tags, 'minor'), ('0.2.0', True, '0.2.0'))
		self.assertEqual(plan('0.1', tags + ['0.2.0'], 'patch'), ('0.2.1', True, '0.2.1'))
		return

	def test_none_keeps_latest_version_and_tag(self) -> None:
		self.assertEqual(plan('0.1', ['v0.1.28', 'v0.1.29'], 'none'), ('0.1.29', False, 'v0.1.29'))
		return

	def test_first_release_and_legacy_tag_start_new_version(self) -> None:
		self.assertEqual(plan('0.1', [], 'none'), ('0.1.0', True, '0.1.0'))
		self.assertEqual(plan('0.1', ['0.1.3.2'], 'none'), ('0.1.4', True, '0.1.4'))
		return

	def test_tags_below_series_or_other_major_are_ignored(self) -> None:
		self.assertEqual(plan('0.2', ['0.1.9', '1.5.0'], 'none'), ('0.2.0', True, '0.2.0'))
		return

	def test_commit_without_merged_pr_has_no_issue_names(self) -> None:
		with patch('plan_release.check_output', return_value=dumps([[]]).encode()):
			self.assertEqual(read_names('example/project', 'sha'), [])
		return

	def test_merged_pr_ignores_labels_when_classifying_issues(self) -> None:
		pull = {
			'number': 7,
			'merged_at': '2026-01-01T00:00:00Z',
			'merge_commit_sha': 'sha',
			'base': {'ref': 'master', 'repo': {'full_name': 'example/project'}},
		}
		for nodes, expected_names, bump in (
			([
				{'issueType': {'name': 'Task'}, 'labels': {'nodes': [{'name': 'feature'}]}},
				{'issueType': None, 'labels': {'nodes': [{'name': 'bug'}, {'name': 'fix'}]}},
			], ['Task'], 'none'),
			([
				{'issueType': {'name': 'Bug'}, 'labels': {'nodes': [{'name': 'feature'}]}},
				{'issueType': {'name': 'FEATURE'}, 'labels': {'nodes': [{'name': 'fix'}]}},
			], ['Bug', 'FEATURE'], 'minor'),
			([
				{'issueType': {'name': 'fIx'}},
				{'issueType': None},
			], ['fIx'], 'patch'),
		):
			graphql = {'data': {'repository': {'pullRequest': {'closingIssuesReferences': {'nodes': nodes}}}}}
			with self.subTest(nodes=nodes), patch('plan_release.check_output', side_effect=[
				dumps([[pull]]).encode(),
				dumps(graphql).encode(),
			]):
				names: list[str] = read_names('example/project', 'sha')
				self.assertEqual(names, expected_names)
				self.assertEqual(classify(names), bump)
		return
