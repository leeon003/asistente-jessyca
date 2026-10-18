const {test}=require('node:test');
const assert=require('node:assert/strict');
const {SpeechEndpoint,VoiceActivation}=require('../../interfaces/webui_bridge/studio_static/continuous_voice.js');
function feed(detector,amplitude,ms){const results=[];for(let i=0;i<ms/20;i++){const result=detector.push(new Float32Array(320).fill(amplitude));if(result)results.push(result);}return results;}
test('silence never submits a transcription',()=>{assert.equal(feed(new SpeechEndpoint(16000),0,60000).length,0);});
test('speech ends automatically and preserves pre-roll',()=>{const d=new SpeechEndpoint(16000);feed(d,0,500);feed(d,.06,600);const results=feed(d,0,1200);assert.equal(results.length,1);assert.ok(results[0].length>=16000*1.5);});
test('two turns need no microphone restart',()=>{const d=new SpeechEndpoint(16000);for(let i=0;i<2;i++){feed(d,.06,500);assert.equal(feed(d,0,1200).length,1);}});
test('brief click does not become a command',()=>{const d=new SpeechEndpoint(16000);feed(d,.2,80);assert.equal(feed(d,0,2000).length,0);});
test('short spoken confirmation is retained',()=>{const d=new SpeechEndpoint(16000);feed(d,.06,200);assert.equal(feed(d,0,1200).length,1);});
test('long utterance is bounded',()=>{const d=new SpeechEndpoint(16000);const results=feed(d,.08,21000);assert.equal(results.length,1);assert.ok(results[0].length<=16000*20.02);});
test('reset discards partial echo and old utterance',()=>{const d=new SpeechEndpoint(16000);feed(d,.06,500);d.reset();assert.equal(feed(d,0,1500).length,0);});
test('activation ignores background speech and accepts named request',()=>{const a=new VoiceActivation();assert.equal(a.accept('reproduce un video',100000),null);assert.equal(a.accept('Jessica, báilame.',100000),'báilame.');assert.equal(a.accept('ahora otro',101000),'ahora otro');assert.equal(a.accept('ruido de televisión',150000),null);});
test('activation alone opens follow-up; stopping closes it',()=>{const a=new VoiceActivation();assert.equal(a.accept('Jessyca.',100000),'');assert.equal(a.accept('hola',101000),'hola');a.reset();assert.equal(a.accept('hola',102000),null);});
test('Spanish punctuation from actual STT does not block activation',()=>{for(const text of ['¿Hola, Jessica? ¿Cuál es el estado?', '¡Jessyca! ¿Cuál es el estado?', 'Oye, Jessica, ¿Cuál es el estado?']){assert.match(new VoiceActivation().accept(text,100000),/Cuál es el estado/);}});
test('long assistant speech does not consume the follow-up window',()=>{const a=new VoiceActivation();a.followUp(100000);assert.equal(a.accept('ruido',101000),null);a.accept('Jessyca, explícame esto',110000);a.followUp(180000);assert.equal(a.accept('¿y después?',181000),'¿y después?');a.reset();a.followUp(200000);assert.equal(a.accept('ruido',201000),null);});
