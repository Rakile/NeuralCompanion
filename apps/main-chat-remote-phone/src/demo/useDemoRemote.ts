import { useCallback, useEffect, useState } from 'react';

import type { MprcAction, MprcCastAction, MprcSendOptions, SendTextOptions, VisualAction } from '../api/client';
import type { RemoteState } from '../api/types';
import {
  advanceDemoMuseTalkFrame,
  appendDemoChatTurn,
  appendDemoStoryTurn,
  createInitialDemoRemoteState,
  updateDemoVisualPrompt,
} from './demoState';

const DEMO_FRAME_INTERVAL_MS = 850;

export function useDemoRemote(enabled: boolean) {
  const [state, setState] = useState<RemoteState>(() => createInitialDemoRemoteState());

  useEffect(() => {
    if (!enabled) {
      return undefined;
    }
    const timer = setInterval(() => {
      setState((current) => advanceDemoMuseTalkFrame(current));
    }, DEMO_FRAME_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [enabled]);

  const reset = useCallback(() => {
    setState(createInitialDemoRemoteState());
  }, []);

  const sendText = useCallback(async (text: string, _options: SendTextOptions = {}) => {
    setState((current) => appendDemoChatTurn(current, text));
  }, []);

  const sendControl = useCallback(async (action: string, _options: SendTextOptions = {}) => {
    setState((current) => ({
      ...current,
      controls: {
        ...(current.controls ?? {}),
        actions: current.controls?.actions ?? [],
        last_action: action,
      },
      status_line: `Demo control: ${action}`,
    }));
  }, []);

  const visualGenerate = useCallback(async (prompt: string) => {
    setState((current) => updateDemoVisualPrompt(current, prompt));
    return { ok: true, accepted: true, message: 'Demo Visual Reply updated.' };
  }, []);

  const visualAction = useCallback(async (action: VisualAction) => {
    setState((current) => {
      if (action === 'clear') {
        const next = updateDemoVisualPrompt(current, 'Visual Reply cleared in demo mode.');
        if (next.visual?.state) {
          next.visual.state.status = 'demo visual cleared';
          next.visual.state.caption = '';
        }
        return next;
      }
      if (action === 'generate_last') {
        return updateDemoVisualPrompt(current, current.mprc?.visual?.latest_prompt || 'Visual Reply demo scene.');
      }
      return {
        ...current,
        status_line: `Demo Visual Reply action: ${action}`,
      };
    });
    return { ok: true, accepted: true, message: `Demo Visual Reply action: ${action}` };
  }, []);

  const sendStoryText = useCallback(async (text: string, options: MprcSendOptions = {}) => {
    setState((current) => appendDemoStoryTurn(current, text, options.speakerId));
  }, []);

  const selectStoryChoice = useCallback(async (choice: string) => {
    setState((current) => appendDemoStoryTurn(current, choice, 'narrator'));
  }, []);

  const storyAction = useCallback(async (action: MprcAction) => {
    setState((current) => {
      if (action === 'visual') {
        return updateDemoVisualPrompt(current, current.mprc?.visual?.latest_prompt || 'Visual Reply demo scene.');
      }
      return {
        ...current,
        status_line: action === 'play' ? 'Demo story playback started.' : 'Demo story playback paused.',
        mprc: current.mprc ? {
          ...current.mprc,
          message: action === 'play' ? 'Demo story playback started.' : 'Demo story playback paused.',
        } : current.mprc,
      };
    });
  }, []);

  const storyCastAction = useCallback(async (action: MprcCastAction, deviceName = '') => {
    setState((current) => {
      const cast = current.mprc?.cast;
      if (!current.mprc || !cast) {
        return current;
      }
      const selectedDevice = deviceName || cast.selected_device || cast.active_device || 'Living Room Cast';
      const casting = action === 'start' ? true : action === 'stop' ? false : Boolean(cast.casting);
      const status = action === 'refresh'
        ? 'Demo Chromecast target refreshed.'
        : action === 'install'
          ? 'Demo cast dependencies are already available.'
          : casting
            ? `Demo casting to ${selectedDevice}.`
            : 'Demo Chromecast stopped.';
      return {
        ...current,
        mprc: {
          ...current.mprc,
          cast: {
            ...cast,
            selected_device: selectedDevice,
            active_device: casting ? selectedDevice : '',
            casting,
            busy: false,
            status,
          },
        },
      };
    });
  }, []);

  const clearAudio = useCallback(async () => {
    setState((current) => ({
      ...current,
      media: {
        ...(current.media ?? {}),
        items: [],
        status: 'demo queue cleared',
      },
    }));
  }, []);

  const startEngine = useCallback(async () => {
    setState((current) => ({
      ...current,
      engine: {
        ...(current.engine ?? {}),
        running: true,
        engine_connected: true,
        lifecycle_state: 'demo',
      },
      runtime_status: {
        ...(current.runtime_status ?? {}),
        running: true,
        engine_connected: true,
        lifecycle_state: 'demo',
      },
      status_line: 'Demo engine started.',
    }));
  }, []);

  const stopEngine = useCallback(async () => {
    setState((current) => ({
      ...current,
      engine: {
        ...(current.engine ?? {}),
        running: false,
        lifecycle_state: 'demo stopped',
      },
      runtime_status: {
        ...(current.runtime_status ?? {}),
        running: false,
        lifecycle_state: 'demo stopped',
      },
      status_line: 'Demo engine stopped.',
    }));
  }, []);

  return {
    state,
    reset,
    sendText,
    clearAudio,
    sendControl,
    visualGenerate,
    visualAction,
    sendStoryText,
    selectStoryChoice,
    storyAction,
    storyCastAction,
    startEngine,
    stopEngine,
  };
}
