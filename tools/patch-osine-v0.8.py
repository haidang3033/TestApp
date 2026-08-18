#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-osine-v0.8.py <project-dir>')

project = Path(sys.argv[1]).resolve()
app = project / 'app'
src = app / 'src' / 'main'
kotlin = src / 'java' / 'com' / 'randotone' / 'app'


def replace_exact(path: Path, old: str, new: str, expected: int = 1):
    text = path.read_text(encoding='utf-8')
    count = text.count(old)
    if count != expected:
        raise SystemExit(f'{path}: expected {expected} occurrence(s) of marker, found {count}')
    path.write_text(text.replace(old, new, expected), encoding='utf-8')

# Version bump. Lifecycle/Direct-Boot machinery is intentionally not changed in v0.8.
build = app / 'build.gradle.kts'
text = build.read_text(encoding='utf-8')
text = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 8', text)
text = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.8.0"', text)
build.write_text(text, encoding='utf-8')

# Make app-rule changes observable by Compose and by changes coming from another process.
state = kotlin / 'RandoToneState.kt'
st = state.read_text(encoding='utf-8')

observed_marker = '''    var observedApps by mutableStateOf(repository.loadObservedApps())\n        private set\n    var history by mutableStateOf(repository.loadHistory())\n'''
observed_repl = '''    var observedApps by mutableStateOf(repository.loadObservedApps())\n        private set\n    var ruleRevision by mutableStateOf(0L)\n        private set\n    var history by mutableStateOf(repository.loadHistory())\n'''
if observed_marker not in st:
    raise SystemExit(f'{state}: observedApps state marker missing')
st = st.replace(observed_marker, observed_repl, 1)

listener_marker = '''            RandoToneRepository.KEY_OBSERVED_APPS -> {\n                observedApps = repository.loadObservedApps()\n            }\n            RandoToneRepository.KEY_HISTORY -> {\n'''
listener_repl = '''            RandoToneRepository.KEY_OBSERVED_APPS -> {\n                observedApps = repository.loadObservedApps()\n            }\n            RandoToneRepository.KEY_RULES -> {\n                ruleRevision++\n            }\n            RandoToneRepository.KEY_HISTORY -> {\n'''
if listener_marker not in st:
    raise SystemExit(f'{state}: preference listener marker missing')
st = st.replace(listener_marker, listener_repl, 1)

for name in ('setRuleDefault', 'setRuleExcluded'):
    old = f'''    fun {name}(packageName: String) {{\n        repository.{name}(packageName)\n    }}\n'''
    new = f'''    fun {name}(packageName: String) {{\n        repository.{name}(packageName)\n        ruleRevision++\n    }}\n'''
    if old not in st:
        raise SystemExit(f'{state}: {name} marker missing')
    st = st.replace(old, new, 1)

old = '''    fun setRulePool(packageName: String, poolId: String) {\n        repository.setRulePool(packageName, poolId)\n    }\n'''
new = '''    fun setRulePool(packageName: String, poolId: String) {\n        repository.setRulePool(packageName, poolId)\n        ruleRevision++\n    }\n'''
if old not in st:
    raise SystemExit(f'{state}: setRulePool marker missing')
st = st.replace(old, new, 1)
state.write_text(st, encoding='utf-8')

# Per-app assignment UX: searchable/filterable, custom rules first, no arbitrary 30-app UI cap.
activity = kotlin / 'MainActivity.kt'
at = activity.read_text(encoding='utf-8')

# Version label only; tolerate wording changes in earlier lifecycle releases.
at, count = re.subn(
    r'"v0\.7 prototype • [^"]+"',
    '"v0.8 prototype • per-app control"',
    at,
    count=1,
)
if count != 1:
    raise SystemExit(f'{activity}: v0.7 version label missing')

state_vars_marker = '''    var showDefaultPoolDialog by remember { mutableStateOf(false) }\n    var editingApp by remember { mutableStateOf<ObservedApp?>(null) }\n'''
state_vars_repl = '''    var showDefaultPoolDialog by remember { mutableStateOf(false) }\n    var editingApp by remember { mutableStateOf<ObservedApp?>(null) }\n    var appSearch by remember { mutableStateOf("") }\n    var appFilter by remember { mutableStateOf(AppListFilter.ALL) }\n'''
if state_vars_marker not in at:
    raise SystemExit(f'{activity}: app-rule UI state marker missing')
at = at.replace(state_vars_marker, state_vars_repl, 1)

# Compute visible list from all observed apps. Reading ruleRevision deliberately subscribes this
# composable to rule mutations even though individual rules live in SharedPreferences.
list_anchor = '''    val picker = rememberLauncherForActivityResult(\n        contract = ActivityResultContracts.OpenMultipleDocuments()\n    ) { uris ->\n        importTargetPool?.let { state.addSounds(it, uris) }\n        importTargetPool = null\n    }\n\n'''
list_repl = list_anchor + '''    val ruleRevision = state.ruleRevision\n    val appQuery = appSearch.trim()\n    val configuredCount = state.observedApps.count { state.getRule(it.packageName).kind != RuleKind.DEFAULT }\n    val excludedCount = state.observedApps.count { state.getRule(it.packageName).kind == RuleKind.EXCLUDED }\n    val visibleApps = state.observedApps\n        .asSequence()\n        .filter { app ->\n            appQuery.isBlank() ||\n                app.label.contains(appQuery, ignoreCase = true) ||\n                app.packageName.contains(appQuery, ignoreCase = true)\n        }\n        .filter { app ->\n            val kind = state.getRule(app.packageName).kind\n            when (appFilter) {\n                AppListFilter.ALL -> true\n                AppListFilter.CUSTOM -> kind != RuleKind.DEFAULT\n                AppListFilter.EXCLUDED -> kind == RuleKind.EXCLUDED\n            }\n        }\n        .sortedWith(\n            compareByDescending<ObservedApp> { state.getRule(it.packageName).kind != RuleKind.DEFAULT }\n                .thenByDescending { it.lastSeen }\n        )\n        .toList()\n    // Keep this read explicit: it is the invalidation token for ruleDescription()/getRule().\n    @Suppress("UNUSED_VARIABLE") val appRuleUiRevision = ruleRevision\n\n'''
if list_anchor not in at:
    raise SystemExit(f'{activity}: picker/list insertion marker missing')
at = at.replace(list_anchor, list_repl, 1)

old_section = '''            item {\n                AppRulesCardHeader(state.observedApps.size)\n            }\n\n            if (state.observedApps.isEmpty()) {\n                item {\n                    EmptyObservedAppsCard(notificationAccessGranted)\n                }\n            } else {\n                items(state.observedApps.take(30), key = { it.packageName }) { app ->\n                    ObservedAppCard(\n                        app = app,\n                        ruleDescription = state.ruleDescription(app.packageName),\n                        onConfigure = { editingApp = app },\n                        onAndroidSettings = {\n                            openAppNotificationSettings(context, app.packageName)\n                        }\n                    )\n                }\n            }\n'''
new_section = '''            item {\n                AppRulesCardHeader(\n                    count = state.observedApps.size,\n                    configuredCount = configuredCount,\n                    excludedCount = excludedCount\n                )\n            }\n\n            if (state.observedApps.isEmpty()) {\n                item {\n                    EmptyObservedAppsCard(notificationAccessGranted)\n                }\n            } else {\n                item {\n                    AppRulesToolbar(\n                        query = appSearch,\n                        onQueryChange = { appSearch = it },\n                        filter = appFilter,\n                        onFilterChange = { appFilter = it }\n                    )\n                }\n\n                if (visibleApps.isEmpty()) {\n                    item {\n                        Card(modifier = Modifier.fillMaxWidth()) {\n                            Text(\n                                "No observed apps match this search/filter.",\n                                modifier = Modifier.padding(16.dp)\n                            )\n                        }\n                    }\n                } else {\n                    items(visibleApps, key = { it.packageName }) { app ->\n                        val rule = state.getRule(app.packageName)\n                        ObservedAppCard(\n                            app = app,\n                            ruleDescription = state.ruleDescription(app.packageName),\n                            isCustom = rule.kind != RuleKind.DEFAULT,\n                            onConfigure = { editingApp = app },\n                            onReset = { state.setRuleDefault(app.packageName) },\n                            onAndroidSettings = {\n                                openAppNotificationSettings(context, app.packageName)\n                            }\n                        )\n                    }\n                }\n            }\n'''
if old_section not in at:
    raise SystemExit(f'{activity}: old per-app section marker missing')
at = at.replace(old_section, new_section, 1)

old_header = '''@Composable\nprivate fun AppRulesCardHeader(count: Int) {\n    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {\n        Text("Per-app rules", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)\n        Text(\n            "$count observed app${if (count == 1) "" else "s"} • apps appear after they post a normal notification",\n            style = MaterialTheme.typography.bodySmall\n        )\n    }\n}\n'''
new_header = '''private enum class AppListFilter(val label: String) {\n    ALL("All"),\n    CUSTOM("Custom"),\n    EXCLUDED("Excluded")\n}\n\n@Composable\nprivate fun AppRulesCardHeader(count: Int, configuredCount: Int, excludedCount: Int) {\n    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {\n        Text("Per-app rules", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)\n        Text(\n            "$count observed • $configuredCount custom • $excludedCount excluded",\n            style = MaterialTheme.typography.bodySmall\n        )\n        Text(\n            "Custom assignments stay at the top. New apps appear after osine observes a normal notification from them.",\n            style = MaterialTheme.typography.bodySmall\n        )\n    }\n}\n\n@Composable\nprivate fun AppRulesToolbar(\n    query: String,\n    onQueryChange: (String) -> Unit,\n    filter: AppListFilter,\n    onFilterChange: (AppListFilter) -> Unit\n) {\n    Card(modifier = Modifier.fillMaxWidth()) {\n        Column(\n            modifier = Modifier.padding(12.dp),\n            verticalArrangement = Arrangement.spacedBy(10.dp)\n        ) {\n            OutlinedTextField(\n                value = query,\n                onValueChange = onQueryChange,\n                modifier = Modifier.fillMaxWidth(),\n                label = { Text("Find observed app") },\n                placeholder = { Text("Name or package") },\n                singleLine = true\n            )\n            Row(\n                modifier = Modifier.fillMaxWidth(),\n                horizontalArrangement = Arrangement.spacedBy(8.dp)\n            ) {\n                AppListFilter.entries.forEach { option ->\n                    FilterChip(\n                        selected = filter == option,\n                        onClick = { onFilterChange(option) },\n                        label = { Text(option.label) }\n                    )\n                }\n            }\n        }\n    }\n}\n'''
if old_header not in at:
    raise SystemExit(f'{activity}: AppRulesCardHeader marker missing')
at = at.replace(old_header, new_header, 1)

old_card_sig = '''private fun ObservedAppCard(\n    app: ObservedApp,\n    ruleDescription: String,\n    onConfigure: () -> Unit,\n    onAndroidSettings: () -> Unit\n) {\n'''
new_card_sig = '''private fun ObservedAppCard(\n    app: ObservedApp,\n    ruleDescription: String,\n    isCustom: Boolean,\n    onConfigure: () -> Unit,\n    onReset: () -> Unit,\n    onAndroidSettings: () -> Unit\n) {\n'''
if old_card_sig not in at:
    raise SystemExit(f'{activity}: ObservedAppCard signature marker missing')
at = at.replace(old_card_sig, new_card_sig, 1)

old_card_body = '''            Text(app.label, fontWeight = FontWeight.Bold)\n            Text(app.packageName, style = MaterialTheme.typography.bodySmall)\n            Text("Rule: $ruleDescription")\n            Row(\n                modifier = Modifier.fillMaxWidth(),\n                horizontalArrangement = Arrangement.spacedBy(8.dp)\n            ) {\n                Button(onClick = onConfigure, modifier = Modifier.weight(1f)) {\n                    Text("Configure rule")\n                }\n                OutlinedButton(onClick = onAndroidSettings, modifier = Modifier.weight(1f)) {\n                    Text("Android sound settings")\n                }\n            }\n'''
new_card_body = '''            Row(\n                modifier = Modifier.fillMaxWidth(),\n                verticalAlignment = Alignment.CenterVertically\n            ) {\n                Column(modifier = Modifier.weight(1f)) {\n                    Text(app.label, fontWeight = FontWeight.Bold)\n                    Text(app.packageName, style = MaterialTheme.typography.bodySmall)\n                }\n                if (isCustom) {\n                    FilterChip(\n                        selected = true,\n                        onClick = onConfigure,\n                        label = { Text("Custom") }\n                    )\n                }\n            }\n            Text("Rule: $ruleDescription", fontWeight = FontWeight.SemiBold)\n            Text(\n                "Last seen: ${DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date(app.lastSeen))}",\n                style = MaterialTheme.typography.labelSmall\n            )\n            Row(\n                modifier = Modifier.fillMaxWidth(),\n                horizontalArrangement = Arrangement.spacedBy(8.dp)\n            ) {\n                Button(onClick = onConfigure, modifier = Modifier.weight(1f)) {\n                    Text(if (isCustom) "Change rule" else "Assign pool")\n                }\n                OutlinedButton(onClick = onAndroidSettings, modifier = Modifier.weight(1f)) {\n                    Text("Android settings")\n                }\n            }\n            if (isCustom) {\n                TextButton(onClick = onReset, modifier = Modifier.fillMaxWidth()) {\n                    Text("Reset to default pool")\n                }\n            }\n'''
if old_card_body not in at:
    raise SystemExit(f'{activity}: ObservedAppCard body marker missing')
at = at.replace(old_card_body, new_card_body, 1)

# Make the chooser more informative without changing rule semantics.
old_dialog_intro = '''            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {\n                Text("Choose what this app should do:")\n                TextButton(onClick = onDefault, modifier = Modifier.fillMaxWidth()) {\n                    Text(if (currentRule.kind == RuleKind.DEFAULT) "✓ Use default pool" else "Use default pool")\n                }\n'''
new_dialog_intro = '''            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {\n                Text("Choose what this app should do:")\n                Text(\n                    "Default means this app follows the master notification pool. A custom pool overrides only this app.",\n                    style = MaterialTheme.typography.bodySmall\n                )\n                TextButton(onClick = onDefault, modifier = Modifier.fillMaxWidth()) {\n                    Text(if (currentRule.kind == RuleKind.DEFAULT) "✓ Use default pool" else "Use default pool")\n                }\n'''
if old_dialog_intro not in at:
    raise SystemExit(f'{activity}: AppRuleDialog intro marker missing')
at = at.replace(old_dialog_intro, new_dialog_intro, 1)

old_pool_button = '''                    ) {\n                        Text(if (selected) "✓ ${pool.name}" else pool.name)\n                    }\n'''
new_pool_button = '''                    ) {\n                        val enabledCount = pool.sounds.count { it.enabled }\n                        Text(\n                            if (selected) "✓ ${pool.name} • $enabledCount enabled"\n                            else "${pool.name} • $enabledCount enabled"\n                        )\n                    }\n'''
dialog_pos = at.find('private fun AppRuleDialog(')
if dialog_pos < 0:
    raise SystemExit(f'{activity}: AppRuleDialog missing')
prefix, dialog = at[:dialog_pos], at[dialog_pos:]
if old_pool_button not in dialog:
    raise SystemExit(f'{activity}: AppRuleDialog pool button marker missing')
dialog = dialog.replace(old_pool_button, new_pool_button, 1)
at = prefix + dialog

activity.write_text(at, encoding='utf-8')

print(f'Patched osine v0.8 per-app control source in {project}')
