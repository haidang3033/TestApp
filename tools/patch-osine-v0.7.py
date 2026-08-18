#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch-osine-v0.7.py <project-dir>")

project = Path(sys.argv[1]).resolve()
app = project / "app"
src = app / "src" / "main"
kotlin = src / "java" / "com" / "randotone" / "app"

# Version bump.
build = app / "build.gradle.kts"
text = build.read_text(encoding="utf-8")
text = re.sub(r"versionCode\s*=\s*\d+", "versionCode = 7", text)
text = re.sub(r"versionName\s*=\s*\"[^\"]+\"", 'versionName = "0.7.0"', text)
build.write_text(text, encoding="utf-8")

# Direct-Boot aware boot receiver + keep-alive service.
manifest = src / "AndroidManifest.xml"
mt = manifest.read_text(encoding="utf-8")

# Receiver can run before first unlock.
receiver_pat = re.compile(r'(<receiver\s+\n\s*android:name="\.ListenerRecoveryReceiver"[\s\S]*?)(>)', re.M)
m = receiver_pat.search(mt)
if not m:
    raise SystemExit(f"{manifest}: ListenerRecoveryReceiver block missing")
receiver_head = m.group(1)
if 'android:directBootAware="true"' not in receiver_head:
    receiver_head += '\n            android:directBootAware="true"'
mt = mt[:m.start()] + receiver_head + m.group(2) + mt[m.end():]

if 'android.intent.action.LOCKED_BOOT_COMPLETED' not in mt:
    marker = '<action android:name="android.intent.action.BOOT_COMPLETED" />'
    if marker not in mt:
        raise SystemExit(f"{manifest}: BOOT_COMPLETED marker missing")
    mt = mt.replace(
        marker,
        '<action android:name="android.intent.action.LOCKED_BOOT_COMPLETED" />\n                ' + marker,
        1,
    )

# Keep-alive itself must also be eligible to run during Direct Boot.
service_pat = re.compile(r'(<service\s+\n\s*android:name="\.OsineKeepAliveService"[\s\S]*?)(>)', re.M)
m = service_pat.search(mt)
if not m:
    raise SystemExit(f"{manifest}: OsineKeepAliveService block missing")
service_head = m.group(1)
if 'android:directBootAware="true"' not in service_head:
    service_head += '\n            android:directBootAware="true"'
mt = mt[:m.start()] + service_head + m.group(2) + mt[m.end():]
manifest.write_text(mt, encoding="utf-8")

# Only the master ON/OFF bit is duplicated into device-protected storage. No pool names,
# notification contents, sound URIs or history are moved into Direct-Boot storage.
(kotlin / "OsineBootState.kt").write_text(r'''package com.randotone.app

import android.content.Context
import android.os.Build
import android.os.UserManager

object OsineBootState {
    private const val PREFS = "osine_direct_boot"
    private const val KEY_ENABLED = "roulette_enabled"

    private fun deviceContext(context: Context): Context =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            context.applicationContext.createDeviceProtectedStorageContext()
        } else {
            context.applicationContext
        }

    fun setEnabled(context: Context, enabled: Boolean) {
        deviceContext(context)
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_ENABLED, enabled)
            .commit()
    }

    fun isEnabled(context: Context): Boolean =
        deviceContext(context)
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getBoolean(KEY_ENABLED, false)

    fun isUserUnlocked(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return true
        val manager = context.applicationContext.getSystemService(Context.USER_SERVICE) as UserManager
        return manager.isUserUnlocked
    }
}
''', encoding="utf-8")

# Application.onCreate can run because a Direct-Boot component was instantiated. Do not touch
# credential-protected logs/preferences until the user has unlocked the device.
(kotlin / "OsineApplication.kt").write_text(r'''package com.randotone.app

import android.app.Application

class OsineApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        if (!OsineBootState.isUserUnlocked(this)) {
            return
        }
        OsineLog.startSession(this)
        OsineOperation.init(this)
        ListenerRecovery.onProcessStart(this)
    }
}
''', encoding="utf-8")

# Make the operation flag readable during Direct Boot and mirror every normal-state change into
# device-protected storage.
operation = kotlin / "OsineOperation.kt"
ot = operation.read_text(encoding="utf-8")
old_init = '''        appContext = app\n        migrateLegacyStateIfNeeded(app)\n'''
new_init = '''        appContext = app\n        migrateLegacyStateIfNeeded(app)\n        // Keep only the master power bit available before first unlock.\n        OsineBootState.setEnabled(app,\n            app.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY_ENABLED, false)\n        )\n'''
if old_init not in ot:
    raise SystemExit(f"{operation}: init marker missing")
ot = ot.replace(old_init, new_init, 1)

old_enabled = '''    fun isEnabled(context: Context): Boolean =\n        context.applicationContext\n            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)\n            .getBoolean(KEY_ENABLED, false)\n'''
new_enabled = '''    fun isEnabled(context: Context): Boolean {\n        val app = context.applicationContext\n        return if (OsineBootState.isUserUnlocked(app)) {\n            app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)\n                .getBoolean(KEY_ENABLED, false)\n        } else {\n            OsineBootState.isEnabled(app)\n        }\n    }\n'''
if old_enabled not in ot:
    raise SystemExit(f"{operation}: isEnabled marker missing")
ot = ot.replace(old_enabled, new_enabled, 1)

commit_marker = '''        app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)\n            .edit()\n            .putBoolean(KEY_ENABLED, enabled)\n            .commit()\n        OsineLog.event(app, "OPERATION", "roulette-enabled=$enabled reason=$reason")\n'''
commit_repl = '''        app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)\n            .edit()\n            .putBoolean(KEY_ENABLED, enabled)\n            .commit()\n        OsineBootState.setEnabled(app, enabled)\n        OsineLog.event(app, "OPERATION", "roulette-enabled=$enabled reason=$reason")\n'''
if commit_marker not in ot:
    raise SystemExit(f"{operation}: setEnabled persistence marker missing")
ot = ot.replace(commit_marker, commit_repl, 1)
operation.write_text(ot, encoding="utf-8")

# Boot receiver: LOCKED_BOOT_COMPLETED only starts the already-authorized keep-alive using the
# device-protected master bit. All listener recovery waits for unlocked storage/system state.
(kotlin / "ListenerRecoveryReceiver.kt").write_text(r'''package com.randotone.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class ListenerRecoveryReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val app = context.applicationContext
        val action = intent?.action

        if (action == Intent.ACTION_LOCKED_BOOT_COMPLETED) {
            if (!OsineBootState.isEnabled(app)) return
            OsineKeepAliveService.startIfEnabled(app, "locked-boot-completed")
            return
        }

        // From here onward the user is expected to be unlocked, so normal osine state/logging
        // is available. Re-initialize because this process may have originally started in
        // Direct Boot and Application.onCreate intentionally skipped credential storage.
        if (!OsineBootState.isUserUnlocked(app)) return
        OsineOperation.init(app)

        val reason = when (action) {
            Intent.ACTION_BOOT_COMPLETED -> "boot-completed"
            Intent.ACTION_USER_UNLOCKED -> "user-unlocked"
            Intent.ACTION_MY_PACKAGE_REPLACED -> "package-replaced"
            else -> "recovery-broadcast"
        }
        OsineLog.event(app, "RECEIVER", "action=${action ?: "null"} reason=$reason")

        if (!OsineOperation.isEnabled(app)) {
            OsineLog.event(app, "RECEIVER", "ignored reason=$reason roulette-off")
            OsineKeepAliveService.stop(app, "receiver-roulette-off")
            return
        }

        OsineKeepAliveService.startIfEnabled(app, reason)

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

# Replace keep-alive with a Direct-Boot-safe equivalent. If Xiaomi delays BOOT_COMPLETED, the
# already-running foreground service polls UserManager and performs the post-unlock rebind itself.
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
    private var createdWhileLocked = false
    private var unlockedRuntimeInitialized = false

    private val watchdog = object : Runnable {
        override fun run() {
            if (!OsineOperation.isEnabled(applicationContext)) {
                safeLog("KEEPALIVE", "watchdog sees roulette-off; stopping service")
                stopSelf()
                return
            }

            if (!OsineBootState.isUserUnlocked(applicationContext)) {
                handler.postDelayed(this, LOCKED_POLL_MS)
                return
            }

            ensureUnlockedRuntime()

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
        createdWhileLocked = !OsineBootState.isUserUnlocked(applicationContext)
        safeLog("KEEPALIVE", "onCreate directBoot=$createdWhileLocked")
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!OsineOperation.isEnabled(applicationContext)) {
            safeLog("KEEPALIVE", "start rejected roulette-off")
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

        if (OsineBootState.isUserUnlocked(applicationContext)) {
            ensureUnlockedRuntime()
        }

        handler.removeCallbacks(watchdog)
        handler.postDelayed(watchdog, INITIAL_WATCHDOG_MS)
        safeLog("KEEPALIVE", "foreground active reason=${intent?.getStringExtra(EXTRA_REASON) ?: "system-restart"}")
        return START_STICKY
    }

    private fun ensureUnlockedRuntime() {
        if (unlockedRuntimeInitialized || !OsineBootState.isUserUnlocked(applicationContext)) return
        unlockedRuntimeInitialized = true

        // Application.onCreate may have run in Direct Boot and intentionally skipped this work.
        OsineOperation.init(applicationContext)
        if (createdWhileLocked) {
            OsineLog.startSession(applicationContext)
            OsineLog.event(applicationContext, "KEEPALIVE", "user unlocked; Direct-Boot runtime promoted")
        }
        ListenerRecovery.requestRebind(applicationContext, "keepalive-user-unlocked")
        ListenerRecovery.scheduleHealthCheck(applicationContext, "keepalive-user-unlocked")
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        safeLog("KEEPALIVE", "onTaskRemoved; service remains active")
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        safeLog("KEEPALIVE", "onDestroy")
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun safeLog(tag: String, message: String) {
        if (OsineBootState.isUserUnlocked(applicationContext)) {
            OsineLog.event(applicationContext, tag, message)
        }
    }

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
        private const val INITIAL_WATCHDOG_MS = 2500L
        private const val LOCKED_POLL_MS = 2000L
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
                if (OsineBootState.isUserUnlocked(app)) {
                    OsineLog.event(app, "KEEPALIVE", "start submitted reason=$reason")
                }
            }.onFailure {
                if (OsineBootState.isUserUnlocked(app)) {
                    OsineLog.event(app, "KEEPALIVE", "start failed reason=$reason", it)
                }
            }
        }

        fun stop(context: Context, reason: String) {
            val app = context.applicationContext
            runCatching {
                val stopped = app.stopService(Intent(app, OsineKeepAliveService::class.java))
                if (OsineBootState.isUserUnlocked(app)) {
                    OsineLog.event(app, "KEEPALIVE", "stop submitted reason=$reason stopped=$stopped")
                }
            }.onFailure {
                if (OsineBootState.isUserUnlocked(app)) {
                    OsineLog.event(app, "KEEPALIVE", "stop failed reason=$reason", it)
                }
            }
        }
    }
}
''', encoding="utf-8")

# Version label only. Keep UI surgery minimal for this lifecycle build.
activity = kotlin / "MainActivity.kt"
at = activity.read_text(encoding="utf-8")
at = at.replace(
    '"v0.6 prototype • foreground survival"',
    '"v0.7 prototype • Direct Boot survival"',
    1,
)
activity.write_text(at, encoding="utf-8")

print(f"Patched osine v0.7 Direct Boot source in {project}")
