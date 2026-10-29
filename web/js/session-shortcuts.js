// Execute native shortcuts in the browser that owns the active audio session.
export function createSessionShortcutHandler(actions, sendStatus, onChange = () => {}) {
    const seen = new Set();
    let visionQueue = Promise.resolve();
    const visionCommands = new Set(['capture_screenshot', 'process_screenshots', 'reset_screenshot_queue']);

    return function handle(payload) {
        if (!payload?.id || seen.has(payload.id)) return Promise.resolve();
        seen.add(payload.id);
        if (seen.size > 200) seen.delete(seen.values().next().value);
        const execute = async () => {
            let success = false;
            let message = '';
            try {
                if (payload.expires_at && Date.now() > payload.expires_at) throw new Error('Shortcut expired while Chrome was busy. Press it again.');
                const action = actions[payload.command];
                if (typeof action !== 'function') throw new Error('Unknown session shortcut');
                success = (await action(payload)) !== false;
                if (!success) message = payload.command.includes('vision') || payload.command.includes('screenshot')
                    ? 'Check vision mode, the selected vision model and the screenshot queue in Chrome.'
                    : 'The requested control is unavailable in this session.';
            } catch (error) {
                message = error.message;
            }
            onChange();
            sendStatus({ id: payload.id, success, message });
        };
        if (visionCommands.has(payload.command)) {
            visionQueue = visionQueue.then(execute, execute);
            return visionQueue;
        }
        return execute();
    };
}
