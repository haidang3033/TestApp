#!/usr/bin/env python3
from pathlib import Path
import re, sys
if len(sys.argv)!=2: raise SystemExit('usage: patch-osine-v0.11.py <project-dir>')
project=Path(sys.argv[1]).resolve(); app=project/'app'; kt=app/'src'/'main'/'java'/'com'/'randotone'/'app'

p=app/'build.gradle.kts'; t=p.read_text(); t=re.sub(r'versionCode\s*=\s*\d+','versionCode = 11',t); t=re.sub(r'versionName\s*=\s*"[^"]+"','versionName = "0.11.0"',t); p.write_text(t)

(kt/'OsineCallSettings.kt').write_text(r'''package com.randotone.app
import android.content.Context
object OsineCallSettings {
 private const val P="osine_call_roulette"; private const val E="enabled"; private const val I="pool_id"
 fun isEnabled(c:Context)=c.applicationContext.getSharedPreferences(P,0).getBoolean(E,false)
 fun setEnabled(c:Context,v:Boolean){val a=c.applicationContext;a.getSharedPreferences(P,0).edit().putBoolean(E,v).commit();OsineLog.event(a,"CALL_CFG","roulette-enabled=$v");if(!v)OsineCallEngine.stopAll(a,"call-roulette-disabled")}
 fun poolId(c:Context,pools:List<SoundPool>,fallback:String?):String?{if(pools.isEmpty())return null;val s=c.applicationContext.getSharedPreferences(P,0).getString(I,null);return pools.firstOrNull{it.id==s}?.id?:pools.firstOrNull{it.id==fallback}?.id?:pools.first().id}
 fun setPoolId(c:Context,id:String){val a=c.applicationContext;a.getSharedPreferences(P,0).edit().putString(I,id).commit();OsineLog.event(a,"CALL_CFG","pool-id=$id")}
}
''')

(kt/'OsineCallEngine.kt').write_text(r'''package com.randotone.app
import android.app.Notification
import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.net.Uri
import android.os.Build
import android.os.SystemClock
import android.service.notification.StatusBarNotification
object OsineCallEngine {
 private val lock=Any(); private var player:MediaPlayer?=null; private var gen=0L; private var key:String?=null; private var pkg:String?=null; private var pool:String?=null; private var sound:String?=null; private val seen=LinkedHashMap<String,Long>()
 fun posted(s:RandoToneNotificationListener,n:StatusBarNotification){if(n.notification.category!=Notification.CATEGORY_CALL)return;val ct=callType(n.notification);val fresh=synchronized(lock){val x=!seen.containsKey(n.key);if(x)seen[n.key]=SystemClock.elapsedRealtime();x};OsineLog.event(s,if(fresh)"CALL_POST" else "CALL_UPDATE","key=${n.key} package=${n.packageName} id=${n.id} callType=${ctName(ct)} fullScreen=${n.notification.fullScreenIntent!=null} flags=${n.notification.flags}");if(ct==2||ct==3){stopKey(s,n.key,"call-type-${ctName(ct)}");return};if(ct!=0&&ct!=1)return;if(!OsineCallSettings.isEnabled(s)){OsineLog.event(s,"CALL_AUDIO","not-started key=${n.key} reason=call-roulette-disabled");return};synchronized(lock){if(key==n.key){OsineLog.event(s,"CALL_AUDIO","keep-existing key=${n.key} reason=notification-update");return}};val r=RandoToneRepository(s.applicationContext);val ps=r.loadPools();val id=OsineCallSettings.poolId(s,ps,r.getDefaultPoolId(ps));val picked=id?.let{r.chooseSound(it)};if(picked==null){OsineLog.event(s,"CALL_AUDIO","not-started key=${n.key} package=${n.packageName} reason=no-enabled-call-sound poolId=${id?:"null"}");return};start(s,n,picked.first,picked.second)}
 fun removed(c:Context,n:StatusBarNotification,reason:Int){val st=synchronized(lock){seen.remove(n.key)};if(st!=null)OsineLog.event(c,"CALL_REMOVE","key=${n.key} package=${n.packageName} id=${n.id} reason=$reason lifetimeMs=${(SystemClock.elapsedRealtime()-st).coerceAtLeast(0)}");stopKey(c,n.key,"notification-removed-$reason")}
 fun stopAll(c:Context,why:String){var op:MediaPlayer?=null;var ok:String?=null;var pp:String?=null;var pl:String?=null;var ss:String?=null;synchronized(lock){gen++;op=player;ok=key;pp=pkg;pl=pool;ss=sound;player=null;key=null;pkg=null;pool=null;sound=null;seen.clear()};runCatching{op?.stop()};runCatching{op?.release()};if(ok!=null||op!=null)OsineLog.event(c,"CALL_AUDIO","stopped key=${ok?:"null"} package=${pp?:"null"} pool=${pl?:"null"} sound=${ss?:"null"} reason=$why")}
 private fun stopKey(c:Context,k:String,why:String){var op:MediaPlayer?=null;var pp:String?=null;var pl:String?=null;var ss:String?=null;synchronized(lock){if(key!=k)return;gen++;op=player;pp=pkg;pl=pool;ss=sound;player=null;key=null;pkg=null;pool=null;sound=null};runCatching{op?.stop()};runCatching{op?.release()};OsineLog.event(c,"CALL_AUDIO","stopped key=$k package=${pp?:"null"} pool=${pl?:"null"} sound=${ss?:"null"} reason=$why")}
 private fun start(c:Context,n:StatusBarNotification,p:SoundPool,s:SoundItem){var old:MediaPlayer?=null;var token=0L;synchronized(lock){gen++;token=gen;old=player;player=null;key=n.key;pkg=n.packageName;pool=p.name;sound=s.name};runCatching{old?.stop()};runCatching{old?.release()};OsineLog.event(c,"CALL_AUDIO","selected key=${n.key} package=${n.packageName} pool=${p.name} sound=${s.name} mode=${p.mode}");try{val mp=MediaPlayer().apply{setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());isLooping=true;setDataSource(c.applicationContext,Uri.parse(s.uri));setOnPreparedListener{x->val go=synchronized(lock){gen==token&&key==n.key&&player===x};if(!go){x.release();return@setOnPreparedListener};runCatching{x.start()}.onSuccess{OsineLog.event(c,"CALL_AUDIO","started key=${n.key} package=${n.packageName} pool=${p.name} sound=${s.name} looping=true usage=ringtone")}.onFailure{OsineLog.event(c,"CALL_AUDIO","start-failed key=${n.key}",it);stopKey(c,n.key,"start-failed")}};setOnErrorListener{x,w,e->val cur=synchronized(lock){player===x&&key==n.key};OsineLog.event(c,"CALL_AUDIO","player-error key=${n.key} what=$w extra=$e current=$cur");if(cur)stopKey(c,n.key,"media-error-$w-$e")else runCatching{x.release()};true};prepareAsync()};val keep=synchronized(lock){if(gen==token&&key==n.key){player=mp;true}else false};if(!keep)mp.release()}catch(e:Exception){OsineLog.event(c,"CALL_AUDIO","prepare-failed key=${n.key} package=${n.packageName} pool=${p.name} sound=${s.name}",e);stopKey(c,n.key,"prepare-failed")}}
 private fun callType(n:Notification)=if(Build.VERSION.SDK_INT>=34)n.extras.getInt(Notification.EXTRA_CALL_TYPE,Notification.CallStyle.CALL_TYPE_UNKNOWN)else 0
 private fun ctName(v:Int)=when(v){1->"incoming";2->"ongoing";3->"screening";else->"unknown"}
}
''')

p=kt/'RandoToneNotificationListener.kt'; t=p.read_text()
old='        OsineRingtoneLab.recordCallNotification(this, sbn)\n        if (shouldHardIgnore(sbn)) return\n'
new='        OsineRingtoneLab.recordCallNotification(this, sbn)\n        if (sbn.notification.category == Notification.CATEGORY_CALL) OsineCallEngine.posted(this, sbn)\n        if (shouldHardIgnore(sbn)) return\n'
if old not in t: raise SystemExit('listener call marker missing')
t=t.replace(old,new,1)
if 'override fun onNotificationRemoved(' not in t:
 m='    override fun onListenerHintsChanged(hints: Int) {'
 if m not in t: raise SystemExit('listener hints marker missing')
 t=t.replace(m,'    override fun onNotificationRemoved(sbn: StatusBarNotification, rankingMap: RankingMap, reason: Int) {\n        OsineCallEngine.removed(applicationContext, sbn, reason)\n        super.onNotificationRemoved(sbn, rankingMap, reason)\n    }\n\n'+m,1)
if '"listener-disconnected")' not in t:
 m='        OsineRingtoneLab.onListenerDisconnected(this)\n'
 if m not in t: raise SystemExit('disconnect marker missing')
 t=t.replace(m,m+'        OsineCallEngine.stopAll(applicationContext, "listener-disconnected")\n',1)
if '"listener-destroy")' not in t:
 m='    override fun onDestroy() {\n'
 if m not in t: raise SystemExit('destroy marker missing')
 t=t.replace(m,m+'        OsineCallEngine.stopAll(applicationContext, "listener-destroy")\n',1)
p.write_text(t)

p=kt/'OsineRingtoneLab.kt';t=p.read_text();m='    fun clearBeforeOperationStop(context: Context) {\n'
if 'OsineCallEngine.stopAll(context, "operation-stop")' not in t:
 if m not in t: raise SystemExit('operation stop marker missing')
 t=t.replace(m,m+'        OsineCallEngine.stopAll(context, "operation-stop")\n',1)
p.write_text(t)

p=kt/'MainActivity.kt';t=p.read_text()
if 'import androidx.compose.foundation.layout.width\n' not in t:
 a='import androidx.compose.foundation.layout.fillMaxWidth\n'
 if a not in t: raise SystemExit('width import anchor missing')
 t=t.replace(a,a+'import androidx.compose.foundation.layout.width\n',1)
t=t.replace('"v0.10 prototype • sections + ringtone lab"','"v0.11 prototype • call roulette + retractable sections"',1)
m='    var callSuppressionRequested by remember { mutableStateOf(OsineRingtoneLab.isSuppressionRequested(context)) }\n    var ringtoneLabRevision by remember { mutableStateOf(0) }\n'
r='    var callSuppressionRequested by remember { mutableStateOf(OsineRingtoneLab.isSuppressionRequested(context)) }\n    var callRouletteEnabled by remember { mutableStateOf(OsineCallSettings.isEnabled(context)) }\n    var callPoolId by remember { mutableStateOf(OsineCallSettings.poolId(context, state.pools, state.defaultPoolId)) }\n    var navigationExpanded by remember { mutableStateOf(false) }\n    var ringtoneLabRevision by remember { mutableStateOf(0) }\n'
if m not in t: raise SystemExit('state marker missing')
t=t.replace(m,r,1)
m='        OsineSectionRail(\n            selected = selectedSection,\n            onSelect = { selectedSection = it }\n        )\n';r='        OsineSectionRail(\n            selected = selectedSection,\n            expanded = navigationExpanded,\n            onToggle = { navigationExpanded = !navigationExpanded },\n            onSelect = { selectedSection = it }\n        )\n'
if m not in t: raise SystemExit('rail call marker missing')
t=t.replace(m,r,1)
m='                    RingtoneLabCard(\n                        requested = callSuppressionRequested,\n';r='                    CallRouletteCard(callRouletteEnabled, state.pools, callPoolId, { v -> callRouletteEnabled=v; OsineCallSettings.setEnabled(context,v) }, { id -> callPoolId=id; OsineCallSettings.setPoolId(context,id) })\n                    androidx.compose.foundation.layout.Spacer(modifier = Modifier.padding(4.dp))\n                    RingtoneLabCard(\n                        requested = callSuppressionRequested,\n'
if m not in t: raise SystemExit('ring card marker missing')
t=t.replace(m,r,1)
pat=re.compile(r'@Composable\nprivate fun OsineSectionRail\(selected: OsineSection, onSelect: \(OsineSection\) -> Unit\) \{.*?\n\}\n\n@Composable\nprivate fun DefaultBehaviorCard',re.S)
rep=r'''@Composable
private fun OsineSectionRail(selected: OsineSection, expanded: Boolean, onToggle: () -> Unit, onSelect: (OsineSection) -> Unit) {
    androidx.compose.material3.Surface(modifier = Modifier.fillMaxHeight().width(if (expanded) 168.dp else 56.dp), tonalElevation = 2.dp) {
        androidx.compose.foundation.layout.Column(modifier = Modifier.fillMaxHeight().padding(horizontal = 4.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            androidx.compose.material3.TextButton(onClick = onToggle, modifier = Modifier.fillMaxWidth()) { Text(if (expanded) "‹  osine" else "☰", fontWeight = FontWeight.Bold) }
            OsineSection.entries.forEach { s ->
                val label = if (expanded) "${s.glyph}  ${s.label}" else s.glyph
                if (selected == s) androidx.compose.material3.FilledTonalButton(onClick = { onSelect(s) }, modifier = Modifier.fillMaxWidth(), contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp, vertical = 8.dp)) { Text(label, fontWeight = FontWeight.Bold) }
                else androidx.compose.material3.TextButton(onClick = { onSelect(s) }, modifier = Modifier.fillMaxWidth(), contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 6.dp, vertical = 8.dp)) { Text(label) }
            }
        }
    }
}

@Composable
private fun DefaultBehaviorCard'''
t,n=pat.subn(rep,t,1)
if n!=1: raise SystemExit('rail function replacement failed')
mark='@Composable\nprivate fun RingtoneLabCard(\n'
ui=r'''@Composable
private fun CallRouletteCard(enabled:Boolean,pools:List<SoundPool>,selectedPoolId:String?,onEnabled:(Boolean)->Unit,onPool:(String)->Unit){
 androidx.compose.material3.Card(modifier=Modifier.fillMaxWidth()){
  androidx.compose.foundation.layout.Column(modifier=Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(10.dp)){
   Text("Call Roulette",style=MaterialTheme.typography.titleLarge,fontWeight=FontWeight.Bold)
   Text("Pick one sound for an incoming call, loop that same sound, then stop it when the call notification ends.")
   androidx.compose.foundation.layout.Row(modifier=Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically){androidx.compose.foundation.layout.Column(modifier=Modifier.weight(1f)){Text("Play osine ringtone",fontWeight=FontWeight.SemiBold);Text(if(enabled)"Enabled" else "Disabled",style=MaterialTheme.typography.bodySmall)};androidx.compose.material3.Switch(checked=enabled,onCheckedChange=onEnabled)}
   Text("Call pool",fontWeight=FontWeight.SemiBold)
   pools.forEach{p->androidx.compose.foundation.layout.Row(modifier=Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically){androidx.compose.material3.RadioButton(selected=selectedPoolId==p.id,onClick={onPool(p.id)});androidx.compose.foundation.layout.Column(modifier=Modifier.weight(1f)){Text(p.name);Text("${p.sounds.count{it.enabled}} enabled sound(s) • ${p.mode.label}",style=MaterialTheme.typography.bodySmall)}}}
   Text("v0.11 uses one global call pool. Keep source-call suppression enabled below to avoid hearing both ringtones.",style=MaterialTheme.typography.bodySmall)
  }
 }
}

'''
if mark not in t: raise SystemExit('ringtone card declaration missing')
t=t.replace(mark,ui+mark,1)
t=t.replace('Text("Prototype experiment: ask Android to suppress host call sounds while keeping notification sounds alone. osine does not play a replacement ringtone yet.")','Text("Ask Android to suppress host call sounds while keeping ordinary notification sounds alone. Pair this with Call Roulette above for replacement ringing.")',1)
p.write_text(t)
print('Patched osine v0.11 real Call Roulette + retractable navigation')
