import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const load = async path => import('data:text/javascript;base64,' + Buffer.from(await readFile(new URL(path, import.meta.url), 'utf8')).toString('base64'));
const { createConversationRenderer } = await load('../web/js/desktop-conversation.js');
const { setupDesktopControls } = await load('../web/js/desktop-controls.js');

// A small DOM double: exercise output, events and scroll state without a browser.
class Element {
    constructor(tag = 'div') {
        this.tagName = tag;
        this.children = [];
        this.dataset = {};
        this.attributes = {};
        this.events = {};
        this.value = '';
        this.scrollTop = 0;
        this.scrollHeight = 1000;
        this.clientHeight = 100;
    }
    set innerHTML(_) { throw new Error('Conversation text must not be interpreted as HTML'); }
    get textContent() { return this.text ?? this.children.map(child => child.textContent).join(''); }
    set textContent(value) { this.text = value; this.children = []; }
    append(...children) { children.forEach(child => this.appendChild(child)); }
    appendChild(child) {
        if (child.tagName === 'fragment') this.append(...child.children);
        else { child.parent = this; this.children.push(child); }
    }
    replaceChildren(...children) { this.text = undefined; this.children = []; this.append(...children); }
    remove() { this.parent.children.splice(this.parent.children.indexOf(this), 1); }
    setAttribute(name, value) { this.attributes[name] = value; }
    addEventListener(name, handler) { this.events[name] = handler; }
    fire(name) { return this.events[name]({target: this, preventDefault() {}}); }
}
const doc = { createElement: tag => new Element(tag), createDocumentFragment: () => new Element('fragment') };

test('all questions and answers form a chronological stream with no previous-question disclosure', () => {
    const stream = new Element('main');
    const render = createConversationRenderer(stream, doc);
    const history = Array.from({length: 24}, (_, index) => ({question: `Question ${index}`, answer: `Answer ${index}`}));
    render({session_id: 'one', history, question: 'Question 24', answer: 'Answer 24'});
    assert.equal(stream.children.length, 25);
    stream.children.forEach((turn, index) => {
        assert.equal(turn.tagName, 'article');
        assert.equal(turn.children[0].textContent, `Question ${index}`);
        assert.equal(turn.children[1].textContent, `Answer ${index}`);
    });
    const lastTurn = stream.children[24];
    render({session_id: 'one', history: [...history, {question: 'Question 24', answer: 'Answer 24'}], question: 'Next', answer: 'Streaming', answering: true});
    assert.equal(stream.children[24], lastTurn);
    assert.equal(stream.children[25].children[2].textContent, 'Generating…');
});

test('stream updates preserve reading position; following, reset and new sessions behave correctly', () => {
    const stream = new Element('main');
    const render = createConversationRenderer(stream, doc);
    const state = {session_id: 'one', question: 'Question', answer: 'Partial'};
    render(state);
    stream.scrollTop = 200;
    render({...state, answer: 'Longer partial answer'});
    assert.equal(stream.scrollTop, 200);
    stream.scrollTop = 900;
    render({...state, answer: 'Complete answer'});
    assert.equal(stream.scrollTop, stream.scrollHeight);
    render({session_id: 'one', history: []});
    assert.equal(stream.children.length, 0);
    render({...state, session_id: 'two'});
    assert.equal(stream.children.length, 1);
    assert.equal(stream.children[0].children[1].textContent, 'Partial');
});

test('answers render text and code safely, including markup-looking model output', () => {
    const stream = new Element('main');
    createConversationRenderer(stream, doc)({session_id: 'one', question: '<img src=x>', answer: '<script>alert(1)</script>\n```js\nconst x = "<div>";\n```'});
    const turn = stream.children[0];
    assert.equal(turn.children[0].textContent, '<img src=x>');
    assert.equal(turn.children[1].children[0].textContent, '<script>alert(1)</script>\n');
    assert.equal(turn.children[1].children[1].tagName, 'pre');
    assert.equal(turn.children[1].children[1].children[0].textContent, 'const x = "<div>";\n');
});

function controlPage(fetchCommand) {
    const names = ['toggle_mic_mute', 'toggle_universal_mute', 'toggle_vision_mode', 'capture_screenshot', 'process_screenshots', 'reset_screenshot_queue', 'switch_vision_model', 'reset_interview', 'end_interview'];
    const buttons = Object.fromEntries(names.map(name => {
        const button = new Element('button');
        button.dataset.sessionCommand = name;
        return [name, button];
    }));
    const ids = Object.fromEntries(['local-control-status', 'desktop-model', 'desktop-question', 'desktop-question-form', 'desktop-question-send'].map(id => [id, new Element()]));
    const opacity = new Element('button');
    opacity.dataset = {appearance: 'opacity', opacity: '0.7'};
    const page = {
        getElementById: id => ids[id],
        querySelectorAll: selector => selector === '[data-session-command]' ? Object.values(buttons) : [opacity]
    };
    const update = setupDesktopControls(page, fetchCommand);
    return {buttons, ids, opacity, update};
}
const live = {session_id: 'chrome-one', active: true, connected: true, controls: {mic_muted: true, paused: false, vision_active: false, queue_count: 0}};
const ok = () => ({ok: true, json: async () => ({success: true})});

test('mute, pause, end, models and typed questions target the current Chrome session', async () => {
    const requests = [];
    const page = controlPage(async (url, options) => {requests.push([url, JSON.parse(options.body)]); return ok();});
    assert.equal(page.buttons.end_interview.disabled, true);
    page.update(live);
    assert.equal(page.buttons.toggle_mic_mute.textContent, 'Unmute mic');
    for (const name of ['toggle_mic_mute', 'toggle_universal_mute', 'reset_interview', 'end_interview']) await page.buttons[name].fire('click');
    assert.deepEqual(requests.slice(0, 4).map(item => item[1]), ['toggle_mic_mute', 'toggle_universal_mute', 'reset_interview', 'end_interview'].map(command => ({session_id: 'chrome-one', command})));
    page.ids['desktop-model'].value = 'secondary';
    await page.ids['desktop-model'].fire('change');
    assert.equal(requests[4][1].preset_key, 'secondary');
    page.ids['desktop-question'].value = '  Typed question  ';
    await page.ids['desktop-question-form'].fire('submit');
    assert.deepEqual(requests[5][1], {session_id: 'chrome-one', command: 'manual_question', text: 'Typed question'});
    assert.equal(page.ids['desktop-question'].value, '');
    page.update({...live, controls: {...live.controls, mic_muted: false, paused: true}});
    assert.equal(page.buttons.toggle_mic_mute.textContent, 'Mute mic');
    assert.equal(page.buttons.toggle_universal_mute.textContent, 'Resume audio');
    page.update({...live, active: false});
    assert(Object.values(page.buttons).every(button => button.disabled));
    assert.equal(page.ids['desktop-question'].disabled, true);
});

test('vision buttons follow the shared screenshot queue', async () => {
    const page = controlPage(async () => ok());
    page.update(live);
    assert.equal(page.buttons.capture_screenshot.disabled, true);
    page.update({...live, controls: {...live.controls, vision_active: true, queue_count: 0}});
    assert.equal(page.buttons.capture_screenshot.disabled, false);
    assert.equal(page.buttons.process_screenshots.disabled, true);
    page.update({...live, controls: {...live.controls, vision_active: true, queue_count: 4}});
    assert.equal(page.buttons.capture_screenshot.disabled, true);
    assert.equal(page.buttons.process_screenshots.disabled, false);
    assert.equal(page.buttons.reset_screenshot_queue.disabled, false);
    page.update({...live, controls: {...live.controls, vision_active: true, queue_count: 1, queue_limit: 1}});
    assert.equal(page.buttons.capture_screenshot.disabled, true);
    assert.equal(page.buttons.process_screenshots.disabled, false);
});

test('pending controls resist repeated clicks and stale-session errors are visible', async () => {
    let release;
    let calls = 0;
    const wait = new Promise(resolve => {release = resolve;});
    const page = controlPage(async () => {calls++; await wait; return {ok: false, json: async () => ({detail: 'This Chrome session is no longer connected.'})};});
    page.update(live);
    const first = page.buttons.toggle_mic_mute.fire('click');
    assert.equal(page.buttons.toggle_mic_mute.disabled, true);
    await page.buttons.toggle_mic_mute.fire('click');
    assert.equal(calls, 1);
    release();
    await first;
    assert.match(page.ids['local-control-status'].textContent, /no longer connected/);
    page.update({...live, connected: false});
    assert.equal(page.buttons.toggle_mic_mute.disabled, true);
    await page.buttons.toggle_mic_mute.fire('click');
    assert.equal(calls, 1);
});
