# Bee Researcher v3.30.4

## Media and Topic actions

- Add Media and Add Topic now open synchronously for the currently rendered authorized assistant.
- Legacy `onclick` assignments are removed during each explicit reconciliation, so each action has exactly one execution path.
- Form opening no longer waits for a redundant workspace network refresh; scoped API authorization is still enforced when drafting or saving.
- Catalog write actions are hidden from roles that cannot write media or topics.
- Async action failures restore controls and produce a visible localized error.
- Failed UI actions emit only a coarse, authenticated route signal for diagnosis; exception text and customer data are not transmitted.

## Validation

- The full automated suite covers the UI contract, API authorization, workspace isolation, source and topic endpoints, CSP and asset delivery.
- Browser smoke tests exercise the public domain and verify that both forms open without JavaScript errors.
