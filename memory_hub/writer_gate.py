"""Compatibility fence, checked on every mutation, including long-lived clients."""
import json
from .skill_store import read, safe

WRITER_VERSION = 2


def check_writer(control):
    path = safe(control / 'writer-version.json')
    if path.exists():
        value = json.loads(read(path))
        if (value.get('schema_version') != 1
                or type(value.get('minimum_writer_version')) is not int
                or value['minimum_writer_version'] > WRITER_VERSION
                or value.get('maintenance', False)):
            raise ValueError('WRITER_UPGRADE_OR_MAINTENANCE_REQUIRED')


def features(control):
    path = safe(control / 'features.json')
    if not path.exists():
        return {}
    value = json.loads(read(path))
    allowed = {'schema_version', 'activity_index', 'deferred_views', 'managed_catalog'}
    if (not isinstance(value, dict) or value.get('schema_version') != 1 or set(value) - allowed
            or any(type(v) is not bool for k, v in value.items() if k != 'schema_version')):
        raise ValueError('INVALID_FEATURE_CONFIGURATION')
    return value
