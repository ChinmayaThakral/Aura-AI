// Native playback enters the existing mixer; it is never played to speakers.
export class NativeSystemAudio {
    constructor(onSamples, onStatus, options = {}) {
        this.onSamples = onSamples;
        this.onStatus = onStatus;
        this.WebSocketType = options.WebSocketType || WebSocket;
        this.baseURL = options.baseURL || window.location.href;
        this.timeoutMS = options.timeoutMS || 60000;
        this.isLive = false;
        this.stopped = false;
    }

    start() {
        return new Promise((resolve, reject) => {
            const endpoint = new URL('/ws/system-audio', this.baseURL);
            endpoint.protocol = endpoint.protocol === 'https:' ? 'wss:' : 'ws:';
            const socket = this.socket = new this.WebSocketType(endpoint.href);
            socket.binaryType = 'arraybuffer';
            const fail = message => {
                if (this.stopped || this.failed) return;
                this.failed = true;
                this.isLive = false;
                this.onStatus({state: 'error', message});
                clearTimeout(this.timer);
                reject(new Error(message));
                socket.close();
            };
            this.rejectStart = reject;
            this.timer = setTimeout(() => fail('Mac audio permission timed out. Allow Aura in macOS capture settings, then restart the session.'), this.timeoutMS);
            this.onStatus({state: 'starting', message: 'Connecting Mac playback audio — allow the macOS capture prompt if shown.'});
            socket.addEventListener('message', event => {
                if (this.stopped || this.failed) return;
                if (event.data instanceof ArrayBuffer) {
                    if (!this.isLive || !event.data.byteLength || event.data.byteLength % 2 || event.data.byteLength > 96000) return;
                    const input = new DataView(event.data);
                    const samples = new Float32Array(event.data.byteLength / 2);
                    for (let index = 0; index < samples.length; index++) samples[index] = input.getInt16(index * 2, true) / 32768;
                    this.onSamples(samples);
                    return;
                }
                try {
                    const message = JSON.parse(event.data);
                    if (message.type === 'ready') {
                        if (message.sample_rate !== 48000 || message.channels !== 1) return fail('Mac audio returned an incompatible format.');
                        clearTimeout(this.timer);
                        this.isLive = true;
                        this.onStatus({state: 'live', message: 'Mac playback connected — app audio through speakers or headphones. No Aura Chrome tab is needed.'});
                        resolve();
                    } else if (message.type === 'error') fail(message.message || 'Mac audio capture failed.');
                } catch {
                    fail('Mac audio returned an invalid response.');
                }
            });
            socket.addEventListener('error', () => fail('Could not connect Mac playback capture. Keep Aura running and restart the session.'));
            socket.addEventListener('close', () => {
                if (!this.stopped) fail('Mac playback disconnected. Restart the session to reconnect.');
            });
        });
    }

    stop() {
        this.stopped = true;
        this.isLive = false;
        clearTimeout(this.timer);
        this.rejectStart?.(new Error('Mac audio capture cancelled.'));
        this.socket?.close();
    }
}
