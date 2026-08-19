#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: hotfix-notiflab-v0.4.4-call-ui.py <project-dir>')

project = Path(sys.argv[1]).resolve()
app = project / 'app'
kt = app / 'src' / 'main' / 'java' / 'com' / 'randotone' / 'notiflab'

# Version bump.
build = app / 'build.gradle.kts'
t = build.read_text(encoding='utf-8')
t = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 8', t)
t = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.4.4"', t)
build.write_text(t, encoding='utf-8')

# Call Lab: content has outgrown one portrait screen. Wrap the existing linear layout
# in a ScrollView so bottom controls cannot be clipped/squashed by the viewport.
p = kt / 'FakeCallLabActivity.kt'
t = p.read_text(encoding='utf-8')
if 'import android.widget.ScrollView\n' not in t:
    marker = 'import android.widget.LinearLayout\n'
    if marker not in t:
        raise SystemExit('FakeCallLabActivity LinearLayout import marker missing')
    t = t.replace(marker, marker + 'import android.widget.ScrollView\n', 1)

old = '        setContentView(buildUi())\n'
new = '''        setContentView(ScrollView(this).apply {\n            isFillViewport = true\n            clipToPadding = false\n            addView(\n                buildUi(),\n                android.view.ViewGroup.LayoutParams(\n                    android.view.ViewGroup.LayoutParams.MATCH_PARENT,\n                    android.view.ViewGroup.LayoutParams.WRAP_CONTENT\n                )\n            )\n        })\n'''
if old not in t:
    raise SystemExit('FakeCallLabActivity setContentView marker missing')
t = t.replace(old, new, 1)
t = t.replace('"NotifLab Fake Call Lab • v0.4.3"', '"NotifLab Fake Call Lab • v0.4.4"', 1)
t = t.replace(
    '"Direct CallStyle remains a policy probe. TRUE FSI tests are posted later by the foreground service after this Activity backgrounds itself, so you can lock the phone before the incoming call exists."',
    '"Direct CallStyle remains a policy probe. Immediate FSI probes may remain notification-only while this Activity is already foreground. TRUE FSI backgrounds NotifLab first, then posts later so Android can launch the incoming-call screen over a locked phone."',
    1,
)
t = t.replace('text = "Full-screen intent calls"', 'text = "Immediate full-screen-intent probes"', 1)
p.write_text(t, encoding='utf-8')

# Replace the diagnostic postcard with an unmistakable call-shaped full-screen Activity.
# This is still only an FSI/CallStyle test. It intentionally does not register a Telecom call.
p = kt / 'FakeFullScreenCallActivity.kt'
p.write_text(r'''package com.randotone.notiflab

import android.app.Activity
import android.app.NotificationManager
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
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
        window.addFlags(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_FULLSCREEN
        )
        window.statusBarColor = Color.BLACK
        window.navigationBarColor = Color.BLACK
        NotifLabLog.event(applicationContext, "FSI_UI", "onCreate action=${intent?.action}")

        if (handleTerminalAction(intent?.action)) return
        setContentView(buildCallUi())
    }

    override fun onNewIntent(intent: android.content.Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        NotifLabLog.event(applicationContext, "FSI_UI", "onNewIntent action=${intent?.action}")
        if (handleTerminalAction(intent?.action)) return
        if (intent?.action == ACTION_SHOW) setContentView(buildCallUi())
    }

    private fun handleTerminalAction(action: String?): Boolean {
        if (action != ACTION_ANSWER && action != ACTION_DECLINE) return false
        manager.cancel(FakeCallLabActivity.FAKE_CALL_NOTIFICATION_ID)
        NotifLabLog.event(applicationContext, "FSI_UI", "terminal action=$action; notification cancelled")
        finishAndRemoveTask()
        return true
    }

    private fun buildCallUi(): View {
        NotifLabLog.event(applicationContext, "FSI_UI", "render incoming-call layout")
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setBackgroundColor(Color.rgb(16, 18, 22))
            setPadding(dp(28), dp(42), dp(28), dp(34))
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )

            addView(TextView(this@FakeFullScreenCallActivity).apply {
                text = "INCOMING CALL"
                textSize = 14f
                setTextColor(Color.rgb(185, 190, 198))
                gravity = Gravity.CENTER
                letterSpacing = 0.12f
                typeface = Typeface.DEFAULT_BOLD
            })

            addView(View(this@FakeFullScreenCallActivity).apply {
                layoutParams = LinearLayout.LayoutParams(1, 0, 0.65f)
            })

            addView(TextView(this@FakeFullScreenCallActivity).apply {
                text = "N"
                textSize = 42f
                setTextColor(Color.WHITE)
                gravity = Gravity.CENTER
                typeface = Typeface.DEFAULT_BOLD
                background = GradientDrawable().apply {
                    shape = GradientDrawable.OVAL
                    setColor(Color.rgb(68, 76, 92))
                }
                layoutParams = LinearLayout.LayoutParams(dp(112), dp(112))
            })

            addView(TextView(this@FakeFullScreenCallActivity).apply {
                text = "NotifLab Caller"
                textSize = 31f
                setTextColor(Color.WHITE)
                gravity = Gravity.CENTER
                typeface = Typeface.DEFAULT_BOLD
                setPadding(0, dp(24), 0, 0)
            })

            addView(TextView(this@FakeFullScreenCallActivity).apply {
                text = "Simulated incoming call • full-screen intent"
                textSize = 16f
                setTextColor(Color.rgb(190, 194, 202))
                gravity = Gravity.CENTER
                setPadding(0, dp(8), 0, 0)
            })

            addView(TextView(this@FakeFullScreenCallActivity).apply {
                text = "Notification/FSI test only • no Telecom call is registered"
                textSize = 12f
                setTextColor(Color.rgb(130, 136, 146))
                gravity = Gravity.CENTER
                setPadding(0, dp(8), 0, 0)
            })

            addView(View(this@FakeFullScreenCallActivity).apply {
                layoutParams = LinearLayout.LayoutParams(1, 0, 1.0f)
            })

            addView(LinearLayout(this@FakeFullScreenCallActivity).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER

                addView(
                    callButton("Decline", Color.rgb(183, 48, 48)) { finishCall(ACTION_DECLINE) },
                    LinearLayout.LayoutParams(0, dp(68), 1f).apply { marginEnd = dp(8) }
                )
                addView(
                    callButton("Answer", Color.rgb(38, 142, 80)) { finishCall(ACTION_ANSWER) },
                    LinearLayout.LayoutParams(0, dp(68), 1f).apply { marginStart = dp(8) }
                )
            })
        }
    }

    private fun callButton(label: String, color: Int, action: () -> Unit): Button = Button(this).apply {
        text = label
        textSize = 18f
        isAllCaps = false
        setTextColor(Color.WHITE)
        typeface = Typeface.DEFAULT_BOLD
        backgroundTintList = ColorStateList.valueOf(color)
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

print('Applied NotifLab v0.4.4 scroll fix + incoming-call FSI layout')
