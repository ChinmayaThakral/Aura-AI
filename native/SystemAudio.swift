import Foundation
import ScreenCaptureKit
import CoreMedia
import AudioToolbox
import Darwin

// Stdout is a private, bounded JSON-lines pipe to the local backend, not a file.
private let outputLock = NSLock()
private func emit(_ message: [String: Any]) {
    guard var data = try? JSONSerialization.data(withJSONObject: message) else { return }
    data.append(10)
    outputLock.lock()
    defer { outputLock.unlock() }
    FileHandle.standardOutput.write(data)
}

func pcm16(_ samples: UnsafeBufferPointer<Float>) -> Data {
    var result = [Int16](repeating: 0, count: samples.count)
    for index in samples.indices {
        let finite = samples[index].isFinite ? samples[index] : 0
        let clipped = max(-1, min(1, finite))
        result[index] = Int16(clipped * (clipped < 0 ? 32768 : 32767)).littleEndian
    }
    return result.withUnsafeBytes { Data($0) }
}

@available(macOS 13.0, *)
final class SystemAudioCapture: NSObject, SCStreamOutput, SCStreamDelegate {
    private var capture: SCStream?
    private var formatErrorSent = false
    private let samplesQueue = DispatchQueue(label: "com.bhavit.aura.system-audio")

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
        guard let display = content.displays.first else {
            throw NSError(domain: "AuraAudio", code: 1, userInfo: [NSLocalizedDescriptionKey: "No display is available for Mac audio capture."])
        }
        // Capture the system mix before speaker/headphone routing. Do not change
        // the default output device or play the captured samples back.
        let excluded = content.applications.filter {
            $0.processID == getpid() || $0.processID == getppid()
        }
        let filter = SCContentFilter(display: display, excludingApplications: excluded, exceptingWindows: [])
        let config = SCStreamConfiguration()
        config.width = 2
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        config.showsCursor = false
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.sampleRate = 48000
        config.channelCount = 1
        let stream = SCStream(filter: filter, configuration: config, delegate: self)
        // No video output is registered: only audio leaves this helper.
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: samplesQueue)
        capture = stream
        try await stream.startCapture()
        emit(["type": "ready", "sample_rate": 48000, "channels": 1])
    }

    func stop() async {
        try? await capture?.stopCapture()
        capture = nil
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        emit(["type": "error", "message": "Mac audio capture stopped. Check Aura's capture permission and restart the session."])
        exit(1)
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer buffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, CMSampleBufferDataIsReady(buffer),
              let description = CMSampleBufferGetFormatDescription(buffer),
              let format = CMAudioFormatDescriptionGetStreamBasicDescription(description)?.pointee else { return }
        guard format.mSampleRate == 48000, format.mChannelsPerFrame == 1,
              format.mBitsPerChannel == 32, format.mFormatFlags & kAudioFormatFlagIsFloat != 0 else {
            if !formatErrorSent {
                formatErrorSent = true
                emit(["type": "error", "message": "Mac audio did not provide the required 48 kHz mono format. Restart capture after changing audio devices."])
            }
            return
        }
        var buffers = AudioBufferList()
        var retained: CMBlockBuffer?
        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            buffer, bufferListSizeNeededOut: nil, bufferListOut: &buffers,
            bufferListSize: MemoryLayout<AudioBufferList>.size,
            blockBufferAllocator: kCFAllocatorDefault, blockBufferMemoryAllocator: kCFAllocatorDefault,
            flags: UInt32(kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment), blockBufferOut: &retained)
        let count = CMSampleBufferGetNumSamples(buffer)
        guard status == noErr, buffers.mNumberBuffers == 1, count > 0, count <= 48000,
              let bytes = buffers.mBuffers.mData,
              Int(buffers.mBuffers.mDataByteSize) >= count * MemoryLayout<Float>.size else { return }
        let samples = UnsafeBufferPointer(start: bytes.assumingMemoryBound(to: Float.self), count: count)
        let data = pcm16(samples)
        emit(["type": "audio", "data": data.base64EncodedString()])
        withExtendedLifetime(retained) {}
    }
}

@main
struct AuraAudioMain {
    static func main() async {
        if CommandLine.arguments.contains("--self-test") {
            let samples: [Float] = [0, 0.5, -0.5, 1, -1, .nan, 2, -2]
            let data = samples.withUnsafeBufferPointer { pcm16($0) }
            emit(["type": "self_test", "sample_rate": 48000, "channels": 1, "pcm": data.base64EncodedString()])
            return
        }
        guard #available(macOS 13.0, *) else {
            emit(["type": "error", "message": "Direct Mac playback capture requires macOS 13 or newer."])
            return
        }
        let capture = SystemAudioCapture()
        let owner = getppid()
        do {
            try await capture.start()
            signal(SIGTERM, SIG_IGN)
            let termination = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
            termination.setEventHandler {
                Task {
                    await capture.stop()
                    exit(0)
                }
            }
            termination.resume()
            while getppid() == owner { try await Task.sleep(nanoseconds: 1_000_000_000) }
            await capture.stop()
        } catch {
            emit(["type": "error", "message": "Could not start Mac playback capture. Allow Aura in macOS Privacy & Security → Screen & System Audio Recording, then restart Aura. \(error.localizedDescription)"])
            exit(1)
        }
    }
}
