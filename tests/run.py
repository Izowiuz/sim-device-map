#!/usr/bin/env python3
"""Every test in this directory.

    ./tests/run.py              all of them
    ./tests/run.py writer       only these
    ./tests/run.py -v           and say what each one was

Stdlib `unittest` and nothing else, because the rest of the repo takes no
dependencies either.

Nothing here opens `/dev/input`. The hardware arrives as dicts from `fake.py`
-- a suite that needs the author's own stick plugged in is a suite that runs
on one machine.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for path in (REPO, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    verbose = any(a in ('-v', '--verbose') for a in sys.argv[1:])

    loader = unittest.TestLoader()
    if args:
        suite = unittest.TestSuite(
            loader.loadTestsFromName(a if a.startswith('test_')
                                     else f'test_{a}') for a in args)
    else:
        suite = loader.discover(HERE, pattern='test_*.py', top_level_dir=HERE)

    result = unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
