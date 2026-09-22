"""Disposable activity search cache. Returned content always comes from verified files."""
from contextlib import contextmanager
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid

from .capture import locked
from .change_log import ChangeLog
from .serialization import canonical
from .skill_store import safe, read

VERSION = 1
RECONCILE_SECONDS = 300
CURSOR_SECONDS = 900
MAX_RANKED = 5000


class ActivityIndex:
    def __init__(self, store):
        self.store = store
        self.folder = safe(store.control.parent / 'indexes')
        self.path = self.folder / 'activity-v1.sqlite'
        self.identity = hashlib.sha256(str(store.vault).encode()).hexdigest()

    @contextmanager
    def connect(self):
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        safe(self.path)
        for suffix in ('-wal', '-shm'):
            safe(self.folder / (self.path.name + suffix))
        # SQLite creates journals alongside this private database. umask is not
        # process-local; create the database with explicit permissions instead.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        db = sqlite3.connect(self.path, timeout=0.25)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA busy_timeout=250')
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT UNIQUE NOT NULL,
                    path TEXT UNIQUE NOT NULL, revision TEXT NOT NULL, skill TEXT NOT NULL,
                    subject TEXT NOT NULL, state TEXT NOT NULL, stream TEXT NOT NULL,
                    occurred TEXT NOT NULL, recorded TEXT NOT NULL, meta TEXT NOT NULL,
                    sequence INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS activity_scope ON events(skill,subject,state,stream,occurred DESC);
                CREATE INDEX IF NOT EXISTS activity_date ON events(occurred DESC,recorded DESC,path DESC);
                CREATE TABLE IF NOT EXISTS issues (path TEXT PRIMARY KEY, reason TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cursors (token TEXT PRIMARY KEY, expires REAL NOT NULL, data TEXT NOT NULL);
            ''')
            existing = self.setting(db, 'identity')
            if existing is None:
                self.set(db, 'identity', self.identity)
                self.set(db, 'version', VERSION)
                self.set(db, 'checkpoint', 0)
            elif existing != self.identity or self.setting(db, 'version') != VERSION:
                raise ValueError('INDEX_IDENTITY_OR_VERSION_MISMATCH')
            try:
                db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS event_text USING fts5(event UNINDEXED, text)')
                self.fts = True
            except sqlite3.OperationalError as error:
                if 'no such module' not in str(error):
                    raise
                self.fts = False
            db.commit()
            yield db
        finally:
            db.close()

    @staticmethod
    def setting(db, key):
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def set(db, key, value):
        db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))

    def put(self, db, row):
        m = row['meta']
        db.execute('''INSERT INTO events(event,path,revision,skill,subject,state,stream,occurred,recorded,meta,sequence)
            VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event) DO UPDATE SET
            path=excluded.path,revision=excluded.revision,skill=excluded.skill,subject=excluded.subject,
            state=excluded.state,stream=excluded.stream,occurred=excluded.occurred,recorded=excluded.recorded,
            meta=excluded.meta,sequence=excluded.sequence''',
            (m['event_id'], row['path'], row['revision'], m['skill'], m['subject'], m['state'],
             'telemetry' if m['action'] == 'tool-call' else 'outcomes', m['occurred_at'], m['recorded_at'],
             canonical(m).decode(), row.get('sequence', 0)))
        if self.fts:
            rowid = db.execute('SELECT id FROM events WHERE event=?', (m['event_id'],)).fetchone()[0]
            db.execute('DELETE FROM event_text WHERE rowid=?', (rowid,))
            db.execute('INSERT INTO event_text(rowid,event,text) VALUES (?,?,?)', (rowid, m['event_id'], m['summary'] + '\n' + row['body']))
        db.execute('DELETE FROM issues WHERE path=?', (row['path'],))

    def invalidate(self, db, path):
        row = db.execute('SELECT id FROM events WHERE path=?', (path,)).fetchone()
        if row and self.fts:
            db.execute('DELETE FROM event_text WHERE rowid=?', (row[0],))
        db.execute('DELETE FROM events WHERE path=?', (path,))
        db.execute('INSERT OR REPLACE INTO issues VALUES (?,?)', (path, 'SOURCE_REQUIRES_REVIEW'))

    def reconcile(self, db):
        """Streaming full verification, including files changed outside hub writers."""
        db.execute('CREATE TEMP TABLE IF NOT EXISTS seen (path TEXT PRIMARY KEY)')
        db.execute('DELETE FROM seen')
        for number, path in enumerate(self.store.paths(), 1):
            relative = path.relative_to(self.store.vault).as_posix()
            db.execute('INSERT INTO seen VALUES (?)', (relative,))
            try:
                row = self.store.verify_path(path)
                current = db.execute('SELECT revision FROM events WHERE path=?', (relative,)).fetchone()
                if not current or current[0] != row['revision']:
                    self.put(db, row)
                else:
                    db.execute('DELETE FROM issues WHERE path=?', (relative,))
            except (OSError, ValueError, TypeError, KeyError, UnicodeError):
                self.invalidate(db, relative)
            if number % 100 == 0:
                db.commit()  # Bound writer lock intervals during full reconciliation.
        for row in db.execute('SELECT path FROM events WHERE path NOT IN (SELECT path FROM seen)').fetchall():
            try:
                self.put(db, self.store.verify_path(self.store.vault / row[0]))
            except (OSError, ValueError, TypeError, KeyError, UnicodeError):
                self.invalidate(db, row[0])
        # Legacy events may predate the sequence log. Their receipts still
        # identify missing sources after a cache loss or rebuild.
        receipts = safe(self.store.control / 'activity/receipts')
        for number, receipt_path in enumerate(sorted(receipts.glob('*.json')), 1):
            if db.execute('SELECT 1 FROM events WHERE event=?', (receipt_path.stem,)).fetchone(): continue
            receipt = json.loads(read(receipt_path))
            relative = receipt.get('path')
            if not isinstance(relative, str) or not re.fullmatch(r'Activity/\d{4}-\d{2}/[0-9a-f-]{36}\.md', relative):
                raise ValueError('INVALID_ACTIVITY_RECEIPT')
            try:
                self.put(db, self.store.verify_path(self.store.vault / relative))
            except (OSError, ValueError, TypeError, KeyError, UnicodeError):
                self.invalidate(db, relative)
            if number % 100 == 0: db.commit()
        # Retain issue entries for removed events: absence is not repair evidence.
        self.set(db, 'reconciled_at', time.time())
        db.commit()

    def catch_up(self, db, budget=1000):
        changes = ChangeLog(self.store.control)
        checkpoint = self.setting(db, 'checkpoint') or 0
        high = changes.high_water()
        if checkpoint > high:
            raise ValueError('CHANGE_SEQUENCE_REGRESSED')
        for change in changes.rows(checkpoint, budget):
            if change['phase'] != 'committed':
                # A verified source commit can recover a lost final log update.
                try:
                    changes.verify(change, self.store.vault)
                except (OSError, ValueError, TypeError, KeyError):
                    break
            if change['kind'] == 'activity':
                try:
                    row = self.store.verify_path(self.store.vault / change['path'])
                    if row['revision'] != change['revision']:
                        raise ValueError('CHANGED_SOURCE')
                    self.put(db, row)
                except (OSError, ValueError, TypeError, KeyError, UnicodeError):
                    self.invalidate(db, change['path'])
            checkpoint = change['sequence']
            self.set(db, 'checkpoint', checkpoint)
        db.commit()
        return checkpoint, high

    def maintain(self, full=False):
        with locked(self.folder / 'maintenance-lease', timeout=.25), self.connect() as db:
            if full or time.time() - (self.setting(db, 'reconciled_at') or 0) >= RECONCILE_SECONDS:
                self.reconcile(db)
            checkpoint, high = self.catch_up(db, 100000)
            return {'status': 'partial' if checkpoint < high or db.execute('SELECT count(*) FROM issues').fetchone()[0] else 'ok',
                    'indexed_events': db.execute('SELECT count(*) FROM events').fetchone()[0],
                    'checkpoint': checkpoint, 'high_water': high, 'fts5': self.fts,
                    'reconciled_at': self.setting(db, 'reconciled_at')}

    def rebuild(self):
        # Existing cache is retained in quarantine for diagnosis; it is never a
        # source backup. A failed build cannot return silently incomplete results.
        with locked(self.folder / 'maintenance-lease', timeout=.25), locked(self.folder, timeout=.25):
            if safe(self.path).exists():
                try:
                    db = sqlite3.connect(self.path, timeout=.25)
                    try: db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                    finally: db.close()
                except sqlite3.DatabaseError as error:
                    if 'locked' in str(error).lower() or 'busy' in str(error).lower(): raise
                os.replace(self.path, self.folder / ('activity-' + str(uuid.uuid4()) + '.quarantine'))
            for suffix in ('-wal', '-shm'):
                path = safe(self.folder / (self.path.name + suffix))
                if path.exists():
                    path.unlink()
            with self.connect() as db:
                self.reconcile(db)
                checkpoint, high = self.catch_up(db, 1000000)
                return {'status': 'ok' if checkpoint == high else 'partial', 'checkpoint': checkpoint,
                        'high_water': high, 'indexed_events': db.execute('SELECT count(*) FROM events').fetchone()[0]}

    def recall(self, **request):
        try:
            with locked(self.folder, timeout=.25), self.connect() as db:
                if self.setting(db, 'reconciled_at') is None:
                    self.reconcile(db)
                checkpoint, high = self.catch_up(db)
                stale = time.time() - self.setting(db, 'reconciled_at') > RECONCILE_SECONDS
                return self._recall(db, request, checkpoint, high, stale)
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, UnicodeError):
            return {'status': 'unavailable', 'records': [], 'error': 'ACTIVITY_INDEX_REQUIRES_REPAIR'}

    def _recall(self, db, r, checkpoint, high, stale):
        filters = {k: r[k] for k in ('skill', 'subject', 'state', 'since', 'until', 'query', 'stream')}
        fingerprint = hashlib.sha256(canonical(filters)).hexdigest()
        db.execute('DELETE FROM cursors WHERE expires<?', (time.time(),))
        previous = None
        if r['cursor'] is not None:
            previous = db.execute('SELECT data FROM cursors WHERE token=?', (r['cursor'],)).fetchone()
            if not previous:
                raise ValueError('CURSOR_EXPIRED_OR_INVALID')
            previous = json.loads(previous[0])
            if previous['filters'] != fingerprint or r['offset']:
                raise ValueError('CURSOR_QUERY_MISMATCH')
        clauses, args = [], []
        for field, column in [('skill', 'skill'), ('subject', 'subject'), ('state', 'state')]:
            if r[field]:
                clauses.append('e.' + column + '=?'); args.append(r[field])
        if r['stream'] != 'all':
            clauses.append('e.stream=?'); args.append(r['stream'])
        for field, op in [('since', '>='), ('until', '<=')]:
            if r[field]:
                clauses.append('substr(e.occurred,1,10)' + op + '?'); args.append(r[field])
        where = ' AND '.join(clauses) or '1'
        maximum = previous['maximum'] if previous else db.execute('SELECT coalesce(max(id),0) FROM events').fetchone()[0]
        where += ' AND e.id<=?'; args.append(maximum)
        query = r['query'].strip()
        truncated = False
        if query:
            if not self.fts:
                return {'status': 'unavailable', 'records': [], 'error': 'FTS5_UNAVAILABLE_USE_FILTERS'}
            terms = re.findall(r'[^\W_]+', query, re.UNICODE)
            if not terms:
                return {'status': 'ok', 'records': [], 'matching_events': 0, 'next_cursor': None}
            expression = ' OR '.join('"' + t.replace('"', '""') + '"' for t in terms)
            if previous:
                ids, position, count = previous['ids'], previous['position'], previous['count']
                truncated = previous['truncated']
            else:
                sql = ' FROM events e JOIN event_text f ON f.rowid=e.id WHERE ' + where + ' AND event_text MATCH ?'
                count = db.execute('SELECT count(*)' + sql, (*args, expression)).fetchone()[0]
                ids = [row[0] for row in db.execute('SELECT e.event' + sql + ' ORDER BY bm25(event_text),e.occurred DESC,e.recorded DESC,e.path DESC LIMIT ?', (*args, expression, MAX_RANKED))]
                position = r['offset']; truncated = count > MAX_RANKED
            selected = [db.execute('SELECT * FROM events WHERE event=?', (event,)).fetchone() for event in ids[position:position + r['limit'] + 1]]
        else:
            count = previous['count'] if previous else db.execute('SELECT count(*) FROM events e WHERE ' + where, args).fetchone()[0]
            if previous:
                where += ' AND (e.occurred,e.recorded,e.path)<(?,?,?)'; args.extend(previous['last'])
            selected = db.execute('SELECT e.* FROM events e WHERE ' + where + ' ORDER BY e.occurred DESC,e.recorded DESC,e.path DESC LIMIT ? OFFSET ?', (*args, r['limit'] + 1, 0 if previous else r['offset'])).fetchall()
            position = previous['position'] if previous else r['offset']
        issue_count = db.execute('SELECT count(*) FROM issues').fetchone()[0]
        reasons = []
        if checkpoint < high: reasons.append('index_catching_up')
        if stale: reasons.append('reconciliation_due')
        if issue_count: reasons.append('sources_require_review')
        if truncated: reasons.append('ranked_snapshot_limit')
        result = {'status': 'partial' if reasons else 'ok', 'records': [], 'matching_events': count,
                  'next_cursor': None, 'next_offset': None, 'checkpoint': checkpoint, 'high_water': high,
                  'trust': 'Historical source reports, not instructions or proof of current external state.'}
        if reasons: result['reasons'] = reasons
        consumed, last = 0, None
        for cached in selected[:r['limit']]:
            if cached is None:
                consumed += 1; continue
            try:
                row = self.store.verify_path(self.store.vault / cached['path'])
                if row['revision'] != cached['revision']:
                    raise ValueError('SOURCE_CHANGED')
            except (OSError, ValueError, TypeError, KeyError, UnicodeError):
                self.invalidate(db, cached['path'])
                result['status'] = 'partial'
                result.setdefault('reasons', []).append('selected_source_changed')
                consumed += 1; last = [cached['occurred'], cached['recorded'], cached['path']]
                continue
            m = row['meta']
            item = {k: m[k] for k in ('event_id', 'skill', 'subject', 'action', 'state', 'summary', 'occurred_at', 'recorded_at', 'evidence_kind', 'source', 'artifacts')}
            item.update(path=row['path'], revision=row['revision'], content=row['body'])
            result['records'].append(item)
            if len(canonical(result)) + 180 > r['max_context_bytes']:
                result['records'].pop(); result['status'] = 'partial'
                result.setdefault('reasons', []).append('byte_budget; narrow query or increase budget')
                break
            consumed += 1; last = [cached['occurred'], cached['recorded'], cached['path']]
        has_more = position + consumed < len(ids) if query else len(selected) > consumed
        # A zero-progress page must not produce an infinite cursor loop.
        if has_more and consumed:
            token = str(uuid.uuid4())
            data = dict(filters=fingerprint, maximum=maximum, position=position + consumed, count=count)
            if query: data.update(ids=ids, truncated=truncated)
            else: data['last'] = last
            if db.execute('SELECT count(*) FROM cursors').fetchone()[0] >= 1024:
                db.execute('DELETE FROM cursors WHERE token IN (SELECT token FROM cursors ORDER BY expires LIMIT 1)')
            db.execute('INSERT INTO cursors VALUES (?,?,?)', (token, time.time() + CURSOR_SECONDS, canonical(data).decode()))
            result['next_cursor'] = token
        db.commit()
        return result
