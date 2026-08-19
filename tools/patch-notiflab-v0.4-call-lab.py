#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-notiflab-v0.4-call-lab.py <project-dir>')

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


# v0.4 keeps the v0.3 harness intact and adds a self-contained Call Lab screen.
build = app / 'build.gradle.kts'
text = build.read_text(encoding='utf-8')
text = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 4', text)
text = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.4.0"', text)
build.write_text(text, encoding='utf-8')

activity = kt / 'MainActivity.kt'
replace_exact(
    activity,
    '        root.addView(button("CALL category (RandoTone should ignore)") { sendCommand("call") })\n',
    '        root.addView(button("CALL category (osine should ignore as a normal notification)") { sendCommand("call") })\n'
    '        root.addView(button("Open Fake Call Lab 📞") { startActivity(Intent(this, FakeCallLabActivity::class.java)) })\n',
)
replace_exact(
    activity,
    'A notification firing range for RandoTone. v0.3 keeps the LAN server and timed fire alive in a foreground service after you swipe the app away.',
    'A notification firing range for osine. v0.4 adds a Fake Call Lab for ringtone-suppression and CallStyle experiments.',
)

manifest = src / 'AndroidManifest.xml'
replace_exact(
    manifest,
    '''        <activity\n            android:name=".MainActivity"\n            android:exported="true">\n''',
    '''        <activity\n            android:name=".FakeCallLabActivity"\n            android:exported="false" />\n\n        <receiver\n            android:name=".FakeCallActionReceiver"\n            android:exported="false" />\n\n        <activity\n            android:name=".MainActivity"\n            android:exported="true">\n''',
)

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
        manager = getSystemService(NotificationManager::class.java)
        createCallChannels()
        setContentView(buildUi())
    }

    private fun buildUi(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(18), dp(18), dp(18), dp(28))

        addView(TextView(this@FakeCallLabActivity).apply {
            text = "NotifLab Fake Call Lab"
            textSize = 26f
        })
        addView(TextView(this@FakeCallLabActivity).apply {
            text = "Posts an Android incoming CallStyle notification without a real caller. Use ringtone mode to test osine call-effect suppression, or silent mode to test replacement-ringtone playback."
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
            manager.cancel(FAKE_CALL_NOTIFICATION_ID)
            status.text = "Fake call ended from NotifLab."
        })
        addView(button("Open ringtone-channel settings") {
            val intent = Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
                .putExtra(Settings.EXTRA_CHANNEL_ID, CALL_RINGTONE_CHANNEL_ID)
            startActivity(intent)
        })

        addView(TextView(this@FakeCallLabActivity).apply {
            text = "Ringtone source: Android default ringtone URI + USAGE_NOTIFICATION_RINGTONE. Silent source: same incoming-call shape, but channel sound is null. Answer/Decline buttons only dismiss the fake call. No Telecom call is created."
            textSize = 13f
            setPadding(0, dp(14), 0, 0)
        })
    }

    private fun button(label: String, action: () -> Unit): Button = Button(this).apply {
        text = label
        isAllCaps = false
        gravity = Gravity.CENTER
        setOnClickListener { action() }
    }

    private fun createCallChannels() {
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
            setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE), ringtoneAttributes)
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
        manager.cancel(FAKE_CALL_NOTIFICATION_ID)
        val channelId = if (withSourceRingtone) CALL_RINGTONE_CHANNEL_ID else CALL_SILENT_CHANNEL_ID
        val mode = if (withSourceRingtone) "Android default ringtone" else "silent source"

        val openIntent = PendingIntent.getActivity(
            this,
            10,
            Intent(this, FakeCallLabActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val declineIntent = actionPendingIntent(FakeCallActionReceiver.ACTION_DECLINE, 11)
        val answerIntent = actionPendingIntent(FakeCallActionReceiver.ACTION_ANSWER, 12)

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

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val caller = Person.Builder()
                .setName("NotifLab caller")
                .setImportant(true)
                .build()
            builder.setStyle(Notification.CallStyle.forIncomingCall(caller, declineIntent, answerIntent))
        } else {
            builder.setStyle(Notification.BigTextStyle().bigText("Incoming fake call • $mode"))
        }

        val notification = builder.build().apply {
            if (withSourceRingtone) flags = flags or Notification.FLAG_INSISTENT
        }
        manager.notify(FAKE_CALL_NOTIFICATION_ID, notification)
        status.text = "RINGING • $mode • CATEGORY_CALL${if (Build.VERSION.SDK_INT >= 31) " • CallStyle" else ""}"
    }

    private fun actionPendingIntent(action: String, requestCode: Int): PendingIntent =
        PendingIntent.getBroadcast(
            this,
            requestCode,
            Intent(this, FakeCallActionReceiver::class.java).setAction(action),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

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
        if (intent?.action != ACTION_ANSWER && intent?.action != ACTION_DECLINE) return
        context.getSystemService(NotificationManager::class.java)
            .cancel(FakeCallLabActivity.FAKE_CALL_NOTIFICATION_ID)
    }

    companion object {
        const val ACTION_ANSWER = "com.randotone.notiflab.action.FAKE_CALL_ANSWER"
        const val ACTION_DECLINE = "com.randotone.notiflab.action.FAKE_CALL_DECLINE"
    }
}
''', encoding='utf-8')

print(f'Patched NotifLab v0.4 Call Lab source in {project}')
