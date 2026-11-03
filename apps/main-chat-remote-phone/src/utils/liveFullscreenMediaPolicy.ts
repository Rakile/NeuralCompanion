const MIME_EXTENSIONS: Record<string, string> = {
  'image/jpeg': '.jpg',
  'image/jpg': '.jpg',
  'image/png': '.png',
  'image/webp': '.webp',
  'video/mp4': '.mp4',
};

export function isPrivateLiveFullscreenUri(uri: string, root: string): boolean {
  const normalizedRoot = root.endsWith('/') ? root : `${root}/`;
  const remainder = String(uri || '').slice(normalizedRoot.length);
  return Boolean(uri)
    && String(uri).startsWith(normalizedRoot)
    && Boolean(remainder)
    && !remainder.includes('../')
    && !remainder.includes('..\\');
}

export function normalizedImportedExtension(mimeType: string, fileName: string): string {
  const mapped = MIME_EXTENSIONS[String(mimeType || '').toLowerCase()];
  if (mapped) {
    return mapped;
  }
  const match = String(fileName || '').toLowerCase().match(/\.(jpe?g|png|webp|mp4)$/);
  if (!match) {
    return '';
  }
  return match[1] === 'jpeg' ? '.jpg' : `.${match[1]}`;
}

export function shouldDeleteReplacedBackground(previousUri: string, root: string, nextUri: string): boolean {
  return previousUri !== nextUri && isPrivateLiveFullscreenUri(previousUri, root);
}
