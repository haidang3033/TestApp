#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: hotfix-osine-v0.6-ci.py <project-dir>")

project = Path(sys.argv[1]).resolve()
listener = project / "app/src/main/java/com/randotone/app/RandoToneNotificationListener.kt"
text = listener.read_text(encoding="utf-8")

old = "if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N)"
new = "if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.N)"
count = text.count(old)
if count != 1:
    raise SystemExit(f"{listener}: expected exactly one v0.6 Build guard, found {count}")

listener.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Applied osine v0.6 missing-Build-reference CI hotfix")
