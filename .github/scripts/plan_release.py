from json import loads
from os import environ
from pathlib import Path
from re import fullmatch
from subprocess import check_output
from typing import Optional

QUERY = (
	'query($owner:String!,$name:String!,$number:Int!){'
	'repository(owner:$owner,name:$name){pullRequest(number:$number){'
	'closingIssuesReferences(first:100){nodes{number issueType{name}}}'
	'}}}'
)
MINOR_NAMES = {'feature'}
PATCH_NAMES = {'bug', 'fix'}


def parse_release(tag: str, series: str) -> Optional[tuple]:
	"""Return (major, minor, patch, build, post, legacy) when the tag is a release at or above the series."""
	match = fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?(?:\.post(\d+))?', tag)
	if match is None:
		return None
	major, minor = map(int, series.split('.'))
	if int(match[1]) != major or int(match[2]) < minor:
		return None
	return tuple(map(int, match.groups()[:3])) + (
		int(match[4] or 0), int(match[5] or 0), match[4] is not None or match[5] is not None,
	)


def classify(names: list[str]) -> str:
	"""
	Return 'minor', 'patch' or 'none' for issue type names; feature wins over bug and fix.
	"""
	lowered = {name.lower() for name in names}
	if lowered & MINOR_NAMES:
		return 'minor'
	if lowered & PATCH_NAMES:
		return 'patch'
	return 'none'


def plan(series: str, tags: list[str], bump: str) -> tuple:
	"""Return (version, new_version, tag) for the latest release tags and the requested bump."""
	releases = {}
	for tag in tags:
		release = parse_release(tag, series)
		if release is not None:
			releases[release] = tag
	if not releases:
		return '{}.0'.format(series), True, '{}.0'.format(series)
	latest = max(releases)
	major, minor, patch = latest[:3]
	if bump == 'minor':
		version = '{}.{}.0'.format(major, minor + 1)
	elif bump == 'patch' or latest[5]:
		version = '{}.{}.{}'.format(major, minor, patch + 1)
	else:
		return '{}.{}.{}'.format(major, minor, patch), False, releases[latest]
	return version, True, version


def read_names(repository: str, sha: str) -> list[str]:
	"""
	Collect issue type names of the issues closed by the PR merged as the commit.
	"""
	pages = loads(check_output([
		'gh', 'api', '--paginate', '--slurp',
		'repos/{}/commits/{}/pulls?per_page=100'.format(repository, sha),
	]))
	pulls = [
		pull for page in pages for pull in page
		if pull['merged_at'] is not None
		and pull['merge_commit_sha'] == sha
		and pull['base']['ref'] == 'master'
		and pull['base']['repo']['full_name'] == repository
	]
	if len(pulls) > 1:
		raise ValueError('Multiple merged PRs found for the release commit')
	if not pulls:
		return []
	owner, name = repository.split('/')
	result = loads(check_output([
		'gh', 'api', 'graphql', '-f', 'query={}'.format(QUERY),
		'-F', 'owner={}'.format(owner), '-F', 'name={}'.format(name),
		'-F', 'number={}'.format(pulls[0]['number']),
	]))
	names = []
	for issue in result['data']['repository']['pullRequest']['closingIssuesReferences']['nodes']:
		if issue['issueType'] is not None:
			names.append(issue['issueType']['name'])
	return names


def main() -> None:
	series = environ['RELEASE_SERIES']
	if fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)', series) is None:
		raise ValueError('Invalid RELEASE_SERIES: {!r}'.format(series))
	before = environ['BEFORE']
	if not before:
		raise ValueError('Missing push base commit')
	number = int(environ['GITHUB_RUN_NUMBER'])
	if number < 1:
		raise ValueError('Build number must be positive')
	first_push = set(before) == {'0'}
	# Tags created by an earlier run of this commit are excluded on rerun.
	tags = [] if first_push else check_output(['git', 'tag', '--merged', before], text=True).splitlines()
	bump = classify(read_names(environ['GITHUB_REPOSITORY'], environ['GITHUB_SHA']))
	version, new_version, tag = plan(series, tags, bump)
	print('Issue bump: {}; planned version: {}, new version: {}, wheel build: {}'.format(
		bump, version, new_version, number,
	))
	with Path(environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
		output.write('release=true\nversion={}\n'.format(version))
		output.write('build={}\nnew_version={}\n'.format(number, str(new_version).lower()))
		output.write('tag={}\n'.format(tag))
	return


if __name__ == '__main__':
	main()
