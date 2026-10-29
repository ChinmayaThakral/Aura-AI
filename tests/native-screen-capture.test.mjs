import test from 'node:test';
import assert from 'node:assert/strict';
import { captureNativeScreen } from '../web/js/native-screen-capture.js';

class Reader {
    async readAsDataURL(blob) {
        this.result = `data:${blob.type};base64,${Buffer.from(await blob.arrayBuffer()).toString('base64')}`;
        this.onload();
    }
}

test('native screenshot requests one local capture and retains a queued JPEG', async () => {
    const image = new Blob(['jpeg-content'], {type: 'image/jpeg'});
    const {blob, dataUrl} = await captureNativeScreen(async (url, options) => {
        assert.equal(url, '/api/screen/capture');
        assert.equal(options.method, 'POST');
        assert.equal(options.headers['Content-Type'], 'application/json');
        return {ok: true, blob: async () => image};
    }, Reader);
    assert.equal(blob, image);
    assert.equal(dataUrl, 'data:image/jpeg;base64,anBlZy1jb250ZW50');
});

test('native screenshot permission failures stay visible instead of queuing an image', async () => {
    await assert.rejects(captureNativeScreen(async () => ({
        ok: false, json: async () => ({detail: 'Enable Aura in Screen Recording.'})
    }), Reader), /Enable Aura in Screen Recording/);
});

test('native screenshot read errors do not report successful capture', async () => {
    class FailedReader {
        readAsDataURL() { this.onerror(); }
    }
    await assert.rejects(captureNativeScreen(async () => ({
        ok: true, blob: async () => new Blob(['jpeg'])
    }), FailedReader), /Could not read/);
});
