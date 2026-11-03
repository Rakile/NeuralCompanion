// Maintained transforms for the exact RN WebRTC package. No package upgrades.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const normalize = value => value.replace(/\r\n/g, '\n');
const JAVA = 'android/src/main/java/com/oney/WebRTCModule/';

// Identifies the maintained native implementation in the installed binary,
// independently of whichever JavaScript Metro currently serves.
function diagnosticSource(nativeRoot, platform) {
  const directory = path.join(nativeRoot, platform);
  const files = fs.readdirSync(directory).filter(name => /\.(swift|kt|java|mm|m|h)$/.test(name)).sort();
  const guard = path.join(__dirname, '../patches', platform === 'ios' ? 'expo-audio-1.1.1-ios-stop/ios/NCPlaybackGuard.swift'
    : 'expo-audio-1.1.1-android-live/android/NCPlaybackGuard.kt');
  return hash(files.map(name => `${name}\n${normalize(fs.readFileSync(path.join(directory, name), 'utf8'))}`).join('\n')
    + normalize(fs.readFileSync(guard, 'utf8')));
}

function rejectLinks(target) {
  for (let p = path.resolve(target); ; p = path.dirname(p)) {
    if (fs.existsSync(p) && fs.lstatSync(p).isSymbolicLink()) throw new Error('Unexpected symlink/junction in module enrollment');
    if (path.dirname(p) === p) break;
  }
}
function replaceOnce(source, before, after) {
  if (!before || source.split(before).length !== 2) throw new Error('Unexpected pinned module source');
  return source.replace(before, () => after);
}
function transform(file, beforeHash, replacements) {
  rejectLinks(file);
  const actual = normalize(fs.readFileSync(file, 'utf8'));
  let before = actual;
  if (hash(before) !== beforeHash) {
    for (const [a, b] of [...replacements].reverse()) before = replaceOnce(before, b, a);
    if (hash(before) !== beforeHash) throw new Error('Unexpected pinned module source hash');
  }
  let desired = before;
  for (const [a, b] of replacements) desired = replaceOnce(desired, a, b);
  return { file, data: desired, applied: actual === desired };
}
function copied(source, file) {
  rejectLinks(source); rejectLinks(file);
  const data = fs.readFileSync(source);
  const applied = fs.existsSync(file);
  if (applied && !fs.readFileSync(file).equals(data)) throw new Error('Unexpected native module adapter source');
  return { file, data, applied };
}
function writePlan(files, verifyOnly = false) {
  if (files.every(p => p.applied)) return { state: 'already-applied' };
  if (verifyOnly) throw new Error('Required native AV enrollment is not applied');
  if (files.some(p => p.applied)) throw new Error('Partial/mixed NC module enrollment; restore the exact dependency first');
  // Every existing input was verified before the first write. A filesystem error
  // leaves a detectably partial state; a later run will not silently accept it.
  for (const { file, data } of files) {
    fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, data);
  }
  return { state: 'applied' };
}

function verifyStandard(moduleRoot, inputs) {
  rejectLinks(moduleRoot);
  if (JSON.parse(fs.readFileSync(path.join(moduleRoot,'package.json'),'utf8')).version !== '124.0.8')
    throw new Error('Unexpected react-native-webrtc version');
  for (const [file,expected] of inputs) {
    rejectLinks(path.join(moduleRoot,file));
    if (hash(normalize(fs.readFileSync(path.join(moduleRoot,file),'utf8'))) !== expected)
      throw new Error('Reinstall the pinned standard react-native-webrtc package; modified SDK enrollment is not supported');
  }
  return {state:'already-applied'};
}
function enrollAndroid({moduleRoot=path.resolve(__dirname,'../node_modules/react-native-webrtc')}={}) {
  return verifyStandard(moduleRoot,[
    [JAVA+'WebRTCModule.java','595bdfbf50427a347e5dd2b000f1d70d8314b6e1251345b4c7499b6c3ec2d2e9'],
    ['android/build.gradle','7d560b309c4e7496c7563dbbee98747c2bd3c2ae434474cc2a7a0c9d87bcedf2'],
  ]);
}

function enrollAndroidAudio({ audioRoot = path.resolve(__dirname, '../node_modules/expo-audio'), nativeRoot = __dirname } = {}) {
  rejectLinks(audioRoot); rejectLinks(nativeRoot);
  if (JSON.parse(fs.readFileSync(path.join(audioRoot, 'package.json'), 'utf8')).version !== '1.1.1')
    throw new Error('Unexpected expo-audio version');
  const java = 'android/src/main/java/expo/modules/audio/';
  const audioManifest = JSON.parse(fs.readFileSync(
    path.resolve(nativeRoot, '../patches/expo-audio-1.1.1-android-live/manifest.json'), 'utf8'));
  const audioModuleHash = audioManifest.files.find(entry => entry.path === java + 'AudioModule.kt')?.after;
  if (!/^[a-f0-9]{64}$/.test(audioModuleHash || '')) throw new Error('Missing pinned Android audio module hash');
  const api = `    Function("ncAVVersion") { 1 }
    Function("ncBufferedPresentationVersion") { 1 }
    Function("ncBufferedPresentationOpen") { ncAV.openBuffered() }
    Function("ncBufferedPresentationVisible") { handle: String, enabled: Boolean -> ncAV.presentBuffered(handle,enabled) }
    Function("ncBufferedPresentationClose") { handle: String -> ncAV.close(handle) }
    AsyncFunction("ncBufferedAudioBind") { handle: String, key: Double, player: AudioPlayer, ticket: String, request: String, chunk: String, samples: Int ->
      ncAV.bindBufferedAudio(handle,key,player,ticket,request,chunk,samples)
    }.runOnQueue(Queues.MAIN)
    Function("ncBufferedAudioRetire") { handle: String, key: Double -> ncAV.retireBufferedAudio(handle,key) }
    AsyncFunction("ncBufferedVideoBind") { handle: String, key: Double, player: expo.modules.video.player.VideoPlayer, uri: String, start: Int, frames: Int ->
      ncAV.bindBufferedVideo(handle,key,player,uri,start,frames)
    }.runOnQueue(expo.modules.kotlin.functions.Queues.MAIN)
    AsyncFunction("ncBufferedVideoRetire") { handle: String, token: String -> ncAV.retireBufferedVideo(handle,token) }
      .runOnQueue(expo.modules.kotlin.functions.Queues.MAIN)
    AsyncFunction("ncBufferedVideoReady") { handle: String, token: String -> ncAV.bufferedVideoReady(handle,token) }
      .runOnQueue(expo.modules.kotlin.functions.Queues.MAIN)
    Function("ncAVHandoffVersion") { 1 }
    Function("ncAVOpeningVersion") { 1 }
    AsyncFunction("ncAVHandoffBegin") { handle: String, key: Double, revision: Long, owner: String, plan: String, count: Int, indices: List<Int> ->
      ncAV.handoffBegin(handle,key,revision,owner,plan,count,indices)
    }
    AsyncFunction("ncAVHandoffAppend") { handle: String, key: Double, revision: Long, index: Int, uri: String ->
      ncAV.handoffAppend(handle,key,revision,index,uri)
    }
    AsyncFunction("ncAVHandoffArm") { handle: String, key: Double, revision: Long -> ncAV.handoffArm(handle,key,revision) }
    AsyncFunction("ncAVHandoffNext") { handle: String, key: Double, revision: Long, next: Double, count: Int, indices: List<Int> ->
      ncAV.handoffNext(handle,key,revision,next,count,indices)
    }
    AsyncFunction("ncBufferedHandoffSource") { handle: String, key: Double, revision: Long, next: Double, source: Map<String,Any> ->
      val sha=source["idleSha"] as? String
      val verified=if(source.containsKey("idleChunks")) NCIdleChunkReturn.parse(source)!=null else if(sha.isNullOrEmpty()) true else {
        val file=ncIdleCache.get(source["idleGeneration"] as? String ?: "",source["idleId"] as? String ?: "")
        file!=null && file["sha256"]==sha && file["uri"]==source["idleUri"]
      }
      verified && ncAV.bufferedSource(handle,key,revision,next,source)
    }
    Function("ncAVHandoffStatus") { handle: String -> ncAV.handoffStatus(handle) }
    Function("ncAVOpeningBegin") { handle: String, key: Double -> ncAV.openingBegin(handle,key) }
    AsyncFunction("ncAVOpeningPrepare") { handle: String, key: Double, revision: Long, owner: String, media: String, uri: String, sourceCount: Int, indices: List<Int> ->
      ncAV.openingPrepare(handle,key,revision,owner,media,uri,sourceCount,indices)
    }
    Function("ncAVOpeningDetachBegin") { handle: String, key: Double -> ncAV.openingDetachBegin(handle,key) }
    AsyncFunction("ncAVOpeningDetachWait") { ticket: String -> ncAV.idleDetachWait(ticket) }
    Function("ncIdleVideoVersion") { 1 }
    Function("ncBufferedIdleChunksVersion") { 1 }
    AsyncFunction("ncBufferedIdleChunkPrepare") { handle: String, revision: Long, data: Map<String,Any> ->
      ncAV.idleChunkPrepare(handle,revision,data)
    }
    AsyncFunction("ncBufferedIdleChunkAppend") { handle: String, revision: Long, data: Map<String,Any> ->
      ncAV.idleChunkAppend(handle,revision,data)
    }
    AsyncFunction("ncBufferedIdleChunkSelect") { handle: String, revision: Long, generation: String, motion: String, media: String ->
      ncAV.idleChunkSelect(handle,revision,generation,motion,media)
    }.runOnQueue(Queues.MAIN)
    Function("ncBufferedIdleChunkDetachBegin") { handle: String, generation: String, media: String ->
      ncAV.idleChunkDetachBegin(handle,generation,media)
    }
    AsyncFunction("ncBufferedIdleChunkDetachWait") { ticket: String -> ncAV.idleDetachWait(ticket) }
    AsyncFunction("ncBufferedIdlePrepare") { handle: String, generation: String, id: String, uri: String, fade: Int, revision: Long, sourceCount: Int ->
      ncAV.idlePrepare(handle,mapOf("generation" to generation,"id" to id,"uri" to uri),fade,revision,sourceCount)
    }
    Function("ncAVIdleBegin") { handle: String -> ncAV.idleBegin(handle) }
    AsyncFunction("ncAVIdlePrepare") { handle: String, generation: String, id: String, sha: String, fade: Int, revision: Long ->
      val file = ncIdleCache.get(generation,id)
      file != null && file["sha256"] == sha && ncAV.idlePrepare(handle,file,fade,revision)
    }
    AsyncFunction("ncAVIdleSelect") { handle: String, generation: String, id: String -> ncAV.idleSelect(handle,generation,id) }.runOnQueue(Queues.MAIN)
    Function("ncAVIdleClear") { handle: String -> ncAV.idleClear(handle) }
    Function("ncAVIdleDetachBegin") { handle: String -> ncAV.idleDetachBegin(handle) }
    AsyncFunction("ncAVIdleDetachWait") { ticket: String -> ncAV.idleDetachWait(ticket) }
    Function("ncAVIdleClockVersion") { 1 }
    Function("ncAVIdlePosition") { handle: String -> ncAV.idlePosition(handle) }
    AsyncFunction("ncAVIdlePrepareFrame") { handle: String, generation: String, id: String, sha: String, fade: Int, revision: Long, sourceCount: Int ->
      val file = ncIdleCache.get(generation,id)
      file != null && file["sha256"] == sha && ncAV.idlePrepare(handle,file,fade,revision,sourceCount)
    }
    Function("ncIdleCacheVersion") { 2 }
    AsyncFunction("ncIdleCacheSelect") { scope: String, avatar: String -> ncIdleCache.select(scope, avatar) }
    AsyncFunction("ncIdleCacheBegin") { generation: String, id: String, bytes: Long, sha: String -> ncIdleCache.begin(generation, id, bytes, sha) }
    AsyncFunction("ncIdleCacheAppend") { handle: String, offset: Long, bytes: ByteArray ->
      require(bytes.size in 1..262144) { "Invalid idle IO chunk" }
      ncIdleCache.append(handle, offset, bytes)
    }
    AsyncFunction("ncIdleCacheFinish") { handle: String -> ncIdleCache.finish(handle) }
    AsyncFunction("ncIdleCacheAbort") { handle: String -> ncIdleCache.abort(handle) }
    AsyncFunction("ncIdleCacheInvalidate") { generation: String -> ncIdleCache.invalidate(generation) }
    AsyncFunction("ncIdleCacheGet") { generation: String, id: String -> ncIdleCache.get(generation, id) }
    AsyncFunction("ncIdleCacheUsage") { ncIdleCache.usage() }
    Function("ncAVDiagnosticSource") { "${diagnosticSource(nativeRoot, 'android')}" }
    Function("ncAVVisible") { handle: String -> ncAV.visible(handle) }
    View(NCAVView::class) {
      Prop("handle") { view: NCAVView, handle: String -> view.handle = handle }
    }

`;
  const hooks = [
    ['  private val focusLifecycle = NCAudioFocusLifecycle()', '  private val ncAV = NCAVBridge()\n  private val ncIdleCacheDelegate = lazy { NCIdleCacheIO(java.io.File(requireNotNull(appContext.reactContext).cacheDir, "nc-idle-v1")) }\n  private val ncIdleCache by ncIdleCacheDelegate\n  private val focusLifecycle = NCAudioFocusLifecycle()'],
    ['    Function("ncPlaybackGuardVersion")', api + '    Function("ncPlaybackGuardVersion")'],
    ['    OnDestroy {\n', '    OnDestroy {\n      ncAV.destroy()\n      if (ncIdleCacheDelegate.isInitialized()) Thread { ncIdleCache.close() }.start()\n'],
  ];
  const names = ['NCBufferedVideoSource.kt','NCBufferedVideoTimeline.kt','NCBufferedAudioClock.kt',
    'NCVisualTransition.kt','NCSpeechOpening.kt','NCIdleVideo.kt','NCHandoffVideo.kt','NCTextureVideo.kt',
    'NCIdleChunkFile.kt','NCIdleChunkWindow.kt','NCIdleChunkReturn.kt',
    'NCIdleCacheIO.kt','NCAVBridge.kt','NCAVView.kt'];
  return writePlan([
    transform(path.join(audioRoot, java, 'AudioModule.kt'), audioModuleHash, hooks),
    transform(path.join(audioRoot, 'android/build.gradle'), '33ecc037b48cd0a8172448af3b6907ec05902eb6f6eba3dd9616316a32f3a287', [
      ['dependencies {', "dependencies {\n  implementation project(':react-native-webrtc')\n  implementation(findProject(':expo-video') ?: 'host.exp.exponent:expo.modules.video:3.0.16')"],
    ]),
    ...names.map(name => copied(path.join(nativeRoot, 'android', name), path.join(audioRoot, java, name))),
  ]);
}

function enrollIOS({moduleRoot=path.resolve(__dirname,'../node_modules/react-native-webrtc')}={}) {
  return verifyStandard(moduleRoot,[
    ['ios/RCTWebRTC/WebRTCModule.m','67494a4494e58f7fd35032ef0c5925a6acd9e7ec68254f69a6147a78cb64bcd0'],
    ['react-native-webrtc.podspec','2c347aa1affd034dcfdf109a9e639516520ba1e8a0cb4d38c94a038e67eafdca'],
  ]);
}

function enrollIOSAudio({ audioRoot = path.resolve(__dirname, '../node_modules/expo-audio'), nativeRoot = __dirname, verifyOnly = false, env = process.env } = {}) {
  rejectLinks(audioRoot); rejectLinks(nativeRoot);
  if (JSON.parse(fs.readFileSync(path.join(audioRoot, 'package.json'), 'utf8')).version !== '1.1.1')
    throw new Error('Unexpected expo-audio version');
  if (env.NC_IOS_HANDOFF_ACCEPTANCE === '1') throw new Error('Native acceptance tests require the development repository');
  const acceptance = false;
  const api = `${acceptance ? '    Function("ncAVHandoffVersion") { 1 }\n' : ''}    Function("ncAVVersion") { 1 }
    Function("ncBufferedPresentationVersion") { 1 }
    Function("ncBufferedPresentationOpen") { self.ncAV.openBuffered() }
    Function("ncBufferedPresentationVisible") { (handle: String, enabled: Bool) in self.ncAV.presentBuffered(handle,enabled:enabled) }
    Function("ncBufferedPresentationClose") { (handle: String) in self.ncAV.close(handle) }
    AsyncFunction("ncBufferedAudioBind") { (handle:String,key:Double,player:AudioPlayer,ticket:String,request:String,chunk:String,samples:Int) in
      self.ncAV.bindBufferedAudio(handle,value:key,player:player,ticket:ticket,request:request,chunk:chunk,samples:samples)
    }.runOnQueue(.main)
    Function("ncBufferedAudioRetire") { (handle:String,key:Double) in self.ncAV.retireBufferedAudio(handle,value:key) }
    AsyncFunction("ncBufferedVideoBind") { (handle:String,key:Double,player:SharedRef<AVPlayer>,uri:String,start:Int,frames:Int) in
      self.ncAV.bindBufferedVideo(handle,value:key,player:player.ref,uri:uri,start:start,frames:frames)
    }.runOnQueue(.main)
    AsyncFunction("ncBufferedVideoRetire") { (handle:String,token:String) in self.ncAV.retireBufferedVideo(handle,token:token) }.runOnQueue(.main)
    AsyncFunction("ncBufferedVideoReady") { (handle:String,token:String) in self.ncAV.bufferedVideoReady(handle,token:token) }.runOnQueue(.main)
    Function("ncAVOpeningVersion") { 1 }
    Function("ncAVOpeningBegin") { (handle: String, key: Double) in self.ncAV.openingBegin(handle,value:key) }
    AsyncFunction("ncAVOpeningPrepare") { (handle: String, key: Double, revision: Int, owner: String, media: String, uri: String, sourceCount: Int, indices: [Int]) in
      self.ncAV.openingPrepare(handle,value:key,revision:revision,owner:owner,media:media,uri:uri,sourceCount:sourceCount,indices:indices)
    }
    Function("ncAVOpeningDetachBegin") { (handle: String, key: Double) in self.ncAV.openingDetachBegin(handle,value:key) }
    AsyncFunction("ncAVOpeningDetachWait") { (ticket: String) in self.ncAV.idleDetachWait(ticket) }
    // Complete capability remains unadvertised until Apple native acceptance.
    AsyncFunction("ncAVHandoffBegin") { (handle: String, key: Double, revision: Int, owner: String, plan: String, count: Int, indices: [Int]) in
      self.ncAV.handoffBegin(handle,value:key,revision:revision,owner:owner,plan:plan,count:count,indices:indices)
    }
    AsyncFunction("ncAVHandoffAppend") { (handle: String, key: Double, revision: Int, index: Int, uri: String) in
      self.ncAV.handoffAppend(handle,value:key,revision:revision,index:index,uri:uri)
    }
    AsyncFunction("ncAVHandoffArm") { (handle: String, key: Double, revision: Int) in
      self.ncAV.handoffArm(handle,value:key,revision:revision)
    }
    AsyncFunction("ncAVHandoffNext") { (handle: String, key: Double, revision: Int, next: Double, count: Int, indices: [Int]) in
      self.ncAV.handoffNext(handle,value:key,revision:revision,next:next,count:count,indices:indices)
    }
    AsyncFunction("ncBufferedHandoffSource") { (handle:String,key:Double,revision:Int,next:Double,source:[String:Any]) -> Bool in
      let sha=source["idleSha"] as? String ?? ""
      if !sha.isEmpty {
        guard let generation=source["idleGeneration"] as? String,let id=source["idleId"] as? String,
          let file=try? self.ncIdleCache.get(generation:generation,id:id),file["sha256"] as? String == sha,
          file["uri"] as? String == source["idleUri"] as? String else { return false }
      }
      return self.ncAV.bufferedSource(handle,value:key,revision:revision,next:next,data:source)
    }
    Function("ncAVHandoffStatus") { (handle: String) in self.ncAV.handoffStatus(handle) }
    Function("ncIdleVideoVersion") { 1 }
    Function("ncAVIdleBegin") { (handle: String) in self.ncAV.idleBegin(handle) }
    AsyncFunction("ncBufferedIdlePrepare") { (handle: String, generation: String, id: String, uri: String, fade: Int, revision: Int, sourceCount: Int) in
      return self.ncAV.idlePrepare(handle,file:["generation":generation,"id":id,"uri":uri],fade:fade,revision:revision,sourceTicks:sourceCount)
    }
    AsyncFunction("ncAVIdlePrepare") { (handle: String, generation: String, id: String, sha: String, fade: Int, revision: Int) in
      guard let file = try self.ncIdleCache.get(generation: generation, id: id), file["sha256"] as? String == sha else { return false }
      return self.ncAV.idlePrepare(handle, file: file, fade: fade, revision: revision)
    }
    AsyncFunction("ncAVIdleSelect") { (handle: String, generation: String, id: String) in
      self.ncAV.idleSelect(handle, generation: generation, id: id)
    }.runOnQueue(.main)
    Function("ncAVIdleClear") { (handle: String) in self.ncAV.idleClear(handle) }
    Function("ncAVIdleDetachBegin") { (handle: String) in self.ncAV.idleDetachBegin(handle) }
    AsyncFunction("ncAVIdleDetachWait") { (ticket: String) in self.ncAV.idleDetachWait(ticket) }
    Function("ncAVIdleClockVersion") { 1 }
    Function("ncAVIdlePosition") { (handle: String) in self.ncAV.idlePosition(handle) }
    AsyncFunction("ncAVIdlePrepareFrame") { (handle: String, generation: String, id: String, sha: String, fade: Int, revision: Int, sourceCount: Int) in
      guard let file = try self.ncIdleCache.get(generation: generation, id: id), file["sha256"] as? String == sha else { return false }
      return self.ncAV.idlePrepare(handle,file:file,fade:fade,revision:revision,sourceTicks:sourceCount)
    }
    Function("ncIdleCacheVersion") { 2 }
    AsyncFunction("ncIdleCacheSelect") { (scope: String, avatar: String) in try self.ncIdleCache.select(scope: scope, avatar: avatar) }
    AsyncFunction("ncIdleCacheBegin") { (generation: String, id: String, bytes: Int, sha: String) in
      try self.ncIdleCache.begin(generation: generation, id: id, bytes: bytes, sha256: sha)
    }
    AsyncFunction("ncIdleCacheAppend") { (handle: String, offset: Int, bytes: Data) in
      guard (1...262144).contains(bytes.count) else {
        throw NSError(domain: "NCIdleCache", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid idle IO chunk"])
      }
      try self.ncIdleCache.append(handle: handle, offset: offset, chunk: bytes)
    }
    AsyncFunction("ncIdleCacheFinish") { (handle: String) in try self.ncIdleCache.finish(handle: handle) }
    AsyncFunction("ncIdleCacheAbort") { (handle: String) in try self.ncIdleCache.abort(handle: handle) }
    AsyncFunction("ncIdleCacheInvalidate") { (generation: String) in try self.ncIdleCache.invalidate(generation: generation) }
    AsyncFunction("ncIdleCacheGet") { (generation: String, id: String) in try self.ncIdleCache.get(generation: generation, id: id) }
    AsyncFunction("ncIdleCacheUsage") { try self.ncIdleCache.usage() }
    Function("ncAVDiagnosticSource") { "${diagnosticSource(nativeRoot, 'ios')}" }
    Function("ncAVVisible") { (handle: String) in self.ncAV.visible(handle) }
    View(NCAVView.self) {
      Prop("handle") { (view: NCAVView, handle: String) in view.handle = handle }
    }

`;
  const names = ['NCBufferedVideoSource.swift','NCBufferedAudioClock.swift','NCVisualTransition.swift','NCStreamPicture.swift',
    'NCSpeechOpening.swift','NCIdleVideo.swift','NCHandoffVideo.swift','NCIdleCacheIO.swift','NCAVBridge.swift','NCAVView.swift'];
  return writePlan([
    transform(path.join(audioRoot, 'ios/AudioModule.swift'), 'ceeae354d1d95a3c16a55a93030bc5a58f7010bfd5772047b16189320f2045a5', [
      ['  private let registry = AudioComponentRegistry()', '  private let registry = AudioComponentRegistry()\n  private let ncAV = NCAVBridge()\n  private let ncIdleCache = NCIdleCacheIO(directory: FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("nc-idle-v1"))'],
      ['    Function("ncPlaybackGuardVersion")', api + '    Function("ncPlaybackGuardVersion")'],
      ['    OnDestroy {\n', '    OnDestroy {\n      self.ncAV.destroy()\n      DispatchQueue.global(qos: .utility).async { self.ncIdleCache.close() }\n'],
    ]),
    transform(path.join(audioRoot, 'ios/ExpoAudio.podspec'), '3253dc7bdd25118fe26c56c40be325ffae05a6427567a412c584cfc9b833b12f', [
      ["  s.dependency 'ExpoModulesCore'", "  s.dependency 'ExpoModulesCore'\n  s.dependency 'JitsiWebRTC', '~> 124.0.0'"],
      ["    'DEFINES_MODULE' => 'YES',", "    'DEFINES_MODULE' => 'YES',\n    'CLANG_CXX_LANGUAGE_STANDARD' => 'c++17',"],
      ['Dir.glob("**/*.{h,m,swift}",', 'Dir.glob("**/*.{h,m,mm,swift}",'],
    ]),
    ...names.map(name => copied(path.join(nativeRoot, 'ios', name), path.join(audioRoot, 'ios/nc', name))),
  ], verifyOnly);
}

module.exports = { enrollAndroid, enrollAndroidAudio, enrollIOS, enrollIOSAudio };
