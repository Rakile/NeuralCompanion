const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {createRequire} = require('node:module');

const VERSION = '0.81.5';
const BEFORE_HASH = '2beec1985f5f18039278a0e4890051d8d23e79cff852d2902e268b596ebe8e06';
const BEFORE = '        offset = this._averageCellLength * index;';
const AFTER = `${BEFORE}
        // NC: anchor estimates to the measured prefix, not absolute zero.
        // Otherwise a virtualized spacer can feed its own previous position
        // back into the next layout after items change indices (head trimming).
        for (let previous = index - 1; previous >= 0; previous--) {
          const preceding = this.getCellMetrics(previous, props);
          if (preceding) {
            offset =
              preceding.offset + preceding.length +
              this._averageCellLength * (index - previous - 1);
            break;
          }
        }`;
const hash = text => crypto.createHash('sha256').update(text).digest('hex');
const repair = 'Restore the pinned @react-native/virtualized-lists 0.81.5 package; do not fuzzy-apply this patch.';
function fail(message) { throw new Error(`${message}. ${repair}`); }
function rejectLinks(target) {
  for (let current=path.resolve(target);;) {
    if (fs.lstatSync(current).isSymbolicLink()) fail('Refusing a symlink/junction dependency target');
    const parent=path.dirname(current);
    if (parent===current) return;
    current=parent;
  }
}
function installedRoot() {
  const rnPackage=require.resolve('react-native/package.json');
  if (JSON.parse(fs.readFileSync(rnPackage,'utf8')).version!==VERSION) fail('Unexpected React Native version');
  return path.dirname(createRequire(rnPackage).resolve('@react-native/virtualized-lists/package.json'));
}
function inspect(options={}) {
  const root=path.resolve(options.moduleRoot || installedRoot());
  const file=path.join(root,'Lists/ListMetricsAggregator.js');
  rejectLinks(file);
  const pkg=JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8'));
  if(pkg.name!=='@react-native/virtualized-lists' || pkg.version!==VERSION) fail('Unexpected virtualized-lists package/version');
  const text=fs.readFileSync(file,'utf8');
  if(hash(text)===BEFORE_HASH) {
    if(text.split(BEFORE).length!==2) fail('Unexpected list patch anchor');
    return {file,text: text.replace(BEFORE,AFTER),applied:false};
  }
  if(text.split(AFTER).length===2 && hash(text.replace(AFTER,BEFORE))===BEFORE_HASH) {
    return {file,text,applied:true};
  }
  fail('Unknown or partially modified list metrics source');
}
function verifyPatch(options={}) {
  const state=inspect(options);
  if(!state.applied) fail('Required stable list metrics patch is not applied');
  return {state:'verified',sha256:hash(state.text)};
}
function applyPatch(options={}) {
  const state=inspect(options);
  if(state.applied) return {state:'already-applied'};
  fs.writeFileSync(state.file,state.text,'utf8');
  verifyPatch(options);
  return {state:'applied'};
}
if(require.main===module) {
  try {
    const args=process.argv.slice(2);
    if(args.length>1 || (args.length===1 && args[0]!=='--verify')) throw Error('Usage: apply-list-metrics-patch.cjs [--verify]');
    console.log('[list-metrics-patch]',args[0]==='--verify'?verifyPatch():applyPatch());
  } catch(error) { console.error('[list-metrics-patch]',error.message);process.exitCode=1; }
}
module.exports={applyPatch,verifyPatch,BEFORE,AFTER,BEFORE_HASH};
