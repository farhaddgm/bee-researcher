# Bee Researcher 3.33.3 — translation quality gate correction

Carries the complete-report translation fixes in 3.33.2. Live repair exposed a
false positive: a faithful Persian translation repeating the model name Sonnet
three times was rejected. The language gate now counts distinct foreign words,
keeps reviewed Sonnet/Opus/Haiku model names, and still rejects untranslated
lowercase vocabulary and whole English/TitleCase sentences. Regression tests
cover repeated known/unknown proper names and untranslated technical terms.

Failed translation jobs record only invalid schema field names (not provider
text or credentials), making bounded retries diagnosable without another paid
probe. No schema migration, score/status/configuration change or Telegram send.
