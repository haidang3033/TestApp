#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-notiflab-v0.4.3-true-fsi.py <project-dir>')

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
text = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 7', text)
text = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.4.3"', text)
build.write_text(text, encoding='utf-8')

(kt / 'TrueFullScreenCallPoster.kt').write_text(r'''package com.randotone.notiflab

import android.app.KeyguardManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Person
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import android.os.PowerManager

object TrueFullScreenCallPoster {
    fun post(context: Context, withSourceRingtone: Boolean, trigger: String): Boolean {
        val app = context.applicationContext
        val manager = app.getSystemService(NotificationManager::class.java)
        return runCatching {
            ensureChannels(app, manager)
            manager.cancel(FakeCallLabActivity.FAKE_CALL_NOTIFICATION_ID)
            val power = app.getSystemService(PowerManager::class.java)
            val keyguard = app.getSystemService(KeyguardManager::class.java)
            val fsiAllowed = Build.VERSION.SDK_INT < 34 || manager.canUseFullScreenIntent()
            NotifLabLog.event(app,"TRUE_FSI","posting trigger=$trigger ringtone=$withSourceRingtone fsiAllowed=$fsiAllowed interactive=${power.isInteractive} keyguardLocked=${keyguard.isKeyguardLocked}")

            val fullScreenIntent = PendingIntent.getActivity(app,40,Intent(app, FakeFullScreenCallActivity::class.java).setAction(FakeFullScreenCallActivity.ACTION_SHOW).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            val declineIntent = PendingIntent.getActivity(app,41,Intent(app, FakeFullScreenCallActivity::class.java).setAction(FakeFullScreenCallActivity.ACTION_DECLINE).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            val answerIntent = PendingIntent.getActivity(app,42,Intent(app, FakeFullScreenCallActivity::class.java).setAction(FakeFullScreenCallActivity.ACTION_ANSWER).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

            val channelId = if (withSourceRingtone) FakeCallLabActivity.CALL_RINGTONE_CHANNEL_ID else FakeCallLabActivity.CALL_SILENT_CHANNEL_ID
            val mode = if (withSourceRingtone) "system-ringtone" else "silent-source"
            val builder = Notification.Builder(app, channelId)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("NotifLab caller")
                .setContentText("TRUE incoming FSI test • $mode")
                .setCategory(Notification.CATEGORY_CALL)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
                .setWhen(System.currentTimeMillis())
                .setShowWhen(true)
                .setTimeoutAfter(30_000L)
                .setFullScreenIntent(fullScreenIntent, true)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val caller = Person.Builder().setName("NotifLab TRUE FSI caller").setImportant(true).build()
                builder.setStyle(Notification.CallStyle.forIncomingCall(caller, declineIntent, answerIntent))
            }
            val notification = builder.build().apply { if (withSourceRingtone) flags = flags or Notification.FLAG_INSISTENT }
            manager.notify(FakeCallLabActivity.FAKE_CALL_NOTIFICATION_ID, notification)
            NotifLabLog.event(app,"TRUE_FSI","notify-success id=${FakeCallLabActivity.FAKE_CALL_NOTIFICATION_ID} mode=$mode category=${notification.category} flags=0x${notification.flags.toString(16)}")
            true
        }.onFailure { error ->
            NotifLabLog.event(app,"TRUE_FSI_ERR","post failed trigger=$trigger ringtone=$withSourceRingtone type=${error.javaClass.name} message=${error.message ?: "<none>"}",error)
        }.getOrDefault(false)
    }

    private fun ensureChannels(context: Context, manager: NotificationManager) {
        val attrs = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build()
        val ringtone = NotificationChannel(FakeCallLabActivity.CALL_RINGTONE_CHANNEL_ID,"Fake calls • system ringtone",NotificationManager.IMPORTANCE_HIGH).apply {
            description="NotifLab incoming-call tests using Android's default ringtone.";setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE),attrs);enableVibration(false);setShowBadge(false);lockscreenVisibility=Notification.VISIBILITY_PUBLIC
        }
        val silent = NotificationChannel(FakeCallLabActivity.CALL_SILENT_CHANNEL_ID,"Fake calls • silent source",NotificationManager.IMPORTANCE_HIGH).apply {
            description="NotifLab incoming-call tests with no source ringtone.";setSound(null,null);enableVibration(false);setShowBadge(false);lockscreenVisibility=Notification.VISIBILITY_PUBLIC
        }
        manager.createNotificationChannel(ringtone); manager.createNotificationChannel(silent)
        NotifLabLog.event(context,"TRUE_FSI","channels ringSound=${manager.getNotificationChannel(FakeCallLabActivity.CALL_RINGTONE_CHANNEL_ID)?.sound} silentSound=${manager.getNotificationChannel(FakeCallLabActivity.CALL_SILENT_CHANNEL_ID)?.sound}")
    }
}
''', encoding='utf-8')

service = kt / 'NotifLabService.kt'
t = service.read_text(encoding='utf-8')
method_marker = '''    private fun postUpdate(onlyAlertOnce: Boolean, title: String, body: String) {\n'''
true_methods = r'''    private fun scheduleTrueFsiCall(withSourceRingtone: Boolean, delayMs: Long) {
        val safeDelay = delayMs.coerceIn(1000L, 60_000L)
        val mode = if (withSourceRingtone) "system-ringtone" else "silent-source"
        NotifLabLog.event(applicationContext, "TRUE_FSI", "armed mode=$mode delayMs=$safeDelay")
        setStatus("TRUE FSI call armed: $mode in ${safeDelay}ms. Background or lock the phone now.")
        thread(name = "NotifLab-TrueFSI") {
            try { Thread.sleep(safeDelay); TrueFullScreenCallPoster.post(applicationContext, withSourceRingtone, "delayed-service") }
            catch (_: InterruptedException) { NotifLabLog.event(applicationContext, "TRUE_FSI", "delayed test interrupted mode=$mode") }
        }
    }

    private fun postTrueFsiNow(withSourceRingtone: Boolean, trigger: String): String {
        val ok = TrueFullScreenCallPoster.post(applicationContext, withSourceRingtone, trigger)
        return if (ok) "TRUE FSI call posted" else "TRUE FSI call failed; export diagnostics"
    }

'''
if method_marker not in t: raise SystemExit(f'{service}: postUpdate marker missing')
t = t.replace(method_marker, true_methods + method_marker, 1)
command_marker = '''        "alarm" -> { postCategory(Notification.CATEGORY_ALARM, title, body); "ALARM-category notification posted" }\n        "cancel" -> { cancelTestNotifications(); "All test notifications cancelled; service kept alive" }\n'''
command_repl = '''        "alarm" -> { postCategory(Notification.CATEGORY_ALARM, title, body); "ALARM-category notification posted" }\n        "true-fsi-ring" -> { scheduleTrueFsiCall(true, interval); "TRUE FSI ringtone call armed" }\n        "true-fsi-silent" -> { scheduleTrueFsiCall(false, interval); "TRUE FSI silent call armed" }\n        "true-fsi-ring-now" -> postTrueFsiNow(true, "lan-now")\n        "true-fsi-silent-now" -> postTrueFsiNow(false, "lan-now")\n        "cancel" -> { cancelTestNotifications(); "All test notifications cancelled; service kept alive" }\n'''
if command_marker not in t: raise SystemExit(f'{service}: handleCommand marker missing')
t=t.replace(command_marker,command_repl,1)
lan_marker='''            "/alarm" -> handleCommand("alarm", title, body, count, interval)\n            "/cancel" -> handleCommand("cancel", title, body, count, interval)\n'''
lan_repl='''            "/alarm" -> handleCommand("alarm", title, body, count, interval)\n            "/fsi-ring" -> handleCommand("true-fsi-ring-now", title, body, count, interval)\n            "/fsi-silent" -> handleCommand("true-fsi-silent-now", title, body, count, interval)\n            "/cancel" -> handleCommand("cancel", title, body, count, interval)\n'''
if lan_marker not in t: raise SystemExit(f'{service}: LAN marker missing')
t=t.replace(lan_marker,lan_repl,1)
known_old='val known = setOf("/notify", "/burst", "/timed-start", "/timed-stop", "/update", "/once", "/group", "/ongoing", "/call", "/alarm", "/cancel")'
known_new='val known = setOf("/notify", "/burst", "/timed-start", "/timed-stop", "/update", "/once", "/group", "/ongoing", "/call", "/alarm", "/fsi-ring", "/fsi-silent", "/cancel")'
if known_old not in t: raise SystemExit(f'{service}: LAN known-path marker missing')
t=t.replace(known_old,known_new,1)
html_marker='''            <button onclick="fire('/alarm')">ALARM category</button>\n            <button onclick="fire('/cancel')">Cancel test notifications</button>\n'''
html_repl='''            <button onclick="fire('/alarm')">ALARM category</button>\n            <button onclick="fire('/fsi-ring')">TRUE FSI call • ringtone</button>\n            <button onclick="fire('/fsi-silent')">TRUE FSI call • silent</button>\n            <button onclick="fire('/cancel')">Cancel test notifications</button>\n'''
if html_marker not in t: raise SystemExit(f'{service}: LAN HTML marker missing')
t=t.replace(html_marker,html_repl,1);service.write_text(t,encoding='utf-8')

call_activity=kt/'FakeCallLabActivity.kt';t=call_activity.read_text(encoding='utf-8')
t=t.replace('"NotifLab Fake Call Lab • v0.4.2"','"NotifLab Fake Call Lab • v0.4.3"',1)
t=t.replace('"Direct CallStyle remains as a policy probe. Full-screen variants attach a real fullScreenIntent for incoming-call behavior."','"Direct CallStyle remains a policy probe. TRUE FSI tests are posted later by the foreground service after this Activity backgrounds itself, so you can lock the phone before the incoming call exists."',1)
fsi_section='''        addView(TextView(this@FakeCallLabActivity).apply {\n            text = "Full-screen intent calls"\n            textSize = 18f\n            setPadding(0, dp(16), 0, dp(6))\n        })\n'''
true_section='''        addView(TextView(this@FakeCallLabActivity).apply {\n            text = "TRUE full-screen incoming-call test"\n            textSize = 18f\n            setPadding(0, dp(16), 0, dp(6))\n        })\n        addView(TextView(this@FakeCallLabActivity).apply {\n            text = "Arms the foreground service for 7 seconds, then sends this app to the background. Lock the phone during the countdown. A successful locked-screen launch logs FSI_UI action=FSI_SHOW."\n            textSize = 13f\n            setPadding(0, 0, 0, dp(6))\n        })\n        addView(button("TRUE FSI in 7s • Android default ringtone") { armTrueFsi(true) })\n        addView(button("TRUE FSI in 7s • silent source") { armTrueFsi(false) })\n\n'''+fsi_section
if fsi_section not in t: raise SystemExit(f'{call_activity}: FSI section marker missing')
t=t.replace(fsi_section,true_section,1)
helper_marker='''    private fun openFsiSettings() {\n'''
helper=r'''    private fun armTrueFsi(withSourceRingtone: Boolean) {
        val command = if (withSourceRingtone) "true-fsi-ring" else "true-fsi-silent"
        val mode = if (withSourceRingtone) "system-ringtone" else "silent-source"
        val intent = Intent(this, NotifLabService::class.java).setAction(NotifLabService.ACTION_COMMAND).putExtra(NotifLabService.EXTRA_COMMAND, command).putExtra(NotifLabService.EXTRA_INTERVAL, TRUE_FSI_DELAY_MS)
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent) else startService(intent)
            status.text = "TRUE FSI armed • $mode • ${TRUE_FSI_DELAY_MS / 1000}s. Lock the phone now."
            NotifLabLog.event(applicationContext, "CALLLAB", "armed TRUE FSI mode=$mode delayMs=$TRUE_FSI_DELAY_MS; moving task to background")
            moveTaskToBack(true)
        }.onFailure { fail("arm-true-fsi-$mode", it) }
    }

'''
if helper_marker not in t: raise SystemExit(f'{call_activity}: openFsiSettings marker missing')
t=t.replace(helper_marker,helper+helper_marker,1)
comp_marker='''        const val CALL_SILENT_CHANNEL_ID = "notiflab_fake_call_silent_v1"\n    }\n}\n'''
comp_repl='''        const val CALL_SILENT_CHANNEL_ID = "notiflab_fake_call_silent_v1"\n        private const val TRUE_FSI_DELAY_MS = 7_000L\n    }\n}\n'''
if comp_marker not in t: raise SystemExit(f'{call_activity}: companion marker missing')
t=t.replace(comp_marker,comp_repl,1);call_activity.write_text(t,encoding='utf-8')

fsi_ui=kt/'FakeFullScreenCallActivity.kt';t=fsi_ui.read_text(encoding='utf-8');t=t.replace('text = "Full-screen intent test • no real Telecom call exists"','text = if (intent?.action == ACTION_SHOW) "TRUE full-screen intent launch • no real Telecom call exists" else "Full-screen call action • no real Telecom call exists"',1);fsi_ui.write_text(t,encoding='utf-8')
print('Patched NotifLab v0.4.3 true background/lock-screen FSI tests')
