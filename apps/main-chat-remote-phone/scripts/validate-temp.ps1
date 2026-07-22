$ErrorActionPreference = "Stop"

function Invoke-Native {
  param(
    [Parameter(Mandatory = $true)][string]$Command,
    [string[]]$Arguments = @()
  )
  & $Command @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$Command failed with exit code $LASTEXITCODE"
  }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$appRoot = (Resolve-Path -LiteralPath (Join-Path $scriptRoot "..")).Path
$tempBase = (Resolve-Path -LiteralPath $env:TEMP).Path
$tempRoot = Join-Path $tempBase ("nc-phone-validate-" + [guid]::NewGuid().ToString("N"))
$target = Join-Path $tempRoot "app"

$urlSmoke = @'
const assert = require("assert");
const { normalizeLanUrl } = require("./url.js");
assert.equal(normalizeLanUrl("192.168.1.10"), "http://192.168.1.10:8777");
assert.equal(normalizeLanUrl("http://192.168.1.10:8777/health?x=1"), "http://192.168.1.10:8777");
assert.equal(normalizeLanUrl("ws://192.168.1.10:8777/ws?code=123456"), "http://192.168.1.10:8777");
assert.equal(normalizeLanUrl("https://relay.example.test/path"), "https://relay.example.test");
assert.equal(normalizeLanUrl("/health"), "");
assert.equal(normalizeLanUrl("?code=123456"), "");
assert.equal(normalizeLanUrl("http://"), "");
assert.equal(normalizeLanUrl("http://:8777"), "");
'@

$clientSmoke = @'
const assert = require("assert");
const { RemoteClient, RemoteRequestError, isRemoteAuthError } = require("./api/client.js");

const calls = [];
global.fetch = async (url, init) => {
  calls.push({ url, init });
  if (String(url).endsWith("/health")) {
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ ok: true, service: "nc_main_chat_remote" }),
    };
  }
  return {
    ok: false,
    status: 429,
    text: async () => JSON.stringify({ ok: false, error: "Too many invalid pairing attempts. Wait before retrying." }),
  };
};

(async () => {
  const client = new RemoteClient("http://127.0.0.1:8777", "123456");
  const mediaUrl = client.authorizedUrl("/api/musetalk/stream?code=000000&token=secret&fps=8", {
    token: "param-secret",
    wait: 2,
  });
  assert.equal(mediaUrl, "http://127.0.0.1:8777/api/musetalk/stream?fps=8&wait=2&code=123456");
  const health = await client.health();
  assert.equal(health.ok, true);
  assert.equal(calls[0].url, "http://127.0.0.1:8777/health");
  assert.equal(calls[0].init.headers["X-NC-Phone-Code"], undefined);
  try {
    await client.state();
    assert.fail("state request should fail");
  } catch (exc) {
    assert.ok(exc instanceof RemoteRequestError);
    assert.equal(exc.status, 429);
    assert.equal(isRemoteAuthError(exc), true);
    assert.equal(exc.message, "Too many invalid pairing attempts. Wait before retrying.");
    assert.equal(calls[1].url, "http://127.0.0.1:8777/api/state");
    assert.equal(calls[1].init.headers["X-NC-Phone-Code"], "123456");
  }
})().catch((exc) => {
  console.error(exc);
  process.exit(1);
});
'@

$envelopeSmoke = @'
const assert = require("assert");
const { remoteActionError } = require("./envelope.js");

assert.equal(remoteActionError({ ok: false, error: "outer failure" }), "outer failure");
assert.equal(remoteActionError({ result: { ok: false, error: "nested bridge failure" } }), "nested bridge failure");
assert.equal(remoteActionError({ result: { accepted: false, message: "not accepted" } }), "not accepted");
assert.equal(
  remoteActionError({ result: { send_result: { accepted: false, error: "chat rejected transcript" } } }),
  "chat rejected transcript"
);
assert.equal(remoteActionError({ ok: true, result: { accepted: true } }), "");
'@

$demoSmoke = @'
const assert = require("assert");
const { createInitialDemoRemoteState, advanceDemoMuseTalkFrame, appendDemoChatTurn } = require("./demo/demoState.js");

const state = createInitialDemoRemoteState();
assert.equal(state.features.main_chat_text, true);
assert.equal(state.features.buddy_chat, true);
assert.ok((state.chat.messages || []).length >= 4);
assert.ok((state.mprc.segments || []).length >= 3);
assert.ok(state.mprc.visual.latest_prompt.includes("Visual Reply"));
assert.equal(state.buddy_chat.enabled, true);
assert.equal(state.buddy_chat.llm_mode, "per_persona");
assert.ok((state.musetalk.feed || []).length >= 3);

const advanced = advanceDemoMuseTalkFrame(state);
assert.notEqual(advanced.musetalk.state.preview_frame_index, state.musetalk.state.preview_frame_index);

const replied = appendDemoChatTurn(state, "What do we do next?");
assert.equal(replied.chat.messages[replied.chat.messages.length - 2].content, "What do we do next?");
assert.equal(replied.chat.messages[replied.chat.messages.length - 1].role, "assistant");
'@

New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
  New-Item -ItemType Directory -Path $target | Out-Null
  foreach ($item in @("app.json", "App.tsx", "index.ts", "package.json", "README.md", "tsconfig.json", "plugins", "scripts", "src")) {
    $source = Join-Path $appRoot $item
    if (Test-Path -LiteralPath $source) {
      Copy-Item -LiteralPath $source -Destination $target -Recurse
    }
  }
  Push-Location -LiteralPath $target
  try {
    Invoke-Native -Command npm -Arguments @("install")
    Invoke-Native -Command node -Arguments @("scripts/smoke-ui-copy.js")
    Invoke-Native -Command node -Arguments @("--no-warnings", "--experimental-strip-types", "scripts/smoke-lan-discovery.mjs")
    Invoke-Native -Command node -Arguments @("--no-warnings", "--experimental-strip-types", "scripts/smoke-pairing-qr.mjs")
    Invoke-Native -Command node -Arguments @("--no-warnings", "--experimental-strip-types", "scripts/smoke-swipe-controls.mjs")
    Invoke-Native -Command node -Arguments @("--no-warnings", "--experimental-strip-types", "scripts/smoke-interface-mode.mjs")
    Invoke-Native -Command node -Arguments @("--no-warnings", "--experimental-strip-types", "scripts/smoke-audio-fast-start.mjs")
    Invoke-Native -Command npm -Arguments @("run", "typecheck")
    Invoke-Native -Command npx -Arguments @("tsc", "src/utils/url.ts", "--target", "ES2020", "--module", "commonjs", "--outDir", "out", "--skipLibCheck")
    Invoke-Native -Command npx -Arguments @("tsc", "src/api/client.ts", "--target", "ES2020", "--module", "commonjs", "--outDir", "out", "--skipLibCheck")
    Invoke-Native -Command npx -Arguments @("tsc", "src/api/envelope.ts", "--target", "ES2020", "--module", "commonjs", "--outDir", "out", "--skipLibCheck")
    Invoke-Native -Command npx -Arguments @("tsc", "src/demo/demoState.ts", "--target", "ES2020", "--module", "commonjs", "--outDir", "out", "--skipLibCheck")
    $urlSmokePath = Join-Path (Get-Location).Path "out\url-smoke.js"
    Set-Content -LiteralPath $urlSmokePath -Value $urlSmoke -Encoding UTF8
    Invoke-Native -Command node -Arguments @($urlSmokePath)
    $clientSmokePath = Join-Path (Get-Location).Path "out\client-smoke.js"
    Set-Content -LiteralPath $clientSmokePath -Value $clientSmoke -Encoding UTF8
    Invoke-Native -Command node -Arguments @($clientSmokePath)
    $envelopeSmokePath = Join-Path (Get-Location).Path "out\envelope-smoke.js"
    Set-Content -LiteralPath $envelopeSmokePath -Value $envelopeSmoke -Encoding UTF8
    Invoke-Native -Command node -Arguments @($envelopeSmokePath)
    $demoSmokePath = Join-Path (Get-Location).Path "out\demo-smoke.js"
    Set-Content -LiteralPath $demoSmokePath -Value $demoSmoke -Encoding UTF8
    Invoke-Native -Command node -Arguments @($demoSmokePath)
    & npx expo config --type public | Out-Null
    if ($LASTEXITCODE -ne 0) {
      throw "expo config failed with exit code $LASTEXITCODE"
    }
  } finally {
    Pop-Location
  }
} finally {
  $resolvedTemp = if (Test-Path -LiteralPath $tempRoot) { (Resolve-Path -LiteralPath $tempRoot).Path } else { $null }
  if ($resolvedTemp -and $resolvedTemp.StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase)) {
    Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
  }
}
