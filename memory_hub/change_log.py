"""Durable ordered source commits. Call prepare/commit under the source writer lock."""
import hashlib
import json
from .serialization import canonical
from .skill_store import atomic, read, safe


class ChangeLog:
    def __init__(self, control):
        self.control = safe(control)
        self.folder = self.control / 'changes'
        self.counter = self.folder / 'sequence.json'

    def high_water(self):
        if not safe(self.counter).exists():
            return 0
        value = json.loads(read(self.counter))
        if value.get('version') != 1 or type(value.get('sequence')) is not int or value['sequence'] < 0:
            raise ValueError('INVALID_CHANGE_SEQUENCE')
        return value['sequence']

    def path(self, sequence):
        if type(sequence) is not int or sequence < 1:
            raise ValueError('INVALID_CHANGE_SEQUENCE')
        return self.folder / 'records' / f'{sequence:020}.json'

    def prepare(self, kind, identity, path, revision, receipt):
        if kind not in {'activity', 'general'}:
            raise ValueError('INVALID_CHANGE_KIND')
        sequence = self.high_water() + 1
        row = dict(version=1, sequence=sequence, kind=kind, identity=identity, path=path,
                   revision=revision, receipt=receipt, phase='pending')
        # A crash before counter publication leaves an orphan at the next slot.
        # Never overwrite it: recovery must reconcile it first.
        destination = self.path(sequence)
        if safe(destination).exists():
            existing = json.loads(read(destination))
            if existing != row:
                raise ValueError('CHANGE_ORPHAN_REQUIRES_RECOVERY')
        else:
            atomic(destination, canonical(row))
        atomic(self.counter, canonical({'version': 1, 'sequence': sequence}))
        return sequence

    def committed(self, sequence):
        path = self.path(sequence)
        row = json.loads(read(path))
        row['phase'] = 'committed'
        atomic(path, canonical(row))

    def rows(self, after=0, limit=1000):
        high = self.high_water()
        for sequence in range(after + 1, min(high, after + limit) + 1):
            row = json.loads(read(self.path(sequence)))
            if row.get('sequence') != sequence or row.get('version') != 1:
                raise ValueError('INVALID_CHANGE_RECORD')
            yield row

    def verify(self, row, vault):
        relative = row['path']
        if relative.startswith('/') or '..' in relative.split('/'):
            raise ValueError('INVALID_CHANGE_PATH')
        receipt_path = row['receipt']
        if receipt_path.startswith('/') or '..' in receipt_path.split('/'):
            raise ValueError('INVALID_CHANGE_RECEIPT')
        receipt = json.loads(read(self.control / receipt_path))
        raw = read(vault / relative, 65536)
        if (receipt.get('phase') != 'committed' or receipt.get('path') != relative
                or receipt.get('content_sha256') != row['revision']
                or hashlib.sha256(raw).hexdigest() != row['revision']):
            raise ValueError('UNCOMMITTED_OR_CHANGED_SOURCE')
        return True

    def recover(self, vault, apply=False, expected_plan_hash=None):
        """Commit only provable publications; unresolved intents remain blockers."""
        from .capture import locked
        with locked(self.control):
            candidates, blockers = [], []
            high = self.high_water()
            orphan = self.path(high + 1)
            rows = list(self.rows(0, high))
            if safe(orphan).exists(): rows.append(json.loads(read(orphan)))
            for row in rows:
                if row.get('phase') == 'committed': continue
                try:
                    self.verify(row, vault)
                    candidates.append(row['sequence'])
                except (OSError, ValueError, KeyError, TypeError):
                    blockers.append(row['sequence'])
            plan = dict(candidates=candidates, blockers=blockers, high_water=high)
            plan['plan_hash'] = hashlib.sha256(canonical(plan)).hexdigest()
            if apply:
                if expected_plan_hash != plan['plan_hash']: raise ValueError('RECOVERY_PLAN_STALE')
                for sequence in candidates:
                    self.committed(sequence)
                    if sequence > high:
                        atomic(self.counter, canonical({'version': 1, 'sequence': sequence}))
            return dict(status='partial' if blockers else 'ok', applied=apply, **plan)
