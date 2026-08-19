#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch-osine-v0.12-ui-sounds.py <project-dir>")

project = Path(sys.argv[1]).resolve()
app = project / "app"
kt = app / "src" / "main" / "java" / "com" / "randotone" / "app"

def matching_brace(text: str, open_index: int) -> int:
    if text[open_index] != "{":
        raise ValueError("expected opening brace")
    depth = 0
    i = open_index
    state = "code"
    while i < len(text):
        c = text[i]
        n = text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if c == "/" and n == "/":
                state = "line"; i += 2; continue
            if c == "/" and n == "*":
                state = "block"; i += 2; continue
            if text.startswith('"""', i):
                state = "triple"; i += 3; continue
            if c == '"':
                state = "string"; i += 1; continue
            if c == "'":
                state = "char"; i += 1; continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
            continue
        if state == "line":
            if c == "\n":
                state = "code"
            i += 1
            continue
        if state == "block":
            if c == "*" and n == "/":
                state = "code"; i += 2; continue
            i += 1
            continue
        if state == "triple":
            if text.startswith('"""', i):
                state = "code"; i += 3; continue
            i += 1
            continue
        quote = '"' if state == "string" else "'"
        if c == "\\":
            i += 2
            continue
        if c == quote:
            state = "code"
        i += 1
    raise ValueError("unterminated block")

# v0.12 is intentionally a UI/data-model release. Keep the v0.11.1 call lifecycle
# and the v0.6 OFF invariant untouched.
build = app / "build.gradle.kts"
t = build.read_text(encoding="utf-8")
t = re.sub(r"versionCode\s*=\s*\d+", "versionCode = 13", t)
t = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.12.0"', t)
build.write_text(t, encoding="utf-8")

(kt / "OsineSoundProfiles.kt").write_text(r'''package com.randotone.app

import android.content.Context
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.util.Base64
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap

data class OsineSoundProfile(
    val displayName: String = "",
    val artworkUri: String = "",
    val volumePercent: Int = 100,
    val startMs: Long = 0L,
    val durationMs: Long = 0L
)

object OsineSoundProfiles {
    private const val PREFS = "osine_sound_profiles_v1"
    private val artworkCache = ConcurrentHashMap<String, Boolean>()

    private fun key(uri: String): String =
        Base64.encodeToString(uri.toByteArray(Charsets.UTF_8), Base64.NO_WRAP or Base64.URL_SAFE)

    fun get(context: Context, uri: String): OsineSoundProfile {
        val raw = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(key(uri), null) ?: return OsineSoundProfile()
        return runCatching {
            val j = JSONObject(raw)
            OsineSoundProfile(
                displayName = j.optString("displayName", ""),
                artworkUri = j.optString("artworkUri", ""),
                volumePercent = j.optInt("volumePercent", 100).coerceIn(0, 100),
                startMs = j.optLong("startMs", 0L).coerceAtLeast(0L),
                durationMs = j.optLong("durationMs", 0L).coerceAtLeast(0L)
            )
        }.getOrElse { OsineSoundProfile() }
    }

    fun save(context: Context, uri: String, profile: OsineSoundProfile) {
        val clean = profile.copy(
            displayName = profile.displayName.trim().take(120),
            artworkUri = profile.artworkUri.trim(),
            volumePercent = profile.volumePercent.coerceIn(0, 100),
            startMs = profile.startMs.coerceAtLeast(0L),
            durationMs = profile.durationMs.coerceAtLeast(0L)
        )
        val j = JSONObject()
            .put("displayName", clean.displayName)
            .put("artworkUri", clean.artworkUri)
            .put("volumePercent", clean.volumePercent)
            .put("startMs", clean.startMs)
            .put("durationMs", clean.durationMs)
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(key(uri), j.toString()).apply()
        OsineLog.event(
            context.applicationContext,
            "SOUND_PROFILE",
            "saved uriKey=${key(uri).take(12)} name=${clean.displayName.ifBlank { "<file-name>" }} volume=${clean.volumePercent} startMs=${clean.startMs} durationMs=${clean.durationMs} artwork=${clean.artworkUri.isNotBlank()}"
        )
    }

    fun reset(context: Context, uri: String) {
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().remove(key(uri)).apply()
        OsineLog.event(context.applicationContext, "SOUND_PROFILE", "reset uriKey=${key(uri).take(12)}")
    }

    fun resolvedName(context: Context, sound: SoundItem): String =
        get(context, sound.uri).displayName.ifBlank { sound.name }

    fun hasArtwork(context: Context, uri: String): Boolean {
        val profile = get(context, uri)
        if (profile.artworkUri.isNotBlank()) return true
        return artworkCache.getOrPut(uri) {
            runCatching {
                val retriever = MediaMetadataRetriever()
                try {
                    retriever.setDataSource(context.applicationContext, Uri.parse(uri))
                    retriever.embeddedPicture?.isNotEmpty() == true
                } finally {
                    retriever.release()
                }
            }.getOrDefault(false)
        }
    }
}
''', encoding="utf-8")

(kt / "OsineSoundPreview.kt").write_text(r'''package com.randotone.app

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.net.Uri
import android.os.Handler
import android.os.Looper

object OsineSoundPreview {
    private val lock = Any()
    private val handler = Handler(Looper.getMainLooper())
    private var player: MediaPlayer? = null
    private var generation = 0L

    fun play(context: Context, sound: SoundItem) {
        val app = context.applicationContext
        val profile = OsineSoundProfiles.get(app, sound.uri)
        stop(app, "new-preview")
        val token: Long
        synchronized(lock) {
            generation += 1
            token = generation
        }
        runCatching {
            val mp = MediaPlayer().apply {
                setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_NOTIFICATION)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build()
                )
                setDataSource(app, Uri.parse(sound.uri))
                setOnPreparedListener { ready ->
                    val current = synchronized(lock) { generation == token && player === ready }
                    if (!current) {
                        ready.release()
                        return@setOnPreparedListener
                    }
                    runCatching {
                        val gain = profile.volumePercent.coerceIn(0, 100) / 100f
                        ready.setVolume(gain, gain)
                        if (profile.startMs > 0L) {
                            ready.seekTo(profile.startMs.coerceAtMost(Int.MAX_VALUE.toLong()).toInt())
                        }
                        ready.start()
                        OsineLog.event(
                            app,
                            "SOUND_PREVIEW",
                            "started sound=${profile.displayName.ifBlank { sound.name }} volume=${profile.volumePercent} startMs=${profile.startMs} durationMs=${profile.durationMs}"
                        )
                        if (profile.durationMs > 0L) {
                            handler.postDelayed({
                                val stillCurrent = synchronized(lock) { generation == token && player === ready }
                                if (stillCurrent) stop(app, "profile-duration")
                            }, profile.durationMs)
                        }
                    }.onFailure {
                        OsineLog.event(app, "SOUND_PREVIEW", "start failed sound=${sound.name}", it)
                        stop(app, "start-failed")
                    }
                }
                setOnCompletionListener { stop(app, "completed") }
                setOnErrorListener { _, what, extra ->
                    OsineLog.event(app, "SOUND_PREVIEW", "player error what=$what extra=$extra sound=${sound.name}")
                    stop(app, "media-error")
                    true
                }
                prepareAsync()
            }
            synchronized(lock) {
                if (generation == token) player = mp else mp.release()
            }
        }.onFailure {
            OsineLog.event(app, "SOUND_PREVIEW", "prepare failed sound=${sound.name}", it)
            stop(app, "prepare-failed")
        }
    }

    fun stop(context: Context, reason: String = "manual") {
        var old: MediaPlayer? = null
        synchronized(lock) {
            generation += 1
            old = player
            player = null
        }
        handler.removeCallbacksAndMessages(null)
        runCatching { old?.stop() }
        runCatching { old?.release() }
        if (old != null) OsineLog.event(context.applicationContext, "SOUND_PREVIEW", "stopped reason=$reason")
    }
}
''', encoding="utf-8")

# Apply the safe parts of a sound profile to real call playback now:
# gain + initial start offset. The existing call loop lifecycle remains unchanged.
call_engine = kt / "OsineCallEngine.kt"
t = call_engine.read_text(encoding="utf-8")
if "val profile=OsineSoundProfiles.get(c,s.uri)" not in t:
    marker = "try{val mp=MediaPlayer().apply{"
    if marker not in t:
        raise SystemExit("OsineCallEngine MediaPlayer marker missing")
    t = t.replace(
        marker,
        'val profile=OsineSoundProfiles.get(c,s.uri);OsineLog.event(c,"CALL_AUDIO","profile key=${n.key} display=${profile.displayName.ifBlank{s.name}} volume=${profile.volumePercent} startMs=${profile.startMs} durationMs=${profile.durationMs}");' + marker,
        1,
    )
    start_marker = "runCatching{x.start()}"
    if start_marker not in t:
        raise SystemExit("OsineCallEngine start marker missing")
    t = t.replace(
        start_marker,
        "runCatching{val gain=profile.volumePercent.coerceIn(0,100)/100f;x.setVolume(gain,gain);if(profile.startMs>0L)x.seekTo(profile.startMs.coerceAtMost(Int.MAX_VALUE.toLong()).toInt());x.start()}",
        1,
    )
call_engine.write_text(t, encoding="utf-8")

activity = kt / "MainActivity.kt"
t = activity.read_text(encoding="utf-8")
t = t.replace(
    '"v0.11 prototype • call roulette + retractable sections"',
    '"v0.12 • reorganized UI + sound profiles"',
    1,
)

if "mutableStateOf(OsineSection.GENERAL)" in t:
    t = t.replace("mutableStateOf(OsineSection.GENERAL)", "mutableStateOf(OsineSection.HOME)", 1)

old_enum = '''private enum class OsineSection(val label: String, val glyph: String) {
    GENERAL("General", "G"),
    APPS("Apps", "A"),
    CALLS("Calls", "C")
}'''
new_enum = '''private enum class OsineSection(val label: String, val glyph: String) {
    HOME("Home", "H"),
    GENERAL("Notifications", "N"),
    SOUNDS("Sounds", "S"),
    APPS("Apps", "A"),
    CALLS("Calls", "C"),
    DIAGNOSTICS("Diagnostics", "D"),
    SETTINGS("Settings", "⚙")
}'''
if old_enum not in t:
    raise SystemExit("OsineSection enum marker missing")
t = t.replace(old_enum, new_enum, 1)

when_pos = t.find("when (selectedSection) {")
if when_pos < 0:
    raise SystemExit("selectedSection when block missing")
when_open = t.find("{", when_pos)
when_close = matching_brace(t, when_open)
when_body = t[when_open + 1:when_close]

if "OsineSection.HOME ->" not in when_body:
    general_pos = when_body.find("OsineSection.GENERAL ->")
    if general_pos < 0:
        raise SystemExit("GENERAL branch missing")
    home = r'''
            OsineSection.HOME -> {
                item {
                    OsineDashboardCard(
                        masterEnabled = OsineOperation.isEnabled(context),
                        defaultEnabled = defaultFallbackEnabled,
                        callEnabled = callRouletteEnabled,
                        callSuppression = callSuppressionRequested,
                        poolCount = state.pools.size,
                        observedCount = state.observedApps.size,
                        openNotifications = { selectedSection = OsineSection.GENERAL },
                        openSounds = { selectedSection = OsineSection.SOUNDS },
                        openApps = { selectedSection = OsineSection.APPS },
                        openCalls = { selectedSection = OsineSection.CALLS }
                    )
                }
            }
            '''
    when_body = when_body[:general_pos] + home + when_body[general_pos:]

if "OsineSection.SOUNDS ->" not in when_body:
    extras = r'''
            OsineSection.SOUNDS -> {
                item { OsineSoundsIntroCard(state.pools) }
                state.pools.forEach { pool ->
                    item {
                        Text(
                            pool.name,
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.padding(top = 8.dp, bottom = 2.dp)
                        )
                    }
                    pool.sounds.forEach { sound ->
                        item { OsineSoundProfileCard(context, pool, sound) }
                    }
                }
            }
            OsineSection.DIAGNOSTICS -> {
                item { OsineDiagnosticsHubCard(context) }
            }
            OsineSection.SETTINGS -> {
                item {
                    OsineSettingsHubCard(
                        context = context,
                        masterEnabled = OsineOperation.isEnabled(context)
                    )
                }
            }
'''
    when_body = when_body.rstrip() + "\n" + extras

t = t[:when_open + 1] + when_body + t[when_close:]

if "private fun OsineDashboardCard(" not in t:
    t += r'''

@Composable
private fun OsineDashboardCard(
    masterEnabled: Boolean,
    defaultEnabled: Boolean,
    callEnabled: Boolean,
    callSuppression: Boolean,
    poolCount: Int,
    observedCount: Int,
    openNotifications: () -> Unit,
    openSounds: () -> Unit,
    openApps: () -> Unit,
    openCalls: () -> Unit
) {
    androidx.compose.material3.Card(modifier = Modifier.fillMaxWidth()) {
        androidx.compose.foundation.layout.Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Text("osine", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text("one sound is not enough", style = MaterialTheme.typography.bodySmall)
            androidx.compose.material3.Divider()
            Text(if (masterEnabled) "Roulette is running" else "Roulette is OFF", fontWeight = FontWeight.Bold)
            Text(
                "Default notifications: ${if (defaultEnabled) "pool fallback" else "custom apps only"}  •  " +
                    "Calls: ${if (callEnabled) "roulette on" else "roulette off"}  •  " +
                    "Source-call suppression: ${if (callSuppression) "requested" else "off"}"
            )
            Text("$poolCount pool(s)  •  $observedCount observed app(s)")
            androidx.compose.foundation.layout.Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                androidx.compose.material3.Button(onClick = openNotifications, modifier = Modifier.weight(1f)) { Text("Notifications") }
                androidx.compose.material3.Button(onClick = openSounds, modifier = Modifier.weight(1f)) { Text("Sounds") }
            }
            androidx.compose.foundation.layout.Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                androidx.compose.material3.OutlinedButton(onClick = openApps, modifier = Modifier.weight(1f)) { Text("Apps") }
                androidx.compose.material3.OutlinedButton(onClick = openCalls, modifier = Modifier.weight(1f)) { Text("Calls") }
            }
        }
    }
}

@Composable
private fun OsineSoundsIntroCard(pools: List<SoundPool>) {
    val sounds = pools.sumOf { it.sounds.size }
    androidx.compose.material3.Card(modifier = Modifier.fillMaxWidth()) {
        androidx.compose.foundation.layout.Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Text("Sound library", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text("$sounds sound(s) across ${pools.size} pool(s). Profiles are stored inside osine; original audio files are never edited.")
            Text(
                "v0.12 profiles control the local display name, artwork attachment, preview volume, preview start point and preview duration. Call Roulette also uses the profile volume and initial start point.",
                style = MaterialTheme.typography.bodySmall
            )
        }
    }
}

@Composable
private fun OsineSoundProfileCard(context: android.content.Context, pool: SoundPool, sound: SoundItem) {
    var revision by remember { mutableStateOf(0) }
    val profile = remember(sound.uri, revision) { OsineSoundProfiles.get(context, sound.uri) }
    val display = profile.displayName.ifBlank { sound.name }
    val hasArtwork = remember(sound.uri, profile.artworkUri, revision) {
        OsineSoundProfiles.hasArtwork(context, sound.uri)
    }
    var editing by remember { mutableStateOf(false) }

    val artworkLauncher = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.OpenDocument()
    ) { uri ->
        if (uri != null) {
            runCatching {
                context.contentResolver.takePersistableUriPermission(
                    uri,
                    android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION
                )
            }
            OsineSoundProfiles.save(context, sound.uri, profile.copy(artworkUri = uri.toString()))
            revision++
        }
    }

    androidx.compose.material3.Card(modifier = Modifier.fillMaxWidth()) {
        androidx.compose.foundation.layout.Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(7.dp)
        ) {
            androidx.compose.foundation.layout.Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(if (hasArtwork) "▣" else "♪", style = MaterialTheme.typography.headlineSmall)
                androidx.compose.foundation.layout.Column(
                    modifier = Modifier.weight(1f).padding(start = 10.dp)
                ) {
                    Text(display, fontWeight = FontWeight.Bold)
                    Text(
                        "${pool.name}  •  ${profile.volumePercent}%  •  start ${profile.startMs} ms" +
                            if (profile.durationMs > 0) "  •  ${profile.durationMs} ms" else "  •  full duration",
                        style = MaterialTheme.typography.bodySmall
                    )
                    if (display != sound.name) Text("File: ${sound.name}", style = MaterialTheme.typography.bodySmall)
                }
            }
            androidx.compose.foundation.layout.Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                androidx.compose.material3.Button(
                    onClick = { OsineSoundPreview.play(context, sound) },
                    modifier = Modifier.weight(1f)
                ) { Text("Preview") }
                androidx.compose.material3.OutlinedButton(
                    onClick = { editing = true },
                    modifier = Modifier.weight(1f)
                ) { Text("Edit") }
            }
            androidx.compose.foundation.layout.Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                androidx.compose.material3.TextButton(
                    onClick = { artworkLauncher.launch(arrayOf("image/*")) },
                    modifier = Modifier.weight(1f)
                ) { Text(if (profile.artworkUri.isBlank()) "Set artwork" else "Change artwork") }
                androidx.compose.material3.TextButton(
                    onClick = {
                        OsineSoundPreview.stop(context, "profile-reset")
                        OsineSoundProfiles.reset(context, sound.uri)
                        revision++
                    },
                    modifier = Modifier.weight(1f)
                ) { Text("Reset profile") }
            }
        }
    }

    if (editing) {
        OsineSoundProfileDialog(
            initial = profile,
            fileName = sound.name,
            onDismiss = { editing = false },
            onSave = { updated ->
                OsineSoundProfiles.save(context, sound.uri, updated)
                revision++
                editing = false
            }
        )
    }
}

@Composable
private fun OsineSoundProfileDialog(
    initial: OsineSoundProfile,
    fileName: String,
    onDismiss: () -> Unit,
    onSave: (OsineSoundProfile) -> Unit
) {
    var name by remember(initial) { mutableStateOf(initial.displayName) }
    var volume by remember(initial) { mutableStateOf(initial.volumePercent.toString()) }
    var start by remember(initial) { mutableStateOf(initial.startMs.toString()) }
    var duration by remember(initial) { mutableStateOf(if (initial.durationMs > 0L) initial.durationMs.toString() else "") }

    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Sound profile") },
        text = {
            androidx.compose.foundation.layout.Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(fileName, style = MaterialTheme.typography.bodySmall)
                androidx.compose.material3.OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text("Local display name") },
                    placeholder = { Text(fileName) },
                    singleLine = true
                )
                androidx.compose.material3.OutlinedTextField(
                    value = volume,
                    onValueChange = { volume = it.filter { ch -> ch.isDigit() }.take(3) },
                    label = { Text("Volume % (0–100)") },
                    singleLine = true
                )
                androidx.compose.material3.OutlinedTextField(
                    value = start,
                    onValueChange = { start = it.filter { ch -> ch.isDigit() }.take(10) },
                    label = { Text("Start point (ms)") },
                    singleLine = true
                )
                androidx.compose.material3.OutlinedTextField(
                    value = duration,
                    onValueChange = { duration = it.filter { ch -> ch.isDigit() }.take(10) },
                    label = { Text("Play duration (ms, blank = full)") },
                    singleLine = true
                )
                Text(
                    "These values are a playback recipe. The original file is left untouched.",
                    style = MaterialTheme.typography.bodySmall
                )
            }
        },
        confirmButton = {
            androidx.compose.material3.Button(onClick = {
                onSave(
                    initial.copy(
                        displayName = name.trim(),
                        volumePercent = (volume.toIntOrNull() ?: 100).coerceIn(0, 100),
                        startMs = (start.toLongOrNull() ?: 0L).coerceAtLeast(0L),
                        durationMs = (duration.toLongOrNull() ?: 0L).coerceAtLeast(0L)
                    )
                )
            }) { Text("Save") }
        },
        dismissButton = {
            androidx.compose.material3.TextButton(onClick = onDismiss) { Text("Cancel") }
        }
    )
}

@Composable
private fun OsineDiagnosticsHubCard(context: android.content.Context) {
    var recent by remember { mutableStateOf("") }
    val exportLauncher = androidx.activity.compose.rememberLauncherForActivityResult(
        androidx.activity.result.contract.ActivityResultContracts.CreateDocument("text/plain")
    ) { uri ->
        if (uri != null) {
            val ok = OsineLog.export(context, uri)
            OsineLog.event(context.applicationContext, "ACTIVITY", "diagnostics export ui-overhaul success=$ok")
            recent = if (ok) "Diagnostics exported." else "Diagnostics export failed."
        }
    }

    androidx.compose.material3.Card(modifier = Modifier.fillMaxWidth()) {
        androidx.compose.foundation.layout.Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text("Diagnostics", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text("Listener health, call events and audio routing stay in persistent local logs.")
            androidx.compose.material3.Button(
                onClick = { recent = OsineLog.readRecent(context).takeLast(5000) },
                modifier = Modifier.fillMaxWidth()
            ) { Text("Show recent log") }
            androidx.compose.material3.OutlinedButton(
                onClick = { exportLauncher.launch(OsineLog.suggestedExportName()) },
                modifier = Modifier.fillMaxWidth()
            ) { Text("Export diagnostics…") }
            androidx.compose.material3.OutlinedButton(
                onClick = {
                    context.startActivity(android.content.Intent(android.provider.Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
                },
                modifier = Modifier.fillMaxWidth()
            ) { Text("Open notification access") }
            androidx.compose.material3.TextButton(
                onClick = {
                    OsineLog.clear(context)
                    OsineLog.startSession(context)
                    recent = "Diagnostics cleared; new session started."
                },
                modifier = Modifier.fillMaxWidth()
            ) { Text("Clear diagnostics") }
            if (recent.isNotBlank()) {
                Text(recent, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun OsineSettingsHubCard(context: android.content.Context, masterEnabled: Boolean) {
    androidx.compose.material3.Card(modifier = Modifier.fillMaxWidth()) {
        androidx.compose.foundation.layout.Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text("Settings", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text("Operation state: ${if (masterEnabled) "ON" else "OFF"}")
            Text(
                "Master OFF remains a hard boundary: no keep-alive recovery, no notification playback and no Call Roulette resurrection.",
                style = MaterialTheme.typography.bodySmall
            )
            androidx.compose.material3.OutlinedButton(
                onClick = {
                    context.startActivity(
                        android.content.Intent(
                            android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                            android.net.Uri.parse("package:${context.packageName}")
                        )
                    )
                },
                modifier = Modifier.fillMaxWidth()
            ) { Text("Open Android app settings") }
            androidx.compose.material3.OutlinedButton(
                onClick = {
                    runCatching {
                        context.startActivity(android.content.Intent(android.provider.Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
                    }
                },
                modifier = Modifier.fillMaxWidth()
            ) { Text("Open battery optimization settings") }
        }
    }
}
'''

activity.write_text(t, encoding="utf-8")
print("Patched osine v0.12 UI overhaul + non-destructive sound profiles")
