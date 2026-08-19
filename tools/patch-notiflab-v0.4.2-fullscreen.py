#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-notiflab-v0.4.2-fullscreen.py <project-dir>')

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

build = app / 'build.gradle.kts'
text = build.read_text(encoding='utf-8')
text = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 6', text)
text = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.4.2"', text)
build.write_text(text, encoding='utf-8')

manifest = src / 'AndroidManifest.xml'
m = manifest.read_text(encoding='utf-8')
if 'android.permission.USE_FULL_SCREEN_INTENT' not in m:
    marker = '    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />\n'
    if marker not in m:
        raise SystemExit(f'{manifest}: POST_NOTIFICATIONS marker missing')
    m = m.replace(
        marker,
        marker + '    <uses-permission android:name="android.permission.USE_FULL_SCREEN_INTENT" />\n',
        1,
    )

if 'android:name=".FakeFullScreenCallActivity"' not in m:
    marker = '''        <activity
            android:name=".FakeCallLabActivity"
            android:exported="false" />
'''
    if marker not in m:
        raise SystemExit(f'{manifest}: FakeCallLabActivity marker missing')
    m = m.replace(
        marker,
        '''        <activity
            android:name=".FakeFullScreenCallActivity"
            android:exported="false"
            android:excludeFromRecents="true"
            android:launchMode="singleTop"
            android:showWhenLocked="true"
            android:turnScreenOn="true" />

''' + marker,
        1,
    )
manifest.write_text(m, encoding='utf-8')

activity = kt / 'MainActivity.kt'
t = activity.read_text(encoding='utf-8')
old = '        root.addView(button("Copy persistent diagnostics log") { copyDiagnostics() })\n'
new = (
    '        root.addView(button("Copy persistent diagnostics log") { copyDiagnostics() })\n'
    '        root.addView(button("Export diagnostics log…") { exportDiagnostics() })\n'
)
if old not in t:
    raise SystemExit(f'{activity}: diagnostics button marker missing')
t = t.replace(old, new, 1)

method_marker = '''    private fun copyLanAddress() {
'''
export_method = r'''    private fun exportDiagnostics() {
        val stamp = java.text.SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", java.util.Locale.US)
            .format(java.util.Date())
        val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "text/plain"
            putExtra(Intent.EXTRA_TITLE, "notiflab-diagnostics-$stamp.txt")
        }
        NotifLabLog.event(applicationContext, "ACTIVITY", "export diagnostics picker opened")
        startActivityForResult(intent, REQUEST_EXPORT_DIAGNOSTICS)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQUEST_EXPORT_DIAGNOSTICS || resultCode != RESULT_OK) return
        val uri = data?.data ?: run {
            NotifLabLog.event(applicationContext, "ACTIVITY", "export diagnostics returned without URI")
            return
        }
        runCatching {
            val diagnostics = NotifLabLog.readAll(this)
            contentResolver.openOutputStream(uri, "w")?.bufferedWriter(Charsets.UTF_8)?.use { writer ->
                writer.write(diagnostics)
            } ?: error("Could not open destination")
            Toast.makeText(this, "Diagnostics exported.", Toast.LENGTH_SHORT).show()
            NotifLabLog.event(applicationContext, "ACTIVITY", "diagnostics exported uri=$uri chars=${diagnostics.length}")
        }.onFailure { error ->
            Toast.makeText(this, "Export failed: ${error.message ?: error.javaClass.simpleName}", Toast.LENGTH_LONG).show()
            NotifLabLog.event(applicationContext, "ACTIVITY", "diagnostics export failed", error)
        }
    }

'''
if method_marker not in t:
    raise SystemExit(f'{activity}: copyLanAddress marker missing')
t = t.replace(method_marker, export_method + method_marker, 1)
companion_old = '''    companion object {
        private const val REQUEST_NOTIFICATIONS = 100
    }
'''
companion_new = '''    companion object {
        private const val REQUEST_NOTIFICATIONS = 100
        private const val REQUEST_EXPORT_DIAGNOSTICS = 101
    }
'''
if companion_old not in t:
    raise SystemExit(f'{activity}: companion marker missing')
t = t.replace(companion_old, companion_new, 1)
activity.write_text(t, encoding='utf-8')

(kt / 'FakeFullScreenCallActivity.kt').write_text(r'''package com.randotone.notiflab

import android.app.Activity
import android.app.NotificationManager
import android.os.Bundle
import android.view.Gravity
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

class FakeFullScreenCallActivity : Activity() {
    private lateinit var manager: NotificationManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        manager = getSystemService(NotificationManager::class.java)
        setShowWhenLocked(true)
        setTurnScreenOn(true)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        NotifLabLog.event(applicationContext, "FSI_UI", "onCreate action=${intent?.action}")

        if (handleTerminalAction(intent?.action)) return
        setContentView(buildUi())
    }

    override fun onNewIntent(intent: android.content.Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        NotifLabLog.event(applicationContext, "FSI_UI", "onNewIntent action=${intent?.action}")
        handleTerminalAction(intent?.action)
    }

    private fun handleTerminalAction(action: String?): Boolean {
        if (action != ACTION_ANSWER && action != ACTION_DECLINE) return false
        manager.cancel(FakeCallLabActivity.FAKE_CALL_NOTIFICATION_ID)
        NotifLabLog.event(applicationContext, "FSI_UI", "terminal action=$action; notification cancelled")
        finishAndRemoveTask()
        return true
    }

    private fun buildUi(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER
        setPadding(dp(28), dp(40), dp(28), dp(40))

        addView(TextView(this@FakeFullScreenCallActivity).apply {
            text = "NotifLab incoming fake call"
            textSize = 30f
            gravity = Gravity.CENTER
        })
        addView(TextView(this@FakeFullScreenCallActivity).apply {
            text = "Full-screen intent test • no real Telecom call exists"
            textSize = 15f
            gravity = Gravity.CENTER
            setPadding(0, dp(12), 0, dp(30))
        })
        addView(button("Answer") { finishCall(ACTION_ANSWER) })
        addView(button("Decline") { finishCall(ACTION_DECLINE) })
    }

    private fun button(label: String, action: () -> Unit): Button = Button(this).apply {
        text = label
        isAllCaps = false
        setOnClickListener { action() }
    }

    private fun finishCall(action: String) {
        manager.cancel(FakeCallLabActivity.FAKE_CALL_NOTIFICATION_ID)
        NotifLabLog.event(applicationContext, "FSI_UI", "button action=$action; notification cancelled")
        finishAndRemoveTask()
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    companion object {
        const val ACTION_SHOW = "com.randotone.notiflab.action.FSI_SHOW"
        const val ACTION_ANSWER = "com.randotone.notiflab.action.FSI_ANSWER"
        const val ACTION_DECLINE = "com.randotone.notiflab.action.FSI_DECLINE"
    }
}
''', encoding='utf-8')

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
import android.net.Uri
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
    private lateinit var fsiStatus: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        NotifLabLog.event(applicationContext, "CALLLAB", "onCreate begin sdk=${Build.VERSION.SDK_INT}")
        manager = getSystemService(NotificationManager::class.java)
        setContentView(buildUi())
        ensureCallChannels("activity-create")
        refreshFsiStatus()
        NotifLabLog.event(applicationContext, "CALLLAB", "onCreate complete")
    }

    override fun onResume() {
        super.onResume()
        refreshFsiStatus()
        NotifLabLog.event(applicationContext, "CALLLAB", "onResume")
    }

    private fun buildUi(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(18), dp(18), dp(18), dp(28))

        addView(TextView(this@FakeCallLabActivity).apply {
            text = "NotifLab Fake Call Lab • v0.4.2"
            textSize = 26f
        })
        addView(TextView(this@FakeCallLabActivity).apply {
            text = "Direct CallStyle remains as a policy probe. Full-screen variants attach a real fullScreenIntent for incoming-call behavior."
            textSize = 14f
            setPadding(0, dp(6), 0, dp(14))
        })

        status = TextView(this@FakeCallLabActivity).apply {
            text = "Idle. Fake calls auto-timeout after 30 seconds."
            setPadding(0, 0, 0, dp(8))
        }
        fsiStatus = TextView(this@FakeCallLabActivity).apply {
            text = "Full-screen intent access: checking…"
            setPadding(0, 0, 0, dp(12))
        }
        addView(status)
        addView(fsiStatus)

        addView(TextView(this@FakeCallLabActivity).apply {
            text = "Direct CallStyle policy probes"
            textSize = 18f
            setPadding(0, dp(8), 0, dp(6))
        })
        addView(button("Direct CallStyle • Android default ringtone") {
            postIncomingCall(withSourceRingtone = true, withFullScreenIntent = false)
        })
        addView(button("Direct CallStyle • silent source") {
            postIncomingCall(withSourceRingtone = false, withFullScreenIntent = false)
        })

        addView(TextView(this@FakeCallLabActivity).apply {
            text = "Full-screen intent calls"
            textSize = 18f
            setPadding(0, dp(16), 0, dp(6))
        })
        addView(button("Full-screen call • Android default ringtone") {
            postIncomingCall(withSourceRingtone = true, withFullScreenIntent = true)
        })
        addView(button("Full-screen call • silent source") {
            postIncomingCall(withSourceRingtone = false, withFullScreenIntent = true)
        })
        addView(button("Open full-screen intent access") { openFsiSettings() })

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
            text = "On Android 14+, canUseFullScreenIntent() is logged before every full-screen test. If access is denied, Android may fall back to an expanded heads-up notification rather than launching the full-screen Activity."
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

    private fun refreshFsiStatus() {
        if (!::fsiStatus.isInitialized) return
        val allowed = canUseFsi()
        fsiStatus.text = if (Build.VERSION.SDK_INT >= 34) {
            "Full-screen intent access: ${if (allowed) "ALLOWED" else "NOT ALLOWED"}"
        } else {
            "Full-screen intent access: manifest permission path (pre-Android 14)"
        }
    }

    private fun canUseFsi(): Boolean =
        Build.VERSION.SDK_INT < 34 || manager.canUseFullScreenIntent()

    private fun openFsiSettings() {
        if (Build.VERSION.SDK_INT < 34) {
            status.text = "This Android version has no dedicated full-screen-intent access page."
            return
        }
        runCatching {
            val intent = Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT).apply {
                data = Uri.parse("package:$packageName")
            }
            startActivity(intent)
            NotifLabLog.event(applicationContext, "CALLLAB", "opened full-screen intent access settings")
        }.onFailure { fail("open-fsi-settings", it) }
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

    private fun postIncomingCall(withSourceRingtone: Boolean, withFullScreenIntent: Boolean) {
        val soundMode = if (withSourceRingtone) "ringtone" else "silent"
        val transport = if (withFullScreenIntent) "fsi" else "direct"
        val stage = "$transport-$soundMode"
        NotifLabLog.event(applicationContext, "CALLLAB", "post begin stage=$stage")

        runCatching {
            if (!ensureCallChannels("post-$stage")) error("Call channels unavailable")

            manager.cancel(FAKE_CALL_NOTIFICATION_ID)
            val channelId = if (withSourceRingtone) CALL_RINGTONE_CHANNEL_ID else CALL_SILENT_CHANNEL_ID

            val openIntent = PendingIntent.getActivity(
                this,
                10,
                Intent(this, FakeCallLabActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )

            val declineIntent: PendingIntent
            val answerIntent: PendingIntent
            if (withFullScreenIntent) {
                declineIntent = PendingIntent.getActivity(
                    this,
                    21,
                    Intent(this, FakeFullScreenCallActivity::class.java)
                        .setAction(FakeFullScreenCallActivity.ACTION_DECLINE)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                )
                answerIntent = PendingIntent.getActivity(
                    this,
                    22,
                    Intent(this, FakeFullScreenCallActivity::class.java)
                        .setAction(FakeFullScreenCallActivity.ACTION_ANSWER)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                )
            } else {
                declineIntent = actionPendingIntent(FakeCallActionReceiver.ACTION_DECLINE, 11)
                answerIntent = actionPendingIntent(FakeCallActionReceiver.ACTION_ANSWER, 12)
            }

            val builder = Notification.Builder(this, channelId)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("NotifLab caller")
                .setContentText("Incoming fake call • $stage")
                .setContentIntent(openIntent)
                .setCategory(Notification.CATEGORY_CALL)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .setWhen(System.currentTimeMillis())
                .setShowWhen(true)
                .setTimeoutAfter(30_000L)

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val caller = Person.Builder()
                    .setName("NotifLab caller")
                    .setImportant(true)
                    .build()
                builder.setStyle(Notification.CallStyle.forIncomingCall(caller, declineIntent, answerIntent))
                NotifLabLog.event(applicationContext, "CALLLAB", "CallStyle applied stage=$stage")
            }

            if (withFullScreenIntent) {
                val fsiAllowed = canUseFsi()
                val fullScreenIntent = PendingIntent.getActivity(
                    this,
                    23,
                    Intent(this, FakeFullScreenCallActivity::class.java)
                        .setAction(FakeFullScreenCallActivity.ACTION_SHOW)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                )
                builder.setFullScreenIntent(fullScreenIntent, true)
                NotifLabLog.event(
                    applicationContext,
                    "CALLLAB",
                    "fullScreenIntent attached stage=$stage canUseFullScreenIntent=$fsiAllowed"
                )
            }

            val notification = builder.build().apply {
                if (withSourceRingtone) flags = flags or Notification.FLAG_INSISTENT
            }
            NotifLabLog.event(
                applicationContext,
                "CALLLAB",
                "notification built stage=$stage category=${notification.category} flags=0x${notification.flags.toString(16)} channel=$channelId"
            )
            manager.notify(FAKE_CALL_NOTIFICATION_ID, notification)
            NotifLabLog.event(applicationContext, "CALLLAB", "notify returned successfully stage=$stage")
            status.text = if (withFullScreenIntent) {
                "POSTED • full-screen call • $soundMode • FSI access=${canUseFsi()}"
            } else {
                "POSTED • direct CallStyle • $soundMode"
            }
        }.onFailure { fail("post-$stage", it) }
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
            status.text = "FAILED • $stage • ${error.javaClass.simpleName}: ${error.message ?: "no message"}"
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

print(f'Patched NotifLab v0.4.2 full-screen Call Lab in {project}')
