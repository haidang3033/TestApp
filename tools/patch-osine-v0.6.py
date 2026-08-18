#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch-osine-v0.6.py <project-dir>")

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


# v0.6: keep the stable package/signing identity, add foreground survival semantics.
build = app / "build.gradle.kts"
text = build.read_text(encoding="utf-8")
text = re.sub(r"versionCode\s*=\s*\d+", "versionCode = 6", text)
text = re.sub(r"versionName\s*=\s*\"[^\"]+\"", 'versionName = "0.6.0"', text)
build.write_text(text, encoding="utf-8")

# Foreground service permissions + specialUse declaration. The service intentionally does NOT
# stop with the Activity task, so a normal Recents swipe does not disable an enabled roulette.
manifest = src / "AndroidManifest.xml"
manifest_text = manifest.read_text(encoding="utf-8")

for permission in (
    "android.permission.FOREGROUND_SERVICE",
    "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
):
    if permission not in manifest_text:
        manifest_text, count = re.subn(
            r'(<manifest\s+xmlns:android="http://schemas.android.com/apk/res/android"\s*>)',
            r'\1\n\n    <uses-permission android:name="' + permission + r'" />',
            manifest_text,
            count=1,
        )
        if count != 1:
            raise SystemExit(f"{manifest}: could not add {permission}")

if 'android:name=".OsineKeepAliveService"' not in manifest_text:
    service_block = '''        <service
            android:name=".OsineKeepAliveService"
            android:enabled="true"
            android:exported="false"
            android:stopWithTask="false"
            android:foregroundServiceType="specialUse">
            <property
                android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"
                android:value="Keeps the user-enabled osine notification sound roulette alive after the UI task is dismissed and monitors notification-listener health." />
        </service>

'''
    marker = re.search(
        r'(?m)^\s*<service\s*\n\s*android:name="\.RandoToneNotificationListener"',
        manifest_text,
    )
    if not marker:
        raise SystemExit(f"{manifest}: notification-listener service marker missing")
    manifest_text = manifest_text[:marker.start()] + service_block + manifest_text[marker.start():]

manifest.write_text(manifest_text, encoding="utf-8")

# Master operation state. This is deliberately separate from notification-access permission:
# roulette OFF means foreground service OFF, recovery OFF, boot resurrection OFF, listener
# processing OFF. The preference mirrors the existing RandoToneState toggle.
(kotlin / "OsineOperation.kt").write_text(r'''package com.randotone.app

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.service.notification.NotificationListenerService

object OsineOperation {
    private const val PREFS = "osine_operation"
    private const val KEY_ENABLED = "roulette_enabled"
    @Volatile private var appContext: Context? = null

    fun init(context: Context) {
        val app = context.applicationContext
        appContext = app
        migrateLegacyStateIfNeeded(app)
    }

    fun isEnabled(context: Context): Boolean =
        context.applicationContext
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getBoolean(KEY_ENABLED, false)

    fun setEnabledFromState(enabled: Boolean) {
        val app = appContext ?: return
        setEnabled(app, enabled, "state-toggle")
    }

    fun setEnabled(context: Context, enabled: Boolean, reason: String) {
        val app = context.applicationContext
        appContext = app
        // commit() is intentional: OFF must become visible to listener/recovery threads before
        // teardown begins, so a delayed rebind cannot race the master switch.
        app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_ENABLED, enabled)
            .commit()
        OsineLog.event(app, "OPERATION", "roulette-enabled=$enabled reason=$reason")

        if (enabled) {
            OsineKeepAliveService.startIfEnabled(app, reason)
            ListenerRecovery.requestRebind(app, "operation-on-$reason")
            ListenerRecovery.scheduleHealthCheck(app, "operation-on-$reason")
        } else {
            ListenerRecovery.cancelPending(app, "operation-off-$reason")
            requestListenerUnbind(app, "operation-off-$reason")
            OsineKeepAliveService.stop(app, reason)
        }
    }

    fun mirrorInitialState(enabled: Boolean) {
        val app = appContext ?: return
        val prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (!prefs.contains(KEY_ENABLED)) {
            prefs.edit().putBoolean(KEY_ENABLED, enabled).commit()
            OsineLog.event(app, "OPERATION", "initial roulette state mirrored enabled=$enabled")
        }
    }

    private fun migrateLegacyStateIfNeeded(context: Context) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (prefs.contains(KEY_ENABLED)) return

        // v0.5 and older did not have a separate operation preference. Best-effort migration
        // reads the existing RandoToneState getter without hard-coding its SharedPreferences key.
        val migrated = runCatching {
            val clazz = RandoToneState::class.java
            val ctor = clazz.declaredConstructors.firstOrNull { constructor ->
                constructor.parameterCount == 1 &&
                    constructor.parameterTypes[0].isAssignableFrom(context.javaClass)
            } ?: clazz.declaredConstructors.firstOrNull { constructor ->
                constructor.parameterCount == 1 &&
                    android.content.Context::class.java.isAssignableFrom(constructor.parameterTypes[0])
            } ?: clazz.declaredConstructors.firstOrNull { it.parameterCount == 0 }
                ?: return@runCatching null

            ctor.isAccessible = true
            val instance = when (ctor.parameterCount) {
                0 -> ctor.newInstance()
                1 -> ctor.newInstance(context)
                else -> null
            } ?: return@runCatching null

            val getter = clazz.methods.firstOrNull {
                it.parameterCount == 0 &&
                    (it.name == "getNotificationEnabled" || it.name == "isNotificationEnabled")
            } ?: return@runCatching null
            getter.invoke(instance) as? Boolean
        }.getOrNull()

        if (migrated != null) {
            prefs.edit().putBoolean(KEY_ENABLED, migrated).commit()
            OsineLog.event(context, "OPERATION", "migrated v0.5 roulette state enabled=$migrated")
        } else {
            // Safe migration default: do not create an always-on service unless the prior state
            // can be proven. Opening osine and touching the toggle establishes the new state.
            prefs.edit().putBoolean(KEY_ENABLED, false).commit()
            OsineLog.event(context, "OPERATION", "legacy roulette state unavailable; safe default enabled=false")
        }
    }

    private fun requestListenerUnbind(context: Context, reason: String) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            val component = ComponentName(context, RandoToneNotificationListener::class.java)
            runCatching {
                NotificationListenerService.requestUnbind(component)
                OsineLog.event(context, "OPERATION", "listener unbind submitted reason=$reason")
            }.onFailure {
                OsineLog.event(context, "OPERATION", "listener unbind failed reason=$reason", it)
            }
        } else {
            OsineLog.event(context, "OPERATION", "listener static unbind unavailable sdk=${Build.VERSION.SDK_INT}; listener remains passive")
        }
    }
}
''', encoding="utf-8")

# Persistent foreground service. It exists only while the roulette master switch is ON.
(kotlin / "OsineKeepAliveService.kt").write_text(r'''package com.randotone.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper

class OsineKeepAliveService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private val watchdog = object : Runnable {
        override fun run() {
            if (!OsineOperation.isEnabled(applicationContext)) {
                OsineLog.event(applicationContext, "KEEPALIVE", "watchdog sees roulette-off; stopping service")
                stopSelf()
                return
            }

            if (hasNotificationListenerAccess(applicationContext) &&
                !ListenerRecovery.isConnectedInThisProcess()
            ) {
                OsineLog.event(applicationContext, "KEEPALIVE", "watchdog listener-connected=false; requesting recovery")
                ListenerRecovery.requestHardRecovery(applicationContext, "keepalive-watchdog")
            }
            handler.postDelayed(this, WATCHDOG_MS)
        }
    }

    override fun onCreate() {
        super.onCreate()
        OsineLog.event(applicationContext, "KEEPALIVE", "onCreate")
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!OsineOperation.isEnabled(applicationContext)) {
            OsineLog.event(applicationContext, "KEEPALIVE", "start rejected roulette-off")
            stopSelf()
            return START_NOT_STICKY
        }

        val notification = buildNotification()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }

        handler.removeCallbacks(watchdog)
        handler.postDelayed(watchdog, INITIAL_WATCHDOG_MS)
        OsineLog.event(applicationContext, "KEEPALIVE", "foreground active reason=${intent?.getStringExtra(EXTRA_REASON) ?: "system-restart"}")
        return START_STICKY
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Deliberately do not stop: dismissing the UI task is not the same as turning roulette off.
        OsineLog.event(applicationContext, "KEEPALIVE", "onTaskRemoved; service remains active")
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        OsineLog.event(applicationContext, "KEEPALIVE", "onDestroy")
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(
            CHANNEL_ID,
            "osine active service",
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "Keeps notification sound roulette active when osine's window is closed."
            setSound(null, null)
            enableVibration(false)
            setShowBadge(false)
        }
        manager.createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification {
        val openIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val pending = PendingIntent.getActivity(
            this,
            0,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            Notification.Builder(this)
        }
        return builder
            .setSmallIcon(android.R.drawable.stat_notify_sync_noanim)
            .setContentTitle("osine is active")
            .setContentText("Notification sound roulette is running")
            .setContentIntent(pending)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .build()
    }

    companion object {
        private const val CHANNEL_ID = "osine_keepalive"
        private const val NOTIFICATION_ID = 0x0519E
        private const val EXTRA_REASON = "reason"
        private const val INITIAL_WATCHDOG_MS = 5000L
        private const val WATCHDOG_MS = 30000L

        fun startIfEnabled(context: Context, reason: String) {
            val app = context.applicationContext
            if (!OsineOperation.isEnabled(app)) return
            val intent = Intent(app, OsineKeepAliveService::class.java)
                .putExtra(EXTRA_REASON, reason)
            runCatching {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    app.startForegroundService(intent)
                } else {
                    app.startService(intent)
                }
                OsineLog.event(app, "KEEPALIVE", "start submitted reason=$reason")
            }.onFailure {
                OsineLog.event(app, "KEEPALIVE", "start failed reason=$reason", it)
            }
        }

        fun stop(context: Context, reason: String) {
            val app = context.applicationContext
            runCatching {
                val stopped = app.stopService(Intent(app, OsineKeepAliveService::class.java))
                OsineLog.event(app, "KEEPALIVE", "stop submitted reason=$reason stopped=$stopped")
            }.onFailure {
                OsineLog.event(app, "KEEPALIVE", "stop failed reason=$reason", it)
            }
        }
    }
}
''', encoding="utf-8")

# Recovery helper with a hard master gate. Every delayed callback checks the flag again, including
# the gap between hard unbind and rebind, so OFF cannot be followed by a zombie rebind.
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
        if (!OsineOperation.isEnabled(app)) {
            OsineLog.event(app, "HEALTH", "process-start roulette-off; no recovery scheduled")
            return
        }
        if (!hasNotificationListenerAccess(app)) {
            OsineLog.event(app, "HEALTH", "process-start access=false; no recovery scheduled")
            return
        }
        scheduleHealthCheck(app, "process-start")
    }

    fun cancelPending(context: Context, reason: String) {
        mainHandler.removeCallbacksAndMessages(null)
        OsineLog.event(context.applicationContext, "HEALTH", "pending recovery callbacks cancelled reason=$reason")
    }

    fun requestRebind(context: Context, reason: String): Boolean {
        val app = context.applicationContext
        if (!OsineOperation.isEnabled(app)) {
            OsineLog.event(app, "REBIND", "soft-rebind skipped reason=$reason roulette-off")
            return false
        }
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
        if (!OsineOperation.isEnabled(app)) return
        if (!hasNotificationListenerAccess(app)) return
        OsineLog.event(app, "HEALTH", "check scheduled reason=$reason delayMs=$delayMs")
        mainHandler.postDelayed({
            if (!OsineOperation.isEnabled(app)) {
                OsineLog.event(app, "HEALTH", "check cancelled-at-run reason=$reason roulette-off")
                return@postDelayed
            }
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
        if (!OsineOperation.isEnabled(context)) {
            OsineLog.event(context, "RECOVERY", "hard-recovery skipped reason=$reason roulette-off")
            return false
        }
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
        if (!OsineOperation.isEnabled(context)) return false
        val component = ComponentName(context, RandoToneNotificationListener::class.java)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            return runCatching {
                OsineLog.event(context, "RECOVERY", "hard-unbind submit reason=$reason")
                NotificationListenerService.requestUnbind(component)
                OsineLog.event(context, "RECOVERY", "hard-unbind submitted reason=$reason")

                SystemClock.sleep(HARD_REBIND_GAP_MS)
                if (!OsineOperation.isEnabled(context)) {
                    OsineLog.event(context, "RECOVERY", "hard-rebind cancelled reason=$reason roulette-off-during-gap")
                    return@runCatching false
                }

                OsineLog.event(context, "RECOVERY", "hard-rebind submit reason=$reason")
                NotificationListenerService.requestRebind(component)
                recordRequest(context, "hard-unbind-rebind", reason)
                OsineLog.event(context, "RECOVERY", "hard-rebind submitted reason=$reason awaiting onListenerConnected")
                true
            }.onFailure { error ->
                OsineLog.event(context, "RECOVERY", "hard-recovery failed reason=$reason", error)
            }.getOrDefault(false)
        }

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

# Gate boot/update recovery behind the master switch. BOOT_COMPLETED is also the one place where
# v0.6 intentionally starts the FGS from a receiver; Android permits that background-start case.
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

        if (!OsineOperation.isEnabled(app)) {
            OsineLog.event(app, "RECEIVER", "ignored reason=$reason roulette-off")
            return
        }

        if (intent?.action == Intent.ACTION_BOOT_COMPLETED) {
            OsineKeepAliveService.startIfEnabled(app, "boot-completed")
        }

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

# Process startup initializes/migrates the master state before any recovery scheduling.
(kotlin / "OsineApplication.kt").write_text(r'''package com.randotone.app

import android.app.Application

class OsineApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        OsineLog.startSession(this)
        OsineOperation.init(this)
        ListenerRecovery.onProcessStart(this)
    }
}
''', encoding="utf-8")

# The existing state setter remains the source of truth for the UI; mirror every explicit toggle
# into the master operation controller without changing its original persistence logic.
state = kotlin / "RandoToneState.kt"
state_text = state.read_text(encoding="utf-8")
if "OsineOperation.setEnabledFromState(enabled)" not in state_text:
    state_text, count = re.subn(
        r'(fun\s+updateNotificationEnabled\s*\(\s*enabled\s*:\s*Boolean\s*\)\s*\{)',
        r'\1\n        OsineOperation.setEnabledFromState(enabled)',
        state_text,
        count=1,
    )
    if count != 1:
        raise SystemExit(f"{state}: updateNotificationEnabled marker missing")
state.write_text(state_text, encoding="utf-8")

# Listener must be passive when OFF even if Android happens to bind it. If Android binds while
# OFF, immediately request instance unbind; posted notifications return before diagnostics/audio.
listener = kotlin / "RandoToneNotificationListener.kt"
listener_text = listener.read_text(encoding="utf-8")
if '"connected while roulette-off; requesting unbind"' not in listener_text:
    marker = '        ListenerRecovery.markConnected(applicationContext)\n'
    if marker not in listener_text:
        raise SystemExit(f"{listener}: markConnected marker missing")
    listener_text = listener_text.replace(
        marker,
        '''        if (!OsineOperation.isEnabled(applicationContext)) {
            OsineLog.event(applicationContext, "NLS", "connected while roulette-off; requesting unbind")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                runCatching { requestUnbind() }
            }
            return
        }
''' + marker,
        1,
    )

if 'if (!OsineOperation.isEnabled(applicationContext)) return' not in listener_text:
    posted = re.compile(r'(override\s+fun\s+onNotificationPosted\s*\([^)]*\)\s*\{)')
    match = posted.search(listener_text)
    if not match:
        raise SystemExit(f"{listener}: onNotificationPosted marker missing")
    listener_text = listener_text[:match.end()] + '\n        if (!OsineOperation.isEnabled(applicationContext)) return' + listener_text[match.end():]

listener.write_text(listener_text, encoding="utf-8")

# Activity launch is a user-visible FGS start opportunity, including after Force Stop. Existing
# soft-rebind calls are also gated so opening osine with roulette OFF does not wake the machinery.
activity = kotlin / "MainActivity.kt"
activity_text = activity.read_text(encoding="utf-8")
activity_text = activity_text.replace(
    '"v0.5 prototype • verified listener recovery"',
    '"v0.6 prototype • foreground survival"',
    1,
)

for lifecycle in ("activity-create", "activity-resume"):
    old = f'''        if (notificationAccessGranted) {{\n            ListenerRecovery.requestRebind(this, "{lifecycle}")\n        }}\n'''
    new = f'''        OsineKeepAliveService.startIfEnabled(this, "{lifecycle}")\n        if (notificationAccessGranted && OsineOperation.isEnabled(this)) {{\n            ListenerRecovery.requestRebind(this, "{lifecycle}")\n        }}\n'''
    if old not in activity_text:
        raise SystemExit(f"{activity}: lifecycle rebind marker missing for {lifecycle}")
    activity_text = activity_text.replace(old, new, 1)

# Make the semantics explicit next to the existing repair explanation.
semantic_marker = '"Deep repair uses Android 14+ component unbind → rebind and only counts success when onListenerConnected arrives.",'
if semantic_marker in activity_text and "Roulette OFF is a full shutdown" not in activity_text:
    activity_text = activity_text.replace(
        semantic_marker,
        semantic_marker + '''\n                    style = MaterialTheme.typography.bodySmall\n                )\n                Text(\n                    "Roulette ON keeps osine alive with a quiet foreground-service notification. Roulette OFF is a full shutdown: keep-alive, health checks and recovery stop together.",''',
        1,
    )
    # The replacement deliberately consumed the original style/close that follows the marker;
    # remove the now duplicated immediate style/close pair once.
    duplicate = '''\n                    style = MaterialTheme.typography.bodySmall\n                )\n                    style = MaterialTheme.typography.bodySmall\n                )\n'''
    activity_text = activity_text.replace(duplicate, '''\n                    style = MaterialTheme.typography.bodySmall\n                )\n''', 1)

activity.write_text(activity_text, encoding="utf-8")

print(f"Patched osine v0.6 foreground survival source in {project}")
