export function shouldExitLiveFullscreen(input: {
  visible: boolean;
  demoMode: boolean;
  sessionActive: boolean;
}): boolean {
  return input.visible && !input.demoMode && !input.sessionActive;
}
