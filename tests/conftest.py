from __future__ import annotations

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Keep source-checkout subprocess tests on the same import boundary as pytest.
# Updating sys.path alone affects only this process, so child Python processes
# otherwise fail to import the src-layout package unless it was preinstalled.
pythonpath = [str(SRC)]
pythonpath.extend(filter(None, os.environ.get("PYTHONPATH", "").split(os.pathsep)))
os.environ["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(pythonpath))
