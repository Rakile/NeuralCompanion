import Foundation

struct OwnedClip {
    let sessionId: String
    let utteranceId: String
    let uri: String
    let byteLength: Int
    let durationMs: Double
}

enum UtteranceStoreError: Error, Equatable {
    case invalidID
    case invalidSamples
    case accessDenied
    case duplicateID
    case backlogFull
    case fileFailed
}

/// Synchronous worker/file operations; never call on the audio callback. The
/// process-wide lock serializes slot reservation with cleanup across store
/// instances. Disk contents are the quota authority, including failed writes,
/// failed removals, and young files left by earlier process lifetimes.
final class UtteranceStore {
    private struct Key: Hashable {
        let session: String
        let utterance: String
    }
    private struct Entry {
        let clip: OwnedClip
        let url: URL
        var leased = false
        var retired = false
    }

    private static let lock = NSLock()
    // A second store performing stale cleanup must still protect live readers.
    // Production owns one private directory with at most two paths in this set.
    private static var leasedPaths: Set<String> = []
    private let directory: URL
    private let clock: () -> Date
    private let fileManager: FileManager
    private var entries: [Key: Entry] = [:]

    init(rootDirectory: URL, clock: @escaping () -> Date = Date.init,
         fileManager: FileManager = .default) throws {
        self.directory = rootDirectory.standardizedFileURL.appendingPathComponent("nc-live-capture", isDirectory: true)
        self.clock = clock
        self.fileManager = fileManager
        Self.lock.lock()
        defer { Self.lock.unlock() }
        do {
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
            let attributes = try fileManager.attributesOfItem(atPath: directory.path)
            guard attributes[.type] as? FileAttributeType == .typeDirectory else {
                throw UtteranceStoreError.fileFailed
            }
        } catch { throw UtteranceStoreError.fileFailed }
    }

    func write(sessionId: String, utteranceId: String, samples: [Int16]) throws -> OwnedClip {
        try validate(sessionId, utteranceId)
        guard !samples.isEmpty, samples.count <= 960000 else { throw UtteranceStoreError.invalidSamples }
        Self.lock.lock()
        defer { Self.lock.unlock() }
        let key = Key(session: sessionId, utterance: utteranceId)
        // No age eviction during a write. Young or undeletable leftovers make
        // backlogFull recoverable through explicit cleanup/release, not growth.
        let existing: [URL]
        do { existing = try fileManager.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil) }
        catch { throw UtteranceStoreError.fileFailed }
        // Another instance may have cleaned old, unleased files. Discard those
        // obsolete mappings before checking IDs so the in-memory map stays
        // bounded by files that actually exist.
        let existingPaths = Set(existing.map(Self.fileIdentity))
        for oldKey in Array(entries.keys) {
            if let old = entries[oldKey], !existingPaths.contains(Self.fileIdentity(old.url)) {
                Self.leasedPaths.remove(Self.fileIdentity(old.url))
                entries.removeValue(forKey: oldKey)
            }
        }
        guard entries[key] == nil else { throw UtteranceStoreError.duplicateID }
        guard existing.count < 2 else { throw UtteranceStoreError.backlogFull }

        let url = directory.appendingPathComponent(UUID().uuidString + ".wav")
        let header = Self.wavHeader(sampleCount: samples.count)
        var reserved = false
        var handle: FileHandle?
        do {
            // The final generated name is itself the reservation. Never use
            // .atomic: an extra staging file would evade the two-file quota.
            try header.write(to: url, options: .withoutOverwriting)
            reserved = true
            handle = try FileHandle(forWritingTo: url)
            try handle!.seekToEnd()
            var bytes = Data()
            bytes.reserveCapacity(8192)
            for start in stride(from: 0, to: samples.count, by: 4096) {
                bytes.removeAll(keepingCapacity: true)
                for sample in samples[start..<min(start + 4096, samples.count)] {
                    let bits = UInt16(bitPattern: sample)
                    bytes.append(UInt8(truncatingIfNeeded: bits))
                    bytes.append(UInt8(truncatingIfNeeded: bits >> 8))
                }
                try handle!.write(contentsOf: bytes)
            }
            try handle!.close()
            handle = nil
            try fileManager.setAttributes([.modificationDate: clock()], ofItemAtPath: url.path)
            let clip = OwnedClip(sessionId: sessionId, utteranceId: utteranceId, uri: url.absoluteString,
                                 byteLength: 44 + samples.count * 2, durationMs: Double(samples.count) / 16.0)
            entries[key] = Entry(clip: clip, url: url)
            return clip
        } catch {
            try? handle?.close()
            // Failed deletion leaves the reservation on disk, and it still
            // consumes a slot on the next write or after restart. A failed
            // exclusive create never authorizes deleting another file.
            if reserved { try? fileManager.removeItem(at: url) }
            throw UtteranceStoreError.fileFailed
        }
    }

    func acquire(sessionId: String, utteranceId: String) throws -> OwnedClip {
        try validate(sessionId, utteranceId)
        Self.lock.lock()
        defer { Self.lock.unlock() }
        let key = Key(session: sessionId, utterance: utteranceId)
        guard var entry = entries[key], !entry.retired else { throw UtteranceStoreError.accessDenied }
        do {
            let attributes = try fileManager.attributesOfItem(atPath: entry.url.path)
            guard attributes[.type] as? FileAttributeType == .typeRegular,
                  (attributes[.size] as? NSNumber)?.intValue == entry.clip.byteLength else {
                throw UtteranceStoreError.fileFailed
            }
        } catch { throw UtteranceStoreError.fileFailed }
        // Exactly one idempotent read lease, not a reference count.
        entry.leased = true
        entries[key] = entry
        Self.leasedPaths.insert(Self.fileIdentity(entry.url))
        return entry.clip
    }

    func release(sessionId: String, utteranceId: String) throws {
        try validate(sessionId, utteranceId)
        Self.lock.lock()
        defer { Self.lock.unlock() }
        let key = Key(session: sessionId, utterance: utteranceId)
        guard var entry = entries[key] else {
            // A successful release stays idempotent even when a newer session
            // reuses the numeric utterance ID. Never inspect a foreign entry.
            return
        }
        entry.leased = false
        entry.retired = true
        entries[key] = entry
        Self.leasedPaths.remove(Self.fileIdentity(entry.url))
        try delete(key: key, entry: entry)
    }

    func stop(sessionId: String) throws {
        try validateID(sessionId)
        Self.lock.lock()
        defer { Self.lock.unlock() }
        var failed = false
        for key in Array(entries.keys) where key.session == sessionId {
            guard var entry = entries[key] else { continue }
            entry.retired = true
            entries[key] = entry
            if !entry.leased {
                do { try delete(key: key, entry: entry) }
                catch { failed = true }
            }
        }
        if failed { throw UtteranceStoreError.fileFailed }
    }

    func cleanup(now: Date) throws {
        Self.lock.lock()
        defer { Self.lock.unlock() }
        let files: [URL]
        do { files = try fileManager.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil) }
        catch { throw UtteranceStoreError.fileFailed }
        var failed = false
        for url in files {
            guard url.pathExtension == "wav", UUID(uuidString: url.deletingPathExtension().lastPathComponent) != nil,
                  !Self.leasedPaths.contains(Self.fileIdentity(url)) else { continue }
            do {
                let attributes = try fileManager.attributesOfItem(atPath: url.path)
                guard attributes[.type] as? FileAttributeType == .typeRegular,
                      let modified = attributes[.modificationDate] as? Date,
                      now.timeIntervalSince(modified) >= 600 else { continue }
                try fileManager.removeItem(at: url)
                for key in Array(entries.keys) where entries[key].map({ Self.fileIdentity($0.url) }) == Self.fileIdentity(url) {
                    entries.removeValue(forKey: key)
                }
            } catch { failed = true }
        }
        if failed { throw UtteranceStoreError.fileFailed }
    }

    // Foundation directory listings may return base-relative URLs. URL equality
    // also compares that representation, even when the filesystem path matches.
    // Use the same standardized absolute path for mappings and reader pins.
    private static func fileIdentity(_ url: URL) -> String {
        url.standardizedFileURL.path
    }

    private func delete(key: Key, entry: Entry) throws {
        do {
            if fileManager.fileExists(atPath: entry.url.path) { try fileManager.removeItem(at: entry.url) }
            entries.removeValue(forKey: key)
        } catch { throw UtteranceStoreError.fileFailed }
    }

    private func validate(_ session: String, _ utterance: String) throws {
        try validateID(session)
        try validateID(utterance)
    }

    private func validateID(_ id: String) throws {
        guard !id.isEmpty, id.utf8.count <= 128, id.utf8.allSatisfy({ byte in
            (byte >= 48 && byte <= 57) || (byte >= 65 && byte <= 90) ||
                (byte >= 97 && byte <= 122) || byte == 45 || byte == 95
        }) else { throw UtteranceStoreError.invalidID }
    }

    private static func wavHeader(sampleCount: Int) -> Data {
        var data = Data()
        func text(_ value: String) { data.append(contentsOf: value.utf8) }
        func u16(_ value: UInt16) {
            data.append(UInt8(truncatingIfNeeded: value))
            data.append(UInt8(truncatingIfNeeded: value >> 8))
        }
        func u32(_ value: UInt32) {
            for shift in stride(from: 0, to: 32, by: 8) {
                data.append(UInt8(truncatingIfNeeded: value >> shift))
            }
        }
        let length = UInt32(sampleCount * 2)
        text("RIFF"); u32(36 + length); text("WAVE")
        text("fmt "); u32(16); u16(1); u16(1)
        u32(16000); u32(32000); u16(2); u16(16)
        text("data"); u32(length)
        return data
    }
}
