export type ChatPhotoFormat = 'jpg' | 'png' | 'webp';

export function addAvatarToPhotoPrompt(prompt: string): string {
  const instruction = 'Add yourself to the attached photo.';
  const text = prompt.trim();
  if (text.startsWith(instruction)) return text;
  return !text || text === 'Please respond to this photo.' ? instruction : `${instruction} ${text}`;
}

export type PickedPhotoAsset = {
  uri?: string | null;
  base64?: string | null;
  mimeType?: string | null;
};

export type ChatPhoto = {
  uri: string;
  base64: string;
  format: ChatPhotoFormat;
  source: 'camera' | 'gallery';
};

export function normalizePickedPhotoAsset(asset: PickedPhotoAsset): ChatPhoto | null {
  const uri = String(asset.uri || '').trim();
  const base64 = String(asset.base64 || '').trim();
  if (!uri || !base64) return null;
  // Inspect only the container signature, as the backend does. Picker metadata
  // can still describe the original HEIC after iOS supplies a compatible file.
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  let signature = '', bits = 0, value = 0;
  for (const char of base64.slice(0, 16)) {
    const digit = alphabet.indexOf(char);
    if (digit < 0) break;
    value = (value << 6) | digit;
    bits += 6;
    if (bits >= 8) { bits -= 8; signature += String.fromCharCode((value >> bits) & 255); }
  }
  const format: ChatPhotoFormat | null = signature.startsWith('\x89PNG\r\n\x1a\n') ? 'png'
    : signature.startsWith('\xff\xd8\xff') ? 'jpg'
    : signature.startsWith('RIFF') && signature.slice(8, 12) === 'WEBP' ? 'webp' : null;
  if (!format) throw new Error('Photo format is not supported. Choose a JPEG, PNG, or WebP image.');
  return { uri, base64, format, source: 'gallery' };
}
