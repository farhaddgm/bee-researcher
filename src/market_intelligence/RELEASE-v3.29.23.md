# Bee Researcher v3.29.23

## Media and topic catalog creation

- Media creation now supports the intended review-first flow: enter only a media name, review an editable draft, then complete and save the public URLs.
- Direct media creation remains available when both public URLs are provided; a half-filled URL pair is rejected with a clear message.
- Topic creation keeps the same review-first flow and now falls back to an explicit editable local draft when the optional AI draft request is unavailable.
- Source and topic saves remain scoped to the selected assistant, with server-generated `S-###` and `T-###` identifiers.

## Verification

- API smoke test: source and topic creation for the `هوش مصنوعی` assistant succeeded and temporary records were removed.
- Browser smoke test covers selecting `هوش مصنوعی`, name-only media review, final media save, topic review, final topic save, and exact cleanup.
