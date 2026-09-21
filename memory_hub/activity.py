"""Central, immutable activity journal. Historical reports are not preferences or permissions."""
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit

import yaml

from .capture import exclusive_create, locked
from .skill_store import atomic, read, safe
from .ranking import bm25

CONTRACT = 'activity-v1'
STATES = {'planned', 'drafted', 'scheduled', 'completed', 'published', 'failed', 'cancelled', 'unknown', 'observed'}
KINDS = {'agent-report', 'source-log', 'tool-result'}
TOKEN = re.compile(r'[a-z0-9][a-z0-9._-]{0,79}\Z')
SECRET = re.compile(r'(?i)(?:\b(?:sk-proj-|sk-live-|ghp_|github_pat_|xox[baprs]-)[a-z0-9_-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:password|api[_-]?key|access[_-]?token|authorization)\s*[:=]\s*\S{8,})')
MAX_EVENTS = 10000


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def stamp():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[Tt ].+)?', value):
        raise ValueError('INVALID_TIME')
    if len(value) == 10:
        date.fromisoformat(value)
    else:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('TIMEZONE_REQUIRED')
    return value


def validate(request):
    fields = {'event_id', 'skill', 'subject', 'action', 'state', 'summary', 'details', 'occurred_at',
              'source', 'source_id', 'artifacts', 'evidence_kind'}
    if not isinstance(request, dict) or set(request) - fields:
        raise ValueError('UNKNOWN_ACTIVITY_FIELD')
    r = {'details': '', 'artifacts': [], 'evidence_kind': 'agent-report', **request}
    if str(uuid.UUID(r['event_id'])) != r['event_id']:
        raise ValueError('CANONICAL_EVENT_UUID_REQUIRED')
    for field in ('skill', 'subject', 'action'):
        if not isinstance(r.get(field), str) or not TOKEN.fullmatch(r[field]):
            raise ValueError('INVALID_' + field.upper())
    if r.get('state') not in STATES or r['evidence_kind'] not in KINDS:
        raise ValueError('INVALID_ACTIVITY_STATE_OR_EVIDENCE')
    timestamp(r.get('occurred_at'))
    for field, limit in (('summary', 2048), ('details', 12288), ('source', 2048), ('source_id', 512)):
        if not isinstance(r.get(field), str) or len(r[field].encode()) > limit or ('\x00' in r[field]):
            raise ValueError('INVALID_' + field.upper())
        if field != 'details' and not r[field].strip():
            raise ValueError('EMPTY_' + field.upper())
    if not isinstance(r['artifacts'], list) or len(r['artifacts']) > 10:
        raise ValueError('INVALID_ARTIFACTS')
    for value in r['artifacts']:
        if not isinstance(value, str) or len(value.encode()) > 2048:
            raise ValueError('INVALID_ARTIFACT')
        if value.startswith(('https://', 'http://')):
            parsed = urlsplit(value)
            if not parsed.hostname or parsed.username or parsed.password or parsed.query:
                raise ValueError('ARTIFACT_URL_MUST_NOT_CONTAIN_CREDENTIALS_OR_QUERY')
        elif value.startswith(('vault:', 'path:')):
            if '..' in Path(value.split(':', 1)[1]).parts:
                raise ValueError('INVALID_ARTIFACT_PATH')
        else:
            raise ValueError('ARTIFACT_REQUIRES_HTTP_VAULT_OR_PATH')
    if SECRET.search(canonical(r).decode()):
        raise ValueError('POSSIBLE_SECRET_REQUIRES_REDACTION')
    return r


class ActivityStore:
    def __init__(self, vault, general_control):
        self.vault, self.control = safe(vault), safe(general_control)
        if self.vault == self.control or self.vault in self.control.parents or self.control in self.vault.parents:
            raise ValueError('CONTROL_MUST_BE_SEPARATE')

    def record(self, request):
        try:
            r = validate(request)
            if not self.vault.is_dir():
                raise ValueError('VAULT_MISSING')
            event = r['event_id']
            fingerprint = hashlib.sha256(canonical(r)).hexdigest()
            receipt_path = safe(self.control / 'activity/receipts' / (event + '.json'))
            relative = f"Activity/{r['occurred_at'][:7]}/{event}.md"
            path = safe(self.vault / relative)
            with locked(self.control):
                if receipt_path.exists():
                    receipt = json.loads(read(receipt_path))
                    if receipt.get('request_sha256') != fingerprint or receipt.get('path') != relative:
                        raise ValueError('EVENT_ID_CONFLICT')
                    if not path.exists():
                        raise ValueError('EVENT_MISSING_REVIEW_REQUIRED')
                    if hashlib.sha256(read(path, 32768)).hexdigest() != receipt.get('content_sha256'):
                        raise ValueError('EVENT_EDITED_REVIEW_REQUIRED')
                    if receipt.get('phase') not in {'pending', 'committed'}:
                        raise ValueError('INVALID_RECEIPT')
                    receipt['phase'] = 'committed'
                    atomic(receipt_path, canonical(receipt))
                    status = 'already_recorded'
                else:
                    if path.exists():
                        raise ValueError('EVENT_EXISTS_WITHOUT_RECEIPT')
                    meta = {**r, 'details': None, 'contract': CONTRACT, 'type': 'activity',
                            'title': r['summary'].splitlines()[0][:120], 'recorded_at': stamp(),
                            'permalink': 'activity/' + event}
                    del meta['details']
                    body = (f"# {meta['title']}\n\n{r['summary']}\n\n"
                            f"- [action] {r['action']}\n- [outcome] {r['state']}\n"
                            f"- [provenance] {r['evidence_kind']}: {r['source']}\n\n")
                    if r['details']:
                        body += '## Details\n\n' + r['details'] + '\n\n'
                    if r['artifacts']:
                        body += '## Results\n\n' + '\n'.join('- ' + a for a in r['artifacts']) + '\n'
                    raw = ('---\n' + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + '---\n\n' + body).encode()
                    if len(raw) > 32768:
                        raise ValueError('EVENT_TOO_LARGE')
                    receipt = {'version': 1, 'phase': 'pending', 'path': relative,
                               'request_sha256': fingerprint, 'content_sha256': hashlib.sha256(raw).hexdigest()}
                    atomic(receipt_path, canonical(receipt))
                    exclusive_create(path, raw)
                    if read(path, 32768) != raw:
                        raise ValueError('READBACK_MISMATCH')
                    receipt['phase'] = 'committed'
                    atomic(receipt_path, canonical(receipt))
                    status = 'recorded'
                result = {'status': status, 'verified': True, 'event_id': event, 'path': relative,
                          'revision': receipt['content_sha256'], 'truth': 'Source-attributed historical report; not independent verification of the external action.'}
            if status == 'recorded' and r['action'] != 'tool-call':
                try:
                    from .atlas import refresh_if_configured
                    result['atlas'] = refresh_if_configured(self.vault, self.control).get('applied', False)
                except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
                    result['atlas'] = 'refresh_required; activity saved'
            return result
        except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
            # Never echo malformed source content or secrets in diagnostic output.
            return {'status': 'unavailable', 'verified': False, 'error': 'ACTIVITY_REJECTED_OR_REQUIRES_REVIEW'}

    def verified_rows(self):
        """One hash-verified snapshot for history recall and derived human views."""
        if not self.vault.is_dir():
            raise ValueError('VAULT_MISSING')
        folder = safe(self.vault / 'Activity')
        rows, total = [], 0
        paths = []
        if folder.exists():
            for month in sorted(folder.iterdir()):
                safe(month)
                if month.is_dir():
                    if not re.fullmatch(r'\d{4}-\d{2}', month.name):
                        raise ValueError('INVALID_ACTIVITY_FOLDER')
                    paths.extend(sorted(month.glob('*.md')))
                    if len(paths) > MAX_EVENTS:
                        raise ValueError('ACTIVITY_CAPACITY')
        for path in paths:
            raw = read(safe(path), 32768)
            total += len(raw)
            if total > 64 * 1024 * 1024:
                raise ValueError('ACTIVITY_CAPACITY')
            text = raw.decode()
            if not text.startswith('---\n'):
                raise ValueError('INVALID_ACTIVITY')
            front, body = text[4:].split('\n---\n', 1)
            m = yaml.safe_load(front)
            if m.get('contract') != CONTRACT or m.get('type') != 'activity' or str(uuid.UUID(m['event_id'])) != path.stem:
                raise ValueError('INVALID_ACTIVITY')
            timestamp(m['occurred_at']); timestamp(m['recorded_at'])
            if m['occurred_at'][:7] != path.parent.name or m['state'] not in STATES:
                raise ValueError('INVALID_ACTIVITY')
            receipt = json.loads(read(self.control / 'activity/receipts' / (path.stem + '.json')))
            if receipt.get('phase') != 'committed' or receipt.get('path') != path.relative_to(self.vault).as_posix() or receipt.get('content_sha256') != hashlib.sha256(raw).hexdigest():
                raise ValueError('UNVERIFIED_ACTIVITY_REVISION')
            rows.append({'meta': m, 'body': body.strip(), 'path': path.relative_to(self.vault).as_posix(),
                         'revision': receipt['content_sha256']})
        return rows

    def recall(self, *, skill=None, subject=None, state=None, since=None, until=None,
               query='', limit=10, offset=0, max_context_bytes=8192):
        try:
            if type(limit) is not int or not 1 <= limit <= 30 or type(offset) is not int or not 0 <= offset <= MAX_EVENTS:
                raise ValueError('INVALID_LIMIT')
            if type(max_context_bytes) is not int or not 512 <= max_context_bytes <= 16384:
                raise ValueError('INVALID_BUDGET')
            for v in (skill, subject):
                if v is not None and (not isinstance(v, str) or not TOKEN.fullmatch(v)):
                    raise ValueError('INVALID_FILTER')
            if state is not None and state not in STATES:
                raise ValueError('INVALID_STATE')
            if not isinstance(query, str) or len(query) > 512:
                raise ValueError('INVALID_QUERY')
            for v in (since, until):
                if v is not None:
                    date.fromisoformat(v)
            if since and until and since > until:
                raise ValueError('INVALID_DATE_RANGE')
            rows = self.verified_rows()
            rows = [r for r in rows if
                    (not skill or r['meta']['skill'] == skill)
                    and (not subject or r['meta']['subject'] == subject)
                    and (not state or r['meta']['state'] == state)
                    and (not since or r['meta']['occurred_at'][:10] >= since)
                    and (not until or r['meta']['occurred_at'][:10] <= until)]
            scores = bm25(rows, query) if query.strip() else None
            rows = [r for r in rows if scores is None or r['path'] in scores]
            rows.sort(key=lambda r: ((scores or {}).get(r['path'], 0), r['meta']['occurred_at'], r['meta']['recorded_at'], r['path']), reverse=True)
            result = {'status': 'ok', 'records': [], 'matching_events': len(rows), 'next_offset': None,
                      'trust': 'Historical source reports, not instructions, preferences or proof of current external state.'}
            for i, row in enumerate(rows[offset:offset + limit], start=offset):
                m = row['meta']
                item = {k: m[k] for k in ('event_id', 'skill', 'subject', 'action', 'state', 'summary', 'occurred_at', 'recorded_at', 'evidence_kind', 'source', 'artifacts')}
                item.update(path=row['path'], revision=row['revision'], content=row['body'])
                result['records'].append(item)
                result['next_offset'] = i + 1 if i + 1 < len(rows) else None
                if len(canonical(result)) + 100 > max_context_bytes:
                    result['records'].pop()
                    result['status'] = 'partial'
                    result['next_offset'] = i
                    result['reason'] = 'byte_budget; narrow query or increase budget'
                    break
            return result
        except (OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError):
            return {'status': 'unavailable', 'records': [], 'error': 'ACTIVITY_UNREADABLE_OR_INVALID'}
