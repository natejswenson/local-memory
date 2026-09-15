"""Local policy contract; hosted enforcement requires separate live receipts."""
import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GENERATED = '.github/workflows/main-automerge.yml'


def workflow(text):
    # Preserve GitHub's 'on' key instead of interpreting it as a YAML 1.1 boolean.
    return yaml.load(text, Loader=yaml.BaseLoader)


def condition(expression, context):
    """Fail-closed interpreter for comparisons joined by && in this template.

    Parse every clause before evaluating; unknown syntax fails even after a
    false clause. This intentionally is not a general GitHub expression engine.
    """
    operand = r"(?:github\.[a-zA-Z_.]+|'[^']*'|true|false)"
    parsed = []
    def value(token):
        if token.startswith("'"):
            return token[1:-1]
        if token in ('true', 'false'):
            return token == 'true'
        if token not in context:
            raise ValueError(f'Unsupported context: {token}')
        return context[token]
    for clause in expression.split('&&'):
        match = re.fullmatch(rf'\s*({operand})\s*(==|!=)\s*({operand})\s*', clause)
        if not match:
            raise ValueError(f'Unsupported condition: {clause}')
        left, op, right = match.groups()
        equal = value(left) == value(right)
        parsed.append(equal if op == '==' else not equal)
    return all(parsed)


def run_shell(script, inputs):
    """Execute the rendered shell with fake secrets and only a fake gh on PATH."""
    with tempfile.TemporaryDirectory(prefix='repository-policy-') as temporary:
        directory = Path(temporary)
        recorder = directory / 'gh'
        recorder.write_text(
            '#!' + sys.executable + '\n'
            'import json, os, sys\n'
            'with open(os.environ["RECORD"], "a") as output:\n'
            '    output.write(json.dumps(sys.argv[1:]) + "\\n")\n')
        recorder.chmod(0o700)
        record = directory / 'calls.jsonl'
        env = {'PATH': str(directory), 'HOME': str(directory), 'TMPDIR': str(directory),
               'RECORD': str(record), 'GITHUB_TOKEN': 'fake-unrelated-default-token',
               **inputs}
        result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-e', '-c', script],
                                cwd=directory, env=env, text=True, capture_output=True, timeout=5)
        if result.returncode:
            raise AssertionError(f'Rendered shell failed ({result.returncode}): {result.stderr}')
        calls = [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []
        return calls, result.stdout + result.stderr


class RepositoryPolicyTests(unittest.TestCase):
    def read(self, name):
        path = ROOT / name
        self.assertTrue(path.is_file(), f'Missing required policy file: {name}')
        return path.read_text()

    def config(self):
        return json.loads(self.read('.github/shipflow.json'))

    def assert_check_contract(self, config, ci):
        self.assertEqual(config['workflowPattern'], 'github-flow')
        self.assertEqual(config['branches'], {'main': 'main'})
        self.assertEqual(config['requiredChecks'], ['repository-policy'])
        event = ci['on']['pull_request']
        self.assertEqual(event['branches'], ['main'])
        self.assertFalse({'paths', 'paths-ignore', 'branches-ignore'} & event.keys())
        self.assertTrue({'opened', 'reopened', 'synchronize', 'edited'} <= set(event['types']))
        job = ci['jobs']['repository-policy']
        self.assertEqual(job['name'], 'repository-policy')
        for field in ['if', 'needs', 'continue-on-error']:
            self.assertNotIn(field, job)
        runs = [step['run'] for step in job['steps'] if 'run' in step]
        self.assertIn('python -B -m unittest discover -s tests -v\n', runs)
        self.assertTrue(any(
            'go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12' in run
            and '"$(go env GOPATH)/bin/actionlint" .github/workflows/ci.yml .github/workflows/main-automerge.yml' in run
            for run in runs))
        for step in job['steps']:
            self.assertNotIn('if', step)
            self.assertNotIn('continue-on-error', step)

    def test_required_check_contract(self):
        # The first assertion on the unchanged empty base is missing policy.
        config = self.config()
        self.assert_check_contract(config, workflow(self.read('.github/workflows/ci.yml')))

    def test_rejects_ungated_ci(self):
        config = self.config()
        ci = workflow(self.read('.github/workflows/ci.yml'))
        bad = copy.deepcopy(config)
        bad['requiredChecks'] = []
        with self.assertRaises(AssertionError):
            self.assert_check_contract(bad, ci)
        for field, value in [('branches', ['other']), ('paths', ['README.md']), ('types', ['closed'])]:
            bad = copy.deepcopy(ci)
            bad['on']['pull_request'][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.assert_check_contract(config, bad)
        bad = copy.deepcopy(ci)
        bad['on']['pull_request']['types'].remove('edited')
        with self.assertRaises(AssertionError):
            self.assert_check_contract(config, bad)
        bad = copy.deepcopy(ci)
        bad['jobs']['repository-policy']['steps'].pop()
        with self.assertRaises(AssertionError):
            self.assert_check_contract(config, bad)
        bad = copy.deepcopy(ci)
        del bad['on']['pull_request']
        with self.assertRaises(KeyError):
            self.assert_check_contract(config, bad)
        bad = copy.deepcopy(ci)
        bad['jobs']['repository-policy']['if'] = '!github.event.pull_request.draft'
        with self.assertRaises(AssertionError):
            self.assert_check_contract(config, bad)

    def assert_hash(self, config):
        self.assertTrue((ROOT / GENERATED).is_file())
        digest = hashlib.sha256((ROOT / GENERATED).read_bytes()).hexdigest()
        self.assertEqual(config['renderedTemplateHashes'], {GENERATED: digest})

    def test_generated_workflow_and_hash(self):
        config = self.config()
        self.assert_hash(config)
        bad = copy.deepcopy(config)
        bad['renderedTemplateHashes'][GENERATED] = '0' * 64
        with self.assertRaises(AssertionError):
            self.assert_hash(bad)
        self.assertEqual(config['protectionOwner'], 'shipflow')
        self.assertEqual(config['mergeMethod'], {'devToMainMethod': 'squash'})
        self.assertEqual(config['release'], {'enabled': True, 'mode': 'manual-gate',
                         'releaseCredential': 'SHIPFLOW_AUTOMERGE_PAT'})
        self.assertEqual(config['branchCleanup'], {'deleteOnMerge': True,
                         'protectedBranches': ['main']})
        self.assertIs(config['enforceAdmins'], True)
        doc = workflow(self.read(GENERATED))
        self.assertEqual(set(doc['jobs']), {'auto-merge', 'label-release-pending'})
        self.assertEqual(doc['permissions'], {})
        for job in doc['jobs'].values():
            self.assertEqual(job['permissions'], {'pull-requests': 'write'})
            self.assertEqual(len(job['steps']), 1)
            step = job['steps'][0]
            self.assertNotIn('uses', step)  # No checkout or PR code execution.
            self.assertEqual(step['env'], {
                'PR_NUMBER': '${{ github.event.pull_request.number }}',
                'PR_REPO': '${{ github.repository }}',
                'GH_TOKEN': '${{ secrets.SHIPFLOW_AUTOMERGE_PAT }}'})
            self.assertNotIn('${{', step['run'])
            self.assertNotIn('GITHUB_TOKEN', step['run'])
            self.assertIn('"$PR_NUMBER"', step['run'])
            self.assertIn('"$PR_REPO"', step['run'])

    def assert_generated_events(self, doc):
        self.assertEqual(doc['on'], {'pull_request': {'types': [
            'opened', 'reopened', 'synchronize', 'ready_for_review', 'closed'],
            'branches': ['main']}})

    def assert_generated_case(self, doc, action, draft, origin, merged, token):
        repo, number = 'example/local-memory', '17'
        context = {'github.repository': repo, 'github.event.action': action,
                   'github.event.pull_request.draft': draft,
                   'github.event.pull_request.merged': merged,
                   'github.event.pull_request.head.repo.full_name': origin}
        expected_jobs = []
        if origin == repo:
            if action == 'closed' and merged:
                expected_jobs = ['label-release-pending']
            elif action != 'closed' and not draft:
                expected_jobs = ['auto-merge']
        admitted = [name for name, job in doc['jobs'].items()
                    if condition(job['if'], context)]
        self.assertEqual(admitted, expected_jobs)
        for name in admitted:
            step = doc['jobs'][name]['steps'][0]
            # Resolve only the three reviewed env expressions. A new expression
            # cannot silently inherit the test process's environment or secrets.
            values = {'${{ github.event.pull_request.number }}': number,
                      '${{ github.repository }}': repo,
                      '${{ secrets.SHIPFLOW_AUTOMERGE_PAT }}': token}
            env = {key: values[value] for key, value in step['env'].items()
                   if values[value] is not None}
            script = step['run']
            # Model the runner's two fixed, safe-valued substitutions for the
            # old-template red probe; arbitrary expressions are rejected.
            for expression in ['${{ github.event.pull_request.number }}', '${{ github.repository }}']:
                script = script.replace(expression, values[expression])
            self.assertNotIn('${{', script)
            calls, output = run_shell(script, env)
            self.assertNotIn('fake-configured-token', output)
            self.assertNotIn('fake-unrelated-default-token', output)
            if token:
                expected = (['pr', 'merge', '--auto', '--squash', number, '--repo', repo]
                            if name == 'auto-merge' else
                            ['pr', 'edit', number, '--add-label', 'release-pending', '--repo', repo])
                self.assertEqual(calls, [expected])
            else:
                self.assertEqual(calls, [])
                self.assertIn('Skipping', output)
                self.assertIn('GH_TOKEN is unavailable or not configured', output)

    def test_generated_event_and_credential_contract(self):
        doc = workflow(self.read(GENERATED))  # Assertion-red on the empty base.
        with self.subTest(contract='subscribed events'):
            self.assert_generated_events(doc)
        # Evaluate every expected subscription even on an old workflow missing
        # readiness, so the red probe exposes guard and shell defects as well.
        for action in ['opened', 'reopened', 'synchronize', 'ready_for_review', 'closed']:
            for draft in [False, True]:
                for origin in ['example/local-memory', 'contributor/fork', None]:
                    for merged in ([False, True] if action == 'closed' else [False]):
                        for token in ['fake-configured-token', '', None]:
                            with self.subTest(action=action, draft=draft, origin=origin,
                                              merged=merged, token=bool(token)):
                                self.assert_generated_case(doc, action, draft, origin, merged, token)

    def test_rejects_weakened_generated_guards(self):
        doc = workflow(self.read(GENERATED))
        bad = copy.deepcopy(doc)
        bad['on']['pull_request']['types'].remove('ready_for_review')
        with self.assertRaises(AssertionError):
            self.assert_generated_events(bad)
        mutations = [
            ('auto-merge', 'github.event.pull_request.draft == false',
             'opened', True, 'example/local-memory', False),
            ('auto-merge', 'github.event.pull_request.head.repo.full_name == github.repository',
             'opened', False, 'contributor/fork', False),
            ('label-release-pending', 'github.event.pull_request.head.repo.full_name == github.repository',
             'closed', False, None, True)]
        for job, clause, action, draft, origin, merged in mutations:
            bad = copy.deepcopy(doc)
            clauses = bad['jobs'][job]['if'].split(' && ')
            self.assertIn(clause, clauses)
            clauses.remove(clause)
            bad['jobs'][job]['if'] = ' && '.join(clauses)
            with self.subTest(job=job, clause=clause), self.assertRaises(AssertionError):
                self.assert_generated_case(bad, action, draft, origin, merged, 'fake-configured-token')

    def test_guard_parser_fails_closed(self):
        context = {'github.event.action': 'opened'}
        self.assertTrue(condition("github.event.action != 'closed'", context))
        for expression in ["success()", "true || false", "github.unknown == true",
                           "github.event.action == 'opened' && nonsense", "",
                           "github.event.action != 'closed' || always()"]:
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                condition(expression, context)


    def assert_protection(self, policy):
        self.assertEqual(policy['required_status_checks'], {'strict': True,
            'checks': [{'context': 'repository-policy', 'app_id': 15368}]})
        self.assertIs(policy['enforce_admins'], True)
        self.assertIs(policy['allow_force_pushes'], False)
        self.assertIs(policy['allow_deletions'], False)
        self.assertEqual(policy['required_pull_request_reviews'], {
            'dismiss_stale_reviews': True, 'require_code_owner_reviews': False,
            'required_approving_review_count': 0})
        self.assertIsNone(policy['restrictions'])
        self.assertNotIn('bypass_pull_request_allowances', policy)

    def test_supplemental_enforcement(self):
        policy = json.loads(self.read('.github/main-protection.json'))
        self.assert_protection(policy)
        for field in ['allow_force_pushes', 'allow_deletions', 'enforce_admins']:
            bad = copy.deepcopy(policy)
            bad[field] = not bad[field]
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.assert_protection(bad)
        self.assertEqual(json.loads(self.read('.github/repository-settings.json')), {
            'allow_auto_merge': True, 'delete_branch_on_merge': True})

    def test_all_workflows_parse_and_stay_in_scope(self):
        files = sorted((ROOT / '.github/workflows').glob('*.y*ml'))
        self.assertEqual([p.name for p in files], ['ci.yml', 'main-automerge.yml'])
        for path in files:
            doc = workflow(path.read_text())
            self.assertIsInstance(doc, dict)
            self.assertTrue(set(doc['on']) <= {'pull_request', 'workflow_dispatch'})
            for job in doc['jobs'].values():
                for step in job['steps']:
                    command = step.get('run', '')
                    self.assertNotRegex(command, r'gh release|git tag|release-cut|workflow run')
                    self.assertNotRegex(command, r'head.ref|refs/heads/(dev|develop)')
        ci = workflow(self.read('.github/workflows/ci.yml'))
        self.assertEqual(ci['permissions'], {'contents': 'read'})
        self.assertIn('concurrency', ci)
        job = ci['jobs']['repository-policy']
        self.assertLessEqual(int(job['timeout-minutes']), 15)
        actions = [s for s in job['steps'] if 'uses' in s]
        self.assertEqual(len(actions), 2)
        for action in actions:
            self.assertRegex(action['uses'], r'^actions/[a-z-]+@[0-9a-f]{40}$')
        self.assertEqual(actions[0]['with']['persist-credentials'], 'false')
        self.assertIn('PyYAML==6.0.3', job['steps'][2]['run'])

    def test_contribution_guidance(self):
        self.assertIn('CONTRIBUTING.md', self.read('README.md'))
        docs = self.read('CONTRIBUTING.md')
        self.assertNotRegex(docs, r'npx[^\n]*@latest')
        for phrase in ['4b0847110915e596619593408f22be2e8309c41b',
                       'https://github.com/natejswenson/claude-skills.git',
                       '5614b69a8e3ebd7a6a81a46409073a9f549acf2297a8fc19c731893bfc54b427',
                       'SHIPFLOW_SOURCE_ROOT', 'unreleased source', 'fork PRs',
                       'unavailable', 'legacy', 'GITHUB_TOKEN', 'pending',
                       'git switch -c feature/', '--base main', 'repository-policy',
                       'draft', 'SHIPFLOW_AUTOMERGE_PAT', 'manual-gate',
                       '--expect-state-hash', '--dry-run', 'main-protection.json',
                       'repository-settings.json', 'ready_for_review', 'branch deletion']:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, docs)


if __name__ == '__main__':
    unittest.main()
