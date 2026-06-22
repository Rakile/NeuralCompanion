import { readFileSync } from "node:fs";
import { resolve } from "node:path";


export function loadJsonSettings() {
  const settingsPath = process.env.NC_DISCORD_BRIDGE_SETTINGS_JSON || "";
  if (!settingsPath) {
    return {};
  }

  const resolved = resolve(settingsPath);
  const data = JSON.parse(readFileSync(resolved, "utf8"));
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error(`Settings file must contain a JSON object: ${resolved}`);
  }
  return data;
}


export function setting(settings, path, fallback) {
  let cursor = settings;
  for (const part of path.split(".")) {
    if (!cursor || typeof cursor !== "object" || !(part in cursor)) {
      return fallback;
    }
    cursor = cursor[part];
  }
  return cursor ?? fallback;
}


export function envOrSetting(name, settings, path, fallback = "") {
  const envValue = process.env[name];
  if (envValue !== undefined && envValue !== "") {
    return envValue;
  }
  const settingsValue = setting(settings, path, fallback);
  return settingsValue === undefined || settingsValue === null ? fallback : settingsValue;
}

