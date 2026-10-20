# AI providers, roles and privacy

*[Deutsch](de/AI.md) · English*

Code: `backend/src/justai/ai/`. Rationale: [ADR 0006](adr/0006-ai-router.md).

## Roles

Every task is a **role** with a provider chain (first entry = primary, then fallbacks), a
locality rule and a timeout:

| Role | Purpose | Default without Google key | Default with Google key |
| --- | --- | --- | --- |
| `conversation` | answers in pipeline mode | – (assign one!) | gemini-3.8-flash → gemini-flash-lite-latest |
| `reasoning` | complex questions, security review of generated plugins | – | as above |
| `vision` | "What do you see?" | – | as above |
| `memory` | extraction/consolidation of memories | – | as above |
| `tool_generation` | writing new plugins | – | as above |
| `background` | summaries and others | – | as above |
| `realtime` | speech to speech (Gemini Live) | – | gemini-3.8-live |
| `stt` | speech recognition | faster-whisper `small` (local) | same |
| `tts` | speech output | Piper (local) | same |
| `embedding` | memory vectors | fastembed multilingual (local only) | same |

Wakeword and VAD always run locally and are not AI roles.

**Without a Google key and without a local LLM the assistant can hear and speak, but not
answer.** A local LLM (e.g. Ollama, [DEPLOYMENT.md](DEPLOYMENT.md#local-ai-with-ollama))
has to be assigned to the roles under *AI providers → Models & fallbacks*. This does not
happen automatically because size and quality of local models vary a lot.

As soon as a Google key is entered, JuStAI5 fills **empty** roles with the Gemini
defaults. Roles configured by the admin stay unchanged.

## Languages

The assistant understands and speaks **English, German and Italian** (setting
`languages`, main language `default_language` under *AI providers*).

* It answers in the language it was spoken to. If somebody switches language in the
  middle of a conversation, it switches too.
* Everything the language model reads is English: system prompt, tool descriptions and
  results, error messages, the event catalogue. The instruction "always answer in the
  user's language" makes the answer follow the conversation language. This keeps one set
  of texts for all languages and works best with the models.
* Texts spoken or stored without the model are translated in `justai/i18n.py`: the
  apology after an error, the note that an answer comes from the cloud, announcements of
  watches ("A car is in the driveway"), the episode memory of a conversation.
* Memories are written in the language of the conversation they come from; search works
  across languages (multilingual embeddings).
* Speech output uses a Piper voice per language (setting `voices`; included are
  `en_US-lessac`, `de_DE-thorsten` and `it_IT-paola`); Gemini Live speaks every language by
  itself.

## Conversation mode

* **Realtime** (default with Google key): audio goes directly to Gemini Live, answers come
  back as audio. Lowest latency, interruption in the model. JuStAI5 only sends audio that
  passed the echo gate.
* **Pipeline**: local STT → LLM of the role `conversation` → local TTS. Every step can be
  replaced individually and can run completely locally. Sentences are streamed (TTS starts
  with the first sentence).

The mode can be overridden per endpoint (`conversation.mode`).

### Speech recognition

* **Languages**: the configured languages (main language first) go to the recogniser as
  expected languages, to Gemini Live as `language_codes`. Before, automatic language
  detection often recognised short snippets as Spanish or Hindi. In the pipeline a result
  in a language that is not allowed is recognised again in the conversation language.
* **Vocabulary**: name of the assistant, "Jarvis", rooms and names of people and pets go
  to the recogniser as preferred terms (Gemini `custom_vocabulary`, faster-whisper
  `initial_prompt`).
* **Pauses**: Gemini ends the user's turn only after 1.0 s of silence with insensitive
  end detection (plugin setting `vad_silence_ms`). Before, a thinking pause of 0.7 s was
  taken as the end of the sentence. The assistant started to answer, and with half duplex
  cameras the rest of the sentence fell into the echo gate.
* **Measurement**: every conversation stores how much speech-like sound fell into the
  echo gate (`gated_speech_ms` in the conversation history, log "speech during echo
  gate"). A lot of it means: the gate is too long for this device.

Test bench (in the container): German test sentences in camera quality (8 kHz, room
noise) are recognised ~99 % correctly by Gemini Live with and without these settings.
The errors in real operation therefore mostly come from cut or split sentences, not from
the recognition itself.

## Fallback and outages

* If the primary provider fails (error, timeout, no first token after 25 s), the next one
  of the chain is taken. The failing provider then pauses briefly (cooldown) so that not
  every request first waits for the error. Paused models are shown orange on the
  dashboard.
* Every fallback creates `ai.provider.fallback`. A switch from local to cloud is
  **always** in the audit log. With `announce_cloud_fallback` (default: on) the assistant
  says in a running conversation (pipeline mode) before the answer that it comes from the
  cloud.
* Observed in operation: `gemini-3.8-flash` occasionally returned 503 (overload) and 429
  (quota). The chain switched automatically to `gemini-flash-lite-latest`.

## Privacy rules

*AI providers → Privacy & costs*:

| Switch | Effect |
| --- | --- |
| `cloud_allowed` | global: allow cloud providers at all |
| `camera_images_to_cloud` | camera images to cloud models |
| `conversation_audio_to_cloud` | conversation audio to the cloud (affects realtime and cloud STT) |
| `personal_memories_to_cloud` | memories and personal context to cloud models |
| `announce_cloud_fallback` | announce a switch to the cloud in the conversation (it is always logged) |
| per role `locality` | `local_only` / `prefer_local` / `any` |
| per room `cloud_media_allowed` | images/audio from this room never go to the cloud |

If a rule forbids all providers of a chain, the request fails with a clear reason instead
of bypassing the rule.

## Costs

Every call is recorded with tokens, audio seconds, latency and estimated costs (*AI
providers → Usage*, dashboard "AI costs today"). Daily and monthly limits
(`cost_limits.daily_usd`, `monthly_usd`) block cloud providers when reached; local ones
keep running. The costs are estimates from token counts and list prices, not a bill.

## Adding providers

Providers are plugins with the permission `ai.provide` (ports in `justai_sdk.ports.ai`:
chat with tools and streaming, realtime, STT, TTS, embeddings). Any OpenAI-compatible
server can be added without code as another endpoint through the plugin
*OpenAI-compatible*. This was tested with Gemini's OpenAI-compatible interface: the role
`conversation` was switched by configuration only ([TESTING.md](TESTING.md),
criterion 16).
