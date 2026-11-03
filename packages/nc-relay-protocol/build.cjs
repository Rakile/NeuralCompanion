// npm install in a separate tools directory, then node build.cjs <tools-directory>.
const fs = require('node:fs'), path = require('node:path'), cp = require('node:child_process');
const tools = path.resolve(process.argv[2] || __dirname);
const esbuild = require(path.join(tools, 'node_modules/esbuild'));
const dest = path.join(__dirname, 'dist'); fs.mkdirSync(dest, {recursive:true});
const common = { bundle:true, nodePaths:[path.join(tools,'node_modules')], logLevel:'warning' };
esbuild.buildSync({...common,entryPoints:[path.join(__dirname,'index.ts')],outfile:path.join(dest,'index.js'),platform:'neutral',format:'esm'});
esbuild.buildSync({...common,entryPoints:[path.join(__dirname,'validator.ts')],outfile:path.join(dest,'validator.cjs'),platform:'node',format:'cjs'});
// Emit types from an isolated build directory whose dependencies belong to tools.
const scratch = path.join(tools,'protocol-types'); fs.mkdirSync(scratch,{recursive:true});
for (const name of ['http.ts','signaling.ts','index.ts']) fs.copyFileSync(path.join(__dirname,name),path.join(scratch,name));
cp.execFileSync(process.execPath,[path.join(tools,'node_modules/typescript/bin/tsc'), '--strict','--declaration','--emitDeclarationOnly','--skipLibCheck','--target','ES2022','--module','NodeNext','--moduleResolution','NodeNext','--types','node','--outDir',dest,path.join(scratch,'index.ts')],{stdio:'inherit',cwd:scratch});
console.log('Built canonical protocol, declarations and local validator.');
