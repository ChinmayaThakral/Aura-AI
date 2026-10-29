// Modular main.js - Entry point and coordination
import { StateManager } from './state-manager.js';
import { WebSocketHandler } from './websocket-handler.js';
import { ProviderManager } from './provider-manager.js';
import {
    setupMicrophone,
    startAudioProcessing,
    stopAudioProcessing,
    getScreenVideoTrack,
    isScreenSharingAvailable,
    isSystemAudioLive
} from './audio_handler.js';
import muteManager from './mute-manager.js';
// Personal defaults are optional and never required by a fresh checkout.
const { autofillForTesting } = await import('./dev.js').catch(() => import('./dev.example.js'));
import { loadConfig, isDev, devLog, devWarn, devError, applyConsoleGate } from './config.js';
import liveInterviewUI from './live-interview.js';
import hotkeyManager from './hotkeys.js';
import presetManager from './preset-manager.js';
import screenshotService from './screenshot-service.js';
import { ConfigManager } from './config-manager.js';
import { testStreamingMarkdown, testSampleMarkdown } from './streaming-markdown-demo.js';
import { onDomReady, loadDefaultProfile, setupDesktopSyncLink } from './onboarding.js';
import { createSessionShortcutHandler } from './session-shortcuts.js';

// Initialize managers
const stateManager = new StateManager();
const webSocketHandler = new WebSocketHandler(stateManager);
const providerManager = new ProviderManager(stateManager, webSocketHandler);
const configManager = new ConfigManager(stateManager);

// Expose to window for inter-module integration
window.providerManager = providerManager;
window.configManager = configManager;

// --- Dependency Injection ---
// Wire the managers together to avoid race conditions and reliance on globals.
// This ensures the WebSocketHandler has a direct reference to the ProviderManager.
webSocketHandler.setProviderManager(providerManager);

// --- DOM Elements ---
const views = {
    onboarding: document.getElementById('onboarding-view'),
    preflight: document.getElementById('preflight-view'),
    live: document.getElementById('live-view'),
};

const micSelect = document.getElementById('mic-select');
const proceedButton = document.getElementById('proceed-to-checks');
const startButton = document.getElementById('start-interview-button');
const backButton = document.getElementById('back-to-onboarding-btn');
let sessionStartVersion = 0;
window.addEventListener('aura-audio-status', event => {
    const status = document.getElementById('audio-source-status');
    if (status) {
        status.textContent = event.detail.message;
        status.dataset.state = event.detail.state;
    }
});

// --- Tab Management ---
function setupTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-tab');

            // Update buttons
            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            // Update panes
            tabPanes.forEach(p => p.classList.remove('active'));
            const targetPane = document.getElementById(targetId);
            if (targetPane) targetPane.classList.add('active');

            // Refresh advanced config if switching to that tab
            if (targetId === 'advanced-config-tab') {
                configManager.loadInitialData();
            }
        });
    });

    // Wire up the Fill Demo Data button
    const fillDemoBtn = document.getElementById('fill-demo-btn');
    if (fillDemoBtn) {
        fillDemoBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            autofillForTesting();
            fillDemoBtn.textContent = '✅ Filled!';
            setTimeout(() => { fillDemoBtn.textContent = '⚡ Demo'; }, 1500);
        });
    }
}


// --- View Management ---
function switchView(targetView) {
    Object.values(views).forEach(view => view.classList.remove('active'));
    views[targetView].classList.add('active');
}

function handleOnboarding() {
    if (stateManager.handleOnboarding()) {
        switchView('preflight');
        runPreFlightChecks();
    }
}

async function runPreFlightChecks() {
    const captureInfo = document.getElementById('system-capture-info');
    if (captureInfo) {
        captureInfo.textContent = window.pywebview
            ? 'Desktop sessions capture Mac playback directly. Allow Aura’s macOS capture permission when you start; no Chrome Aura tab is needed.'
            : 'Browser sessions require sharing the tab containing the audio with Share tab audio enabled.';
        if (window.pywebview) {
            try {
                const response = await fetch('/api/audio/system/status');
                const status = await response.json();
                captureInfo.textContent = status.message;
            } catch {
                captureInfo.textContent = 'Could not check Mac playback capture. Keep Aura running and retry setup.';
            }
        }
    }
    // --- 1. Microphone Check ---
    // First, ensure we have microphone permissions as this is a prerequisite.
    const micPermissionCheck = document.getElementById('check-mic-permission');
    const micSelectionCheck = document.getElementById('check-mic-selection');

    providerManager.webSocketHandler.updateCheckStatus(micPermissionCheck, 'pending', 'Requesting Microphone...');
    const micPermission = await setupMicrophone();
    window.__auraTextOnly = !micPermission && !window.pywebview;
    if (micPermission) {
        providerManager.webSocketHandler.updateCheckStatus(micPermissionCheck, 'success', 'Microphone Permission OK');
        providerManager.webSocketHandler.updateCheckStatus(micSelectionCheck, 'success', 'Microphone Selection Ready');
    } else {
        // On non-bundled macOS builds WKWebView often can't obtain mic access
        // (no OS prompt is possible). Fall back to a text-only interview using
        // the typed-question bar instead of blocking Start.
        providerManager.webSocketHandler.updateCheckStatus(micPermissionCheck, 'success', window.pywebview ? 'Microphone unavailable — Mac playback remains available' : 'Text-only mode (mic unavailable)');
        providerManager.webSocketHandler.updateCheckStatus(micSelectionCheck, 'success', window.pywebview ? 'System audio will be captured without microphone input' : 'Type your questions instead of speaking');
        // Do NOT return — let the remaining checks run so Start can enable.
    }

    // --- 2. Backend Connection and Session Establishment (NEW ASYNC FLOW) ---
    // We now `await` the connection. The `connect` method returns a promise that
    // only resolves after the WebSocket is open AND the server has confirmed
    // that a session (new or resumed) is established.
    try {
        providerManager.webSocketHandler.updateCheckStatus(providerManager.checks.backend, 'pending', 'Connecting to Backend...');
        await webSocketHandler.connect();
        providerManager.webSocketHandler.updateCheckStatus(providerManager.checks.backend, 'success', 'Backend Connected');
    } catch (error) {
        providerManager.webSocketHandler.updateCheckStatus(providerManager.checks.backend, 'error', 'Backend Connection Failed');
        console.error("Failed to establish WebSocket connection and session:", error);
        // The error status is already set within the WebSocketHandler's onError method.
        return; // Stop checks if backend connection fails.
    }

    // --- 3. AI Provider and Deepgram API Verification ---
    // These checks are now only run *after* the backend session is confirmed to be ready.
    // This ensures that the verification messages can be sent reliably.
    await providerManager.runPreFlightChecks();
}

// These functions are now handled by the modules

// This function is now handled by WebSocketHandler

// This function is now handled by WebSocketHandler

async function startInterview() {
    const version = ++sessionStartVersion;
    switchView('live');
    liveInterviewUI.init();
    liveInterviewUI.initialize();
    hotkeyManager.setEnabled(true);

    if (!window.__auraTextOnly || window.pywebview) {
        const onAudioData = (audioData, speakerHint) => {
            webSocketHandler.sendAudioChunk(audioData, muteManager.isMicrophoneMuted());
        };

        const processingStarted = await startAudioProcessing(micSelect.value, onAudioData);
        if (version !== sessionStartVersion) return;
        window.__auraTextOnly = !processingStarted;

        if (!processingStarted) {
            // Audio failed at start — drop to text-only rather than bouncing back.
            devWarn('Audio processing unavailable — continuing in text-only mode.');
            window.__auraTextOnly = true;
        }
    }

    if (window.__auraTextOnly) {
        // Make the text-only mode obvious in the live view.
        const activity = document.getElementById('activity-indicator');
        if (activity) {
            const label = activity.querySelector('span');
            if (label) label.textContent = 'Text-only mode — type your question below';
        }
    }

    webSocketHandler.startInterview();
    reportClientControls();
}

function reportClientControls() {
    if (!stateManager.isLiveInterviewActive()) return;
    const mute = muteManager.getMuteStatus();
    webSocketHandler.sendMessage('client_controls', {
        mic_muted: mute.microphone, paused: mute.universal,
        vision_active: stateManager.getState().visionMode.isActive,
        queue_count: screenshotService.screenshotQueue.length,
        queue_limit: screenshotService.maxScreenshots,
        vision_model: screenshotService.visionConfig?.model || '',
        tab_audio_live: isSystemAudioLive()
    });
}

async function endInterview() {
    sessionStartVersion++;
    console.log('🔚 Ending interview and clearing state...');

    // Stop all audio processing
    stopAudioProcessing();

    // Send end interview signal to backend
    webSocketHandler.endInterview();

    // Disable hotkeys
    hotkeyManager.setEnabled(false);

    // Clear conversation UI
    if (window.liveInterviewUI) {
        liveInterviewUI.clearConversation();
    }

    // Comprehensive state clearing
    stateManager.clearInterviewState();

    // Reset preset manager if available
    if (window.presetManager) {
        presetManager.clearNotifications?.();
    }

    // Switch back to onboarding
    switchView('onboarding');

    console.log('✅ Interview ended and state cleared successfully');
}

async function resetInterview() {
    console.log('🔄 Resetting interview...');

    // Send reset signal to backend
    webSocketHandler.sendMessage('reset_session', {});

    // Clear conversation UI
    if (window.liveInterviewUI) {
        liveInterviewUI.clearConversation();
        liveInterviewUI.showActivity('Listening...');
    }

    console.log('✅ Interview reset successfully');
}

// Provider management functions are now handled by ProviderManager


// --- Preset Switching Functions ---
function switchPreset(presetKey) {
    return webSocketHandler.switchPreset(presetKey);
}

// --- Transparency Functions ---
async function setTransparency(level) {
    return await liveInterviewUI.setTransparency(level);
}

function getSystemStatus() {
    return stateManager.getSystemStatus();
}

// --- Vision Mode Functions ---
function switchVisionModel() {
    return stateManager.switchVisionModel();
}

function toggleVisionMode() {
    return stateManager.toggleVisionMode();
}

// --- Screenshot Functions ---
async function captureScreenshot() {
    return await stateManager.captureScreenshot();
}

async function processScreenshots() {
    return await stateManager.processScreenshots();
}

async function resetScreenshotQueue() {
    return await stateManager.resetScreenshotQueue();
}

// --- Audio Toggle Functions ---
function toggleMicMute() {
    return stateManager.toggleMicMute();
}

function toggleUniversalMute() {
    return stateManager.toggleUniversalMute();
}

// --- Event Listeners ---
function setupEventListeners() {
    proceedButton?.addEventListener('click', handleOnboarding);
    startButton?.addEventListener('click', startInterview);
    backButton?.addEventListener('click', () => switchView('onboarding'));

    // Provider change listeners
    const providerSelect = document.getElementById('ai-provider-select');
    const secondaryProviderSelect = document.getElementById('ai-secondary-provider-select');
    const visionProviderSelect = document.getElementById('vision-provider-select');
    const visionSecondaryProviderSelect = document.getElementById('vision-secondary-provider-select');

    providerSelect?.addEventListener('change', providerManager.updateModelDropdown.bind(providerManager));
    secondaryProviderSelect?.addEventListener('change', providerManager.updateSecondaryModelDropdown.bind(providerManager));
    visionProviderSelect?.addEventListener('change', providerManager.updateVisionModelDropdown.bind(providerManager));
    visionSecondaryProviderSelect?.addEventListener('change', providerManager.updateSecondaryVisionModelDropdown.bind(providerManager));

    setupManualQuestion();
    setupPdfUploads();
}

// Typed-question input (alternative to voice) shown during the live interview.
function setupManualQuestion() {
    const form = document.getElementById('manual-question-form');
    const input = document.getElementById('manual-question-input');
    if (!form || !input) return;

    form.addEventListener('submit', (e) => {
        e.preventDefault();
        if (submitManualQuestion(input.value)) input.value = '';
    });
}

function submitManualQuestion(value) {
    const text = String(value || '').trim();
    if (!text || !stateManager.isLiveInterviewActive()) return false;
    liveInterviewUI.addInterviewerQuestion(text, false);
    webSocketHandler.sendManualQuestion(text);
    return true;
}

// Onboarding PDF upload slots — extract text server-side and append to the
// target textarea (background/resume) under a labeled header.
function setupPdfUploads() {
    const inputs = document.querySelectorAll('input[type="file"][data-pdf-target]');
    inputs.forEach((input) => {
        input.addEventListener('change', async () => {
            const file = input.files && input.files[0];
            const statusEl = input.parentElement?.querySelector('[data-pdf-status]');
            if (!file) return;

            const label = input.getAttribute('data-pdf-label') || 'DOCUMENT';
            const targetId = input.getAttribute('data-pdf-target') === 'objectives'
                ? 'user-objectives' : 'user-resume';
            const target = document.getElementById(targetId);
            if (statusEl) statusEl.textContent = 'Extracting…';

            try {
                const fd = new FormData();
                fd.append('file', file);
                const res = await fetch('/api/extract-pdf', { method: 'POST', body: fd });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    throw new Error(data.detail || `HTTP ${res.status}`);
                }
                const header = `\n\n=== ${label} (from PDF: ${data.filename}) ===\n`;
                if (target) target.value = (target.value || '').trimEnd() + header + data.text;
                if (statusEl) statusEl.textContent = `✅ ${data.chars.toLocaleString()} chars added`;
            } catch (err) {
                if (statusEl) statusEl.textContent = `❌ ${String(err.message || err).slice(0, 80)}`;
                devError('PDF extract failed:', err);
            }
        });
    });
}

// Optional profile imports can finish after DOMContentLoaded has already fired.
onDomReady(async () => {
    setupEventListeners();
    setupTabs();
    setupDesktopSyncLink();
    const label = proceedButton?.textContent;
    if (proceedButton) {
        proceedButton.disabled = true;
        proceedButton.textContent = 'Loading Aura…';
    }
    try {
        await loadConfig();
        applyConsoleGate();
        await providerManager.loadAiProviders();
        liveInterviewUI.init();
        setupDeveloperShortcuts();
        setupPresetHotkeys();
        hotkeyManager.setEnabled(false);
        switchView('onboarding');
        await autofillForTesting();
        await loadDefaultProfile();
    } catch (error) {
        console.error('Aura initialization failed:', error);
        stateManager.showOnboardingError('Aura could not finish loading. Please close and reopen the app.');
    } finally {
        if (proceedButton) {
            proceedButton.disabled = false;
            proceedButton.textContent = label;
        }
    }
});

// --- Developer Shortcuts ---
function setupDeveloperShortcuts() {

    devLog('🛠️ Developer shortcuts enabled');

    // Console helper functions
    if (isDev) {
        console.log(`
🧪 === AURA DEVELOPER TOOLS ===
Available testing functions:
• testSampleMarkdown() - Test with sample markdown content  
• testStreamingMarkdown() - Test with comprehensive scenarios
• closeAllTestWindows() - Close all test windows manually
• closeTestWindow('id') - Close specific test window
• autofillForTesting() - Auto-fill onboarding form
• Ctrl+J - Auto-fill form shortcut

📝 Real-time Markdown Testing:
The new hybrid streaming markdown parser integrates with the existing 
MarkdownProcessor to provide real-time rendering that's compatible 
with code blocks, syntax highlighting, and all existing features.

🕒 Auto-Close Feature:
Test windows now auto-close after 10 seconds with countdown display.
Manual close (× button) cancels auto-close timer.

Try: testSampleMarkdown()

🔧 Code Block Fix Applied:
• Fixed missing code blocks in streaming responses
• Added proper syntax highlighting with Prism.js
• Integrated with existing MarkdownProcessor system
• Real-time code block rendering during streaming
        `);
    }

    window.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'j') {
            e.preventDefault();
            devLog('🛠️ Auto-filling form via Ctrl+J');
            autofillForTesting();
        }
    });
}

function setupPresetHotkeys() {
    const commands = {
        KeyQ: ['switch_preset', 'primary'], KeyW: ['switch_preset', 'secondary'],
        KeyE: ['switch_preset', 'auto'], KeyF: ['toggle_vision_mode'],
        KeyV: ['switch_vision_model'], KeyS: ['capture_screenshot'],
        KeyA: ['process_screenshots'], KeyD: ['reset_screenshot_queue'],
        KeyM: ['toggle_mic_mute'], KeyU: ['toggle_universal_mute'], KeyR: ['reset_interview']
    };
    document.addEventListener('keydown', e => {
        if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || e.repeat
            || e.target.matches('input, textarea, select') || !stateManager.isLiveInterviewActive()) return;
        const binding = commands[e.code];
        if (!binding) return;
        e.preventDefault();
        // The native monitor already sends this key to Chrome when permission is present.
        if (window.__auraNativeShortcuts) return;
        window.runSessionShortcut?.({
            id: `local-${Date.now()}-${e.code}`, command: binding[0], preset_key: binding[1],
            expires_at: Date.now() + 10000
        });
    });
}

// --- Global Exports ---
// Make functions globally accessible for hotkeys and external calls
window.switchPreset = switchPreset;
window.setTransparency = setTransparency;
window.getSystemStatus = getSystemStatus;
window.switchVisionModel = switchVisionModel;
window.toggleVisionMode = toggleVisionMode;
window.captureScreenshot = captureScreenshot;
window.processScreenshots = processScreenshots;
window.resetScreenshotQueue = resetScreenshotQueue;
window.toggleMicMute = toggleMicMute;
window.toggleUniversalMute = toggleUniversalMute;
window.endInterview = endInterview;
window.resetInterview = resetInterview;
window.getScreenVideoTrack = getScreenVideoTrack;
window.isScreenSharingAvailable = isScreenSharingAvailable;
window.testStreamingMarkdown = testStreamingMarkdown;
window.testSampleMarkdown = testSampleMarkdown;

// Export managers for other modules
window.appState = stateManager.getState();
window.sendSocketMessage = (type, payload) => webSocketHandler.sendMessage(type, payload);
window.webSocketHandler = webSocketHandler;
window.runSessionShortcut = createSessionShortcutHandler({
    toggle_mic_mute: toggleMicMute,
    toggle_universal_mute: toggleUniversalMute,
    toggle_vision_mode: toggleVisionMode,
    switch_vision_model: switchVisionModel,
    capture_screenshot: captureScreenshot,
    process_screenshots: processScreenshots,
    reset_screenshot_queue: resetScreenshotQueue,
    reset_interview: resetInterview,
    end_interview: endInterview,
    manual_question: ({ text }) => submitManualQuestion(text),
    switch_preset: ({ preset_key }) => {
        if (preset_key === 'secondary' && !stateManager.getState().selectedSecondaryProvider.name) return false;
        return switchPreset(preset_key);
    }
}, payload => webSocketHandler.sendMessage('shortcut_applied', payload), reportClientControls);
muteManager.on('stateChange', reportClientControls);
setInterval(reportClientControls, 3000);

// Export for external use
export { switchView, startInterview, endInterview, stateManager, webSocketHandler, providerManager };
