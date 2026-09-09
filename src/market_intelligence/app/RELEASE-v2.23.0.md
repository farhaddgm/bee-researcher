# Bee Researcher v2.23.0

## MI-035 — table sorting and Telegram bot/channel administration

- Replaced row-level up/down ordering controls with selectable table headers for media and topics.
- Added ascending/descending sorting for the visible columns while preserving search and workspace scope.
- Added a channel-section editor for bot identity and both channel IDs.
- Bot username and numeric bot ID are editable per assistant; the bot token remains server-side in environment configuration and is exposed only as a configured/not-configured status.
- Added inline edit actions to each channel card for clearer UX.
- Added validation and audit-safe handling for bot identity fields.
