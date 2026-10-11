# Reader voice and project memory

The sections below record the 3.43.0 baseline. The 3.45.0 ElevenLabs replacement and its pending activation requirements are documented at the end and in the operations guide.

The news dialog now follows report → **Summarize simply** → **Discuss this news**. The existing summary shortcut still fills a question for review before sending. Chat offers Text, Audio and Text and audio together; the last option shows the same answer while speaking it. Voice input fills the editable question and requires Send. No model request occurs on opening, choosing a mode, dictating or replaying an answer.

Speech recognition and synthesis use browser/device facilities. Recognition may send audio to the browser vendor's service, disclosed beside the microphone. Availability varies by device, browser and installed language voices, including Persian. Missing support and speech errors show a localized message and return to text. Physical microphone quality and vendor services are outside synthetic automated tests. This increment does not provide continuous Realtime voice or server-generated audio files.

Unsaved news-window conversations keep the existing erase-on-close and short server-lease behavior. Saving atomically removes the window lease, so saved threads survive close, logout and session expiry. Reopening news starts a fresh chat; saved transcripts are viewed in Project memory.

**Save conversation** explicitly retains a whole thread in its news project's memory. This includes persisted older pages and subsequent turns in that saved thread. At least one completed, nonempty answer is required. Repeated saves keep the original timestamp. The reader sidebar opens Project memory for the currently selected workspace; entries show source, date and expandable full history. Removing an entry from memory returns it to ordinary retention; deleting its conversation clears its text immediately.

Memory remains private to the saving user. Both list and message access enforce current project membership and published-news access. Saving does not inject other saved conversations into model prompts. No raw voice recording is persisted. These boundaries apply to owners as well: an owner sees their own saved conversations through the reader portal.

## Database and release

Additive migration `0047_project_chat_memory` adds nullable `saved_at` and a filtered user/project/timestamp index to the existing conversation table. Ordinary expired conversations and orphaned generation text are still cleaned; explicitly saved conversations and their messages survive retention. Existing cascade erasure remains active for account, project and article deletion.

Run `ops/scoped-release/migrate_project_memory.py --image <verified-digest> --revision <main-sha>` with the private migrator environment. This backs up only the Researcher schema and verifies the restricted runtime identity. Apply the separate migration job before starting a release with this code. Runtime startup verifies the packaged migration head. The scoped application deployment controller does not run migrations. No production migration, deployment or session reset is part of this feature preparation. Rollback keeps the additive column and saved data; review old-version retention behavior before running an earlier application, as that version does not exempt saved conversations.

## Validation

- Unit and HTTP tests cover assets, CSRF, reader-only microphone policy and access denial.
- Browser acceptance covers all eight interface languages, responsive layout, dictation without auto-send, text/audio modes, same-text playback and saved-memory viewing. Speech APIs are deterministic test doubles, with live HTTP and PostgreSQL for application behavior.
- Real PostgreSQL acceptance covers complete-answer admission, idempotent save, equal-timestamp pagination, user/project isolation, retention, removing a save and explicit deletion.
- Existing startup, chat, reader and admin acceptance gates remain required. CI runs the added SQL checks through `ops/scoped-release/verify_news_chat.py`.

Product research and the prioritized 20 ideas are in [USER-BACKOFFICE-20-IDEAS-fa.md](USER-BACKOFFICE-20-IDEAS-fa.md).

## ElevenLabs extension in 3.45.0

The implementation replaces device speech services with server-proxied ElevenLabs STT/TTS and adds actual audio files, explicit Save audio, private project-memory playback/download and separate microphone-recording consent. See the [product proposal](ELEVENLABS-VOICE-PROPOSAL-fa.md), [technical design](ELEVENLABS-VOICE-TECHNICAL-DESIGN-fa.md), [acceptance backlog](ELEVENLABS-VOICE-BACKLOG-fa.md) and [operations guide](ELEVENLABS-VOICE-OPERATIONS-fa.md). The earlier sections above describe the 3.43.0 baseline; their device speech and test-double claims do not describe this extension. Live account activation remains pending server credentials, approved voices, verified tariff and provider/device acceptance; the feature defaults off.
