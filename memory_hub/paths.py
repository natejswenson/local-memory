"""Explicit installation paths. A worktree never implicitly selects a live vault."""
from dataclasses import dataclass
import json
from pathlib import Path
from .skill_store import read, safe


@dataclass(frozen=True)
class HubPaths:
    root: Path
    pilot: bool = False

    def __post_init__(self):
        object.__setattr__(self, 'root', safe(self.root))

    @property
    def state(self):
        return self.root / '.runtime' / ('pilot' if self.pilot else 'live')

    @property
    def vault(self):
        return self.state / 'vault' if self.pilot else self.root / 'vault'

    @property
    def runtime(self):
        return self.state if self.pilot else self.root / '.runtime'

    @property
    def control(self):
        return self.runtime / 'general-memory'

    @property
    def skill_control(self):
        return self.runtime / 'skill-memory'

    @property
    def index(self):
        return self.runtime / 'indexes' / 'activity-v1.sqlite'

    def readiness(self):
        if not safe(self.vault).is_dir():
            return {'ready': False, 'activation': 'disabled'}
        if self.pilot:
            return {'ready': True, 'activation': 'synthetic'}
        try:
            value = json.loads(read(self.state / 'activation.json'))
            ready = value.get('desktop_verified') is True and value.get('vault') == str(self.vault)
            return {'ready': ready, 'activation': 'live' if ready else 'invalid'}
        except FileNotFoundError:
            return {'ready': False, 'activation': 'disabled'}
        except (OSError, ValueError, TypeError):
            return {'ready': False, 'activation': 'invalid'}

    def require_ready(self):
        if not self.readiness()['ready']:
            raise ValueError('MEMORY_NOT_ACTIVATED')


def control_for(vault):
    """Matches existing live layout and the isolated pilot's control layout."""
    vault = safe(vault)
    if vault.parent.name == 'pilot' and vault.parent.parent.name == '.runtime':
        return vault.parent / 'general-memory'
    return vault.parent / '.runtime/general-memory'
