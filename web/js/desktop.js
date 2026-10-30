import { createConversationRenderer } from './desktop-conversation.js';
import { setupDesktopControls } from './desktop-controls.js';
import { setupDesktopAppearance } from './desktop-appearance.js';

const status = document.getElementById('sync-status');
const error = document.getElementById('sync-error');
const transcript = document.getElementById('transcript');
const hint = document.getElementById('setup-hint');
const renderConversation = createConversationRenderer(document.getElementById('conversation-stream'));
const updateControls = setupDesktopControls();
const stopAppearanceSync = setupDesktopAppearance();
let retryDelay = 1000;
let socket;
let closing = false;
let pendingState;
let renderPending = false;
let windowConfigurationError = '';

function render(state) {
    const connected = state.active && state.connected && state.controls?.tab_audio_live && state.transcription_ready;
    status.dataset.connected = String(connected && !state.paused);
    status.textContent = !state.session_id ? 'Waiting for a Chrome session…'
        : !state.active ? 'Session ended — conversation retained'
        : !state.connected ? 'Chrome disconnected — waiting to reconnect'
        : !state.controls?.tab_audio_live ? 'Chrome tab audio is not connected'
        : !state.transcription_ready ? 'Speech transcription is not connected'
        : state.paused ? 'Chrome audio processing paused'
        : 'Synced with Chrome — audio captured in the browser';
    hint.hidden = connected;
    const controls = state.controls || {};
    document.getElementById('control-state').textContent = [
        controls.mic_muted ? 'Mic muted' : 'Mic on',
        controls.paused ? 'Audio paused' : 'Audio active',
        controls.vision_active ? `Vision on · ${controls.queue_count || 0}/${controls.queue_limit || 4} screenshots · ${controls.vision_model || ''}` : 'Vision off',
        state.model || ''
    ].filter(Boolean).join(' | ');
    const shortcutStatus = document.getElementById('shortcut-status');
    shortcutStatus.textContent = state.shortcut_status || '';
    shortcutStatus.dataset.success = String(state.shortcut_ok !== false);
    error.hidden = !state.error && !windowConfigurationError;
    error.textContent = windowConfigurationError || state.error || '';
    transcript.textContent = state.transcript || 'Waiting for speech from Chrome.';
    transcript.scrollTop = transcript.scrollHeight;
    renderConversation(state);
    updateControls(state);
}

function connect() {
    const endpoint = new URL('/ws/desktop', window.location.href);
    endpoint.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(endpoint.href);
    socket.addEventListener('open', () => { retryDelay = 1000; });
    socket.addEventListener('message', event => {
        const message = JSON.parse(event.data);
        if (message.type !== 'desktop_state') return;
        pendingState = message.payload;
        if (renderPending) return;
        renderPending = true;
        requestAnimationFrame(() => {
            renderPending = false;
            render(pendingState);
        });
    });
    socket.addEventListener('close', () => {
        status.dataset.connected = 'false';
        status.textContent = 'Connection lost — reconnecting to Aura…';
        updateControls({active: false, connected: false});
        if (!closing) {
            setTimeout(connect, retryDelay);
            retryDelay = Math.min(retryDelay * 2, 10000);
        }
    });
    socket.addEventListener('error', () => socket.close());
}

async function configureWindow(enabled) {
    try {
        const response = await fetch('/api/window/desktop-display', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled })
        });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error('Window configuration failed');
        windowConfigurationError = '';
    } catch (err) {
        console.warn('Desktop window could not be configured:', err);
        windowConfigurationError = 'Could not configure the floating window. Return to Setup and reopen the Chrome session display.';
        error.hidden = false;
        error.textContent = windowConfigurationError;
    }
}

if (window.pywebview) configureWindow(true);
else window.addEventListener('pywebviewready', () => configureWindow(true), { once: true });
document.getElementById('back-to-setup').addEventListener('click', async event => {
    if (!window.pywebview) return;
    event.preventDefault();
    await configureWindow(false);
    window.location.href = '/';
});
window.addEventListener('beforeunload', () => { closing = true; socket?.close(); stopAppearanceSync(); });
connect();
