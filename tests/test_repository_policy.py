"""Local policy contract; hosted enforcement requires separate live receipts."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GENERATED = '.github/workflows/main-automerge.yml'


def workflow(text):
    # Preserve GitHub's 'on' key instead of interpreting it as a YAML 1.1 boolean.
    return yaml.load(text, Loader=yaml.BaseLoader)


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
        self.assertEqual(doc['on'], {'pull_request': {'types': [
            'opened', 'reopened', 'synchronize', 'closed'], 'branches': ['main']}})
        self.assertEqual(set(doc['jobs']), {'auto-merge', 'label-release-pending'})
        auto = doc['jobs']['auto-merge']
        self.assertEqual(auto['if'], "github.event.action != 'closed'")
        self.assertIn('gh pr merge --auto --squash', auto['steps'][0]['run'])
        label = doc['jobs']['label-release-pending']
        self.assertIn("github.event.action == 'closed'", label['if'])
        self.assertIn('github.event.pull_request.merged == true', label['if'])
        self.assertIn('--add-label release-pending', label['steps'][0]['run'])
        for job in doc['jobs'].values():
            self.assertEqual(job['steps'][0]['env']['GH_TOKEN'],
                             '${{ secrets.SHIPFLOW_AUTOMERGE_PAT }}')

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
        for phrase in ['git switch -c feature/', '--base main', 'repository-policy',
                       'draft', 'SHIPFLOW_AUTOMERGE_PAT', 'manual-gate',
                       '--expect-state-hash', '--dry-run', 'main-protection.json',
                       'repository-settings.json', 'ready_for_review', 'branch deletion']:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, docs)


if __name__ == '__main__':
    unittest.main()
