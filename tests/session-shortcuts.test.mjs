import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const load = async path => import('data:text/javascript;base64,' + Buffer.from(await readFile(new URL(path, import.meta.url), 'utf8')).toString('base64'));
const { createSessionShortcutHandler } = await load('../web/js/session-shortcuts.js');

test('session commands execute once, update state and acknowledge their own IDs', async () => {
    const names = ['toggle_mic_mute','toggle_universal_mute','switch_preset','toggle_vision_mode','switch_vision_model','capture_screenshot','process_screenshots','reset_screenshot_queue','reset_interview','end_interview','manual_question'];
    const calls = [];
    const replies = [];
    let changes = 0;
    const actions = Object.fromEntries(names.map(name => [name, payload => {calls.push([name,payload.preset_key]);return true;}]));
    const run = createSessionShortcutHandler(actions, value => replies.push(value), () => changes++);
    for (const name of names) {
        const command = {id:name,command:name,preset_key:'secondary',expires_at:Date.now()+10000};
        await run(command);
        await run(command);
    }
    assert.equal(calls.length,names.length);
    assert.equal(changes,names.length);
    assert.equal(replies.length,names.length);
    assert(replies.every(reply=>reply.success));
    assert.deepEqual(calls[2],['switch_preset','secondary']);
});

test('vision actions stay ordered while microphone controls remain responsive', async () => {
    let release;
    const wait = new Promise(resolve=>{release=resolve;});
    const order=[];
    const run = createSessionShortcutHandler({
        capture_screenshot:async()=>{order.push('capture');await wait;order.push('captured');},
        process_screenshots:()=>order.push('analyse'),
        toggle_mic_mute:()=>order.push('microphone'),
        toggle_vision_mode:()=>order.push('vision-mode')
    },()=>{});
    const capture=run({id:'capture',command:'capture_screenshot'});
    const analyse=run({id:'analyse',command:'process_screenshots'});
    await run({id:'mic',command:'toggle_mic_mute'});
    await run({id:'mode',command:'toggle_vision_mode'});
    assert(order.includes('microphone'));
    assert(order.includes('vision-mode'));
    assert(!order.includes('analyse'));
    release();
    await Promise.all([capture,analyse]);
    assert(order.indexOf('analyse') > order.indexOf('captured'));
});

test('expired, unknown and unavailable actions produce failures without false confirmation', async()=>{
    const replies=[];
    let calls=0;
    const run=createSessionShortcutHandler({toggle_mic_mute:()=>calls++,switch_vision_model:()=>false},reply=>replies.push(reply));
    await run({id:'expired',command:'toggle_mic_mute',expires_at:1});
    await run({id:'unknown',command:'execute_anything'});
    await run({id:'unavailable',command:'switch_vision_model'});
    assert.equal(calls,0);
    assert(replies.every(reply=>!reply.success));
    assert.match(replies[0].message,/expired/);
    assert.match(replies[2].message,/vision/);
});

test('desktop entry remains blocked until Chrome is ready and checks again on click', async()=>{
    const {setupDesktopSyncLink}=await load('../web/js/onboarding.js');
    const originalWindow=globalThis.window;
    const originalInterval=globalThis.setInterval;
    let poll;
    globalThis.window={location:{href:'unchanged'},addEventListener(){}};
    globalThis.setInterval=fn=>{poll=fn;return 1;};
    try {
        const button={disabled:true,addEventListener(type,fn){this.click=fn;}};
        const status={};
        const shortcutStatus={};
        let ready=false;
        const doc={getElementById:id=>({'show-chrome-session':button,'chrome-readiness':status,'shortcut-readiness':shortcutStatus}[id])};
        setupDesktopSyncLink(doc,async()=>({ok:true,json:async()=>({ready,message:ready?'Ready':'Start Chrome first',shortcuts_ready:true})}));
        await new Promise(resolve=>setImmediate(resolve));
        assert.equal(button.disabled,true);
        ready=true;
        await poll();
        assert.equal(button.disabled,false);
        ready=false;
        await button.click();
        assert.equal(window.location.href,'unchanged');
        ready=true;
        await button.click();
        assert.equal(window.location.href,'/static/desktop.html');
    } finally {
        globalThis.window=originalWindow;
        globalThis.setInterval=originalInterval;
    }
});

test('Mac Option symbols use physical keys and native delivery is not duplicated', async()=>{
    const source=await readFile(new URL('../web/js/main.js',import.meta.url),'utf8');
    const start=source.indexOf('function setupPresetHotkeys() {');
    const end=source.indexOf('// --- Global Exports ---',start);
    let listener;
    const calls=[];
    const window={__auraNativeShortcuts:false,runSessionShortcut:payload=>calls.push(payload)};
    const context={window,document:{addEventListener(type,fn){listener=fn;}},stateManager:{isLiveInterviewActive:()=>true},Date};
    vm.runInNewContext(source.slice(start,end)+'\nsetupPresetHotkeys();',context);
    const event={altKey:true,ctrlKey:false,metaKey:false,shiftKey:false,repeat:false,key:'ß',code:'KeyS',target:{matches:()=>false},preventDefault(){}};
    listener(event);
    assert.equal(calls.length,1);
    assert.equal(calls[0].command,'capture_screenshot');
    window.__auraNativeShortcuts=true;
    listener(event);
    assert.equal(calls.length,1);
    window.__auraNativeShortcuts=false;
    listener({...event,repeat:true});
    assert.equal(calls.length,1);
});
