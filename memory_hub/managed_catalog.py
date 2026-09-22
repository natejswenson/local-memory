"""Durable general-record membership, independent of rebuildable search indexes."""
from datetime import date
import hashlib
import json
import uuid

from .serialization import canonical, load_yaml
from .skill_store import atomic, read, safe

FIELDS = ('title', 'type', 'project', 'status', 'source', 'capture_id', 'permalink', 'key', 'supersedes')
STRUCTURE = ('type', 'project', 'status', 'capture_id', 'permalink', 'key', 'supersedes')


class ManagedCatalog:
    def __init__(self, vault, control):
        self.vault, self.control = safe(vault), safe(control)
        self.path = self.control / 'managed-records/catalog.json'

    def load(self):
        value = json.loads(read(self.path, 8 * 1024 * 1024))
        if (value.get('schema_version') != 1 or value.get('vault') != str(self.vault)
                or not isinstance(value.get('records'), dict) or len(value['records']) > 2000):
            raise ValueError('MANAGED_CATALOG_INVALID')
        for path, entry in value['records'].items():
            if path.startswith('/') or '..' in path.split('/') or not path.endswith('.md'):
                raise ValueError('MANAGED_CATALOG_PATH_INVALID')
            if (not isinstance(entry.get('meta'), dict) or any(not isinstance(entry['meta'].get(key), str) or not entry['meta'][key].strip() for key in FIELDS[:7])
                    or ('key' in entry['meta'] and (not isinstance(entry['meta']['key'], str) or not entry['meta']['key']))):
                raise ValueError('MANAGED_CATALOG_IDENTITY_INVALID')
        return value

    def preview(self):
        from .recall import scan, eligible, resolve
        from collections import defaultdict
        issues = []
        rows = scan(self.vault, issues=issues, use_catalog=False)
        records, groups = {}, defaultdict(list)
        for row in rows:
            if eligible(row, date.min) is not None:
                issues.append({'path': row['path'], 'reason': 'unmanaged_or_invalid_metadata'})
                continue
            m = row['meta']
            records[row['path']] = {'meta': {k: m[k] for k in FIELDS if k in m}, 'adopted_revision': row['revision']}
            if m.get('status') == 'active' and m.get('key'):
                groups[(m['project'], m['key'])].append(row)
        blockers = []
        for group in groups.values():
            try:
                resolve(group)
            except (ValueError, TypeError):
                blockers.append({'path': group[0]['path'], 'reason': 'correction_chain_requires_review'})
        receipts = safe(self.control / 'receipts')
        if receipts.exists():
            for path in sorted(receipts.glob('*.json')):
                receipt = json.loads(read(path))
                if receipt.get('phase') != 'committed' or receipt.get('path') not in records:
                    blockers.append({'path': receipt.get('path'), 'reason': 'receipt_without_valid_managed_source'})
        value = {'schema_version': 1, 'vault': str(self.vault), 'records': records}
        return {'status': 'blocked' if blockers else 'ready', 'catalog': value,
                'unmanaged': issues, 'blockers': blockers,
                'plan_hash': hashlib.sha256(canonical(value)).hexdigest()}

    def adopt(self, expected_plan_hash):
        from .capture import locked
        from .writer_gate import check_writer
        with locked(self.control):
            check_writer(self.control)
            if safe(self.path).exists():
                raise ValueError('CATALOG_ALREADY_EXISTS_USE_EXPLICIT_REPAIR')
            plan = self.preview()
            if plan['status'] != 'ready' or plan['plan_hash'] != expected_plan_hash:
                raise ValueError('CATALOG_PLAN_STALE_OR_BLOCKED')
            atomic(self.path, canonical(plan['catalog']))
            return {'status': 'adopted', 'records': len(plan['catalog']['records']), 'plan_hash': expected_plan_hash}

    def register(self, path, meta, revision):
        """Called under writer lock before publication. Missing files remain members."""
        value = self.load()
        entry = {'meta': {k: meta[k] for k in FIELDS if k in meta}, 'adopted_revision': revision}
        existing = value['records'].get(path)
        if existing is not None and existing != entry:
            raise ValueError('MANAGED_IDENTITY_CONFLICT')
        value['records'][path] = entry
        atomic(self.path, canonical(value))

    def scan(self, issues=None):
        rows, total = [], 0
        for relative, entry in sorted(self.load()['records'].items()):
            expected = entry['meta']
            reason = None
            try:
                raw = read(self.vault / relative, 65536)
                total += len(raw)
                if total > 16 * 1024 * 1024:
                    raise ValueError('CATALOG_CAPACITY')
                front, body = raw.decode()[4:].split('\n---\n', 1)
                if not raw.startswith(b'---\n'):
                    raise ValueError('MALFORMED_MANAGED_NOTE')
                meta = load_yaml(front)
                if not isinstance(meta, dict) or any(meta.get(k) != expected.get(k) for k in STRUCTURE):
                    raise ValueError('MANAGED_METADATA_DRIFT')
                rows.append(dict(meta=meta, body=body.strip(), path=relative, revision=hashlib.sha256(raw).hexdigest()))
                continue
            except Exception as error:
                # Only source parsing/read errors are converted to tombstones.
                import yaml
                if not isinstance(error, (OSError, ValueError, TypeError, UnicodeError, yaml.YAMLError)):
                    raise
                if str(error) == 'CATALOG_CAPACITY': raise
                reason = 'managed_source_requires_review'
            if issues is not None:
                issues.append({'path': relative, 'reason': reason})
            # Preserve correction membership. A damaged terminal can never make
            # a surviving predecessor look current, even after cache rebuild.
            rows.append(dict(meta=dict(expected), body='', path=relative,
                             revision=entry['adopted_revision'], invalid=reason))
        return rows
