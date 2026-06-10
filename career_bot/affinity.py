"""Affinity and lineage tracking for parent quality.

Per hakuraku data, white spark generation rate is approximately:
  P(spark generated) = base_rate * 1.1^lineage_count

where lineage_count is the number of times the spark appears in the
immediate lineage (parents + grandparents). Each lineage match adds
~10% relative chance.

Affinity (base + race epithets + GP G1 wins) doesn't directly multiply
spark rates the way lineage_count does, but it correlates with lineage
quality and is worth tracking separately for diagnostic visibility.

Field names below are best-effort against typical game log shapes —
verify against actual capture data and adjust as needed. The functions
defensively coerce missing fields to 0 / [] so an unexpected log shape
produces a neutral "no signal" answer rather than crashing.
"""


def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_list(value):
    return value if isinstance(value, list) else []


def compute_career_affinity(career_log):
    """Compute the affinity profile for a finished career.

    Returns a dict with the three components plus their total. All counts
    default to 0 when missing, so a partial / older log returns zero
    affinity rather than raising.
    """
    if not isinstance(career_log, dict):
        return {"base_affinity": 0, "race_epithets_count": 0, "grandparent_g1_wins": 0, "total": 0}

    final_summary = (
        career_log.get("final_summary")
        or career_log.get("summary")
        or career_log.get("learning_metadata", {}).get("final_summary")
        or {}
    )
    if not isinstance(final_summary, dict):
        final_summary = {}

    base_affinity = _safe_int(final_summary.get("base_affinity"))

    races = _safe_list(final_summary.get("race_history"))
    race_epithets_count = sum(
        1 for r in races
        if isinstance(r, dict) and r.get("granted_epithet")
    )

    gp_g1_wins = 0
    for parent in _safe_list(final_summary.get("grandparents")):
        if isinstance(parent, dict):
            gp_g1_wins += _safe_int(parent.get("g1_wins"))

    total = base_affinity + race_epithets_count + gp_g1_wins
    return {
        "base_affinity": base_affinity,
        "race_epithets_count": race_epithets_count,
        "grandparent_g1_wins": gp_g1_wins,
        "total": total,
    }


def compute_lineage_counts_for_sparks(final_sparks, lineage_data):
    """For each white spark on the career, count how many times that spark
    appears in the immediate lineage (parents + grandparents).

    Returns a dict mapping spark_name -> lineage_count. Used to validate
    that observed white spark rates roughly follow base * 1.1^n, and to
    feed `expected_white_generation_rate` for spark-rate observation
    reporting in the learning report.

    lineage_data: dict with parent_1, parent_2, grandparent_p1_1,
                  grandparent_p1_2, grandparent_p2_1, grandparent_p2_2
                  entries — each containing a `sparks` list of {name, ...}.
    """
    if not isinstance(final_sparks, list) or not isinstance(lineage_data, dict):
        return {}

    lineage_keys = (
        "parent_1", "parent_2",
        "grandparent_p1_1", "grandparent_p1_2",
        "grandparent_p2_1", "grandparent_p2_2",
    )
    lineage_spark_counts = {}
    for entry_key in lineage_keys:
        entry = lineage_data.get(entry_key) or {}
        if not isinstance(entry, dict):
            continue
        for spark in _safe_list(entry.get("sparks")):
            if isinstance(spark, dict):
                name = str(spark.get("name") or "").lower()
                if name:
                    lineage_spark_counts[name] = lineage_spark_counts.get(name, 0) + 1

    result = {}
    for spark in final_sparks:
        if isinstance(spark, dict):
            name = str(spark.get("name") or "").lower()
            if name and name not in result:
                result[name] = lineage_spark_counts.get(name, 0)
    return result
