package com.randotone.notiflab

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
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
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

object NotifLabRuntime {
    @Volatile var serviceRunning: Boolean = false
    @Volatile var lastStatus: String = "Ready."
    @Volatile var timedStatus: String = "Timed fire idle. Count 0 means run until Stop."
    @Volatile var lanStatus: String = "LAN server: stopped"
    @Volatile var lanAddresses: List<String> = emptyList()
}

class NotifLabService : Service() {
    private lateinit var notificationManager: NotificationManager
    private var lanServer: LanServer? = null

    private val nextId = AtomicInteger(1000)
    private val updateCount = AtomicInteger(0)
    private val onlyAlertOnceCount = AtomicInteger(0)
    private val timedRunning = AtomicBoolean(false)
    private val timedGeneration = AtomicInteger(0)
    private var timedThread: Thread? = null
    private val testNotificationIds = ConcurrentHashMap.newKeySet<Int>()

    override fun onCreate() {
        super.onCreate()
        notificationManager = getSystemService(NotificationManager::class.java)
        createChannels()
        NotifLabRuntime.serviceRunning = true
        NotifLabRuntime.lastStatus = "Foreground service created."
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        promoteToForeground()
        ensureLanServer()

        when (intent?.action) {
            ACTION_STOP_SERVICE -> {
                NotifLabRuntime.lastStatus = "Stopping NotifLab foreground service…"
                NotifLabRuntime.serviceRunning = false
                stopTimed(updateStatus = false)
                stopLanServer()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_COMMAND -> handleCommandIntent(intent)
            ACTION_START_SERVICE, null -> {
                NotifLabRuntime.lastStatus = "Foreground service running. LAN control is active."
            }
        }

        updateServiceNotification()
        return START_STICKY
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Deliberately do not stop. Swiping the task away should leave the foreground service alive.
        NotifLabRuntime.lastStatus = "App task swiped away; foreground service is still running."
        updateServiceNotification()
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        NotifLabRuntime.serviceRunning = false
        stopTimed(updateStatus = false)
        stopLanServer()
        NotifLabRuntime.lastStatus = "NotifLab service stopped."
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun promoteToForeground() {
        val notification = buildServiceNotification()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(
                SERVICE_NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            )
        } else {
            startForeground(SERVICE_NOTIFICATION_ID, notification)
        }
        NotifLabRuntime.serviceRunning = true
    }

    private fun buildServiceNotification(): Notification {
        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val timerText = if (timedRunning.get()) "timer running" else "timer idle"
        val address = NotifLabRuntime.lanAddresses.firstOrNull()?.let { "http://$it:$PORT" } ?: "LAN waiting"
        return Notification.Builder(this, SERVICE_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_manage)
            .setContentTitle("NotifLab service running")
            .setContentText("$address • $timerText")
            .setStyle(Notification.BigTextStyle().bigText("NotifLab LAN controller and timed-fire engine are active. $address • $timerText"))
            .setContentIntent(openIntent)
            .setCategory(Notification.CATEGORY_SERVICE)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .build()
    }

    private fun updateServiceNotification() {
        if (NotifLabRuntime.serviceRunning) {
            notificationManager.notify(SERVICE_NOTIFICATION_ID, buildServiceNotification())
        }
    }

    private fun createChannels() {
        val testChannel = NotificationChannel(
            TEST_CHANNEL_ID,
            "NotifLab silent tests",
            NotificationManager.IMPORTANCE_DEFAULT
        ).apply {
            description = "Silent source notifications used to test notification listeners such as RandoTone."
            setSound(null, null)
            enableVibration(false)
            setShowBadge(true)
        }
        val serviceChannel = NotificationChannel(
            SERVICE_CHANNEL_ID,
            "NotifLab foreground service",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Keeps NotifLab LAN control and timed tests running after the app UI is swiped away."
            setSound(null, null)
            enableVibration(false)
            setShowBadge(false)
        }
        notificationManager.createNotificationChannel(testChannel)
        notificationManager.createNotificationChannel(serviceChannel)
    }

    private fun baseBuilder(title: String, body: String): Notification.Builder =
        Notification.Builder(this, TEST_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(Notification.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .setWhen(System.currentTimeMillis())
            .setShowWhen(true)

    private fun notifyTest(id: Int, notification: Notification) {
        testNotificationIds += id
        notificationManager.notify(id, notification)
    }

    private fun postNormal(title: String, body: String) {
        val id = nextId.incrementAndGet()
        notifyTest(id, baseBuilder(title, body).build())
        setStatus("Posted normal notification #$id")
    }

    private fun postBurst(count: Int, intervalMs: Long, title: String, body: String) {
        val safeCount = count.coerceIn(1, 30)
        val safeInterval = intervalMs.coerceIn(0, 5000)
        setStatus("Firing burst: $safeCount notification(s), ${safeInterval}ms apart")
        thread(name = "NotifLab-Burst") {
            repeat(safeCount) { index ->
                val id = nextId.incrementAndGet()
                notifyTest(
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
        updateServiceNotification()

        timedThread = thread(name = "NotifLab-Timed") {
            var fired = 0
            try {
                while (timedRunning.get() && timedGeneration.get() == generation && (safeCount == 0 || fired < safeCount)) {
                    Thread.sleep(safeInterval)
                    if (!timedRunning.get() || timedGeneration.get() != generation) break
                    fired++
                    val id = nextId.incrementAndGet()
                    val suffix = if (safeCount == 0) "#$fired" else "$fired/$safeCount"
                    notifyTest(
                        id,
                        baseBuilder("$title • timed $suffix", "$body • timed fire $suffix").build()
                    )
                    setTimedStatus("Running: fired $fired${if (safeCount == 0) "" else "/$safeCount"}; next in ${safeInterval}ms.")
                    setStatus("Timed notification #$id fired ($suffix).")
                }
            } catch (_: InterruptedException) {
                // Stop interrupts sleep so the timer ends immediately.
            } finally {
                if (timedGeneration.get() == generation) {
                    timedRunning.set(false)
                    timedThread = null
                    if (safeCount != 0 && fired >= safeCount) {
                        setTimedStatus("Complete: fired $fired notification(s).")
                        setStatus("Timed fire complete: $fired notification(s).")
                    }
                    updateServiceNotification()
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
        updateServiceNotification()
    }

    private fun postUpdate(onlyAlertOnce: Boolean, title: String, body: String) {
        val counter = if (onlyAlertOnce) onlyAlertOnceCount.incrementAndGet() else updateCount.incrementAndGet()
        val id = if (onlyAlertOnce) ONLY_ALERT_ONCE_ID else UPDATE_ID
        val builder = baseBuilder("$title • update $counter", "$body • same notification ID $id")
        if (onlyAlertOnce) builder.setOnlyAlertOnce(true)
        notifyTest(id, builder.build())
        setStatus("Updated fixed ID $id, revision $counter${if (onlyAlertOnce) " with ONLY_ALERT_ONCE" else ""}.")
    }

    private fun postGroup(title: String, body: String) {
        val groupKey = "notiflab-group-${System.currentTimeMillis()}"
        repeat(3) { index ->
            val id = nextId.incrementAndGet()
            notifyTest(
                id,
                baseBuilder("$title • group child ${index + 1}", "$body • child ${index + 1}")
                    .setGroup(groupKey)
                    .build()
            )
        }
        val summaryId = nextId.incrementAndGet()
        notifyTest(
            summaryId,
            baseBuilder("$title • group summary", "Three child notifications")
                .setGroup(groupKey)
                .setGroupSummary(true)
                .build()
        )
        setStatus("Posted 3 group children + 1 summary. RandoTone should ignore the summary.")
    }

    private fun postOngoing(title: String, body: String) {
        val id = nextId.incrementAndGet()
        notifyTest(
            id,
            baseBuilder("$title • ongoing", body)
                .setOngoing(true)
                .setAutoCancel(false)
                .build()
        )
        setStatus("Posted ongoing notification #$id. RandoTone should ignore it.")
    }

    private fun postCategory(category: String, title: String, body: String) {
        val id = nextId.incrementAndGet()
        notifyTest(
            id,
            baseBuilder("$title • ${category.substringAfterLast('.').uppercase()}", body)
                .setCategory(category)
                .build()
        )
        setStatus("Posted category $category. RandoTone should ignore CALL/ALARM.")
    }

    private fun cancelTestNotifications() {
        for (id in testNotificationIds) notificationManager.cancel(id)
        testNotificationIds.clear()
        setStatus("Cancelled all NotifLab test notifications. Foreground service remains alive.")
    }

    private fun handleCommandIntent(intent: Intent) {
        val command = intent.getStringExtra(EXTRA_COMMAND) ?: return
        val title = intent.getStringExtra(EXTRA_TITLE)?.takeIf { it.isNotBlank() } ?: "NotifLab test"
        val body = intent.getStringExtra(EXTRA_BODY)?.takeIf { it.isNotBlank() } ?: "Test notification"
        val count = intent.getIntExtra(EXTRA_COUNT, 10)
        val interval = intent.getLongExtra(EXTRA_INTERVAL, 1000L)
        handleCommand(command, title, body, count, interval)
    }

    private fun handleCommand(command: String, title: String, body: String, count: Int, interval: Long): String = when (command) {
        "notify" -> { postNormal(title, body); "Normal notification posted" }
        "burst" -> { postBurst(count, interval, title, body); "Burst started" }
        "timed-start" -> {
            startTimed(interval, count, title, body)
            "Timed fire started: every ${interval.coerceIn(50L, 3_600_000L)}ms, ${if (count <= 0) "until stopped" else "${count.coerceAtMost(10_000)} time(s)"}"
        }
        "timed-stop" -> { stopTimed(); "Timed fire stopped" }
        "update" -> { postUpdate(false, title, body); "Fixed-ID notification updated" }
        "once" -> { postUpdate(true, title, body); "ONLY_ALERT_ONCE notification updated" }
        "group" -> { postGroup(title, body); "Group posted" }
        "ongoing" -> { postOngoing(title, body); "Ongoing notification posted" }
        "call" -> { postCategory(Notification.CATEGORY_CALL, title, body); "CALL-category notification posted" }
        "alarm" -> { postCategory(Notification.CATEGORY_ALARM, title, body); "ALARM-category notification posted" }
        "cancel" -> { cancelTestNotifications(); "All test notifications cancelled; service kept alive" }
        "lan-restart" -> { restartLanServer(); "LAN server restarted" }
        else -> "Unknown command"
    }

    private fun setStatus(message: String) {
        NotifLabRuntime.lastStatus = message
    }

    private fun setTimedStatus(message: String) {
        NotifLabRuntime.timedStatus = message
    }

    private fun ensureLanServer() {
        if (lanServer != null) return
        startLanServer()
    }

    private fun restartLanServer() {
        stopLanServer()
        startLanServer()
    }

    private fun startLanServer() {
        try {
            val server = LanServer(PORT) { command -> handleLanCommand(command) }
            server.start()
            lanServer = server
            val addresses = localIpv4Addresses()
            NotifLabRuntime.lanAddresses = addresses
            NotifLabRuntime.lanStatus = if (addresses.isEmpty()) {
                "LAN server running on port $PORT, but no local IPv4 address was found. Connect to Wi‑Fi and use Restart LAN server."
            } else {
                "LAN control page:\n" + addresses.joinToString("\n") { "http://$it:$PORT/" }
            }
            updateServiceNotification()
        } catch (e: Exception) {
            NotifLabRuntime.lanAddresses = emptyList()
            NotifLabRuntime.lanStatus = "LAN server failed: ${e.message ?: e.javaClass.simpleName}"
        }
    }

    private fun stopLanServer() {
        lanServer?.stop()
        lanServer = null
        NotifLabRuntime.lanAddresses = emptyList()
        NotifLabRuntime.lanStatus = "LAN server: stopped"
    }

    private fun handleLanCommand(command: LanCommand): String {
        val title = command.params["title"]?.takeIf { it.isNotBlank() } ?: "NotifLab remote test"
        val body = command.params["text"]?.takeIf { it.isNotBlank() } ?: "Triggered from the LAN control page"
        val count = command.params["count"]?.toIntOrNull() ?: 10
        val interval = command.params["interval"]?.toLongOrNull() ?: 1000L
        return when (command.path) {
            "/notify" -> handleCommand("notify", title, body, count, interval)
            "/burst" -> handleCommand("burst", title, body, command.params["count"]?.toIntOrNull() ?: 5, command.params["interval"]?.toLongOrNull() ?: 300L)
            "/timed-start" -> handleCommand("timed-start", title, body, count, interval)
            "/timed-stop" -> handleCommand("timed-stop", title, body, count, interval)
            "/update" -> handleCommand("update", title, body, count, interval)
            "/once" -> handleCommand("once", title, body, count, interval)
            "/group" -> handleCommand("group", title, body, count, interval)
            "/ongoing" -> handleCommand("ongoing", title, body, count, interval)
            "/call" -> handleCommand("call", title, body, count, interval)
            "/alarm" -> handleCommand("alarm", title, body, count, interval)
            "/cancel" -> handleCommand("cancel", title, body, count, interval)
            else -> "Unknown command"
        }
    }

    private fun localIpv4Addresses(): List<String> = try {
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

    companion object {
        const val ACTION_START_SERVICE = "com.randotone.notiflab.action.START_SERVICE"
        const val ACTION_STOP_SERVICE = "com.randotone.notiflab.action.STOP_SERVICE"
        const val ACTION_COMMAND = "com.randotone.notiflab.action.COMMAND"
        const val EXTRA_COMMAND = "command"
        const val EXTRA_TITLE = "title"
        const val EXTRA_BODY = "body"
        const val EXTRA_COUNT = "count"
        const val EXTRA_INTERVAL = "interval"
        const val PORT = 8765

        private const val TEST_CHANNEL_ID = "notiflab_test_silent"
        private const val SERVICE_CHANNEL_ID = "notiflab_service"
        private const val SERVICE_NOTIFICATION_ID = 90
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
          <p>Remote notification firing range. v0.3 is hosted by a foreground service, so this page should stay alive after the phone UI is swiped away.</p>
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
            <button onclick="fire('/cancel')">Cancel test notifications</button>
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
