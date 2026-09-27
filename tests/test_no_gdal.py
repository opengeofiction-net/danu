"""danu.core.profile must import without GDAL.

The CI comment claimed this before it was true. Both test modules imported
danu.checks.rivers and danu.water.constraints, which import osgeo at module
level, so every run of the tests job failed with ModuleNotFoundError and the
badge was red from the first push - unnoticed, because the tests passed on a
laptop that has GDAL.

The property is worth having: it is what lets the suite run on Windows, where
GDAL is not reasonably installable from PyPI, and it keeps the functions which
decide what a contour means separable from the ones which read rasters. So it
is asserted rather than asserted-in-a-comment.
"""

import builtins



def test_profile_imports_without_gdal(monkeypatch):
    real = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.split('.')[0] == 'osgeo':
            raise ModuleNotFoundError(f"No module named '{name}'")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', blocked)
    for mod in ('danu.core.profile', 'danu.core.square'):
        monkeypatch.delitem(__import__('sys').modules, mod, raising=False)
        importlib = __import__('importlib')
        importlib.import_module(mod)


def test_the_pure_modules_import_no_raster_ui_or_network_library():
    """Checked on the import statements, not the prose: a docstring is allowed
    to say why pyosmium is not used here, and a test that forbids the word
    forbids the explanation."""
    import ast
    import pathlib
    banned = ('osgeo', 'osmium', 'PySide6', 'PyQt6', 'urllib', 'requests', 'numpy')
    for name in ('profile', 'square'):
        src = pathlib.Path(__file__).parents[1] / 'danu' / 'core' / f'{name}.py'
        tree = ast.parse(src.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or '']
            else:
                continue
            for n in names:
                # profile is arithmetic over arrays and is allowed numpy;
                # square is not, so the model stays importable anywhere
                assert n.split('.')[0] not in banned or (name == 'profile' and n == 'numpy'), \
                    f'danu.core.{name} imports {n}'


def test_the_linter_is_configured_and_runs_here():
    """Ruff's config lives in pyproject and the CI job runs `ruff check .`, so
    a developer and the runner have to be asking the same question.

    Forty-five unused imports had accumulated across nineteen files with
    nothing watching, five of them in the commit that noticed. This is what
    makes the config the contract rather than a habit.
    """
    import tomllib
    from pathlib import Path

    root = Path(__file__).parents[1]
    conf = tomllib.loads((root / 'pyproject.toml').read_text())
    rules = conf['tool']['ruff']['lint']['select']
    assert 'F' in rules, 'pyflakes is the reason the linter is here'
    assert 'E402' in rules, (
        'E402 is selected because 97 `# noqa: E402` comments are already '
        'written against it; without the rule they say nothing')
    assert 'ruff>=0.16' in conf['project']['optional-dependencies']['dev']

    workflow = (root / '.github' / 'workflows' / 'ci.yml').read_text()
    assert 'ruff check .' in workflow, 'the CI job does not run the linter'
    assert '  lint:' in workflow
