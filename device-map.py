#!/usr/bin/env python3
"""Run the capture tool: `./device-map.py`, or by a link from your PATH.

    ./device-map.py            the full-screen walk
    ./device-map.py --list     what is known, then exit
    ./device-map.py --raw      every event, live

The command sits beside the library it runs, the way `bind-wizard.py` sits
beside `core/` in sim-bind-wizard. The hyphen and the extension are what
let it: `devicemap` itself is the package, and a directory and a file
cannot share one name in one directory. `import devicemap` is what the six
games read, so the package is the half that keeps the plain name.

`realpath` rather than `dirname`, so a symbolic link to this from a
directory on your PATH still finds the repo it belongs to.
"""
import os
import sys

ROOT = os.path.dirname(os.path.realpath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from devicemap import capture                              # noqa: E402

if __name__ == '__main__':
    sys.exit(capture.main())
