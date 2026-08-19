#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-osine-v0.10.py <project-dir>')
project = Path(sys.argv[1]).resolve()
app = project/'app'; src = app/'src'/'main'; kt = src/'java'/'com'/'randotone'/'app'

def matching_brace(text, open_index):
    if text[open_index] != '{':
        raise ValueError('not an opening brace')
    depth = 0; i = open_index; state = 'code'
    while i < len(text):
        c = text[i]; n = text[i+1] if i + 1 < len(text) else ''
        if state == 'code':
            if c == '/' and n == '/': state = 'line'; i += 2; continue
            if c == '/' and n == '*': state = 'block'; i += 2; continue
            if text.startswith('"""', i): state = 'triple'; i += 3; continue
            if c == '"': state = 'string'; i += 1; continue
            if c == "'": state = 'char'; i += 1; continue
            if c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0: return i
            i += 1; continue
        if state == 'line':
            if c == '\n': state = 'code'
            i += 1; continue
        if state == 'block':
            if c == '*' and n == '/': state = 'code'; i += 2; continue
            i += 1; continue
        if state == 'triple':
            if text.startswith('"""', i): state = 'code'; i += 3; continue
            i += 1; continue
        if state in ('string','char'):
            quote = '"' if state == 'string' else "'"
            if c == '\\': i += 2; continue
            if c == quote: state = 'code'
            i += 1; continue
    raise ValueError('unterminated brace')

# Version bump only. v0.7 lifecycle/Direct-Boot mechanics stay intact.
p = app/'build.gradle.kts'; t = p.read_text(encoding='utf-8')
t = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 10', t)
t = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.10.0"', t)
p.write_text(t, encoding='utf-8')

# Independent fallback policy. Master roulette controls whether osine exists; this controls only
# what DEFAULT app rules do while the master is already ON.
(kt/'OsineDefaultPolicy.kt').write_text(r'''package com.randotone.app

import android.content.Context

object OsineDefaultPolicy {
    private const val PREFS = "osine_default_policy"
    private const val KEY_ENABLED = "default_enabled"

    fun isEnabled(context: Context): Boolean =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getBoolean(KEY_ENABLED, true)

    fun setEnabled(context: Context, enabled: Boolean) {
        val app = context.applicationContext
        app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putBoolean(KEY_ENABLED, enabled).commit()
        OsineLog.event(app, "DEFAULT", "fallback-enabled=$enabled")
    }
}
''', encoding='utf-8')

# Experimental listener-hint lab. No call audio is played in this prototype. We first establish
# whether the host actually honors HINT_HOST_DISABLE_CALL_EFFECTS on the user's device/apps.
(kt/'OsineRingtoneLab.kt').write_text(r'''package com.randotone.app

import android.app.Notification
import android.content.Context
import android.os.Build
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import java.lang.ref.WeakReference

object OsineRingtoneLab {
    private const val PREFS = "osine_ringtone_lab"
    private const val KEY_SUPPRESS = "suppress_call_effects"
    private const val KEY_EFFECTIVE = "last_effective_hints"
    @Volatile private var listenerRef: WeakReference<RandoToneNotificationListener>? = null

    fun isSuppressionRequested(context: Context): Boolean =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getBoolean(KEY_SUPPRESS, false)

    fun lastEffectiveHints(context: Context): Int =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getInt(KEY_EFFECTIVE, 0)

    fun setSuppression(context: Context, enabled: Boolean) {
        val app = context.applicationContext
        app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putBoolean(KEY_SUPPRESS, enabled).commit()
        OsineLog.event(app, "RINGLAB", "call-effects suppression requested=$enabled")
        listenerRef?.get()?.let { applyRequestedState(it, enabled, "ui-toggle") }
    }

    fun onListenerConnected(service: RandoToneNotificationListener) {
        listenerRef = WeakReference(service)
        applyRequestedState(service, isSuppressionRequested(service), "listener-connected")
    }

    fun onListenerDisconnected(service: RandoToneNotificationListener) {
        if (listenerRef?.get() === service) listenerRef = null
    }

    fun clearBeforeOperationStop(context: Context) {
        listenerRef?.get()?.let { service ->
            runCatching {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) service.clearRequestedListenerHints()
                else service.requestListenerHints(0)
                val current = service.currentListenerHints
                storeEffective(context, current)
                OsineLog.event(context, "RINGLAB", "cleared before operation stop effective=$current")
            }.onFailure { OsineLog.event(context, "RINGLAB", "clear before operation stop failed", it) }
        }
    }

    fun onHintsChanged(context: Context, hints: Int) {
        storeEffective(context, hints)
        val callSuppressed = hints and NotificationListenerService.HINT_HOST_DISABLE_CALL_EFFECTS != 0
        OsineLog.event(context, "RINGLAB", "listener hints changed=$hints callEffectsSuppressed=$callSuppressed")
    }

    private fun applyRequestedState(service: RandoToneNotificationListener, enabled: Boolean, reason: String) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            OsineLog.event(service, "RINGLAB", "hint unavailable sdk=${Build.VERSION.SDK_INT}")
            return
        }
        runCatching {
            if (enabled) {
                service.requestListenerHints(NotificationListenerService.HINT_HOST_DISABLE_CALL_EFFECTS)
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                service.clearRequestedListenerHints()
            } else {
                service.requestListenerHints(0)
            }
            val current = service.currentListenerHints
            storeEffective(service, current)
            val accepted = current and NotificationListenerService.HINT_HOST_DISABLE_CALL_EFFECTS != 0
            OsineLog.event(service, "RINGLAB", "hint apply reason=$reason requested=$enabled effective=$current accepted=$accepted")
        }.onFailure { OsineLog.event(service, "RINGLAB", "hint apply failed reason=$reason", it) }
    }

    private fun storeEffective(context: Context, hints: Int) {
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putInt(KEY_EFFECTIVE, hints).apply()
    }

    fun recordCallNotification(service: RandoToneNotificationListener, sbn: StatusBarNotification) {
        if (sbn.notification.category != Notification.CATEGORY_CALL) return
        val ranking = NotificationListenerService.Ranking()
        val hasRanking = runCatching { service.currentRanking.getRanking(sbn.key, ranking) }.getOrDefault(false)
        val channel = if (hasRanking && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) ranking.channel else null
        val channelSound = channel?.sound?.toString() ?: "null"
        val usage = channel?.audioAttributes?.usage ?: -1
        val importance = if (hasRanking) ranking.importance else -1
        OsineLog.event(
            service,
            "CALL",
            "package=${sbn.packageName} id=${sbn.id} channelId=${sbn.notification.channelId ?: "null"} " +
                "ranking=$hasRanking importance=$importance channelSound=$channelSound usage=$usage flags=${sbn.notification.flags}"
        )
    }
}
''', encoding='utf-8')

# Default-policy gate + Ringtone Lab hooks.
p = kt/'RandoToneNotificationListener.kt'; t = p.read_text(encoding='utf-8')
if 'OsineDefaultPolicy.isEnabled' not in t:
    m = re.search(r'(?m)^(\s*)val\s+(\w+)\s*=\s*repository\.getRule\(sbn\.packageName\)\s*$', t)
    if not m: raise SystemExit(f'{p}: per-app rule lookup missing')
    indent, rule = m.group(1), m.group(2)
    insert = m.group(0) + f'''\n{indent}if ({rule}.kind == RuleKind.DEFAULT && !OsineDefaultPolicy.isEnabled(applicationContext)) {{\n{indent}    OsineLog.event(applicationContext, "DEFAULT", "suppressed package=${{sbn.packageName}} reason=fallback-disabled")\n{indent}    return\n{indent}}}'''
    t = t[:m.start()] + insert + t[m.end():]

if 'OsineRingtoneLab.recordCallNotification' not in t:
    marker = '        if (shouldHardIgnore(sbn)) return\n'
    if marker not in t: raise SystemExit(f'{p}: hard-ignore marker missing')
    t = t.replace(marker, '        OsineRingtoneLab.recordCallNotification(this, sbn)\n' + marker, 1)

if 'OsineRingtoneLab.onListenerConnected(this)' not in t:
    marker = '        seedActiveNotificationApps()\n'
    if marker not in t: raise SystemExit(f'{p}: v0.9 active seed marker missing')
    t = t.replace(marker, marker + '        OsineRingtoneLab.onListenerConnected(this)\n', 1)

if 'override fun onListenerHintsChanged' not in t:
    marker = '    override fun onDestroy() {'
    method = '''    override fun onListenerHintsChanged(hints: Int) {\n        super.onListenerHintsChanged(hints)\n        OsineRingtoneLab.onHintsChanged(applicationContext, hints)\n    }\n\n'''
    if marker not in t: raise SystemExit(f'{p}: onDestroy marker missing')
    t = t.replace(marker, method + marker, 1)

if 'OsineRingtoneLab.onListenerDisconnected(this)' not in t:
    marker = '        OsineLog.event(applicationContext, "NLS", "onListenerDisconnected")\n'
    if marker not in t: raise SystemExit(f'{p}: disconnect log marker missing')
    t = t.replace(marker, marker + '        OsineRingtoneLab.onListenerDisconnected(this)\n', 1)
    destroy = '    override fun onDestroy() {\n'
    if destroy in t:
        t = t.replace(destroy, destroy + '        OsineRingtoneLab.onListenerDisconnected(this)\n', 1)
p.write_text(t, encoding='utf-8')

# OFF must clear any global call-effect request while the NLS is still connected.
p = kt/'OsineOperation.kt'; t = p.read_text(encoding='utf-8')
if 'OsineRingtoneLab.clearBeforeOperationStop' not in t:
    marker = '''        } else {\n            ListenerRecovery.cancelPending(app, "operation-off-$reason")\n'''
    repl = '''        } else {\n            OsineRingtoneLab.clearBeforeOperationStop(app)\n            ListenerRecovery.cancelPending(app, "operation-off-$reason")\n'''
    if marker not in t: raise SystemExit(f'{p}: operation-off branch missing')
    t = t.replace(marker, repl, 1)
p.write_text(t, encoding='utf-8')

# UI: split the long screen into General / Apps / Calls with a permanent left navigation rail.
p = kt/'MainActivity.kt'; t = p.read_text(encoding='utf-8')
t, n = re.subn(r'"v0\.9 prototype • [^"]+"', '"v0.10 prototype • sections + ringtone lab"', t, count=1)
if n != 1: raise SystemExit(f'{p}: v0.9 label missing')

state_marker = '    var appFilter by remember { mutableStateOf(AppListFilter.ALL) }\n'
state_repl = state_marker + '''    var selectedSection by remember { mutableStateOf(OsineSection.GENERAL) }\n    var defaultFallbackEnabled by remember { mutableStateOf(OsineDefaultPolicy.isEnabled(context)) }\n    var callSuppressionRequested by remember { mutableStateOf(OsineRingtoneLab.isSuppressionRequested(context)) }\n    var ringtoneLabRevision by remember { mutableStateOf(0) }\n'''
if 'var selectedSection by remember' not in t:
    if state_marker not in t: raise SystemExit(f'{p}: appFilter state marker missing')
    t = t.replace(state_marker, state_repl, 1)

search_from = 0; lazy_start = lazy_open = lazy_close = -1
while True:
    pos = t.find('LazyColumn(', search_from)
    if pos < 0: break
    op = t.find('{', pos)
    if op < 0: break
    cl = matching_brace(t, op)
    if 'AppRulesCardHeader' in t[op:cl]:
        lazy_start, lazy_open, lazy_close = pos, op, cl
        break
    search_from = cl + 1
if lazy_start < 0: raise SystemExit(f'{p}: main LazyColumn not found')
inner = t[lazy_open+1:lazy_close]

app_m = re.search(r'(?m)^\s*item\s*\{\s*\n\s*AppRulesCardHeader\s*\(', inner)
if not app_m: raise SystemExit(f'{p}: app rules header block missing')
app_start = app_m.start()
if_pos = inner.find('if (state.observedApps.isEmpty())', app_m.end())
if if_pos < 0: raise SystemExit(f'{p}: observed apps conditional missing')
first_open = inner.find('{', if_pos); first_close = matching_brace(inner, first_open)
else_pos = re.search(r'\belse\s*\{', inner[first_close+1:])
if not else_pos: raise SystemExit(f'{p}: observed apps else missing')
else_abs = first_close + 1 + else_pos.start()
else_open = inner.find('{', else_abs); else_close = matching_brace(inner, else_open)
app_end = else_close + 1
app_block = inner[app_start:app_end]
general_inner = inner[:app_start] + '''\n            item {\n                androidx.compose.material3.Card(modifier = Modifier.fillMaxWidth()) {\n                    androidx.compose.foundation.layout.Column(\n                        modifier = Modifier.padding(16.dp),\n                        verticalArrangement = Arrangement.spacedBy(8.dp)\n                    ) {\n                        Text("Per-app rules moved to Apps", fontWeight = FontWeight.Bold)\n                        Text("Use the Apps section on the left so the installed-app catalog no longer turns this page into geological strata.")\n                        androidx.compose.material3.Button(onClick = { selectedSection = OsineSection.APPS }) { Text("Open Apps") }\n                    }\n                }\n            }\n''' + inner[app_end:]

new_inner = '''\n        when (selectedSection) {\n            OsineSection.GENERAL -> {\n                item {\n                    DefaultBehaviorCard(\n                        enabled = defaultFallbackEnabled,\n                        onEnabled = { enabled ->\n                            defaultFallbackEnabled = enabled\n                            OsineDefaultPolicy.setEnabled(context, enabled)\n                        }\n                    )\n                }\n''' + general_inner + '''\n            }\n            OsineSection.APPS -> {\n''' + app_block + '''\n            }\n            OsineSection.CALLS -> {\n                item {\n                    @Suppress("UNUSED_VARIABLE") val revision = ringtoneLabRevision\n                    RingtoneLabCard(\n                        requested = callSuppressionRequested,\n                        effectiveHints = OsineRingtoneLab.lastEffectiveHints(context),\n                        masterEnabled = OsineOperation.isEnabled(context),\n                        onRequested = { enabled ->\n                            callSuppressionRequested = enabled\n                            OsineRingtoneLab.setSuppression(context, enabled)\n                            ringtoneLabRevision++\n                        }\n                    )\n                }\n            }\n        }\n'''

lazy_block = t[lazy_start:lazy_close+1]
new_lazy = lazy_block[:lazy_open-lazy_start+1] + new_inner + lazy_block[lazy_close-lazy_start:]
wrapped = '''androidx.compose.foundation.layout.Row(modifier = Modifier.fillMaxSize()) {\n        OsineSectionRail(\n            selected = selectedSection,\n            onSelect = { selectedSection = it }\n        )\n        androidx.compose.foundation.layout.Box(modifier = Modifier.weight(1f)) {\n''' + new_lazy + '''\n        }\n    }'''
t = t[:lazy_start] + wrapped + t[lazy_close+1:]

if 'private enum class OsineSection' not in t:
    t += r'''

private enum class OsineSection(val label: String, val glyph: String) {
    GENERAL("General", "G"),
    APPS("Apps", "A"),
    CALLS("Calls", "C")
}

@Composable
private fun OsineSectionRail(selected: OsineSection, onSelect: (OsineSection) -> Unit) {
    androidx.compose.material3.NavigationRail(modifier = Modifier.fillMaxHeight()) {
        Text("osine", modifier = Modifier.padding(vertical = 12.dp), fontWeight = FontWeight.Bold)
        OsineSection.entries.forEach { section ->
            androidx.compose.material3.NavigationRailItem(
                selected = selected == section,
                onClick = { onSelect(section) },
                icon = { Text(section.glyph, fontWeight = FontWeight.Bold) },
                label = { Text(section.label) },
                alwaysShowLabel = true
            )
        }
    }
}

@Composable
private fun DefaultBehaviorCard(enabled: Boolean, onEnabled: (Boolean) -> Unit) {
    androidx.compose.material3.Card(modifier = Modifier.fillMaxWidth()) {
        androidx.compose.foundation.layout.Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text("Default app behavior", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            androidx.compose.foundation.layout.Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                androidx.compose.foundation.layout.Column(modifier = Modifier.weight(1f)) {
                    Text(if (enabled) "Default pool enabled" else "Disabled • custom apps only", fontWeight = FontWeight.SemiBold)
                    Text(
                        if (enabled) "Apps with no custom rule use the selected default pool."
                        else "Unconfigured apps make no osine sound. Explicit custom-pool assignments still work.",
                        style = MaterialTheme.typography.bodySmall
                    )
                }
                androidx.compose.material3.Switch(checked = enabled, onCheckedChange = onEnabled)
            }
            Text("Master Roulette remains the power switch. Turning Master OFF still shuts down osine completely.", style = MaterialTheme.typography.labelSmall)
        }
    }
}

@Composable
private fun RingtoneLabCard(
    requested: Boolean,
    effectiveHints: Int,
    masterEnabled: Boolean,
    onRequested: (Boolean) -> Unit
) {
    val effective = effectiveHints and android.service.notification.NotificationListenerService.HINT_HOST_DISABLE_CALL_EFFECTS != 0
    androidx.compose.material3.Card(modifier = Modifier.fillMaxWidth()) {
        androidx.compose.foundation.layout.Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text("Ringtone Lab", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text("Prototype experiment: ask Android to suppress host call sounds while keeping notification sounds alone. osine does not play a replacement ringtone yet.")
            androidx.compose.foundation.layout.Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                androidx.compose.foundation.layout.Column(modifier = Modifier.weight(1f)) {
                    Text("Suppress Android call effects", fontWeight = FontWeight.SemiBold)
                    Text(if (requested) "Requested" else "Not requested", style = MaterialTheme.typography.bodySmall)
                }
                androidx.compose.material3.Switch(checked = requested, onCheckedChange = onRequested)
            }
            Text("Host reports call-effect suppression: ${if (effective) "YES" else "NO / not connected yet"}", fontWeight = FontWeight.SemiBold)
            if (!masterEnabled) {
                Text("Master Roulette is OFF, so the listener is intentionally unbound. The request will only be applied after Master is ON.", style = MaterialTheme.typography.bodySmall)
            }
            Text("This hint is global while active. Test an incoming Zalo/WhatsApp/Messenger/Phone call and export diagnostics afterward. CATEGORY_CALL metadata is logged without notification message text.", style = MaterialTheme.typography.bodySmall)
        }
    }
}
'''
p.write_text(t, encoding='utf-8')

print(f'Patched osine v0.10 section navigation, default policy and Ringtone Lab in {project}')
