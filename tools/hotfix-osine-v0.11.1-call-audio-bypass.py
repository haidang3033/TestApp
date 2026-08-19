#!/usr/bin/env python3
from pathlib import Path
import re, sys

if len(sys.argv) != 2:
    raise SystemExit('usage: hotfix-osine-v0.11.1-call-audio-bypass.py <project-dir>')

project = Path(sys.argv[1]).resolve()
app = project / 'app'
kt = app / 'src' / 'main' / 'java' / 'com' / 'randotone' / 'app'

# v0.11.1: keep the v0.11 call lifecycle, but route osine's replacement audio as
# ordinary notification audio. HINT_HOST_DISABLE_CALL_EFFECTS suppresses phone-call
# sounds on the tested Xiaomi device, and v0.11 labelled its own replacement as
# USAGE_NOTIFICATION_RINGTONE, putting it in the suppressed class too.
p = app / 'build.gradle.kts'
t = p.read_text(encoding='utf-8')
t = re.sub(r'versionCode\s*=\s*\d+', 'versionCode = 12', t)
t = re.sub(r'versionName\s*=\s*"[^"]+"', 'versionName = "0.11.1"', t)
p.write_text(t, encoding='utf-8')

p = kt / 'OsineCallEngine.kt'
t = p.read_text(encoding='utf-8')

if 'import android.media.AudioManager\n' not in t:
    marker = 'import android.media.AudioAttributes\n'
    if marker not in t:
        raise SystemExit('AudioAttributes import marker missing')
    t = t.replace(marker, marker + 'import android.media.AudioManager\n', 1)

old_usage = 'setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)'
if old_usage not in t:
    raise SystemExit('v0.11 ringtone usage marker missing')
t = t.replace(old_usage, 'setUsage(AudioAttributes.USAGE_NOTIFICATION)', 1)

old_started = 'looping=true usage=ringtone'
if old_started not in t:
    raise SystemExit('v0.11 started-log marker missing')
t = t.replace(old_started, 'looping=true usage=notification-bypass', 1)

selected_marker = 'OsineLog.event(c,"CALL_AUDIO","selected key=${n.key} package=${n.packageName} pool=${p.name} sound=${s.name} mode=${p.mode}");try{val mp='
if selected_marker not in t:
    raise SystemExit('v0.11 selected marker missing')
route_log = 'OsineLog.event(c,"CALL_AUDIO","selected key=${n.key} package=${n.packageName} pool=${p.name} sound=${s.name} mode=${p.mode}");OsineLog.event(c,"CALL_AUDIO","route key=${n.key} usage=notification-bypass suppressionRequested=${OsineRingtoneLab.isSuppressionRequested(c)} effectiveHints=${OsineRingtoneLab.lastEffectiveHints(c)} ${volumeSnapshot(c)}");try{val mp='
t = t.replace(selected_marker, route_log, 1)

helper_marker = ' private fun callType(n:Notification)='
if helper_marker not in t:
    raise SystemExit('callType helper marker missing')
helper = ''' private fun volumeSnapshot(c:Context):String=runCatching{val a=c.applicationContext.getSystemService(Context.AUDIO_SERVICE) as AudioManager;"ring=${a.getStreamVolume(AudioManager.STREAM_RING)}/${a.getStreamMaxVolume(AudioManager.STREAM_RING)} notif=${a.getStreamVolume(AudioManager.STREAM_NOTIFICATION)}/${a.getStreamMaxVolume(AudioManager.STREAM_NOTIFICATION)} music=${a.getStreamVolume(AudioManager.STREAM_MUSIC)}/${a.getStreamMaxVolume(AudioManager.STREAM_MUSIC)} mode=${a.ringerMode}"}.getOrElse{"volume=unavailable:${it.javaClass.simpleName}"}\n'''
t = t.replace(helper_marker, helper + helper_marker, 1)

p.write_text(t, encoding='utf-8')
print('Applied osine v0.11.1 call audio bypass hotfix')
