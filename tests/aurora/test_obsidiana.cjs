// Run with: node --test tests/aurora/test_obsidiana.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
function setup(){
 const attrs={},events={},windowEvents={};let canceled=0,removed=false;
 const gradient={addColorStop(){}};
 const ctx=new Proxy({}, {get:(target,key)=>target[key] || (key.startsWith('create')?()=>gradient:()=>{}),set:(target,key,value)=>(target[key]=value,true)});
 const canvas={style:{},getContext:()=>ctx,setAttribute:(k,v)=>attrs[k]=v,remove:()=>removed=true};
 const container={appendChild(){},getBoundingClientRect:()=>({width:560,height:560})};
 const document={hidden:false,getElementById:()=>container,createElement:()=>canvas,addEventListener:(k,v)=>events[k]=v,removeEventListener:k=>delete events[k]};
 const window={devicePixelRatio:3,matchMedia:()=>({matches:false}),addEventListener:(k,v)=>windowEvents[k]=v,removeEventListener:k=>delete windowEvents[k]};
 const context=vm.createContext({document,window,performance:{now:()=>1000},requestAnimationFrame:()=>17,cancelAnimationFrame:()=>canceled++});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../../interfaces/aurora/static/js/aurora_core.js'),'utf8')+'\nglobalThis.Orb=AuroraCore3D;',context);
 return {orb:new context.Orb('orb'),attrs,document,events,canvas,get canceled(){return canceled},get removed(){return removed}};
}
test('real states map to distinct expressions; idle never implies completion',()=>{
 const {orb,attrs}=setup();
 for(const [state,expression] of Object.entries({IDLE:'IDLE',LISTENING:'LISTENING',TRANSCRIBING:'THINKING',EXECUTING:'THINKING',SPEAKING:'SPEAKING',RESPONDING:'SPEAKING',SEARCHING:'THINKING',COMPLETED:'SUCCESS',CLARIFYING:'CLARIFYING',CONFIRMING:'CLARIFYING',ERROR:'ERROR',UNKNOWN:'IDLE'})){
 orb.setTheme({},state);assert.equal(orb.expression,expression);orb.draw(1000);
 }
 orb.setTheme({},'IDLE');assert.match(attrs['aria-label'],/reposo/);assert.equal(orb.audioAmplitude,0);
});
test('audio input is bounded and invalid input cannot corrupt drawing',()=>{
 const {orb}=setup();
 for(const [input,expected] of [[2,1],[-1,0],[NaN,0],[Infinity,0],[.4,.4]]){orb.setAudioAmplitude(input);assert.equal(orb.audioAmplitude,expected);orb.draw(1000)}
 orb.setReducedMotion(true);orb.setTheme({},'SPEAKING');orb.draw(2000);assert.equal(orb.reducedMotion,true);
});
test('hidden tabs stop animation; dispose removes listeners and canvas',()=>{
 const result=setup();assert.equal(result.canvas.width,1120);
 result.document.hidden=true;result.events.visibilitychange();assert.equal(result.orb.frame,null);
 result.document.hidden=false;result.events.visibilitychange();assert.equal(result.orb.frame,17);
 result.orb.setQuality('low');assert.equal(result.canvas.width,560);
 result.orb.dispose();result.orb.dispose();assert.equal(result.removed,true);assert.deepEqual(Object.keys(result.events),[]);assert.ok(result.canceled>=2);
});
