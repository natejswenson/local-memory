"""Trusted, private repository bindings; vault content cannot register a subject."""
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .skill_store import read, safe

DEFAULT_SUBJECTS = frozenset({'global', 'local-memory'})
TOKEN = re.compile(r'[a-z0-9][a-z0-9._-]{0,79}\Z')
RESERVED = {'global', 'local-fitness', 'atlas', 'activity', 'skillmemory',
            'templates', 'scratch', 'clippings', 'issueflow'}
DEFAULT_TOPICS = {'memory': 'Knowledge', 'software': 'Software'}


def valid_title(value):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= 120
            and value == value.strip() and not any(c in value for c in '/\\[]|#^\r\n:*?"<>')
            and value not in {'.', '..'})


def registry_path(vault):
    from .paths import control_for
    return control_for(safe(vault)) / 'project-registry.json'


def registry(vault):
    path = safe(registry_path(vault))
    if not path.exists():
        return {'version': 1, 'projects': [], 'timezone': 'UTC',
                'topics': dict(DEFAULT_TOPICS), 'areas': {}, 'activity_areas': {}}
    value = json.loads(read(path, 262144))
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('projects'), list):
        raise ValueError('INVALID_PROJECT_REGISTRY')
    topics, areas = value.get('topics', {}), value.get('areas', {})
    if not isinstance(topics, dict) or not isinstance(areas, dict):
        raise ValueError('INVALID_ATLAS_TAXONOMY')
    topics = {**DEFAULT_TOPICS, **topics}
    if (any(not isinstance(key, str) or not TOKEN.fullmatch(key) or not valid_title(title)
            for key, title in topics.items())
            or len({title.casefold() for title in topics.values()}) != len(topics)):
        raise ValueError('INVALID_ATLAS_TOPICS')
    area_tags = set()
    for name, tags in areas.items():
        if (not valid_title(name) or not isinstance(tags, list) or not tags
                or any(not isinstance(t, str) or t not in topics or t in area_tags for t in tags)
                or len(set(tags)) != len(tags)):
            raise ValueError('INVALID_ATLAS_AREAS')
        area_tags.update(tags)
    if len({name.casefold() for name in areas}) != len(areas):
        raise ValueError('INVALID_ATLAS_AREAS')
    activity_areas = value.get('activity_areas', {})
    if (not isinstance(activity_areas, dict)
            or any(not isinstance(key, str) or not TOKEN.fullmatch(key)
                   or not isinstance(area, str) or area not in areas for key, area in activity_areas.items())
            or value.get('fitness_area') is not None and value['fitness_area'] not in areas):
        raise ValueError('INVALID_ATLAS_AREA_BINDING')
    try:
        ZoneInfo(value.get('timezone', 'UTC'))
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise ValueError('INVALID_PROJECT_TIMEZONE') from None
    value = {**value, 'topics': topics, 'areas': areas, 'activity_areas': activity_areas,
             'timezone': value.get('timezone', 'UTC')}
    subjects, paths, titles = set(), set(), set()
    for row in value['projects']:
        if not isinstance(row, dict):
            raise ValueError('INVALID_PROJECT_BINDING')
        subject, title = row.get('subject'), row.get('title')
        if (not isinstance(subject, str) or not TOKEN.fullmatch(subject)
                or subject in RESERVED or subject in subjects
                or not valid_title(title)
                or title.casefold() in titles or title.casefold() == 'local projects'):
            raise ValueError('INVALID_PROJECT_BINDING')
        subjects.add(subject); titles.add(title.casefold())
        if (not isinstance(row.get('topics', []), list)
                or any(not isinstance(t, str) or t not in topics for t in row.get('topics', []))
                or row.get('area') is not None and row['area'] not in areas):
            raise ValueError('INVALID_PROJECT_TAXONOMY')
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
