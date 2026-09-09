# Bee Researcher v2.51.2

## Topic threshold editing

- Owner accounts can update topic relevance thresholds from the back-office.
- Changing a topic threshold, definition, or term list invalidates only the
  unanalysed score rows for that topic, so the next pipeline run re-evaluates
  recent articles with the new rule.
- Scores attached to analysed articles remain intact for audit and feedback
  history.
