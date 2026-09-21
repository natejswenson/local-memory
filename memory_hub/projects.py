"""Trusted, private repository bindings; vault content cannot register a subject."""
import json
from pathlib import Path
import re

from .skill_store import read, safe

DEFAULT_SUBJECTS = frozenset({'global', 'local-memory'})
TOKEN = re.compile(r'[a-z0-9][a-z0-9._-]{0,79}\Z')
RESERVED = {'global', 'local-fitness', 'atlas', 'activity', 'skillmemory',
            'templates', 'scratch', 'clippings', 'issueflow'}


def registry_path(vault):
    return safe(vault).parent / '.runtime/general-memory/project-registry.json'


def registry(vault):
    path = safe(registry_path(vault))
    if not path.exists():
        return {'version': 1, 'projects': [], 'timezone': 'America/Chicago'}
    value = json.loads(read(path, 262144))
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('projects'), list):
        raise ValueError('INVALID_PROJECT_REGISTRY')
    subjects, paths, titles = set(), set(), set()
    for row in value['projects']:
        if not isinstance(row, dict):
            raise ValueError('INVALID_PROJECT_BINDING')
        subject, title = row.get('subject'), row.get('title')
        if (not isinstance(subject, str) or not TOKEN.fullmatch(subject)
                or subject in RESERVED or subject in subjects
                or not isinstance(title, str) or not title.strip() or len(title) > 120
                or any(c in title for c in '/\\[]|#^\r\n:*?"<>')
                or title.casefold() in titles or title.casefold() == 'local projects'):
            raise ValueError('INVALID_PROJECT_BINDING')
        subjects.add(subject); titles.add(title.casefold())
        if not isinstance(row.get('paths'), list) or not row['paths']:
            raise ValueError('PROJECT_PATHS_REQUIRED')
        for root in row['paths']:
            if not isinstance(root, str) or not Path(root).is_absolute() or root in paths or '..' in Path(root).parts:
                raise ValueError('INVALID_PROJECT_PATH')
            paths.add(root)
    return value


def subjects(vault):
    return DEFAULT_SUBJECTS | {r['subject'] for r in registry(vault)['projects']}


def resolve_subject(vault, directory):
    """Exact configured checkout/worktree ancestry, never a name similarity guess."""
    selected = Path(directory).resolve()
    matches = [(len(Path(root).parts), r['subject']) for r in registry(vault)['projects']
               for root in r['paths'] if selected == Path(root) or Path(root) in selected.parents]
    return max(matches)[1] if matches else 'global'
