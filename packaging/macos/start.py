"""The editor started with Python's fault handler on from the first line - a
fault before Danu's own reporter is installed says where it was. Run through
the launcher, `Danu --python start.py`, for the app's check when it fails."""

import faulthandler
import sys

faulthandler.enable(all_threads=True)
from danu.ui.app import main  # noqa: E402

sys.exit(main(['danu', *sys.argv[1:]]))
