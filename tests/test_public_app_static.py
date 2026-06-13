import unittest
from pathlib import Path
import json


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PublicAppStaticTests(unittest.TestCase):
    def test_trainee_growth_map_is_outfit_specific_and_not_partial_stub(self):
        aptitude_map = json.loads((PROJECT_ROOT / "public" / "assets" / "data" / "chara_aptitude_map.json").read_text(encoding="utf-8"))

        outfit_keys = [key for key in aptitude_map.keys() if key.isdigit() and len(key) == 6]
        self.assertGreaterEqual(len(aptitude_map), 350)
        self.assertGreaterEqual(len(outfit_keys), 240)
        self.assertIn("100801", aptitude_map)
        self.assertIn("100802", aptitude_map)
        self.assertIn("103201", aptitude_map)
        self.assertIn("103202", aptitude_map)
        self.assertIn("105901", aptitude_map)
        self.assertNotEqual(aptitude_map["100801"]["growths"], aptitude_map["100802"]["growths"])
        self.assertNotEqual(aptitude_map["103201"]["growths"], aptitude_map["103202"]["growths"])

    def test_race_result_labels_are_rank_authoritative(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn("row.won || raceResult.won || rank === 1 ? 'WON' : 'LOST'", app_js)
        self.assertIn("const resultWon = rank > 0 ? rank === 1 : flagWon;", app_js)
        self.assertIn("result: rank === 1 ? 'won' : rank > 1 ? 'lost' : (row.result || 'unknown')", app_js)

    def test_preset_owned_settings_are_not_saved_to_hardcoded_default(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")

        self.assertIn("preset_name: selectedPresetName()", app_js)
        self.assertNotIn('state.selectedPreset = "xguri parent";\n            syncStartButton();\n            await loadRaceData();', app_js)
        self.assertIn('id="alarm-clock-mode-select"', index_html)
        self.assertIn('id="alarm-clock-limit-input"', index_html)

    def test_saved_skill_plan_has_session_persistence_cache(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")

        self.assertIn("selectedPreset: safeLocalGet('selectedPreset', '')", app_js)
        self.assertIn("function defaultPresetName()", app_js)
        self.assertIn("function cacheSkillPlanSnapshot", app_js)
        self.assertIn("localStorage.setItem(skillPlanCacheKey(name)", app_js)
        self.assertIn("cacheSkillPlanSnapshot(selectedPresetName());", app_js)
        self.assertIn("function loadCachedSkillPlanSnapshot", app_js)
        self.assertIn("applyCachedSkillPlanSnapshot(loadCachedSkillPlanSnapshot(selectedPresetName()))", app_js)

    def test_team_bar_shows_combo_affinity_and_gold_inheritance_odds(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="team-combo-affinity"', index_html)
        self.assertIn("function renderComboAffinitySummary", app_js)
        self.assertIn("computeProjectedAffinityGame(trainee, parent1, parent2)", app_js)
        self.assertIn("function comboGoldInspirationOdds", app_js)
        self.assertIn("Gold inspiration odds", app_js)
        self.assertIn("renderComboAffinitySummary();", app_js)
        self.assertIn(".team-combo-affinity", styles_css)
        self.assertIn(".combo-affinity-kpi", styles_css)

    def test_backend_refresh_button_triggers_manual_dev_reload(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="refresh-backend-btn"', index_html)
        self.assertIn("async function refreshBackend()", app_js)
        self.assertIn("await apiJson('/api/dev/reload'", app_js)
        self.assertIn("REFRESH BACKEND", app_js)

    def test_login_view_keeps_auth_refresh_available(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="auth-refresh-btn"', index_html)
        self.assertNotIn('id="auth-refresh-btn" type="button" class="btn btn-secondary" style="display:none;', index_html)
        self.assertIn("els.authRefreshBtn.style.display = '';", app_js)
        self.assertIn("const payload = readLoginPayload();", app_js)
        self.assertIn("REFRESHING REUSABLE AUTH FROM YOUR STEAM CREDENTIALS", app_js)
        self.assertIn("body: JSON.stringify(payload)", app_js)

    def test_dashboard_has_top_auth_refresh_end_career_and_completion_notifications(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="top-auth-refresh-btn"', index_html)
        self.assertIn('id="career-notify-toggle-btn"', index_html)
        self.assertIn('id="end-career-btn"', index_html)
        self.assertIn("async function refreshAuthFromUi()", app_js)
        self.assertIn("function readAuthRefreshPayload()", app_js)
        self.assertIn("careerCompleteNotifyEnabled: safeLocalBool('careerCompleteNotifyEnabled', true)", app_js)
        self.assertIn("function notifyCareerCompletion(runner, loop = {})", app_js)
        self.assertIn("new Notification(title,", app_js)
        self.assertIn("await apiJson('/api/career/end', {", app_js)
        self.assertIn("#career-notify-toggle-btn.is-active", styles_css)

    def test_loop_enabled_flag_is_persisted_separately_from_loop_mode(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function safeLocalBool(key, fallback = false)", app_js)
        self.assertIn("loopEnabled: safeLocalBool('loopEnabled', false)", app_js)
        self.assertIn("safeLocalSet('loopEnabled', state.loopEnabled ? '1' : '0');", app_js)
        self.assertIn("if (loop.active) {\n                    state.loopEnabled = true;", app_js)

    def test_deck_advice_panel_and_loader_exist(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="deck-advice-panel"', index_html)
        self.assertIn("async function loadDeckAdvice(", app_js)
        self.assertIn("function renderDeckAdvice()", app_js)
        self.assertIn("/api/decks/advice?", app_js)
        self.assertIn("function bindDeckAdviceToggle()", app_js)
        self.assertIn("deckAdviceExpanded", app_js)
        self.assertIn("recommended_build", app_js)
        self.assertIn("swap_suggestions", app_js)
        self.assertIn("current_weaknesses", app_js)
        self.assertIn('id="deck-advice-toggle"', index_html)
        self.assertIn(".deck-advice-toggle", styles_css)
        self.assertIn(".deck-advice-panel.is-collapsed .deck-advice-list", styles_css)
        self.assertIn(".deck-advice-panel", styles_css)
        self.assertIn(".deck-advice-card", styles_css)

    def test_deck_screen_supports_local_deck_editing(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="deck-reset-btn"', index_html)
        self.assertIn('id="deck-editor-card-search"', index_html)
        self.assertIn('id="deck-editor-card-list"', index_html)
        self.assertIn("const DECK_CARD_LIMIT = 5", app_js)
        self.assertIn("async function saveDeckEdit", app_js)
        self.assertIn("function addCardToDeck", app_js)
        self.assertIn("function removeCardFromDeck", app_js)
        self.assertIn("await apiJson('/api/decks/save'", app_js)
        self.assertIn("Deck needs 5 support cards", app_js)
        self.assertIn(".deck-add-card-btn", styles_css)
        self.assertIn(".deck-slot-remove", styles_css)
        self.assertIn(".deck-edited-chip", styles_css)

    def test_parent_and_guest_views_support_stars_and_date_sort(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("borrowUmas", app_js)
        self.assertIn("'date-made': 'Date Made'", app_js)
        self.assertIn("favoriteType: 'borrowUmas'", app_js)
        self.assertIn('value="starred"', index_html)
        self.assertIn('value="date-made"', index_html)
        self.assertIn(".parent-card-rich .favorite-toggle", styles_css)

    def test_parent_views_support_bot_sort_and_score_search(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")

        self.assertIn('value="bot"', index_html)
        self.assertIn("bot: 'BOT Tag'", app_js)
        self.assertIn("case 'bot': return metrics.bot;", app_js)
        self.assertIn("p.score != null ? String(p.score) : ''", app_js)
        self.assertIn("p.score != null ? formatNumber(p.score) : ''", app_js)
        self.assertIn("p.made_by_bot ? 'bot bot-made bottag' : 'user'", app_js)

    def test_trainee_cards_show_full_surface_and_distance_aptitudes(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("const TRAINEE_APTITUDE_GROUPS", app_js)
        self.assertIn("{ key: 'sprint', label: 'Spr' }", app_js)
        self.assertIn("{ key: 'medium', label: 'Med' }", app_js)
        self.assertIn("function renderTraineeAptitudePanel(aptVals)", app_js)
        self.assertIn(".trainee-apt-panel", styles_css)
        self.assertIn(".trainee-apt-group-title", styles_css)
        self.assertIn(".trainee-apt-strip.is-surface", styles_css)
        self.assertIn(".trainee-apt-strip.is-distance", styles_css)
        self.assertIn("minmax(156px, 1fr)", styles_css)

    def test_friend_id_add_controls_exist(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="friend-id-input"', index_html)
        self.assertIn('id="friend-id-add-btn"', index_html)
        self.assertIn('id="friend-id-status"', index_html)
        self.assertIn('id="friend-following-quota"', index_html)
        self.assertIn('id="friend-profile-modal-overlay"', index_html)
        self.assertIn('id="friend-profile-use-btn"', index_html)
        self.assertIn('id="friend-profile-unfollow-btn"', index_html)
        self.assertIn("async function addFriendById()", app_js)
        self.assertIn("function bindFriendProfileModal()", app_js)
        self.assertIn("async function unfollowActiveFriend()", app_js)
        self.assertIn("await apiJson('/api/friends/add'", app_js)
        self.assertIn("await apiJson('/api/friends/unfollow'", app_js)
        self.assertIn("function setFriendIdStatus", app_js)
        self.assertIn(".friend-id-toolbar .library-search-input", styles_css)
        self.assertIn(".friend-id-status", styles_css)
        self.assertIn(".friend-following-head", styles_css)
        self.assertIn(".friend-list-row", styles_css)
        self.assertIn(".friend-profile-modal", styles_css)

    def test_card_borrow_pane_exists_for_direct_friend_support_selection(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('data-cat="card-borrow"', index_html)
        self.assertIn('data-pane="card-borrow"', index_html)
        self.assertIn('id="card-borrow-search-input"', index_html)
        self.assertIn('id="card-borrow-refresh-btn"', index_html)
        self.assertIn('id="card-borrow-grid"', index_html)
        self.assertIn("function getVisibleCardBorrows()", app_js)
        self.assertIn("function renderCardBorrows()", app_js)
        self.assertIn("function attachCardBorrowHandlers()", app_js)
        self.assertIn("'card-borrow': (dashData && dashData.friends ? dashData.friends.length : null)", app_js)
        self.assertIn("#card-borrow-grid.friend-following-list", styles_css)

    def test_library_test_tab_exists(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")

        self.assertIn('data-cat="test"', index_html)
        self.assertIn('<span class="rail-name">Test 36</span>', index_html)
        self.assertIn('data-pane="test"', index_html)
        self.assertIn("Test 36 tab is wired and selectable.", index_html)
        self.assertIn("test:'TEST 36'", app_js)

    def test_team_trials_searchable_screen_exists(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="team-trials-screen-btn"', index_html)
        self.assertIn('id="team-trials-screen"', index_html)
        self.assertNotIn('data-cat="team-trials"', index_html)
        self.assertNotIn('data-pane="team-trials"', index_html)
        self.assertIn('id="team-trials-search-input"', index_html)
        self.assertIn('id="team-trials-player-list"', index_html)
        self.assertIn('id="team-trials-team-layout"', index_html)
        self.assertIn('id="team-trials-character-detail"', index_html)
        self.assertIn("teamTrialsData", app_js)
        self.assertIn("async function loadTeamTrialsData", app_js)
        self.assertIn("/api/team_trials/live?limit=100", app_js)
        self.assertIn("/api/team_trials/live_profile?", app_js)
        self.assertIn("/api/team_trials/data?", app_js)
        self.assertIn("function showTeamTrialsScreen", app_js)
        self.assertIn("function openTeamTrialsTeam", app_js)
        self.assertIn("function openTeamTrialsCharacter", app_js)
        self.assertIn("Deck RB", app_js)
        self.assertNotIn("'team-trials':'TEAM TRIALS'", app_js)
        self.assertIn(".team-trials-screen", styles_css)
        self.assertIn(".team-trials-player-card", styles_css)
        self.assertIn(".team-trials-team-layout", styles_css)
        self.assertIn(".team-trials-detail-tabs", styles_css)

    def test_owned_card_inventory_supports_live_duplicate_uncap(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="card-uncap-all-btn"', index_html)
        self.assertIn('id="card-inventory-status"', index_html)
        self.assertIn("function getSupportUncapPlan(supports)", app_js)
        self.assertIn("async function uncapAllOwnedSupportCards()", app_js)
        self.assertIn("await apiJson('/api/supports/limit_break_all', { method: 'POST' })", app_js)
        self.assertIn("LB${Number(card.limit_break_count || 0)} | Stock ${Number(card.stock || 0)} | Lv${Number(card.support_card_level || card.level || 0)}", app_js)
        self.assertIn(".grid-card-submeta", styles_css)

    def test_borrow_umas_prefer_real_rank_over_chara_grade(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")

        self.assertIn("rank: Number(uma.rank || uma.chara_grade || 0)", app_js)
        self.assertIn("rank: uma.rank != null ? uma.rank : uma.chara_grade", app_js)
        self.assertIn("const resolvedRank = Number(uma.rank || 0) || Number(uma.chara_grade || 0) || 0;", app_js)

    def test_parent_card_white_factor_count_uses_parent_only_not_lineage_total(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")

        self.assertIn("const whiteCount = countMainWhiteFactors(parent);", app_js)

    def test_parent_card_g1_wins_use_parent_only_not_lineage_total(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function countMainWinsByGrade(parent, grade)", app_js)
        self.assertIn("const g1Wins = countMainWinsByGrade(parent, 'g1');", app_js)

    def test_legacy_preview_keeps_header_compact_and_moves_advanced_details_into_setup(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="setup-legacy-section"', index_html)
        self.assertIn('id="setup-legacy-details"', index_html)
        self.assertIn('id="setup-legacy-summary"', index_html)
        self.assertIn("function renderLegacySetupDetailsPanel(trainee, parents)", app_js)
        self.assertIn("function renderSetupLegacyDetails()", app_js)
        self.assertIn("renderSetupLegacyDetails();", app_js)
        self.assertIn("legacy-dashboard-panel legacy-dashboard-panel-setup", app_js)
        self.assertIn("function renderLegacyAptitudeTable(trainee, aptitudeBonuses)", app_js)
        self.assertIn(".setup-legacy-details", styles_css)
        self.assertIn(".setup-legacy-summary-line", styles_css)
        self.assertIn(".legacy-dashboard-panel-setup", styles_css)
        self.assertIn(".legacy-dashboard-panel", styles_css)
        self.assertIn(".legacy-gain-grid", styles_css)
        self.assertIn(".legacy-aptitude-table", styles_css)

    def test_session_parent_pane_tracks_live_bot_outputs_only(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function isTrackableSessionParent(parent)", app_js)
        self.assertIn("const list = (Array.isArray(parents) ? parents : []).filter(isTrackableSessionParent);", app_js)
        self.assertIn("retuned.sessionParentOrder = retuned.sessionParentOrder.filter(id => !!liveById[id]);", app_js)
        self.assertIn("bot-made parent${items.length === 1 ? '' : 's'} created this session", app_js)
        self.assertIn("No bot-made parents created in this browser session yet", app_js)

    def test_planner_profile_controls_exist(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="planner-profile-name-input"', index_html)
        self.assertIn('id="planner-profile-select"', index_html)
        self.assertIn('id="planner-profile-save-btn"', index_html)
        self.assertIn('id="planner-profile-load-btn"', index_html)
        self.assertIn('id="planner-profile-export-btn"', index_html)
        self.assertIn('id="planner-profile-file"', index_html)
        self.assertIn("async function savePlannerProfile()", app_js)
        self.assertIn("async function loadPlannerProfiles(", app_js)
        self.assertIn("function exportPlannerProfile()", app_js)
        self.assertIn("async function importPlannerProfileFile(event)", app_js)

    def test_race_calendar_modal_uses_agenda_toolbar_layout(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (PROJECT_ROOT / "public" / "index.html").read_text(encoding="utf-8")
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="race-modal-status"', index_html)
        self.assertIn('id="race-modal-save-btn"', index_html)
        self.assertIn('id="race-modal-load-btn"', index_html)
        self.assertIn('id="race-modal-import-btn"', index_html)
        self.assertIn('id="race-modal-reset-btn"', index_html)
        self.assertIn('id="race-modal-search"', index_html)
        self.assertNotIn('id="race-toggle"', index_html)
        self.assertNotIn('id="race-chevron"', index_html)
        self.assertNotIn('id="race-body"', index_html)
        self.assertNotIn('id="race-advanced"', index_html)
        self.assertNotIn('id="race-modal-share-btn"', index_html)
        self.assertNotIn('id="race-modal-filters-btn"', index_html)
        self.assertNotIn('id="race-modal-sidebar-close"', index_html)
        self.assertNotIn('id="race-modal-race-bonus"', index_html)
        self.assertNotIn('id="race-modal-hammer-toggle"', index_html)
        self.assertIn('id="race-modal-import-file"', index_html)
        self.assertIn("function setRaceCalendarStatus(message, isError = false)", app_js)
        self.assertIn("function isRaceCalendarDraftShape(data)", app_js)
        self.assertIn("async function persistRaceCalendarDraft(message)", app_js)
        self.assertIn("async function importRaceCalendarDraftFile(event)", app_js)
        self.assertIn("await apiJson('/api/presets/save_race_plan', {", app_js)
        self.assertIn("available is-pickable", app_js)
        self.assertNotIn("choose ${candidates.length}", app_js)
        self.assertNotIn("'Pre-Debut',", app_js)
        self.assertIn("const RACE_TURN_ROW_SIZE = 4;", app_js)
        self.assertIn('rows.push(`<div class="cal-month-row">', app_js)
        self.assertIn("if (retuned.calendarOpen) {", app_js)
        self.assertIn("hydrateRaceCalendarDraftFromSaved();", app_js)
        self.assertIn("populateRaceCalendarGrid();", app_js)
        self.assertIn(".agenda-btn", styles_css)
        self.assertIn(".race-modal-body", styles_css)
        self.assertIn(".cal-month-row", styles_css)
        self.assertIn(".race-modal-status.is-error", styles_css)
        self.assertIn("await apiJson('/api/planner_profiles/save'", app_js)
        self.assertIn("await apiJson('/api/planner_profiles/load'", app_js)
        self.assertIn(".planner-profile-panel", styles_css)
        self.assertIn(".planner-profile-actions", styles_css)
        self.assertIn(".planner-profile-select", styles_css)

    def test_factor_badges_expose_hover_effect_summary(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function factorBadgeTitle(factor)", app_js)
        self.assertIn("factor.effect_summary", app_js)
        self.assertIn('title="${escapeAttr(factorBadgeTitle(factor))}"', app_js)
        self.assertIn('aria-label="${escapeAttr(factorBadgeTitle(factor))}"', app_js)

    def test_parent_card_header_reserves_space_for_top_right_controls(self):
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn(".parent-card-rich .card-head {", styles_css)
        self.assertIn("padding-right: 86px;", styles_css)

    def test_action_history_only_autoscrolls_when_already_at_bottom(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")

        self.assertIn("const previousWrap = els.startStatus.querySelector('.action-history-wrap');", app_js)
        self.assertIn("const previousPinnedToBottom = !previousWrap", app_js)
        self.assertIn("(previousWrap.scrollHeight - previousWrap.clientHeight - previousWrap.scrollTop) <= 24", app_js)
        self.assertIn("wrap.scrollTop = Math.min(", app_js)

    def test_action_history_shows_actual_race_strategy(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")

        self.assertIn("const raceStrategyDetail = row =>", app_js)
        self.assertIn("row.running_style_label", app_js)
        self.assertIn("raceResult.running_style_label", app_js)
        self.assertIn("STRAT ${used} (wanted ${desired}", app_js)
        self.assertIn("const strategyTag = normalizeHistoryAction(row).action === 'race' ? raceStrategyDetail(row) : '';", app_js)
        self.assertIn("if (row.action === 'race_progress')", app_js)

    def test_team_bar_shows_legacy_start_bonus_preview(self):
        app_js = (PROJECT_ROOT / "public" / "app.js").read_text(encoding="utf-8")
        styles_css = (PROJECT_ROOT / "public" / "styles.css").read_text(encoding="utf-8")

        self.assertIn("const LEGACY_START_BLUE_STAR_BONUS = { 1: 5, 2: 12, 3: 21 };", app_js)
        self.assertIn("function combinedLegacyAptitudePreview(trainee, parents, nodes = ['self', 'p1', 'p2'])", app_js)
        self.assertIn("const legacyPreview = legacyStartPreview(trainee, [parent1, parent2]);", app_js)
        self.assertIn("function renderLegacyStartPreviewPanel(preview, options = {})", app_js)
        self.assertIn("Start gains", app_js)
        self.assertIn("Aptitude upgrades", app_js)
        self.assertIn("team-item-legacy-sub", app_js)
        self.assertIn("legacy-start-stat-strip", app_js)
        self.assertIn("legacy-start-apt-chip", app_js)
        self.assertIn(".team-item-legacy-sub", styles_css)
        self.assertIn(".combo-affinity-kpi.combo-affinity-legacy strong", styles_css)
        self.assertIn(".legacy-start-preview-panel", styles_css)
        self.assertIn(".legacy-start-stat-chip", styles_css)


if __name__ == "__main__":
    unittest.main()
