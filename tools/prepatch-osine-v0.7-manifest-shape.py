#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: prepatch-osine-v0.7-manifest-shape.py <project-dir>")

project = Path(sys.argv[1]).resolve()
manifest = project / "app/src/main/AndroidManifest.xml"
text = manifest.read_text(encoding="utf-8")


def normalize_opening_tag(source: str, tag: str, component_name: str) -> str:
    pattern = re.compile(rf'<{tag}\b(?P<attrs>[^>]*)>', re.S)
    for match in pattern.finditer(source):
        attrs = match.group("attrs")
        name_token = f'android:name="{component_name}"'
        if name_token not in attrs:
            continue

        name_pattern = re.compile(
            r'\s*android:name\s*=\s*"' + re.escape(component_name) + r'"'
        )
        remaining = name_pattern.sub("", attrs, count=1).strip()

        replacement = f'<{tag}\n            android:name="{component_name}"'
        if remaining:
            replacement += " " + remaining
        replacement += ">"

        return source[:match.start()] + replacement + source[match.end():]

    raise SystemExit(f"{manifest}: <{tag}> for {component_name} missing")


text = normalize_opening_tag(text, "receiver", ".ListenerRecoveryReceiver")
text = normalize_opening_tag(text, "service", ".OsineKeepAliveService")
manifest.write_text(text, encoding="utf-8")

print("Normalized osine v0.7 manifest opening tags for Direct-Boot patcher")
