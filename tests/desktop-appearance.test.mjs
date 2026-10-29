import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../web/js/desktop-appearance.js', import.meta.url), 'utf8');
const {setupDesktopAppearance} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const flush = () => new Promise(resolve => setImmediate(resolve));
const response = (value, ok = true) => ({ok, json: async () => value});

function page(fetchState) {
    const status = {dataset: {}};
    const error = {};
    const click = {dataset: {appearance: 'click_through'}};
    const opacity = {dataset: {appearance: 'opacity', opacity: '0.7'}};
    for (const button of [click, opacity]) {
        button.setAttribute = (name, value) => {button[name] = value;};
        button.addEventListener = (name, action) => {button[name] = action;};
    }
    let poll;
    let cancelled;
    const stop = setupDesktopAppearance({
        getElementById: id => id === 'click-through-status' ? status : error,
        querySelectorAll: () => [click, opacity]
    }, fetchState, callback => {poll = callback; return 7;}, id => {cancelled = id;});
    return {status, error, click, opacity, poll: () => poll(), stop, cancelled: () => cancelled};
}

test('the overlay reports real click-through state and follows native Option+X toggles', async () => {
    let state = {available: true, click_through: true, shortcuts_ready: true};
    const view = page(async () => response(state));
    await flush();
    assert.match(view.status.textContent, /Click-through ON.*clicks go to Chrome.*Option\+X/);
    assert.equal(view.click['aria-pressed'], 'true');
    state = {...state, click_through: false};
    await view.poll();
    assert.match(view.status.textContent, /OFF.*controls are clickable/);
    assert.equal(view.click['aria-pressed'], 'false');
    assert.equal(view.click.disabled, false);
    view.stop();
    assert.equal(view.cancelled(), 7);
});

test('native failures remain visible and appearance changes are sent to the native endpoint', async () => {
    const requests = [];
    const state = {available: true, click_through: false, shortcuts_ready: true};
    const view = page(async (url, options) => {
        if (!options) return response(state);
        requests.push([url, JSON.parse(options.body)]);
        return response({success: options.body.includes('opacity')});
    });
    await flush();
    await view.opacity.click();
    assert.deepEqual(requests[0], ['/api/desktop/appearance', {action: 'opacity', opacity: 0.7}]);
    await view.click.click();
    assert.match(view.error.textContent, /did not apply/);
    assert.match(view.status.textContent, /OFF/);
    view.stop();
});

test('missing native window or global recovery does not offer a trapping click-through button', async () => {
    let state = {available: true, click_through: false, shortcuts_ready: false};
    let calls = 0;
    const view = page(async () => {calls++; return response(state);});
    await flush();
    assert.equal(view.click.disabled, true);
    assert.match(view.status.textContent, /Accessibility/);
    state = {...state, available: false};
    await view.poll();
    assert.equal(view.opacity.disabled, true);
    assert.match(view.status.textContent, /unavailable/);
    view.stop();
    const before = calls;
    await view.poll();
    assert.equal(calls, before);
});
