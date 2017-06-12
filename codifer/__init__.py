from codifer._flake8 import Collected, Source, make_collector
from codifer._version import get_versions


__version__ = get_versions()['version']
del get_versions


__all__ = (
    '__version__',
)
