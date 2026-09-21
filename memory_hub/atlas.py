"""Readable, linked views over authoritative memory, without rewriting owner records.

Atlas pages are navigation, never independent AI evidence. Technical identities
remain in source records; the graph contains meaningful projects, topics and days.
"""
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import uuid
from zoneinfo import ZoneInfo

import yaml

from .activity import ActivityStore
from .capture import locked
from .maintenance import catalog
from .projects import registry, registry_path
from .skill_store import atomic, read, safe

BEGIN = '<!-- BEGIN MEMORY ATLAS -->'
END = '<!-- END MEMORY ATLAS -->'
MANAGED = 'memory-atlas-v1'


def topic_path(topic, topics, areas):
    # A life area and its identically named topic are one concept, not two nodes.
    area = next((name for name, tags in areas.items() if topic in tags), None)
    return 'Atlas/Areas/' + area + '.md' if area else 'Atlas/Topics/' + topics[topic] + '.md'


def clean(value, limit=160):
    text = re.sub(r'[\[\]|#^\r\n/\\:*?"<>]', ' ', str(value))
    return re.sub(r'\s+', ' ', text).strip()[:limit].rstrip(' .') or 'Untitled'


def title(value):
    return clean(re.sub(r'\s+[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$', '', str(value)), 110)


def link(path, label=None):
    name = path[:-3] if path.endswith('.md') else path
    return '[[' + name + ('|' + clean(label) if label else '') + ']]'


def page(name, kind, body, tags=(), **properties):
    meta = {'title': name, 'type': 'navigation', 'status': 'system',
            'managed_by': MANAGED, 'kind': kind,
            'tags': ['atlas', *sorted({'topic/' + t for t in tags})], **properties}
    return ('---\n' + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
            + '---\n\n# ' + name + '\n\n' + BEGIN + '\n' + body.strip() + '\n' + END + '\n')


def merge(old, new):
    """Only regenerate our region; personal writing outside it always wins."""
    if old is None:
        return new
    front, rest = old.decode().split('\n---\n', 1)
    meta = yaml.safe_load(front.removeprefix('---\n'))
    if meta.get('managed_by') != MANAGED or rest.count(BEGIN) != 1 or rest.count(END) != 1:
        raise ValueError('ATLAS_DESTINATION_CUSTOMIZED_OR_UNMANAGED')
    if rest.index(END) < rest.index(BEGIN):
        raise ValueError('ATLAS_MARKERS_INVALID')
    # Preserve custom properties; refresh only properties the generator owns.
    new_front, new_rest = new.split('\n---\n', 1)
    generated = yaml.safe_load(new_front.removeprefix('---\n'))
    combined = {**meta, **generated}
    combined['tags'] = list(dict.fromkeys([*generated['tags'], *(meta.get('tags') or [])]))
    old_region = rest.split(BEGIN, 1)[1].split(END, 1)[0]
    new_region = new_rest.split(BEGIN, 1)[1].split(END, 1)[0]
    rest = rest.replace(BEGIN + old_region + END, BEGIN + new_region + END, 1)
    return '---\n' + yaml.safe_dump(combined, sort_keys=False, allow_unicode=True) + '---\n' + rest


def local_day(when, zone):
    if len(when) == 10:
        return when  # Date-only source logs must not acquire invented timezones.
    return datetime.fromisoformat(when.replace('Z', '+00:00')).astimezone(zone).date().isoformat()


def plan(vault, control):
    cfg = registry(vault)
    if not cfg['projects']:
        raise ValueError('REGISTER_PROJECTS_BEFORE_BUILDING_ATLAS')
    zone = ZoneInfo(cfg['timezone'])
    topics, areas = cfg['topics'], cfg['areas']
    projects = {r['subject']: r for r in cfg['projects']}
    project_paths = {s: 'Atlas/Projects/' + r['title'] + '.md' for s, r in projects.items()}
    # Owner fitness records stay with their writer. Software-project facts have a
    # different scope from the owner's health preferences and coaching history.
    aliases = {Path(p).name: s for s, r in projects.items() for p in r['paths']}
    aliases.update({s: s for s in projects})
    records = ActivityStore(vault, control).verified_rows()
    meaningful = [r for r in records if r['meta']['action'] != 'tool-call']
    history = defaultdict(list)
    for row in meaningful:
        history[local_day(row['meta']['occurred_at'], zone)].append(row)
    bodies, project_days, topic_pages = {}, defaultdict(set), defaultdict(list)
    project_knowledge = defaultdict(list)
    inventory = catalog(vault)
    current = inventory['current']
    knowledge_paths = {}
    for row in current:
        name = title(row['meta']['title'])
        name = cfg.get('note_titles', {}).get(row['path'], name)
        path = 'Atlas/Knowledge/' + clean(name, 110) + '.md'
        if path in knowledge_paths.values() or path == 'Atlas/Knowledge/Knowledge.md':
            path = path[:-3] + ' (' + hashlib.sha256(row['path'].encode()).hexdigest()[:8] + ').md'
        knowledge_paths[row['path']] = path
        subject = row['meta']['project']
        # Global memory-hub preferences are explicitly tied to the memory hub;
        # other global records belong to the Knowledge index until curated.
        selected = subject if subject in projects else 'local-memory' if 'local-memory' in projects and str(row['meta'].get('key', '')).startswith('preferences.memory-hub.') else None
        links = [link('Atlas/Knowledge/Knowledge.md', 'Knowledge')]
        tags = ['memory']
        if selected:
            links.append(link(project_paths[selected], projects[selected]['title']))
            project_knowledge[selected].append(path)
            tags.extend(projects[selected].get('topics', []))
        body = ('Related: ' + ' · '.join(links) + '\n\n'
                + 'This page displays the current source note.\n\n!'
                + link(row['path']) + '\n\nSource: ' + link(row['path'], 'Open the authoritative memory')
                + '\n\n' + str(row['meta'].get('source', '')))
        bodies[path] = page(name, 'knowledge', body, tags, subject=subject,
                            source_note=link(row['path']), source_revision=row['revision'])
        for tag in set(tags): topic_pages[tag].append(path)

    daily_paths = []
    for day, rows in sorted(history.items(), reverse=True):
        path = f'Atlas/Journal/{day} - Daily summary.md'
        daily_paths.append(path)
        sections = defaultdict(list)
        tags = set()
        priority = {'published': 8, 'completed': 7, 'failed': 6, 'unknown': 5,
                    'scheduled': 4, 'drafted': 3, 'cancelled': 2, 'planned': 1, 'observed': 0}
        for row in sorted(rows, key=lambda r: (priority[r['meta']['state']], r['meta']['occurred_at'], r['path']), reverse=True):
            m = row['meta']; subject = aliases.get(m['subject'])
            if subject:
                group = link(project_paths[subject], projects[subject]['title'])
                project_days[subject].add(path)
                tags.update(projects[subject].get('topics', []))
            elif m['subject'] in cfg['activity_areas']:
                area = cfg['activity_areas'][m['subject']]
                group = link('Atlas/Areas/' + area + '.md', area)
                tags.update(areas[area])
            else:
                group = clean(m['subject'])
            summary = re.sub(r'\s+', ' ', m['summary']).strip()
            # Preserve whole concise sentences when available; source remains one click away.
            if len(summary) > 220:
                first = re.split(r'(?<=[.!?])\s+', summary)[0]
                summary = first if len(first) <= 220 else summary[:217].rsplit(' ', 1)[0] + '…'
            summary = summary.replace('[[', '').replace(']]', '')
            line = f"- **{m['state'].capitalize()}** — {summary} " + link(row['path'], 'source')
            sections[group].append(line)
        counts = Counter(r['meta']['state'] for r in rows)
        lines = [link('Atlas/Journal/Daily summaries.md', 'Daily summaries'), '',
                 ' · '.join(str(n) + ' ' + state for state, n in sorted(counts.items())), '']
        for group, items in sorted(sections.items()):
            lines.extend(['## ' + group, '', *items[:3], ''])
            if len(items) > 3:
                lines.extend(['> [!abstract]- ' + str(len(items) - 3) + ' more recorded outcomes',
                              *['> ' + item for item in items[3:]], ''])
        lines.extend(['Dates use ' + str(zone) + '; date-only source dates are preserved.',
                      'This is a summary of recorded outcomes. Tool invocations are omitted.'])
        bodies[path] = page(day + ' — Daily summary', 'daily-summary', '\n'.join(lines), tags, date=day)

    for subject, row in projects.items():
        path = project_paths[subject]; project_topics = row.get('topics', ['software'])
        lines = [link('Atlas/Projects/Local Projects.md', 'All local projects'), '', row.get('description', 'Local repository. Its purpose has not been documented here yet.'), '']
        area = row.get('area')
        if area in areas:
            lines.extend(['Area: ' + link('Atlas/Areas/' + area + '.md', area), ''])
        related_topics = [link(topic_path(t, topics, areas), topics[t]) for t in project_topics if topic_path(t, topics, areas) != 'Atlas/Areas/' + str(area) + '.md']
        if related_topics: lines.extend(['Topics: ' + ' · '.join(related_topics), ''])
        lines.extend(['## Decisions and preferences', '',
                      '\n'.join('- ' + link(k, Path(k).stem) for k in project_knowledge[subject]) or 'No durable project facts have been explicitly saved yet.', '',
                      '## Recent outcomes', '',
                      '\n'.join('- ' + link(p, Path(p).stem) for p in sorted(project_days[subject], reverse=True)[:7]) or 'No skill outcomes are recorded for this project yet.', '',
                      '## Repository', '', *['- `' + p + '`' for p in row['paths']]])
        bodies[path] = page(row['title'], 'project', '\n'.join(lines), project_topics,
                            aliases=list(dict.fromkeys([Path(p).name for p in row['paths']])), subject=subject)
        for topic in project_topics: topic_pages[topic].append(path)

    for name, area_topics in areas.items():
        items = sorted(set([p for topic in area_topics for p in topic_pages[topic]]))
        lines = [link('Atlas/Home.md', 'Home'), '',
                 '## Projects and knowledge', '', *['- ' + link(p, Path(p).stem) for p in items]]
        if name == cfg.get('fitness_area'):
            lines.extend(['', '## Coaching history', '',
                          'Preferences and coaching history remain in their fitness source records.',
                          '![[Atlas/Fitness history.base]]'])
        else:
            days = [p for p in daily_paths if any('topic/' + topic in bodies[p] for topic in area_topics)]
            lines.extend(['', '## Recent activity', '', *['- ' + link(p, Path(p).stem) for p in days[:7]]])
        path = 'Atlas/Areas/' + name + '.md'
        bodies[path] = page(name, 'area', '\n'.join(lines), area_topics)
        for topic in area_topics: topic_pages[topic].append(path)

    for topic, paths in sorted(topic_pages.items()):
        if topic not in topics: continue
        if topic_path(topic, topics, areas).startswith('Atlas/Areas/'): continue
        name = topics[topic]
        bodies['Atlas/Topics/' + name + '.md'] = page(name, 'topic',
            link('Atlas/Home.md', 'Home') + '\n\n' + '\n'.join('- ' + link(p, Path(p).stem) for p in sorted(set(paths))), [topic])
    bodies['Atlas/Projects/Local Projects.md'] = page('Local Projects', 'index',
        link('Atlas/Home.md', 'Home') + '\n\n' + '\n'.join('- ' + link(p, projects[s]['title']) for s, p in sorted(project_paths.items(), key=lambda item: projects[item[0]]['title'].lower())), ['software'])
    bodies['Atlas/Knowledge/Knowledge.md'] = page('Knowledge', 'index',
        link('Atlas/Home.md', 'Home') + '\n\nDecisions and preferences from current, validated memory.\n\n' +
        '\n'.join('- ' + link(p, Path(p).stem) for p in sorted(knowledge_paths.values())), ['memory'])
    bodies['Atlas/Journal/Daily summaries.md'] = page('Daily summaries', 'index',
        link('Atlas/Home.md', 'Home') + '\n\nMeaningful outcomes grouped by your local day and project.\n\n' +
        '\n'.join('- ' + link(p, Path(p).stem) for p in daily_paths), ['memory'])
    bodies['Atlas/How this memory works.md'] = page('How this memory works', 'guide', '''[[Atlas/Home|Home]]

Projects organize work. Areas organize ongoing parts of life. Topic pages connect related projects and knowledge.

Tags use the configured vocabulary: {{topic-tags}}. The `atlas` tag marks pages in the readable map. A note's `kind` property says whether it is a project, area, topic, knowledge page, or daily summary.

Daily summaries show meaningful outcomes and keep drafted, failed, scheduled and published states separate. Tool-call receipts stay in the detailed record collection. [[Activity views.base|Browse detailed activity]] when you need sources.

To save lasting knowledge, ask to remember the specific decision or preference and its project. A source-backed memory is saved in that scope; this map displays the current source. A journal entry never becomes a preference automatically. Corrections preserve their history.

The main graph shows `tag:#atlas -path:"Atlas/Journal"`: projects, areas, topics and knowledge. Browse [[Atlas/Journal/Daily summaries|daily summaries]] separately. Use `tag:#atlas` to include them in the graph. Edges are actual wikilinks: project membership, topic relationships, and source-backed knowledge. Tags aid filtering; they do not replace those links. Source records remain accessible through the map.

These pages are refreshed views. Add personal writing outside the managed block if you want it preserved. Use the memory tools to correct authoritative claims. Source-owned records keep their owner tools and remain separate from software project decisions.
'''.replace('{{topic-tags}}', ', '.join('`topic/' + t + '`' for t in sorted(topics))), ['memory'])
    bodies['Atlas/Home.md'] = page('Home', 'home', '\n'.join([
        '## Areas', '', *['- ' + link('Atlas/Areas/' + a + '.md', a) for a in areas], '',
        '## Projects and knowledge', '',
        '- [[Atlas/Projects/Local Projects|All local projects]]',
        '- [[Atlas/Knowledge/Knowledge|Decisions and preferences]]',
        '- [[Atlas/Journal/Daily summaries|Daily summaries]]', '',
        '## Recent days', '', *['- ' + link(p, Path(p).stem) for p in daily_paths[:5]], '',
        '[[Atlas/How this memory works|How this memory works]]']), ['memory'])
    base = {'filters': {'and': ['file.ext == "md"', 'file.inFolder("Projects/local-fitness")']},
            'formulas': {'entry': 'link(file.path, if(fitness_entry_date, fitness_entry_date + " — Coach note", "Fitness preference"))'},
            'views': [{'type': 'table', 'name': 'Coaching history',
                       'order': ['formula.entry', 'note.fitness_entry_date', 'note.kind', 'note.status'],
                       'sort': [{'property': 'note.fitness_entry_date', 'direction': 'DESC'}]}]}
    if cfg.get('fitness_area'):
        bodies['Atlas/Fitness history.base'] = '# ' + MANAGED + '\n' + yaml.safe_dump(base, sort_keys=False)
    return bodies, {'projects': len(projects), 'daily_summaries': len(history), 'knowledge_pages': len(current),
                    'meaningful_outcomes': len(meaningful), 'technical_records': len(records) - len(meaningful)}


def refresh(vault, control, apply=False):
    vault, control = safe(vault), safe(control)
    with locked(control):
        bodies, counts = plan(vault, control)
        # Replaced/overdue memories must not leave an apparently current page.
        # Retire only our known generated views, preserving personal additions.
        for path in sorted((vault / 'Atlas').rglob('*.md')):
            name = path.relative_to(vault).as_posix()
            if name in bodies: continue
            old = read(safe(path), 1024 * 1024).decode()
            if not old.startswith('---\n'): continue
            meta = yaml.safe_load(old[4:].split('\n---\n', 1)[0])
            if meta.get('managed_by') == MANAGED:
                bodies[name] = page(meta.get('title', path.stem), 'retired-view',
                    'This view is no longer current. See [[Atlas/Knowledge/Knowledge|current knowledge]] or [[Atlas/Home|Home]].', ['memory'])
        changes = []
        for name, proposed in bodies.items():
            path = safe(vault / name)
            old = read(path, 1024 * 1024) if path.exists() else None
            if name.endswith('.md'):
                proposed = merge(old, proposed)
            elif old is not None and not old.startswith(('# ' + MANAGED + '\n').encode()):
                continue
            new = proposed.encode()
            if old != new: changes.append((name, old, new))
        result = {'applied': apply, **counts, 'changed': [p for p, _, _ in changes]}
        if not apply or not changes: return result
        backup = safe(control.parent / 'atlas-backups' / str(uuid.uuid4()))
        # Validate every destination before any write. Every replaced page has a recovery copy.
        for name, old, _ in changes:
            path = safe(vault / name)
            if (read(path, 1024 * 1024) if path.exists() else None) != old:
                raise ValueError('ATLAS_CHANGED_DURING_REFRESH')
        for name, old, new in changes:
            if old is not None: atomic(backup / name, old)
            atomic(vault / name, new)
        atomic(backup / 'manifest.json', json.dumps({'created': [p for p, old, _ in changes if old is None],
                                                   'updated': [p for p, old, _ in changes if old is not None]}).encode())
        result['backup'] = str(backup)
        return result


def refresh_if_configured(vault, control):
    if registry_path(vault).exists():
        return refresh(vault, control, True)
    return {'applied': False, 'reason': 'atlas_not_configured'}
