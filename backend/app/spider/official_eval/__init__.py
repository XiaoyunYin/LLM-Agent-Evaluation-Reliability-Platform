"""Vendored copy of the official Spider test-suite evaluator.

Fetched by `scripts/download_spider.py` from `taoyds/test-suite-sql-eval` and
pinned by per-file sha256 in `datasets/spider/PIN.json`. Do not edit these files:
the point of vendoring is that SQL result-comparison semantics (row order,
duplicate rows, column permutation) match the published implementation exactly
rather than being re-derived here.

The upstream files use flat imports (`from parse import ...`) because they are
written to be run as scripts from their own directory. Rather than patching the
vendored source, this loads them under their bare module names from this
directory, which keeps the files byte-identical to what the sha256 pins describe.
"""

from __future__ import annotations

import importlib.util
import sys
import warnings
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# Load order matters: exec_eval imports parse at module scope.
_VENDORED_MODULES = ("parse", "exec_eval")


def _load_vendored(name: str):
    if name in sys.modules:
        return sys.modules[name]

    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load vendored evaluator module {name!r}")

    module = importlib.util.module_from_spec(spec)
    # Registered before exec so the vendored `from parse import ...` resolves to
    # this copy and not to some unrelated `parse` on sys.path.
    sys.modules[name] = module
    with warnings.catch_warnings():
        # The upstream files predate Python 3.12's SyntaxWarning for unescaped
        # regex sequences. Silenced rather than fixed: editing vendored source
        # would break the sha256 pins that prove which evaluator ran.
        warnings.simplefilter("ignore", SyntaxWarning)
        spec.loader.exec_module(module)
    return module


for _name in _VENDORED_MODULES:
    _load_vendored(_name)

from exec_eval import eval_exec_match, result_eq  # noqa: E402

__all__ = ["eval_exec_match", "result_eq"]
