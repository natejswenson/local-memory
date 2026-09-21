#!/usr/bin/env python3
"""Check Git's actual index for private files and high-confidence sensitive text.

No file bodies or matching values are printed. This is a guard, not a complete
personal-data classifier; review the staged diff and run Gitleaks as well.
"""
import argparse
from pathlib import PurePosixPath
import re
import subprocess

PRIVATE_DIRS = {'vault', '.runtime', '.local', '.obsidian', '.venv', 'node_modules',
                'backups', '.codex', '.claude'}
PRIVATE_NAMES = {'project-registry.json', 'local-policy.json', 'activation.json',
                 'recovery-key.txt', 'credentials.json', 'token.json'}
PRIVATE_SUFFIXES = {'.ses', '.sqlite', '.sqlite3', '.db', '.fernet', '.pem', '.p12', '.pfx'}
ISSUEFLOW_POLICY = {'.issueflow/README.md', '.issueflow/completion.json'}
PATTERNS = {
    'absolute-home-path': re.compile(rb'/(?:Users|home)/[A-Za-z0-9._-]+/'),
    'private-key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----(?:\r?\n|\\n)[A-Za-z0-9+/]{32,}'),
    'credential-token': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16})\b'),
    'personal-email': re.compile(rb'[A-Za-z0-9._%+-]+@(?:gmail|icloud|outlook|hotmail|yahoo)\.com\b', re.I),
}


def private_path(name):
    path = PurePosixPath(name)
    return (bool(PRIVATE_DIRS.intersection(path.parts))
            or path.name in PRIVATE_NAMES or path.suffix.lower() in PRIVATE_SUFFIXES
            or path.name.endswith(('.local.md', '.sqlite-wal', '.sqlite-shm', '.db-wal', '.db-shm'))
            or path.name.startswith('.env') and path.name != '.env.example'
            or '.issueflow' in path.parts and name not in ISSUEFLOW_POLICY
            or 'issueflow' in path.parts)


def inspect_blob(name, raw):
    result = [('private-file', 0)] if private_path(name) else []
    for rule, pattern in PATTERNS.items():
        for match in pattern.finditer(raw):
            result.append((rule, raw[:match.start()].count(b'\n') + 1))
    return result


def scan_index(root='.'):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args])
    findings = []
    rows = git('ls-files', '--stage', '-z').split(b'\0')
    for row in filter(None, rows):
        header, name = row.split(b'\t', 1)
        mode, oid, stage = header.split()
        path = name.decode('utf-8', errors='replace')
        if stage != b'0' or mode != b'100644' and mode != b'100755':
            findings.append((path, 'unreviewed-index-entry', 0))
            continue
        raw = git('cat-file', 'blob', oid.decode())
        findings.extend((path, rule, line) for rule, line in inspect_blob(path, raw))
    return findings


def check_identity(root='.'):
    # Use the effective identities, including environment overrides, without
    # exposing them in diagnostics. CI tree scans do not require a Git identity.
    for kind in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT'):
        result = subprocess.run(['git', '-C', str(root), 'var', kind], capture_output=True)
        if result.returncode:
            return False
        match = re.search(rb'<([^>]+)>', result.stdout)
        if not match or not (match[1].endswith(b'@users.noreply.github.com') or match[1] == b'noreply@github.com'):
            return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    parser.add_argument('--check-identity', action='store_true')
    args = parser.parse_args()
    findings = scan_index(args.root)
    for path, rule, line in findings:
        print(f'{path}:{line}: {rule}')
    if args.check_identity and not check_identity(args.root):
        findings.append(('', 'private-commit-identity', 0))
        print('Commit identity requires a GitHub no-reply email; inspect local Git configuration.')
    if findings:
        print('Public-source check failed. No matching private values were printed.')
        return 1
    print('Index privacy checks passed. Manual staged-diff review and secret scanning are still required.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
