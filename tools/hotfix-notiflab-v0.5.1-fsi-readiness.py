#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: hotfix-notiflab-v0.5.1-fsi-readiness.py <project-dir>")

project = Path(sys.argv[1]).resolve()
app = project / "app"
kt = app / "src" / "main" / "java" / "com" / "randotone" / "notiflab"

build = app / "build.gradle.kts"
t = build.read_text(encoding="utf-8")
t = re.sub(r"versionCode\s*=\s*\d+", "versionCode = 10", t)
t = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.5.1"', t)
build.write_text(t, encoding="utf-8")

p = kt / "MainActivity.kt"
t = p.read_text(encoding="utf-8")
t = t.replace("notification + incoming-call test harness • v0.5", "notification + incoming-call test harness • v0.5.1", 1)

imports = {
    "import android.app.NotificationManager\n": "import android.app.Activity\n",
    "import android.net.Uri\n": "import android.graphics.drawable.GradientDrawable\n",
    "import android.provider.Settings\n": "import android.os.Looper\n",
}
for addition, anchor in imports.items():
    if addition not in t:
        if anchor not in t:
            raise SystemExit(f"MainActivity import anchor missing for {addition.strip()}")
        t = t.replace(anchor, anchor + addition, 1)

old_card = '''        content.addView(card("Which FSI test?", "The two families deliberately test different Android behavior.") {
            addView(statusText("Immediate FSI probe", bold = true))
            addView(statusText("Posts while the Call Lab Activity is already foreground. Android may keep this notification-only."))
            addView(space(dp(8)))
            addView(statusText("TRUE background FSI", bold = true))
            addView(statusText("Arms the foreground service, backgrounds NotifLab, waits 7 seconds, then posts. Lock the phone during the countdown to test real takeover."))
        })
'''
new_card = '''        val fsiAllowed = Build.VERSION.SDK_INT < 34 ||
            getSystemService(NotificationManager::class.java).canUseFullScreenIntent()
        content.addView(card("FSI readiness", "Android 14 and HyperOS both have gates that can turn a full-screen call into only a lock-screen notification.") {
            addView(statusText(
                if (fsiAllowed) "Android full-screen-intent access: ALLOWED" else "Android full-screen-intent access: NOT ALLOWED",
                bold = true
            ))
            if (!fsiAllowed && Build.VERSION.SDK_INT >= 34) {
                addView(statusText("When this is denied, Android intentionally falls back to an expanded heads-up/lock-screen notification instead of launching the call Activity."))
                addView(actionButton("Open Android full-screen intent access") {
                    startActivity(Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT).apply {
                        data = Uri.parse("package:$packageName")
                    })
                })
            }
            addView(space(dp(8)))
            addView(statusText("Xiaomi / HyperOS check", bold = true))
            addView(statusText("If Android FSI access is ALLOWED but the Activity still waits until unlock, also allow NotifLab to Show on Lock screen and Open new windows while running in the background under Xiaomi's Other permissions. Android has no public API for NotifLab to read those Xiaomi toggles."))
            addView(actionButton("Open NotifLab app settings") {
                startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                    data = Uri.parse("package:$packageName")
                })
            })
        })
        content.addView(card("Which FSI test?", "Foreground and locked-screen behavior are intentionally different on modern Android.") {
            addView(statusText("Foreground FSI / HUN probe", bold = true))
            addView(statusText("While the phone is unlocked and in use, Android 13+ normally shows the call as an expanded heads-up notification instead of auto-launching the full-screen Activity."))
            addView(space(dp(8)))
            addView(statusText("TRUE background FSI", bold = true))
            addView(statusText("This is the actual takeover test: NotifLab backgrounds itself, waits 7 seconds, then posts. Lock or turn off the screen during the countdown. It only counts as a valid FSI test when Android access is ALLOWED."))
        })
'''
if old_card not in t:
    raise SystemExit("MainActivity FSI explanation card marker missing")
t = t.replace(old_card, new_card, 1)
p.write_text(t, encoding="utf-8")

p = kt / "FakeCallLabActivity.kt"
t = p.read_text(encoding="utf-8")
t = t.replace('"NotifLab Call Lab • v0.5"', '"NotifLab Call Lab • v0.5.1"', 1)
t = t.replace(
    '"Immediate probes test Android policy while this screen is foreground. TRUE FSI backgrounds NotifLab first, waits 7 seconds, then posts so a locked-screen takeover can be tested cleanly."',
    '"Foreground FSI is a heads-up-notification probe on Android 13+. TRUE FSI is the locked/off-screen takeover test and requires Android full-screen-intent access first."',
    1,
)
t = t.replace('text = "Immediate full-screen-intent probes"', 'text = "Foreground FSI / heads-up probes"', 1)
t = t.replace('"Full-screen call • Android default ringtone"', '"Foreground FSI probe • Android default ringtone"', 1)
t = t.replace('"Full-screen call • silent source"', '"Foreground FSI probe • silent source"', 1)

settings_button = '        addView(button("Open full-screen intent access") { openFsiSettings() })\n'
preview = '''        addView(button("Preview incoming-call screen • UI only") {
            NotifLabLog.event(applicationContext, "CALLLAB", "manual incoming-call UI preview")
            startActivity(
                Intent(this@FakeCallLabActivity, FakeFullScreenCallActivity::class.java)
                    .setAction(FakeFullScreenCallActivity.ACTION_SHOW)
            )
        })
'''
if preview.strip() not in t:
    if settings_button not in t:
        raise SystemExit("CallLab FSI settings button marker missing")
    t = t.replace(settings_button, preview + settings_button, 1)

old_arm = '''    private fun armTrueFsi(withSourceRingtone: Boolean) {
        val command = if (withSourceRingtone) "true-fsi-ring" else "true-fsi-silent"
'''
new_arm = '''    private fun armTrueFsi(withSourceRingtone: Boolean) {
        if (!canUseFsi()) {
            status.text = "TRUE FSI blocked: Android full-screen-intent access is NOT ALLOWED. Open the access page first."
            NotifLabLog.event(applicationContext, "TRUE_FSI", "arm blocked reason=fsi-access-denied")
            openFsiSettings()
            return
        }
        val command = if (withSourceRingtone) "true-fsi-ring" else "true-fsi-silent"
'''
if old_arm not in t:
    raise SystemExit("armTrueFsi marker missing")
t = t.replace(old_arm, new_arm, 1)
p.write_text(t, encoding="utf-8")

p = kt / "TrueFullScreenCallPoster.kt"
t = p.read_text(encoding="utf-8")
old_log = 'NotifLabLog.event(app,"TRUE_FSI","posting trigger=$trigger ringtone=$withSourceRingtone fsiAllowed=$fsiAllowed interactive=${power.isInteractive} keyguardLocked=${keyguard.isKeyguardLocked}")'
new_log = 'NotifLabLog.event(app,"TRUE_FSI","posting trigger=$trigger ringtone=$withSourceRingtone fsiAllowed=$fsiAllowed expectedSurface=${if(!fsiAllowed) "HUN_PERMISSION_DENIED" else if(power.isInteractive) "HUN_DEVICE_UNLOCKED" else "FSI_LOCKED_OR_OFF"} interactive=${power.isInteractive} keyguardLocked=${keyguard.isKeyguardLocked}")'
if old_log not in t:
    raise SystemExit("TRUE_FSI posting log marker missing")
t = t.replace(old_log, new_log, 1)
p.write_text(t, encoding="utf-8")

print("Applied NotifLab v0.5.1 FSI readiness + preview hotfix")
