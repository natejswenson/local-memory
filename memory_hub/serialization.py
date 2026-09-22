"""Shared safe decoding; never use YAML constructors that execute objects."""
import json
import yaml

YAML_LOADER = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)


def load_yaml(value):
    return yaml.load(value, Loader=YAML_LOADER)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
