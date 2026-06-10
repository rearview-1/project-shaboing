# Stat Targets And Parent Spark Intent

`expect_attribute` is the fallback target stat vector for Speed, Stamina,
Power, Guts, and Wit. Fresh presets use `[1100, 700, 950, 600, 800]` so the
bot starts from realistic SS-parent targets instead of treating every stat as
unbounded.

`expect_attribute_profiles` is the preferred source when present. The resolver
first checks the current objective/style/distance/deck profile, then falls back
to matching `balanced_any` profiles before using top-level `expect_attribute`.
This lets learned real-run targets override stale all-1166 or all-1200 vectors.

`desired_parent_sparks` is operator intent. It is owned by the config/UI layer,
not by auto-learning or account-local policy overrides. Learning reports may log
the value used for traceability, but learned model/override layers must not
write it back over the active preset.
