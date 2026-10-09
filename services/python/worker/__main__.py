"""services/python/worker/__main__.py

Standalone entrypoint for running the durable job worker as a module:
python -m services.python.worker [options]
"""

import sys
from services.python.worker.main import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
