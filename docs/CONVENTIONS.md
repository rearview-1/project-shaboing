# Conventions

## Career Log Schemas

New bot career logs must include a top-level `schema` field. Current schema:

- `sweepy_career_log_v1`: normal bot career log with top-level run metadata and
  per-turn rows under `turns`.
- `sweepy_career_log_v0`: implicit legacy format for older logs that have no
  `schema` field.

Career-log readers should accept only listed schemas. Unknown future schemas
should be skipped with a warning instead of being silently treated as valid
training data.
