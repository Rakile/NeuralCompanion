type VisualReplyMedia = {
  extension: '.jpg' | '.png' | '.webp';
  mimeType: 'image/jpeg' | 'image/png' | 'image/webp';
};

type MediaFileSystem = {
  copyAsync(options: { from: string; to: string }): Promise<void>;
  downloadAsync(url: string, target: string): Promise<{ uri: string; status?: number }>;
};

type ExportFileSystem = MediaFileSystem & {
  cacheDirectory: string | null;
  readDirectoryAsync(path: string): Promise<string[]>;
  deleteAsync(path: string, options: { idempotent: boolean }): Promise<void>;
};
let exportSequence = 0;
const activeExports = new Set<string>();
const EXPORT_RETENTION_MS = 24 * 60 * 60 * 1000;

/** Sharing can return when Android opens another app; keep that file for a day. */
export async function withVisualReplyExport(
  fs: ExportFileSystem, source: string, extension: string,
  consume: (uri: string) => Promise<unknown>, sharing = false,
): Promise<void> {
  if (!fs.cacheDirectory) throw new Error('Visual Reply image cache is unavailable.');
  const root = fs.cacheDirectory;
  const target = `${root}nc_visual_export_${Date.now()}_${++exportSequence}${extension}`;
  activeExports.add(target);
  let keepForConsumer = false;
  try {
    // Match only our export names, including earlier app versions. Never recurse.
    const names = await fs.readDirectoryAsync(root).catch(() => []);
    await Promise.all(names.map(async name => {
      const match = /^(?:nc_visual_export_(\d+)_\d+|nc_visual_reply_(\d+)|nc_inline_visual_.+_(\d+))\.(?:png|jpg|webp)$/.exec(name);
      if (!match || activeExports.has(root + name)) return;
      const created = Number(match[1] || match[2] || match[3]);
      if (created < Date.now() - EXPORT_RETENTION_MS) await fs.deleteAsync(root + name, { idempotent: true }).catch(() => undefined);
    }));
    const uri = await prepareVisualReplyFile(fs, source, target);
    await consume(uri);
    keepForConsumer = sharing;
  } finally {
    activeExports.delete(target);
    if (!keepForConsumer) await fs.deleteAsync(target, { idempotent: true }).catch(() => undefined);
  }
}

/** Export a private cached image without handing a file URI to the HTTP downloader. */
export async function prepareVisualReplyFile(fs: MediaFileSystem, source: string, target: string): Promise<string> {
  if (/^(file|content):\/\//i.test(source)) {
    await fs.copyAsync({ from: source, to: target });
    return target;
  }
  if (!/^https?:\/\//i.test(source)) throw new Error('This image is not available for saving.');
  const result = await fs.downloadAsync(source, target);
  if (result.status !== undefined && (result.status < 200 || result.status >= 300)) {
    throw new Error('Could not download the image. Reopen it and try again.');
  }
  return result.uri;
}

export function visualReplyMedia(contentType?: string, urlPath?: string): VisualReplyMedia {
  const mime = (String(contentType || '').split(';')[0] || '').trim().toLowerCase();
  if (mime === 'image/png') return { extension: '.png', mimeType: 'image/png' };
  if (mime === 'image/webp') return { extension: '.webp', mimeType: 'image/webp' };
  if (mime === 'image/jpeg') return { extension: '.jpg', mimeType: 'image/jpeg' };

  let pathname = '';
  try {
    pathname = new URL(String(urlPath || ''), 'http://localhost').pathname;
  } catch {
    // Unknown or malformed paths use the established JPEG fallback.
  }
  const extension = pathname.match(/\.(png|webp|jpe?g)$/i)?.[1]?.toLowerCase();
  if (extension === 'png') return { extension: '.png', mimeType: 'image/png' };
  if (extension === 'webp') return { extension: '.webp', mimeType: 'image/webp' };
  return { extension: '.jpg', mimeType: 'image/jpeg' };
}
