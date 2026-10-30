// A screenshot is captured only when the user requests Capture / Option+S.
export async function captureNativeScreen(request = fetch, Reader = FileReader) {
    const response = await request('/api/screen/capture', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'
    });
    if (!response.ok) {
        const failure = await response.json().catch(() => ({}));
        throw new Error(failure.detail || 'Mac screenshot capture failed. Check Aura’s Screen Recording permission.');
    }
    const blob = await response.blob();
    const dataUrl = await new Promise((resolve, reject) => {
        const reader = new Reader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error('Could not read the captured screenshot.'));
        reader.readAsDataURL(blob);
    });
    return {blob, dataUrl};
}
