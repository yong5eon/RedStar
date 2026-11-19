from json import dumps
from unittest import TestCase
from unittest.mock import patch

from plan_release import (
	classify,
	plan,
	read_names,
)


class PlanReleaseTests(TestCase):
	def test_feature_or_bug_in_type_or_label_selects_bump(self) -> None:
		for names, bump in (
			(['Task', 'feature'], 'minor'),
			(['Feature'], 'minor'),
			(['bug'], 'patch'),
			(['Task', 'fix'], 'patch'),
			(['feature', 'bug'], 'minor'),
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

	def test_merged_pr_collects_issue_types_and_labels(self) -> None:
		pull = {
			'number': 7,
			'merged_at': '2026-01-01T00:00:00Z',
			'merge_commit_sha': 'sha',
			'base': {'ref': 'master', 'repo': {'full_name': 'example/project'}},
		}
		nodes = [
			{'number': 1, 'issueType': {'name': 'Task'}, 'labels': {'nodes': [{'name': 'feature'}]}},
			{'number': 2, 'issueType': None, 'labels': {'nodes': [{'name': 'bug'}]}},
		]
		graphql = {'data': {'repository': {'pullRequest': {'closingIssuesReferences': {'nodes': nodes}}}}}
		with patch('plan_release.check_output', side_effect=[
			dumps([[pull]]).encode(),
			dumps(graphql).encode(),
		]):
			self.assertEqual(read_names('example/project', 'sha'), ['Task', 'feature', 'bug'])
		return
