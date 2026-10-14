"""Child-process fixture loading without adding production source to sys.path."""

FIXTURE_BOOTSTRAP = """
import importlib.util
import sys
import sysconfig
from pathlib import Path

def load_isolated_fixture_module(fixture_file):
    import adaptive_replay
    installed = Path(adaptive_replay.__file__).resolve()
    sites = {Path(sysconfig.get_path(kind)).resolve() for kind in ('purelib', 'platlib')}
    if not any(site in installed.parents for site in sites):
        raise RuntimeError('recovery child requires the non-editable installed replay wheel')
    fixture_file = Path(fixture_file).resolve()
    package = '_kairos_isolated_recovery_fixtures'
    spec = importlib.util.spec_from_file_location(
        package, fixture_file.parent / '__init__.py',
        submodule_search_locations=[str(fixture_file.parent)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError('missing private fixture package')
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    name = package + '.' + fixture_file.stem
    spec = importlib.util.spec_from_file_location(name, fixture_file)
    if spec is None or spec.loader is None:
        raise RuntimeError('missing recovery fixture module')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
"""
