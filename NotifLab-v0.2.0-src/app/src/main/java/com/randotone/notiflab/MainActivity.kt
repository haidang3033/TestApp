package com.randotone.notiflab

import android.Manifest
import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
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
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.Socket
import java.net.URLDecoder
import java.nio.charset.StandardCharsets
import java.util.Collections
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

class MainActivity : Activity() {
    private lateinit var notificationManager: NotificationManager
    private lateinit var titleInput: EditText
    private lateinit var bodyInput: EditText
    private lateinit var lanStatus: TextView
    private lateinit var activityStatus: TextView
    private lateinit var timedIntervalInput: EditText
    private lateinit var timedCountInput: EditText
    private lateinit var timedStatus: TextView
    private var lanServer: LanServer? = null
    private val nextId = AtomicInteger(1000)
    private val updateCount = AtomicInteger(0)
    private val onlyAlertOnceCount = AtomicInteger(0)
    private val mainHandler = Handler(Looper.getMainLooper())
    private val timedRunning = AtomicBoolean(false)
    private val timedGeneration = AtomicInteger(0)
    private var timedThread: Thread? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        notificationManager = getSystemService(NotificationManager::class.java)
        createSilentTestChannel()
        requestNotificationPermissionIfNeeded()
        setContentView(buildUi())
        startLanServer()
    }

    override fun onDestroy() {
        stopTimed(updateStatus = false)
        lanServer?.stop()
        lanServer = null
        super.onDestroy()
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
            text = "A notification firing range for RandoTone. The tester channel itself is silent."
            textSize = 15f
            setPadding(0, dp(4), 0, dp(14))
        })

        activityStatus = TextView(this).apply {
            text = "Ready."
            setPadding(0, 0, 0, dp(10))
        }
        root.addView(activityStatus)

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
        root.addView(button("Normal notification") { postNormal() })
        root.addView(button("Burst ×5") { postBurst(5, 300) })
        root.addView(button("Update same notification ID") { postUpdate(false) })
        root.addView(button("Update same ID + ONLY_ALERT_ONCE") { postUpdate(true) })
        root.addView(button("Grouped notifications (3 + summary)") { postGroup() })
        root.addView(button("Ongoing notification") { postOngoing() })
        root.addView(button("CALL category (RandoTone should ignore)") { postCategory(Notification.CATEGORY_CALL) })
        root.addView(button("ALARM category (RandoTone should ignore)") { postCategory(Notification.CATEGORY_ALARM) })
        root.addView(button("Cancel all test notifications") {
            notificationManager.cancelAll()
            setStatus("Cancelled all NotifLab notifications.")
        })

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
            startTimed(interval, count, currentTitle(), currentBody())
        })
        root.addView(button("Stop timed notifications") { stopTimed() })
        root.addView(timedStatus)

        root.addView(sectionTitle("Wireless PC control"))
        lanStatus = TextView(this).apply {
            text = "Starting LAN server…"
            setTextIsSelectable(true)
            setPadding(0, 0, 0, dp(8))
        }
        root.addView(lanStatus)
        root.addView(button("Copy control-page address") { copyLanAddress() })
        root.addView(button("Restart LAN server") {
            lanServer?.stop()
            lanServer = null
            startLanServer()
        })
        root.addView(TextView(this).apply {
            text = "Open the shown address on a PC connected to the same Wi‑Fi. Keep NotifLab open while using LAN control. Any device on your local network can reach the page while the server is running."
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

    private fun createSilentTestChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "NotifLab silent tests",
            NotificationManager.IMPORTANCE_DEFAULT
        ).apply {
            description = "Silent source notifications used to test notification listeners such as RandoTone."
            setSound(null, null)
            enableVibration(false)
            setShowBadge(true)
        }
        notificationManager.createNotificationChannel(channel)
    }

    private fun currentTitle(): String = titleInput.text?.toString()?.takeIf { it.isNotBlank() } ?: "NotifLab test"
    private fun currentBody(): String = bodyInput.text?.toString()?.takeIf { it.isNotBlank() } ?: "Test notification"

    private fun baseBuilder(title: String, body: String): Notification.Builder =
        Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(Notification.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setWhen(System.currentTimeMillis())
            .setShowWhen(true)

    private fun postNormal(title: String = currentTitle(), body: String = currentBody()) {
        val id = nextId.incrementAndGet()
        notificationManager.notify(id, baseBuilder(title, body).build())
        setStatus("Posted normal notification #$id")
    }

    private fun postBurst(count: Int, intervalMs: Long, title: String = currentTitle(), body: String = currentBody()) {
        val safeCount = count.coerceIn(1, 30)
        val safeInterval = intervalMs.coerceIn(0, 5000)
        setStatus("Firing burst: $safeCount notification(s), ${safeInterval}ms apart")
        thread(name = "NotifLab-Burst") {
            repeat(safeCount) { index ->
                val id = nextId.incrementAndGet()
                notificationManager.notify(
                    id,
                    baseBuilder("$title ${index + 1}/$safeCount", "$body • burst item ${index + 1}").build()
                )
                if (index != safeCount - 1 && safeInterval > 0) Thread.sleep(safeInterval)
            }
            setStatus("Burst complete: $safeCount notification(s).")
        }
    }

    private fun startTimed(intervalMs: Long, count: Int, title: String, body: String) {
        val safeInterval = intervalMs.coerceIn(50L, 3_600_000L)
        val safeCount = count.coerceIn(0, 10_000)
        stopTimed(updateStatus = false)

        val generation = timedGeneration.incrementAndGet()
        timedRunning.set(true)
        val countLabel = if (safeCount == 0) "until stopped" else "$safeCount time(s)"
        setTimedStatus("Running: every ${safeInterval}ms, $countLabel. First notification fires after one interval.")
        setStatus("Timed fire started: ${safeInterval}ms interval, $countLabel.")

        timedThread = thread(name = "NotifLab-Timed") {
            var fired = 0
            try {
                while (timedRunning.get() && timedGeneration.get() == generation && (safeCount == 0 || fired < safeCount)) {
                    Thread.sleep(safeInterval)
                    if (!timedRunning.get() || timedGeneration.get() != generation) break
                    fired++
                    val id = nextId.incrementAndGet()
                    val suffix = if (safeCount == 0) "#$fired" else "$fired/$safeCount"
                    notificationManager.notify(
                        id,
                        baseBuilder("$title • timed $suffix", "$body • timed fire $suffix").build()
                    )
                    setTimedStatus("Running: fired $fired${if (safeCount == 0) "" else "/$safeCount"}; next in ${safeInterval}ms.")
                    setStatus("Timed notification #$id fired ($suffix).")
                }
            } catch (_: InterruptedException) {
                // Stop button interrupts sleep so the timer stops immediately.
            } finally {
                if (timedGeneration.get() == generation) {
                    timedRunning.set(false)
                    timedThread = null
                    if (safeCount != 0 && fired >= safeCount) {
                        setTimedStatus("Complete: fired $fired notification(s).")
                        setStatus("Timed fire complete: $fired notification(s).")
                    }
                }
            }
        }
    }

    private fun stopTimed(updateStatus: Boolean = true) {
        timedGeneration.incrementAndGet()
        val wasRunning = timedRunning.getAndSet(false)
        timedThread?.interrupt()
        timedThread = null
        if (updateStatus) {
            setTimedStatus(if (wasRunning) "Stopped." else "Timed fire is already stopped.")
            if (wasRunning) setStatus("Timed fire stopped.")
        }
    }

    private fun setTimedStatus(message: String) {
        mainHandler.post { if (::timedStatus.isInitialized) timedStatus.text = message }
    }

    private fun postUpdate(onlyAlertOnce: Boolean, title: String = currentTitle(), body: String = currentBody()) {
        val counter = if (onlyAlertOnce) onlyAlertOnceCount.incrementAndGet() else updateCount.incrementAndGet()
        val id = if (onlyAlertOnce) ONLY_ALERT_ONCE_ID else UPDATE_ID
        val builder = baseBuilder("$title • update $counter", "$body • same notification ID $id")
        if (onlyAlertOnce) builder.setOnlyAlertOnce(true)
        notificationManager.notify(id, builder.build())
        setStatus("Updated fixed ID $id, revision $counter${if (onlyAlertOnce) " with ONLY_ALERT_ONCE" else ""}.")
    }

    private fun postGroup(title: String = currentTitle(), body: String = currentBody()) {
        val groupKey = "notiflab-group-${System.currentTimeMillis()}"
        repeat(3) { index ->
            val id = nextId.incrementAndGet()
            notificationManager.notify(
                id,
                baseBuilder("$title • group child ${index + 1}", "$body • child ${index + 1}")
                    .setGroup(groupKey)
                    .build()
            )
        }
        val summaryId = nextId.incrementAndGet()
        notificationManager.notify(
            summaryId,
            baseBuilder("$title • group summary", "Three child notifications")
                .setGroup(groupKey)
                .setGroupSummary(true)
                .build()
        )
        setStatus("Posted 3 group children + 1 summary. RandoTone should ignore the summary.")
    }

    private fun postOngoing(title: String = currentTitle(), body: String = currentBody()) {
        val id = nextId.incrementAndGet()
        notificationManager.notify(
            id,
            baseBuilder("$title • ongoing", body)
                .setOngoing(true)
                .setAutoCancel(false)
                .build()
        )
        setStatus("Posted ongoing notification #$id. RandoTone should ignore it.")
    }

    private fun postCategory(category: String, title: String = currentTitle(), body: String = currentBody()) {
        val id = nextId.incrementAndGet()
        notificationManager.notify(
            id,
            baseBuilder("$title • ${category.substringAfterLast('.').uppercase()}", body)
                .setCategory(category)
                .build()
        )
        setStatus("Posted category $category. RandoTone should ignore CALL/ALARM.")
    }

    private fun setStatus(message: String) {
        mainHandler.post { if (::activityStatus.isInitialized) activityStatus.text = message }
    }

    private fun startLanServer() {
        try {
            val server = LanServer(PORT) { command -> handleLanCommand(command) }
            server.start()
            lanServer = server
            val addresses = localIpv4Addresses()
            val display = if (addresses.isEmpty()) {
                "LAN server running on port $PORT, but no local IPv4 address was found. Connect to Wi‑Fi, then tap Restart LAN server."
            } else {
                "LAN control page:\n" + addresses.joinToString("\n") { "http://$it:$PORT/" }
            }
            mainHandler.post { if (::lanStatus.isInitialized) lanStatus.text = display }
        } catch (e: Exception) {
            mainHandler.post {
                if (::lanStatus.isInitialized) lanStatus.text = "LAN server failed: ${e.message ?: e.javaClass.simpleName}"
            }
        }
    }

    private fun copyLanAddress() {
        val address = localIpv4Addresses().firstOrNull()?.let { "http://$it:$PORT/" }
        if (address == null) {
            Toast.makeText(this, "No local IPv4 address found.", Toast.LENGTH_SHORT).show()
            return
        }
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("NotifLab LAN address", address))
        Toast.makeText(this, "Copied $address", Toast.LENGTH_SHORT).show()
    }

    private fun handleLanCommand(command: LanCommand): String {
        val title = command.params["title"]?.takeIf { it.isNotBlank() } ?: "NotifLab remote test"
        val body = command.params["text"]?.takeIf { it.isNotBlank() } ?: "Triggered from the LAN control page"
        return when (command.path) {
            "/notify" -> {
                postNormal(title, body)
                "Normal notification posted"
            }
            "/burst" -> {
                val count = command.params["count"]?.toIntOrNull() ?: 5
                val interval = command.params["interval"]?.toLongOrNull() ?: 300L
                postBurst(count, interval, title, body)
                "Burst started"
            }
            "/timed-start" -> {
                val count = command.params["count"]?.toIntOrNull() ?: 10
                val interval = command.params["interval"]?.toLongOrNull() ?: 1000L
                startTimed(interval, count, title, body)
                val safeInterval = interval.coerceIn(50L, 3_600_000L)
                val safeCount = count.coerceIn(0, 10_000)
                "Timed fire started: every ${safeInterval}ms, ${if (safeCount == 0) "until stopped" else "$safeCount time(s)"}"
            }
            "/timed-stop" -> {
                stopTimed()
                "Timed fire stopped"
            }
            "/update" -> {
                postUpdate(false, title, body)
                "Fixed-ID notification updated"
            }
            "/once" -> {
                postUpdate(true, title, body)
                "ONLY_ALERT_ONCE notification updated"
            }
            "/group" -> {
                postGroup(title, body)
                "Group posted"
            }
            "/ongoing" -> {
                postOngoing(title, body)
                "Ongoing notification posted"
            }
            "/call" -> {
                postCategory(Notification.CATEGORY_CALL, title, body)
                "CALL-category notification posted"
            }
            "/alarm" -> {
                postCategory(Notification.CATEGORY_ALARM, title, body)
                "ALARM-category notification posted"
            }
            "/cancel" -> {
                notificationManager.cancelAll()
                setStatus("Cancelled all NotifLab notifications from LAN control.")
                "All NotifLab notifications cancelled"
            }
            else -> "Unknown command"
        }
    }

    private fun localIpv4Addresses(): List<String> {
        return try {
            val result = mutableListOf<Pair<Int, String>>()
            val interfaces = Collections.list(NetworkInterface.getNetworkInterfaces())
            for (network in interfaces) {
                if (!network.isUp || network.isLoopback) continue
                val priority = if (network.name.startsWith("wlan", ignoreCase = true)) 0 else 1
                for (address in Collections.list(network.inetAddresses)) {
                    if (address is Inet4Address && !address.isLoopbackAddress && address.isSiteLocalAddress) {
                        result += priority to address.hostAddress
                    }
                }
            }
            result.sortedWith(compareBy<Pair<Int, String>> { it.first }.thenBy { it.second }).map { it.second }.distinct()
        } catch (_: Exception) {
            emptyList()
        }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    companion object {
        private const val CHANNEL_ID = "notiflab_test_silent"
        private const val REQUEST_NOTIFICATIONS = 100
        private const val PORT = 8765
        private const val UPDATE_ID = 4242
        private const val ONLY_ALERT_ONCE_ID = 4343
    }
}

data class LanCommand(val path: String, val params: Map<String, String>)

class LanServer(
    private val port: Int,
    private val commandHandler: (LanCommand) -> String
) {
    private val running = AtomicBoolean(false)
    private var serverSocket: ServerSocket? = null
    private var serverThread: Thread? = null

    fun start() {
        if (!running.compareAndSet(false, true)) return
        val socket = ServerSocket(port)
        socket.reuseAddress = true
        serverSocket = socket
        serverThread = thread(name = "NotifLab-LAN", isDaemon = true) {
            while (running.get()) {
                try {
                    val client = socket.accept()
                    thread(name = "NotifLab-HTTP", isDaemon = true) { handleClient(client) }
                } catch (_: Exception) {
                    if (running.get()) Thread.sleep(50)
                }
            }
        }
    }

    fun stop() {
        running.set(false)
        try { serverSocket?.close() } catch (_: Exception) {}
        serverSocket = null
    }

    private fun handleClient(socket: Socket) {
        socket.use { client ->
            client.soTimeout = 3000
            val reader = BufferedReader(InputStreamReader(client.getInputStream(), StandardCharsets.UTF_8))
            val requestLine = reader.readLine() ?: return
            while (true) {
                val line = reader.readLine() ?: break
                if (line.isEmpty()) break
            }

            val rawTarget = requestLine.split(" ").getOrNull(1) ?: "/"
            val question = rawTarget.indexOf('?')
            val rawPath = if (question >= 0) rawTarget.substring(0, question) else rawTarget
            val rawQuery = if (question >= 0) rawTarget.substring(question + 1) else ""
            val path = decode(rawPath)
            val params = parseQuery(rawQuery)

            if (path == "/" || path == "/index.html") {
                respond(client.getOutputStream(), 200, "text/html; charset=utf-8", controlPage())
            } else if (path == "/favicon.ico") {
                respond(client.getOutputStream(), 204, "text/plain", "")
            } else {
                val known = setOf("/notify", "/burst", "/timed-start", "/timed-stop", "/update", "/once", "/group", "/ongoing", "/call", "/alarm", "/cancel")
                if (path in known) {
                    val result = commandHandler(LanCommand(path, params))
                    respond(client.getOutputStream(), 200, "text/plain; charset=utf-8", result)
                } else {
                    respond(client.getOutputStream(), 404, "text/plain; charset=utf-8", "Not found")
                }
            }
        }
    }

    private fun parseQuery(raw: String): Map<String, String> {
        if (raw.isBlank()) return emptyMap()
        return raw.split('&').mapNotNull { part ->
            if (part.isBlank()) return@mapNotNull null
            val equals = part.indexOf('=')
            val key = decode(if (equals >= 0) part.substring(0, equals) else part)
            val value = decode(if (equals >= 0) part.substring(equals + 1) else "")
            key to value
        }.toMap()
    }

    private fun decode(value: String): String = URLDecoder.decode(value, StandardCharsets.UTF_8.name())

    private fun respond(output: OutputStream, status: Int, contentType: String, body: String) {
        val bytes = body.toByteArray(StandardCharsets.UTF_8)
        val reason = when (status) {
            200 -> "OK"
            204 -> "No Content"
            404 -> "Not Found"
            else -> "OK"
        }
        val header = buildString {
            append("HTTP/1.1 $status $reason\r\n")
            append("Content-Type: $contentType\r\n")
            append("Content-Length: ${bytes.size}\r\n")
            append("Cache-Control: no-store\r\n")
            append("Connection: close\r\n")
            append("\r\n")
        }.toByteArray(StandardCharsets.UTF_8)
        output.write(header)
        if (status != 204) output.write(bytes)
        output.flush()
    }

    private fun controlPage(): String = """
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width,initial-scale=1">
          <title>NotifLab</title>
          <style>
            body{font-family:system-ui,sans-serif;max-width:760px;margin:32px auto;padding:0 18px;background:#111;color:#eee}
            input{box-sizing:border-box;width:100%;padding:11px;margin:5px 0;background:#222;color:#fff;border:1px solid #555;border-radius:8px}
            .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:9px;margin-top:14px}
            button{padding:13px;border:0;border-radius:9px;font-weight:650;cursor:pointer}
            #status{margin-top:16px;padding:12px;background:#222;border-radius:8px;min-height:22px}
            .small{font-size:13px;color:#aaa}
          </style>
        </head>
        <body>
          <h1>NotifLab 📡</h1>
          <p>Remote notification firing range. Every button posts a notification on the phone.</p>
          <label>Title</label><input id="title" value="NotifLab remote test">
          <label>Body</label><input id="text" value="Triggered from PC">
          <div class="grid">
            <button onclick="fire('/notify')">Normal</button>
            <button onclick="burst()">Burst ×5</button>
            <button onclick="fire('/update')">Update same ID</button>
            <button onclick="fire('/once')">ONLY_ALERT_ONCE update</button>
            <button onclick="fire('/group')">Group 3 + summary</button>
            <button onclick="fire('/ongoing')">Ongoing</button>
            <button onclick="fire('/call')">CALL category</button>
            <button onclick="fire('/alarm')">ALARM category</button>
            <button onclick="fire('/cancel')">Cancel all</button>
          </div>
          <p class="small">Burst settings</p>
          <input id="count" type="number" min="1" max="30" value="5" placeholder="Burst count">
          <input id="interval" type="number" min="0" max="5000" value="300" placeholder="Burst interval (ms)">

          <h2>Timed fire ⏱️</h2>
          <p class="small">Fire one normal notification every interval. Set count to 0 to continue until Stop.</p>
          <input id="timedInterval" type="number" min="50" max="3600000" value="1000" placeholder="Interval (ms)">
          <input id="timedCount" type="number" min="0" max="10000" value="10" placeholder="Count; 0 = until stopped">
          <div class="grid">
            <button onclick="timedStart()">Start timed fire</button>
            <button onclick="fire('/timed-stop')">Stop timed fire</button>
          </div>
          <div id="status">Ready.</div>
          <script>
            function qs(){return '?title='+encodeURIComponent(title.value)+'&text='+encodeURIComponent(text.value)}
            async function fire(path){status.textContent='Sending…';try{let r=await fetch(path+qs());status.textContent=await r.text()}catch(e){status.textContent='Failed: '+e}}
            async function burst(){status.textContent='Sending burst…';let extra='&count='+encodeURIComponent(count.value)+'&interval='+encodeURIComponent(interval.value);try{let r=await fetch('/burst'+qs()+extra);status.textContent=await r.text()}catch(e){status.textContent='Failed: '+e}}
            async function timedStart(){status.textContent='Starting timed fire…';let extra='&count='+encodeURIComponent(timedCount.value)+'&interval='+encodeURIComponent(timedInterval.value);try{let r=await fetch('/timed-start'+qs()+extra);status.textContent=await r.text()}catch(e){status.textContent='Failed: '+e}}
          </script>
        </body>
        </html>
    """.trimIndent()
}
