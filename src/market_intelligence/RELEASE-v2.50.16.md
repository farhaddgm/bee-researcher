# Release v2.50.16

## Seven-news per run cap

- `max_items_per_run` is capped at 7 across configuration, API validation and pipeline settings.
- The backoffice prevents values above 7, including older cached UI shells.
- Existing workspace runtime values are normalized to 7 during deployment; 24 selected hourly slots therefore allow up to 168 scheduled items per day.
