#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-osine-v0.9.py <project-dir>')
project = Path(sys.argv[1]).resolve()
app = project/'app'; src = app/'src'/'main'; kt = src/'java'/'com'/'randotone'/'app'

def one(text, old, new, label):
    if text.count(old) != 1:
        raise SystemExit(f'{label}: marker count={text.count(old)}')
    return text.replace(old, new, 1)

# Version only. v0.7 survival/Direct-Boot code is intentionally untouched.
p = app/'build.gradle.kts'; t = p.read_text()
t = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 9', t)
t = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.9.0"', t)
p.write_text(t)

# Hybrid app catalog: launcher-visible installed apps + real notification observations.
p = kt/'RandoToneRepository.kt'; t = p.read_text()
if 'import android.content.pm.PackageManager' not in t:
    t = one(t, 'import android.content.Intent\n', 'import android.content.Intent\nimport android.content.pm.PackageManager\nimport android.os.Build\n', p)
if 'fun loadAppCatalog()' not in t:
    marker = '    fun recordObservedApp(packageName: String, label: String, timestamp: Long = System.currentTimeMillis()) {'
    code = r'''    fun loadAppCatalog(): List<ObservedApp> {
        val merged = LinkedHashMap<String, ObservedApp>()
        queryLaunchableApps().forEach { merged[it.packageName] = it }
        loadObservedApps().forEach { observed ->
            val installed = merged[observed.packageName]
            val label = if (observed.label == observed.packageName && installed != null) installed.label else observed.label
            merged[observed.packageName] = observed.copy(label = label)
        }
        return merged.values.sortedWith(
            compareByDescending<ObservedApp> { it.lastSeen > 0L }
                .thenByDescending { it.lastSeen }
                .thenBy { it.label.lowercase() }
        )
    }

    private fun queryLaunchableApps(): List<ObservedApp> {
        val pm = context.packageManager
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val matches = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            pm.queryIntentActivities(intent, PackageManager.ResolveInfoFlags.of(0L))
        } else {
            @Suppress("DEPRECATION")
            pm.queryIntentActivities(intent, 0)
        }
        return matches.asSequence().mapNotNull { info ->
            val pkg = info.activityInfo?.packageName ?: return@mapNotNull null
            if (pkg == context.packageName) return@mapNotNull null
            val label = runCatching { info.loadLabel(pm)?.toString()?.trim().orEmpty() }.getOrDefault("")
            ObservedApp(pkg, label.ifBlank { pkg }, 0L)
        }.distinctBy { it.packageName }.toList()
    }

'''
    if marker not in t: raise SystemExit(f'{p}: recordObservedApp missing')
    t = t.replace(marker, code + marker, 1)
p.write_text(t)

# State always exposes the catalog, not only observed packages.
p = kt/'RandoToneState.kt'; t = p.read_text()
if t.count('repository.loadObservedApps()') < 2:
    raise SystemExit(f'{p}: loadObservedApps call sites missing')
t = t.replace('repository.loadObservedApps()', 'repository.loadAppCatalog()')
if 'fun refreshAppCatalog()' not in t:
    marker = '    fun createPool(name: String) {'
    code = '''    fun refreshAppCatalog() {
        observedApps = repository.loadAppCatalog()
        OsineLog.event(context.applicationContext, "APPS", "catalog total=${observedApps.size} observed=${observedApps.count { it.lastSeen > 0L }}")
    }

'''
    if marker not in t: raise SystemExit(f'{p}: createPool missing')
    t = t.replace(marker, code + marker, 1)
p.write_text(t)

# Observation fixes: identify ignored notification types too, and sweep active notifications on bind.
p = kt/'RandoToneNotificationListener.kt'; t = p.read_text()
old = '''        if (shouldHardIgnore(sbn)) return

        val appLabel = resolveAppLabel(sbn.packageName, sbn.notification)
        repository.recordObservedApp(sbn.packageName, appLabel, sbn.postTime)
'''
new = '''        if (sbn.packageName == packageName) return
        val appLabel = resolveAppLabel(sbn.packageName, sbn.notification)
        repository.recordObservedApp(sbn.packageName, appLabel, sbn.postTime)
        if (shouldHardIgnore(sbn)) return
'''
t = one(t, old, new, p)
if 'seedActiveNotificationApps()' not in t:
    pat = re.compile(r'(override\s+fun\s+onListenerConnected\s*\(\)\s*\{[\s\S]*?OsineLog\.event\(applicationContext,\s*"NLS",\s*"onListenerConnected"\)\s*\n)(\s*})')
    m = pat.search(t)
    if not m: raise SystemExit(f'{p}: onListenerConnected log marker missing')
    t = t[:m.start()] + m.group(1) + '        seedActiveNotificationApps()\n' + m.group(2) + t[m.end():]
    marker = '    override fun onDestroy() {'
    method = r'''    private fun seedActiveNotificationApps() {
        val active = runCatching { getActiveNotifications().toList() }
            .onFailure { OsineLog.event(applicationContext, "APPS", "active seed failed", it) }
            .getOrDefault(emptyList())
        var seeded = 0
        active.asSequence().filter { it.packageName != packageName }.distinctBy { it.packageName }.forEach { sbn ->
            repository.recordObservedApp(sbn.packageName, resolveAppLabel(sbn.packageName, sbn.notification), sbn.postTime)
            seeded++
        }
        OsineLog.event(applicationContext, "APPS", "active seed packages=$seeded")
    }

'''
    if marker not in t: raise SystemExit(f'{p}: onDestroy missing')
    t = t.replace(marker, method + marker, 1)
p.write_text(t)

# Refresh catalog when UI opens and stop calling catalog-only apps "observed".
p = kt/'MainActivity.kt'; t = p.read_text()
t, n = re.subn(r'"v0\.8 prototype • [^"]+"', '"v0.9 prototype • app catalog"', t, count=1)
if n != 1: raise SystemExit(f'{p}: v0.8 label missing')
t = one(t, '''    DisposableEffect(Unit) {
        onDispose { state.close() }
    }
''', '''    DisposableEffect(Unit) {
        state.refreshAppCatalog()
        onDispose { state.close() }
    }
''', p)
needle = '    val configuredCount = state.observedApps.count { state.getRule(it.packageName).kind != RuleKind.DEFAULT }\n'
if needle not in t: raise SystemExit(f'{p}: configuredCount missing')
t = t.replace(needle, needle + '    val actuallyObservedCount = state.observedApps.count { it.lastSeen > 0L }\n', 1)
t = one(t, '''                    count = state.observedApps.size,
                    configuredCount = configuredCount,
                    excludedCount = excludedCount
''', '''                    count = state.observedApps.size,
                    observedCount = actuallyObservedCount,
                    configuredCount = configuredCount,
                    excludedCount = excludedCount
''', p)
t = one(t, 'private fun AppRulesCardHeader(count: Int, configuredCount: Int, excludedCount: Int) {', 'private fun AppRulesCardHeader(count: Int, observedCount: Int, configuredCount: Int, excludedCount: Int) {', p)
t = one(t, '"$count observed • $configuredCount custom • $excludedCount excluded"', '"$count apps • $observedCount notification-observed • $configuredCount custom • $excludedCount excluded"', p)
t = one(t, '"Custom assignments stay at the top. New apps appear after osine observes a normal notification from them."', '"The catalog is seeded from launchable installed apps. Notification-observed apps also show when they were last seen."', p)
t = t.replace('label = { Text("Find observed app") }', 'label = { Text("Find app") }', 1)
t = t.replace('"No observed apps match this search/filter."', '"No apps match this search/filter."', 1)
old = '''            Text(
                "Last seen: ${DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date(app.lastSeen))}",
                style = MaterialTheme.typography.labelSmall
            )
'''
new = '''            if (app.lastSeen > 0L) {
                Text(
                    "Notification observed: ${DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date(app.lastSeen))}",
                    style = MaterialTheme.typography.labelSmall
                )
            } else {
                Text("Installed app • no notification observed yet", style = MaterialTheme.typography.labelSmall)
            }
'''
t = one(t, old, new, p)
p.write_text(t)

print(f'Patched osine v0.9 hybrid app catalog source in {project}')
