package com.randotone.notiflab

import android.Manifest
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {
    private lateinit var titleInput: EditText
    private lateinit var bodyInput: EditText
    private lateinit var lanStatus: TextView
    private lateinit var activityStatus: TextView
    private lateinit var timedIntervalInput: EditText
    private lateinit var timedCountInput: EditText
    private lateinit var timedStatus: TextView
    private lateinit var serviceStatus: TextView

    private val mainHandler = Handler(Looper.getMainLooper())
    private val statusPoll = object : Runnable {
        override fun run() {
            refreshRuntimeState()
            mainHandler.postDelayed(this, 500L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildUi())
        requestNotificationPermissionIfNeeded()
        startHarnessService()
    }

    override fun onResume() {
        super.onResume()
        mainHandler.removeCallbacks(statusPoll)
        mainHandler.post(statusPoll)
    }

    override fun onPause() {
        mainHandler.removeCallbacks(statusPoll)
        super.onPause()
    }

    private fun buildUi(): View {
        val scroll = ScrollView(this)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(18), dp(18), dp(28))
        }
        scroll.addView(root)

        root.addView(TextView(this).apply {
            text = "NotifLab"
            textSize = 28f
            setTypeface(typeface, Typeface.BOLD)
        })
        root.addView(TextView(this).apply {
            text = "A notification firing range for RandoTone. v0.3 keeps the LAN server and timed fire alive in a foreground service after you swipe the app away."
            textSize = 15f
            setPadding(0, dp(4), 0, dp(14))
        })

        activityStatus = TextView(this).apply {
            text = "Ready."
            setPadding(0, 0, 0, dp(8))
        }
        serviceStatus = TextView(this).apply {
            text = "Service: starting…"
            setTypeface(typeface, Typeface.BOLD)
            setPadding(0, 0, 0, dp(12))
        }
        root.addView(activityStatus)
        root.addView(serviceStatus)

        titleInput = EditText(this).apply {
            hint = "Notification title"
            setText("NotifLab test")
            isSingleLine = true
        }
        bodyInput = EditText(this).apply {
            hint = "Notification body"
            setText("Random bullshit go boom")
            isSingleLine = true
        }
        root.addView(titleInput)
        root.addView(bodyInput)

        root.addView(sectionTitle("Local tests"))
        root.addView(button("Normal notification") { sendCommand("notify") })
        root.addView(button("Burst ×5") { sendCommand("burst", count = 5, interval = 300L) })
        root.addView(button("Update same notification ID") { sendCommand("update") })
        root.addView(button("Update same ID + ONLY_ALERT_ONCE") { sendCommand("once") })
        root.addView(button("Grouped notifications (3 + summary)") { sendCommand("group") })
        root.addView(button("Ongoing notification") { sendCommand("ongoing") })
        root.addView(button("CALL category (RandoTone should ignore)") { sendCommand("call") })
        root.addView(button("ALARM category (RandoTone should ignore)") { sendCommand("alarm") })
        root.addView(button("Cancel all test notifications") { sendCommand("cancel") })

        root.addView(sectionTitle("Timed fire"))
        timedIntervalInput = EditText(this).apply {
            hint = "Interval in milliseconds"
            setText("1000")
            inputType = android.text.InputType.TYPE_CLASS_NUMBER
            isSingleLine = true
        }
        timedCountInput = EditText(this).apply {
            hint = "How many notifications? 0 = until stopped"
            setText("10")
            inputType = android.text.InputType.TYPE_CLASS_NUMBER
            isSingleLine = true
        }
        timedStatus = TextView(this).apply {
            text = "Timed fire idle. Count 0 means run until Stop."
            setPadding(0, dp(4), 0, dp(8))
        }
        root.addView(timedIntervalInput)
        root.addView(timedCountInput)
        root.addView(button("Start timed notifications") {
            val interval = timedIntervalInput.text?.toString()?.toLongOrNull() ?: 1000L
            val count = timedCountInput.text?.toString()?.toIntOrNull() ?: 10
            sendCommand("timed-start", count = count, interval = interval)
        })
        root.addView(button("Stop timed notifications") { sendCommand("timed-stop") })
        root.addView(timedStatus)

        root.addView(sectionTitle("Wireless PC control"))
        lanStatus = TextView(this).apply {
            text = "LAN server: starting…"
            setTextIsSelectable(true)
            setPadding(0, 0, 0, dp(8))
        }
        root.addView(lanStatus)
        root.addView(button("Copy control-page address") { copyLanAddress() })
        root.addView(button("Restart LAN server") { sendCommand("lan-restart") })
        root.addView(TextView(this).apply {
            text = "Open the shown address on a PC on the same Wi‑Fi. In v0.3, the LAN page stays available after you swipe NotifLab out of Recents as long as the foreground service is running."
            textSize = 13f
            setPadding(0, dp(8), 0, 0)
        })

        root.addView(sectionTitle("Foreground service"))
        root.addView(button("Start / repair service") { startHarnessService() })
        root.addView(button("Stop NotifLab service") {
            sendServiceIntent(NotifLabService.ACTION_STOP_SERVICE)
            Toast.makeText(this, "NotifLab service stop requested.", Toast.LENGTH_SHORT).show()
        })
        root.addView(TextView(this).apply {
            text = "The persistent NotifLab service notification is intentionally ongoing and silent. RandoTone should ignore it. Force Stop from Android settings will still stop everything, because Android always keeps the final boss button."
            textSize = 13f
            setPadding(0, dp(8), 0, 0)
        })

        return scroll
    }

    private fun sectionTitle(textValue: String): TextView = TextView(this).apply {
        text = textValue
        textSize = 19f
        setTypeface(typeface, Typeface.BOLD)
        setPadding(0, dp(20), 0, dp(8))
    }

    private fun button(label: String, action: () -> Unit): Button = Button(this).apply {
        text = label
        isAllCaps = false
        gravity = Gravity.CENTER
        setOnClickListener { action() }
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFICATIONS)
        }
    }

    private fun startHarnessService() {
        val intent = Intent(this, NotifLabService::class.java).setAction(NotifLabService.ACTION_START_SERVICE)
        try {
            startForegroundService(intent)
            activityStatus.text = "Foreground service start requested."
        } catch (e: Exception) {
            activityStatus.text = "Could not start service: ${e.message ?: e.javaClass.simpleName}"
        }
    }

    private fun currentTitle(): String = titleInput.text?.toString()?.takeIf { it.isNotBlank() } ?: "NotifLab test"
    private fun currentBody(): String = bodyInput.text?.toString()?.takeIf { it.isNotBlank() } ?: "Test notification"

    private fun sendCommand(command: String, count: Int? = null, interval: Long? = null) {
        val intent = Intent(this, NotifLabService::class.java)
            .setAction(NotifLabService.ACTION_COMMAND)
            .putExtra(NotifLabService.EXTRA_COMMAND, command)
            .putExtra(NotifLabService.EXTRA_TITLE, currentTitle())
            .putExtra(NotifLabService.EXTRA_BODY, currentBody())
        if (count != null) intent.putExtra(NotifLabService.EXTRA_COUNT, count)
        if (interval != null) intent.putExtra(NotifLabService.EXTRA_INTERVAL, interval)
        try {
            startForegroundService(intent)
        } catch (e: Exception) {
            activityStatus.text = "Command failed: ${e.message ?: e.javaClass.simpleName}"
        }
    }

    private fun sendServiceIntent(action: String) {
        try {
            startService(Intent(this, NotifLabService::class.java).setAction(action))
        } catch (e: Exception) {
            activityStatus.text = "Service action failed: ${e.message ?: e.javaClass.simpleName}"
        }
    }

    private fun refreshRuntimeState() {
        if (!::serviceStatus.isInitialized) return
        serviceStatus.text = if (NotifLabRuntime.serviceRunning) {
            "Service: RUNNING • survives Recents swipe"
        } else {
            "Service: stopped"
        }
        activityStatus.text = NotifLabRuntime.lastStatus
        timedStatus.text = NotifLabRuntime.timedStatus
        lanStatus.text = NotifLabRuntime.lanStatus
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

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    companion object {
        private const val REQUEST_NOTIFICATIONS = 100
    }
}
