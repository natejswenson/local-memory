"""Explicit allowlisted source-log adapters; no transcript or recursive workspace ingestion."""
import hashlib
import json
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import yaml

from .activity import ActivityStore, canonical, validate, stamp
from .skill_store import read, safe, atomic
from .capture import locked


def publication(skill, row, source):
    if skill not in {'ghostwriter', 'ghostwriter-x'} or not isinstance(row, dict):
        raise ValueError('Unsupported publisher')
    link = row.get('url')
    parsed = urlsplit(link) if isinstance(link, str) else None
    hosts = {'linkedin.com', 'www.linkedin.com'} if skill == 'ghostwriter' else {'x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'}
    if not parsed or parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password or not parsed.path.strip('/'):
        raise ValueError('Confirmed publication URL required')
    # Tracking query parameters never become memory or identity.
    link = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip('/'), '', ''))
    title = row.get('first_line') or row.get('slug') or 'Published post'
    if not isinstance(title, str):
        raise ValueError('Invalid publication title')
    when = row.get('published_at') or row.get('date')
    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, 'local-memory:publication:' + skill + ':' + link))
    details = '\n'.join(f'{k}: {row[k]}' for k in ('slug', 'lane', 'format') if isinstance(row.get(k), str))
    details += '\n\nImported from the publisher success log. Only the logged excerpt is available; the link identifies the published content. The platform was not re-fetched.'
    return validate(dict(event_id=event_id, skill=skill, subject='publishing', action='publish', state='published',
        occurred_at=when, summary=title[:300], details=details, source=str(source), source_id=link,
        artifacts=[link], evidence_kind='source-log'))


def sync_sources(vault, general_control, sources, apply=False):
    if not isinstance(sources, list) or len(sources) > 20:
        raise ValueError('Invalid source configuration')
    store = ActivityStore(vault, general_control)
    reports = []
    for spec in sources:
        report = {'skill': spec.get('skill') if isinstance(spec, dict) else None, 'created': 0, 'unchanged': 0, 'rejected': 0, 'status': 'ok'}
        try:
            if not isinstance(spec, dict) or set(spec) != {'skill', 'path'}:
                raise ValueError('Unknown source fields')
            if not isinstance(spec['path'], str) or not Path(spec['path']).is_absolute():
                raise ValueError('Absolute source required')
            source = safe(spec['path'])
            if any(p.casefold() in {'.issueflow', 'issueflow', 'projects'} for p in source.parts):
                raise ValueError('Source not eligible for log ingestion')
            raw = read(source, 8 * 1024 * 1024)
            lines = raw.splitlines()
            if len(lines) > 10000:
                raise ValueError('Source too large')
            prepared = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    prepared.append(publication(spec['skill'], json.loads(line), source))
                except (ValueError, TypeError, KeyError):
                    report['rejected'] += 1
            if raw != read(source, 8 * 1024 * 1024):
                raise ValueError('Source changed during read')
            report['source_sha256'] = hashlib.sha256(raw).hexdigest()
            report['eligible'] = len(prepared)
            if apply:
                for event in prepared:
                    result = store.record(event)
                    if result.get('status') == 'recorded':
                        report['created'] += 1
                    elif result.get('status') == 'already_recorded':
                        report['unchanged'] += 1
                    else:
                        report['rejected'] += 1
            if report['rejected']:
                report['status'] = 'needs_review'
        except (OSError, ValueError, TypeError, KeyError):
            report['status'] = 'unavailable'
        reports.append(report)
    result = {'status': 'ok' if all(r['status'] == 'ok' for r in reports) else 'partial',
              'applied': apply, 'checked_at': stamp(), 'sources': reports}
    if apply:
        atomic(safe(general_control) / 'activity/sync-status.json', canonical(result))
        from scripts.install_vault_workspace import navigation, update_navigation
        lines = ['Last publication-log check: ' + result['checked_at'], '',
                 '| Source | Mode | Latest check |', '| --- | --- | --- |']
        for report in reports:
            lines.append(f"| {report['skill']} | Automatic source-log sync, every 5 minutes | {report['status']}; {report['created']} new, {report['unchanged']} already recorded, {report['rejected']} need review |")
        hook_status = 'No native host event observed yet; trusted hooks report here after their next tool call (restart existing CLI sessions)'
        hook_health = safe(general_control) / 'activity/hook-status.json'
        if hook_health.exists():
            health = json.loads(read(hook_health, 4096))
            hook_status = str(health.get('status', 'unknown')) + '; last hook check ' + str(health.get('checked_at', 'unknown'))
        lines.extend(['| All skill outcomes | Agent reports via record_activity | Requires updated host instructions/tools |',
                      '| Codex tool calls | PostToolUse metadata hook | ' + hook_status + ' |',
                      '| Fitness preferences/journal | Existing owner tools | Already stored under Projects/local-fitness |', '',
                      'Publication entries preserve the source-log excerpt and URL. No transcript scan, raw tool payloads, or issueflow artifact ingestion occurs.', '',
                      'A last check confirms importer execution, not that an external platform still hosts a post. Historical deletions and edited records require review.'])
        proposed = navigation('Integration coverage', '\n'.join(lines))
        path = safe(Path(vault) / 'Activity/Coverage.md')
        with locked(general_control):
            if path.exists():
                proposed = update_navigation(read(path, 32768).decode(), proposed)
            atomic(path, proposed.encode())
        try:
            from .atlas import refresh_if_configured
            result['atlas'] = refresh_if_configured(vault, general_control).get('applied', False)
        except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
            result['atlas'] = 'refresh_required; source import completed'
    return result
