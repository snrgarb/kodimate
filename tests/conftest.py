import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Fakes first so `import xbmc` etc. resolve to the hand-written stubs.
sys.path.insert(0, os.path.join(_ROOT, 'tests', 'fakes'))
sys.path.insert(0, os.path.join(_ROOT, 'resources', 'lib'))
