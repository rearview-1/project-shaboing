"""Mid-career outcome prediction via checkpoint centroids.

At every turn, the bot has a feature vector (current stats, HP, skill
points). Past careers have those same vectors at the same turn. By
aggregating top-sample and bottom-sample centroids at fixed checkpoint
turns (24, 36, 48, 60, 72), we can answer "is the current career
tracking top-quartile or bottom-quartile?" by simple nearest-centroid
classification.

The prediction is informational — it logs to the career report so the
user can see "at turn 36 the bot was tracking_bottom" without the bot
itself making any new decisions. Wiring it into decisions
(skill-purchase timing, race-entry aggressiveness, etc.) is a future
step the user can choose to take after observing whether the
classifier is actually accurate on real careers.

Feature vector at each turn:
    [speed, stamina, power, guts, wit, hp, skill_point]

We use Euclidean distance to centroids. Stats are roughly comparable
scale (0-1200), skill_point and hp are smaller — we normalize each
dimension by its overall sample max before computing distance so no
single dimension dominates.
"""

import math


CHECKPOINT_TURNS = (24, 36, 48, 60, 72)
# Window for matching a turn to its nearest checkpoint. Turns within
# this window of a checkpoint are predicted against that checkpoint's
# centroids; turns outside any window return "unknown".
CHECKPOINT_WINDOW = 4

# Minimum samples per checkpoint to build a centroid. Below this,
# the checkpoint is omitted and the predictor returns "unknown" near it.
MIN_SAMPLES_PER_CHECKPOINT = 3

FEATURE_KEYS = ("speed", "stamina", "power", "guts", "wit", "hp", "skill_point")


def stat_curve_from_turns(turns):
    """Extract a slim per-turn feature vector list from a career log.

    Returns [{turn, speed, stamina, power, guts, wit, hp, skill_point}, ...].
    Skips turns missing the stats dict.
    """
    out = []
    for turn_row in turns or []:
        if not isinstance(turn_row, dict):
            continue
        stats = turn_row.get("stats") or {}
        turn_num = turn_row.get("turn") or stats.get("turn")
        try:
            turn_int = int(turn_num)
        except (TypeError, ValueError):
            continue
        if turn_int <= 0:
            continue
        vec = {"turn": turn_int}
        usable = False
        for key in FEATURE_KEYS:
            try:
                value = int(stats.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                usable = True
            vec[key] = value
        if usable:
            out.append(vec)
    return out


def _nearest_checkpoint(turn):
    """Map an arbitrary turn to its nearest CHECKPOINT_TURNS entry,
    or None if no checkpoint is within CHECKPOINT_WINDOW turns."""
    best = None
    best_dist = CHECKPOINT_WINDOW + 1
    for cp in CHECKPOINT_TURNS:
        dist = abs(turn - cp)
        if dist < best_dist:
            best_dist = dist
            best = cp
    if best_dist > CHECKPOINT_WINDOW:
        return None
    return best


def aggregate_trajectory_centroids(top_samples, bottom_samples):
    """Build per-checkpoint centroids from top + bottom sample curves.

    Returns:
        {
          "checkpoints": {
            "24": {
              "top_centroid": {speed: 250, stamina: ..., ...},
              "bottom_centroid": {speed: 220, stamina: ..., ...},
              "top_count": int,
              "bottom_count": int,
              "feature_scales": {speed: max_value, ...},
            },
            ...
          }
        }

    Empty when no checkpoint has enough samples on either side.
    """
    by_cp_top = {cp: [] for cp in CHECKPOINT_TURNS}
    by_cp_bottom = {cp: [] for cp in CHECKPOINT_TURNS}

    def gather(samples_list, bucket):
        for sample in samples_list or []:
            curve = sample.get("stat_curve") or []
            seen = set()
            for row in curve:
                if not isinstance(row, dict):
                    continue
                try:
                    turn = int(row.get("turn") or 0)
                except (TypeError, ValueError):
                    continue
                cp = _nearest_checkpoint(turn)
                if cp is None or cp in seen:
                    continue
                seen.add(cp)
                bucket[cp].append({k: int(row.get(k) or 0) for k in FEATURE_KEYS})

    gather(top_samples, by_cp_top)
    gather(bottom_samples, by_cp_bottom)

    # Feature scales: max observed across all samples per feature.
    # Used to normalize distance so 0-1200 stats don't dwarf 0-200 HP.
    feature_scales = {key: 1 for key in FEATURE_KEYS}
    for cp in CHECKPOINT_TURNS:
        for vec in by_cp_top[cp] + by_cp_bottom[cp]:
            for key in FEATURE_KEYS:
                if vec[key] > feature_scales[key]:
                    feature_scales[key] = vec[key]

    checkpoints = {}
    for cp in CHECKPOINT_TURNS:
        top_vecs = by_cp_top[cp]
        bottom_vecs = by_cp_bottom[cp]
        if len(top_vecs) < MIN_SAMPLES_PER_CHECKPOINT and len(bottom_vecs) < MIN_SAMPLES_PER_CHECKPOINT:
            continue
        cp_entry = {
            "top_count": len(top_vecs),
            "bottom_count": len(bottom_vecs),
        }
        if top_vecs:
            cp_entry["top_centroid"] = _centroid(top_vecs)
        if bottom_vecs:
            cp_entry["bottom_centroid"] = _centroid(bottom_vecs)
        checkpoints[str(cp)] = cp_entry
    if not checkpoints:
        return {}
    return {
        "schema": "sweepy_trajectory_centroids_v1",
        "checkpoints": checkpoints,
        "feature_scales": feature_scales,
    }


def _centroid(vecs):
    n = max(1, len(vecs))
    return {key: sum(v[key] for v in vecs) / n for key in FEATURE_KEYS}


def predict_trajectory(centroids, current_stats, current_turn):
    """Classify the current career's trajectory.

    Args:
        centroids: result of `aggregate_trajectory_centroids`.
        current_stats: dict with FEATURE_KEYS values (matches
            stat_curve_from_turns row shape).
        current_turn: int.

    Returns:
        {
          "label": "tracking_top" | "ambiguous" | "tracking_bottom" | "unknown",
          "checkpoint": int|None,    # which checkpoint was used
          "top_distance": float|None,
          "bottom_distance": float|None,
          "confidence": float,        # 0..1, |dist_diff| / (dist_top + dist_bottom)
        }
    """
    out = {
        "label": "unknown",
        "checkpoint": None,
        "top_distance": None,
        "bottom_distance": None,
        "confidence": 0.0,
    }
    if not centroids:
        return out
    checkpoints_dict = centroids.get("checkpoints") or {}
    feature_scales = centroids.get("feature_scales") or {key: 1 for key in FEATURE_KEYS}
    try:
        turn_int = int(current_turn)
    except (TypeError, ValueError):
        return out
    cp = _nearest_checkpoint(turn_int)
    if cp is None:
        return out
    cp_entry = checkpoints_dict.get(str(cp))
    if not cp_entry:
        return out
    top_c = cp_entry.get("top_centroid")
    bottom_c = cp_entry.get("bottom_centroid")
    if not top_c and not bottom_c:
        return out
    cur_vec = {key: int(current_stats.get(key) or 0) for key in FEATURE_KEYS}
    top_dist = _normalized_distance(cur_vec, top_c, feature_scales) if top_c else None
    bottom_dist = _normalized_distance(cur_vec, bottom_c, feature_scales) if bottom_c else None
    out["checkpoint"] = cp
    out["top_distance"] = round(top_dist, 4) if top_dist is not None else None
    out["bottom_distance"] = round(bottom_dist, 4) if bottom_dist is not None else None
    if top_dist is None:
        out["label"] = "tracking_bottom"
        out["confidence"] = 1.0
        return out
    if bottom_dist is None:
        out["label"] = "tracking_top"
        out["confidence"] = 1.0
        return out
    # Both centroids present: classify by nearest.
    total = top_dist + bottom_dist
    if total <= 0:
        out["label"] = "ambiguous"
        return out
    diff = bottom_dist - top_dist
    confidence = abs(diff) / total
    out["confidence"] = round(confidence, 3)
    # Require some confidence margin to commit — close calls stay
    # "ambiguous" so the dashboard doesn't flip-flop turn by turn.
    if confidence < 0.05:
        out["label"] = "ambiguous"
    elif diff > 0:
        out["label"] = "tracking_top"
    else:
        out["label"] = "tracking_bottom"
    return out


def _normalized_distance(vec_a, vec_b, scales):
    total = 0.0
    for key in FEATURE_KEYS:
        scale = max(1, scales.get(key, 1))
        diff = (vec_a.get(key, 0) - vec_b.get(key, 0)) / scale
        total += diff * diff
    return math.sqrt(total)
