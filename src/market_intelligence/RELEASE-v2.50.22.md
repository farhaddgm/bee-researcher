# Release v2.50.22

## Processing and publication limits

- The per-run value of 7 is now explicitly a publication limit only.
- Extraction, relevance scoring, clustering, analysis and preview creation use the processing budget instead of the publication cap.
- Each project may process up to 1,000 newly extracted articles per day.
- The processing budget is enforced per project and reported in the pipeline result.
- Automatic delivery still publishes at most 7 previews per run; previously queued previews may be delivered on later scheduled slots.
- The back office now labels the field as «سقف انتشار در هر نوبت» and explains the independent 1,000-article processing cap.
