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
        growthPreset: $("training-sim-growth-preset"),
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
        tilesHint: $("training-sim-tiles-hint")
    };

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
        growth: {},
        megaphonePct: Number(localGet("trainingSimMegaphonePct", "0")) || 0,
        weightFacilities: {},
        yearEffects: localJson("trainingSimYearEffects", {}),
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
        const lb = Math.max(0, Math.min(4, Number(rawLb == null ? 4 : rawLb) || 0));
        return { support_card_id: id, lb: card && card.owned ? lb : 4 };
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
    function syncItemSummary() {
        const weightCount = weightFacilitiesArray().length;
        const selected = Number(state.megaphonePct || 0) + (weightCount ? 50 : 0);
        const other = Number(state.megaphonePct || 0);
        const overcap = state.overcapStat ? " | Trained stat over 1200: primary gain halved" : "";
        els.itemSummary.textContent = `Selected Facility Bonus: +${selected}% | Other Facilities Bonus: +${other}%${overcap}`;
    }
    function payload() {
        return {
            scenario: selectedScenario(),
            facility_level: selectedLevel(),
            mood: selectedMood(),
            growth: { ...(state.growth || {}) },
            areas: state.areas || defaultAreas(),
            npc_counts: state.npc || defaultNpc(),
            megaphone_bonus_pct: Number(state.megaphonePct || 0),
            weight_training_pct: 50,
            weight_energy_pct: 20,
            weight_facilities: weightFacilitiesArray(),
            active_scenario_effects: [],
            year_effect_ids: selectedYearEffectIds(),
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
        const growthRows = meta.growth_presets || [];
        els.growthPreset.innerHTML = growthRows.map((row, idx) => `<option value="${idx}">${escapeHtml(row.label)}</option>`).join("");
        const currentGrowth = growthRows.findIndex(row => JSON.stringify(row.growth || {}) === JSON.stringify(state.growth || {}));
        els.growthPreset.value = String(currentGrowth >= 0 ? currentGrowth : 0);
        if (!state.growth || !Object.keys(state.growth).length) {
            state.growth = { ...((growthRows[0] && growthRows[0].growth) || {}) };
        }
        els.megaphones.innerHTML = (((meta.item_options || {}).megaphones || []).map(row => `
            <button class="training-sim-chip ${Number(row.value) === Number(state.megaphonePct || 0) ? "is-active" : ""}" type="button" data-megaphone="${escapeAttr(row.value)}">${escapeHtml(row.label)}</button>
        `).join(""));
        els.weights.innerHTML = STATS.map(stat => `
            <button class="training-sim-chip training-sim-chip-stat ${state.weightFacilities[stat] ? "is-active" : ""}" type="button" data-weight="${stat}">
                ${escapeHtml(statLabel(stat))} Weight
            </button>
        `).join("");
        els.overcapStat.classList.toggle("is-active", !!state.overcapStat);
        els.supportTypeGate.checked = !!state.enforceSupportTypes;
        els.ownedOnly.checked = !!state.ownedOnly;
        syncItemSummary();
        renderYearEffects();
    }

    function renderYearEffects() {
        const meta = state.meta || {};
        const result = state.result || {};
        const skippedIds = new Set((result.year_effects_skipped || []).map(row => String(row.id || "")));
        const activeIds = new Set(selectedYearEffectIds());
        const typeCount = Number(result.support_type_count || 0);
        const gateOn = !!state.enforceSupportTypes;
        els.yearEffects.innerHTML = (meta.year_effects || []).map(group => {
            const buttons = (group.effects || []).map(effect => {
                const id = String(effect.id || "");
                const active = activeIds.has(id);
                const blocked = active && skippedIds.has(id);
                // Explain the gate BEFORE the user clicks: chips that need 4 card
                // types show as gated (dimmed, not dead) while under 4 types.
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
            return `
                <div class="training-sim-year-group">
                    <div class="training-sim-year-heading">${escapeHtml(group.year || "Year")}</div>
                    <div class="training-sim-year-chip-grid">${buttons}</div>
                </div>
            `;
        }).join("") || '<div class="training-sim-empty">No scenario bonus data loaded.</div>';
        const types = (result.support_types || []).join(", ") || "none placed";
        const activeCount = (result.year_effects_active || []).length;
        const skippedCount = (result.year_effects_skipped || []).length;
        if (gateOn && typeCount < 4) {
            els.yearEffectStatus.textContent = `Classic/Senior bonuses need 4 card types on tiles — you have ${typeCount} (${types}). Place more types or untick the gate. | active ${activeCount}, inactive ${skippedCount}`;
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
        });
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
            const owned = card.owned ? `LB${Number(card.limit_break_count || 0)}` : "catalog";
            return `
                <button class="training-sim-card ${typeClass(card.type)} ${active ? "is-selected" : ""}" type="button" data-card-id="${id}">
                    <img src="/api/images/${id}.png" loading="lazy" onerror="this.style.display='none'">
                    <span class="training-sim-card-name">${escapeHtml(card.name || `Support ${id}`)}</span>
                    <span class="training-sim-card-meta">${escapeHtml(card.rarity || "?")} - ${escapeHtml(card.type || "?")} - ${escapeHtml(owned)}</span>
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
                return `
                    <button class="training-sim-placed-card ${typeClass(card.type)}" type="button" data-remove-card-id="${id}" title="Remove ${escapeAttr(card.name || id)}">
                        <img src="/api/images/${id}.png" onerror="this.style.display='none'">
                        <span>${escapeHtml(card.name || `Support ${id}`)}</span>
                    </button>
                `;
            }).join("");
            const gainRows = ["speed", "stamina", "power", "guts", "wit", "sp", "energy"].map(key => {
                const value = gainValue(total, key);
                if (!value && !["sp", "energy"].includes(key)) return "";
                return `<div class="training-sim-gain-row"><span>${escapeHtml(statLabel(key))}</span><strong class="${gainClass(value, key)}">${formatGain(value, key)}</strong></div>`;
            }).join("");
            const baseSummary = ["speed", "stamina", "power", "guts", "wit", "sp"].map(key => gainValue(base, key)).filter(Boolean).join(" / ");
            const scenarioDelta = Object.values(scenario).reduce((sum, value) => sum + Math.abs(Number(value || 0)), 0);
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
                    <div class="training-sim-gains">${gainRows}</div>
                    <div class="training-sim-breakdown">Base ${escapeHtml(baseSummary || "0")}${scenarioDelta ? ` - Scenario adj ${escapeHtml(String(scenarioDelta))}` : ""}</div>
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
        els.growthPreset.addEventListener("change", () => {
            const idx = Number(els.growthPreset.value || 0);
            const row = ((state.meta || {}).growth_presets || [])[idx] || {};
            state.growth = { ...(row.growth || {}) };
            scheduleCalculation();
        });
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
            localSet("trainingSimMegaphonePct", "0");
            localSet("trainingSimOvercapStat", "0");
            saveYearEffects();
            renderAll();
            scheduleCalculation();
        });
        els.megaphones.addEventListener("click", event => {
            const btn = event.target.closest("[data-megaphone]");
            if (!btn) return;
            state.megaphonePct = Number(btn.dataset.megaphone || 0) || 0;
            localSet("trainingSimMegaphonePct", state.megaphonePct);
            renderControls();
            scheduleCalculation();
        });
        els.weights.addEventListener("click", event => {
            const btn = event.target.closest("[data-weight]");
            if (!btn) return;
            const stat = btn.dataset.weight;
            state.weightFacilities[stat] = !state.weightFacilities[stat];
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
        els.yearEffects.addEventListener("click", event => {
            const btn = event.target.closest("[data-year-effect]");
            if (!btn) return;
            const id = btn.dataset.yearEffect || "";
            if (!id) return;
            state.yearEffects[id] = !state.yearEffects[id];
            if (!state.yearEffects[id]) delete state.yearEffects[id];
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
