#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: hotfix-osine-v0.10-ci.py <project-dir>')

project = Path(sys.argv[1]).resolve()
activity = project / 'app' / 'src' / 'main' / 'java' / 'com' / 'randotone' / 'app' / 'MainActivity.kt'
text = activity.read_text(encoding='utf-8')

needed = 'import androidx.compose.foundation.layout.fillMaxHeight\n'
if needed not in text:
    anchor = 'import androidx.compose.foundation.layout.fillMaxWidth\n'
    if anchor not in text:
        raise SystemExit(f'{activity}: fillMaxWidth import anchor missing')
    text = text.replace(anchor, anchor + needed, 1)
    activity.write_text(text, encoding='utf-8')

print('Applied osine v0.10 missing fillMaxHeight import hotfix')
