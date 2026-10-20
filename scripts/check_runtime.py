"""Check installed runtime requirements without downloading anything."""
import importlib
from importlib import metadata
from pathlib import Path
import sys


def main():
    if not (3, 11) <= sys.version_info[:2] <= (3, 13) or sys.maxsize <= 2**32:
        print('A 64-bit Python 3.11-3.13 environment is required.')
        return 1
    try:
        from packaging.requirements import Requirement
        requirements = Path(__file__).resolve().parents[1] / 'backend' / 'requirements.txt'
        for line in requirements.read_text(encoding='utf-8-sig').splitlines():
            line = line.split('#', 1)[0].strip()
            if not line:
                continue
            req = Requirement(line)
            if req.marker and not req.marker.evaluate():
                continue
            installed = metadata.version(req.name)
            if not req.specifier.contains(installed, prereleases=True):
                raise RuntimeError(f'{req.name}: installed {installed}, required {req.specifier}')
        for module in ('uvicorn', 'fastapi', 'multipart', 'cryptography', 'geopandas',
                       'rasterio', 'pyproj', 'pyarrow', 'langgraph', 'langchain_openai'):
            importlib.import_module(module)
        # Scrapling exposes Fetcher lazily; importing scrapling.fetchers alone can
        # succeed even when its required fetcher backend (for example curl_cffi) is absent.
        fetchers = importlib.import_module('scrapling.fetchers')
        getattr(fetchers, 'Fetcher')
    except Exception as exc:
        print(f'Runtime needs installation or repair: {exc}')
        return 1
    print('Runtime dependencies are ready.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
