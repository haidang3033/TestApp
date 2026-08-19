#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: hotfix-notiflab-v0.4.1-diagnostics.py <project-dir>')

project = Path(sys.argv[1]).resolve()
app = project / 'app'
src = app / 'src' / 'main'
kt = src / 'java' / 'com' / 'randotone' / 'notiflab'


def replace_exact(path: Path, old: str, new: str, expected: int = 1):
    text = path.read_text(encoding='utf-8')
    count = text.count(old)
    if count != expected:
        raise SystemExit(f'{path}: expected {expected} marker(s), found {count}')
    path.write_text(text.replace(old, new, expected), encoding='utf-8')


# Diagnostic hotfix version. Keep package/signing identity stable for in-place install.
build = app / 'build.gradle.kts'
text = build.read_text(encoding='utf-8')
text = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 5', text)
text = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.4.1"', text)
build.write_text(text, encoding='utf-8')

# Persistent app-wide diagnostics + fatal exception recorder.
(kt / 'NotifLabLog.kt').write_text(r'''package com.randotone.notiflab

import android.content.Context
import android.os.Build
import android.util.Log
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object NotifLabLog {
    private const val DIR_NAME = "notiflab-diagnostics"
    private const val ACTIVE_NAME = "notiflab.log"
    private const val MAX_BYTES = 256L * 1024L
    private const val MAX_FILES = 4
    private val lock = Any()
    private val stamp = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US)

    private fun dir(context: Context): File = File(context.filesDir, DIR_NAME).apply { mkdirs() }
    private fun active(context: Context): File = File(dir(context), ACTIVE_NAME)

    fun startSession(context: Context) {
        val app = context.applicationContext
        event(app, "APP", "================ NotifLab session ================")
        val version = runCatching {
            val info = app.packageManager.getPackageInfo(app.packageName, 0)
            "${info.versionName ?: "?"} (${info.longVersionCode})"
        }.getOrDefault("unknown")
        event(app, "APP", "version=$version android=${Build.VERSION.RELEASE} sdk=${Build.VERSION.SDK_INT}")
        event(app, "APP", "device=${Build.MANUFACTURER} ${Build.MODEL}")
    }

    fun event(context: Context, tag: String, message: String, error: Throwable? = null) {
        val safeTag = tag.replace(Regex("[^A-Za-z0-9_-]"), "_").take(18)
        val clean = message.replace('\n', ' ').replace('\r', ' ')
        val line = "${stamp.format(Date())}  [$safeTag]  $clean"
        val stack = error?.let { Log.getStackTraceString(it) }
        synchronized(lock) {
            runCatching {
                val incoming = line.length + 1 + (stack?.length ?: 0)
                rotateIfNeeded(context, incoming)
                active(context).appendText(line + "\n", Charsets.UTF_8)
                if (!stack.isNullOrBlank()) {
                    active(context).appendText(stack + "\n", Charsets.UTF_8)
                }
            }
        }
    }

    private fun rotateIfNeeded(context: Context, incomingChars: Int) {
        val current = active(context)
        if (!current.exists() || current.length() + incomingChars <= MAX_BYTES) return
        val folder = dir(context)
        File(folder, "notiflab.${MAX_FILES - 1}.log").delete()
        for (index in (MAX_FILES - 2) downTo 1) {
            val from = File(folder, "notiflab.$index.log")
            if (from.exists()) from.renameTo(File(folder, "notiflab.${index + 1}.log"))
        }
        current.renameTo(File(folder, "notiflab.1.log"))
    }

    fun readAll(context: Context): String = synchronized(lock) {
        val folder = dir(context)
        val ordered = buildList {
            for (index in (MAX_FILES - 1) downTo 1) {
                val file = File(folder, "notiflab.$index.log")
                if (file.exists()) add(file)
            }
            active(context).takeIf { it.exists() }?.let(::add)
        }
        if (ordered.isEmpty()) "No NotifLab diagnostics have been recorded yet."
        else ordered.joinToString("\n") { file ->
            "----- ${file.name} -----\n${runCatching { file.readText(Charsets.UTF_8) }.getOrDefault("<unreadable>")}" 
        }
    }

    fun clear(context: Context) {
        synchronized(lock) {
            dir(context).listFiles()?.forEach { file ->
                if (file.name.startsWith("notiflab") && file.extension == "log") file.delete()
            }
        }
    }
}
''', encoding='utf-8')

(kt / 'NotifLabApplication.kt').write_text(r'''package com.randotone.notiflab

import android.app.Application
import android.os.Process

class NotifLabApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        NotifLabLog.startSession(this)

        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            runCatching {
                NotifLabLog.event(
                    applicationContext,
                    "FATAL",
                    "uncaught exception thread=${thread.name} type=${error.javaClass.name} message=${error.message ?: "<none>"}",
                    error
                )
            }
            if (previous != null) {
                previous.uncaughtException(thread, error)
            } else {
                Process.killProcess(Process.myPid())
            }
        }
    }
}
''', encoding='utf-8')

manifest = src / 'AndroidManifest.xml'
manifest_text = manifest.read_text(encoding='utf-8')
if 'android:name=".NotifLabApplication"' not in manifest_text:
    manifest_text, count = re.subn(
        r'<application\n(\s*)android:allowBackup=',
        r'<application\n\1android:name=".NotifLabApplication"\n\1android:allowBackup=',
        manifest_text,
        count=1,
    )
    if count != 1:
        raise SystemExit(f'{manifest}: application marker missing')
manifest.write_text(manifest_text, encoding='utf-8')

# Main screen gets a simple post-crash retrieval toolbox.
activity = kt / 'MainActivity.kt'
text = activity.read_text(encoding='utf-8')
text = text.replace(
    '        super.onCreate(savedInstanceState)\n        setContentView(buildUi())\n',
    '        super.onCreate(savedInstanceState)\n        NotifLabLog.event(applicationContext, "ACTIVITY", "MainActivity onCreate")\n        setContentView(buildUi())\n',
    1,
)
text = text.replace(
    '        super.onResume()\n        mainHandler.removeCallbacks(statusPoll)\n',
    '        super.onResume()\n        NotifLabLog.event(applicationContext, "ACTIVITY", "MainActivity onResume")\n        mainHandler.removeCallbacks(statusPoll)\n',
    1,
)
text = text.replace(
    'A notification firing range for osine. v0.4 adds a Fake Call Lab for ringtone-suppression and CallStyle experiments.',
    'A notification firing range for osine. v0.4.1 adds persistent crash diagnostics around the Fake Call Lab.',
    1,
)
marker = '''        root.addView(sectionTitle("Foreground service"))\n'''
diag = '''        root.addView(sectionTitle("Diagnostics"))\n        root.addView(button("Copy persistent diagnostics log") { copyDiagnostics() })\n        root.addView(button("Clear diagnostics log") {\n            NotifLabLog.clear(this)\n            NotifLabLog.startSession(this)\n            Toast.makeText(this, "Diagnostics cleared and new session started.", Toast.LENGTH_SHORT).show()\n        })\n        root.addView(TextView(this).apply {\n            text = "The log survives app crashes and normal relaunches. Reproduce the Call Lab crash, reopen NotifLab, then copy this log and send it back."\n            textSize = 13f\n            setPadding(0, dp(8), 0, dp(8))\n        })\n\n'''
if marker not in text:
    raise SystemExit(f'{activity}: foreground section marker missing')
text = text.replace(marker, diag + marker, 1)
method_marker = '''    private fun copyLanAddress() {\n'''
copy_method = '''    private fun copyDiagnostics() {\n        val diagnostics = NotifLabLog.readAll(this)\n        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager\n        clipboard.setPrimaryClip(ClipData.newPlainText("NotifLab diagnostics", diagnostics))\n        Toast.makeText(this, "NotifLab diagnostics copied.", Toast.LENGTH_SHORT).show()\n        NotifLabLog.event(applicationContext, "ACTIVITY", "diagnostics copied to clipboard chars=${diagnostics.length}")\n    }\n\n'''
if method_marker not in text:
    raise SystemExit(f'{activity}: copyLanAddress marker missing')
text = text.replace(method_marker, copy_method + method_marker, 1)
activity.write_text(text, encoding='utf-8')

# Replace Call Lab with heavily instrumented, exception-contained equivalent.
(kt / 'FakeCallLabActivity.kt').write_text(r'''package com.randotone.notiflab

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Person
import android.content.Intent
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

class FakeCallLabActivity : Activity() {
    private lateinit var manager: NotificationManager
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        NotifLabLog.event(applicationContext, "CALLLAB", "onCreate begin sdk=${Build.VERSION.SDK_INT}")
        manager = getSystemService(NotificationManager::class.java)
        setContentView(buildUi())
        ensureCallChannels("activity-create")
        NotifLabLog.event(applicationContext, "CALLLAB", "onCreate complete")
    }

    override fun onResume() {
        super.onResume()
        NotifLabLog.event(applicationContext, "CALLLAB", "onResume")
    }

    private fun buildUi(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(18), dp(18), dp(18), dp(28))

        addView(TextView(this@FakeCallLabActivity).apply {
            text = "NotifLab Fake Call Lab • diagnostic"
            textSize = 26f
        })
        addView(TextView(this@FakeCallLabActivity).apply {
            text = "v0.4.1 logs every call-notification construction stage. If a fake call fails, reopen NotifLab and copy the persistent diagnostics log."
            textSize = 14f
            setPadding(0, dp(6), 0, dp(16))
        })

        status = TextView(this@FakeCallLabActivity).apply {
            text = "Idle. Fake calls auto-timeout after 30 seconds."
            setPadding(0, 0, 0, dp(12))
        }
        addView(status)

        addView(button("Ring fake call • Android default ringtone") {
            postIncomingCall(withSourceRingtone = true)
        })
        addView(button("Ring fake call • silent source") {
            postIncomingCall(withSourceRingtone = false)
        })
        addView(button("End fake call") {
            runCatching {
                manager.cancel(FAKE_CALL_NOTIFICATION_ID)
                NotifLabLog.event(applicationContext, "CALLLAB", "manual cancel submitted")
                status.text = "Fake call ended from NotifLab."
            }.onFailure { fail("manual-cancel", it) }
        })
        addView(button("Open ringtone-channel settings") {
            runCatching {
                val intent = Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
                    .putExtra(Settings.EXTRA_CHANNEL_ID, CALL_RINGTONE_CHANNEL_ID)
                startActivity(intent)
            }.onFailure { fail("open-channel-settings", it) }
        })

        addView(TextView(this@FakeCallLabActivity).apply {
            text = "Ringtone mode uses Android's default ringtone URI + USAGE_NOTIFICATION_RINGTONE. Silent mode uses the same CallStyle shape with channel sound disabled."
            textSize = 13f
            setPadding(0, dp(14), 0, 0)
        })
    }

    private fun button(label: String, action: () -> Unit): Button = Button(this).apply {
        text = label
        isAllCaps = false
        gravity = Gravity.CENTER
        setOnClickListener {
            NotifLabLog.event(applicationContext, "CALLLAB", "button=$label")
            action()
        }
    }

    private fun ensureCallChannels(reason: String): Boolean = runCatching {
        NotifLabLog.event(applicationContext, "CALLLAB", "create channels begin reason=$reason")
        createCallChannels()
        val ring = manager.getNotificationChannel(CALL_RINGTONE_CHANNEL_ID)
        val silent = manager.getNotificationChannel(CALL_SILENT_CHANNEL_ID)
        NotifLabLog.event(
            applicationContext,
            "CALLLAB",
            "ring channel id=${ring?.id} importance=${ring?.importance} sound=${ring?.sound} usage=${ring?.audioAttributes?.usage} vibration=${ring?.shouldVibrate()}"
        )
        NotifLabLog.event(
            applicationContext,
            "CALLLAB",
            "silent channel id=${silent?.id} importance=${silent?.importance} sound=${silent?.sound} usage=${silent?.audioAttributes?.usage} vibration=${silent?.shouldVibrate()}"
        )
        true
    }.onFailure { fail("create-channels-$reason", it) }.getOrDefault(false)

    private fun createCallChannels() {
        val ringtoneUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
        NotifLabLog.event(applicationContext, "CALLLAB", "default ringtone uri=$ringtoneUri")
        val ringtoneAttributes = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()

        val ringtone = NotificationChannel(
            CALL_RINGTONE_CHANNEL_ID,
            "Fake calls • system ringtone",
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = "NotifLab incoming-call tests using Android's default ringtone."
            setSound(ringtoneUri, ringtoneAttributes)
            enableVibration(false)
            setShowBadge(false)
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        }
        val silent = NotificationChannel(
            CALL_SILENT_CHANNEL_ID,
            "Fake calls • silent source",
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = "NotifLab incoming-call tests with no source ringtone."
            setSound(null, null)
            enableVibration(false)
            setShowBadge(false)
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        }
        manager.createNotificationChannel(ringtone)
        manager.createNotificationChannel(silent)
    }

    private fun postIncomingCall(withSourceRingtone: Boolean) {
        val mode = if (withSourceRingtone) "ringtone" else "silent"
        NotifLabLog.event(applicationContext, "CALLLAB", "post begin mode=$mode")
        runCatching {
            if (!ensureCallChannels("post-$mode")) error("Call channels unavailable")

            manager.cancel(FAKE_CALL_NOTIFICATION_ID)
            NotifLabLog.event(applicationContext, "CALLLAB", "previous fake call cancelled mode=$mode")
            val channelId = if (withSourceRingtone) CALL_RINGTONE_CHANNEL_ID else CALL_SILENT_CHANNEL_ID

            val openIntent = PendingIntent.getActivity(
                this,
                10,
                Intent(this, FakeCallLabActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val declineIntent = actionPendingIntent(FakeCallActionReceiver.ACTION_DECLINE, 11)
            val answerIntent = actionPendingIntent(FakeCallActionReceiver.ACTION_ANSWER, 12)
            NotifLabLog.event(applicationContext, "CALLLAB", "pending intents built mode=$mode")

            val builder = Notification.Builder(this, channelId)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("NotifLab caller")
                .setContentText("Incoming fake call • $mode")
                .setContentIntent(openIntent)
                .setCategory(Notification.CATEGORY_CALL)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .setWhen(System.currentTimeMillis())
                .setShowWhen(true)
                .setTimeoutAfter(30_000L)
            NotifLabLog.event(applicationContext, "CALLLAB", "base Notification.Builder configured mode=$mode")

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val caller = Person.Builder()
                    .setName("NotifLab caller")
                    .setImportant(true)
                    .build()
                NotifLabLog.event(applicationContext, "CALLLAB", "Person built; applying CallStyle mode=$mode")
                builder.setStyle(Notification.CallStyle.forIncomingCall(caller, declineIntent, answerIntent))
                NotifLabLog.event(applicationContext, "CALLLAB", "CallStyle applied mode=$mode")
            } else {
                builder.setStyle(Notification.BigTextStyle().bigText("Incoming fake call • $mode"))
            }

            val notification = builder.build()
            if (withSourceRingtone) notification.flags = notification.flags or Notification.FLAG_INSISTENT
            NotifLabLog.event(
                applicationContext,
                "CALLLAB",
                "notification built mode=$mode category=${notification.category} flags=0x${notification.flags.toString(16)} channel=$channelId"
            )
            manager.notify(FAKE_CALL_NOTIFICATION_ID, notification)
            NotifLabLog.event(applicationContext, "CALLLAB", "notify returned successfully mode=$mode id=$FAKE_CALL_NOTIFICATION_ID")
            status.text = "RINGING • $mode • CATEGORY_CALL${if (Build.VERSION.SDK_INT >= 31) " • CallStyle" else ""}"
        }.onFailure { fail("post-$mode", it) }
    }

    private fun actionPendingIntent(action: String, requestCode: Int): PendingIntent =
        PendingIntent.getBroadcast(
            this,
            requestCode,
            Intent(this, FakeCallActionReceiver::class.java).setAction(action),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

    private fun fail(stage: String, error: Throwable) {
        NotifLabLog.event(
            applicationContext,
            "CALLLAB_ERR",
            "stage=$stage type=${error.javaClass.name} message=${error.message ?: "<none>"}",
            error
        )
        if (::status.isInitialized) {
            status.text = "FAILED at $stage: ${error.javaClass.simpleName}: ${error.message ?: "no message"}"
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    companion object {
        const val FAKE_CALL_NOTIFICATION_ID = 9090
        const val CALL_RINGTONE_CHANNEL_ID = "notiflab_fake_call_ringtone_v1"
        const val CALL_SILENT_CHANNEL_ID = "notiflab_fake_call_silent_v1"
    }
}
''', encoding='utf-8')

(kt / 'FakeCallActionReceiver.kt').write_text(r'''package com.randotone.notiflab

import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class FakeCallActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        NotifLabLog.event(context.applicationContext, "CALL_ACTION", "received action=${intent?.action ?: "null"}")
        if (intent?.action != ACTION_ANSWER && intent?.action != ACTION_DECLINE) return
        runCatching {
            context.getSystemService(NotificationManager::class.java)
                .cancel(FakeCallLabActivity.FAKE_CALL_NOTIFICATION_ID)
            NotifLabLog.event(context.applicationContext, "CALL_ACTION", "fake call cancelled action=${intent.action}")
        }.onFailure {
            NotifLabLog.event(context.applicationContext, "CALL_ACTION", "cancel failed action=${intent.action}", it)
        }
    }

    companion object {
        const val ACTION_ANSWER = "com.randotone.notiflab.action.FAKE_CALL_ANSWER"
        const val ACTION_DECLINE = "com.randotone.notiflab.action.FAKE_CALL_DECLINE"
    }
}
''', encoding='utf-8')

# General service breadcrumbs help distinguish Call Lab crashes from process/service restarts.
service = kt / 'NotifLabService.kt'
text = service.read_text(encoding='utf-8')
text = text.replace(
    '    override fun onCreate() {\n        super.onCreate()\n',
    '    override fun onCreate() {\n        super.onCreate()\n        NotifLabLog.event(applicationContext, "SERVICE", "onCreate")\n',
    1,
)
text = text.replace(
    '    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {\n        promoteToForeground()\n',
    '    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {\n        NotifLabLog.event(applicationContext, "SERVICE", "onStartCommand action=${intent?.action ?: "null"} startId=$startId")\n        promoteToForeground()\n',
    1,
)
text = text.replace(
    '    override fun onDestroy() {\n        NotifLabRuntime.serviceRunning = false\n',
    '    override fun onDestroy() {\n        NotifLabLog.event(applicationContext, "SERVICE", "onDestroy")\n        NotifLabRuntime.serviceRunning = false\n',
    1,
)
service.write_text(text, encoding='utf-8')

print(f'Applied NotifLab v0.4.1 persistent diagnostics hotfix in {project}')
