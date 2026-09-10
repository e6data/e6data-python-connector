"""Explicit collection boundary for historical scripts and real-service suites."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
MANIFEST = json.loads((ROOT / 'test' / 'collection_manifest.json').read_text())['files']


def pytest_addoption(parser):
    parser.addoption('--integration-config', help='Path to an explicit real-service test configuration')
    parser.addoption('--legacy-integration', action='store_true', default=False,
                     help='Also collect historical integration scripts after supplying their documented environment')


def pytest_configure(config):
    if config.getoption('--legacy-integration') and not config.getoption('--integration-config'):
        raise pytest.UsageError('--legacy-integration requires --integration-config')


def pytest_ignore_collect(collection_path, config):
    try:
        name = collection_path.relative_to(ROOT).as_posix()
    except ValueError:
        return None
    entry = MANIFEST.get(name)
    if entry is None:
        return None
    if entry['kind'] == 'utility' or entry.get('runner') == 'manual':
        return True
    if entry['kind'] == 'integration' and not config.getoption('--legacy-integration'):
        return True
    return None


def pytest_collection_modifyitems(config, items):
    for item in items:
        name = item.path.relative_to(ROOT).as_posix()
        entry = MANIFEST.get(name, {})
        if entry.get('kind') == 'synthetic':
            item.add_marker(pytest.mark.synthetic)
        if name.startswith('test/integration/') or entry.get('kind') == 'integration':
            item.add_marker(pytest.mark.integration)
            if not config.getoption('--integration-config'):
                item.add_marker(pytest.mark.skip(reason='Real-service qualification requires --integration-config'))


def pytest_report_header(config):
    excluded = sum(entry['kind'] in ('integration', 'utility') or entry.get('runner') == 'manual'
                   for entry in MANIFEST.values())
    return ('Historical test inventory: %d classified modules; %d real-service/manual/utility modules '
            'outside default collection. See test/collection_manifest.json; offline success is not live qualification.'
            % (len(MANIFEST), excluded))
