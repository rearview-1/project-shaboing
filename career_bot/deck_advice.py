import math
import statistics
import itertools
import re
from collections import Counter, defaultdict


TYPE_ALIASES = {
    "friends": "Pal",
    "friend": "Pal",
    "pal": "Pal",
    "wisdom": "Wit",
    "int": "Wit",
    "intelligence": "Wit",
}

GOAL_TYPE_HINTS = {
    "speed": {"Speed": 1.0, "Power": 0.35, "Wit": 0.25},
    "stamina": {"Stamina": 1.0, "Power": 0.35, "Wit": 0.15},
    "power": {"Power": 1.0, "Wit": 0.45, "Speed": 0.2},
    "guts": {"Guts": 1.0, "Power": 0.3, "Wit": 0.2},
    "wit": {"Wit": 1.0, "Speed": 0.25, "Power": 0.15},
}
TARGET_TYPE_PROFILES = {
    "speed": {"Speed": 2.1, "Power": 1.0, "Wit": 1.2, "Stamina": 0.5, "Guts": 0.2},
    "stamina": {"Stamina": 2.0, "Power": 1.0, "Wit": 1.0, "Speed": 0.7, "Guts": 0.3},
    "power": {"Power": 2.2, "Wit": 1.3, "Speed": 0.8, "Stamina": 0.5, "Guts": 0.2},
    "guts": {"Guts": 1.8, "Power": 1.0, "Wit": 1.0, "Speed": 0.8, "Stamina": 0.4},
    "wit": {"Wit": 2.2, "Power": 1.2, "Speed": 0.8, "Stamina": 0.5, "Guts": 0.3},
    "balanced": {"Power": 1.3, "Wit": 1.3, "Speed": 1.0, "Stamina": 0.9, "Guts": 0.5},
}
RARITY_STRENGTH = {"SSR": 1.0, "SR": 0.78, "R": 0.52}
SOURCE_QUALITY_BONUS = {
    "bot_parent_outcome": 0.25,
    "bot_parent_library": 0.18,
    "user_parent_library": 0.05,
    "bot": 0.08,
    "manual_trace": 0.14,
    "manual_hachimi": 0.12,
    "team_trials_observation": 0.10,
}


def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _normalize_type(value):
    text = str(value or "").strip()
    if not text:
        return "Unknown"
    folded = text.lower()
    return TYPE_ALIASES.get(folded, text)


def _normalize_card(card, support_catalog=None):
    support_catalog = support_catalog or {}
    if not isinstance(card, dict):
        return None
    card_id = _safe_int(card.get("id") or card.get("support_card_id") or card.get("card_id"))
    if not card_id:
        return None
    catalog = support_catalog.get(str(card_id), {})
    return {
        "id": card_id,
        "name": str(card.get("name") or catalog.get("name") or f"Card {card_id}"),
        "rarity": str(card.get("rarity") or catalog.get("rarity") or "?"),
        "type": _normalize_type(card.get("type") or catalog.get("type")),
        "limit_break_count": _safe_int(card.get("limit_break_count") or card.get("lb_level")),
        "exp": _safe_int(card.get("exp")),
        "level": _safe_int(card.get("level") or card.get("support_card_level") or card.get("lv")),
    }


def _normalize_deck(deck, support_catalog=None):
    support_catalog = support_catalog or {}
    if not isinstance(deck, dict):
        return None
    cards = []
    raw_cards = deck.get("cards") or []
    if isinstance(raw_cards, list):
        for card in raw_cards:
            normalized = _normalize_card(card, support_catalog=support_catalog)
            if normalized:
                cards.append(normalized)
    if not cards:
        for raw_id in deck.get("support_card_ids") or deck.get("support_card_id_array") or []:
            card_id = _safe_int(raw_id)
            if not card_id:
                continue
            catalog = support_catalog.get(str(card_id), {})
            cards.append({
                "id": card_id,
                "name": str(catalog.get("name") or f"Card {card_id}"),
                "rarity": str(catalog.get("rarity") or "?"),
                "type": _normalize_type(catalog.get("type")),
            })
    if not cards:
        return None
    return {
        "id": _safe_int(deck.get("id") or deck.get("deck_id")),
        "name": str(deck.get("name") or deck.get("deck_name") or f"Deck {_safe_int(deck.get('id') or deck.get('deck_id'))}").strip(),
        "cards": cards,
    }


def _percentile(values, q):
    ordered = sorted(_safe_float(value) for value in values if value is not None)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    idx = _clamp(q, 0.0, 1.0) * (len(ordered) - 1)
    low = int(math.floor(idx))
    high = int(math.ceil(idx))
    if low == high:
        return ordered[low]
    mix = idx - low
    return ordered[low] * (1.0 - mix) + ordered[high] * mix


def _normalize_parent_goals(value):
    try:
        from career_bot.learning import normalize_parent_goals
        return normalize_parent_goals(value)
    except Exception:
        return {"blue": [], "pink": [], "green": [], "white": []}


def _first_goal(goals, key):
    goals = goals or {}
    values = goals.get(key) or []
    if isinstance(values, list) and values:
        return str(values[0] or "").strip()
    text = str(values or "").strip()
    return text


def _goal_signature(goals):
    goals = _normalize_parent_goals(goals)
    blue = _first_goal(goals, "blue").lower() or "any"
    white = ",".join(str(item).strip().lower() for item in (goals.get("white") or [])[:2] if str(item).strip())
    green = ",".join(str(item).strip().lower() for item in (goals.get("green") or [])[:1] if str(item).strip())
    return f"blue:{blue}|green:{green}|white:{white}"


def _sample_goals(sample):
    sample = sample or {}
    ctx = sample.get("run_context") or {}
    goals = ctx.get("desired_parent_sparks")
    if isinstance(goals, dict) and any(goals.values()):
        return _normalize_parent_goals(goals)
    meta = sample.get("learning_metadata") or {}
    session = meta.get("session") or {}
    primary = str(((session.get("primary_stat_target") or {}).get("stat") or "")).strip()
    blue = str(((session.get("blue_spark_intent") or {}).get("preferred_color") or "")).strip()
    return _normalize_parent_goals({
        "blue": [primary or blue] if (primary or blue) else [],
        "white": ((session.get("white_spark_intent") or {}).get("high_value_targets") or [])[:3],
    })


def _sample_support_ids(sample):
    sample = sample or {}
    ctx = sample.get("run_context") or {}
    ids = ctx.get("support_card_ids")
    if isinstance(ids, list) and ids:
        return tuple(_safe_int(item) for item in ids if _safe_int(item))
    cards = ctx.get("support_cards")
    if isinstance(cards, list) and cards:
        return tuple(_safe_int(item.get("id") or item.get("support_card_id")) for item in cards if _safe_int(item.get("id") or item.get("support_card_id")))
    manifest = sample.get("manifest") or {}
    deck = manifest.get("deck") or sample.get("deck") or []
    if isinstance(deck, list) and deck:
        resolved = []
        for row in deck:
            if not isinstance(row, dict):
                continue
            card_id = _safe_int(row.get("support_card_id") or row.get("id") or row.get("card_id"))
            if card_id:
                resolved.append(card_id)
        return tuple(resolved)
    return ()


def _sample_cards(sample, support_catalog=None):
    support_catalog = support_catalog or {}
    sample = sample or {}
    ctx = sample.get("run_context") or {}
    cards = []
    for row in ctx.get("support_cards") or []:
        normalized = _normalize_card(row, support_catalog=support_catalog)
        if normalized:
            cards.append(normalized)
    if cards:
        return cards
    cards = []
    for card_id in _sample_support_ids(sample):
        catalog = support_catalog.get(str(card_id), {})
        cards.append({
            "id": card_id,
            "name": str(catalog.get("name") or f"Card {card_id}"),
            "rarity": str(catalog.get("rarity") or "?"),
            "type": _normalize_type(catalog.get("type")),
            "limit_break_count": _safe_int(((sample.get("run_context") or {}).get("support_card_lb_levels") or {}).get(str(card_id), {}).get("lb")),
            "exp": _safe_int(((sample.get("run_context") or {}).get("support_card_lb_levels") or {}).get(str(card_id), {}).get("exp")),
            "level": 0,
        })
    return cards


def _type_counts(cards):
    counter = Counter()
    for card in cards or []:
        counter[_normalize_type(card.get("type"))] += 1
    return counter


def _goal_focus_bonus(deck_cards, goals):
    blue = _first_goal(goals, "blue").strip().lower()
    weights = GOAL_TYPE_HINTS.get(blue)
    if not weights:
        return 0.0
    counts = _type_counts(deck_cards)
    total = max(1, len(deck_cards or []))
    score = 0.0
    for type_name, weight in weights.items():
        score += (counts.get(type_name, 0) / total) * weight
    return score


def _confidence_label(sample_count, unique_decks):
    if sample_count >= 18 and unique_decks >= 2:
        return "high"
    if sample_count >= 8:
        return "medium"
    return "low"


def _load_bot_parent_positive_samples(base_dir, parent_goals=None):
    try:
        from career_bot.learning import normalize_parent_library_entry
        from career_bot.parent_memory import library_path, load_parent_library, load_registry
    except Exception:
        return []

    parent_goals = _normalize_parent_goals(parent_goals)
    library = load_parent_library(base_dir)
    parents = library.get("parents") if isinstance(library, dict) else []
    by_id = {
        _safe_int(parent.get("instance_id")): parent
        for parent in (parents or [])
        if isinstance(parent, dict) and parent.get("made_by_bot")
    }
    registry = load_registry(base_dir)
    samples = []
    for row in registry.get("bot_parents") or []:
        if not isinstance(row, dict):
            continue
        parent = by_id.get(_safe_int(row.get("instance_id")))
        if not parent:
            continue
        sample = normalize_parent_library_entry(library_path(base_dir), parent, parent_goals=parent_goals)
        if not sample:
            continue
        sample["path"] = f"{row.get('career_log') or sample.get('path')}#parent_outcome"
        sample["career_log"] = row.get("career_log")
        sample["source"] = "bot_parent_outcome"
        sample["run_context"] = row.get("run_context") or {}
        sample["final_stats"] = row.get("final_stats") or sample.get("final_stats") or {}
        sample["sample_weight"] = max(_safe_float(sample.get("sample_weight"), 1.0), 1.15)
        samples.append(sample)
    return samples


def _collect_runtime_deck_advice_samples(base_dir, parent_goals=None, recent_bot_logs=20):
    """Load only the evidence deck advice actually needs.

    The generic learner sample collector is too heavy for a live UI endpoint:
    it walks manual/Hachimi corpora, annotates decision quality, and attaches
    learning metadata across the whole sample pool. For deck advice we only
    need:
    - bot-made parent outcomes
    - saved parent-library rows
    - a small recent slice of bot logs

    This keeps deck advice responsive during normal bot runs and avoids
    scanning external Hachimi captures when the operator is not using manual
    capture workflows.
    """
    parent_goals = _normalize_parent_goals(parent_goals)
    samples = list(_load_bot_parent_positive_samples(base_dir, parent_goals=parent_goals))
    seen_paths = {
        str(sample.get("path") or "").strip()
        for sample in samples
        if str(sample.get("path") or "").strip()
    }
    try:
        from career_bot.learning import load_bot_logs, load_parent_library_samples, runtime_roots
    except Exception:
        return samples
    try:
        from career_bot.observed_profiles import load_observation_samples
    except Exception:
        load_observation_samples = None

    recent_bot_logs = _clamp(_safe_int(recent_bot_logs, 20), 0, 40)
    for root in runtime_roots(base_dir, None):
        if load_observation_samples:
            for sample in load_observation_samples(root, recent=400, min_score=17500):
                path = str(sample.get("path") or "").strip()
                if path and path in seen_paths:
                    continue
                if path:
                    seen_paths.add(path)
                samples.append(sample)
        for sample in load_parent_library_samples(root, parent_goals=parent_goals, recent=120):
            path = str(sample.get("path") or "").strip()
            if path and path in seen_paths:
                continue
            if path:
                seen_paths.add(path)
            samples.append(sample)
        if recent_bot_logs <= 0:
            continue
        for sample in load_bot_logs(root, recent=recent_bot_logs, parent_goals=parent_goals):
            path = str(sample.get("path") or "").strip()
            if path and path in seen_paths:
                continue
            if path:
                seen_paths.add(path)
            samples.append(sample)
    return samples


def _top_card_rows(card_stats):
    rows = []
    for card_id, data in card_stats.items():
        weight = data["weight"]
        if weight <= 0:
            continue
        rows.append({
            "id": card_id,
            "name": data["name"],
            "type": data["type"],
            "score": round(data["score_sum"] / weight, 4),
            "appearances": int(data["count"]),
            "top_rate": round(data["top_weight"] / weight, 4),
        })
    rows.sort(key=lambda row: (row["score"], row["top_rate"], row["appearances"]), reverse=True)
    return rows


def _normalize_character_name(name):
    return re.sub(r"[^a-z0-9]+", "", re.sub(r"\([^)]*\)", "", str(name or "").lower()))


def _normalize_support_pool(available_supports, support_catalog=None):
    support_catalog = support_catalog or {}
    cards = []
    for row in available_supports or []:
        normalized = _normalize_card(row, support_catalog=support_catalog)
        if normalized:
            cards.append(normalized)
    return cards


def _default_target_profile(parent_goals):
    blue = _first_goal(parent_goals, "blue").strip().lower()
    base = TARGET_TYPE_PROFILES.get(blue) or TARGET_TYPE_PROFILES["balanced"]
    return dict(base)


def _ownership_strength(card):
    rarity = str(card.get("rarity") or "?").upper()
    base = RARITY_STRENGTH.get(rarity, 0.45)
    lb = _clamp(_safe_int(card.get("limit_break_count")), 0, 4) / 4.0
    exp = _clamp(math.log1p(max(0, _safe_int(card.get("exp")))) / math.log1p(60000), 0.0, 1.0)
    level = _clamp(_safe_int(card.get("level")) / 50.0, 0.0, 1.0)
    maturity = max(exp, level)
    return (base * 0.72) + (lb * 0.2) + (maturity * 0.08)


def _sample_factor_quality(sample, parent_goals):
    factor_quality = sample.get("factor_quality")
    if isinstance(factor_quality, dict):
        return factor_quality
    try:
        from career_bot.learning import factor_quality_metrics
        return factor_quality_metrics(sample, parent_goals=parent_goals)
    except Exception:
        return {}


def _sample_trainee_card_id(sample):
    return _safe_int(((sample.get("run_context") or {}).get("trainee_card_id")))


def _sample_style(sample):
    sample = sample or {}
    ctx = sample.get("run_context") or {}
    return str(
        ctx.get("skill_profile_style")
        or ctx.get("style_target")
        or ctx.get("style")
        or sample.get("style")
        or sample.get("skill_profile_style")
        or ""
    ).strip()


def _sample_distance(sample):
    sample = sample or {}
    ctx = sample.get("run_context") or {}
    return str(
        ctx.get("skill_profile_distance")
        or ctx.get("distance")
        or ctx.get("team_trials_distance_slot")
        or sample.get("distance")
        or sample.get("team_trials_distance_slot")
        or ""
    ).strip().lower()


def _matches_style_distance(sample, style="", distance=""):
    style = str(style or "").strip()
    distance = str(distance or "").strip().lower()
    if style and _sample_style(sample) != style:
        return False
    if distance:
        sample_distance = _sample_distance(sample)
        sample_slot = str(((sample or {}).get("run_context") or {}).get("team_trials_distance_slot") or (sample or {}).get("team_trials_distance_slot") or "").strip().lower()
        if sample_distance != distance and sample_slot != distance:
            return False
    return True


def _sample_relevance_score(sample, parent_goals, trainee_card_id, score_mid, spread):
    score = _safe_float(sample.get("score"))
    normalized_score = _clamp((score - score_mid) / spread, -2.0, 2.0)
    factor_quality = _sample_factor_quality(sample, parent_goals)
    desired_hits = sum(_safe_int(value) for value in (factor_quality.get("desired_hits") or {}).values())
    desired_three = sum(_safe_int(value) for value in (factor_quality.get("desired_three_star_hits") or {}).values())
    source_bonus = SOURCE_QUALITY_BONUS.get(str(sample.get("source") or ""), 0.0)
    trainee_bonus = 0.2 if trainee_card_id and _sample_trainee_card_id(sample) == trainee_card_id else 0.0
    return normalized_score + (desired_hits * 0.18) + (desired_three * 0.45) + source_bonus + trainee_bonus


def _relevant_builder_samples(samples, parent_goals, trainee_card_id, style="", distance=""):
    goal_signature = _goal_signature(parent_goals)
    with_supports = [sample for sample in samples or [] if len(_sample_support_ids(sample)) >= 3]
    contextual = [sample for sample in with_supports if _matches_style_distance(sample, style=style, distance=distance)]
    scoped_pool = contextual if len(contextual) >= 4 else with_supports
    exact_goal = [sample for sample in scoped_pool if _goal_signature(_sample_goals(sample)) == goal_signature]
    if trainee_card_id:
        exact_trainee = [sample for sample in exact_goal if _sample_trainee_card_id(sample) == trainee_card_id]
        if len(exact_trainee) >= 4:
            return exact_trainee, len(exact_trainee), len(exact_goal)
    if len(exact_goal) >= 6:
        return exact_goal, 0, len(exact_goal)
    return scoped_pool, 0, len(exact_goal)


def _learned_target_profile(samples, parent_goals):
    default_profile = _default_target_profile(parent_goals)
    if not samples:
        return default_profile
    scores = [_safe_float(sample.get("score")) for sample in samples]
    score_hi = _percentile(scores, 0.65)
    learned = defaultdict(float)
    weight_total = 0.0
    for sample in samples:
        sample_score = _safe_float(sample.get("score"))
        if sample_score < score_hi:
            continue
        weight = max(0.2, _safe_float(sample.get("sample_weight"), 1.0))
        counts = _type_counts(_sample_cards(sample))
        for type_name, count in counts.items():
            learned[type_name] += count * weight
        weight_total += weight
    if weight_total <= 0:
        return default_profile
    learned_profile = {name: (value / weight_total) for name, value in learned.items()}
    blended = {}
    for type_name in set(default_profile) | set(learned_profile):
        blended[type_name] = (default_profile.get(type_name, 0.0) * 0.45) + (learned_profile.get(type_name, 0.0) * 0.55)
    return blended


def _build_card_priors(owned_cards, samples, parent_goals, trainee_card_id):
    scores = [_safe_float(sample.get("score")) for sample in samples] or [0.0]
    score_mid = _percentile(scores, 0.50)
    spread = max(abs(_percentile(scores, 0.75) - _percentile(scores, 0.25)), 1.0)
    target_profile = _learned_target_profile(samples, parent_goals)
    max_profile = max(target_profile.values()) if target_profile else 1.0
    raw_stats = defaultdict(lambda: {"quality_sum": 0.0, "weight": 0.0, "count": 0})
    for sample in samples:
        relevance = _sample_relevance_score(sample, parent_goals, trainee_card_id, score_mid, spread)
        weight = max(0.1, _safe_float(sample.get("sample_weight"), 1.0))
        for card in _sample_cards(sample):
            stat = raw_stats[_safe_int(card.get("id"))]
            stat["quality_sum"] += relevance * weight
            stat["weight"] += weight
            stat["count"] += 1
    priors = {}
    for card in owned_cards:
        card_id = _safe_int(card.get("id"))
        stat = raw_stats.get(card_id) or {}
        historical = (stat.get("quality_sum", 0.0) / stat.get("weight", 1.0)) if stat.get("weight") else 0.0
        ownership = _ownership_strength(card)
        type_fit = target_profile.get(_normalize_type(card.get("type")), 0.0) / max(1.0, max_profile)
        composite = (historical * 0.82) + (ownership * 0.58) + (type_fit * 0.44)
        reasons = []
        if stat.get("count"):
            reasons.append(f"shows up in {int(stat['count'])} relevant runs")
        if ownership >= 0.78:
            reasons.append("high investment on this account")
        elif ownership >= 0.62:
            reasons.append("solid investment level")
        if type_fit >= 0.75:
            reasons.append(f"fits the {_first_goal(parent_goals, 'blue') or 'balanced'} target profile")
        priors[card_id] = {
            "historical": historical,
            "ownership": ownership,
            "type_fit": type_fit,
            "composite": composite,
            "reasons": reasons,
        }
    return priors, target_profile


def _candidate_supports(owned_cards, priors):
    by_type = defaultdict(list)
    overall = []
    for card in owned_cards:
        card_id = _safe_int(card.get("id"))
        prior = priors.get(card_id) or {}
        row = {**card, **prior}
        by_type[_normalize_type(card.get("type"))].append(row)
        overall.append(row)
    for rows in by_type.values():
        rows.sort(key=lambda row: (row.get("composite", 0.0), row.get("ownership", 0.0)), reverse=True)
    overall.sort(key=lambda row: (row.get("composite", 0.0), row.get("ownership", 0.0)), reverse=True)
    chosen = []
    seen = set()
    for row in overall[:18]:
        if row["id"] not in seen:
            seen.add(row["id"])
            chosen.append(row)
    for rows in by_type.values():
        for row in rows[:5]:
            if row["id"] not in seen:
                seen.add(row["id"])
                chosen.append(row)
    chosen.sort(key=lambda row: (row.get("composite", 0.0), row.get("ownership", 0.0)), reverse=True)
    return chosen[:24]


def _evaluate_combo(cards, target_profile, parent_goals):
    counts = _type_counts(cards)
    distinct_types = len([name for name, count in counts.items() if count > 0])
    if distinct_types < 2:
        return None
    blue_goal = _first_goal(parent_goals, "blue").strip().lower()
    primary_type = {
        "speed": "Speed",
        "stamina": "Stamina",
        "power": "Power",
        "guts": "Guts",
        "wit": "Wit",
    }.get(blue_goal)
    if any(count > 3 and type_name != primary_type for type_name, count in counts.items()):
        return None
    sum_composite = sum(_safe_float(card.get("composite")) for card in cards)
    sum_historical = sum(_safe_float(card.get("historical")) for card in cards)
    avg_ownership = statistics.mean([_safe_float(card.get("ownership")) for card in cards]) if cards else 0.0
    dist = 0.0
    for type_name in set(target_profile) | set(counts):
        dist += abs(counts.get(type_name, 0) - target_profile.get(type_name, 0.0))
    type_bonus = 1.2 - _clamp(dist / 5.0, 0.0, 1.2)
    goal_bonus = _goal_focus_bonus(cards, parent_goals) * 0.5
    diversity_bonus = min(distinct_types, 4) * 0.08
    raw_score = sum_composite + (sum_historical * 0.12) + type_bonus + diversity_bonus + goal_bonus + (avg_ownership * 0.25)
    return {
        "cards": cards,
        "type_counts": dict(counts),
        "distinct_types": distinct_types,
        "raw_score": raw_score,
        "average_ownership": avg_ownership,
        "average_historical": (sum_historical / len(cards)) if cards else 0.0,
    }


def _describe_profile_gap(counts, target_profile):
    gaps = []
    for type_name, target in sorted(target_profile.items(), key=lambda item: item[1], reverse=True):
        actual = counts.get(type_name, 0)
        if target - actual >= 0.75:
            gaps.append(f"short on {type_name}")
        elif actual - target >= 1.1:
            gaps.append(f"heavy on {type_name}")
    return gaps


def synthesize_deck(available_supports, samples, *, parent_goals=None, support_catalog=None, trainee=None, friend=None, current_deck=None, style="", distance=""):
    parent_goals = _normalize_parent_goals(parent_goals)
    support_catalog = support_catalog or {}
    owned_cards = _normalize_support_pool(available_supports, support_catalog=support_catalog)
    trainee_name = _normalize_character_name((trainee or {}).get("name"))
    friend_name = _normalize_character_name((friend or {}).get("support_name") or (friend or {}).get("name"))
    legal_owned = []
    for card in owned_cards:
        card_name = _normalize_character_name(card.get("name"))
        if trainee_name and card_name == trainee_name:
            continue
        if friend_name and card_name == friend_name:
            continue
        legal_owned.append(card)
    if len(legal_owned) < 5:
        return {
            "schema": "sweepy_deck_builder_v1",
            "status": "insufficient_pool",
            "message": "Not enough legal owned supports remain after trainee/friend restrictions.",
            "cards": [],
        }

    trainee_card_id = _safe_int((trainee or {}).get("id") or (trainee or {}).get("card_id"))
    relevant_samples, exact_trainee_samples, exact_goal_samples = _relevant_builder_samples(
        samples,
        parent_goals,
        trainee_card_id,
        style=style,
        distance=distance,
    )
    priors, target_profile = _build_card_priors(legal_owned, relevant_samples, parent_goals, trainee_card_id)
    candidates = _candidate_supports(legal_owned, priors)
    if len(candidates) < 5:
        return {
            "schema": "sweepy_deck_builder_v1",
            "status": "insufficient_candidates",
            "message": "Could not score enough supports to build a deck yet.",
            "cards": [],
        }

    combos = []
    for combo in itertools.combinations(candidates, 5):
        evaluated = _evaluate_combo(list(combo), target_profile, parent_goals)
        if evaluated:
            combos.append(evaluated)
    if not combos:
        return {
            "schema": "sweepy_deck_builder_v1",
            "status": "no_legal_combo",
            "message": "No legal 5-support combination passed the current deck rules.",
            "cards": [],
        }
    combos.sort(key=lambda row: (row["raw_score"], row["average_ownership"], row["average_historical"]), reverse=True)
    best = combos[0]

    support_by_id = {card["id"]: card for card in legal_owned}
    current_cards = []
    for row in (current_deck or {}).get("cards") or []:
        card_id = _safe_int(row.get("id") or row.get("support_card_id"))
        card = support_by_id.get(card_id)
        if card:
            current_cards.append({**card, **(priors.get(card_id) or {})})
        else:
            normalized = _normalize_card(row, support_catalog=support_catalog)
            if normalized:
                current_cards.append({**normalized, **(priors.get(_safe_int(normalized.get("id"))) or {})})
    current_eval = _evaluate_combo(current_cards, target_profile, parent_goals) if len(current_cards) >= 5 else None

    recommended_ids = {card["id"] for card in best["cards"]}
    current_ids = {card["id"] for card in current_cards}
    adds = [card for card in best["cards"] if card["id"] not in current_ids]
    removes = sorted(
        [card for card in current_cards if card["id"] not in recommended_ids],
        key=lambda row: (_safe_float(row.get("composite")), _safe_float(row.get("ownership"))),
    )
    swap_suggestions = []
    for add, remove in zip(adds[:3], removes[:3]):
        swap_suggestions.append({
            "add": {"id": add["id"], "name": add["name"], "type": add["type"], "rarity": add["rarity"]},
            "remove": {"id": remove["id"], "name": remove["name"], "type": remove["type"], "rarity": remove["rarity"]},
            "reason": f"{add['name']} better matches the current spark goal and account investment than {remove['name']}.",
        })

    current_weaknesses = []
    if current_eval:
        current_weaknesses.extend(_describe_profile_gap(current_eval["type_counts"], target_profile)[:2])
        weak_current = sorted(current_cards, key=lambda row: (_safe_float(row.get("composite")), _safe_float(row.get("ownership"))))[:2]
        for row in weak_current:
            if _safe_float(row.get("ownership")) < 0.62 or _safe_float(row.get("historical")) < -0.1:
                current_weaknesses.append(f"{row.get('name')} is one of the weaker current slots")
    else:
        current_weaknesses.append("No current 5-card deck selected for comparison")

    if current_eval:
        gain = round(best["raw_score"] - current_eval["raw_score"], 3)
        if gain > 0.2:
            message = f"Built a stronger 5-support deck for this run than the current slot by leaning harder into {(_first_goal(parent_goals, 'blue') or 'balanced')} and your best invested cards."
            status = "upgrade"
        else:
            message = f"The current deck is already close to optimal; this build is only a small adjustment."
            status = "minor_tune"
    else:
        gain = None
        message = f"Built a recommended 5-support deck for {(_first_goal(parent_goals, 'blue') or 'balanced')} parent farming."
        status = "generated"

    cards = []
    max_type_weight = max(target_profile.values()) if target_profile else 1.0
    for card in best["cards"]:
        reasons = list((priors.get(card["id"]) or {}).get("reasons") or [])
        if (target_profile.get(card["type"], 0.0) / max(1.0, max_type_weight)) >= 0.8:
            reasons.append("fills a high-priority support slot")
        cards.append({
            "id": card["id"],
            "name": card["name"],
            "type": card["type"],
            "rarity": card["rarity"],
            "limit_break_count": _safe_int(card.get("limit_break_count")),
            "exp": _safe_int(card.get("exp")),
            "level": _safe_int(card.get("level")),
            "ownership": round(_safe_float(card.get("ownership")), 4),
            "historical": round(_safe_float(card.get("historical")), 4),
            "composite": round(_safe_float(card.get("composite")), 4),
            "reasons": reasons[:3],
        })
    cards.sort(key=lambda row: (row["composite"], row["ownership"]), reverse=True)

    confidence = _confidence_label(len(relevant_samples), len({_sample_trainee_card_id(sample) or tuple(_sample_support_ids(sample)) for sample in relevant_samples}))
    return {
        "schema": "sweepy_deck_builder_v1",
        "status": status,
        "message": message,
        "confidence": confidence,
        "cards": cards,
        "target_type_profile": {key: round(value, 2) for key, value in target_profile.items()},
        "sample_count": len(relevant_samples),
        "same_trainee_samples": exact_trainee_samples,
        "goal_match_samples": exact_goal_samples,
        "current_weaknesses": current_weaknesses[:3],
        "swap_suggestions": swap_suggestions,
        "current_deck_score": round(current_eval["raw_score"], 4) if current_eval else None,
        "recommended_score": round(best["raw_score"], 4),
        "score_gain": gain,
        "type_counts": best["type_counts"],
    }


def advise_decks(available_decks, samples, *, current_deck_id=None, parent_goals=None, support_catalog=None, style="", distance=""):
    support_catalog = support_catalog or {}
    parent_goals = _normalize_parent_goals(parent_goals)
    candidate_decks = []
    for deck in available_decks or []:
        normalized = _normalize_deck(deck, support_catalog=support_catalog)
        if normalized:
            candidate_decks.append(normalized)
    if not candidate_decks:
        return {
            "schema": "sweepy_deck_advice_v1",
            "status": "no_decks",
            "detail": "No synced decks are available to score.",
        }

    current_deck_id = _safe_int(current_deck_id)
    current_deck = next((deck for deck in candidate_decks if _safe_int(deck.get("id")) == current_deck_id), None)
    goal_signature = _goal_signature(parent_goals)

    deck_samples = []
    for sample in samples or []:
        support_ids = _sample_support_ids(sample)
        if len(support_ids) < 3:
            continue
        score = _safe_float(sample.get("score"), None)
        if score is None:
            continue
        deck_samples.append({
            "support_ids": tuple(support_ids),
            "cards": _sample_cards(sample, support_catalog=support_catalog),
            "score": score,
            "weight": max(0.1, _safe_float(sample.get("sample_weight"), 1.0)),
            "source": str(sample.get("source") or "unknown"),
            "path": str(sample.get("path") or ""),
            "goal_signature": _goal_signature(_sample_goals(sample)),
            "style": _sample_style(sample),
            "distance": _sample_distance(sample),
            "deck_name": str(((sample.get("run_context") or {}).get("deck_name") or "")).strip(),
        })

    relevant_samples = [sample for sample in deck_samples if sample["goal_signature"] == goal_signature]
    contextual_relevant = [sample for sample in relevant_samples if _matches_style_distance(sample, style=style, distance=distance)]
    if len(contextual_relevant) >= 4:
        relevant_samples = contextual_relevant
    if not relevant_samples:
        contextual_all = [sample for sample in deck_samples if _matches_style_distance(sample, style=style, distance=distance)]
        relevant_samples = contextual_all if len(contextual_all) >= 4 else deck_samples
    if not relevant_samples:
        return {
            "schema": "sweepy_deck_advice_v1",
            "status": "insufficient_data",
            "detail": "No historical runs with deck data are available yet.",
            "goal_signature": goal_signature,
            "goal_summary": parent_goals,
        }

    scores = [sample["score"] for sample in relevant_samples]
    score_hi = _percentile(scores, 0.75)
    score_lo = _percentile(scores, 0.25)
    score_mid = _percentile(scores, 0.50)
    spread = max(abs(score_hi - score_lo), 1.0)

    card_stats = defaultdict(lambda: {
        "count": 0,
        "weight": 0.0,
        "score_sum": 0.0,
        "top_weight": 0.0,
        "bottom_weight": 0.0,
        "name": "",
        "type": "Unknown",
    })
    exact_deck_stats = defaultdict(lambda: {
        "count": 0,
        "weight": 0.0,
        "score_sum": 0.0,
        "top_weight": 0.0,
        "bottom_weight": 0.0,
        "deck_name": "",
    })
    profile_counts = defaultdict(float)
    profile_weight = 0.0

    for sample in relevant_samples:
        weight = sample["weight"]
        normalized_score = _clamp((sample["score"] - score_mid) / spread, -2.0, 2.0)
        band = 1 if sample["score"] >= score_hi else (-1 if sample["score"] <= score_lo else 0)
        signature = tuple(sample["support_ids"])
        exact = exact_deck_stats[signature]
        exact["count"] += 1
        exact["weight"] += weight
        exact["score_sum"] += normalized_score * weight
        exact["deck_name"] = exact["deck_name"] or sample["deck_name"]
        if band > 0:
            exact["top_weight"] += weight
        elif band < 0:
            exact["bottom_weight"] += weight

        type_counts = _type_counts(sample["cards"])
        if band > 0:
            profile_weight += weight
            for type_name, count in type_counts.items():
                profile_counts[type_name] += count * weight
        for card in sample["cards"]:
            stat = card_stats[card["id"]]
            stat["count"] += 1
            stat["weight"] += weight
            stat["score_sum"] += normalized_score * weight
            stat["name"] = stat["name"] or card["name"]
            stat["type"] = stat["type"] if stat["type"] != "Unknown" else card["type"]
            if band > 0:
                stat["top_weight"] += weight
            elif band < 0:
                stat["bottom_weight"] += weight

    learned_type_profile = {}
    if profile_weight > 0:
        for type_name, value in profile_counts.items():
            learned_type_profile[type_name] = round(value / profile_weight, 3)

    deck_rows = []
    for deck in candidate_decks:
        cards = list(deck.get("cards") or [])
        signature = tuple(card["id"] for card in cards)
        exact = exact_deck_stats.get(signature) or {}
        exact_weight = _safe_float(exact.get("weight"))
        exact_history = {
            "sample_count": _safe_int(exact.get("count")),
            "weighted_score": round((exact.get("score_sum", 0.0) / exact_weight), 4) if exact_weight else 0.0,
            "top_rate": round((exact.get("top_weight", 0.0) / exact_weight), 4) if exact_weight else 0.0,
            "bottom_rate": round((exact.get("bottom_weight", 0.0) / exact_weight), 4) if exact_weight else 0.0,
        }
        card_scores = []
        observed_cards = 0
        evidence_weight = 0.0
        top_card_names = []
        for card in cards:
            stat = card_stats.get(card["id"])
            if not stat or stat["weight"] <= 0:
                continue
            observed_cards += 1
            evidence_weight += stat["weight"]
            prior = stat["score_sum"] / stat["weight"]
            prior += 0.35 * ((stat["top_weight"] - stat["bottom_weight"]) / stat["weight"])
            card_scores.append(prior)
            if stat["top_weight"] > stat["bottom_weight"]:
                top_card_names.append(card["name"])
        card_fit = statistics.mean(card_scores) if card_scores else 0.0
        type_counts = _type_counts(cards)
        if learned_type_profile:
            dist = 0.0
            for type_name in set(learned_type_profile) | set(type_counts):
                dist += abs(type_counts.get(type_name, 0) - learned_type_profile.get(type_name, 0.0))
            type_fit = 1.0 - _clamp(dist / 10.0, 0.0, 1.0)
        else:
            type_fit = 0.5
        goal_fit = _goal_focus_bonus(cards, parent_goals)
        exact_component = exact_history["weighted_score"] * min(1.0, math.sqrt(max(0.0, exact_history["sample_count"])) / 3.0)
        evidence_coverage = observed_cards / max(1, len(cards))
        evidence_component = evidence_coverage * 0.55
        raw_score = (
            (exact_component * 0.95)
            + (card_fit * 0.85)
            + evidence_component
            + ((type_fit * 2.0 - 1.0) * 0.35)
            + ((goal_fit * 2.0 - 1.0) * 0.25)
        )
        reasons = []
        if exact_history["sample_count"] >= 2:
            reasons.append(f"Seen in {exact_history['sample_count']} matching runs.")
        if top_card_names:
            reasons.append("Carries strong learned cards: " + ", ".join(top_card_names[:3]) + ".")
        if learned_type_profile:
            dominant = sorted(learned_type_profile.items(), key=lambda item: item[1], reverse=True)[:2]
            if dominant:
                reasons.append("Closer to the learned support-type profile: " + ", ".join(f"{name} {value:.1f}" for name, value in dominant) + ".")
        deck_rows.append({
            "deck_id": _safe_int(deck.get("id")),
            "name": deck.get("name") or f"Deck {_safe_int(deck.get('id'))}",
            "cards": cards,
            "raw_score": raw_score,
            "card_fit": round(card_fit, 4),
            "type_fit": round(type_fit, 4),
            "goal_fit": round(goal_fit, 4),
            "evidence_coverage": round(evidence_coverage, 4),
            "evidence_weight": round(evidence_weight, 4),
            "exact_history": exact_history,
            "reasons": reasons,
        })

    raw_values = [row["raw_score"] for row in deck_rows]
    raw_min = min(raw_values)
    raw_max = max(raw_values)
    spread = max(raw_max - raw_min, 0.0001)
    for row in deck_rows:
        row["score"] = round(100.0 * ((row["raw_score"] - raw_min) / spread), 1) if raw_max != raw_min else 50.0
    deck_rows.sort(key=lambda row: (row["raw_score"], row["exact_history"]["sample_count"], row["evidence_coverage"]), reverse=True)

    best_deck = deck_rows[0]
    current_row = next((row for row in deck_rows if row["deck_id"] == current_deck_id), None)
    top_cards = _top_card_rows(card_stats)[:5]
    confidence = _confidence_label(len(relevant_samples), len({tuple(sample["support_ids"]) for sample in relevant_samples}))
    fallback_mode = not any(sample["goal_signature"] == goal_signature for sample in deck_samples)

    if current_row is None:
        message = f"Best saved deck for this parent goal looks like {best_deck['name']}."
        status = "suggest_deck"
    else:
        gap = best_deck["raw_score"] - current_row["raw_score"]
        if best_deck["deck_id"] != current_row["deck_id"] and gap > 0.18:
            message = (
                f"{current_row['name']} looks weaker for this parent goal than {best_deck['name']}. "
                f"Try {best_deck['name']} instead."
            )
            status = "suboptimal"
        else:
            message = f"{current_row['name']} is currently the strongest saved deck for this parent goal."
            status = "optimal"

    return {
        "schema": "sweepy_deck_advice_v1",
        "status": status,
        "message": message,
        "goal_signature": goal_signature,
        "goal_summary": parent_goals,
        "goal_label": _first_goal(parent_goals, "blue") or "balanced",
        "style_context": style or "",
        "distance_context": distance or "",
        "confidence": confidence,
        "fallback_mode": fallback_mode,
        "sample_count": len(relevant_samples),
        "source_counts": dict(Counter(sample.get("source") or "unknown" for sample in relevant_samples)),
        "unique_deck_count": len({tuple(sample["support_ids"]) for sample in relevant_samples}),
        "learned_type_profile": learned_type_profile,
        "top_cards": top_cards,
        "current_deck": current_row,
        "best_deck": best_deck,
        "alternatives": deck_rows[:3],
    }


def build_deck_advice(
    base_dir,
    available_decks,
    *,
    current_deck_id=None,
    parent_goals=None,
    support_catalog=None,
    available_supports=None,
    current_deck=None,
    trainee=None,
    friend=None,
    recent=None,
    style="",
    distance="",
):
    parent_goals = _normalize_parent_goals(parent_goals)
    support_catalog = support_catalog or {}
    recent = recent if recent is not None else 20
    samples = _collect_runtime_deck_advice_samples(
        base_dir,
        parent_goals=parent_goals,
        recent_bot_logs=recent,
    )
    advice = advise_decks(
        available_decks,
        samples,
        current_deck_id=current_deck_id,
        parent_goals=parent_goals,
        support_catalog=support_catalog,
        style=style,
        distance=distance,
    )
    if available_supports:
        advice["recommended_build"] = synthesize_deck(
            available_supports,
            samples,
            parent_goals=parent_goals,
            support_catalog=support_catalog,
            trainee=trainee,
            friend=friend,
            current_deck=current_deck,
            style=style,
            distance=distance,
        )
    return advice
