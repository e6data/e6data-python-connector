"""Packaging and safe collection contracts; no live services or test doubles."""
import ast
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_optional_async_dependencies_do_not_raise_base_python_floor():
    tree = ast.parse((ROOT / 'setup.py').read_text())
    setup = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == 'setup')
    keywords = {arg.arg: arg.value for arg in setup.keywords}
    assert 'extras_require' in keywords, 'Async dependencies must be optional extras'
    extras = ast.literal_eval(keywords['extras_require'])
    assert 'httpx>=0.28.1,<1' in extras['async']
    assert 'SQLAlchemy[asyncio]>=2.0,<2.1' in extras['async-sqlalchemy']
    assert 'python_requires' not in keywords


def test_manifest_accounts_for_every_existing_test_and_utility():
    path = ROOT / 'test' / 'collection_manifest.json'
    assert path.exists(), 'All historical test and utility modules need explicit classification'
    manifest = json.loads(path.read_text())
    tracked = subprocess.check_output(['git', 'ls-files', '*.py'], cwd=ROOT, text=True).splitlines()
    # The manifest inventories historical scripts. New suites have explicit
    # unit/integration directories and an import-safe fixture module.
    expected = {name for name in tracked
                if (name.startswith('test/') or name.startswith('test_'))
                and not name.startswith(('test/unit/', 'test/integration/'))
                and name != 'test/conftest.py'}
    assert expected <= set(manifest['files'])
    assert {'offline', 'synthetic', 'integration', 'utility'} >= {
        value['kind'] for value in manifest['files'].values()}
    for name in ('test/cleanup_test_files.py', 'test/move_tests.py'):
        assert manifest['files'][name]['kind'] == 'utility'


def test_base_import_keeps_existing_exports_and_does_not_load_httpx():
    code = ('import sys; import e6data_python_connector as c; '
            'assert c.__all__ == ["Connection", "Cursor", "ConnectionPool"]; '
            'assert "httpx" not in sys.modules')
    subprocess.run([sys.executable, '-c', code], cwd=ROOT, check=True)


def test_async_entrypoint_exports_and_factory_use_native_connection():
    import asyncio
    import grpc
    import pytest
    from e6data_python_connector import aio
    for name in aio.__all__:
        assert callable(getattr(aio, name))
    with pytest.raises(AttributeError):
        getattr(aio, 'unsupported_public_name')
    async def run():
        connection = await aio.connect('localhost', 1, username='unit-user', password='unit-input')
        try:
            assert isinstance(connection._channel, grpc.aio.Channel)
            assert connection.check_connection()
        finally:
            await connection.close()
    asyncio.run(run())
