export type NarrationPace = 'original' | 'storyteller';

export function normalizeNarrationPace(value: unknown): NarrationPace {
  return value === 'storyteller' ? value : 'original';
}

export function narrationProfile(value: unknown) {
  return normalizeNarrationPace(value) === 'storyteller'
    ? { rate: 1, sentencePauseMs: 280, clausePauseMs: 160 }
    : { rate: 1, sentencePauseMs: 0, clausePauseMs: 0 };
}

export function endsNarrationSentence(text: string | undefined): boolean {
  // TTS chunks can end mid-sentence. Only punctuation followed by closing
  // quotes/formatting or emotion tags earns an extra breath.
  return /[.!?…。！？][\s"'”’»)\]}*_]*$/u.test((text || '').replace(/\[[^\]\r\n]{0,80}\]/g, ''));
}

export function narrationPauseMs(value: unknown, text: string | undefined): number {
  const profile = narrationProfile(value);
  if (endsNarrationSentence(text)) return profile.sentencePauseMs;
  const clean = (text || '').replace(/\[[^\]\r\n]{0,80}\]/g, '');
  return /[,;:，；：—–][\s"'”’»)\]}*_]*$/u.test(clean) || /\s--?\s*$/u.test(clean)
    ? profile.clausePauseMs : 0;
}
