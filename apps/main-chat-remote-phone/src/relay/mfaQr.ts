type Qr = { addData(value: string): void; make(): void; getModuleCount(): number; isDark(row: number, column: number): boolean };
// Local, licensed QR encoder; enrollment secrets never leave the device for rendering.
const QRCode = require('./qr/index.js') as new (version: number, level: number) => Qr;
export function enrollmentQr(uri: string): { size: number; path: string } {
  if (!uri.startsWith('otpauth://totp/') || uri.length > 1024 || !/^[\x20-\x7e]+$/.test(uri)) throw new Error('Invalid authenticator URI');
  const qr = new QRCode(-1, 0); // Error correction M, automatic size.
  qr.addData(uri); qr.make();
  const count = qr.getModuleCount(); const path: string[] = [];
  for (let row = 0; row < count; row++) for (let column = 0; column < count; column++) {
    if (qr.isDark(row, column)) path.push(`M${column + 4} ${row + 4}h1v1h-1z`);
  }
  return { size: count + 8, path: path.join('') };
}
