import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import type { StyleProp, TextLayoutEventData, TextStyle } from 'react-native';
import type { ChatReadingStyle } from '../hooks/usePhoneSettings';
import { useThemeColors } from '../styles/ThemeContext';
import type { ReadingCursor, ReadingLine } from '../utils/readingAlong';

export type HighlightLine = ReadingLine & {x: number; width: number};
type Fragment = {line: HighlightLine; prefix: string; through: string};

/** Keep native wrapping and exact text offsets, including repeated lines and split words. */
export function readingFragments(text: string, lines: readonly HighlightLine[], start: number, end: number): Fragment[] {
  const result: Fragment[] = [];
  let searchFrom = 0;
  for (const line of lines) {
    const value = line.text.replace(/[\r\n]+$/, '');
    if (!value) continue;
    const offset = text.indexOf(value, searchFrom);
    if (offset < 0 || text.slice(searchFrom, offset).trim()) return [];
    const limit = offset + value.length;
    if (start < limit && end > offset && [line.x,line.y,line.width,line.height].every(Number.isFinite)
      && line.width > 0 && line.height > 0) {
      result.push({line,prefix:value.slice(0, Math.max(0, start-offset)),through:value.slice(0, Math.min(value.length, end-offset))});
    }
    searchFrom = limit;
  }
  return result;
}

type Props = {cursor: ReadingCursor; lines: readonly HighlightLine[]; styleName: ChatReadingStyle; textStyle: StyleProp<TextStyle>};

/** Decoration only: the original selectable Text owns wrapping, gestures and scrolling. */
export function ReadingHighlight({cursor, lines, styleName, textStyle}: Props) {
  const colors = useThemeColors();
  // Soft focus glows on the native text itself; only Reading rail needs an overlay.
  if (styleName !== 'reading_rail') return null;
  const fragments = readingFragments(cursor.text, lines, cursor.start, cursor.end);
  return <View pointerEvents="none" accessible={false} accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={StyleSheet.absoluteFill}>
    {fragments.map(fragment => <React.Fragment key={`${fragment.line.y}:${fragment.line.text}`}>
        <View style={{position:'absolute',left:fragment.line.x-5,top:fragment.line.y+1,width:fragment.line.width+10,
          height:fragment.line.height-2,borderRadius:6,backgroundColor:`${colors.accent}0D`}} />
        <View style={{position:'absolute',left:fragment.line.x-9,top:fragment.line.y+3,width:2,
          height:Math.max(2,fragment.line.height-6),borderRadius:1,backgroundColor:colors.accent,opacity:.6}} />
      <WordHighlight fragment={fragment} textStyle={textStyle} />
    </React.Fragment>)}
  </View>;
}

export function WordHighlight({fragment, textStyle}: {fragment: Fragment; textStyle: StyleProp<TextStyle>}) {
  const colors = useThemeColors();
  const {line,prefix,through} = fragment;
  const key = JSON.stringify([prefix,through,textStyle,line.width,line.height]);
  const current = React.useRef(key); current.current = key;
  const [measured, setMeasured] = React.useState<{key:string; prefix:number|null; end:number|null}>({key:'',prefix:null,end:null});
  const receive = (part: 'prefix' | 'end', lines: TextLayoutEventData['lines']) => {
    const width = lines[0]?.width;
    if (current.current !== key || typeof width !== 'number' || !Number.isFinite(width) || width < 0) return;
    setMeasured(previous => previous.key === key && previous[part] === width ? previous
      : {...(previous.key === key ? previous : {key,prefix:null,end:null}),[part]:width});
  };
  const left = !prefix ? 0 : measured.key === key ? measured.prefix : null;
  const right = measured.key === key ? measured.end : null;
  // Prefix widths cannot describe bidirectional shaping. Keep the native current-word
  // colour in that case, rather than placing a guessed marker on an unrelated word.
  if (/[\u0590-\u08ff\u200e-\u200f\u202a-\u202e\u2066-\u2069]/u.test(line.text)) return null;
  return <>
    <Text accessible={false} numberOfLines={1} style={[textStyle,styles.measure]}
      onTextLayout={event => receive('prefix',event.nativeEvent.lines)}>{prefix}</Text>
    <Text accessible={false} numberOfLines={1} style={[textStyle,styles.measure]}
      onTextLayout={event => receive('end',event.nativeEvent.lines)}>{through}</Text>
    {left !== null && right !== null && right > left && right <= line.width+2 ? <View testID="reading-word-marker"
      style={[styles.marker,{left:line.x+(left+right)/2-1.5,top:line.y+line.height-3,width:3,height:3,borderRadius:2,backgroundColor:colors.accent}]} /> : null}
  </>;
}

const styles = StyleSheet.create({
  measure: {position:'absolute',left:0,top:0,width:'100%',opacity:0},
  marker: {position:'absolute'},
});
