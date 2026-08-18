#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-osine-v0.4.py <project-dir>')

project = Path(sys.argv[1]).resolve()
app = project / 'app'
src = app / 'src' / 'main'
kotlin = src / 'java' / 'com' / 'randotone' / 'app'


def replace_exact(path: Path, old: str, new: str, expected: int = 1):
    text = path.read_text(encoding='utf-8')
    count = text.count(old)
    if count != expected:
        raise SystemExit(f'{path}: expected {expected} occurrence(s) of {old!r}, found {count}')
    path.write_text(text.replace(old, new), encoding='utf-8')


def replace_regex(path: Path, pattern: str, repl, expected: int = 1, flags: int = 0):
    text = path.read_text(encoding='utf-8')
    new, count = re.subn(pattern, repl, text, flags=flags)
    if count != expected:
        raise SystemExit(f'{path}: expected {expected} regex replacement(s) for {pattern!r}, found {count}')
    path.write_text(new, encoding='utf-8')


# v0.4 keeps the package/class names stable for upgrade compatibility, but the product name is now osine.
build = app / 'build.gradle.kts'
text = build.read_text(encoding='utf-8')
text = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 4', text)
text = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.4.0"', text)
build.write_text(text, encoding='utf-8')

strings = src / 'res' / 'values' / 'strings.xml'
text = strings.read_text(encoding='utf-8')
text, count = re.subn(r'(<string\s+name="app_name"[^>]*>).*?(</string>)', r'\1osine\2', text, count=1)
if count != 1:
    raise SystemExit(f'{strings}: app_name string not found')
strings.write_text(text, encoding='utf-8')

# Persistent rolling diagnostics. Internal app storage survives process death, Recents swipe,
# force-stop and reboot; uninstall intentionally removes it.
(kotlin / 'OsineLog.kt').write_text(r'''package com.randotone.app

import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object OsineLog {
    private const val DIR_NAME = "osine-diagnostics"
    private const val ACTIVE_NAME = "osine.log"
    private const val MAX_FILES = 5
    private const val MAX_BYTES = 256L * 1024L
    private val lock = Any()
    private val stamp = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US)
    private val exportStamp = SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", Locale.US)

    private fun dir(context: Context): File = File(context.filesDir, DIR_NAME).apply { mkdirs() }
    private fun active(context: Context): File = File(dir(context), ACTIVE_NAME)

    fun startSession(context: Context) {
        val app = context.applicationContext
        event(app, "APP", "================ osine session ================")
        val version = runCatching {
            val info = app.packageManager.getPackageInfo(app.packageName, 0)
            "${info.versionName ?: "?"} (${info.longVersionCode})"
        }.getOrDefault("unknown")
        val battery = runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                val pm = app.getSystemService(Context.POWER_SERVICE) as PowerManager
                if (pm.isIgnoringBatteryOptimizations(app.packageName)) "unrestricted" else "optimized"
            } else "n/a"
        }.getOrDefault("unknown")
        val access = runCatching { hasNotificationListenerAccess(app) }.getOrDefault(false)
        event(app, "APP", "version=$version android=${Build.VERSION.RELEASE} sdk=${Build.VERSION.SDK_INT}")
        event(app, "APP", "device=${Build.MANUFACTURER} ${Build.MODEL}")
        event(app, "APP", "notificationAccess=$access batteryOptimization=$battery")
    }

    fun event(context: Context, tag: String, message: String, error: Throwable? = null) {
        val safeTag = tag.replace(Regex("[^A-Za-z0-9_-]"), "_").take(16)
        val line = buildString {
            append(stamp.format(Date()))
            append("  [")
            append(safeTag)
            append("]  ")
            append(message.replace('\n', ' ').replace('\r', ' '))
            if (error != null) {
                append(" | ")
                append(error::class.java.simpleName)
                error.message?.let { append(": ").append(it.replace('\n', ' ').replace('\r', ' ')) }
            }
        }
        synchronized(lock) {
            runCatching {
                rotateIfNeeded(context, line.length + 1)
                active(context).appendText(line + "\n", Charsets.UTF_8)
            }
        }
    }

    private fun rotateIfNeeded(context: Context, incomingChars: Int) {
        val current = active(context)
        if (!current.exists() || current.length() + incomingChars <= MAX_BYTES) return
        val folder = dir(context)
        File(folder, "osine.${MAX_FILES - 1}.log").delete()
        for (index in (MAX_FILES - 2) downTo 1) {
            val from = File(folder, "osine.$index.log")
            if (from.exists()) from.renameTo(File(folder, "osine.${index + 1}.log"))
        }
        current.renameTo(File(folder, "osine.1.log"))
    }

    fun readAll(context: Context): String = synchronized(lock) {
        val folder = dir(context)
        val ordered = buildList {
            for (index in (MAX_FILES - 1) downTo 1) {
                val file = File(folder, "osine.$index.log")
                if (file.exists()) add(file)
            }
            active(context).takeIf { it.exists() }?.let(::add)
        }
        if (ordered.isEmpty()) "No osine diagnostics have been recorded yet."
        else ordered.joinToString("\n") { file ->
            "----- ${file.name} -----\n${runCatching { file.readText(Charsets.UTF_8) }.getOrDefault("<unreadable>")}" 
        }
    }

    fun readRecent(context: Context): String = synchronized(lock) {
        val file = active(context)
        if (!file.exists()) "No osine diagnostics have been recorded yet."
        else runCatching { file.readText(Charsets.UTF_8) }.getOrDefault("Unable to read osine diagnostics.")
    }

    fun clear(context: Context) {
        synchronized(lock) {
            dir(context).listFiles()?.forEach { file ->
                if (file.name.startsWith("osine") && file.extension == "log") file.delete()
            }
        }
    }

    fun export(context: Context, uri: Uri): Boolean = runCatching {
        context.contentResolver.openOutputStream(uri, "w")?.bufferedWriter(Charsets.UTF_8).use { writer ->
            requireNotNull(writer) { "Unable to open export destination" }
            writer.write(readAll(context))
        }
        true
    }.getOrDefault(false)

    fun suggestedExportName(): String = "osine-diagnostics-${exportStamp.format(Date())}.txt"
}
''', encoding='utf-8')

(kotlin / 'OsineApplication.kt').write_text(r'''package com.randotone.app

import android.app.Application

class OsineApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        OsineLog.startSession(this)
    }
}
''', encoding='utf-8')

# Application-level process start logging, without changing the package/applicationId.
manifest = src / 'AndroidManifest.xml'
replace_regex(
    manifest,
    r'<application(?![^>]*android:name=)',
    '<application\n        android:name=".OsineApplication"',
    expected=1,
)

# Listener lifecycle + delivery logging. No notification title/body/text is persisted.
listener = kotlin / 'RandoToneNotificationListener.kt'
listener_text = listener.read_text(encoding='utf-8')

if 'override fun onCreate()' in listener_text:
    listener_text, count = re.subn(
        r'(override\s+fun\s+onCreate\s*\(\s*\)\s*\{\s*\n)',
        r'\1        OsineLog.event(applicationContext, "NLS", "onCreate")\n',
        listener_text,
        count=1,
    )
    if count != 1:
        raise SystemExit(f'{listener}: could not instrument existing onCreate')
else:
    marker = '    override fun onListenerConnected() {'
    if marker not in listener_text:
        raise SystemExit(f'{listener}: onListenerConnected marker missing')
    listener_text = listener_text.replace(
        marker,
        '''    override fun onCreate() {\n        super.onCreate()\n        OsineLog.event(applicationContext, "NLS", "onCreate")\n    }\n\n    override fun onDestroy() {\n        OsineLog.event(applicationContext, "NLS", "onDestroy")\n        super.onDestroy()\n    }\n\n    override fun onTaskRemoved(rootIntent: android.content.Intent?) {\n        OsineLog.event(applicationContext, "NLS", "onTaskRemoved")\n        super.onTaskRemoved(rootIntent)\n    }\n\n''' + marker,
        1,
    )

listener_text = listener_text.replace(
    '        ListenerRecovery.markConnected(applicationContext)\n',
    '        ListenerRecovery.markConnected(applicationContext)\n        OsineLog.event(applicationContext, "NLS", "onListenerConnected")\n',
    1,
)
listener_text = listener_text.replace(
    '        ListenerRecovery.markDisconnected(applicationContext)\n',
    '        ListenerRecovery.markDisconnected(applicationContext)\n        OsineLog.event(applicationContext, "NLS", "onListenerDisconnected")\n',
    1,
)

posted = re.compile(r'(override\s+fun\s+onNotificationPosted\s*\(\s*(\w+)\s*:[^)]*\)\s*\{)')
match = posted.search(listener_text)
if not match:
    raise SystemExit(f'{listener}: onNotificationPosted signature not found')
var = match.group(2)
instrument = match.group(1) + f'''\n        OsineLog.event(\n            applicationContext,\n            "NOTIF",\n            "received package=${{{var}?.packageName ?: "unknown"}} id=${{{var}?.id ?: -1}}"\n        )'''
listener_text = listener_text[:match.start()] + instrument + listener_text[match.end():]
listener.write_text(listener_text, encoding='utf-8')

# Replace the v0.3 recovery helper with an instrumented equivalent.
(kotlin / 'ListenerRecovery.kt').write_text(r'''package com.randotone.app

import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.service.notification.NotificationListenerService

object ListenerRecovery {
    private const val PREFS = "listener_recovery"
    private const val KEY_LAST_REQUEST = "last_request"
    private const val KEY_LAST_REASON = "last_reason"
    private const val KEY_LAST_CONNECTED = "last_connected"
    private const val KEY_LAST_DISCONNECTED = "last_disconnected"

    fun requestRebind(context: Context, reason: String): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            OsineLog.event(context, "REBIND", "skipped reason=$reason sdk-too-old")
            return false
        }
        if (!hasNotificationListenerAccess(context)) {
            OsineLog.event(context, "REBIND", "skipped reason=$reason notification-access=false")
            return false
        }

        val component = ComponentName(context, RandoToneNotificationListener::class.java)
        return runCatching {
            OsineLog.event(context, "REBIND", "request reason=$reason")
            NotificationListenerService.requestRebind(component)
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit()
                .putLong(KEY_LAST_REQUEST, System.currentTimeMillis())
                .putString(KEY_LAST_REASON, reason)
                .apply()
            OsineLog.event(context, "REBIND", "request accepted reason=$reason")
            true
        }.onFailure { error ->
            OsineLog.event(context, "REBIND", "request failed reason=$reason", error)
        }.getOrDefault(false)
    }

    fun markConnected(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putLong(KEY_LAST_CONNECTED, System.currentTimeMillis())
            .apply()
    }

    fun markDisconnected(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putLong(KEY_LAST_DISCONNECTED, System.currentTimeMillis())
            .apply()
    }
}
''', encoding='utf-8')

(kotlin / 'ListenerRecoveryReceiver.kt').write_text(r'''package com.randotone.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class ListenerRecoveryReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val reason = when (intent?.action) {
            Intent.ACTION_BOOT_COMPLETED -> "boot-completed"
            Intent.ACTION_USER_UNLOCKED -> "user-unlocked"
            Intent.ACTION_MY_PACKAGE_REPLACED -> "package-replaced"
            else -> "recovery-broadcast"
        }
        OsineLog.event(context, "RECEIVER", "action=${intent?.action ?: "null"} reason=$reason")
        ListenerRecovery.requestRebind(context.applicationContext, reason)
    }
}
''', encoding='utf-8')

# Activity lifecycle breadcrumbs + a user-facing diagnostics toolbox.
activity = kotlin / 'MainActivity.kt'
text = activity.read_text(encoding='utf-8')
text = text.replace(
    '        notificationAccessGranted = hasNotificationListenerAccess(this)\n        if (notificationAccessGranted) {\n            ListenerRecovery.requestRebind(this, "activity-create")\n        }\n',
    '        notificationAccessGranted = hasNotificationListenerAccess(this)\n        OsineLog.event(applicationContext, "ACTIVITY", "onCreate access=$notificationAccessGranted")\n        if (notificationAccessGranted) {\n            ListenerRecovery.requestRebind(this, "activity-create")\n        }\n',
    1,
)
text = text.replace(
    '        notificationAccessGranted = hasNotificationListenerAccess(this)\n        if (notificationAccessGranted) {\n            ListenerRecovery.requestRebind(this, "activity-resume")\n        }\n',
    '        notificationAccessGranted = hasNotificationListenerAccess(this)\n        OsineLog.event(applicationContext, "ACTIVITY", "onResume access=$notificationAccessGranted")\n        if (notificationAccessGranted) {\n            ListenerRecovery.requestRebind(this, "activity-resume")\n        }\n',
    1,
)

old_repair = '''                Text(\n                    "RandoTone now requests a listener rebind after disconnect, reboot, app update, and whenever this screen is reopened.",\n                    style = MaterialTheme.typography.bodySmall\n                )\n            }\n\n            Row(\n'''
new_repair = '''                Text(\n                    "osine can request a listener rebind after disconnect, reboot, app update, and whenever this screen is reopened.",\n                    style = MaterialTheme.typography.bodySmall\n                )\n            }\n\n            OsineDiagnosticsSection()\n\n            Row(\n'''
if old_repair not in text:
    raise SystemExit(f'{activity}: diagnostics insertion marker missing')
text = text.replace(old_repair, new_repair, 1)

# Rename user-facing string literals without touching RandoTone* class names/package compatibility.
text = text.replace('"RandoTone', '"osine')

text += r'''

@androidx.compose.runtime.Composable
private fun OsineDiagnosticsSection() {
    val context = androidx.compose.ui.platform.LocalContext.current
    val exportLauncher = androidx.activity.compose.rememberLauncherForActivityResult(
        contract = androidx.activity.result.contract.ActivityResultContracts.CreateDocument("text/plain")
    ) { uri ->
        if (uri != null) {
            OsineLog.export(context, uri)
        }
    }

    androidx.compose.foundation.layout.Column {
        androidx.compose.material3.Text(
            "Diagnostics",
            style = androidx.compose.material3.MaterialTheme.typography.titleMedium
        )
        androidx.compose.material3.Text(
            "Persistent rolling logs survive process death, Recents swipe, force-stop and reboot. Notification message text is never recorded.",
            style = androidx.compose.material3.MaterialTheme.typography.bodySmall
        )
        androidx.compose.material3.OutlinedButton(
            onClick = { exportLauncher.launch(OsineLog.suggestedExportName()) }
        ) {
            androidx.compose.material3.Text("Export logs")
        }
        androidx.compose.material3.OutlinedButton(
            onClick = {
                val clipboard = context.getSystemService(android.content.Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
                clipboard.setPrimaryClip(
                    android.content.ClipData.newPlainText("osine diagnostics", OsineLog.readRecent(context))
                )
            }
        ) {
            androidx.compose.material3.Text("Copy recent log")
        }
        androidx.compose.material3.OutlinedButton(
            onClick = { OsineLog.clear(context) }
        ) {
            androidx.compose.material3.Text("Clear logs")
        }
    }
}
'''
activity.write_text(text, encoding='utf-8')

print(f'Patched osine v0.4 diagnostics source in {project}')
