"""Fuzz the failure classifier with arbitrary provider messages.

``classify()`` reads text that providers write, so it sees whatever a remote
API cares to send back. A crash there would turn one odd error into a failed
request instead of a failover, and a mis-ordered verdict would disable a
working member. Run with ``python fuzz/fuzz_classify.py -runs=200000``.
"""

import importlib.util
import sys
from pathlib import Path

import atheris

# Loaded by path: importing the package would run its __init__, which needs
# Home Assistant, while errors.py is deliberately free of it.
_ERRORS = Path(__file__).parent.parent / "custom_components/ai_pool/errors.py"

_spec = importlib.util.spec_from_file_location("ai_pool_errors", _ERRORS)
assert _spec is not None and _spec.loader is not None
errors = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = errors
_spec.loader.exec_module(errors)
# instrument_imports() only sees the import statement, which a by-path load
# bypasses: the fuzzer then ran blind on a one-byte corpus.
atheris.instrument_func(errors.classify)

_QUOTA = dict(errors._PATTERNS)[errors.FailureKind.QUOTA]


def test_one_input(data: bytes) -> None:
    """Check the classifier's contract on one message."""
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())

    verdict = errors.classify(text)
    assert isinstance(verdict.kind, errors.FailureKind)
    assert verdict.message == text.strip()
    # Spent allowances arrive as 403 too; quota evidence must outrank AUTH, the
    # one verdict that disables a member for good.
    if _QUOTA.search(text):
        assert verdict.kind is errors.FailureKind.QUOTA, text
        assert not verdict.is_permanent

    # The exception path must agree with the bare-message path, except for the
    # empty message, which falls back to the exception's type name.
    from_exc = errors.classify(RuntimeError(text))
    if text.strip():
        assert from_exc == verdict


def main() -> None:
    """Run the fuzzer."""
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
