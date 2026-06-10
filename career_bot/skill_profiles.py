STYLE_SKILLS = {
    "front_runner": [
        "Front Runner Straightaways", "Front Runner Corners", "Front Runner Savvy",
        "Taking the Lead", "Early Lead", "Fast-Paced", "Keeping the Lead",
        "Leader's Pride", "Moxie", "Groundwork", "Tail Held High", "Slipstream",
    ],
    "pace_chaser": [
        "Pace Chaser Straightaways", "Pace Chaser Corners", "Pace Chaser Savvy",
        "Preferred Position", "Go with the Flow", "Up-Tempo", "Hydrate",
        "Groundwork", "Tail Held High", "Slipstream",
    ],
    "late_surger": [
        "Late Surger Straightaways", "Late Surger Corners", "Late Surger Savvy",
        "Position Pilfer", "Slick Surge", "Outer Swell", "Straightaway Spurt",
        "Passing Pro", "Groundwork", "Tail Held High", "Slipstream",
    ],
    "end_closer": [
        "End Closer Straightaways", "End Closer Corners", "End Closer Savvy",
        "Gap Closer", "Strategist", "Passing Pro", "Straightaway Spurt",
        "Groundwork", "Tail Held High", "Slipstream",
    ],
}

DISTANCE_SKILLS = {
    "sprint": [
        "Sprint Straightaways", "Sprint Corners", "Sprinting Gear", "Turbo Sprint",
        "Acceleration", "Straightaway Acceleration",
    ],
    "mile": [
        "Mile Straightaways", "Mile Corners", "Mile Maven", "Up-Tempo",
        "Straightaway Adept", "Corner Adept",
    ],
    "medium": [
        "Medium Straightaways", "Medium Corners", "Straightaway Spurt",
        "Homestretch Haste", "Corner Adept", "Straightaway Adept",
    ],
    "long": [
        "Long Straightaways", "Long Corners", "Swinging Maestro", "Corner Recovery",
        "Breath of Fresh Air", "Straightaway Recovery", "Deep Breaths",
        "Stamina to Spare", "Cooldown",
    ],
}

COMMON_SKILLS = [
    "Corner Adept", "Straightaway Adept", "Corner Acceleration", "Focus",
    "Groundwork", "Slipstream", "Tail Held High",
]

COMMA_SKILL_NAMES = [
    "1,500,000 CC",
    "15,000,000 CC",
    "A Lifelong Dream, A Moment's Flight",
    "Arrows Whistle, Shadows Disperse",
    "Chin Up, Derby Umamusume!",
    "Forward, March!",
    "Go, Go, Mun!",
    "I Can Win Sometimes, Right?",
    "Moving Past, and Beyond",
    "Ready, Go!",
    "Where There's a Will, There's a Way",
]


def split_skill_text(value):
    if isinstance(value, list):
        rows = value
    else:
        # Newlines are the canonical separator. Commas used to be split too,
        # but real uma skill names contain commas — splitting on comma chopped
        # skills like "Ready, Set, Go!" into ["Ready", "Set", "Go!"] which then
        # poisoned blacklists with single-word fragments. Now we split on
        # newlines only; if the user pastes a comma-separated list they need
        # newlines between entries (or use the GUI to manage them).
        rows = []
        for line in str(value or "").splitlines():
            protected = {}
            protected_line = line
            for i, skill_name in enumerate(sorted(COMMA_SKILL_NAMES, key=len, reverse=True)):
                token = f"__COMMA_SKILL_{i}__"
                if skill_name in protected_line:
                    protected[token] = skill_name
                    protected_line = protected_line.replace(skill_name, token)
            for part in protected_line.split(","):
                text = part.strip()
                rows.append(protected.get(text, text))
    return [str(item).strip() for item in rows if str(item).strip()]


def sanitize_blacklist(entries):
    """Remove skill names that should NEVER be blacklisted because the bot's
    style/distance/common profiles want to buy them. Saves users (and the bot)
    from accidentally banning the very skills the rest of the preset says are
    priority targets — which would silently make those targets unbuyable.
    """
    cleaned = split_skill_text(entries)
    protected = set()
    for skills in STYLE_SKILLS.values():
        protected.update(skills)
    for skills in DISTANCE_SKILLS.values():
        protected.update(skills)
    protected.update(COMMON_SKILLS)
    return dedupe(s for s in cleaned if s not in protected)


def dedupe(items):
    result = []
    seen = set()
    for item in items:
        key = "".join(ch for ch in str(item).lower() if ch.isalnum())
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def normalize_style(value):
    text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "front": "front_runner",
        "nige": "front_runner",
        "pace": "pace_chaser",
        "senko": "pace_chaser",
        "late": "late_surger",
        "sashi": "late_surger",
        "closer": "end_closer",
        "end": "end_closer",
        "oikomi": "end_closer",
    }
    return aliases.get(text, text if text in STYLE_SKILLS else "")


def normalize_distance(value):
    text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "short": "sprint",
        "middle": "medium",
        "mid": "medium",
    }
    return aliases.get(text, text if text in DISTANCE_SKILLS else "")


def build_skill_priority_rows(buy_on_sight=None, style="", distance=""):
    buy = dedupe(split_skill_text(buy_on_sight))
    style_key = normalize_style(style)
    distance_key = normalize_distance(distance)
    profile = []
    profile.extend(STYLE_SKILLS.get(style_key, []))
    profile.extend(DISTANCE_SKILLS.get(distance_key, []))
    profile.extend(COMMON_SKILLS)
    rows = []
    if buy:
        rows.append(buy)
    rows.append(dedupe(profile))
    return [row for row in rows if row]
