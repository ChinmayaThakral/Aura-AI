import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

test('48 kHz capture separates mic and tab audio and keeps the processor running', async()=>{
    const connections=[];
    const tracks=[];
    const makeTrack=kind=>{
        const track={kind,readyState:'live',enabled:true,muted:false,stop(){this.readyState='ended';}};
        tracks.push(track);
        return track;
    };
    const micTrack=makeTrack('audio');
    const systemTrack=makeTrack('audio');
    const videoTrack=makeTrack('video');
    const stream=(name,items)=>({name,getTracks:()=>items,getAudioTracks:()=>items.filter(track=>track.kind==='audio'),getVideoTracks:()=>items.filter(track=>track.kind==='video')});
    const mic=stream('microphone',[micTrack]);
    const system=stream('tab',[systemTrack,videoTrack]);
    const nodes=[];
    class AudioContext {
        constructor(options){assert.equal(options.sampleRate,48000);this.sampleRate=48000;this.state='running';this.destination={};this.audioWorklet={addModule:async()=>{}};}
        createMediaStreamSource(source){return {connect:(target,output,input)=>connections.push({source:source.name,target,output,input})};}
        createGain(){return {gain:{setTargetAtTime(){}},connect:(target,output,input)=>connections.push({source:'mic-gain',target,output,input})};}
        close(){this.state='closed';}
    }
    class Worklet {
        constructor(context,name,options){this.context=context;this.name=name;this.options=options;this.port={};nodes.push(this);}
        connect(target){this.destination=target;}
    }
    const muteManager={isAudioPaused:()=>false,isMicrophoneMuted:()=>true,on(){},setMicrophoneMute(){},setUniversalMute(){}};
    const original=await readFile(new URL('../web/js/audio_handler.js',import.meta.url),'utf8');
    const source=original.replace(/^import .*;\n/gm,'').replace(/export /g,'');
    const context={window:{AudioContext},navigator:{mediaDevices:{getUserMedia:async()=>mic,getDisplayMedia:async()=>system}},AudioWorkletNode:Worklet,muteManager,devLog(){},devError(){},console:{log(){},warn(){},error(){}},setTimeout:()=>0,clearTimeout(){}};
    vm.createContext(context);
    vm.runInContext(source,context);
    let delivered=0;
    assert.equal(await context.startAudioProcessing('example-mic',()=>delivered++),true);
    assert.equal(nodes[0].options.numberOfInputs,2);
    assert.equal(nodes[0].destination,nodes[0].context.destination);
    assert(connections.some(item=>item.source==='mic-gain'&&item.input===0));
    assert(connections.some(item=>item.source==='tab'&&item.input===1));
    nodes[0].port.onmessage({data:{audioData:new ArrayBuffer(8),micLevel:0,systemLevel:1}});
    assert.equal(delivered,1);
    assert.equal(context.isSystemAudioLive(),true);
    context.stopAudioProcessing();
    assert(tracks.every(track=>track.readyState==='ended'));
    assert.equal(context.isSystemAudioLive(),false);
});

test('desktop capture uses native playback without a Chrome picker and survives missing mic permission', async () => {
    const nodes = [];
    const clients = [];
    let forwarded = 0;
    let pickerCalls = 0;
    class AudioContext {
        constructor() {this.state='running';this.sampleRate=48000;this.destination={};this.audioWorklet={addModule:async()=>{}};}
        createGain() {return {gain:{setTargetAtTime(){}},connect(){}};}
        close() {this.state='closed';}
    }
    class Worklet {
        constructor() {this.port={postMessage: value => {this.native=value;}};nodes.push(this);}
        connect() {}
    }
    class NativeAudio {
        constructor(onSamples) {this.onSamples=onSamples;clients.push(this);}
        async start() {this.isLive=true;this.onSamples(new Float32Array([0.5]));}
        stop() {this.isLive=false;this.stopped=true;}
    }
    let paused = false;
    const muteManager={isAudioPaused:()=>paused,isMicrophoneMuted:()=>true,on(){},setMicrophoneMute(){},setUniversalMute(){}};
    const original=await readFile(new URL('../web/js/audio_handler.js',import.meta.url),'utf8');
    const source=original.replace(/^import .*;\n/gm,'').replace(/export /g,'');
    const context={window:{AudioContext,pywebview:{}},navigator:{mediaDevices:{getUserMedia:async()=>{throw new Error('Mic denied');},getDisplayMedia:async()=>{pickerCalls++;}}},NativeSystemAudio:NativeAudio,AudioWorkletNode:Worklet,muteManager,devLog(){},devError(){},console:{log(){},warn(){},error(){}},setTimeout:()=>0,clearTimeout(){}};
    vm.createContext(context);
    vm.runInContext(source,context);
    assert.equal(await context.startAudioProcessing('',()=>forwarded++),true);
    assert.equal(pickerCalls,0);
    assert.equal(context.isSystemAudioLive(),true);
    assert.equal(nodes[0].native.type,'native-system-audio');
    paused=true;
    nodes[0].port.onmessage({data:{audioData:new ArrayBuffer(8),micLevel:0,systemLevel:0.5}});
    assert.equal(forwarded,0);
    paused=false;
    nodes[0].port.onmessage({data:{audioData:new ArrayBuffer(8),micLevel:0,systemLevel:0.5}});
    assert.equal(forwarded,1);
    context.stopAudioProcessing();
    assert.equal(clients[0].stopped,true);
    assert.equal(context.isSystemAudioLive(),false);
});
