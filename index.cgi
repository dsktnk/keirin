#!/usr/local/bin/python
# Sakura single-directory edition: place this file directly inside ~/www/keirin/
import os
import sys
from pathlib import Path
ROOT = Path(os.environ.get('KEIRIN_LAB_ROOT', str(Path(__file__).resolve().parent))).resolve()
sys.path.insert(0, str(ROOT / 'src'))
from keirinlab.webapp import main
if __name__ == '__main__':
    main(root_override=ROOT)
