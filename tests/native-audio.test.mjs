import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../web/js/native-system-audio.js', import.meta.url), 'utf8');
const {NativeSystemAudio} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
class Socket {
    static instances = [];
    constructor(url) {this.url = url; this.handlers = {}; Socket.instances.push(this);}
    addEventListener(type, action) {this.handlers[type] = action;}
    emit(data) {this.handlers.message({data: typeof data === 'object' && !(data instanceof ArrayBuffer) ? JSON.stringify(data) : data});}
    close() {if (!this.closed) {this.closed = true; this.handlers.close?.();}}
}
function client() {
    const samples = [];
    const statuses = [];
    const audio = new NativeSystemAudio(value => samples.push(value), value => statuses.push(value), {WebSocketType: Socket, baseURL: 'http://127.0.0.1:8765/'});
    const start = audio.start();
    return {audio, samples, statuses, start, socket: Socket.instances.at(-1)};
}
const ready = {type: 'ready', sample_rate: 48000, channels: 1};

test('native playback uses the current backend port and decodes little-endian 48 kHz PCM', async () => {
    const state = client();
    assert.equal(state.socket.url, 'ws://127.0.0.1:8765/ws/system-audio');
    state.socket.emit(ready);
    await state.start;
    const bytes = new ArrayBuffer(6);
    const data = new DataView(bytes);
    [-32768, 0, 32767].forEach((value, index) => data.setInt16(index * 2, value, true));
    state.socket.emit(bytes);
    assert.deepEqual([...state.samples[0]], [-1, 0, 32767 / 32768]);
    assert.equal(state.audio.isLive, true);
    state.audio.stop();
    assert.equal(state.audio.isLive, false);
    assert.equal(state.socket.closed, true);
});

test('capture permission errors are shown and never become a silent mic-only success', async () => {
    const state = client();
    const failed = assert.rejects(state.start, /Allow Aura/);
    state.socket.emit({type: 'error', message: 'Allow Aura capture permission'});
    await failed;
    assert.equal(state.audio.isLive, false);
    assert.equal(state.statuses.at(-1).state, 'error');
    assert.equal(state.socket.closed, true);
});

test('ending while permission is pending cancels startup and ignores late audio', async () => {
    const state = client();
    const cancelled = assert.rejects(state.start, /cancelled/);
    state.audio.stop();
    await cancelled;
    state.socket.emit(ready);
    state.socket.emit(new ArrayBuffer(4));
    assert.equal(state.samples.length, 0);
    assert.equal(state.audio.isLive, false);
});

test('a capture disconnect clears the live status after startup', async () => {
    const state = client();
    state.socket.emit(ready);
    await state.start;
    state.socket.close();
    assert.equal(state.audio.isLive, false);
    assert.match(state.statuses.at(-1).message, /disconnected/);
});

async function processor() {
    let Instance;
    const messages = [];
    const context = {
        AudioWorkletProcessor: class {constructor() {this.port = {postMessage: message => messages.push(message)};}},
        registerProcessor: (name, value) => {Instance = value;}, Float32Array, Int16Array, ArrayBuffer
    };
    vm.createContext(context);
    vm.runInContext(await readFile(new URL('../web/js/audio_processor.js', import.meta.url), 'utf8'), context);
    return {instance: new Instance(), messages};
}

test('native playback mixes with the mic in time and never feeds the speaker output', async () => {
    const {instance, messages} = await processor();
    instance.port.onmessage({data: {type: 'native-system-audio', samples: new Float32Array(1024).fill(0.5)}});
    const output = new Float32Array(128);
    for (let index = 0; index < 8; index++) instance.process([[new Float32Array(128)]], [[output]]);
    assert.equal(messages.length, 1);
    assert.equal(messages[0].audioData.byteLength, 2048);
    assert.equal(messages[0].systemLevel, 0.5);
    assert.equal(messages[0].micLevel, 0);
    assert.equal(new Int16Array(messages[0].audioData)[0], 11468);
    assert(output.every(sample => sample === 0));
    for (let index = 0; index < 8; index++) instance.process([], [[output]]);
    assert.equal(messages.at(-1).systemLevel, 0);
});

test('native audio queue keeps the latest half second instead of growing without limit', async () => {
    const {instance, messages} = await processor();
    const samples = new Float32Array(30000).fill(0.5);
    samples.fill(0, 0, 6000);
    instance.port.onmessage({data: {type: 'native-system-audio', samples}});
    assert.equal(instance.nativeCount, 24000);
    for (let index = 0; index < 8; index++) instance.process([], []);
    assert.equal(messages[0].systemLevel, 0.5);
});
