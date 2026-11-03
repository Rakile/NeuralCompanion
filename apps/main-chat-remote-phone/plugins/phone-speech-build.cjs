const fs = require('node:fs/promises');
const crypto = require('node:crypto');
const path = require('node:path');
const AAR = 'sherpa-onnx-1.13.2.aar';
const SHA = 'aa5505c0ec4f8bdaee5f214a64ba3012be64f2aecc022e82a64f33392b8dd245';
function verifyArtifact(bytes) {
  if (bytes.length !== 56655608 || crypto.createHash('sha256').update(bytes).digest('hex') !== SHA) {
    throw new Error('Phone speech AAR verification failed');
  }
}
function registerPackage(source) {
  const entry = 'add(com.neuralcompanion.phonespeech.PhoneSpeechPackage())';
  if (source.includes(entry)) return source;
  const anchor = /PackageList\(this\)\.packages\.apply\s*\{/;
  if (!anchor.test(source)) throw new Error('Unsupported Android PackageList template');
  return source.replace(anchor, (match) => `${match}\n              ${entry}`);
}
function addDependencies(source) {
  if (source.includes('// NC phone speech dependencies')) return source;
  if (!/dependencies\s*\{/.test(source)) throw new Error('Unsupported Android dependencies template');
  return source.replace(/dependencies\s*\{/, `dependencies {
    // NC phone speech dependencies
    implementation(files("libs/${AAR}"))
    implementation("org.apache.commons:commons-compress:1.28.0")`);
}
async function stageNative(projectRoot, androidRoot) {
  const source = path.join(projectRoot, 'native/phone-speech');
  const javaRoot = path.join(androidRoot, 'app/src/main/java/com/neuralcompanion/phonespeech');
  await fs.mkdir(javaRoot, { recursive: true });
  for (const file of await fs.readdir(path.join(source, 'src'))) {
    if (file.endsWith('.kt')) await fs.copyFile(path.join(source, 'src', file), path.join(javaRoot, file));
  }
  const libs = path.join(androidRoot, 'app/libs');
  const assets = path.join(androidRoot, 'app/src/main/assets');
  await fs.mkdir(assets, { recursive: true });
  await fs.copyFile(path.join(source, 'THIRD_PARTY_NOTICES.txt'), path.join(assets, 'phone-native-audio-notices.txt'));
  await fs.mkdir(libs, { recursive: true });
  const destination = path.join(libs, AAR);
  let bytes;
  try { bytes = await fs.readFile(destination); verifyArtifact(bytes); } catch {
    // Optional build cache is still checked against the same pinned size/hash.
    if (process.env.NC_PHONE_SHERPA_AAR) bytes = await fs.readFile(process.env.NC_PHONE_SHERPA_AAR);
    else {
      const response = await fetch(`https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.2/${AAR}`, { signal: AbortSignal.timeout(180000) });
      if (!response.ok) throw new Error('Phone speech AAR download failed');
      const chunks = []; let count = 0;
      for await (const chunk of response.body) {
        count += chunk.length;
        if (count > 56655608) throw new Error('Phone speech AAR exceeds expected size');
        chunks.push(chunk);
      }
      bytes = Buffer.concat(chunks);
    }
    verifyArtifact(bytes);
    await fs.writeFile(destination, bytes);
  }
  const rules = path.join(androidRoot, 'app/proguard-rules.pro');
  const existing = await fs.readFile(rules, 'utf8');
  if (!existing.includes('com.k2fsa.sherpa.onnx.**')) await fs.appendFile(rules, '\n-keep class com.k2fsa.sherpa.onnx.** { *; }\n');
  if (!existing.includes('com.neuralcompanion.phonespeech.SherpaTtsCallback')) await fs.appendFile(rules, '\n-keep class com.neuralcompanion.phonespeech.SherpaTtsCallback { *; }\n');
}
module.exports = { registerPackage, addDependencies, verifyArtifact, stageNative };
