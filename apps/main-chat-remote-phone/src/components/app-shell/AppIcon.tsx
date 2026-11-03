import React from 'react';
import Svg, { Circle, Path, Rect } from 'react-native-svg';

export type AppIconName = 'chat' | 'visual' | 'settings' | 'companion' | 'voice' | 'look' | 'tools' | 'story' | 'camera' | 'send' | 'paper-plane' | 'live' | 'exit';

/** Shared 24px outline icons, with labels provided by their owning controls. */
export function AppIcon({ name, color, size = 24 }: { name: AppIconName; color: string; size?: number }) {
  return <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" accessibilityElementsHidden>
    {name === 'chat' ? <Path d="M20.5 11.2a8.5 8.5 0 0 1-8.5 8.5 10 10 0 0 1-3.6-.8L3 21l1.4-5.2A8.5 8.5 0 1 1 20.5 11.2Z" /> : null}
    {name === 'visual' ? <><Rect x={5.5} y={3} width={15.5} height={15.5} rx={3} /><Path d="M3 7v12a2 2 0 0 0 2 2h12M6 15l4-4 4 4 3-3 4 4" /><Circle cx={16.5} cy={7.5} r={1} /></> : null}
    {name === 'settings' ? <><Path d="m10 3-.6 2.1-1.8 1L5.5 6 3.7 9.1 5.2 11v2l-1.5 1.9L5.5 18l2.1-.2 1.8 1L10 21h4l.6-2.2 1.8-1 2.1.2 1.8-3.1-1.5-1.9v-2l1.5-1.9L18.5 6l-2.1.2-1.8-1L14 3Z" /><Circle cx={12} cy={12} r={3.1} /></> : null}
    {name === 'companion' ? <><Circle cx={12} cy={8} r={4} /><Path d="M4 21v-2a8 8 0 0 1 16 0v2" /></> : null}
    {name === 'voice' ? <><Rect x={9} y={2} width={6} height={13} rx={3} /><Path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M9 22h6" /></> : null}
    {name === 'look' ? <><Path d="M20 12a8 8 0 1 0-8 8h1.3c2 0 2.4-2 .8-3.1-1.5-1-.8-3 1-3H18a2 2 0 0 0 2-1.9Z" /><Circle cx={7} cy={10} r={.7} /><Circle cx={10} cy={6.5} r={.7} /><Circle cx={15} cy={7} r={.7} /></> : null}
    {name === 'tools' ? <><Path d="M3 6h6m4 0h8M3 12h12m4 0h2M3 18h2m4 0h12M9 3v6m6 0v6M5 15v6" /></> : null}
    {name === 'story' ? <><Path d="M12 5v15M3 4h5a4 4 0 0 1 4 2 4 4 0 0 1 4-2h5v15h-5a4 4 0 0 0-4 2 4 4 0 0 0-4-2H3Z" /></> : null}
    {name === 'camera' ? <><Path d="M8 5 6 8H3v12h18V8h-3l-2-3Z" /><Circle cx={12} cy={13.5} r={3.5} /></> : null}
    {name === 'send' ? <Path d="M12 20V4m-6 6 6-6 6 6" /> : null}
    {name === 'paper-plane' ? <Path d="m3 10 18-7-7 18-3-8-8-3Zm8 3L21 3" /> : null}
    {name === 'live' ? <><Circle cx={12} cy={12} r={1.5} /><Path d="M8 8a6 6 0 0 0 0 8m8-8a6 6 0 0 1 0 8M4.5 4.5a10.6 10.6 0 0 0 0 15m15-15a10.6 10.6 0 0 1 0 15" /></> : null}
    {name === 'exit' ? <Path d="M10 4H4v16h6m-1-8h12m-4-4 4 4-4 4" /> : null}
  </Svg>;
}
