# Bee Researcher v2.50.0

## Guided catalog setup

- Media, topic, and business creation now starts with only a human-readable name.
- The server generates media (`S-###`) and topic (`T-###`) identifiers on final registration.
- A bounded review endpoint creates an editable draft in at most 50 seconds, using the approved OpenAI connection when available and an explicit fallback when it is not.
- The back office supports review, manual correction, final registration, cancellation, and a second review request.
- Existing records and edit APIs remain compatible; caller-supplied identifiers are ignored during creation.
