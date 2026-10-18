'use strict';
// Local energy endpointing. Audio is sent to local Whisper only after speech,
// never on a timer during silence. This is not an acoustic wake-word model.
class SpeechEndpoint {
  constructor(rate) { this.rate=rate; this.noise=.002; this.reset(); }
  reset() { this.pre=[]; this.preLength=0; this.parts=[]; this.length=0; this.speech=0; this.silence=0; this.active=false; this.onset=0; }
  push(input) {
    const chunk=new Float32Array(input), ms=chunk.length/this.rate*1000;
    let power=0; for(const x of chunk) power+=x*x;
    const rms=Math.sqrt(power/chunk.length), voiced=rms>Math.max(.008,this.noise*3);
    if(!this.active) {
      this.pre.push(chunk);this.preLength+=chunk.length;
      while(this.pre.length>1 && this.preLength-this.pre[0].length>this.rate*.3) this.preLength-=this.pre.shift().length;
      if(!voiced) this.noise=Math.min(.02,this.noise*.98+rms*.02);
      this.onset=voiced?this.onset+ms:0;
      if(this.onset<100)return null;
      this.active=true;this.parts=this.pre;this.length=this.preLength;this.speech=this.onset;this.pre=[];this.preLength=0;
      return null;
    }
    this.parts.push(chunk);this.length+=chunk.length;
    if(voiced){this.speech+=ms;this.silence=0;}else this.silence+=ms;
    if(this.silence<900 && this.length<this.rate*20)return null;
    const enough=this.speech>=180, samples=enough?new Float32Array(this.length):null;
    if(samples){let offset=0;for(const part of this.parts){samples.set(part,offset);offset+=part.length;}}
    this.reset();return samples;
  }
}
class VoiceActivation {
  constructor(){this.until=0;}
  reset(){this.until=0;}
  followUp(now=Date.now()){if(this.until>0)this.until=now+45000;}
  accept(text,now=Date.now()) {
    const wake=/^[\s¡¿"“]*(?:(?:oye|hola|hey)[,\s]+)?jess(?:y|i)ca\b[,\s.!?]*/i;
    const named=wake.test(text);
    if(!named && now>this.until)return null;
    this.until=now+45000;
    return named?text.replace(wake,'').trim():text.trim();
  }
}
if(typeof module!=='undefined')module.exports={SpeechEndpoint,VoiceActivation};
else {window.SpeechEndpoint=SpeechEndpoint;window.VoiceActivation=VoiceActivation;}

