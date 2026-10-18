'use strict';
const $ = id => document.getElementById(id);
let token = '', session = crypto.randomUUID(), busy = false, controller = null;
let audio = null, audioURL = null, recording = null, turn = 0, core = null, playbackContext = null, audioFrame = null;
const history = [];
let ambient=null, micEpoch=0, voiceJob=0, voiceBusy=false, transcribingVoice=false, settleUntil=0, micStarting=false;
const activation=new VoiceActivation();
const theme = {primary_color:'#72d6fa',secondary_color:'#0c1732',accent_color:'#ad9cff',orbital_speed:.35,glow_intensity:1,core_pulse_speed:.45};
try { core = new AuroraCore3D('canvas-container'); core.setAudioAmplitude(0); core.setTheme(theme,'IDLE'); core.reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches; }
catch { document.querySelector('.orb-stage').classList.add('no-webgl'); }
$('reduced').checked = core ? core.reducedMotion : true;
function state(name, label) { if(name==='IDLE'&&ambient&&ambient.context.state==='running'&&!audio&&!voiceBusy)label=Date.now()<activation.until?'Te escucho · puedes continuar':'Atenta · di «Jessyca»'; $('status').textContent = label; if (core) core.setTheme(theme,name); $('status-dot').style.background = name === 'ERROR' ? '#eeaa92' : '#73d6fa'; }
function notice(message) { $('notice').textContent = message; $('notice').hidden = false; }
function failure(error) { if (error.name === 'AbortError') return; state('ERROR','Necesito tu atención'); notice(error.message || 'No se pudo completar la solicitud.'); }
function headers(extra = {}) { return {Authorization:`Bearer ${token}`, 'X-Session-ID':session, ...extra}; }
async function checked(response) { if(response.ok) return response; let detail; try { const body = await response.json(); detail = body.detail || body.error?.message; } catch {} throw new Error(detail || `No se pudo completar la solicitud (${response.status}).`); }
function connected() { if(token) return true; $('settings-dialog').showModal(); $('token').focus(); return false; }
function addMessage(role,text='') { const welcome = document.querySelector('.welcome'); if(welcome) welcome.remove(); const node=document.createElement('div'); node.className=`message ${role}`; const label=document.createElement('strong'); label.textContent=role==='user'?'Tú':'Jessyca'; const body=document.createElement('p'); body.textContent=text; node.append(label,body); $('messages').append(node); $('messages').scrollTop=$('messages').scrollHeight; return body; }
function activity(text, detail) { const empty=$('activity').querySelector('.empty'); if(empty) empty.remove(); const li=document.createElement('li'); li.textContent=text; const small=document.createElement('small'); small.textContent=detail; li.append(small); $('activity').prepend(li); while($('activity').children.length>10) $('activity').lastElementChild.remove(); }
function disposeAudio() { if(audio){activation.followUp();settleUntil=Date.now()+650;} if(audioFrame) cancelAnimationFrame(audioFrame); audioFrame=null; if(playbackContext) {playbackContext.close().catch(()=>{});playbackContext=null;} if(audio) { audio.pause(); audio.removeAttribute('src'); audio.load(); audio=null; } if(audioURL) { URL.revokeObjectURL(audioURL); audioURL=null; } if(core) core.setAudioAmplitude(0); }
async function readAloud(text, currentTurn) { if(!$('speak').checked || !text.trim()) return; state('THINKING','Preparando la voz…'); const response=await checked(await fetch('/studio/api/speech',{method:'POST',headers:headers({'Content-Type':'application/json'}),body:JSON.stringify({text:text.slice(0,4000)}),signal:controller.signal})); const blob=await response.blob(); if(currentTurn!==turn || !$('speak').checked) return; audioURL=URL.createObjectURL(blob); audio=new Audio(audioURL); playbackContext=new AudioContext(); const source=playbackContext.createMediaElementSource(audio), analyser=playbackContext.createAnalyser(); analyser.fftSize=256; source.connect(analyser);analyser.connect(playbackContext.destination);const values=new Uint8Array(analyser.fftSize); function animateAudio(){if(!audio)return;analyser.getByteTimeDomainData(values);let power=0;for(const value of values)power+=((value-128)/128)**2;if(core)core.setAudioAmplitude(Math.min(1,Math.sqrt(power/values.length)*4));audioFrame=requestAnimationFrame(animateAudio);}audio.onplay=()=>{state('SPEAKING','Hablando contigo');animateAudio();}; audio.onended=()=>{disposeAudio(); state('IDLE','Lista para escucharte');}; audio.onerror=()=>{disposeAudio(); failure(new Error('No se pudo reproducir la voz. Puedes leer la respuesta.'));}; await playbackContext.resume();await audio.play(); }
async function send(text, speak=true) { text=text.trim(); if(!text || busy || !connected()) return; disposeAudio(); const currentTurn=++turn; controller=new AbortController(); busy=true; $('send').disabled=true; $('notice').hidden=true; addMessage('user',text); $('message').value=''; const answer=addMessage('assistant','…'); state('THINKING','Procesando tu solicitud…'); let responseText='', done=false;
  try { const response=await checked(await fetch('/v1/chat/completions',{method:'POST',headers:headers({'Content-Type':'application/json'}),body:JSON.stringify({model:'jessyca',messages:[...history,{role:'user',content:text}],stream:true}),signal:controller.signal})); const reader=response.body.getReader(), decoder=new TextDecoder(); let buffer='';
    function line(value) { if(!value.startsWith('data:')) return; const data=value.slice(5).trim(); if(data==='[DONE]') {done=true; return;} const event=JSON.parse(data); if(event.error) throw new Error(event.error.message || 'La respuesta se interrumpió.'); const piece=event.choices?.[0]?.delta?.content || ''; responseText+=piece; answer.textContent=responseText || '…'; $('messages').scrollTop=$('messages').scrollHeight; }
    while(true) { const part=await reader.read(); if(part.done) break; buffer+=decoder.decode(part.value,{stream:true}); const lines=buffer.split('\n'); buffer=lines.pop(); for(const value of lines) line(value); } if(buffer.trim()) line(buffer); if(!done || !responseText.trim()) throw new Error('La respuesta quedó incompleta. Intenta otra vez.'); history.push({role:'user',content:text},{role:'assistant',content:responseText}); while(history.length>20) history.splice(0,2); activity(text,'Respuesta recibida · '+new Date().toLocaleTimeString('es-PE',{hour:'2-digit',minute:'2-digit'})); state('IDLE','Lista para escucharte'); if(speak && currentTurn===turn) await readAloud(responseText,currentTurn);
  } catch(error) { if(error.name==='AbortError') {answer.textContent=responseText || 'Solicitud interrumpida.';} else { answer.parentElement.classList.add('error'); answer.textContent=responseText?responseText+'\nLa respuesta no terminó.':error.message; failure(error); activity(text,'No se completó');} }
  finally { if(currentTurn===turn) {busy=false; $('send').disabled=false;} }
}
async function loadFiles() { const response=await checked(await fetch('/studio/api/files',{headers:headers()})); const data=await response.json(); $('file-count').textContent=data.available?`${data.count} videos en tu carpeta`:'No se encontró la carpeta de bailes.'; $('file-list').replaceChildren(); for(const name of data.files) {const li=document.createElement('li'); li.textContent=name; $('file-list').append(li);} }
$('connect').onclick=async()=>{ const candidate=$('token').value.trim(); if(!candidate) {$('settings-status').textContent='Introduce tu clave de conexión.'; return;} token=candidate; try { const response=await checked(await fetch('/studio/api/status',{headers:headers()})); const data=await response.json(); $('voice-engine').textContent=`${data.provider} · ${data.voice}`; $('connection').textContent='Conectada'; $('connection').classList.add('online'); $('token').value=''; $('settings-status').textContent=''; $('settings-dialog').close(); state('IDLE','Lista para escucharte'); await loadFiles(); } catch(error) {token=''; $('connection').textContent='Sin conectar'; $('connection').classList.remove('online'); $('settings-status').textContent=error.message;} };
$('settings').onclick=()=>$('settings-dialog').showModal();
$('reduced').onchange=()=>{if(core) core.reducedMotion=$('reduced').checked;};
$('speak').onchange=()=>{if(!$('speak').checked){disposeAudio(); state('IDLE','Voz desactivada');}};
$('chat-form').onsubmit=event=>{event.preventDefault(); send($('message').value).catch(failure);};
$('message').onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault(); $('chat-form').requestSubmit();}};
document.querySelectorAll('[data-prompt]').forEach(button=>button.onclick=()=>send(button.dataset.prompt).catch(failure));
document.querySelectorAll('[data-panel]').forEach(button=>button.onclick=()=>{document.querySelectorAll('.nav').forEach(item=>item.classList.remove('active')); button.classList.add('active'); $(button.dataset.panel).scrollIntoView({behavior:'smooth',block:'nearest'}); if(button.dataset.panel==='conversation') $('message').focus(); if(button.dataset.panel==='files'&&connected()) loadFiles().catch(failure);});
$('memory').onclick=()=>send('¿Qué recuerdas de mí?').catch(failure);
$('dance-folder').onclick=()=>send('Abre la carpeta D:\\bailes de ia').catch(failure);
$('clear').onclick=()=>{if(busy) return; disposeAudio(); session=crypto.randomUUID(); history.length=0; $('messages').replaceChildren(); addMessage('assistant','Empezamos una conversación nueva.'); state('IDLE','Lista para escucharte');};
function encodeWav(samples, inputRate) { const length=Math.floor(samples.length*16000/inputRate), buffer=new ArrayBuffer(44+length*2), view=new DataView(buffer); const string=(offset,value)=>{for(let i=0;i<value.length;i++)view.setUint8(offset+i,value.charCodeAt(i));}; string(0,'RIFF'); view.setUint32(4,36+length*2,true); string(8,'WAVE'); string(12,'fmt '); view.setUint32(16,16,true); view.setUint16(20,1,true); view.setUint16(22,1,true); view.setUint32(24,16000,true); view.setUint32(28,32000,true); view.setUint16(32,2,true); view.setUint16(34,16,true); string(36,'data'); view.setUint32(40,length*2,true); for(let i=0;i<length;i++){const pos=i*inputRate/16000, lo=Math.floor(pos), fraction=pos-lo, sample=samples[lo]*(1-fraction)+(samples[Math.min(lo+1,samples.length-1)]||0)*fraction; view.setInt16(44+i*2,Math.max(-1,Math.min(1,sample))*32767,true);} return buffer; }
async function endRecording(submit) { const rec=recording; if(!rec) return; recording=null; clearTimeout(rec.timer); rec.processor.disconnect(); rec.source.disconnect(); rec.stream.getTracks().forEach(track=>track.stop()); await rec.context.close(); $('talk').classList.remove('recording'); $('talk-hint').textContent='Hablar'; if(!submit) {state('IDLE','Grabación cancelada'); return;} let length=rec.chunks.reduce((sum,a)=>sum+a.length,0); if(length<rec.rate*.2){state('IDLE','No se capturó suficiente audio'); return;} const samples=new Float32Array(length); let offset=0; for(const chunk of rec.chunks){samples.set(chunk,offset);offset+=chunk.length;} state('TRANSCRIBING','Entendiendo tu voz…'); controller=new AbortController(); const response=await checked(await fetch('/studio/api/transcribe',{method:'POST',headers:headers({'Content-Type':'audio/wav'}),body:encodeWav(samples,rec.rate),signal:controller.signal})); const result=await response.json(); if(result.empty || !result.text.trim()){state('IDLE','No escuché una frase. Intenta de nuevo.');return;} if(result.confidence<.6){$('message').value=result.text;state('IDLE','Revisa lo que entendí antes de enviar.');return;} await send(result.text); }
$('talk').onclick=async()=>{try {if(recording){await endRecording(true);return;} if(busy || !connected())return; disposeAudio(); $('notice').hidden=true; const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true},video:false}); const context=new AudioContext(), source=context.createMediaStreamSource(stream), processor=context.createScriptProcessor(4096,1,1), gain=context.createGain(); gain.gain.value=0; const rec={stream,context,source,processor,chunks:[],rate:context.sampleRate,timer:null}; recording=rec; processor.onaudioprocess=event=>{if(recording!==rec)return;const input=event.inputBuffer.getChannelData(0);rec.chunks.push(new Float32Array(input));let power=0;for(const x of input)power+=x*x;if(core)core.setAudioAmplitude(Math.min(1,Math.sqrt(power/input.length)*8));}; source.connect(processor);processor.connect(gain);gain.connect(context.destination); rec.timer=setTimeout(()=>endRecording(true).catch(failure),20000); $('talk').classList.add('recording'); $('talk-hint').textContent='Terminar grabación';state('LISTENING','Te escucho · pulsa otra vez al terminar');}catch(error){failure(error);}};
$('stop').onclick=()=>{++turn; if(controller)controller.abort(); disposeAudio(); busy=false;$('send').disabled=false; if(recording)endRecording(false).catch(failure);state('IDLE','Interrumpida · puedes continuar');};
window.addEventListener('pagehide',()=>{if(controller)controller.abort();disposeAudio();if(recording){recording.stream.getTracks().forEach(track=>track.stop());recording.context.close();}});
async function pairDesktop(){const ticket=new URLSearchParams(location.hash.slice(1)).get('pair');if(!ticket)return;window.history.replaceState(null,'','/studio');try{const response=await checked(await fetch('/studio/api/pair',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket})}));const data=await response.json();$('token').value=data.token;await $('connect').onclick();}catch(error){failure(error);}}
function stopContinuous(){if(transcribingVoice&&controller){controller.abort();busy=false;$('send').disabled=false;}transcribingVoice=false;++micEpoch;++voiceJob;voiceBusy=false;micStarting=false;activation.reset();const rec=ambient;ambient=null;if(rec){rec.processor.disconnect();rec.source.disconnect();rec.stream.getTracks().forEach(track=>track.stop());rec.context.close().catch(()=>{});}if(core)core.setAudioAmplitude(0);$('talk').classList.remove('recording');$('talk').setAttribute('aria-pressed','false');$('talk-hint').textContent=$('continuous').checked?'Activar escucha':'Hablar';}
async function handleUtterance(samples,rate,epoch){
  const job=++voiceJob;voiceBusy=true;transcribingVoice=true;busy=true;$('send').disabled=true;controller=new AbortController();
  try{
    state('TRANSCRIBING','Entendiendo tu voz…');
    const response=await checked(await fetch('/studio/api/transcribe',{method:'POST',headers:headers({'Content-Type':'audio/wav'}),body:encodeWav(samples,rate),signal:controller.signal}));
    const result=await response.json();if(epoch!==micEpoch||job!==voiceJob)return;
    if(result.empty||result.confidence<.6)return;
    const text=activation.accept(result.text);if(text===null)return;
    if(/^(?:deja de escuchar|desactiva el micr[oó]fono|du[eé]rmete|terminar escucha)[.!?]*$/i.test(text)){stopContinuous();state('IDLE','Escucha desactivada');return;}
    if(!text)return;
    transcribingVoice=false;busy=false;await send(text);
  }catch(error){if(epoch===micEpoch)failure(error);}
  finally{if(job===voiceJob){transcribingVoice=false;voiceBusy=false;if(!audio){busy=false;$('send').disabled=false;if(ambient)state('IDLE','Atenta');}settleUntil=Date.now()+650;}}
}
async function startContinuous(){
  if(ambient||micStarting||!token||!$('continuous').checked)return;
  const epoch=++micEpoch;micStarting=true;let stream=null,context=null;
  try{
    stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
    if(epoch!==micEpoch){stream.getTracks().forEach(track=>track.stop());return;}
    context=new AudioContext();const source=context.createMediaStreamSource(stream),processor=context.createScriptProcessor(4096,1,1),gain=context.createGain();gain.gain.value=0;
    const rec={stream,context,source,processor,endpoint:new SpeechEndpoint(context.sampleRate)};ambient=rec;
    processor.onaudioprocess=event=>{
      if(ambient!==rec)return;
      if(busy||audio||voiceBusy||Date.now()<settleUntil){rec.endpoint.reset();return;}
      const input=event.inputBuffer.getChannelData(0),samples=rec.endpoint.push(input);
      if(core){let power=0;for(const value of input)power+=value*value;core.setAudioAmplitude(Math.min(1,Math.sqrt(power/input.length)*8));}
      $('talk').classList.toggle('recording',rec.endpoint.active);
      if(samples)handleUtterance(samples,context.sampleRate,epoch).catch(failure);
    };
    source.connect(processor);processor.connect(gain);gain.connect(context.destination);
    for(const track of stream.getTracks())track.onended=()=>{if(ambient===rec){stopContinuous();failure(new Error('Se desconectó el micrófono. Vuelve a activar la escucha.'));}};
    context.onstatechange=()=>{if(ambient===rec&&context.state==='running')state('IDLE','Atenta');};
    context.resume().catch(failure);$('talk').setAttribute('aria-pressed','true');$('talk-hint').textContent='Pausar escucha';
    state('IDLE',context.state==='running'?'Atenta':'Pulsa el micrófono una vez para activar la escucha');
  }catch(error){if(stream)stream.getTracks().forEach(track=>track.stop());if(context)context.close().catch(()=>{});if(epoch!==micEpoch)return;ambient=null;failure(new Error('Permite el micrófono y pulsa una vez para dejar a Jessyca atenta. '+error.message));}
  finally{if(epoch===micEpoch)micStarting=false;}
}
const manualTalk=$('talk').onclick, originalStop=$('stop').onclick, originalConnect=$('connect').onclick;
$('talk').onclick=async()=>{if(!$('continuous').checked)return manualTalk();if(!connected())return;if(ambient&&ambient.context.state==='suspended'){await ambient.context.resume();return;}if(ambient||micStarting){stopContinuous();state('IDLE','Escucha pausada');return;}await startContinuous();};
$('stop').onclick=()=>{stopContinuous();originalStop();state('IDLE','Escucha pausada · pulsa el micrófono para reactivar');};
$('continuous').onchange=async()=>{if($('continuous').checked){if(recording)await endRecording(false);await startContinuous();}else{stopContinuous();state('IDLE','Modo pulsar para hablar');}};
$('connect').onclick=async()=>{await originalConnect();if(token&&$('connection').classList.contains('online'))await startContinuous();};
window.addEventListener('pagehide',stopContinuous);
pairDesktop();






