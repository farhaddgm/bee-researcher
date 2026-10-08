# Bee Researcher 3.33.6 — preserve literal code identifiers in translations

Includes complete-report translation, faithful headlines, report/UX isolation,
license/section translation and name-vs-prose validation from 3.33.2–3.33.5.
Review of the real Shopify report revealed that get_checkout, update_checkout
and complete_checkout were falsely rejected as untranslated ordinary words.
Language checks now preserve underscore/dotted identifiers and single-token
inline-code literals. Untranslated ordinary checkout/reasoning prose and English
sentences (including quoted/backtick sentences) remain rejected. Original
identifiers are not renamed, uppercased or changed by a translation repair.

No schema migration, model/settings/budget changes, score/status changes or
Telegram send/repost. All legacy repair is scoped to the named assistant's
unpublished previews and retains immutable source evidence.
