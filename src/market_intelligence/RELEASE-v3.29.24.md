# Bee Researcher v3.29.24

## Reliable media/topic actions during first paint

- Add-media and add-topic actions now wait for the authorized assistant list
  when the user clicks while the first workspace payload is still loading.
- The selected workspace option is preferred; a stale local workspace id is
  never used unless it is present in the current authorized list.
- The existing review-first forms remain unchanged: media needs only a name
  to start review, and topics use the same editable draft flow.

## Verification

- Browser smoke test in English and Persian: both buttons open their modal for
  the `هوش مصنوعی` assistant.
- Full unit suite: 329 tests passed.
- Service health: healthy after deploy.
