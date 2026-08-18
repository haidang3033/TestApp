#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch-osine-v0.5.py <project-dir>")

project = Path(sys.argv[1]).resolve()
app = project / "app"
src = app / "src" / "main"
kotlin = src / "java" / "com" / "randotone" / "app"


def replace_exact(path: Path, old: str, new: str, expected: int = 1):
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{path}: expected {expected} occurrence(s) of {old!r}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


# Version bump. Keep package/application id stable so this installs over v0.4.
build = app / "build.gradle.kts"
text = build.read_text(encoding="utf-8")
text = re.sub(r"versionCode\s*=\s*\d+", "versionCode = 5", text)
text = re.sub(r"versionName\s*=\s*\"[^\"]+\"", 'versionName = "0.5.0"', text)
build.write_text(text, encoding="utf-8")

# Make the already-default auto-bind behavior explicit in the manifest for this experiment.
manifest = src / "AndroidManifest.xml"
manifest_text = manifest.read_text(encoding="utf-8")
if "android.service.notification.default_autobind_listenerservice" not in manifest_text:
    pattern = re.compile(
        r'(<service\s+android:name="\.RandoToneNotificationListener"[\s\S]*?>\s*)(<intent-filter>)'
    )
    manifest_text, count = pattern.subn(
        r'''\1<meta-data
                android:name="android.service.notification.default_autobind_listenerservice"
                android:value="true" />
            \2''',
        manifest_text,
        count=1,
    )
    if count != 1:
        raise SystemExit(f"{manifest}: could not add notification listener auto-bind metadata")
manifest.write_text(manifest_text, encoding="utf-8")

# Replace the recovery helper. Important semantic change from v0.4:
# "submitted" means only that an API call returned without throwing.
# Success is recorded only when onListenerConnected() calls markConnected().
(kotlin / "ListenerRecovery.kt").write_text(r'''package com.randotone.app

import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.service.notification.NotificationListenerService
import java.util.concurrent.atomic.AtomicBoolean

object ListenerRecovery {
    private const val PREFS = "listener_recovery"
    private const val KEY_LAST_REQUEST = "last_request"
    private const val KEY_LAST_REQUEST_KIND = "last_request_kind"
    private const val KEY_LAST_REASON = "last_reason"
    private const val KEY_LAST_CONNECTED = "last_connected"
    private const val KEY_LAST_DISCONNECTED = "last_disconnected"
    private const val KEY_LAST_HARD_ATTEMPT = "last_hard_attempt"

    private const val HEALTH_GRACE_MS = 2500L
    private const val HARD_REBIND_GAP_MS = 750L
    private const val HARD_THROTTLE_MS = 5000L

    private val connectedInThisProcess = AtomicBoolean(false)
    private val hardRecoveryInFlight = AtomicBoolean(false)
    private val mainHandler by lazy { Handler(Looper.getMainLooper()) }

    fun isConnectedInThisProcess(): Boolean = connectedInThisProcess.get()

    fun onProcessStart(context: Context) {
        val app = context.applicationContext
        connectedInThisProcess.set(false)
        if (!hasNotificationListenerAccess(app)) {
            OsineLog.event(app, "HEALTH", "process-start access=false; no recovery scheduled")
            return
        }
        scheduleHealthCheck(app, "process-start")
    }

    fun requestRebind(context: Context, reason: String): Boolean {
        val app = context.applicationContext
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            OsineLog.event(app, "REBIND", "soft-rebind skipped reason=$reason sdk-too-old")
            return false
        }
        if (!hasNotificationListenerAccess(app)) {
            OsineLog.event(app, "REBIND", "soft-rebind skipped reason=$reason notification-access=false")
            return false
        }

        val component = ComponentName(app, RandoToneNotificationListener::class.java)
        return runCatching {
            OsineLog.event(app, "REBIND", "soft-rebind submit reason=$reason")
            NotificationListenerService.requestRebind(component)
            recordRequest(app, "soft-rebind", reason)
            OsineLog.event(app, "REBIND", "soft-rebind submitted reason=$reason awaiting onListenerConnected")
            true
        }.onFailure { error ->
            OsineLog.event(app, "REBIND", "soft-rebind failed reason=$reason", error)
        }.getOrDefault(false)
    }

    fun scheduleHealthCheck(context: Context, reason: String, delayMs: Long = HEALTH_GRACE_MS) {
        val app = context.applicationContext
        if (!hasNotificationListenerAccess(app)) return
        OsineLog.event(app, "HEALTH", "check scheduled reason=$reason delayMs=$delayMs")
        mainHandler.postDelayed({
            if (connectedInThisProcess.get()) {
                OsineLog.event(app, "HEALTH", "check healthy reason=$reason listener-connected=true")
            } else {
                OsineLog.event(app, "HEALTH", "check failed reason=$reason listener-connected=false; escalating")
                requestHardRecovery(app, "health-$reason")
            }
        }, delayMs)
    }

    fun requestHardRecovery(context: Context, reason: String): Boolean {
        val app = context.applicationContext
        if (!canAttemptHardRecovery(app, reason)) return false
        if (!hardRecoveryInFlight.compareAndSet(false, true)) {
            OsineLog.event(app, "RECOVERY", "hard-recovery skipped reason=$reason already-in-flight")
            return false
        }

        Thread({
            try {
                performHardRecoveryBlocking(app, reason)
            } finally {
                hardRecoveryInFlight.set(false)
            }
        }, "osine-listener-recovery").start()
        return true
    }

    fun hardRecoverForReceiver(context: Context, reason: String): Boolean {
        val app = context.applicationContext
        if (!canAttemptHardRecovery(app, reason)) return false
        if (!hardRecoveryInFlight.compareAndSet(false, true)) {
            OsineLog.event(app, "RECOVERY", "receiver hard-recovery skipped reason=$reason already-in-flight")
            return false
        }
        return try {
            performHardRecoveryBlocking(app, reason)
        } finally {
            hardRecoveryInFlight.set(false)
        }
    }

    private fun canAttemptHardRecovery(context: Context, reason: String): Boolean {
        if (!hasNotificationListenerAccess(context)) {
            OsineLog.event(context, "RECOVERY", "hard-recovery skipped reason=$reason notification-access=false")
            return false
        }
        if (connectedInThisProcess.get()) {
            OsineLog.event(context, "RECOVERY", "hard-recovery skipped reason=$reason listener-already-connected")
            return false
        }

        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val now = System.currentTimeMillis()
        val last = prefs.getLong(KEY_LAST_HARD_ATTEMPT, 0L)
        if (last > 0L && now - last < HARD_THROTTLE_MS) {
            OsineLog.event(context, "RECOVERY", "hard-recovery throttled reason=$reason ageMs=${now - last}")
            return false
        }
        prefs.edit().putLong(KEY_LAST_HARD_ATTEMPT, now).apply()
        return true
    }

    private fun performHardRecoveryBlocking(context: Context, reason: String): Boolean {
        val component = ComponentName(context, RandoToneNotificationListener::class.java)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            return runCatching {
                OsineLog.event(context, "RECOVERY", "hard-unbind submit reason=$reason")
                NotificationListenerService.requestUnbind(component)
                OsineLog.event(context, "RECOVERY", "hard-unbind submitted reason=$reason")

                SystemClock.sleep(HARD_REBIND_GAP_MS)

                OsineLog.event(context, "RECOVERY", "hard-rebind submit reason=$reason")
                NotificationListenerService.requestRebind(component)
                recordRequest(context, "hard-unbind-rebind", reason)
                OsineLog.event(context, "RECOVERY", "hard-rebind submitted reason=$reason awaiting onListenerConnected")
                true
            }.onFailure { error ->
                OsineLog.event(context, "RECOVERY", "hard-recovery failed reason=$reason", error)
            }.getOrDefault(false)
        }

        // API 24-33 has static requestRebind(), but no static component requestUnbind().
        // Do not fake a component toggle here; stay on the documented soft path.
        OsineLog.event(context, "RECOVERY", "hard-recovery unavailable sdk=${Build.VERSION.SDK_INT}; falling back to soft-rebind")
        return requestRebind(context, "hard-fallback-$reason")
    }

    private fun recordRequest(context: Context, kind: String, reason: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putLong(KEY_LAST_REQUEST, System.currentTimeMillis())
            .putString(KEY_LAST_REQUEST_KIND, kind)
            .putString(KEY_LAST_REASON, reason)
            .apply()
    }

    fun markConnected(context: Context) {
        val app = context.applicationContext
        connectedInThisProcess.set(true)
        val prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val now = System.currentTimeMillis()
        val requestAt = prefs.getLong(KEY_LAST_REQUEST, 0L)
        val requestKind = prefs.getString(KEY_LAST_REQUEST_KIND, "none") ?: "none"
        val reason = prefs.getString(KEY_LAST_REASON, "none") ?: "none"
        val age = if (requestAt > 0L) now - requestAt else -1L
        prefs.edit().putLong(KEY_LAST_CONNECTED, now).apply()
        OsineLog.event(app, "HEALTH", "connection confirmed lastRequest=$requestKind reason=$reason ageMs=$age")
    }

    fun markDisconnected(context: Context) {
        val app = context.applicationContext
        connectedInThisProcess.set(false)
        app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putLong(KEY_LAST_DISCONNECTED, System.currentTimeMillis())
            .apply()
        OsineLog.event(app, "HEALTH", "listener marked disconnected")
    }

    fun markProcessListenerGone(context: Context, reason: String) {
        connectedInThisProcess.set(false)
        OsineLog.event(context.applicationContext, "HEALTH", "listener object gone reason=$reason")
    }
}
''', encoding="utf-8")

# A BroadcastReceiver process may be reclaimed after onReceive returns. goAsync keeps the
# receiver work alive long enough for the documented unbind -> short gap -> rebind experiment.
(kotlin / "ListenerRecoveryReceiver.kt").write_text(r'''package com.randotone.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class ListenerRecoveryReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val app = context.applicationContext
        val reason = when (intent?.action) {
            Intent.ACTION_BOOT_COMPLETED -> "boot-completed"
            Intent.ACTION_USER_UNLOCKED -> "user-unlocked"
            Intent.ACTION_MY_PACKAGE_REPLACED -> "package-replaced"
            else -> "recovery-broadcast"
        }
        OsineLog.event(app, "RECEIVER", "action=${intent?.action ?: "null"} reason=$reason")

        val pending = goAsync()
        Thread({
            try {
                ListenerRecovery.hardRecoverForReceiver(app, reason)
            } finally {
                pending.finish()
            }
        }, "osine-recovery-receiver").start()
    }
}
''', encoding="utf-8")

# Every new process now schedules a health check. If Android binds the NLS normally, the check
# becomes a no-op. If the process is alive but the listener never connects, v0.5 escalates.
(kotlin / "OsineApplication.kt").write_text(r'''package com.randotone.app

import android.app.Application

class OsineApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        OsineLog.startSession(this)
        ListenerRecovery.onProcessStart(this)
    }
}
''', encoding="utf-8")

listener = kotlin / "RandoToneNotificationListener.kt"
listener_text = listener.read_text(encoding="utf-8")

# Escalate if the documented disconnect callback happens and a soft rebind does not reconnect.
needle = '        ListenerRecovery.requestRebind(applicationContext, "listener-disconnected")\n'
if needle in listener_text and 'scheduleHealthCheck(applicationContext, "listener-disconnected")' not in listener_text:
    listener_text = listener_text.replace(
        needle,
        needle + '        ListenerRecovery.scheduleHealthCheck(applicationContext, "listener-disconnected")\n',
        1,
    )

# The v0.4 CI hotfix created these callbacks. Record process-local health state as well as logs.
listener_text = listener_text.replace(
    '''    override fun onDestroy() {\n        OsineLog.event(applicationContext, "NLS", "onDestroy")\n''',
    '''    override fun onDestroy() {\n        ListenerRecovery.markProcessListenerGone(applicationContext, "onDestroy")\n        OsineLog.event(applicationContext, "NLS", "onDestroy")\n''',
    1,
)
listener_text = listener_text.replace(
    '''    override fun onTaskRemoved(rootIntent: android.content.Intent?) {\n        OsineLog.event(applicationContext, "NLS", "onTaskRemoved")\n''',
    '''    override fun onTaskRemoved(rootIntent: android.content.Intent?) {\n        ListenerRecovery.markProcessListenerGone(applicationContext, "onTaskRemoved")\n        OsineLog.event(applicationContext, "NLS", "onTaskRemoved")\n''',
    1,
)
listener.write_text(listener_text, encoding="utf-8")

activity = kotlin / "MainActivity.kt"
activity_text = activity.read_text(encoding="utf-8")

# Manual repair is now the strong API-34 recovery experiment, not another soft requestRebind.
old_manual = 'onRepair = { ListenerRecovery.requestRebind(context, "manual-repair") },'
new_manual = 'onRepair = { ListenerRecovery.requestHardRecovery(context, "manual-repair") },'
if old_manual not in activity_text:
    raise SystemExit(f"{activity}: manual repair callback marker missing")
activity_text = activity_text.replace(old_manual, new_manual, 1)

activity_text = activity_text.replace(
    'Text("Repair / rebind listener")',
    'Text("Deep repair listener")',
    1,
)
activity_text = activity_text.replace(
    '"osine can request a listener rebind after disconnect, reboot, app update, and whenever this screen is reopened."',
    '"Deep repair uses Android 14+ component unbind → rebind and only counts success when onListenerConnected arrives."',
    1,
)
activity_text = activity_text.replace(
    '"v0.3 prototype • lifecycle hardening"',
    '"v0.5 prototype • verified listener recovery"',
    1,
)

# Add a standard battery-optimization settings shortcut. This does not silently change any setting.
diag_marker = '''        androidx.compose.material3.Text(\n            "Persistent rolling logs survive process death, Recents swipe, force-stop and reboot. Notification message text is never recorded.",\n            style = androidx.compose.material3.MaterialTheme.typography.bodySmall\n        )\n'''
if diag_marker not in activity_text:
    raise SystemExit(f"{activity}: diagnostics text marker missing")

battery_block = diag_marker + r'''        val batteryUnrestricted = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.M) {
            val power = context.getSystemService(android.content.Context.POWER_SERVICE) as android.os.PowerManager
            power.isIgnoringBatteryOptimizations(context.packageName)
        } else true
        if (!batteryUnrestricted) {
            androidx.compose.material3.Text(
                "Android reports osine as battery-optimized. On aggressive Android builds, changing osine to Unrestricted / Not optimized may improve survival after a Recents swipe.",
                style = androidx.compose.material3.MaterialTheme.typography.bodySmall
            )
            androidx.compose.material3.OutlinedButton(
                onClick = {
                    runCatching {
                        context.startActivity(
                            android.content.Intent(android.provider.Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
                                .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
                        )
                    }.onFailure {
                        context.startActivity(
                            android.content.Intent(
                                android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                                android.net.Uri.parse("package:${context.packageName}")
                            ).addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
                        )
                    }
                }
            ) {
                androidx.compose.material3.Text("Battery optimisation settings")
            }
        }
'''
activity_text = activity_text.replace(diag_marker, battery_block, 1)
activity.write_text(activity_text, encoding="utf-8")

print(f"Patched osine v0.5 verified recovery source in {project}")
