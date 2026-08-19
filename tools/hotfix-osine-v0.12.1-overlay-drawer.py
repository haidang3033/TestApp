#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: hotfix-osine-v0.12.1-overlay-drawer.py <project-dir>")

project = Path(sys.argv[1]).resolve()
app = project / "app"
kt = app / "src" / "main" / "java" / "com" / "randotone" / "app"

def matching_brace(text: str, open_index: int) -> int:
    depth = 0
    i = open_index
    state = "code"
    while i < len(text):
        c = text[i]
        n = text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if c == "/" and n == "/": state = "line"; i += 2; continue
            if c == "/" and n == "*": state = "block"; i += 2; continue
            if text.startswith('"""', i): state = "triple"; i += 3; continue
            if c == '"': state = "string"; i += 1; continue
            if c == "'": state = "char"; i += 1; continue
            if c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0: return i
            i += 1; continue
        if state == "line":
            if c == "\n": state = "code"
            i += 1; continue
        if state == "block":
            if c == "*" and n == "/": state = "code"; i += 2; continue
            i += 1; continue
        if state == "triple":
            if text.startswith('"""', i): state = "code"; i += 3; continue
            i += 1; continue
        quote = '"' if state == "string" else "'"
        if c == "\\": i += 2; continue
        if c == quote: state = "code"
        i += 1
    raise ValueError("unterminated block")

build = app / "build.gradle.kts"
t = build.read_text(encoding="utf-8")
t = re.sub(r"versionCode\s*=\s*\d+", "versionCode = 14", t)
t = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.12.1"', t)
build.write_text(t, encoding="utf-8")

p = kt / "MainActivity.kt"
t = p.read_text(encoding="utf-8")
t = t.replace('"v0.12 • reorganized UI + sound profiles"', '"v0.12.1 • overlay drawer + sound profiles"', 1)

old_state = '    var navigationExpanded by remember { mutableStateOf(false) }\n'
new_state = '''    val drawerState = androidx.compose.material3.rememberDrawerState(
        initialValue = androidx.compose.material3.DrawerValue.Closed
    )
    val drawerScope = androidx.compose.runtime.rememberCoroutineScope()
'''
if old_state not in t:
    raise SystemExit("navigationExpanded state marker missing")
t = t.replace(old_state, new_state, 1)

if "import kotlinx.coroutines.launch\n" not in t:
    marker = "import androidx.compose.ui.unit.dp\n"
    if marker not in t:
        raise SystemExit("dp import marker missing")
    t = t.replace(marker, marker + "import kotlinx.coroutines.launch\n", 1)

row_anchor = "androidx.compose.foundation.layout.Row(modifier = Modifier.fillMaxSize()) {"
row_start = t.find(row_anchor)
if row_start < 0:
    raise SystemExit("persistent rail Row wrapper missing")
row_open = t.find("{", row_start)
row_close = matching_brace(t, row_open)
row_block = t[row_start:row_close + 1]
if "OsineSectionRail(" not in row_block:
    raise SystemExit("expected OsineSectionRail inside wrapper")

lazy_start = row_block.find("LazyColumn(")
if lazy_start < 0:
    raise SystemExit("main LazyColumn missing inside rail wrapper")
lazy_open = row_block.find("{", lazy_start)
lazy_close = matching_brace(row_block, lazy_open)
lazy_block = row_block[lazy_start:lazy_close + 1]

new_wrapper = '''androidx.compose.material3.ModalNavigationDrawer(
        drawerState = drawerState,
        gesturesEnabled = true,
        drawerContent = {
            androidx.compose.material3.ModalDrawerSheet(
                modifier = Modifier.fillMaxHeight().width(300.dp)
            ) {
                OsineDrawerContent(
                    selected = selectedSection,
                    onSelect = { section ->
                        selectedSection = section
                        drawerScope.launch { drawerState.close() }
                    }
                )
            }
        }
    ) {
        androidx.compose.foundation.layout.Column(modifier = Modifier.fillMaxSize()) {
            androidx.compose.material3.Surface(tonalElevation = 3.dp) {
                androidx.compose.foundation.layout.Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    androidx.compose.material3.IconButton(
                        onClick = { drawerScope.launch { drawerState.open() } }
                    ) {
                        Text("☰", fontWeight = FontWeight.Bold)
                    }
                    androidx.compose.foundation.layout.Column(modifier = Modifier.weight(1f)) {
                        Text("osine", fontWeight = FontWeight.Bold)
                        Text(selectedSection.label, style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
            androidx.compose.foundation.layout.Box(modifier = Modifier.weight(1f)) {
''' + lazy_block + '''
            }
        }
    }'''
t = t[:row_start] + new_wrapper + t[row_close + 1:]

pat = re.compile(
    r'@Composable\nprivate fun OsineSectionRail\(selected: OsineSection, expanded: Boolean, onToggle: \(\) -> Unit, onSelect: \(OsineSection\) -> Unit\) \{.*?\n\}\n\n@Composable\nprivate fun DefaultBehaviorCard',
    re.S,
)
rep = r'''@Composable
private fun OsineDrawerContent(selected: OsineSection, onSelect: (OsineSection) -> Unit) {
    androidx.compose.foundation.layout.Column(
        modifier = Modifier.fillMaxHeight().padding(vertical = 10.dp)
    ) {
        androidx.compose.foundation.layout.Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("osine", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        }
        Text(
            "one sound is not enough",
            modifier = Modifier.padding(horizontal = 18.dp, vertical = 2.dp),
            style = MaterialTheme.typography.bodySmall
        )
        androidx.compose.material3.HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))
        OsineSection.entries.forEach { section ->
            androidx.compose.material3.NavigationDrawerItem(
                label = { Text(section.label) },
                selected = selected == section,
                onClick = { onSelect(section) },
                icon = { Text(section.glyph, fontWeight = FontWeight.Bold) },
                modifier = Modifier.padding(horizontal = 10.dp, vertical = 2.dp)
            )
        }
    }
}

@Composable
private fun DefaultBehaviorCard'''
t, n = pat.subn(rep, t, count=1)
if n != 1:
    raise SystemExit("OsineSectionRail replacement failed")

if "navigationExpanded" in t or "OsineSectionRail(" in t:
    raise SystemExit("old rail leftovers remain")

p.write_text(t, encoding="utf-8")
print("Applied osine v0.12.1 overlay navigation drawer hotfix")
