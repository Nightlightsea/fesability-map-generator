"""Run the program from inside this folder: `python run.py [options]`.

Works whatever the folder is called and wherever it sits (that is why this
file exists: `python -m feasibility_map` only works when the folder is named
`feasibility_map` and cwd is its parent).  Options are the same; see
README.md, e.g. `python run.py --only LHR,comb`.
"""
import importlib
import importlib.util
import os
import sys


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    name = os.path.basename(here)
    if not name.isidentifier():
        name = "_feasibility_map_local"
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(here, "__init__.py"),
        submodule_search_locations=[here])
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[name] = pkg
    spec.loader.exec_module(pkg)
    return importlib.import_module(name + ".__main__").main()


if __name__ == "__main__":
    sys.exit(main())
