#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch-notiflab-v0.5-ui-overhaul.py <project-dir>')

project = Path(sys.argv[1]).resolve()
app = project / 'app'
kt = app / 'src' / 'main' / 'java' / 'com' / 'randotone' / 'notiflab'


def matching_brace(text: str, open_index: int) -> int:
    depth = 0
    state = 'code'
    i = open_index
    while i < len(text):
        c = text[i]
        n = text[i + 1] if i + 1 < len(text) else ''
        if state == 'code':
            if c == '/' and n == '/': state = 'line'; i += 2; continue
            if c == '/' and n == '*': state = 'block'; i += 2; continue
            if text.startswith('"""', i): state = 'triple'; i += 3; continue
            if c == '"': state = 'string'; i += 1; continue
            if c == "'": state = 'char'; i += 1; continue
            if c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0: return i
            i += 1; continue
        if state == 'line':
            if c == '\n': state = 'code'
            i += 1; continue
        if state == 'block':
            if c == '*' and n == '/': state = 'code'; i += 2; continue
            i += 1; continue
        if state == 'triple':
            if text.startswith('"""', i): state = 'code'; i += 3; continue
            i += 1; continue
        quote = '"' if state == 'string' else "'"
        if c == '\\': i += 2; continue
        if c == quote: state = 'code'
        i += 1
    raise ValueError('unterminated block')

build = app / 'build.gradle.kts'
t = build.read_text(encoding='utf-8')
t = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 9', t)
t = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.5.0"', t)
build.write_text(t, encoding='utf-8')

# Replace the accumulated one-page firing range with four small workspaces.
(kt / 'MainActivity.kt').write_text(r'''package com.randotone.notiflab

import android.Manifest
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {
    private lateinit var content: LinearLayout
    private lateinit var navRow: LinearLayout
    private var selectedSection = Section.DASHBOARD

    private var titleInput: EditText? = null
    private var bodyInput: EditText? = null
    private var lanStatus: TextView? = null
    private var activityStatus: TextView? = null
    private var timedIntervalInput: EditText? = null
    private var timedCountInput: EditText? = null
    private var timedStatus: TextView? = null
    private var serviceStatus: TextView? = null

    private val mainHandler = Handler(Looper.getMainLooper())
    private val statusPoll = object : Runnable {
        override fun run() {
            refreshRuntimeState()
            mainHandler.postDelayed(this, 500L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        NotifLabLog.event(applicationContext, "ACTIVITY", "MainActivity onCreate ui=v0.5")
        setContentView(buildShell())
        requestNotificationPermissionIfNeeded()
        startHarnessService()
        showSection(Section.DASHBOARD)
    }

    override fun onResume() {
        super.onResume()
        NotifLabLog.event(applicationContext, "ACTIVITY", "MainActivity onResume section=${selectedSection.name}")
        mainHandler.removeCallbacks(statusPoll)
        mainHandler.post(statusPoll)
    }

    override fun onPause() {
        mainHandler.removeCallbacks(statusPoll)
        super.onPause()
    }

    private fun buildShell(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(14), dp(14), dp(8))
        }

        root.addView(TextView(this).apply {
            text = "NotifLab"
            textSize = 30f
            setTypeface(typeface, Typeface.BOLD)
        })
        root.addView(TextView(this).apply {
            text = "notification + incoming-call test harness • v0.5"
            textSize = 13f
            setPadding(0, 0, 0, dp(8))
        })

        navRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        root.addView(HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            addView(navRow)
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))

        content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, dp(10), 0, dp(24))
        }
        root.addView(ScrollView(this).apply {
            isFillViewport = true
            addView(content, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))

        rebuildNavigation()
        return root
    }

    private fun rebuildNavigation() {
        navRow.removeAllViews()
        Section.entries.forEach { section ->
            navRow.addView(Button(this).apply {
                text = section.label
                isAllCaps = false
                minHeight = dp(44)
                isEnabled = selectedSection != section
                setOnClickListener { showSection(section) }
            }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                marginEnd = dp(5)
            })
        }
    }

    private fun showSection(section: Section) {
        selectedSection = section
        rebuildNavigation()
        content.removeAllViews()
        clearSectionRefs()
        NotifLabLog.event(applicationContext, "UI", "section=${section.name}")
        when (section) {
            Section.DASHBOARD -> buildDashboard()
            Section.NOTIFICATIONS -> buildNotificationLab()
            Section.CALLS -> buildCallHub()
            Section.DIAGNOSTICS -> buildDiagnostics()
        }
        refreshRuntimeState()
    }

    private fun clearSectionRefs() {
        titleInput = null; bodyInput = null; lanStatus = null; activityStatus = null
        timedIntervalInput = null; timedCountInput = null; timedStatus = null; serviceStatus = null
    }

    private fun buildDashboard() {
        content.addView(card("Runtime", "The harness service owns timed tests, LAN control and delayed TRUE FSI calls.") {
            serviceStatus = statusText("Service: checking…", bold = true)
            activityStatus = statusText("Ready.")
            addView(serviceStatus!!)
            addView(activityStatus!!)
        })

        content.addView(card("Labs", "Pick one job instead of scrolling through every button NotifLab has ever collected.") {
            addView(actionButton("Open Notification Lab") { showSection(Section.NOTIFICATIONS) })
            addView(actionButton("Open Call Lab") { showSection(Section.CALLS) })
            addView(actionButton("Open Diagnostics") { showSection(Section.DIAGNOSTICS) })
        })

        content.addView(card("Wireless control", "Same-Wi-Fi control page. The foreground service keeps it alive after a Recents swipe.") {
            lanStatus = statusText("LAN server: checking…")
            addView(lanStatus!!)
            addView(actionButton("Copy control-page address") { copyLanAddress() })
            addView(actionButton("Restart LAN server") { sendCommand("lan-restart") })
        })

        content.addView(card("Foreground service", "Force Stop still ends everything. Normal Recents swipes do not.") {
            addView(actionButton("Start / repair service") { startHarnessService() })
            addView(actionButton("Stop NotifLab service") {
                sendServiceIntent(NotifLabService.ACTION_STOP_SERVICE)
                Toast.makeText(this@MainActivity, "NotifLab service stop requested.", Toast.LENGTH_SHORT).show()
            })
        })
    }

    private fun buildNotificationLab() {
        content.addView(card("Payload", "Shared title/body for the notification tests below.") {
            titleInput = EditText(this@MainActivity).apply {
                hint = "Notification title"
                setText("NotifLab test")
                isSingleLine = true
            }
            bodyInput = EditText(this@MainActivity).apply {
                hint = "Notification body"
                setText("Test notification")
                isSingleLine = true
            }
            addView(titleInput!!)
            addView(bodyInput!!)
        })

        content.addView(card("Basic notifications", "Ordinary posts, bursts and same-ID updates.") {
            addView(actionButton("Normal notification") { sendCommand("notify") })
            addView(actionButton("Burst ×5") { sendCommand("burst", count = 5, interval = 300L) })
            addView(actionButton("Update same notification ID") { sendCommand("update") })
            addView(actionButton("Update same ID + ONLY_ALERT_ONCE") { sendCommand("once") })
        })

        content.addView(card("Shapes & exclusions", "Group, ongoing and category probes used to verify osine filtering.") {
            addView(actionButton("Grouped notifications (3 + summary)") { sendCommand("group") })
            addView(actionButton("Ongoing notification") { sendCommand("ongoing") })
            addView(actionButton("CALL category probe") { sendCommand("call") })
            addView(actionButton("ALARM category probe") { sendCommand("alarm") })
            addView(actionButton("Cancel all test notifications") { sendCommand("cancel") })
        })

        content.addView(card("Timed fire", "Count 0 means keep firing until Stop.") {
            timedIntervalInput = EditText(this@MainActivity).apply {
                hint = "Interval in milliseconds"
                setText("1000")
                inputType = android.text.InputType.TYPE_CLASS_NUMBER
                isSingleLine = true
            }
            timedCountInput = EditText(this@MainActivity).apply {
                hint = "How many? 0 = until stopped"
                setText("10")
                inputType = android.text.InputType.TYPE_CLASS_NUMBER
                isSingleLine = true
            }
            timedStatus = statusText("Timed fire idle.")
            addView(timedIntervalInput!!)
            addView(timedCountInput!!)
            addView(actionButton("Start timed notifications") {
                val interval = timedIntervalInput?.text?.toString()?.toLongOrNull() ?: 1000L
                val count = timedCountInput?.text?.toString()?.toIntOrNull() ?: 10
                sendCommand("timed-start", count = count, interval = interval)
            })
            addView(actionButton("Stop timed notifications") { sendCommand("timed-stop") })
            addView(timedStatus!!)
        })
    }

    private fun buildCallHub() {
        content.addView(card("Incoming-call lab", "CallStyle, ringtone channels, full-screen intent policy and locked-screen takeover tests live in their own workspace.") {
            addView(actionButton("Open dedicated Call Lab") {
                NotifLabLog.event(applicationContext, "UI", "open FakeCallLabActivity")
                startActivity(Intent(this@MainActivity, FakeCallLabActivity::class.java))
            })
        })
        content.addView(card("Which FSI test?", "The two families deliberately test different Android behavior.") {
            addView(statusText("Immediate FSI probe", bold = true))
            addView(statusText("Posts while the Call Lab Activity is already foreground. Android may keep this notification-only."))
            addView(space(dp(8)))
            addView(statusText("TRUE background FSI", bold = true))
            addView(statusText("Arms the foreground service, backgrounds NotifLab, waits 7 seconds, then posts. Lock the phone during the countdown to test real takeover."))
        })
        content.addView(card("LAN shortcut", "The service also accepts /fsi-ring and /fsi-silent while the UI is nowhere near the foreground.") {
            lanStatus = statusText("LAN server: checking…")
            addView(lanStatus!!)
            addView(actionButton("Copy control-page address") { copyLanAddress() })
        })
    }

    private fun buildDiagnostics() {
        content.addView(card("Persistent diagnostics", "Logs survive crashes and normal relaunches. Export is the preferred way to send a complete report.") {
            addView(actionButton("Copy diagnostics to clipboard") { copyDiagnostics() })
            addView(actionButton("Export diagnostics log…") { exportDiagnostics() })
            addView(actionButton("Clear diagnostics and start new session") {
                NotifLabLog.clear(this@MainActivity)
                NotifLabLog.startSession(this@MainActivity)
                Toast.makeText(this@MainActivity, "Diagnostics cleared.", Toast.LENGTH_SHORT).show()
            })
        })
        content.addView(card("Runtime snapshot", "Useful before exporting after a failed test.") {
            serviceStatus = statusText("Service: checking…", bold = true)
            activityStatus = statusText("Ready.")
            lanStatus = statusText("LAN server: checking…")
            timedStatus = statusText("Timed fire: checking…")
            addView(serviceStatus!!); addView(activityStatus!!); addView(lanStatus!!); addView(timedStatus!!)
        })
    }

    private fun card(title: String, subtitle: String, body: LinearLayout.() -> Unit): LinearLayout =
        LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(12), dp(14), dp(10))
            background = GradientDrawable().apply {
                setColor(Color.TRANSPARENT)
                setStroke(dp(1), Color.rgb(190, 194, 200))
                cornerRadius = dp(10).toFloat()
            }
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                bottomMargin = dp(10)
            }
            addView(TextView(this@MainActivity).apply {
                text = title
                textSize = 20f
                setTypeface(typeface, Typeface.BOLD)
            })
            addView(TextView(this@MainActivity).apply {
                text = subtitle
                textSize = 13f
                setPadding(0, dp(2), 0, dp(8))
            })
            body()
        }

    private fun actionButton(label: String, action: () -> Unit): Button = Button(this).apply {
        text = label
        isAllCaps = false
        gravity = Gravity.CENTER
        minHeight = dp(50)
        setOnClickListener { action() }
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
            bottomMargin = dp(5)
        }
    }

    private fun statusText(value: String, bold: Boolean = false): TextView = TextView(this).apply {
        text = value
        textSize = 14f
        if (bold) setTypeface(typeface, Typeface.BOLD)
        setPadding(0, dp(3), 0, dp(5))
        setTextIsSelectable(true)
    }

    private fun space(height: Int): View = View(this).apply {
        layoutParams = LinearLayout.LayoutParams(1, height)
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFICATIONS)
        }
    }

    private fun startHarnessService() {
        val intent = Intent(this, NotifLabService::class.java).setAction(NotifLabService.ACTION_START_SERVICE)
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent) else startService(intent)
            activityStatus?.text = "Foreground service start requested."
        } catch (e: Exception) {
            activityStatus?.text = "Could not start service: ${e.message ?: e.javaClass.simpleName}"
            NotifLabLog.event(applicationContext, "ACTIVITY", "service start failed", e)
        }
    }

    private fun currentTitle(): String = titleInput?.text?.toString()?.takeIf { it.isNotBlank() } ?: "NotifLab test"
    private fun currentBody(): String = bodyInput?.text?.toString()?.takeIf { it.isNotBlank() } ?: "Test notification"

    private fun sendCommand(command: String, count: Int? = null, interval: Long? = null) {
        val intent = Intent(this, NotifLabService::class.java)
            .setAction(NotifLabService.ACTION_COMMAND)
            .putExtra(NotifLabService.EXTRA_COMMAND, command)
            .putExtra(NotifLabService.EXTRA_TITLE, currentTitle())
            .putExtra(NotifLabService.EXTRA_BODY, currentBody())
        if (count != null) intent.putExtra(NotifLabService.EXTRA_COUNT, count)
        if (interval != null) intent.putExtra(NotifLabService.EXTRA_INTERVAL, interval)
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent) else startService(intent)
        } catch (e: Exception) {
            activityStatus?.text = "Command failed: ${e.message ?: e.javaClass.simpleName}"
            NotifLabLog.event(applicationContext, "ACTIVITY", "command failed command=$command", e)
        }
    }

    private fun sendServiceIntent(action: String) {
        try {
            startService(Intent(this, NotifLabService::class.java).setAction(action))
        } catch (e: Exception) {
            activityStatus?.text = "Service action failed: ${e.message ?: e.javaClass.simpleName}"
            NotifLabLog.event(applicationContext, "ACTIVITY", "service action failed action=$action", e)
        }
    }

    private fun refreshRuntimeState() {
        serviceStatus?.text = if (NotifLabRuntime.serviceRunning) "Service: RUNNING • survives Recents swipe" else "Service: stopped"
        activityStatus?.text = NotifLabRuntime.lastStatus
        timedStatus?.text = NotifLabRuntime.timedStatus
        lanStatus?.text = NotifLabRuntime.lanStatus
    }

    private fun copyLanAddress() {
        val address = NotifLabRuntime.lanAddresses.firstOrNull()?.let { "http://$it:${NotifLabService.PORT}/" }
        if (address == null) {
            Toast.makeText(this, "No local IPv4 address found yet.", Toast.LENGTH_SHORT).show()
            return
        }
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("NotifLab LAN address", address))
        Toast.makeText(this, "Copied $address", Toast.LENGTH_SHORT).show()
    }

    private fun copyDiagnostics() {
        val diagnostics = NotifLabLog.readAll(this)
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("NotifLab diagnostics", diagnostics))
        Toast.makeText(this, "NotifLab diagnostics copied.", Toast.LENGTH_SHORT).show()
        NotifLabLog.event(applicationContext, "ACTIVITY", "diagnostics copied chars=${diagnostics.length}")
    }

    private fun exportDiagnostics() {
        val stamp = java.text.SimpleDateFormat("yyyy-MM-dd_HH-mm-ss", java.util.Locale.US).format(java.util.Date())
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
            contentResolver.openOutputStream(uri, "w")?.bufferedWriter(Charsets.UTF_8)?.use { it.write(diagnostics) }
                ?: error("Could not open destination")
            Toast.makeText(this, "Diagnostics exported.", Toast.LENGTH_SHORT).show()
            NotifLabLog.event(applicationContext, "ACTIVITY", "diagnostics exported uri=$uri chars=${diagnostics.length}")
        }.onFailure { error ->
            Toast.makeText(this, "Export failed: ${error.message ?: error.javaClass.simpleName}", Toast.LENGTH_LONG).show()
            NotifLabLog.event(applicationContext, "ACTIVITY", "diagnostics export failed", error)
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private enum class Section(val label: String) {
        DASHBOARD("Dashboard"),
        NOTIFICATIONS("Notification Lab"),
        CALLS("Call Lab"),
        DIAGNOSTICS("Diagnostics")
    }

    companion object {
        private const val REQUEST_NOTIFICATIONS = 100
        private const val REQUEST_EXPORT_DIAGNOSTICS = 101
    }
}
''', encoding='utf-8')

# Keep the proven Call Lab mechanics, but make every control a stable full-width row and
# update its identity to the new workspace-oriented release.
call = kt / 'FakeCallLabActivity.kt'
t = call.read_text(encoding='utf-8')
t = t.replace('"NotifLab Fake Call Lab • v0.4.4"', '"NotifLab Call Lab • v0.5"', 1)
t = t.replace(
    '"Direct CallStyle remains a policy probe. Immediate FSI probes may remain notification-only while this Activity is already foreground. TRUE FSI backgrounds NotifLab first, then posts later so Android can launch the incoming-call screen over a locked phone."',
    '"Immediate probes test Android policy while this screen is foreground. TRUE FSI backgrounds NotifLab first, waits 7 seconds, then posts so a locked-screen takeover can be tested cleanly."',
    1,
)
fn = t.find('private fun button(label: String, action: () -> Unit): Button')
if fn < 0:
    raise SystemExit('FakeCallLab button helper missing')
open_brace = t.find('{', fn)
close_brace = matching_brace(t, open_brace)
new_button = '''private fun button(label: String, action: () -> Unit): Button = Button(this).apply {
        text = label
        isAllCaps = false
        gravity = Gravity.CENTER
        minHeight = dp(52)
        layoutParams = LinearLayout.LayoutParams(
            android.view.ViewGroup.LayoutParams.MATCH_PARENT,
            android.view.ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { bottomMargin = dp(6) }
        setOnClickListener {
            NotifLabLog.event(applicationContext, "CALLLAB", "button=$label")
            action()
        }
    }'''
t = t[:fn] + new_button + t[close_brace + 1:]
call.write_text(t, encoding='utf-8')

print('Patched NotifLab v0.5 UI overhaul')
