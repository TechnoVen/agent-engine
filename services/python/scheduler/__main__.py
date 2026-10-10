"""services/python/scheduler/__main__.py

Standalone entrypoint for running the timezone-aware scheduler as a module:
python -m services.python.scheduler [options]
"""

import sys
from services.python.scheduler.main import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
