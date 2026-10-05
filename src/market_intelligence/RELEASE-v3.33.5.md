# Bee Researcher 3.33.5 — distinguish names from untranslated prose

Complete-report translation and report/UX isolation fixes from 3.33.2–3.33.4.
Live repair identified legitimate investor/publisher/product names that were
incorrectly rejected merely because three distinct Latin names appeared in a
Persian report. This false-positive rule is replaced by high-signal English
sentence/verb/license vocabulary and untranslated lowercase vocabulary checks.
TitleCase and ALLCAPS English sentences still fail validation. Names such as
Peak/Surge, Reuters/Financial Times, Eufy Video Doorbell and Insight Partners
can appear intact inside translated Persian sentences. No blanket exemption
for English prose. Common compound trademarks are recognized as phrases, not
by whitelisting their individual ordinary English words.

Includes explicit translation of quotes, license prose and time horizons,
field-only failure diagnostics, bounded preview repair and delivery gates.
No new migration, score/status change or Telegram send/repost.
