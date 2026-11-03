import React, { useMemo } from 'react';
import Svg, { Path, Rect } from 'react-native-svg';
import { enrollmentQr } from './mfaQr';

export function EnrollmentQr({ uri }: { uri: string }) {
  const data = useMemo(() => { try { return enrollmentQr(uri); } catch { return null; } }, [uri]);
  if (!data) return null; // Manual key remains available if QR cannot be rendered.
  return <Svg accessibilityLabel="Authenticator enrollment QR code" width={240} height={240} viewBox={`0 0 ${data.size} ${data.size}`}>
    <Rect width={data.size} height={data.size} fill="#fff" /><Path d={data.path} fill="#000" />
  </Svg>;
}
