"""Agent Engine Python Sidecar module entrypoint."""

import sys
from services.python.server.api import main

if __name__ == "__main__":
    main(sys.argv[1:])
