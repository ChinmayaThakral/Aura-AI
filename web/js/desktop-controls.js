export function setupDesktopControls(doc = document, fetchCommand = fetch) {
    let currentState = {};
    const pending = new Set();
    const buttons = [...doc.querySelectorAll('[data-session-command]')];
    const status = doc.getElementById('local-control-status');
    const isReady = () => currentState.active && currentState.connected;

    function update() {
        const controls = currentState.controls || {};
        for (const button of buttons) {
            const command = button.dataset.sessionCommand;
            button.disabled = !isReady() || pending.has(command);
            if (command === 'toggle_mic_mute') {
                button.textContent = controls.mic_muted ? 'Unmute mic' : 'Mute mic';
                button.setAttribute('aria-pressed', String(controls.mic_muted));
            } else if (command === 'toggle_universal_mute') {
                button.textContent = controls.paused ? 'Resume audio' : 'Pause audio';
                button.setAttribute('aria-pressed', String(controls.paused));
            } else if (command === 'toggle_vision_mode') {
                button.textContent = controls.vision_active ? 'Vision on' : 'Vision off';
                button.setAttribute('aria-pressed', String(controls.vision_active));
            } else if (['capture_screenshot', 'process_screenshots', 'reset_screenshot_queue', 'switch_vision_model'].includes(command)) {
                button.disabled ||= !controls.vision_active;
                if (command === 'capture_screenshot') button.disabled ||= controls.queue_count >= (controls.queue_limit || 4);
                if (command === 'process_screenshots' || command === 'reset_screenshot_queue') button.disabled ||= !controls.queue_count;
            }
        }
        const model = doc.getElementById('desktop-model');
        model.disabled = !isReady() || pending.has('switch_preset');
        doc.getElementById('desktop-question').disabled = !isReady() || pending.has('manual_question');
        doc.getElementById('desktop-question-send').disabled = !isReady() || pending.has('manual_question');
    }

    async function send(command, extra = {}) {
        if (!isReady() || pending.has(command)) return false;
        pending.add(command);
        status.textContent = 'Sending to Chrome…';
        update();
        try {
            const response = await fetchCommand('/api/desktop/command', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({session_id: currentState.session_id, command, ...extra})
            });
            const result = await response.json();
            if (!response.ok || !result.success) throw new Error(result.detail || 'Chrome did not accept this control.');
            status.textContent = '';
            return true;
        } catch (error) {
            status.textContent = error.message;
            return false;
        } finally {
            pending.delete(command);
            update();
        }
    }

    for (const button of buttons) button.addEventListener('click', () => send(button.dataset.sessionCommand));
    doc.getElementById('desktop-model').addEventListener('change', event => {
        const choice = event.target.value;
        event.target.value = '';
        if (choice) return send('switch_preset', {preset_key: choice});
    });
    doc.getElementById('desktop-question-form').addEventListener('submit', async event => {
        event.preventDefault();
        const input = doc.getElementById('desktop-question');
        const text = input.value.trim();
        if (text && await send('manual_question', {text})) input.value = '';
    });
    update();
    return state => { currentState = state; update(); };
}
