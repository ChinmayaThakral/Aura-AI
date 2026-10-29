export function onDomReady(initialize, doc = document) {
    if (doc.readyState === 'loading') {
        doc.addEventListener('DOMContentLoaded', initialize, { once: true });
    } else {
        initialize();
    }
}

export async function loadDefaultProfile(doc = document, fetchProfile = fetch) {
    const response = await fetchProfile('/api/profile');
    if (!response.ok) return;
    const profile = await response.json();
    const fields = {
        name: 'user-name', company: 'user-company', role: 'user-role',
        resume: 'user-resume', objectives: 'user-objectives'
    };
    for (const [key, id] of Object.entries(fields)) {
        const input = doc.getElementById(id);
        if (input && typeof profile[key] === 'string') input.value = profile[key];
    }
    for (const [key, group] of [['focus', 'focus'], ['selectedLanguages', 'language']]) {
        if (!Array.isArray(profile[key])) continue;
        doc.querySelectorAll(`input[name="${group}"]`).forEach(input => {
            input.checked = profile[key].includes(input.value);
        });
    }
}

export function setupDesktopSyncLink(doc = document, fetchStatus = fetch) {
    const button = doc.getElementById('show-chrome-session');
    const status = doc.getElementById('chrome-readiness');
    if (!button || !status) return;
    const check = async () => {
        try {
            const response = await fetchStatus('/api/desktop/status');
            if (!response.ok) throw new Error('Could not check Chrome');
            const result = await response.json();
            window.__auraNativeShortcuts = result.shortcuts_ready === true;
            button.disabled = !result.ready;
            status.textContent = result.message;
            const shortcutStatus = doc.getElementById('shortcut-readiness');
            if (shortcutStatus) shortcutStatus.textContent = result.shortcuts_ready ? 'Global Option shortcuts are ready.'
                : 'For shortcuts while Chrome is focused, enable Aura in System Settings → Privacy & Security → Accessibility, then restart Aura. Enable Input Monitoring too if macOS requests it.';
            return result.ready;
        } catch {
            button.disabled = true;
            status.textContent = 'Could not reach Aura. Keep the desktop app open and retry.';
            return false;
        }
    };
    button.addEventListener('click', async () => {
        if (await check()) window.location.href = '/static/desktop.html';
    });
    check();
    const timer = setInterval(check, 2000);
    window.addEventListener('beforeunload', () => clearInterval(timer), { once: true });
}
