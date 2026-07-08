(() => {
    const STATS = ["speed", "stamina", "power", "guts", "wit"];
    const LABELS = { speed: "Speed", stamina: "Stamina", power: "Power", guts: "Guts", wit: "Wit", sp: "SP", energy: "Energy" };
    const TYPE_CLASSES = { Speed: "type-speed", Stamina: "type-stamina", Power: "type-power", Guts: "type-guts", Wit: "type-wit", Pal: "type-pal", Group: "type-pal" };

    const $ = id => document.getElementById(id);
    const els = {
        pageStatus: $("standalone-status"),
        scenario: $("training-sim-scenario"),
        level: $("training-sim-level"),
        mood: $("training-sim-mood"),
        growthOpen: $("training-sim-growth-open"),
        growthSummary: $("training-sim-growth-summary"),
        growthModal: $("training-sim-growth-modal"),
        growthClose: $("training-sim-growth-close"),
        growthFields: $("training-sim-growth-fields"),
        growthSave: $("training-sim-growth-save"),
        clearCards: $("training-sim-clear-cards"),
        reset: $("training-sim-reset"),
        megaphones: $("training-sim-megaphones"),
        weights: $("training-sim-weights"),
        overcapStat: $("training-sim-overcap-stat"),
        itemSummary: $("training-sim-item-summary"),
        yearEffects: $("training-sim-year-effects"),
        yearEffectStatus: $("training-sim-year-effect-status"),
        supportTypeGate: $("training-sim-support-type-gate"),
        status: $("training-sim-status"),
        ownedOnly: $("training-sim-owned-only"),
        search: $("training-sim-card-search"),
        filterRow: $("training-sim-filter-row"),
        cardToolbox: $("training-sim-card-toolbox"),
        areas: $("training-sim-areas"),
        tilesHint: $("training-sim-tiles-hint"),
        itemsBlock: $("training-sim-items-block"),
        gimmickBar: $("training-sim-gimmick-bar"),
        yearTabs: $("training-sim-year-tabs"),
        gimmickTitle: $("training-sim-gimmick-title"),
        noGimmick: $("training-sim-no-gimmick"),
        scenarioPanelTitle: $("training-sim-scenario-panel-title")
    };

    function selectedScenarioRow() {
        const sel = String((els.scenario && els.scenario.value) || state.scenario || "");
        return ((state.meta || {}).scenarios || []).find(row => String(row.selector) === sel) || null;
    }
    // Fallback mirror of main.py TRAINING_SIM_SCENARIO_GIMMICKS for servers
    // started before the backend gained per-scenario gimmicks in /meta —
    // without it an older backend would hide EVERY panel (incl. Hakodate on 14).
    // Mirrors main.py TRAINING_SIM_SCENARIO_GIMMICKS exactly. Selector "1" =
    // らっしゃい！トレセン軒！ (JP newest; its in-game scenario_id is 14, which is
    // what the user calls it) -> regional venue/year toggles, NO megaphone shop.
    // GameWith selector "14" is a different scenario — do NOT attach these there.
    const GIMMICK_FALLBACK = { mant_base: ["items"], "1": ["year_effects"] };
    function scenarioGimmicks() {
        const row = selectedScenarioRow();
        if (row && Array.isArray(row.gimmicks)) return new Set(row.gimmicks);
        const sel = String((row && row.selector) || (els.scenario && els.scenario.value) || state.scenario || "");
        return new Set(GIMMICK_FALLBACK[sel] || []);
    }
    function applyGimmickVisibility() {
        // uma.guide-style: only render the controls the selected scenario has.
        // Trackblazer (mant_base) -> megaphone/weight items; current JP
        // scenario 14 (GameWith newest selector "1") -> regional venue/year
        // toggles; others -> note.
        const gimmicks = scenarioGimmicks();
        const row = selectedScenarioRow();
        const hasItems = gimmicks.has("items");
        const hasYear = gimmicks.has("year_effects");
        if (els.itemsBlock) els.itemsBlock.hidden = !hasItems;
        if (els.gimmickBar) els.gimmickBar.hidden = !hasYear;
        if (els.gimmickTitle && hasYear) els.gimmickTitle.textContent = `${(row && row.name) || "Scenario"} — Regional Venue Bonuses`;
        // The details panel only hosts shop items / the note now; the year bar
        // at the top replaces it entirely for venue scenarios.
        const panel = $("training-sim-bonuses");
        if (panel) panel.hidden = hasYear && !hasItems;
        if (els.noGimmick) els.noGimmick.hidden = hasItems || hasYear;
        if (els.scenarioPanelTitle) {
            const name = (row && row.name) || "Scenario";
            els.scenarioPanelTitle.textContent = hasItems ? `${name} — Shop Items`
                : hasYear ? `${name} — Regional Bonuses`
                : `${name} — Scenario Bonuses`;
        }
    }

    function updateArmedHint() {
        if (!els.tilesHint) return;
        if (state.selectedCard) {
            const name = state.selectedCard.name || `Support ${cardId(state.selectedCard)}`;
            els.tilesHint.textContent = `▸ Placing: ${name} — click a tile to drop it.`;
            els.tilesHint.classList.add("is-armed-hint");
        } else {
            els.tilesHint.textContent = "Pick a card → click a tile to place it. Click a placed card to remove.";
            els.tilesHint.classList.remove("is-armed-hint");
        }
    }

    function localGet(key, fallback = "") {
        try {
            const value = localStorage.getItem(key);
            return value == null ? fallback : value;
        } catch (e) {
            return fallback;
        }
    }
    function localSet(key, value) {
        try {
            localStorage.setItem(key, String(value));
        } catch (e) {}
    }
    function localBool(key, fallback = false) {
        const value = localGet(key, fallback ? "1" : "0");
        return ["1", "true", "yes", "on"].includes(String(value).trim().toLowerCase());
    }
    function localJson(key, fallback) {
        try {
            const parsed = JSON.parse(localStorage.getItem(key) || "null");
            return parsed && typeof parsed === "object" ? parsed : fallback;
        } catch (e) {
            return fallback;
        }
    }
    function normalizeGrowth(raw) {
        const out = {};
        STATS.forEach(stat => {
            const n = Number(raw && raw[stat] != null ? raw[stat] : 0);
            if (Number.isFinite(n) && n !== 0) out[stat] = Math.max(0, Math.min(30, n));
        });
        return out;
    }
    function growthEquals(a, b) {
        const left = normalizeGrowth(a);
        const right = normalizeGrowth(b);
        return STATS.every(stat => Number(left[stat] || 0) === Number(right[stat] || 0));
    }
    function saveGrowth() {
        localSet("trainingSimGrowth", JSON.stringify(normalizeGrowth(state.growth || {})));
    }
    function setGrowth(next, persist = true) {
        state.growth = normalizeGrowth(next || {});
        if (persist) saveGrowth();
    }
    function growthSummaryText(growth) {
        const normalized = normalizeGrowth(growth || {});
        const parts = STATS
            .filter(stat => Number(normalized[stat] || 0) !== 0)
            .map(stat => `${LABELS[stat]} +${Number(normalized[stat])}%`);
        return parts.length ? parts.join(" / ") : "None";
    }
    function escapeHtml(value) {
        return String(value == null ? "" : value).replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
    }
    function escapeAttr(value) {
        return escapeHtml(value);
    }
    async function apiJson(url, options = {}) {
        const response = await fetch(url, options);
        const text = await response.text();
        let data = {};
        try {
            data = text ? JSON.parse(text) : {};
        } catch (e) {
            data = { detail: text };
        }
        if (!response.ok) {
            throw new Error(data.detail || data.error || `${response.status} ${response.statusText}`);
        }
        return data;
    }

    const state = {
        meta: null,
        result: null,
        selectedCard: null,
        selectedArea: "speed",
        areas: { speed: [], stamina: [], power: [], guts: [], wit: [] },
        npc: { speed: 0, stamina: 0, power: 0, guts: 0, wit: 0 },
        scenario: localGet("trainingSimScenario", ""),
        level: Number(localGet("trainingSimLevel", "5")) || 5,
        mood: Number(localGet("trainingSimMood", "0.2")),
        growth: normalizeGrowth(localJson("trainingSimGrowth", {})),
        draftGrowth: {},
        megaphonePct: Number(localGet("trainingSimMegaphonePct", "0")) || 0,
        weightFacilities: {},
        yearEffects: localJson("trainingSimYearEffects", {}),
        gimmickYear: localGet("trainingSimGimmickYear", "Junior Year"),
        enforceSupportTypes: localBool("trainingSimEnforceSupportTypes", true),
        overcapStat: localBool("trainingSimOvercapStat", false),
        ownedOnly: localBool("trainingSimOwnedOnly", false),
        typeFilter: "all",
        rarityFilter: "all",
        search: ""
    };

    let calcTimer = 0;
    let calcSeq = 0;

    function statLabel(stat) {
        return LABELS[stat] || String(stat || "").toUpperCase();
    }
    function typeClass(type) {
        return TYPE_CLASSES[type] || "";
    }
    function cardId(card) {
        return Number(card && (card.support_card_id || card.id) || 0);
    }
    function lbLabel(lb) {
        const value = Math.max(0, Math.min(4, Number(lb || 0)));
        return value >= 4 ? "MLB" : `${value}LB`;
    }
    function clampLb(value) {
        const n = Number(value);
        return Math.max(0, Math.min(4, Number.isFinite(n) ? n : 4));
    }
    function lbOptions(selectedLb) {
        const selected = clampLb(selectedLb);
        return [0, 1, 2, 3, 4].map(lb =>
            `<option value="${lb}" ${lb === selected ? "selected" : ""}>${lbLabel(lb)}</option>`
        ).join("");
    }
    function defaultAreas() {
        return { speed: [], stamina: [], power: [], guts: [], wit: [] };
    }
    function defaultNpc() {
        return { speed: 0, stamina: 0, power: 0, guts: 0, wit: 0 };
    }
    function weightFacilitiesArray() {
        return STATS.filter(stat => state.weightFacilities && state.weightFacilities[stat]);
    }
    function selectedYearEffectIds() {
        return Object.keys(state.yearEffects || {}).filter(id => !!state.yearEffects[id]);
    }
    function saveYearEffects() {
        localSet("trainingSimYearEffects", JSON.stringify(state.yearEffects || {}));
    }
    function findCard(id) {
        const numericId = Number(id || 0);
        return ((state.meta && state.meta.cards) || []).find(card => cardId(card) === numericId) || null;
    }
    function placementForCard(card) {
        const id = cardId(card);
        const rawLb = card && (card.limit_break_count ?? card.lb);
        const lb = clampLb(rawLb == null ? 4 : rawLb);
        return { support_card_id: id, lb: card && card.owned ? lb : 4, fb: true };
    }
    function cardMatchesTile(card, stat) {
        // Friendship applies when the card's type matches the facility;
        // Pal/Group cards always count as matching (uma.guide parity).
        const type = String((card && card.type) || "");
        return type === statLabel(stat) || type === "Pal" || type === "Group";
    }
    function removeCardEverywhere(id) {
        const numericId = Number(id || 0);
        STATS.forEach(stat => {
            state.areas[stat] = (state.areas[stat] || []).filter(row => Number(row.support_card_id || row.id || 0) !== numericId);
        });
    }
    function selectedMood() {
        const value = Number((els.mood && els.mood.value) || state.mood || 0);
        return Number.isFinite(value) ? value : 0;
    }
    function selectedLevel() {
        const value = Number((els.level && els.level.value) || state.level || 5);
        return Math.max(1, Math.min(5, Number.isFinite(value) ? value : 5));
    }
    function selectedScenario() {
        return (els.scenario && els.scenario.value) || state.scenario || (state.meta && state.meta.default_scenario) || "mant_base";
    }
    function renderGrowthControls() {
        const growth = normalizeGrowth(state.growth || {});
        state.growth = growth;
        if (els.growthSummary) els.growthSummary.textContent = growthSummaryText(growth);
    }
    function renderGrowthModal() {
        if (!els.growthFields) return;
        const draft = normalizeGrowth(state.draftGrowth || state.growth || {});
        state.draftGrowth = draft;
        els.growthFields.innerHTML = STATS.map(stat => `
            <div class="training-sim-growth-row">
                <label class="stat-${stat}" for="training-sim-growth-input-${stat}">${escapeHtml(LABELS[stat])}</label>
                <input id="training-sim-growth-input-${stat}" type="number" min="0" max="30" step="1" value="${escapeAttr(Number(draft[stat] || 0))}" data-growth-modal-stat="${escapeAttr(stat)}">
                <span>%</span>
            </div>
        `).join("");
    }
    function openGrowthModal() {
        if (!els.growthModal) return;
        state.draftGrowth = normalizeGrowth(state.growth || {});
        renderGrowthModal();
        els.growthModal.hidden = false;
        const first = els.growthModal.querySelector("[data-growth-modal-stat]");
        if (first) first.focus();
    }
    function closeGrowthModal() {
        if (els.growthModal) els.growthModal.hidden = true;
    }
    function saveGrowthModal() {
        const next = {};
        if (els.growthFields) {
            els.growthFields.querySelectorAll("[data-growth-modal-stat]").forEach(input => {
                next[input.dataset.growthModalStat] = Number(input.value || 0) || 0;
            });
        }
        setGrowth(next);
        renderGrowthControls();
        closeGrowthModal();
        scheduleCalculation();
    }
    function syncItemSummary() {
        const overcap = state.overcapStat ? " | Trained stat over 1200: primary gain halved" : "";
        if (!scenarioGimmicks().has("items")) {
            els.itemSummary.textContent = `No shop items in this scenario${overcap}`;
            return;
        }
        const weighted = weightFacilitiesArray()[0] || "";
        const selected = Number(state.megaphonePct || 0) + (weighted ? 50 : 0);
        const other = Number(state.megaphonePct || 0);
        const energyChip = weighted ? ` | ${statLabel(weighted)} energy cost: +20%` : "";
        els.itemSummary.textContent = `Selected facility bonus: +${selected}% | Other facilities bonus: +${other}%${energyChip}${overcap}`;
    }
    function payload() {
        const gimmicks = scenarioGimmicks();
        const hasItems = gimmicks.has("items");
        const hasYear = gimmicks.has("year_effects");
        return {
            scenario: selectedScenario(),
            facility_level: selectedLevel(),
            mood: selectedMood(),
            growth: { ...(state.growth || {}) },
            areas: state.areas || defaultAreas(),
            npc_counts: state.npc || defaultNpc(),
            // Scenario-specific gimmicks: only send what this scenario has
            // (the server independently ignores inputs the scenario lacks).
            megaphone_bonus_pct: hasItems ? Number(state.megaphonePct || 0) : 0,
            weight_training_pct: 50,
            weight_energy_pct: 20,
            weight_facilities: hasItems ? weightFacilitiesArray() : [],
            active_scenario_effects: [],
            year_effect_ids: hasYear ? selectedYearEffectIds() : [],
            enforce_support_type_condition: !!state.enforceSupportTypes,
            trained_stat_over_1200: !!state.overcapStat,
            bonded: true
        };
    }
    function gainValue(gains, key) {
        const value = Number((gains || {})[key] || 0);
        return Number.isFinite(value) ? value : 0;
    }
    function formatGain(value, key = "") {
        const n = Number(value || 0);
        if (key === "energy") return n > 0 ? `+${n}` : String(n);
        return n >= 0 ? `+${n}` : String(n);
    }
    function gainClass(value, key = "") {
        const n = Number(value || 0);
        if (key === "energy") return n < 0 ? "is-cost" : n > 0 ? "is-positive" : "";
        return n > 0 ? "is-positive" : n < 0 ? "is-cost" : "";
    }

    function renderControls() {
        const meta = state.meta || {};
        const scenarios = meta.scenarios || [];
        const selected = state.scenario || meta.default_scenario || "mant_base";
        els.scenario.innerHTML = scenarios.map(row => `<option value="${escapeAttr(row.selector)}">${escapeHtml(row.name || row.selector)}</option>`).join("");
        els.scenario.value = scenarios.some(row => String(row.selector) === String(selected)) ? selected : (meta.default_scenario || "mant_base");
        state.scenario = els.scenario.value;
        els.level.value = String(selectedLevel());
        const moods = meta.moods || [];
        els.mood.innerHTML = moods.map(row => `<option value="${escapeAttr(row.value)}">${escapeHtml(row.label)}</option>`).join("");
        els.mood.value = String(state.mood);
        renderGrowthControls();
        els.megaphones.innerHTML = (((meta.item_options || {}).megaphones || []).map(row => `
            <button class="training-sim-chip ${Number(row.value) === Number(state.megaphonePct || 0) ? "is-active" : ""}" type="button" data-megaphone="${escapeAttr(row.value)}">${escapeHtml(row.label)}</button>
        `).join(""));
        // uma.guide/game parity: weights exist for Speed/Stamina/Power/Guts only
        // (there is no Wit weight item), and only ONE facility can be weighted.
        els.weights.innerHTML = STATS.filter(stat => stat !== "wit").map(stat => `
            <button class="training-sim-chip training-sim-chip-stat ${state.weightFacilities[stat] ? "is-active" : ""}" type="button" data-weight="${stat}">
                ${escapeHtml(statLabel(stat))} Weight
            </button>
        `).join("");
        els.overcapStat.classList.toggle("is-active", !!state.overcapStat);
        els.supportTypeGate.checked = !!state.enforceSupportTypes;
        els.ownedOnly.checked = !!state.ownedOnly;
        applyGimmickVisibility();
        syncItemSummary();
        renderYearEffects();
    }

    function yearEffectGroups() {
        return ((state.meta || {}).year_effects || []);
    }
    function basicEffectForYear(group) {
        return ((group && group.effects) || []).find(e => String(e.id || "").endsWith("_basic")) || null;
    }
    function venueEffectsForYear(group) {
        return ((group && group.effects) || []).filter(e => !String(e.id || "").endsWith("_basic"));
    }
    function selectedVenueCount(group) {
        return venueEffectsForYear(group).filter(e => state.yearEffects[String(e.id)]).length;
    }
    function renderYearEffects() {
        // Year-tab gimmick bar: Junior/Classic/Senior buttons; each year allows
        // up to 3 venue buffs; the year's Basic buff auto-applies with any pick.
        if (!els.gimmickBar || !els.yearTabs) return;
        const result = state.result || {};
        const skippedIds = new Set((result.year_effects_skipped || []).map(row => String(row.id || "")));
        const typeCount = Number(result.support_type_count || 0);
        const gateOn = !!state.enforceSupportTypes;
        const groups = yearEffectGroups();
        if (!groups.length) {
            els.yearTabs.innerHTML = "";
            els.yearEffects.innerHTML = '<div class="training-sim-empty">No scenario bonus data loaded.</div>';
            return;
        }
        if (!groups.some(g => String(g.year) === String(state.gimmickYear))) {
            state.gimmickYear = String(groups[0].year || "");
        }
        els.yearTabs.innerHTML = groups.map(group => {
            const year = String(group.year || "Year");
            const count = selectedVenueCount(group);
            const open = year === state.gimmickYear;
            return `
                <button class="training-sim-year-tab ${open ? "is-open" : ""} ${count ? "is-filled" : ""}" type="button" data-gimmick-year="${escapeAttr(year)}">
                    <span>${escapeHtml(year)}</span>
                    <b>${count}/3</b>
                    ${count ? '<em>+ Basic</em>' : ""}
                </button>
            `;
        }).join("");
        const group = groups.find(g => String(g.year) === state.gimmickYear) || groups[0];
        const basic = basicEffectForYear(group);
        const basicOn = !!(basic && state.yearEffects[String(basic.id)]);
        const chips = venueEffectsForYear(group).map(effect => {
            const id = String(effect.id || "");
            const active = !!state.yearEffects[id];
            const blocked = active && skippedIds.has(id);
            const gated = gateOn && effect.requires_four_support_types && typeCount < 4;
            const reason = blocked
                ? `Selected, but inactive: needs 4 card types on tiles (you have ${typeCount}). Untick "Require 4 support types" to force it.`
                : "";
            return `
                <button class="training-sim-effect-chip ${active ? "is-active" : ""} ${blocked ? "is-blocked" : ""} ${gated && !active ? "is-gated" : ""}" type="button" data-year-effect="${escapeAttr(id)}"
                    title="${escapeAttr(reason || (gated ? `Needs 4 card types on tiles (you have ${typeCount})` : ""))}">
                    <span class="training-sim-effect-chip-title">${escapeHtml(effect.label || id)}</span>
                    <span class="training-sim-effect-chip-detail">${escapeHtml(effect.detail || "")}</span>
                    ${blocked ? `<span class="training-sim-effect-chip-blockreason">needs 4 card types — you have ${typeCount}</span>` : ""}
                    ${effect.requires_four_support_types ? `<span class="training-sim-effect-chip-gate ${gated ? "is-unmet" : "is-met"}">${gateOn ? `${Math.min(4, typeCount)}/4 types` : "4 types (off)"}</span>` : ""}
                </button>
            `;
        }).join("");
        const basicRow = basic ? `
            <div class="training-sim-basic-pill ${basicOn ? "is-on" : ""}" title="The year's Basic buff is applied automatically as soon as any venue buff for that year is selected.">
                <b>Basic</b> ${escapeHtml(basic.detail || "")} — ${basicOn ? "auto-applied ✓" : "auto-applies with your first venue pick"}
            </div>` : "";
        els.yearEffects.innerHTML = basicRow + `<div class="training-sim-year-chip-grid">${chips}</div>`;
        const types = (result.support_types || []).join(", ") || "none placed";
        const activeCount = (result.year_effects_active || []).length;
        const skippedCount = (result.year_effects_skipped || []).length;
        if (gateOn && typeCount < 4) {
            els.yearEffectStatus.textContent = `Some regional bonuses need 4 card types on tiles — you have ${typeCount} (${types}). Place more types or untick the gate. | active ${activeCount}, inactive ${skippedCount}`;
        } else {
            const gate = gateOn ? `4-type gate met (${typeCount}/4: ${types})` : `4-type gate off (${typeCount} types: ${types})`;
            els.yearEffectStatus.textContent = `${gate} | active ${activeCount}, inactive ${skippedCount}`;
        }
    }

    function renderFilters() {
        const typeOptions = ["all", "Speed", "Stamina", "Power", "Guts", "Wit", "Pal", "Group"];
        const rarityOptions = ["all", "SSR", "SR", "R"];
        const chip = (kind, value, active) => `<button class="training-sim-chip ${active ? "is-active" : ""}" type="button" data-filter="${kind}" data-value="${escapeAttr(value)}">${escapeHtml(value === "all" ? "All" : value)}</button>`;
        els.filterRow.innerHTML = `
            <div class="training-sim-chip-group">${typeOptions.map(value => chip("type", value, state.typeFilter === value)).join("")}</div>
            <div class="training-sim-chip-group">${rarityOptions.map(value => chip("rarity", value, state.rarityFilter === value)).join("")}</div>
        `;
    }
    function filteredCards() {
        const query = String(state.search || "").trim().toLowerCase();
        return ((state.meta || {}).cards || []).filter(card => {
            if (state.ownedOnly && !card.owned) return false;
            if (state.typeFilter !== "all" && String(card.type || "") !== state.typeFilter) return false;
            if (state.rarityFilter !== "all" && String(card.rarity || "") !== state.rarityFilter) return false;
            if (!query) return true;
            return [card.support_card_id, card.id, card.name, card.type, card.rarity].join(" ").toLowerCase().includes(query);
        }).sort((a, b) =>
            // Base sort = release date, newest first (GameTora-style), enforced
            // client-side too so the order holds even against a backend that
            // predates release_ts in /meta. No-date cards sink; same-day
            // banners tiebreak newest-id first.
            (Number(b.release_ts || 0) - Number(a.release_ts || 0))
            || (Number(b.support_card_id || 0) - Number(a.support_card_id || 0))
        );
        // No hard cap: the old slice(0, 220) cut the type-sorted list after
        // Speed/Stamina/Power, hiding EVERY Guts/Wit/Pal card unless filtered.
    }
    function renderCardToolbox() {
        const cards = filteredCards();
        const meta = state.meta || {};
        els.status.textContent = `${cards.length} shown / ${(meta.cards || []).length || 0} cards${meta.owned_count ? `, ${meta.owned_count} owned` : ""}`;
        els.cardToolbox.innerHTML = cards.map(card => {
            const id = cardId(card);
            const active = state.selectedCard && cardId(state.selectedCard) === id;
            const owned = card.owned ? lbLabel(card.limit_break_count) : "catalog";
            return `
                <button class="training-sim-card ${typeClass(card.type)} ${active ? "is-selected" : ""}" type="button" data-card-id="${id}"
                    title="${escapeAttr(card.name || `Support ${id}`)}${card.release_date ? ` — released ${escapeAttr(card.release_date)}` : ""}">
                    <img src="/api/images/${id}.png" loading="lazy" onerror="this.style.display='none'">
                    <span class="training-sim-card-name">${escapeHtml(card.name || `Support ${id}`)}</span>
                    <span class="training-sim-card-meta">${escapeHtml(card.rarity || "?")} - ${escapeHtml(card.type || "?")} - ${escapeHtml(owned)}</span>
                    ${card.release_date ? `<span class="training-sim-card-date">${escapeHtml(card.release_date)}</span>` : ""}
                </button>
            `;
        }).join("") || '<div class="training-sim-empty">No matching support cards.</div>';
    }
    function renderAreas() {
        const result = state.result || {};
        const resultAreas = result.areas || {};
        els.areas.innerHTML = STATS.map(stat => {
            const area = resultAreas[stat] || {};
            const cards = state.areas[stat] || [];
            const npc = Number((state.npc || {})[stat] || 0);
            const total = area.total_gains || {};
            const base = area.base_gains || {};
            const scenario = area.scenario_bonus || {};
            const placedCards = cards.map(row => {
                const card = findCard(row.support_card_id) || row;
                const id = Number(row.support_card_id || row.id || 0);
                const lb = clampLb(row.lb == null ? card.limit_break_count : row.lb);
                const matching = cardMatchesTile(card, stat);
                const fbOn = row.fb !== false;
                const fbChip = matching
                    ? `<span class="training-sim-fb-chip ${fbOn ? "is-on" : "is-off"}" data-fb-toggle="${id}" title="${fbOn ? "Click to disable friendship training" : "Click to enable friendship training"}">FB</span>`
                    : `<span class="training-sim-fb-chip is-na" title="No friendship bonus (card type doesn't match training)">–</span>`;
                return `
                    <div class="training-sim-placed-card ${typeClass(card.type)}" data-placed-card-id="${id}">
                        <button class="training-sim-placed-remove" type="button" data-remove-card-id="${id}" title="Remove ${escapeAttr(card.name || id)}">×</button>
                        <img src="/api/images/${id}.png" onerror="this.style.display='none'">
                        <span>${escapeHtml(card.name || `Support ${id}`)}</span>
                        <div class="training-sim-placed-controls">
                            <select class="training-sim-lb-select" data-lb-card-id="${id}" title="Limit break level for ${escapeAttr(card.name || id)}">
                                ${lbOptions(lb)}
                            </select>
                            ${fbChip}
                        </div>
                    </div>
                `;
            }).join("");
            // uma.guide-style: big headline gain for the tile's own stat, compact
            // secondary rows, and a "Show breakdown" expandable (base / cards+items
            // / scenario) instead of a cryptic one-liner.
            const cardG = area.card_gains || {};
            const headlineValue = gainValue(total, stat);
            const gainRows = ["speed", "stamina", "power", "guts", "wit", "sp", "energy"].map(key => {
                const value = gainValue(total, key);
                if (!value && !["sp", "energy"].includes(key)) return "";
                if (key === stat) return "";
                return `<div class="training-sim-gain-row"><span>${escapeHtml(statLabel(key))}</span><strong class="${gainClass(value, key)}">${formatGain(value, key)}</strong></div>`;
            }).join("");
            const breakdownKeys = ["speed", "stamina", "power", "guts", "wit", "sp", "energy"];
            const breakdownRows = breakdownKeys.map(key => {
                const b = gainValue(base, key), c = gainValue(cardG, key), t = gainValue(total, key);
                if (!b && !c && !t) return "";
                const s = Number((scenario || {})[key] || 0);
                return `<tr><td>${escapeHtml(statLabel(key))}</td><td>${formatGain(b, key)}</td><td>${formatGain(c - b, key)}</td><td>${formatGain(s, key)}</td><td class="${gainClass(t, key)}"><strong>${formatGain(t, key)}</strong></td></tr>`;
            }).join("");
            return `
                <div class="training-sim-area ${typeClass(statLabel(stat))} ${state.selectedArea === stat ? "is-selected" : ""} ${state.selectedCard ? "is-armed" : ""}" data-area="${stat}">
                    <div class="training-sim-area-head"><span>${escapeHtml(statLabel(stat))}</span><b>${cards.length + npc}/6</b></div>
                    <div class="training-sim-drop-zone">
                        ${placedCards || '<div class="training-sim-drop-hint">Drop cards or click for NPC</div>'}
                        ${npc ? `<div class="training-sim-npc-pill">${npc} NPC${npc === 1 ? "" : "s"}</div>` : ""}
                    </div>
                    <div class="training-sim-area-actions">
                        <button class="btn btn-xs" type="button" data-npc-delta="-1" data-npc-area="${stat}">- NPC</button>
                        <button class="btn btn-xs" type="button" data-npc-delta="1" data-npc-area="${stat}">+ NPC</button>
                        <button class="btn btn-xs" type="button" data-clear-area="${stat}">Clear</button>
                    </div>
                    <div class="training-sim-output">
                        <div class="training-sim-output-primary">
                            <span>${escapeHtml(statLabel(stat))}</span>
                            <strong class="${gainClass(headlineValue)}">${formatGain(headlineValue)}</strong>
                        </div>
                        <div class="training-sim-gains">${gainRows}</div>
                        <details class="training-sim-breakdown-details">
                            <summary>Show breakdown</summary>
                            <table class="training-sim-breakdown-table">
                                <thead><tr><th></th><th>Base</th><th>Cards/Items</th><th>Scenario</th><th>Total</th></tr></thead>
                                <tbody>${breakdownRows || '<tr><td colspan="5">Drop cards to see stats</td></tr>'}</tbody>
                            </table>
                        </details>
                    </div>
                </div>
            `;
        }).join("");
    }
    function renderAll() {
        renderControls();
        renderFilters();
        renderCardToolbox();
        renderAreas();
        updateArmedHint();
    }
    async function calculateNow() {
        if (!state.meta) return;
        const seq = ++calcSeq;
        try {
            const data = await apiJson("/api/training-sim/calculate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload())
            });
            if (seq !== calcSeq) return;
            if (!data || !data.success) throw new Error((data && data.detail) || "Training sim calculation failed");
            state.result = data;
            renderYearEffects();
            renderAreas();
            els.pageStatus.textContent = "Ready";
        } catch (e) {
            els.pageStatus.textContent = "Calculation failed";
            els.status.textContent = `Calculation failed: ${e.message || e}`;
        }
    }
    function scheduleCalculation() {
        if (calcTimer) window.clearTimeout(calcTimer);
        calcTimer = window.setTimeout(calculateNow, 80);
    }
    async function loadMeta() {
        try {
            const data = await apiJson("/api/training-sim/meta?t=" + Date.now());
            if (!data || !data.success) throw new Error((data && data.detail) || "Training sim meta failed");
            // Normalize JP-side type names to the UI's global naming so the
            // Wit/Pal filter chips and type colors match every card
            // (backend emits "Intelligence" for Wit and "Friend" for Pal).
            const typeAliases = { Intelligence: "Wit", Wisdom: "Wit", Int: "Wit", Friend: "Pal" };
            (data.cards || []).forEach(card => {
                if (typeAliases[card.type]) card.type = typeAliases[card.type];
            });
            state.meta = data;
            if (!state.scenario) state.scenario = data.default_scenario || "mant_base";
            renderAll();
            scheduleCalculation();
        } catch (e) {
            els.pageStatus.textContent = "Load failed";
            els.status.textContent = `Training sim unavailable: ${e.message || e}`;
        }
    }

    function bindHandlers() {
        els.scenario.addEventListener("change", () => {
            state.scenario = els.scenario.value || "";
            localSet("trainingSimScenario", state.scenario);
            applyGimmickVisibility();
            syncItemSummary();
            scheduleCalculation();
        });
        els.level.addEventListener("change", () => {
            state.level = selectedLevel();
            localSet("trainingSimLevel", state.level);
            scheduleCalculation();
        });
        els.mood.addEventListener("change", () => {
            state.mood = selectedMood();
            localSet("trainingSimMood", state.mood);
            scheduleCalculation();
        });
        if (els.growthOpen) els.growthOpen.addEventListener("click", openGrowthModal);
        if (els.growthClose) els.growthClose.addEventListener("click", closeGrowthModal);
        if (els.growthSave) els.growthSave.addEventListener("click", saveGrowthModal);
        if (els.growthModal) {
            els.growthModal.addEventListener("click", event => {
                if (event.target === els.growthModal) closeGrowthModal();
            });
            els.growthModal.addEventListener("keydown", event => {
                if (event.key === "Escape") closeGrowthModal();
                if (event.key === "Enter" && event.target && event.target.matches("[data-growth-modal-stat]")) saveGrowthModal();
            });
        }
        els.search.addEventListener("input", () => {
            state.search = els.search.value || "";
            renderCardToolbox();
        });
        els.ownedOnly.addEventListener("change", () => {
            state.ownedOnly = !!els.ownedOnly.checked;
            localSet("trainingSimOwnedOnly", state.ownedOnly ? "1" : "0");
            renderCardToolbox();
        });
        els.clearCards.addEventListener("click", () => {
            state.areas = defaultAreas();
            renderAll();
            scheduleCalculation();
        });
        els.reset.addEventListener("click", () => {
            state.areas = defaultAreas();
            state.npc = defaultNpc();
            state.selectedCard = null;
            state.megaphonePct = 0;
            state.weightFacilities = {};
            state.yearEffects = {};
            state.overcapStat = false;
            setGrowth({});
            localSet("trainingSimMegaphonePct", "0");
            localSet("trainingSimOvercapStat", "0");
            saveYearEffects();
            renderAll();
            scheduleCalculation();
        });
        els.megaphones.addEventListener("click", event => {
            const btn = event.target.closest("[data-megaphone]");
            if (!btn) return;
            const value = Number(btn.dataset.megaphone || 0) || 0;
            // uma.guide parity: clicking the active option deselects it.
            state.megaphonePct = value === Number(state.megaphonePct || 0) ? 0 : value;
            localSet("trainingSimMegaphonePct", state.megaphonePct);
            renderControls();
            scheduleCalculation();
        });
        els.weights.addEventListener("click", event => {
            const btn = event.target.closest("[data-weight]");
            if (!btn) return;
            const stat = btn.dataset.weight;
            // Single-select (one weight item per turn); click again to clear.
            const wasActive = !!state.weightFacilities[stat];
            state.weightFacilities = {};
            if (!wasActive) state.weightFacilities[stat] = true;
            renderControls();
            scheduleCalculation();
        });
        els.overcapStat.addEventListener("click", () => {
            state.overcapStat = !state.overcapStat;
            localSet("trainingSimOvercapStat", state.overcapStat ? "1" : "0");
            renderControls();
            scheduleCalculation();
        });
        els.supportTypeGate.addEventListener("change", () => {
            state.enforceSupportTypes = !!els.supportTypeGate.checked;
            localSet("trainingSimEnforceSupportTypes", state.enforceSupportTypes ? "1" : "0");
            renderYearEffects();
            scheduleCalculation();
        });
        els.yearTabs.addEventListener("click", event => {
            const btn = event.target.closest("[data-gimmick-year]");
            if (!btn) return;
            state.gimmickYear = btn.dataset.gimmickYear || "";
            localSet("trainingSimGimmickYear", state.gimmickYear);
            renderYearEffects();
        });
        els.yearEffects.addEventListener("click", event => {
            const btn = event.target.closest("[data-year-effect]");
            if (!btn) return;
            const id = btn.dataset.yearEffect || "";
            if (!id) return;
            const groups = yearEffectGroups();
            const group = groups.find(g => (g.effects || []).some(e => String(e.id) === id)) || null;
            const turningOn = !state.yearEffects[id];
            if (turningOn && group && selectedVenueCount(group) >= 3) {
                els.yearEffectStatus.textContent = `${group.year}: max 3 venue buffs — deselect one first.`;
                return;
            }
            if (turningOn) state.yearEffects[id] = true; else delete state.yearEffects[id];
            // Auto-manage the year's Basic buff: on iff >=1 venue buff selected.
            const basic = basicEffectForYear(group);
            if (basic) {
                if (selectedVenueCount(group) > 0) state.yearEffects[String(basic.id)] = true;
                else delete state.yearEffects[String(basic.id)];
            }
            saveYearEffects();
            renderYearEffects();
            scheduleCalculation();
        });
        els.filterRow.addEventListener("click", event => {
            const btn = event.target.closest("[data-filter]");
            if (!btn) return;
            const kind = btn.dataset.filter;
            const value = btn.dataset.value || "all";
            if (kind === "type") state.typeFilter = value;
            if (kind === "rarity") state.rarityFilter = value;
            renderFilters();
            renderCardToolbox();
        });
        els.cardToolbox.addEventListener("click", event => {
            const btn = event.target.closest("[data-card-id]");
            if (!btn) return;
            const clicked = findCard(btn.dataset.cardId);
            // Toggle: clicking the armed card again disarms it.
            state.selectedCard = (state.selectedCard && cardId(state.selectedCard) === cardId(clicked)) ? null : clicked;
            renderCardToolbox();
            renderAreas();
            updateArmedHint();
        });
        els.areas.addEventListener("click", event => {
            // Clicks inside the breakdown expandable must not place cards/NPCs.
            if (event.target.closest(".training-sim-breakdown-details")) return;
            if (event.target.closest(".training-sim-placed-card") && !event.target.closest("[data-remove-card-id], [data-fb-toggle]")) return;
            // FB chip: toggle friendship for that placed card (do NOT remove it).
            const fbChip = event.target.closest("[data-fb-toggle]");
            if (fbChip) {
                event.preventDefault();
                event.stopPropagation();
                const id = Number(fbChip.dataset.fbToggle || 0);
                STATS.forEach(stat => {
                    (state.areas[stat] || []).forEach(row => {
                        if (Number(row.support_card_id || 0) === id) row.fb = row.fb === false;
                    });
                });
                renderAreas();
                scheduleCalculation();
                return;
            }
            const removeBtn = event.target.closest("[data-remove-card-id]");
            if (removeBtn) {
                removeCardEverywhere(removeBtn.dataset.removeCardId);
                renderAreas();
                scheduleCalculation();
                return;
            }
            const npcBtn = event.target.closest("[data-npc-delta]");
            if (npcBtn) {
                const stat = npcBtn.dataset.npcArea;
                const delta = Number(npcBtn.dataset.npcDelta || 0);
                const cards = (state.areas[stat] || []).length;
                const current = Number((state.npc || {})[stat] || 0);
                state.npc[stat] = Math.max(0, Math.min(6 - cards, current + delta));
                renderAreas();
                scheduleCalculation();
                return;
            }
            const clearBtn = event.target.closest("[data-clear-area]");
            if (clearBtn) {
                const stat = clearBtn.dataset.clearArea;
                state.areas[stat] = [];
                state.npc[stat] = 0;
                renderAreas();
                scheduleCalculation();
                return;
            }
            const area = event.target.closest("[data-area]");
            if (!area) return;
            const stat = area.dataset.area;
            state.selectedArea = stat;
            if (state.selectedCard) {
                const placement = placementForCard(state.selectedCard);
                removeCardEverywhere(placement.support_card_id);
                const current = state.areas[stat] || [];
                const npc = Number((state.npc || {})[stat] || 0);
                if (current.length + npc < 6) current.push(placement);
                state.areas[stat] = current;
                state.selectedCard = null;
                renderCardToolbox();
                updateArmedHint();
            } else {
                const current = Number((state.npc || {})[stat] || 0);
                const cards = (state.areas[stat] || []).length;
                state.npc[stat] = Math.max(0, Math.min(6 - cards, current + 1));
            }
            renderAreas();
            scheduleCalculation();
        });
        els.areas.addEventListener("change", event => {
            const lbSelect = event.target.closest("[data-lb-card-id]");
            if (!lbSelect) return;
            const id = Number(lbSelect.dataset.lbCardId || 0);
            const lb = clampLb(lbSelect.value);
            STATS.forEach(stat => {
                (state.areas[stat] || []).forEach(row => {
                    if (Number(row.support_card_id || 0) === id) row.lb = lb;
                });
            });
            renderAreas();
            scheduleCalculation();
        });
    }

    // Persist the Items & Scenario Bonuses panel open/closed state.
    const bonusesPanel = $("training-sim-bonuses");
    if (bonusesPanel) {
        bonusesPanel.open = localGet("trainingSimBonusesOpen", "1") !== "0";
        bonusesPanel.addEventListener("toggle", () => localSet("trainingSimBonusesOpen", bonusesPanel.open ? "1" : "0"));
    }

    bindHandlers();
    loadMeta();
})();
