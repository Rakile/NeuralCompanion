import type { ChatMessage, RemoteState } from '../api/types';

const DEMO_STARTED_AT = 1781892000;

function cloneState(state: RemoteState): RemoteState {
  return JSON.parse(JSON.stringify(state)) as RemoteState;
}

function message(index: number, role: string, content: string): ChatMessage {
  return {
    id: `demo_chat_${index}`,
    index,
    role,
    content,
    created_at: DEMO_STARTED_AT + index * 12,
  };
}

export function createInitialDemoRemoteState(): RemoteState {
  return {
    status_line: 'Demo mode: offline phone app tour',
    runtime_status: {
      lifecycle_state: 'demo',
      running: true,
      engine_connected: true,
      chat_provider: 'LM Studio',
      model_name: 'story-demo-model',
      tts_backend: 'Chatterbox',
      avatar_engine: 'MuseTalk',
      microphone_state: 'phone demo',
    },
    runtime_settings: {
      chat_provider: 'LM Studio',
      model_name: 'story-demo-model',
      stt_backend: 'Whisper English',
      stt_model_size: 'tiny',
      tts_backend: 'Chatterbox',
      visual_reply_provider: 'Runware',
    },
    engine: {
      running: true,
      engine_connected: true,
      lifecycle_state: 'demo',
    },
    controls: {
      actions: ['pause_speech', 'skip_speech', 'regenerate_response', 'replay_last_assistant'],
      last_action: '',
    },
    chat: {
      message_count: 4,
      messages: [
        message(0, 'system', 'Demo mode is running locally on the phone. No LAN backend is required.'),
        message(1, 'user', 'Start the scene at the old signal tower.'),
        message(2, 'assistant', 'Mara checks the rusted ladder while Nox listens to the storm in the wires. The tower answers with one clean pulse of blue light.'),
        message(3, 'assistant', 'Visual Reply prepared a night-rain scene and MuseTalk is animating a phone preview avatar.'),
      ],
    },
    media: {
      available: true,
      status: 'demo voice queue',
      generation: 2,
      backend_playback_suppressed: true,
      items: [
        {
          id: 'demo_audio_narrator',
          url_path: '',
          index: 0,
          speaker: 'Narrator',
          text: 'Rain moves over the tower like static.',
          duration_seconds: 3.2,
          content_type: 'audio/wav',
          created_at: DEMO_STARTED_AT + 50,
        },
        {
          id: 'demo_audio_mara',
          url_path: '',
          index: 1,
          speaker: 'Mara',
          text: 'If it answers again, we climb.',
          duration_seconds: 2.4,
          content_type: 'audio/wav',
          created_at: DEMO_STARTED_AT + 55,
        },
      ],
    },
    visual: {
      service_available: true,
      state: {
        status: 'demo visual ready',
        image_url_path: '',
        image_cache_key: 'demo_visual_1',
        image_content_type: 'image/demo',
        caption: 'Storm-lit signal tower with Mara and Nox in the foreground.',
        updated_at: DEMO_STARTED_AT + 60,
      },
      settings: {
        provider_label: 'Runware',
        mode_value: 'demo',
      },
      requests: [
        {
          request_id: 'demo_visual_request',
          status: 'ready',
          accepted: true,
          message: 'Demo Visual Reply is ready.',
          prompt_preview: 'Visual Reply beat: storm-lit signal tower, wet metal, blue pulse, tense but curious mood.',
          image_available: true,
          created_at: DEMO_STARTED_AT + 60,
          updated_at: DEMO_STARTED_AT + 60,
        },
      ],
      latest_request: {
        request_id: 'demo_visual_request',
        status: 'ready',
        accepted: true,
        message: 'Demo Visual Reply is ready.',
        prompt_preview: 'Visual Reply beat: storm-lit signal tower, wet metal, blue pulse, tense but curious mood.',
        image_available: true,
      },
    },
    musetalk: {
      available: true,
      state: {
        status: 'demo avatar animating',
        frame_url_path: '',
        stream_url_path: '',
        text: 'Mara: If it answers again, we climb.',
        fps: 12,
        chunk_id: 'demo_audio_mara',
        preview_frame_index: 0,
        updated_at: DEMO_STARTED_AT + 65,
      },
      frames: [
        { id: 'demo_frame_0', url_path: '', index: 0, content_type: 'demo/avatar' },
        { id: 'demo_frame_1', url_path: '', index: 1, content_type: 'demo/avatar' },
        { id: 'demo_frame_2', url_path: '', index: 2, content_type: 'demo/avatar' },
      ],
      feed: [
        { _seq: 0, frame_url_path: '', status: 'demo avatar idle', frame_index: 0 },
        { _seq: 1, frame_url_path: '', status: 'demo avatar speaking', frame_index: 1 },
        { _seq: 2, frame_url_path: '', status: 'demo avatar blink', frame_index: 2 },
      ],
      pipeline: {
        active: true,
        stream_mode: 'demo',
      },
      stream_url_path: '',
    },
    mprc: {
      available: true,
      message: 'Demo story mode is available.',
      schema_version: 1,
      remote: {
        demo: true,
      },
      session: {
        enabled: true,
        mode: 'Story Play',
        turn_index: 7,
        active_persona_id: 'mara',
        current_speaker_id: 'mara',
        scene_title: 'The Signal Tower',
        location: 'A rain-slick relay tower above the harbor',
        time_of_day: 'After midnight',
        mood: 'Tense, curious, cinematic',
        objective: 'Decide whether to climb the tower before the next signal pulse.',
        scene_summary: 'Mara and Nox found an old tower broadcasting a repeating blue pulse.',
      },
      personas: [
        {
          id: 'narrator',
          display_name: 'Narrator',
          role: 'Scene Director',
          enabled: true,
          active: true,
          narrator: true,
          description: 'Keeps the story moving with clear scene beats.',
          visual_enabled: true,
          voice_enabled: true,
        },
        {
          id: 'mara',
          display_name: 'Mara',
          role: 'Scout',
          enabled: true,
          active: true,
          current_speaker: true,
          description: 'Practical, brave, careful with danger.',
          visual_enabled: true,
          voice_enabled: true,
        },
        {
          id: 'nox',
          display_name: 'Nox',
          role: 'Signal Reader',
          enabled: true,
          active: true,
          description: 'Soft-spoken and sharp with old machines.',
          visual_enabled: true,
          voice_enabled: true,
        },
      ],
      latest_reply: 'Mara checks the ladder while Nox watches the signal pulse travel through the rain.',
      segments: [
        {
          segment_id: 'demo_seg_0',
          speaker_id: 'narrator',
          speaker_name: 'Narrator',
          role: 'narrator',
          text: 'Rain needles across the metal tower. Far below, the harbor lights smear into gold lines.',
        },
        {
          segment_id: 'demo_seg_1',
          speaker_id: 'mara',
          speaker_name: 'Mara',
          role: 'character',
          text: 'If it answers again, we climb. If it screams, we run.',
        },
        {
          segment_id: 'demo_seg_2',
          speaker_id: 'nox',
          speaker_name: 'Nox',
          role: 'character',
          text: 'It is not screaming. It is counting down.',
        },
      ],
      choices: [
        { id: 'climb', text: 'Climb toward the blue signal.' },
        { id: 'scan', text: 'Let Nox scan the pulse first.' },
        { id: 'retreat', text: 'Retreat and watch the tower from cover.' },
      ],
      speech_audio: {
        available: true,
        status: 'demo multi-voice chunks',
        generation: 2,
        backend_playback_suppressed: true,
        items: [
          {
            id: 'demo_story_audio_0',
            url_path: '',
            index: 0,
            speaker: 'Narrator',
            text: 'Rain needles across the metal tower.',
            duration_seconds: 3.2,
            content_type: 'audio/wav',
          },
          {
            id: 'demo_story_audio_1',
            url_path: '',
            index: 1,
            speaker: 'Mara',
            text: 'If it answers again, we climb.',
            duration_seconds: 2.4,
            content_type: 'audio/wav',
          },
          {
            id: 'demo_story_audio_2',
            url_path: '',
            index: 2,
            speaker: 'Nox',
            text: 'It is counting down.',
            duration_seconds: 2.1,
            content_type: 'audio/wav',
          },
        ],
      },
      audio_cues: [
        { type: 'ambient', label: 'light rain', intensity: 0.45 },
        { type: 'music', label: 'low suspense pulse', intensity: 0.35 },
      ],
      memory: {
        available: true,
        backend: 'SQLite',
        configured_backend: 'SQLite',
        database_available: true,
        database_status: 'ready',
        databank_available: true,
        configured_databank_source_count: 3,
        indexed_databank_source_count: 3,
        event_count: 14,
        chapter_count: 2,
        pinned_fact_count: 5,
        character_memory_count: 8,
        location_memory_count: 4,
      },
      cast: {
        available: true,
        devices: [
          {
            name: 'Living Room Cast',
            model_name: 'Demo Chromecast',
            host: '192.168.1.55',
            cast_type: 'screen',
          },
        ],
        selected_device: 'Living Room Cast',
        active_device: '',
        casting: false,
        busy: false,
        status: 'Demo Chromecast target ready.',
        stream: {
          running: true,
          url: 'http://demo.local/story-cast',
          port: 8788,
        },
      },
      visual: {
        latest_prompt: 'Visual Reply beat: storm-lit relay tower, Mara on the ladder, Nox reading a blue pulse, cinematic rain, tense curiosity.',
        last_visual_reply_at: DEMO_STARTED_AT + 60,
        auto_image_count: 1,
      },
    },
    features: {
      main_chat_text: true,
      runtime_status: true,
      tts_chunks: true,
      phone_stt: false,
      visual_reply: true,
      visual_reply_controls: true,
      musetalk_frame_feed: true,
      musetalk_frame_stream: true,
      mprc_story_mode: true,
    },
  };
}

export function advanceDemoMuseTalkFrame(state: RemoteState): RemoteState {
  const next = cloneState(state);
  const currentIndex = Number(next.musetalk?.state?.preview_frame_index ?? 0);
  const nextIndex = (currentIndex + 1) % 3;
  if (next.musetalk?.state) {
    next.musetalk.state.preview_frame_index = nextIndex;
    next.musetalk.state.updated_at = Date.now() / 1000;
    next.musetalk.state.status = nextIndex === 1 ? 'demo avatar speaking' : nextIndex === 2 ? 'demo avatar blink' : 'demo avatar listening';
  }
  if (next.musetalk?.feed) {
    next.musetalk.feed = [
      ...next.musetalk.feed.slice(-2),
      {
        _seq: Number(Date.now()),
        frame_url_path: '',
        status: next.musetalk?.state?.status || 'demo avatar animating',
        frame_index: nextIndex,
      },
    ];
  }
  return next;
}

export function appendDemoChatTurn(state: RemoteState, text: string): RemoteState {
  const trimmed = String(text || '').trim();
  if (!trimmed) {
    return state;
  }
  const next = cloneState(state);
  const messages = [...(next.chat?.messages ?? [])];
  const userIndex = messages.length;
  messages.push(message(userIndex, 'user', trimmed));
  messages.push(message(userIndex + 1, 'assistant', `Demo reply: I would send "${trimmed}" to Neural Companion when the LAN bridge is connected. In demo mode, the phone keeps the story preview local.`));
  next.chat = {
    message_count: messages.length,
    messages,
  };
  return next;
}

export function appendDemoStoryTurn(state: RemoteState, text: string, speakerId = ''): RemoteState {
  const trimmed = String(text || '').trim();
  if (!trimmed) {
    return state;
  }
  const next = cloneState(state);
  const persona = (next.mprc?.personas ?? []).find((item) => item.id === speakerId);
  const speakerName = persona?.display_name || 'User';
  const segments = [...(next.mprc?.segments ?? [])];
  segments.push({
    segment_id: `demo_seg_${segments.length}`,
    speaker_id: speakerId || 'user',
    speaker_name: speakerName,
    role: speakerId ? 'character' : 'user',
    text: trimmed,
  });
  segments.push({
    segment_id: `demo_seg_${segments.length + 1}`,
    speaker_id: 'narrator',
    speaker_name: 'Narrator',
    role: 'narrator',
    text: 'The tower answers with a second blue pulse, brighter than the first. The scene is ready for the next real LLM turn.',
  });
  if (next.mprc) {
    next.mprc.segments = segments.slice(-6);
    next.mprc.latest_reply = 'The tower answers with a second blue pulse, brighter than the first.';
    if (next.mprc.session) {
      next.mprc.session.turn_index = Number(next.mprc.session.turn_index ?? 0) + 1;
      next.mprc.session.current_speaker_id = speakerId || 'narrator';
    }
  }
  return next;
}

export function updateDemoVisualPrompt(state: RemoteState, prompt: string): RemoteState {
  const trimmed = String(prompt || '').trim() || 'Visual Reply beat: storm-lit tower, blue signal pulse, cinematic rain.';
  const next = cloneState(state);
  const now = Date.now() / 1000;
  if (next.visual?.state) {
    next.visual.state.status = 'demo visual updated';
    next.visual.state.caption = trimmed;
    next.visual.state.image_cache_key = `demo_visual_${Math.round(now)}`;
    next.visual.state.updated_at = now;
  }
  if (next.visual) {
    next.visual.latest_request = {
      request_id: `demo_visual_${Math.round(now)}`,
      status: 'ready',
      accepted: true,
      message: 'Demo Visual Reply updated.',
      prompt_preview: trimmed,
      image_available: true,
      created_at: now,
      updated_at: now,
    };
  }
  if (next.mprc?.visual) {
    next.mprc.visual.latest_prompt = trimmed.includes('Visual Reply') ? trimmed : `Visual Reply beat: ${trimmed}`;
    next.mprc.visual.last_visual_reply_at = now;
    next.mprc.visual.auto_image_count = Number(next.mprc.visual.auto_image_count ?? 0) + 1;
  }
  return next;
}
