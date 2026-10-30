// Read native hit-testing state so Option+X changes are visible in the overlay.
export function setupDesktopAppearance(doc = document, fetchState = fetch, schedule = setInterval, cancel = clearInterval) {
    const status = doc.getElementById('click-through-status');
    const error = doc.getElementById('local-control-status');
    const buttons = [...doc.querySelectorAll('[data-appearance]')];
    let stopped = false;
    let refreshing = false;

    async function refresh() {
        if (stopped || refreshing) return;
        refreshing = true;
        try {
            const response = await fetchState('/api/desktop/appearance');
            if (!response.ok) throw new Error('Could not read click-through state');
            const state = await response.json();
            if (stopped) return;
            status.dataset.enabled = String(state.available && state.click_through);
            status.textContent = !state.available ? 'Native Aura window is unavailable.'
                : state.click_through ? 'Click-through ON · clicks go to Chrome · Option+X: use controls'
                : !state.shortcuts_ready ? 'Click-through OFF · enable Accessibility and restart Aura to use Option+X'
                : 'Click-through OFF · controls are clickable · Option+X: pass clicks to Chrome';
            for (const button of buttons) {
                button.disabled = !state.available;
                if (button.dataset.appearance === 'click_through') {
                    button.disabled ||= !state.click_through && !state.shortcuts_ready;
                    button.textContent = state.click_through ? 'Use controls (Option+X)' : 'Click-through';
                    button.setAttribute('aria-pressed', String(state.click_through));
                }
            }
        } catch {
            if (!stopped) status.textContent = 'Could not read click-through state · Option+X toggles the native window';
        } finally {
            refreshing = false;
        }
    }

    for (const button of buttons) {
        button.addEventListener('click', async () => {
            button.disabled = true;
            try {
                const response = await fetchState('/api/desktop/appearance', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: button.dataset.appearance,
                        ...(button.dataset.opacity ? {opacity: Number(button.dataset.opacity)} : {}),
                        ...(button.dataset.direction ? {direction: button.dataset.direction} : {})})
                });
                const result = await response.json();
                if (!response.ok || !result.success) throw new Error(result.detail || 'The native window did not apply this change.');
                error.textContent = '';
            } catch (failure) {
                error.textContent = failure.message;
            } finally {
                button.disabled = false;
                await refresh();
            }
        });
    }
    refresh();
    const timer = schedule(refresh, 1500);
    return () => { stopped = true; cancel(timer); };
}
