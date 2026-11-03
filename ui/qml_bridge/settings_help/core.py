"""Reviewed core/schema and chat-provider presentation help."""

HELP: dict[str,str] = {'sensory_feedback_source': 'Source used for background sensory checks. Off stops these ambient '
                            'checks; choose Screen, Webcam, or Clipboard to use that configured '
                            'source. Explicit capture actions remain separate.',
 'sensory_feedback_interval_seconds': 'Minimum interval in seconds between eligible background '
                                      'sensory checks. Shorter intervals can increase capture and '
                                      'model-request work; the sensory policy still decides '
                                      'whether a check may run.',
 'sensory_pingpong_enabled': 'Allow bounded follow-up sensory dialogue between checks. Off '
                             'prevents this follow-up loop; normal user messages and explicit '
                             'captures remain available.',
 'sensory_pingpong_history_depth': 'Number of previous sensory turns considered by the follow-up '
                                   'policy. Larger histories retain more sensory context and can '
                                   'increase request size.',
 'sensory_allow_hidden_proactive_speech': 'Allow a hidden sensory-awareness cycle to produce '
                                          'audible speech when the sensory policy permits it. Off '
                                          'keeps hidden checks from reaching normal speech '
                                          'playback.',
 'sensory_allow_hidden_visual_generation': 'Allow a hidden sensory-awareness cycle to request a '
                                           'generated image through Visual Reply. Enabling this '
                                           'can start image-generation work without a typed chat '
                                           'request.',
 'screen_source_capture_screen_index': 'Monitor captured by Screen Source. Select a screen from '
                                       'the currently available displays; this is separate from '
                                       'the window on which NC is displayed.',
 'screen_source_auto_attach_next_user_turn': 'Queue a fresh Screen Source image for the next user '
                                             'message when this attachment path is used. This does '
                                             'not enable continuous screen capture.',
 'chat_context_window_messages': 'Recent messages available to each new normal-chat model request. '
                                 'The minimum effective value is 4; 0 uses the default of 20. A '
                                 'Persona override has its own limit, where 0 can mean all '
                                 'messages. Saved history is not deleted by this setting.',
 'chat_context_overflow_policy': 'Rolling window sends the most recent messages within the context '
                                 'limit. In this build the Keep all choice falls back to '
                                 'rolling-window behavior, so it does not increase the request '
                                 'context. Saved chat history is separate.',
 'stored_chat_history_limit': 'Maximum messages retained in NC conversation history. 0 keeps '
                              'unlimited history. A positive limit can remove older messages from '
                              'the in-memory conversation; save important context before reducing '
                              'it.',
 'chat_visual_batch_size': 'Number of nearby conversation messages displayed in each visual batch '
                           'while scrolling. -1 displays all rows. This affects rendering and '
                           'memory use, not saved history or model context.',
 'chat_message_timestamps_enabled': 'Show the saved timestamp beside each conversation message. '
                                    'This changes display only and does not alter the message '
                                    'content.',
 'spellcheck_enabled': 'Underline potential spelling mistakes in supported writing fields and '
                       'offer suggestions in their context menus. This does not automatically '
                       'rewrite your text.',
 'spellcheck_language': 'Dictionary language code used by the spelling checker, such as en_US. A '
                        'dictionary must be available for that language; this does not set the '
                        'chat or speech-recognition language.',
 'limit_response_length': 'Apply the configured response token limit to new model requests where '
                          'the provider supports it. Off leaves response length to the provider '
                          'and its other generation settings.',
 'max_response_tokens': 'Maximum generated tokens requested when Limit response length is enabled. '
                        'Tokens are pieces of text, not words; lower limits can truncate replies. '
                        'Applies to new requests.',
 'allow_proactive_replies': 'Allow NC to start a reply after its configured idle conditions are '
                            'met. Off waits for normal user-triggered replies; enabling this can '
                            'generate model requests while you are quiet.',
 'require_first_user_before_proactive': 'Require a user message before proactive replies are '
                                        'eligible in a conversation. Turning it off allows '
                                        'proactive timing before the first user message when '
                                        'proactive replies are enabled.',
 'listen_idle_window_seconds': 'Seconds of listening inactivity used by the idle policy before '
                               'proactive timing becomes eligible. This is separate from the '
                               'additional proactive delay.',
 'proactive_delay_seconds': 'Additional quiet-time delay in seconds before an eligible proactive '
                            'reply. Longer delays reduce how quickly NC speaks without a new user '
                            'message; proactive replies must also be enabled.',
 'visual_reply_story_mode': 'Allow story replies to request images through the active Visual Reply '
                            'provider. Requires a configured image provider and can create '
                            'additional image-generation requests.',
 'visual_reply_story_max_images': 'Maximum number of images allowed for a story reply. Larger '
                                  'limits can increase image-generation time and provider cost.',
 'visual_reply_story_continuity_strength': 'Influence of prior story visuals on later images, from '
                                           '0 to 1. Higher values favor visual continuity when '
                                           'supported by the image-generation path.',
 'visual_reply_master_prompt_safe': 'Include the story image prompt safety instructions when '
                                    'assembling the master visual prompt. This is prompt guidance, '
                                    'not a guarantee about the generated image.',
 'visual_reply_master_prompt_no_speech_bubbles': 'Ask the image model to avoid speech bubbles in '
                                                 'story images. This adds prompt instructions and '
                                                 'depends on the image model following them.',
 'visual_reply_master_style_prompt': 'Reusable visual style text appended when assembling '
                                     'story-image prompts. Use it for a consistent art style '
                                     'across future story images.',
 'chat_provider:lmstudio_sdk.base_url': 'Address of the LM Studio SDK server, normally '
                                      'http://127.0.0.1:1234. Use a plain http host and port; '
                                      'HTTPS, embedded credentials and custom paths are not '
                                      'supported. Changes apply to new requests.',
 'chat_provider:lmstudio_sdk.context_length': 'Tokens allocated when NC prepares the model. '
                                            '0 reuses a loaded model\'s context or NC\'s load-profile '
                                            'default. Nonzero values start at 512. Compatible '
                                            'loaded models are reused; changing the allocation '
                                            'can reload the selected model.',
 'chat_provider:lmstudio_sdk.temperature': 'Sampling randomness for new replies. Lower values '
                                         'favor predictable output; higher values allow more '
                                         'variation. NC sends this setting through the Python SDK.',
 'chat_provider:lmstudio_sdk.top_p': 'Cumulative probability retained for token sampling. '
                                   'Lower values narrow the candidate pool; 1 leaves this '
                                   'filter unrestricted. NC sends this setting through the Python SDK.',
 'chat_provider:lmstudio_sdk.top_k': 'Limits sampling to the highest-scoring tokens. Smaller '
                                   'positive values narrow the candidate pool; 1 keeps only '
                                   'the most likely token. NC sends this setting through the Python SDK.',
 'chat_provider:lmstudio_sdk.repeat_penalty': 'Penalty for repeated tokens. 1 is neutral; '
                                            'larger values discourage repetition. Extreme '
                                            'values can reduce coherence. Applied through the Python SDK.',
 'chat_provider:lmstudio_sdk.min_p': 'Minimum token probability relative to the most likely '
                                   'token. 0 disables this filter; higher values remove more '
                                   'unlikely candidates. Applied through the Python SDK.',
 'chat_provider:lmstudio_sdk.max_tokens': 'Maximum tokens generated for a reply. -1 means no '
                                        'explicit output cap. Input and output still share '
                                        'the model\'s context window, so a long prompt leaves '
                                        'less room for the reply.',
 'chat_provider:lmstudio_sdk.reasoning': 'Enable or disable thinking for new replies. Shown '
                                       'only when the model reports both on and off support. '
                                       'The requested mode is verified against LM Studio; '
                                       'reasoning text stays out of the visible answer and speech.',
 'chat_provider:lmstudio.base_url': 'Server address used by this language-model connection. Use '
                                    'the endpoint expected by this provider. Changes affect new '
                                    'requests; they do not move or download a model.',
 'chat_provider:lmstudio.api_key': 'API credential used to authenticate requests on this '
                                   'language-model connection. It is stored as a secret setting; '
                                   'remote providers may charge for requests made with it.',
 'chat_provider:lmstudio.context_length': 'Tokens allocated when NC next prepares this provider '
                                          'model. Larger contexts need more memory and changing '
                                          'this can reload the model. Use a value supported by the '
                                          'model and available hardware.',
 'chat_provider:lmstudio.anthropic_version': 'Anthropic API version header sent by the Claude '
                                             'connection. Use a version accepted by your endpoint; '
                                             'this is an API contract version, not the selected '
                                             'Claude model.',
 'chat_provider:lmstudio.temperature': 'Sampling randomness for new replies. Lower values favor '
                                       'more predictable wording; higher values allow more '
                                       'variation. The selected provider and model determine the '
                                       'accepted range.',
 'chat_provider:lmstudio.top_p': 'Probability mass retained for sampling the next token. Lower '
                                 'values narrow the candidate pool; 1 keeps the full supported '
                                 'pool. Applies to new replies where the model supports it.',
 'chat_provider:lmstudio.top_k': 'Number of the highest-scoring next-token candidates retained by '
                                 'supported models. Smaller positive values narrow sampling. '
                                 "Provider-specific special values follow that backend's sampling "
                                 'behavior.',
 'chat_provider:lmstudio.repeat_penalty': 'Penalty applied by supported models to repeated tokens. '
                                          '1 leaves repetition unpenalized; larger values '
                                          'discourage repeats but can make wording less natural. '
                                          'Applies to new replies.',
 'chat_provider:lmstudio.min_p': 'Minimum relative probability for a token to remain a sampling '
                                 'candidate on supported models. Higher values discard more '
                                 'unlikely continuations; 0 disables this filter where the backend '
                                 'supports it.',
 'chat_provider:lmstudio.frequency_penalty': 'Discourage tokens in proportion to how often they '
                                             'have already appeared. Positive values reduce '
                                             'repeated wording; 0 adds no frequency penalty. '
                                             'Applies to new replies on supported providers.',
 'chat_provider:lmstudio.presence_penalty': 'Discourage tokens that have already appeared, '
                                            'regardless of their frequency. Positive values '
                                            'encourage new wording or topics; 0 adds no presence '
                                            'penalty. Applies to new replies.',
 'chat_provider:lmstudio.max_tokens': 'Upper token limit for a generated reply. -1 omits this '
                                      'request limit where supported and lets the provider choose '
                                      'its cap. Short limits can stop a reply before it is '
                                      'complete.',
 'chat_provider:lmstudio.thinking_mode': 'Choose whether supported DeepSeek models use their '
                                         'thinking mode for new replies. Thinking can increase '
                                         'generation time and token use; the selected model must '
                                         'support the option.',
 'chat_provider:lmstudio.reasoning_effort': 'Reasoning effort requested for new DeepSeek replies. '
                                            'Default leaves the value unspecified for the '
                                            'provider; High and Max request additional reasoning '
                                            'work and can take longer.',
 'chat_provider:lmstudio.reasoning': 'Request the reasoning option supported by the selected LM '
                                     'Studio model. Shown only when the server reports both public '
                                     'on and off choices; applies to new replies.',
 'chat_provider:ollama.base_url': 'Server address used by this language-model connection. Use the '
                                  'endpoint expected by this provider. Changes affect new '
                                  'requests; they do not move or download a model.',
 'chat_provider:ollama.api_key': 'Compatibility credential for this Ollama connection. A standard '
                                 'local Ollama server does not require a real API key; the dummy '
                                 'value satisfies compatible client interfaces.',
 'chat_provider:ollama.context_length': 'Tokens allocated when NC next prepares this provider '
                                        'model. Larger contexts need more memory and changing this '
                                        'can reload the model. Use a value supported by the model '
                                        'and available hardware.',
 'chat_provider:ollama.anthropic_version': 'Anthropic API version header sent by the Claude '
                                           'connection. Use a version accepted by your endpoint; '
                                           'this is an API contract version, not the selected '
                                           'Claude model.',
 'chat_provider:ollama.temperature': 'Sampling randomness for new replies. Lower values favor more '
                                     'predictable wording; higher values allow more variation. The '
                                     'selected provider and model determine the accepted range.',
 'chat_provider:ollama.top_p': 'Probability mass retained for sampling the next token. Lower '
                               'values narrow the candidate pool; 1 keeps the full supported pool. '
                               'Applies to new replies where the model supports it.',
 'chat_provider:ollama.top_k': 'Number of the highest-scoring next-token candidates retained by '
                               'supported models. Smaller positive values narrow sampling. '
                               "Provider-specific special values follow that backend's sampling "
                               'behavior.',
 'chat_provider:ollama.repeat_penalty': 'Penalty applied by supported models to repeated tokens. 1 '
                                        'leaves repetition unpenalized; larger values discourage '
                                        'repeats but can make wording less natural. Applies to new '
                                        'replies.',
 'chat_provider:ollama.min_p': 'Minimum relative probability for a token to remain a sampling '
                               'candidate on supported models. Higher values discard more unlikely '
                               'continuations; 0 disables this filter where the backend supports '
                               'it.',
 'chat_provider:ollama.frequency_penalty': 'Discourage tokens in proportion to how often they have '
                                           'already appeared. Positive values reduce repeated '
                                           'wording; 0 adds no frequency penalty. Applies to new '
                                           'replies on supported providers.',
 'chat_provider:ollama.presence_penalty': 'Discourage tokens that have already appeared, '
                                          'regardless of their frequency. Positive values '
                                          'encourage new wording or topics; 0 adds no presence '
                                          'penalty. Applies to new replies.',
 'chat_provider:ollama.max_tokens': 'Upper token limit for a generated reply. -1 omits this '
                                    'request limit where supported and lets the provider choose '
                                    'its cap. Short limits can stop a reply before it is complete.',
 'chat_provider:ollama.thinking_mode': 'Choose whether supported DeepSeek models use their '
                                       'thinking mode for new replies. Thinking can increase '
                                       'generation time and token use; the selected model must '
                                       'support the option.',
 'chat_provider:ollama.reasoning_effort': 'Reasoning effort requested for new DeepSeek replies. '
                                          'Default leaves the value unspecified for the provider; '
                                          'High and Max request additional reasoning work and can '
                                          'take longer.',
 'chat_provider:ollama.reasoning': 'Request thinking on supported Ollama models for new replies. '
                                   'On sends reasoning_effort=medium; Off sends '
                                   'reasoning_effort=none. Available only when the model reports '
                                   'thinking support.',
 'chat_provider:openai.base_url': 'Server address used by this language-model connection. Use the '
                                  'endpoint expected by this provider. Changes affect new '
                                  'requests; they do not move or download a model.',
 'chat_provider:openai.api_key': 'API credential used to authenticate requests on this '
                                 'language-model connection. It is stored as a secret setting; '
                                 'remote providers may charge for requests made with it.',
 'chat_provider:openai.context_length': 'Tokens allocated when NC next prepares this provider '
                                        'model. Larger contexts need more memory and changing this '
                                        'can reload the model. Use a value supported by the model '
                                        'and available hardware.',
 'chat_provider:openai.anthropic_version': 'Anthropic API version header sent by the Claude '
                                           'connection. Use a version accepted by your endpoint; '
                                           'this is an API contract version, not the selected '
                                           'Claude model.',
 'chat_provider:openai.temperature': 'Sampling randomness for new replies. Lower values favor more '
                                     'predictable wording; higher values allow more variation. The '
                                     'selected provider and model determine the accepted range.',
 'chat_provider:openai.top_p': 'Probability mass retained for sampling the next token. Lower '
                               'values narrow the candidate pool; 1 keeps the full supported pool. '
                               'Applies to new replies where the model supports it.',
 'chat_provider:openai.top_k': 'Number of the highest-scoring next-token candidates retained by '
                               'supported models. Smaller positive values narrow sampling. '
                               "Provider-specific special values follow that backend's sampling "
                               'behavior.',
 'chat_provider:openai.repeat_penalty': 'Penalty applied by supported models to repeated tokens. 1 '
                                        'leaves repetition unpenalized; larger values discourage '
                                        'repeats but can make wording less natural. Applies to new '
                                        'replies.',
 'chat_provider:openai.min_p': 'Minimum relative probability for a token to remain a sampling '
                               'candidate on supported models. Higher values discard more unlikely '
                               'continuations; 0 disables this filter where the backend supports '
                               'it.',
 'chat_provider:openai.frequency_penalty': 'Discourage tokens in proportion to how often they have '
                                           'already appeared. Positive values reduce repeated '
                                           'wording; 0 adds no frequency penalty. Applies to new '
                                           'replies on supported providers.',
 'chat_provider:openai.presence_penalty': 'Discourage tokens that have already appeared, '
                                          'regardless of their frequency. Positive values '
                                          'encourage new wording or topics; 0 adds no presence '
                                          'penalty. Applies to new replies.',
 'chat_provider:openai.max_tokens': 'Upper token limit for a generated reply. -1 omits this '
                                    'request limit where supported and lets the provider choose '
                                    'its cap. Short limits can stop a reply before it is complete.',
 'chat_provider:openai.thinking_mode': 'Choose whether supported DeepSeek models use their '
                                       'thinking mode for new replies. Thinking can increase '
                                       'generation time and token use; the selected model must '
                                       'support the option.',
 'chat_provider:openai.reasoning_effort': 'Reasoning effort requested for new DeepSeek replies. '
                                          'Default leaves the value unspecified for the provider; '
                                          'High and Max request additional reasoning work and can '
                                          'take longer.',
 'chat_provider:openai.reasoning': 'Request supported model reasoning on new replies. Availability '
                                   'and the request values depend on this connection and the '
                                   'selected model.',
 'chat_provider:deepseek.base_url': 'Server address used by this language-model connection. Use '
                                    'the endpoint expected by this provider. Changes affect new '
                                    'requests; they do not move or download a model.',
 'chat_provider:deepseek.api_key': 'API credential used to authenticate requests on this '
                                   'language-model connection. It is stored as a secret setting; '
                                   'remote providers may charge for requests made with it.',
 'chat_provider:deepseek.context_length': 'Tokens allocated when NC next prepares this provider '
                                          'model. Larger contexts need more memory and changing '
                                          'this can reload the model. Use a value supported by the '
                                          'model and available hardware.',
 'chat_provider:deepseek.anthropic_version': 'Anthropic API version header sent by the Claude '
                                             'connection. Use a version accepted by your endpoint; '
                                             'this is an API contract version, not the selected '
                                             'Claude model.',
 'chat_provider:deepseek.temperature': 'Sampling randomness for new replies. Lower values favor '
                                       'more predictable wording; higher values allow more '
                                       'variation. The selected provider and model determine the '
                                       'accepted range.',
 'chat_provider:deepseek.top_p': 'Probability mass retained for sampling the next token. Lower '
                                 'values narrow the candidate pool; 1 keeps the full supported '
                                 'pool. Applies to new replies where the model supports it.',
 'chat_provider:deepseek.top_k': 'Number of the highest-scoring next-token candidates retained by '
                                 'supported models. Smaller positive values narrow sampling. '
                                 "Provider-specific special values follow that backend's sampling "
                                 'behavior.',
 'chat_provider:deepseek.repeat_penalty': 'Penalty applied by supported models to repeated tokens. '
                                          '1 leaves repetition unpenalized; larger values '
                                          'discourage repeats but can make wording less natural. '
                                          'Applies to new replies.',
 'chat_provider:deepseek.min_p': 'Minimum relative probability for a token to remain a sampling '
                                 'candidate on supported models. Higher values discard more '
                                 'unlikely continuations; 0 disables this filter where the backend '
                                 'supports it.',
 'chat_provider:deepseek.frequency_penalty': 'Discourage tokens in proportion to how often they '
                                             'have already appeared. Positive values reduce '
                                             'repeated wording; 0 adds no frequency penalty. '
                                             'Applies to new replies on supported providers.',
 'chat_provider:deepseek.presence_penalty': 'Discourage tokens that have already appeared, '
                                            'regardless of their frequency. Positive values '
                                            'encourage new wording or topics; 0 adds no presence '
                                            'penalty. Applies to new replies.',
 'chat_provider:deepseek.max_tokens': 'Upper token limit for a generated reply. -1 omits this '
                                      'request limit where supported and lets the provider choose '
                                      'its cap. Short limits can stop a reply before it is '
                                      'complete.',
 'chat_provider:deepseek.thinking_mode': 'Choose whether supported DeepSeek models use their '
                                         'thinking mode for new replies. Thinking can increase '
                                         'generation time and token use; the selected model must '
                                         'support the option.',
 'chat_provider:deepseek.reasoning_effort': 'Reasoning effort requested for new DeepSeek replies. '
                                            'Default leaves the value unspecified for the '
                                            'provider; High and Max request additional reasoning '
                                            'work and can take longer.',
 'chat_provider:deepseek.reasoning': 'Request supported model reasoning on new replies. '
                                     'Availability and the request values depend on this '
                                     'connection and the selected model.',
 'chat_provider:claude.base_url': 'Server address used by this language-model connection. Use the '
                                  'endpoint expected by this provider. Changes affect new '
                                  'requests; they do not move or download a model.',
 'chat_provider:claude.api_key': 'API credential used to authenticate requests on this '
                                 'language-model connection. It is stored as a secret setting; '
                                 'remote providers may charge for requests made with it.',
 'chat_provider:claude.context_length': 'Tokens allocated when NC next prepares this provider '
                                        'model. Larger contexts need more memory and changing this '
                                        'can reload the model. Use a value supported by the model '
                                        'and available hardware.',
 'chat_provider:claude.anthropic_version': 'Anthropic API version header sent by the Claude '
                                           'connection. Use a version accepted by your endpoint; '
                                           'this is an API contract version, not the selected '
                                           'Claude model.',
 'chat_provider:claude.temperature': 'Randomness for new Claude replies. Lower values favor '
                                     'predictable wording. NC exposes Temperature without Top P by '
                                     'default because Claude rejects requests that set both.',
 'chat_provider:claude.top_p': 'Probability mass retained for sampling the next token. Lower '
                               'values narrow the candidate pool; 1 keeps the full supported pool. '
                               'Applies to new replies where the model supports it.',
 'chat_provider:claude.top_k': 'Number of the highest-scoring next-token candidates retained by '
                               'supported models. Smaller positive values narrow sampling. '
                               "Provider-specific special values follow that backend's sampling "
                               'behavior.',
 'chat_provider:claude.repeat_penalty': 'Penalty applied by supported models to repeated tokens. 1 '
                                        'leaves repetition unpenalized; larger values discourage '
                                        'repeats but can make wording less natural. Applies to new '
                                        'replies.',
 'chat_provider:claude.min_p': 'Minimum relative probability for a token to remain a sampling '
                               'candidate on supported models. Higher values discard more unlikely '
                               'continuations; 0 disables this filter where the backend supports '
                               'it.',
 'chat_provider:claude.frequency_penalty': 'Discourage tokens in proportion to how often they have '
                                           'already appeared. Positive values reduce repeated '
                                           'wording; 0 adds no frequency penalty. Applies to new '
                                           'replies on supported providers.',
 'chat_provider:claude.presence_penalty': 'Discourage tokens that have already appeared, '
                                          'regardless of their frequency. Positive values '
                                          'encourage new wording or topics; 0 adds no presence '
                                          'penalty. Applies to new replies.',
 'chat_provider:claude.max_tokens': 'Maximum tokens generated for one new Claude reply. Claude '
                                    'requires a positive cap. Higher limits can increase response '
                                    'time and API usage; lower limits can stop a reply early.',
 'chat_provider:claude.thinking_mode': 'Choose whether supported DeepSeek models use their '
                                       'thinking mode for new replies. Thinking can increase '
                                       'generation time and token use; the selected model must '
                                       'support the option.',
 'chat_provider:claude.reasoning_effort': 'Reasoning effort requested for new DeepSeek replies. '
                                          'Default leaves the value unspecified for the provider; '
                                          'High and Max request additional reasoning work and can '
                                          'take longer.',
 'chat_provider:claude.reasoning': 'Request supported model reasoning on new replies. Availability '
                                   'and the request values depend on this connection and the '
                                   'selected model.',
 'stt.model_size': 'Speech-recognition model for this input provider. Larger models generally need '
                   'more memory and processing time. This choice is saved separately per provider '
                   'and is used when its recognizer loads.',
 'stt.language': 'Spoken language for this recognition provider. Auto Detect lets the multilingual '
                 'recognizer infer it; selecting a language pins recognition to that language. '
                 'This does not change the reply language.',
 'chat_provider:xai.api_key': 'API credential used to authenticate requests on this language-model '
                              'connection. It is stored as a secret setting; remote providers may '
                              'charge for requests made with it.',
 'chat_provider:xai.base_url': 'Server address used by this language-model connection. Use the '
                               'endpoint expected by this provider. Changes affect new requests; '
                               'they do not move or download a model.',
 'chat_provider:xai.temperature': 'Sampling randomness for new replies. Lower values favor more '
                                  'predictable wording; higher values allow more variation. The '
                                  'selected provider and model determine the accepted range.',
 'chat_provider:xai.top_p': 'Probability mass retained for sampling the next token. Lower values '
                            'narrow the candidate pool; 1 keeps the full supported pool. Applies '
                            'to new replies where the model supports it.'}


def help_for(control_id: str, surface_id: str = "") -> str:
    return HELP.get(f"{surface_id}.{control_id}", HELP.get(control_id, ""))
