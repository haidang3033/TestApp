#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-randotone-v0.3.py <project-dir>')

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

# Stable toolchain + version bump.
build = app / 'build.gradle.kts'
text = build.read_text(encoding='utf-8')
import re
text = re.sub(r'compileSdk\s*=\s*\d+', 'compileSdk = 36', text)
text = re.sub(r'targetSdk\s*=\s*\d+', 'targetSdk = 36', text)
text = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 3', text)
text = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.3.0"', text)
build.write_text(text, encoding='utf-8')

# Fix the Kotlin/JVM property-setter collision already discovered in v0.2 CI.
state = kotlin / 'RandoToneState.kt'
replace_exact(
    state,
    'fun setNotificationEnabled(enabled: Boolean)',
    'fun updateNotificationEnabled(enabled: Boolean)',
)

# Harden NotificationListenerService reconnect behavior.
listener = kotlin / 'RandoToneNotificationListener.kt'
replace_exact(
    listener,
    '''    override fun onListenerConnected() {\n        super.onListenerConnected()\n        connectedAtElapsed = SystemClock.elapsedRealtime()\n    }\n''',
    '''    override fun onListenerConnected() {\n        super.onListenerConnected()\n        connectedAtElapsed = SystemClock.elapsedRealtime()\n        ListenerRecovery.markConnected(applicationContext)\n    }\n\n    override fun onListenerDisconnected() {\n        super.onListenerDisconnected()\n        connectedAtElapsed = 0L\n        ListenerRecovery.markDisconnected(applicationContext)\n        ListenerRecovery.requestRebind(applicationContext, "listener-disconnected")\n    }\n''',
)
replace_exact(
    listener,
    'Notification.EXTRA_SUBSTITUTE_APP_NAME',
    '"android.substName"',
)

# Rebind whenever the UI is opened again, including after a force-stop followed by a manual launch.
activity = kotlin / 'MainActivity.kt'
replace_exact(
    activity,
    '''        notificationAccessGranted = hasNotificationListenerAccess(this)\n        setContent {\n''',
    '''        notificationAccessGranted = hasNotificationListenerAccess(this)\n        if (notificationAccessGranted) {\n            ListenerRecovery.requestRebind(this, "activity-create")\n        }\n        setContent {\n''',
)
replace_exact(
    activity,
    '''    override fun onResume() {\n        super.onResume()\n        notificationAccessGranted = hasNotificationListenerAccess(this)\n    }\n''',
    '''    override fun onResume() {\n        super.onResume()\n        notificationAccessGranted = hasNotificationListenerAccess(this)\n        if (notificationAccessGranted) {\n            ListenerRecovery.requestRebind(this, "activity-resume")\n        }\n    }\n''',
)
replace_exact(activity, '"v0.2 prototype • notification roulette"', '"v0.3 prototype • lifecycle hardening"')
replace_exact(
    activity,
    '''                    onOpenAccess = { openNotificationListenerSettings(context) },\n                    onEnabled = { state.setNotificationEnabled(it) },\n                    onChooseDefault = { showDefaultPoolDialog = true },\n''',
    '''                    onOpenAccess = { openNotificationListenerSettings(context) },\n                    onRepair = { ListenerRecovery.requestRebind(context, "manual-repair") },\n                    onEnabled = { state.updateNotificationEnabled(it) },\n                    onChooseDefault = { showDefaultPoolDialog = true },\n''',
)
replace_exact(
    activity,
    '''    onOpenAccess: () -> Unit,\n    onEnabled: (Boolean) -> Unit,\n''',
    '''    onOpenAccess: () -> Unit,\n    onRepair: () -> Unit,\n    onEnabled: (Boolean) -> Unit,\n''',
)
replace_exact(
    activity,
    '''            Button(onClick = onOpenAccess, modifier = Modifier.fillMaxWidth()) {\n                Text(if (accessGranted) "Notification access settings" else "Grant notification access")\n            }\n\n            Row(\n''',
    '''            Button(onClick = onOpenAccess, modifier = Modifier.fillMaxWidth()) {\n                Text(if (accessGranted) "Notification access settings" else "Grant notification access")\n            }\n            if (accessGranted) {\n                OutlinedButton(onClick = onRepair, modifier = Modifier.fillMaxWidth()) {\n                    Text("Repair / rebind listener")\n                }\n                Text(\n                    "RandoTone now requests a listener rebind after disconnect, reboot, app update, and whenever this screen is reopened.",\n                    style = MaterialTheme.typography.bodySmall\n                )\n            }\n\n            Row(\n''',
)
replace_exact(activity, 'Text("v0.3  • Ringtone rotation")', 'Text("v0.4  • Ringtone rotation")')
replace_exact(activity, 'Text("v0.4  • Alarm clock + random alarm pools")', 'Text("v0.5  • Alarm clock + random alarm pools")')
replace_exact(
    activity,
    '"v0.2 deliberately keeps notification replacement conservative: it listens and plays, but does not cancel or rewrite another app\'s notifications."',
    '"Notification replacement remains conservative: it listens and plays, but does not cancel or rewrite another app\'s notifications."',
)

# Ask for another bind after boot, unlock and an in-place update.
manifest = src / 'AndroidManifest.xml'
replace_exact(
    manifest,
    '<manifest xmlns:android="http://schemas.android.com/apk/res/android">',
    '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n\n    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />',
)
replace_exact(
    manifest,
    '''        <service\n            android:name=".RandoToneNotificationListener"\n''',
    '''        <receiver\n            android:name=".ListenerRecoveryReceiver"\n            android:enabled="true"\n            android:exported="true">\n            <intent-filter>\n                <action android:name="android.intent.action.BOOT_COMPLETED" />\n                <action android:name="android.intent.action.USER_UNLOCKED" />\n                <action android:name="android.intent.action.MY_PACKAGE_REPLACED" />\n            </intent-filter>\n        </receiver>\n\n        <service\n            android:name=".RandoToneNotificationListener"\n''',
)

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
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return false
        if (!hasNotificationListenerAccess(context)) return false

        val component = ComponentName(context, RandoToneNotificationListener::class.java)
        return runCatching {
            NotificationListenerService.requestRebind(component)
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit()
                .putLong(KEY_LAST_REQUEST, System.currentTimeMillis())
                .putString(KEY_LAST_REASON, reason)
                .apply()
            true
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
        ListenerRecovery.requestRebind(context.applicationContext, reason)
    }
}
''', encoding='utf-8')

print(f'Patched RandoTone v0.3 source in {project}')
