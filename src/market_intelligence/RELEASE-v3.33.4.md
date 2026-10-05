# Bee Researcher 3.33.4 — complete quoted and license prose

Includes the report/UX language isolation, faithful translated headlines,
complete-prose gate and bounded repair in 3.33.2–3.33.3. A live, budgeted trial
found another ambiguity: the model treated full English license descriptions
and institutional section names as proper names. Instructions now explicitly
translate those descriptions, quotes and ordinary technical vocabulary. Only
short license IDs and real brand/model identifiers may remain unchanged.
Persian examples include MIT News and the Creative Commons license description.
The time-horizon field is explicitly covered too. New tests verify that English
license prose is rejected, its Persian translation and license ID are accepted,
and Persian examples do not leak into other output-language prompts.

The live prompt trial translated three formerly rejected reports completely,
under the existing quota and unchanged language validation. No migration or
settings/score/status changes. No Telegram publication or repost.
