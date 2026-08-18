#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: hotfix-osine-v0.4-ci.py <project-dir>")

project = Path(sys.argv[1]).resolve()
listener = project / "app/src/main/java/com/randotone/app/RandoToneNotificationListener.kt"
text = listener.read_text(encoding="utf-8")

marker = "    override fun onListenerConnected() {"
if marker not in text:
    raise SystemExit(f"{listener}: onListenerConnected marker missing")

additions = ""

if "override fun onDestroy()" not in text:
    additions += '''    override fun onDestroy() {
        OsineLog.event(applicationContext, "NLS", "onDestroy")
        super.onDestroy()
    }

'''

if "override fun onTaskRemoved(" not in text:
    additions += '''    override fun onTaskRemoved(rootIntent: android.content.Intent?) {
        OsineLog.event(applicationContext, "NLS", "onTaskRemoved")
        super.onTaskRemoved(rootIntent)
    }

'''

if additions:
    text = text.replace(marker, additions + marker, 1)
    listener.write_text(text, encoding="utf-8")

print("Applied osine v0.4 lifecycle logging hotfix")
