"""zipapp entry point: ``python3 -m zipapp src/tectdist -o dist/tectdist``."""

import sys

from tectdist.dispatcher import main

if __name__ == "__main__":
    sys.exit(main())
