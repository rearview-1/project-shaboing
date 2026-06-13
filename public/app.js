(() => {
        function safeLocalGet(key, fallback = '') {
            try {
                const value = localStorage.getItem(key);
                return value == null ? fallback : value;
            } catch (e) {
                return fallback;
            }
        }
        function safeLocalSet(key, value) {
            try {
                localStorage.setItem(key, String(value));
            } catch (e) {}
        }
        function safeLocalBool(key, fallback = false) {
            try {
                const value = localStorage.getItem(key);
                if (value == null) return fallback;
                return ['1', 'true', 'yes', 'on'].includes(String(value).trim().toLowerCase());
            } catch (e) {
                return fallback;
            }
        }
        function browserSlugify(value, fallback = 'planner_profile') {
            const cleaned = String(value || '')
                .replace(/[^\w.\- ]+/g, '')
                .replace(/\s+/g, ' ')
                .trim();
            return cleaned || fallback;
        }
        function downloadTextFile(filename, text, mime = 'application/json;charset=utf-8') {
            const blob = new Blob([String(text || '')], { type: mime });
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement('a');
            anchor.href = url;
            anchor.download = filename;
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
            setTimeout(() => URL.revokeObjectURL(url), 0);
        }
        function loadFavoriteState() {
            try {
                const parsed = JSON.parse(localStorage.getItem('sweepyFavorites') || '{}');
                return {
                    trainees: parsed && typeof parsed.trainees === 'object' && parsed.trainees ? parsed.trainees : {},
                    parents: parsed && typeof parsed.parents === 'object' && parsed.parents ? parsed.parents : {},
                    borrowUmas: parsed && typeof parsed.borrowUmas === 'object' && parsed.borrowUmas ? parsed.borrowUmas : {}
                };
            } catch (e) {
                return { trainees: {}, parents: {}, borrowUmas: {} };
            }
        }
        function saveFavoriteState() {
            try {
                localStorage.setItem('sweepyFavorites', JSON.stringify(state.favorites));
            } catch (e) {}
        }
        const DAILY_ASSIGNMENT_KEYS = ['daily_race', 'legend_race', 'daily_legend_race'];
        const DAILY_ASSIGNMENT_LABELS = {
            all: 'All Tags',
            daily_race: 'Daily Race',
            legend_race: 'Legend Race',
            daily_legend_race: 'Daily Legend Race'
        };
        function defaultDailyAssignment(style = '2') {
            return { trained_chara_id: '', running_style: String(style || '2') };
        }
        function loadDailyAssignments() {
            let parsed = {};
            try {
                parsed = JSON.parse(localStorage.getItem('dailyRaceAssignments') || '{}') || {};
            } catch (e) {
                parsed = {};
            }
            const result = { all: defaultDailyAssignment() };
            ['all', ...DAILY_ASSIGNMENT_KEYS].forEach(key => {
                const row = parsed && typeof parsed[key] === 'object' && parsed[key] ? parsed[key] : {};
                result[key] = {
                    trained_chara_id: String(row.trained_chara_id || ''),
                    running_style: String(row.running_style || '2')
                };
            });
            return result;
        }
        function saveDailyAssignments() {
            try {
                localStorage.setItem('dailyRaceAssignments', JSON.stringify(state.dailyAssignments || {}));
            } catch (e) {}
        }
const state = { 
            needs2fa: false, 
            isLoading: false, 
            account: null, 
            isDeletingCareer: false, 
            isFetchingFriends: false, 
            isAddingFriendById: false,
            isUnfollowingFriend: false,
            isStartingCareer: false, 
            isVerifyingStart: false,
            presets: [], 
            selectedPreset: safeLocalGet('selectedPreset', ''), 
            teamBundlePresets: [],
            selectedTeamBundlePreset: safeLocalGet('selectedTeamBundlePreset', ''),
            isSavingTeamBundlePreset: false,
            isTeamBundleMenuOpen: false,
            runnerTimer: 0, 
            accountSyncTimer: 0,
            tpTickTimer: 0,
            runnerRunning: false,
            loopActive: false,
            careerCompleteNotifyEnabled: safeLocalBool('careerCompleteNotifyEnabled', true),
            loopEnabled: safeLocalBool('loopEnabled', false),
            loopMode: safeLocalGet('loopMode', 'forever'),
            loopCareerLimit: Number(safeLocalGet('loopCareerLimit', '10')) || 10,
            loopFanLimit: Number(safeLocalGet('loopFanLimit', '100000000')) || 100000000,
            tpRecoveryMode: 0,
            isStoppingRunner: false,
            isEndingCareer: false,
            lastCareerCompletionToken: safeLocalGet('lastCareerCompletionToken', ''),
            favorites: loadFavoriteState(),
            librarySearch: { decks: '', friends: '', cardBorrows: '', trainees: '', parents: '', cards: '', borrowUmas: '', teamTrials: '' },
            teamTrialsData: null,
            teamTrialsLoading: false,
            teamTrialsSourceKind: '',
            teamTrialsSelectedTeamKey: '',
            teamTrialsSelectedCharacterKey: '',
            isSavingPreset: false,
            raceData: [],
            selectedRaces: new Set(),
            selectedRaceStyles: {},
            racePlanText: "",
            isSyncingDashboard: false,
            isRefreshingBackend: false,
            skillBuyOnSight: "",
            skillBlacklist: "",
            skillProfileStyle: "",
            skillProfileDistance: "",
            parentGoalBlue: "",
            parentGoalPink: "",
            parentGoalGreen: "",
            parentGoalWhite: "",
            alarmClockMode: "carats",
            alarmClockLimit: 5,
            plannerProfiles: [],
            selectedPlannerProfile: safeLocalGet('selectedPlannerProfile', ''),
            activeFriendProfile: null,
            runnerSnapshot: null,
            deckAdvice: null,
            deckAdviceKey: "",
            deckAdviceLoading: false,
            deckAdviceRequestId: 0,
            deckAdviceExpanded: false,
            supportInventoryBusy: false,
            supportInventoryStatusMessage: '',
            deckEditorSearch: '',
            deckEditorBusy: false,
            dailyEvents: null,
            dailyEventsLoading: false,
            dailyEventsRunning: false,
            selectedShowtimeDifficulty: safeLocalGet('selectedShowtimeDifficulty', ''),
            selectedDailyTrainedCharaId: safeLocalGet('selectedDailyTrainedCharaId', ''),
            selectedDailyRunningStyle: safeLocalGet('selectedDailyRunningStyle', '2'),
            selectedDailyRaceId: safeLocalGet('selectedDailyRaceId', ''),
            selectedLegendRaceId: safeLocalGet('selectedLegendRaceId', ''),
            selectedDailyLegendRaceId: safeLocalGet('selectedDailyLegendRaceId', ''),
            dailyAssignments: loadDailyAssignments(),
            activeDailyEventTab: safeLocalGet('activeDailyEventTab', 'run'),
            activeDailyRacePicker: null,
            dailyRacePickerQuery: ''
        };
        function ensureAlarmClockMarkup() {
            if (document.getElementById('alarm-clock-mode-select')) return;
            const panel = document.querySelector('.skill-plan-panel');
            if (!panel) return;
            const anchor = document.getElementById('skill-buy-input')?.closest('.skill-text-field');
            const markup = `
                <div class="seg-field race-continue-field">
                    <span class="seg-field-label">Alarm clocks</span>
                    <div class="seg-group" data-seg-target="alarm-clock-mode-select">
                        <button type="button" class="seg-btn" data-seg-value="normal">Normal</button>
                        <button type="button" class="seg-btn active accent" data-seg-value="carats">+ Carats</button>
                        <button type="button" class="seg-btn" data-seg-value="none">None</button>
                    </div>
                    <select id="alarm-clock-mode-select" class="skill-profile-select" hidden>
                        <option value="normal">NORMAL CLOCKS ONLY</option>
                        <option value="carats">CLOCKS + CARAT EXCHANGE</option>
                        <option value="none">DISABLED</option>
                    </select>
                    <div class="alarm-clock-row">
                        <label class="alarm-clock-limit-label" for="alarm-clock-limit-input">
                            <span>Max uses/career</span>
                            <input id="alarm-clock-limit-input" class="seg-input alarm-clock-limit-input" type="number" min="0" max="5" step="1" value="5">
                        </label>
                        <button id="alarm-clock-save-btn" class="btn btn-sm" type="button">SAVE CLOCKS</button>
                    </div>
                    <div id="alarm-clock-status" class="skill-plan-status"></div>
                </div>`;
            if (anchor) {
                anchor.insertAdjacentHTML('beforebegin', markup);
            } else {
                panel.insertAdjacentHTML('beforeend', markup);
            }
        }
        ensureAlarmClockMarkup();
        const els = {
            loadingScreen: document.getElementById('loading-screen'),
            navbar: document.querySelector('.navbar'),
            themeToggle: document.getElementById('theme-toggle'),
            brandMark: document.querySelector('.title span'),
            loginBtn: document.getElementById('login-btn'),
            authRefreshBtn: document.getElementById('auth-refresh-btn'),
            topAuthRefreshBtn: document.getElementById('top-auth-refresh-btn'),
            careerNotifyToggleBtn: document.getElementById('career-notify-toggle-btn'),
            logoutBtn: document.getElementById('logout-btn'),
            syncDashboardBtn: document.getElementById('sync-dashboard-btn'),
            refreshBackendBtn: document.getElementById('refresh-backend-btn'),
            turnDelayMin: document.getElementById('turn-delay-min'),
            turnDelayMax: document.getElementById('turn-delay-max'),
            temptFateBtn: document.getElementById('tempt-fate-btn'),
            teamBundleMenu: document.getElementById('team-bundle-menu'),
            teamBundleToggleBtn: document.getElementById('team-bundle-toggle-btn'),
            teamBundlePopover: document.getElementById('team-bundle-popover'),
            teamBundlePresetSelect: document.getElementById('team-bundle-preset-select'),
            teamBundlePresetNameInput: document.getElementById('team-bundle-preset-name-input'),
            teamBundlePresetApplyBtn: document.getElementById('team-bundle-preset-apply-btn'),
            teamBundlePresetSaveBtn: document.getElementById('team-bundle-preset-save-btn'),
            teamBundlePresetDeleteBtn: document.getElementById('team-bundle-preset-delete-btn'),
            teamBundlePresetStatus: document.getElementById('team-bundle-preset-status'),
            loginView: document.getElementById('login-view'),
            dashboardView: document.getElementById('dashboard-view'),
            teamTrialsScreenBtn: document.getElementById('team-trials-screen-btn'),
            teamTrialsScreen: document.getElementById('team-trials-screen'),
            teamTrialsBackDashboardBtn: document.getElementById('team-trials-back-dashboard-btn'),
            teamComboAffinity: document.getElementById('team-combo-affinity'),
            errorMsg: document.getElementById('error-msg'),
            standardFields: document.getElementById('standard-fields'),
            faFields: document.getElementById('2fa-fields'),
            umaGrid: document.getElementById('uma-grid'),
            cardGrid: document.getElementById('card-grid'),
            cardGridWrapper: document.getElementById('card-grid-wrapper'),
            cardsToggle: document.getElementById('cards-toggle'),
            cardsChevron: document.getElementById('cards-chevron'),
            parentGrid: document.getElementById('parent-grid'),
            friendGrid: document.getElementById('friend-grid'),
            cardBorrowGrid: document.getElementById('card-borrow-grid'),
            cardBorrowStatus: document.getElementById('card-borrow-status'),
            cardBorrowSearchInput: document.getElementById('card-borrow-search-input'),
            cardBorrowRefreshBtn: document.getElementById('card-borrow-refresh-btn'),
            borrowUmaGrid: document.getElementById('borrow-uma-grid'),
            borrowUmaCount: document.getElementById('borrow-uma-count'),
            borrowUmaStatus: document.getElementById('borrow-uma-status'),
            borrowUmaSearchInput: document.getElementById('borrow-uma-search-input'),
            borrowUmaRefreshBtn: document.getElementById('borrow-uma-refresh-btn'),
            deckList: document.getElementById('deck-list'),
            botViewRefreshBtn: document.getElementById('bot-view-refresh-btn'),
            botViewOutput: document.getElementById('bot-view-output'),
            umaCount: document.getElementById('uma-count'),
            cardCount: document.getElementById('card-count'),
            parentCount: document.getElementById('parent-count'),
            friendCount: document.getElementById('friend-count'),
            friendStatus: document.getElementById('friend-status'),
            friendFollowingQuota: document.getElementById('friend-following-quota'),
            friendRefreshBtn: document.getElementById('friend-refresh-btn'),
            friendIdInput: document.getElementById('friend-id-input'),
            friendIdAddBtn: document.getElementById('friend-id-add-btn'),
            friendIdStatus: document.getElementById('friend-id-status'),
            friendProfileModal: document.getElementById('friend-profile-modal-overlay'),
            friendProfileHero: document.getElementById('friend-profile-hero'),
            friendProfileBody: document.getElementById('friend-profile-modal-body'),
            friendProfileStatus: document.getElementById('friend-profile-status'),
            friendProfileCloseBtn: document.getElementById('friend-profile-close-btn'),
            friendProfileCloseXBtn: document.getElementById('friend-profile-modal-close'),
            friendProfileUseBtn: document.getElementById('friend-profile-use-btn'),
            friendProfileUnfollowBtn: document.getElementById('friend-profile-unfollow-btn'),
            presetSelect: document.getElementById('preset-select'),
            startCareerBtn: document.getElementById('start-career-btn'),
            verifyStartBtn: document.getElementById('verify-start-btn'),
            calibrateBtn: document.getElementById('calibrate-btn'),
            calibrateStatus: document.getElementById('calibrate-status'),
            tpRecoverySelect: document.getElementById('tp-recovery-select'),
            loopToggleBtn: document.getElementById('loop-toggle-btn'),
            loopModeSelect: document.getElementById('loop-mode-select'),
            loopCareerLimitInput: document.getElementById('loop-career-limit-input'),
            loopFanLimitInput: document.getElementById('loop-fan-limit-input'),
            endCareerBtn: document.getElementById('end-career-btn'),
            stopRunnerBtn: document.getElementById('stop-runner-btn'),
            dailyEventPanel: document.getElementById('daily-event-panel'),
            dailyEventSummary: document.getElementById('daily-event-summary'),
            dailyEventRefreshBtn: document.getElementById('daily-event-refresh-btn'),
            dailyEventTabRun: document.getElementById('daily-event-tab-run'),
            dailyEventTabAssignments: document.getElementById('daily-event-tab-assignments'),
            dailyEventRunPanel: document.getElementById('daily-event-run-panel'),
            dailyEventAssignmentsPanel: document.getElementById('daily-event-assignments-panel'),
            showtimeDifficultySelect: document.getElementById('showtime-difficulty-select'),
            dailyTrainedCharaSelect: document.getElementById('daily-trained-chara-select'),
            dailyRunningStyleSelect: document.getElementById('daily-running-style-select'),
            dailyRaceIdSelect: document.getElementById('daily-race-id-select'),
            legendRaceIdInput: document.getElementById('legend-race-id-input'),
            dailyLegendRaceIdSelect: document.getElementById('daily-legend-race-id-select'),
            dailyRacePickerBtn: document.getElementById('daily-race-picker-btn'),
            legendRacePickerBtn: document.getElementById('legend-race-picker-btn'),
            dailyLegendRacePickerBtn: document.getElementById('daily-legend-race-picker-btn'),
            dailyAssignmentAll: document.getElementById('daily-assignment-all'),
            dailyAssignmentDailyRace: document.getElementById('daily-assignment-daily-race'),
            dailyAssignmentLegendRace: document.getElementById('daily-assignment-legend-race'),
            dailyAssignmentDailyLegendRace: document.getElementById('daily-assignment-daily-legend-race'),
            dailyAssignmentStatus: document.getElementById('daily-assignment-status'),
            dailyRacePickerOverlay: document.getElementById('daily-race-picker-overlay'),
            dailyRacePickerTitle: document.getElementById('daily-race-picker-title'),
            dailyRacePickerSubtitle: document.getElementById('daily-race-picker-subtitle'),
            dailyRacePickerClose: document.getElementById('daily-race-picker-close'),
            dailyRacePickerCancel: document.getElementById('daily-race-picker-cancel'),
            dailyRacePickerAuto: document.getElementById('daily-race-picker-auto'),
            dailyRacePickerSearch: document.getElementById('daily-race-picker-search'),
            dailyRacePickerList: document.getElementById('daily-race-picker-list'),
            dailyRunTeamTrials: document.getElementById('daily-run-team-trials'),
            dailyRunDailyRace: document.getElementById('daily-run-daily-race'),
            dailyRunLegendRace: document.getElementById('daily-run-legend-race'),
            dailyRunDailyLegendRace: document.getElementById('daily-run-daily-legend-race'),
            dailyDrainShops: document.getElementById('daily-drain-shops'),
            dailyEventRunBtn: document.getElementById('daily-event-run-btn'),
            dailyEventStatus: document.getElementById('daily-event-status'),
            setupLegacySection: document.getElementById('setup-legacy-section'),
            setupLegacyDetails: document.getElementById('setup-legacy-details'),
            setupLegacySummary: document.getElementById('setup-legacy-summary'),
            setupLegacyDetailsBody: document.getElementById('setup-legacy-details-body'),
            careerStatsPanel: document.getElementById('career-stats-panel'),
            careerStatsPortrait: document.getElementById('career-stats-portrait'),
            careerStatsName: document.getElementById('career-stats-name'),
            careerStatsSub: document.getElementById('career-stats-sub'),
            careerStatsHp: document.getElementById('career-stats-hp'),
            careerStatsMood: document.getElementById('career-stats-mood'),
            careerStatsSp: document.getElementById('career-stats-sp'),
            careerStatsClocks: document.getElementById('career-stats-clocks'),
            careerStatsGrid: document.getElementById('career-stats-grid'),
            deckSearchInput: document.getElementById('deck-search-input'),
            deckEditorStatus: document.getElementById('deck-editor-status'),
            deckEditorCardSearch: document.getElementById('deck-editor-card-search'),
            deckEditorCardList: document.getElementById('deck-editor-card-list'),
            deckResetBtn: document.getElementById('deck-reset-btn'),
            friendSearchInput: document.getElementById('friend-search-input'),
            teamTrialsSearchInput: document.getElementById('team-trials-search-input'),
            teamTrialsRefreshBtn: document.getElementById('team-trials-refresh-btn'),
            teamTrialsLocalBtn: document.getElementById('team-trials-local-btn'),
            teamTrialsSourceLabel: document.getElementById('team-trials-source-label'),
            teamTrialsStatus: document.getElementById('team-trials-status'),
            teamTrialsPlayerList: document.getElementById('team-trials-player-list'),
            teamTrialsListView: document.getElementById('team-trials-list-view'),
            teamTrialsTeamView: document.getElementById('team-trials-team-view'),
            teamTrialsTeamBackBtn: document.getElementById('team-trials-team-back-btn'),
            teamTrialsTeamTitle: document.getElementById('team-trials-team-title'),
            teamTrialsTeamMeta: document.getElementById('team-trials-team-meta'),
            teamTrialsTeamLayout: document.getElementById('team-trials-team-layout'),
            teamTrialsCharacterView: document.getElementById('team-trials-character-view'),
            teamTrialsCharacterBackBtn: document.getElementById('team-trials-character-back-btn'),
            teamTrialsCharacterTitle: document.getElementById('team-trials-character-title'),
            teamTrialsCharacterMeta: document.getElementById('team-trials-character-meta'),
            teamTrialsCharacterDetail: document.getElementById('team-trials-character-detail'),
            traineeSearchInput: document.getElementById('trainee-search-input'),
            parentSearchInput: document.getElementById('parent-search-input'),
            cardSearchInput: document.getElementById('card-search-input'),
            cardUncapAllBtn: document.getElementById('card-uncap-all-btn'),
            cardInventoryStatus: document.getElementById('card-inventory-status'),
            startStatus: document.getElementById('start-status'),
            accountStrip: document.getElementById('account-strip'),
            careerModal: document.getElementById('career-modal'),
            careerModalCopy: document.getElementById('career-modal-copy'),
            careerCancelBtn: document.getElementById('career-cancel-btn'),
            careerDeleteBtn: document.getElementById('career-delete-btn'),
            raceToggle: document.getElementById('race-toggle'),
            raceChevron: document.getElementById('race-chevron'),
            raceBody: document.getElementById('race-body'),
            saveRacesBtn: document.getElementById('save-races-btn'),
            racePlanInput: document.getElementById('race-plan-input'),
            racePlanFile: document.getElementById('race-plan-file'),
            racePlanSaveBtn: document.getElementById('race-plan-save-btn'),
            racePlanStatus: document.getElementById('race-plan-status'),
            raceOptionsContent: document.getElementById('race-options-content'),
            racePopupOverlay: document.getElementById('race-slot-popup-overlay'),
            racePopupTitle: document.getElementById('race-slot-popup-title'),
            racePopupBody: document.getElementById('race-slot-popup-body'),
            racePopupClose: document.getElementById('race-slot-popup-close'),
            raceStyleList: document.getElementById('race-style-list'),
            raceStyleCount: document.getElementById('race-style-count'),
            raceModalStatus: document.getElementById('race-modal-status'),
            raceModalSearchInput: document.getElementById('race-modal-search'),
            raceModalLoadBtn: document.getElementById('race-modal-load-btn'),
            raceModalImportBtn: document.getElementById('race-modal-import-btn'),
            raceModalImportFile: document.getElementById('race-modal-import-file'),
            raceModalResetBtn: document.getElementById('race-modal-reset-btn'),
            raceModalSidebar: document.getElementById('race-modal-sidebar'),
            skillsToggle: document.getElementById('skills-toggle'),
            skillsChevron: document.getElementById('skills-chevron'),
            skillsBody: document.getElementById('skills-body'),
            skillStyleSelect: document.getElementById('skill-style-select'),
            skillDistanceSelect: document.getElementById('skill-distance-select'),
            skillBuyTimingSelect: document.getElementById('skill-buy-timing-select'),
            skillBuyInput: document.getElementById('skill-buy-input'),
            skillBlacklistInput: document.getElementById('skill-blacklist-input'),
            parentGoalBlueInput: document.getElementById('parent-goal-blue-input'),
            parentGoalPinkInput: document.getElementById('parent-goal-pink-input'),
            parentGoalGreenInput: document.getElementById('parent-goal-green-input'),
            parentGoalWhiteInput: document.getElementById('parent-goal-white-input'),
            alarmClockModeSelect: document.getElementById('alarm-clock-mode-select'),
            alarmClockLimitInput: document.getElementById('alarm-clock-limit-input'),
            alarmClockSaveBtn: document.getElementById('alarm-clock-save-btn'),
            alarmClockStatus: document.getElementById('alarm-clock-status'),
            plannerProfileNameInput: document.getElementById('planner-profile-name-input'),
            plannerProfileSelect: document.getElementById('planner-profile-select'),
            plannerProfileSaveBtn: document.getElementById('planner-profile-save-btn'),
            plannerProfileLoadBtn: document.getElementById('planner-profile-load-btn'),
            plannerProfileExportBtn: document.getElementById('planner-profile-export-btn'),
            plannerProfileFile: document.getElementById('planner-profile-file'),
            plannerProfileStatus: document.getElementById('planner-profile-status'),
            skillPlanSaveBtn: document.getElementById('skill-plan-save-btn'),
            skillPlanStatus: document.getElementById('skill-plan-status'),
            deckAdvicePanel: document.getElementById('deck-advice-panel'),
            deckAdviceToggle: document.getElementById('deck-advice-toggle'),
            deckAdviceConfidence: document.getElementById('deck-advice-confidence'),
            deckAdviceMessage: document.getElementById('deck-advice-message'),
            deckAdviceMeta: document.getElementById('deck-advice-meta'),
            deckAdviceList: document.getElementById('deck-advice-list')
        };
        const RACE_STYLE_OPTIONS = [
            { value: '', label: 'Default / profile' },
            { value: 'front_runner', label: 'Front' },
            { value: 'pace_chaser', label: 'Pace' },
            { value: 'late_surger', label: 'Late' },
            { value: 'end_closer', label: 'End' }
        ];
        const RACE_STYLE_ALIAS_MAP = {
            'front': 'front_runner',
            'front runner': 'front_runner',
            'front_runner': 'front_runner',
            'nige': 'front_runner',
            'pace': 'pace_chaser',
            'pace chaser': 'pace_chaser',
            'pace_chaser': 'pace_chaser',
            'senko': 'pace_chaser',
            'late': 'late_surger',
            'late surger': 'late_surger',
            'late_surger': 'late_surger',
            'sashi': 'late_surger',
            'end': 'end_closer',
            'end closer': 'end_closer',
            'end_closer': 'end_closer',
            'closer': 'end_closer',
            'oikomi': 'end_closer'
        };
        const RACE_STYLE_LABELS = {
            front_runner: 'Front',
            pace_chaser: 'Pace',
            late_surger: 'Late',
            end_closer: 'End'
        };
        function setLoadingScreen(visible) {
            if (!els.loadingScreen) return;
            els.loadingScreen.classList.toggle('hidden', !visible);
        }
        function hideNavbar() {
            document.body.classList.add('pre-login');
            if (els.brandMark) els.brandMark.classList.remove('is-entrance');
        }
        function showNavbar() {
            document.body.classList.remove('pre-login');
        }
        function playBrandIntro() {
            if (!els.brandMark) return;
            els.brandMark.classList.remove('is-entrance');
            void els.brandMark.offsetWidth;
            els.brandMark.classList.add('is-entrance');
            window.setTimeout(() => els.brandMark.classList.remove('is-entrance'), 950);
        }
        hideNavbar();
        function syncDashboardHeight() {
            const navbar = document.querySelector('.navbar');
            const navbarHeight = navbar ? navbar.getBoundingClientRect().height : 0;
            const availableHeight = Math.max(360, Math.floor(window.innerHeight - navbarHeight));
            document.documentElement.style.setProperty('--dashboard-height', `${availableHeight}px`);
            syncDashboardCollapseState(false);
        }
        window.addEventListener('resize', syncDashboardHeight);
        window.addEventListener('orientationchange', syncDashboardHeight);
        syncDashboardHeight();
        const panelToggleSyncers = [];
        const dashboardMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
        let dashboardLayoutAnimation = 0;
        const dashboardAnimationMs = 420;
        function isCompactDashboard() {
            return window.matchMedia('(max-width: 850px)').matches;
        }
        function getPanelLayoutTarget(setupCollapsed, contentCollapsed) {
            const compact = isCompactDashboard();
            const gutter = document.querySelector('.split-gutter-controls');
            const dashboardRect = els.dashboardView.getBoundingClientRect();
            const gutterRect = gutter.getBoundingClientRect();
            const gutterSize = compact ? gutterRect.height : gutterRect.width;
            const available = Math.max(0, (compact ? dashboardRect.height : dashboardRect.width) - gutterSize);
            if (compact) {
                const setupSize = setupCollapsed ? 0 : contentCollapsed ? available : available * 0.34;
                const contentSize = contentCollapsed ? 0 : setupCollapsed ? available : Math.max(340, available - setupSize);
                return { compact, gutterSize, setupSize, contentSize };
            }
            const setupSize = setupCollapsed ? 0 : contentCollapsed ? available : Math.min(available * 0.62, available - 340);
            const contentSize = contentCollapsed ? 0 : setupCollapsed ? available : Math.max(340, available - setupSize);
            return { compact, gutterSize, setupSize, contentSize };
        }
        function setDashboardTemplate(layout, setupSize, contentSize) {
            const safeSetup = Math.max(0, setupSize);
            const safeContent = Math.max(0, contentSize);
            if (layout.compact) {
                els.dashboardView.style.gridTemplateColumns = '';
                els.dashboardView.style.gridTemplateRows = `${safeSetup}px ${layout.gutterSize}px ${safeContent}px`;
            } else {
                els.dashboardView.style.gridTemplateRows = '';
                els.dashboardView.style.gridTemplateColumns = `${safeSetup}px ${layout.gutterSize}px ${safeContent}px`;
            }
        }
        function easeDashboardLayout(t) {
            return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
        }
        function syncDashboardCollapseState(animate = false) {
            const setupPanel = document.getElementById('setup-panel');
            const contentPanel = document.getElementById('content-panel');
            if (!setupPanel || !contentPanel || !els.dashboardView) return;
            if (setupPanel.classList.contains('collapsed') && contentPanel.classList.contains('collapsed')) {
                contentPanel.classList.remove('collapsed');
            }
            const setupCollapsed = setupPanel.classList.contains('collapsed');
            const contentCollapsed = contentPanel.classList.contains('collapsed');
            els.dashboardView.classList.toggle('setup-collapsed', setupCollapsed);
            els.dashboardView.classList.toggle('content-collapsed', contentCollapsed);
            if (!els.dashboardView.classList.contains('active')) return;
            const layout = getPanelLayoutTarget(setupCollapsed, contentCollapsed);
            if (dashboardLayoutAnimation) {
                cancelAnimationFrame(dashboardLayoutAnimation);
                dashboardLayoutAnimation = 0;
            }
            els.dashboardView.style.transition = 'none';
            if (!animate || dashboardMotion.matches) {
                setDashboardTemplate(layout, layout.setupSize, layout.contentSize);
                return;
            }
            const compact = layout.compact;
            const setupRect = setupPanel.getBoundingClientRect();
            const contentRect = contentPanel.getBoundingClientRect();
            const startSetup = compact ? setupRect.height : setupRect.width;
            const startContent = compact ? contentRect.height : contentRect.width;
            const targetSetup = layout.setupSize;
            const targetContent = layout.contentSize;
            if (Math.abs(startSetup - targetSetup) < 0.5 && Math.abs(startContent - targetContent) < 0.5) {
                setDashboardTemplate(layout, targetSetup, targetContent);
                return;
            }
            const startedAt = performance.now();
            const step = now => {
                const t = Math.min(1, (now - startedAt) / dashboardAnimationMs);
                const eased = easeDashboardLayout(t);
                setDashboardTemplate(
                    layout,
                    startSetup + (targetSetup - startSetup) * eased,
                    startContent + (targetContent - startContent) * eased
                );
                if (t < 1) {
                    dashboardLayoutAnimation = requestAnimationFrame(step);
                } else {
                    setDashboardTemplate(layout, targetSetup, targetContent);
                    dashboardLayoutAnimation = 0;
                }
            };
            setDashboardTemplate(layout, startSetup, startContent);
            dashboardLayoutAnimation = requestAnimationFrame(step);
        }
        function syncPanelToggleButtons() {
            panelToggleSyncers.forEach(sync => sync());
        }
        function makePanelToggle(panelId, btnId, collapseIcon, expandIcon) {
            const panel = document.getElementById(panelId);
            const btn = document.getElementById(btnId);
            const label = (btn.dataset.panelLabel || 'panel').toLowerCase();
            const renderChevrons = icon => `
                <span class="panel-collapse-btn-chevron-stack" aria-hidden="true">
                    <span>${icon}</span>
                    <span>${icon}</span>
                    <span>${icon}</span>
                </span>
            `;
            const syncButton = () => {
                const isCollapsed = panel.classList.contains('collapsed');
                const icon = isCollapsed ? expandIcon : collapseIcon;
                btn.classList.toggle('is-collapsed', isCollapsed);
                btn.innerHTML = renderChevrons(icon);
                btn.setAttribute('title', `${isCollapsed ? 'Expand' : 'Collapse'} ${label}`);
                btn.setAttribute('aria-label', `${isCollapsed ? 'Expand' : 'Collapse'} ${label}`);
                btn.setAttribute('aria-expanded', String(!isCollapsed));
            };
            panelToggleSyncers.push(syncButton);
            btn.addEventListener('click', () => {
                panel.classList.toggle('collapsed');
                syncDashboardCollapseState(true);
                syncPanelToggleButtons();
            });
            syncDashboardCollapseState(false);
            syncButton();
        }
        makePanelToggle('setup-panel',   'setup-collapse-btn',   '&lt;', '&gt;');
        makePanelToggle('content-panel', 'content-collapse-btn', '&gt;', '&lt;');
        function makeSectionToggle(toggleId, chevronId, bodyId, startExpanded) {
            const toggle  = document.getElementById(toggleId);
            const chevron = document.getElementById(chevronId);
            const body    = document.getElementById(bodyId);
            if (!toggle || !body) return;
            const setInitial = () => {
                const expanded = body.classList.contains('expanded');
                body.style.height = expanded ? 'auto' : '0px';
                chevron.classList.toggle('expanded', expanded);
            };
            const expand = () => {
                body.classList.add('expanded');
                chevron.classList.add('expanded');
                body.style.height = '0px';
                body.offsetHeight;
                body.style.height = `${body.scrollHeight}px`;
            };
            const collapse = () => {
                body.style.height = `${body.scrollHeight}px`;
                body.offsetHeight;
                body.classList.remove('expanded');
                chevron.classList.remove('expanded');
                body.style.height = '0px';
            };
            body.addEventListener('transitionend', event => {
                if (event.propertyName === 'height' && body.classList.contains('expanded')) body.style.height = 'auto';
            });
            toggle.addEventListener('click', () => {
                if (body.classList.contains('expanded')) collapse();
                else expand();
            });
            setInitial();
        }
        makeSectionToggle('decks-toggle',    'decks-chevron',    'decks-body',    true);
        makeSectionToggle('bot-view-toggle', 'bot-view-chevron', 'bot-view-body', false);
        makeSectionToggle('friends-toggle',  'friends-chevron',  'friends-body',  true);
        makeSectionToggle('trainees-toggle', 'trainees-chevron', 'trainees-body', true);
        makeSectionToggle('parents-toggle',  'parents-chevron',  'parents-body',  true);
        makeSectionToggle('borrow-umas-toggle', 'borrow-umas-chevron', 'borrow-umas-body', true);
        makeSectionToggle('cards-toggle',    'cards-chevron',    'card-grid-wrapper', false);
        const applyTheme = theme => {
            const nextTheme = theme === 'blue' ? 'blue' : 'pink';
            document.documentElement.dataset.theme = nextTheme;
            document.documentElement.classList.toggle('theme-blue', nextTheme === 'blue');
            document.body.classList.toggle('theme-blue', nextTheme === 'blue');
            return nextTheme;
        };
        applyTheme(localStorage.getItem('theme'));
        const savedUsername = localStorage.getItem('saved_username');
        const savedPassword = localStorage.getItem('saved_password');
        if (savedUsername) document.getElementById('username').value = savedUsername;
        if (savedPassword) document.getElementById('password').value = savedPassword;
        els.themeToggle.addEventListener('click', () => {
            const nextTheme = document.body.classList.contains('theme-blue') ? 'pink' : 'blue';
            applyTheme(nextTheme);
            localStorage.setItem('theme', nextTheme);
        });
        const sleep = ms => new Promise(resolve => window.setTimeout(resolve, ms));
        const nextFrame = () => new Promise(resolve => requestAnimationFrame(resolve));
        async function waitForDomPaint(frames = 2) {
            for (let i = 0; i < frames; i++) await nextFrame();
        }
        async function apiJson(url, options = {}) {
            const res = await fetch(url, options);
            return res.json();
        }
        function escapeHtml(value) {
            return String(value ?? '').replace(/[&<>"']/g, char => ({
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;'
            }[char]));
        }
        function escapeAttr(value) {
            return escapeHtml(value);
        }
        function normalizeDelayBounds(min, max, disabled = false, restoreMin = null, restoreMax = null) {
            const fallbackMin = Number.isFinite(Number(restoreMin)) ? Number(restoreMin) : 1.6;
            const fallbackMax = Number.isFinite(Number(restoreMax)) ? Number(restoreMax) : 3.7;
            if (disabled) return { min: 0, max: 0, restoreMin: fallbackMin, restoreMax: fallbackMax, disabled: true };
            const left = Math.max(0, Number.isFinite(Number(min)) ? Number(min) : fallbackMin);
            let right = Math.max(0, Number.isFinite(Number(max)) ? Number(max) : fallbackMax);
            if (left > right) right = left;
            return { min: left, max: right, restoreMin: left, restoreMax: right, disabled: false };
        }
        function setDelayControls(settings) {
            if (!els.turnDelayMin || !els.turnDelayMax || !els.temptFateBtn) return;
            const disabled = Boolean(settings.disabled);
            const restoreMin = Number.isFinite(Number(settings.restoreMin)) ? Number(settings.restoreMin) : Number(settings.restore_min);
            const restoreMax = Number.isFinite(Number(settings.restoreMax)) ? Number(settings.restoreMax) : Number(settings.restore_max);
            els.turnDelayMin.value = String(settings.min);
            els.turnDelayMax.value = String(settings.max);
            els.turnDelayMin.dataset.restoreValue = String(Number.isFinite(restoreMin) ? restoreMin : settings.min);
            els.turnDelayMax.dataset.restoreValue = String(Number.isFinite(restoreMax) ? restoreMax : settings.max);
            els.turnDelayMin.disabled = disabled;
            els.turnDelayMax.disabled = disabled;
            els.temptFateBtn.classList.toggle('is-active', disabled);
            els.temptFateBtn.innerText = disabled ? 'FATE TEMPTED' : 'TEMPT FATE';
        }
        async function saveDelaySettings(settings) {
            setDelayControls(settings);
            const data = await apiJson('/api/settings/turn-delay', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
            setDelayControls(normalizeDelayBounds(data.min, data.max, data.disabled, data.restore_min, data.restore_max));
        }
        async function loadDelaySettings() {
            if (!els.turnDelayMin || !els.turnDelayMax || !els.temptFateBtn) return;
            try {
                const data = await apiJson('/api/settings/turn-delay');
                setDelayControls(normalizeDelayBounds(data.min, data.max, data.disabled, data.restore_min, data.restore_max));
            } catch (e) {
                setDelayControls({ min: 1.6, max: 3.7, restoreMin: 1.6, restoreMax: 3.7, disabled: false });
            }
        }
        function bindDelayControls() {
            if (!els.turnDelayMin || !els.turnDelayMax || !els.temptFateBtn) return;
            const sync = () => {
                saveDelaySettings(normalizeDelayBounds(els.turnDelayMin.value, els.turnDelayMax.value, false));
            };
            els.turnDelayMin.addEventListener('input', sync);
            els.turnDelayMax.addEventListener('input', sync);
            els.temptFateBtn.addEventListener('click', () => {
                const active = els.temptFateBtn.classList.contains('is-active');
                const restoreMin = Number(els.turnDelayMin.dataset.restoreValue || 1.6);
                const restoreMax = Number(els.turnDelayMax.dataset.restoreValue || 3.7);
                saveDelaySettings(active
                    ? normalizeDelayBounds(restoreMin, restoreMax, false)
                    : normalizeDelayBounds(0, 0, true, restoreMin, restoreMax)
                );
            });
            loadDelaySettings();
        }
        function resetLoginState() {
            state.isLoading = false;
            els.loginBtn.innerText = state.needs2fa ? 'VALIDATE' : 'LOGIN';
        }
        function showLoginError(message, options = {}) {
            setLoadingScreen(false);
            els.errorMsg.innerText = String(message || 'FAIL').toUpperCase();
            els.errorMsg.style.display = 'block';
            if (els.authRefreshBtn) {
                els.authRefreshBtn.style.display = '';
            }
            resetLoginState();
        }
        function showTwoFactorPrompt() {
            setLoadingScreen(false);
            state.needs2fa = true;
            state.isLoading = false;
            els.standardFields.style.display = 'none';
            els.faFields.style.display = 'block';
            els.loginBtn.innerText = 'VALIDATE';
            els.errorMsg.innerText = '2FA REQUIRED';
            els.errorMsg.style.display = 'block';
        }
        function readLoginPayload() {
            return {
                username: document.getElementById('username').value,
                password: document.getElementById('password').value,
                code: document.getElementById('code').value
            };
        }
        function readAuthRefreshPayload() {
            const payload = readLoginPayload();
            if (!String(payload.username || '').trim()) payload.username = safeLocalGet('saved_username', '');
            if (!String(payload.password || '').trim()) payload.password = safeLocalGet('saved_password', '');
            return payload;
        }
        function authRefreshStatusSink() {
            if (els.loginView && els.loginView.style.display !== 'none') {
                return {
                    set(message, isError = false) {
                        els.errorMsg.innerText = message || '';
                        els.errorMsg.style.display = message ? 'block' : 'none';
                    }
                };
            }
            return {
                set(message, isError = false) {
                    setStartStatusMessage(message || '', isError);
                }
            };
        }
        function syncCareerNotifyToggle() {
            if (!els.careerNotifyToggleBtn) return;
            els.careerNotifyToggleBtn.style.display = state.account ? 'block' : 'none';
            els.careerNotifyToggleBtn.classList.toggle('is-active', state.careerCompleteNotifyEnabled);
            els.careerNotifyToggleBtn.textContent = state.careerCompleteNotifyEnabled ? 'NOTIFY ON' : 'NOTIFY OFF';
        }
        function buildCareerCompletionToken(runner, loop = {}) {
            return [
                Number(runner && runner.turn || 0),
                Number(runner && runner.steps || 0),
                Number(runner && runner.final_fans || 0),
                Number(loop && loop.completed || 0),
                String(runner && runner.last_action || ''),
                String(runner && runner.preset || '')
            ].join(':');
        }
        async function ensureNotificationPermission() {
            if (!('Notification' in window)) return false;
            if (Notification.permission === 'granted') return true;
            if (Notification.permission === 'denied') return false;
            try {
                const permission = await Notification.requestPermission();
                return permission === 'granted';
            } catch (e) {
                return false;
            }
        }
        function notifyCareerCompletion(runner, loop = {}) {
            if (!state.careerCompleteNotifyEnabled) return;
            if (!runner || !runner.finished || runner.last_error) return;
            const token = buildCareerCompletionToken(runner, loop);
            if (!token || token === state.lastCareerCompletionToken) return;
            state.lastCareerCompletionToken = token;
            safeLocalSet('lastCareerCompletionToken', token);
            if (!('Notification' in window) || Notification.permission !== 'granted') return;
            const title = loop && loop.active ? 'Sweepy career finished in loop' : 'Sweepy career complete';
            const bodyParts = [];
            const preset = String(runner.preset || '').trim();
            if (preset) bodyParts.push(preset);
            if (runner.turn) bodyParts.push(`Turn ${runner.turn}`);
            if (runner.final_fans) bodyParts.push(`${formatNumber(runner.final_fans)} fans`);
            if (loop && (loop.completed || loop.current)) {
                bodyParts.push(loopStatusText(loop));
            }
            try {
                new Notification(title, {
                    body: bodyParts.filter(Boolean).join(' | ') || 'A career run finished.'
                });
            } catch (e) {}
        }
        function resetSelection() {
            selection.deck = null;
            selection.friend = null;
            selection.trainee = null;
            selection.veterans = [];
        }
        function hideBrokenImage(img) {
            img.onerror = null;
            img.style.display = 'none';
        }
        window.hideBrokenImage = hideBrokenImage;
        const loginForm = document.getElementById('login-form');
        loginForm.addEventListener('submit', async event => {
            event.preventDefault();
            if (state.isLoading) return;
            state.isLoading = true;
            setLoadingScreen(true);
            els.loginBtn.innerText = 'WORKING...';
            els.errorMsg.style.display = 'none';
            const payload = readLoginPayload();
            try {
                const data = await apiJson('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (data.needs_2fa) {
                    showTwoFactorPrompt();
                } else if (data.success) {
                    localStorage.setItem('saved_username', payload.username);
                    localStorage.setItem('saved_password', payload.password);
                    await renderDashboard(data, { animateIntro: true, waitForIntro: true });
                    state.isLoading = false;
                } else {
                    showLoginError(data.detail || 'FAIL', { showAuthRefresh: Boolean(data.needs_auth_refresh) });
                }
            } catch (e) {
                showLoginError('NETWORK ERROR');
            }
        });

        async function refreshAuthFromUi() {
            if (state.isLoading) return;
            state.isLoading = true;
            const sink = authRefreshStatusSink();
            const buttons = [els.authRefreshBtn, els.topAuthRefreshBtn].filter(Boolean);
            const originalLabels = buttons.map(btn => btn.innerText);
            buttons.forEach(btn => { btn.disabled = true; });
            const payload = readAuthRefreshPayload();
            const hasCreds = Boolean(String(payload.username || '').trim() && String(payload.password || '').trim());
            buttons.forEach(btn => {
                btn.innerText = hasCreds ? 'REFRESHING AUTH...' : 'WAITING FOR GAME...';
            });
            sink.set(
                hasCreds
                    ? 'REFRESHING REUSABLE AUTH FROM YOUR STEAM CREDENTIALS. THIS SHOULD NOT REQUIRE OPENING THE GAME CLIENT.'
                    : 'WAITING FOR IN-GAME CAPTURE (UP TO ~3 MIN). MAKE SURE STEAM IS SIGNED INTO THE TARGET ACCOUNT.'
            );
            try {
                const data = await apiJson('/api/auth/refresh', hasCreds ? {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                } : { method: 'POST' });
                if (data.success) {
                    sink.set(data.mode === 'headless'
                        ? 'AUTH REFRESHED. CLICK LOGIN.'
                        : 'AUTH CAPTURED. CLICK LOGIN.');
                    if (els.authRefreshBtn) els.authRefreshBtn.style.display = 'none';
                } else {
                    sink.set(String(data.detail || 'AUTH REFRESH FAILED').toUpperCase(), true);
                }
            } catch (e) {
                sink.set('AUTH REFRESH NETWORK ERROR', true);
            } finally {
                buttons.forEach((btn, idx) => {
                    btn.disabled = false;
                    btn.innerText = originalLabels[idx] || 'REFRESH AUTH';
                });
                state.isLoading = false;
            }
        }

        els.authRefreshBtn?.addEventListener('click', refreshAuthFromUi);
        els.topAuthRefreshBtn?.addEventListener('click', refreshAuthFromUi);

        els.logoutBtn.addEventListener('click', async () => {
            setLoadingScreen(false);
            try {
                await apiJson('/api/logout', { method: 'POST' });
            } catch (e) {}
            document.body.classList.remove('dashboard-mode');
            hideNavbar();
            state.runnerRunning = false;
            state.loopActive = false;
            state.isStoppingRunner = false;
            if (state.runnerTimer) {
                window.clearInterval(state.runnerTimer);
                state.runnerTimer = 0;
            }
            stopAccountSyncPolling();
            els.loginView.style.display = 'flex';
            els.dashboardView.style.display = 'none';
            els.dashboardView.classList.remove('active');
            if (els.teamTrialsScreen) els.teamTrialsScreen.hidden = true;
            els.logoutBtn.style.display = 'none';
            if (els.teamBundleMenu) els.teamBundleMenu.style.display = 'none';
            setTeamBundleMenuOpen(false);
            if (els.topAuthRefreshBtn) els.topAuthRefreshBtn.style.display = 'none';
            if (els.careerNotifyToggleBtn) els.careerNotifyToggleBtn.style.display = 'none';
            if (els.teamTrialsScreenBtn) els.teamTrialsScreenBtn.style.display = 'none';
            if (els.syncDashboardBtn) els.syncDashboardBtn.style.display = 'none';
            if (els.refreshBackendBtn) els.refreshBackendBtn.style.display = 'none';
            els.standardFields.style.display = 'block';
            els.faFields.style.display = 'none';
            els.loginBtn.innerText = 'LOGIN';
            els.accountStrip.style.display = 'none';
            els.accountStrip.innerHTML = '';
            state.account = null;
            state.isEndingCareer = false;
            state.needs2fa = false;
            state.isRefreshingBackend = false;
            dashData = null;
            resetSelection();
            resetSessionParentStore();
            syncDashboardHeight();
            loginForm.reset();
        });

        async function syncDashboardData() {
            if (state.isSyncingDashboard || state.runnerRunning || state.loopActive) return;
            state.isSyncingDashboard = true;
            const originalText = els.syncDashboardBtn ? els.syncDashboardBtn.innerText : '';
            if (els.syncDashboardBtn) {
                els.syncDashboardBtn.disabled = true;
                els.syncDashboardBtn.innerText = 'SYNCING...';
            }
            if (els.startStatus) {
                setStartStatusMessage('Syncing game data...');
            }
            try {
                const data = await apiJson('/api/dashboard/refresh', { method: 'POST' });
                if (!data.success) throw new Error(data.detail || 'Sync failed');
                await renderDashboard(data, { animateIntro: false, waitForIntro: false });
                if (els.startStatus) {
                    setStartStatusMessage('Game data synced.');
                }
            } catch (e) {
                if (els.startStatus) {
                    setStartStatusMessage(e.message || 'Sync failed', true);
                }
            } finally {
                state.isSyncingDashboard = false;
                if (els.syncDashboardBtn) {
                    els.syncDashboardBtn.disabled = false;
                    els.syncDashboardBtn.innerText = originalText || 'SYNC GAME DATA';
                }
                syncStartButton();
            }
        }
        els.syncDashboardBtn?.addEventListener('click', syncDashboardData);

        async function refreshBackend() {
            if (state.isRefreshingBackend || state.runnerRunning || state.loopActive || state.isStartingCareer || state.isVerifyingStart) return;
            state.isRefreshingBackend = true;
            syncStartButton();
            setStartStatusMessage('Refreshing backend and preserving session...');
            try {
                const data = await apiJson('/api/dev/reload', { method: 'POST' });
                if (!data || !data.success) throw new Error((data && data.detail) || 'Backend refresh failed');
                setStartStatusMessage(data.detail || 'Backend refresh queued. Page will reconnect automatically.');
                window.setTimeout(() => {
                    if (!state.isRefreshingBackend) return;
                    setStartStatusMessage('Waiting for backend restart...');
                }, 1200);
                window.setTimeout(() => {
                    if (!state.isRefreshingBackend) return;
                    state.isRefreshingBackend = false;
                    syncStartButton();
                    setStartStatusMessage('Backend refresh timed out. Check the terminal, then reload the page.', true);
                }, 15000);
            } catch (e) {
                state.isRefreshingBackend = false;
                syncStartButton();
                setStartStatusMessage(e.message || 'Backend refresh failed', true);
            }
        }
        els.refreshBackendBtn?.addEventListener('click', refreshBackend);

        const formatNumber = value => Number(value || 0).toLocaleString();
        function selectedComboParent2() {
            if (selection.guestParent && selection.guestParent.viewer_id && selection.guestParent.trained_chara_id) {
                return normalizeBorrowUmaSelection(selection.guestParent);
            }
            return selection.veterans[1] || null;
        }
        function comboAffinityDetail() {
            const trainee = selection.trainee || null;
            const parent1 = selection.veterans[0] || null;
            const parent2 = selectedComboParent2();
            if (!trainee || !parent1) return null;

            // Single-parent mode: trainee + one parent. Show the side-1
            // affinity so the user can see compatibility even before
            // picking a second parent.
            if (!parent2) {
                let single = null;
                try { single = computeSingleParentAffinityGame(trainee, parent1); } catch (e) {}
                if (single && Number.isFinite(Number(single.total))) {
                    return {
                        total: Math.round(Number(single.total)),
                        side1: Math.round(Number(single.total)),
                        side2: null,
                        exact: true,
                        singleParent: true
                    };
                }
                let fallback = null;
                try { fallback = computeTraineeParentAffinity(trainee, parent1); } catch (e) {}
                if (Number.isFinite(Number(fallback))) {
                    return {
                        total: Math.round(Number(fallback)),
                        side1: Math.round(Number(fallback)),
                        side2: null,
                        exact: false,
                        singleParent: true
                    };
                }
                return null;
            }

            let exact = null;
            let side1 = null;
            let side2 = null;
            try {
                exact = computeProjectedAffinityGame(trainee, parent1, parent2);
                side1 = computeSingleParentAffinityGame(trainee, parent1);
                side2 = computeSingleParentAffinityGame(trainee, parent2);
            } catch (e) {}
            if (exact && Number.isFinite(Number(exact.total))) {
                return {
                    total: Math.round(Number(exact.total)),
                    side1: side1 && Number.isFinite(Number(side1.total)) ? Math.round(Number(side1.total)) : null,
                    side2: side2 && Number.isFinite(Number(side2.total)) ? Math.round(Number(side2.total)) : null,
                    exact: true
                };
            }

            try {
                const total = computeTriangleAffinity(trainee, parent1, parent2);
                const fallbackSide1 = computeTraineeParentAffinity(trainee, parent1);
                const fallbackSide2 = computeTraineeParentAffinity(trainee, parent2);
                if (Number.isFinite(Number(total))) {
                    return {
                        total: Math.round(Number(total)),
                        side1: Number.isFinite(Number(fallbackSide1)) ? Math.round(Number(fallbackSide1)) : null,
                        side2: Number.isFinite(Number(fallbackSide2)) ? Math.round(Number(fallbackSide2)) : null,
                        exact: false
                    };
                }
            } catch (e) {}
            return null;
        }
        function goldBaseProcRateForFactor(factor) {
            const stars = Math.max(0, Math.min(3, Number(factor && factor.stars) || 0));
            if (stars < 2) return 0;
            const category = normalizeSparkCategory(factor && factor.category, factor);
            if (category === 'stat') return stars >= 3 ? 0.90 : 0.80;
            if (category === 'aptitude') return stars >= 3 ? 0.05 : 0.03;
            if (category === 'unique') return stars >= 3 ? 0.15 : 0.10;
            if (category === 'race') return stars >= 3 ? 0.03 : 0.02;
            if (category === 'scenario' || category === 'skill') return stars >= 3 ? 0.09 : 0.06;
            return stars >= 3 ? 0.05 : 0.03;
        }
        function parentGoldInspirationOdds(parent, sideAffinity) {
            const tree = (parent && parent.tree) || {};
            const multiplier = 1 + Math.max(0, Number(sideAffinity) || 0) / 100;
            let miss = 1;
            let eligible = 0;
            ['self', 'p1', 'p2'].forEach(nodeId => {
                const node = tree[nodeId];
                if (!node || !Array.isArray(node.factors)) return;
                node.factors.forEach(factor => {
                    const base = goldBaseProcRateForFactor(factor);
                    if (base <= 0) return;
                    eligible += 1;
                    miss *= (1 - Math.min(0.98, base * multiplier));
                });
            });
            return { probability: eligible ? 1 - miss : null, eligible };
        }
        function comboGoldInspirationOdds(detail) {
            const parent1 = selection.veterans[0] || null;
            const parent2 = selectedComboParent2();
            if (!detail || !parent1 || !parent2) return { probability: null, eligible: 0 };
            const sideFallback = Math.round((Number(detail.total) || 0) / 2);
            const left = parentGoldInspirationOdds(parent1, detail.side1 != null ? detail.side1 : sideFallback);
            const right = parentGoldInspirationOdds(parent2, detail.side2 != null ? detail.side2 : sideFallback);
            const eligible = left.eligible + right.eligible;
            if (!eligible || left.probability == null && right.probability == null) return { probability: null, eligible };
            const leftMiss = left.probability == null ? 1 : 1 - left.probability;
            const rightMiss = right.probability == null ? 1 : 1 - right.probability;
            return { probability: 1 - (leftMiss * rightMiss), eligible };
        }
        function formatProbability(value) {
            if (value == null || !Number.isFinite(Number(value))) return '—';
            const pct = Math.max(0, Math.min(100, Number(value) * 100));
            return `${pct.toFixed(pct >= 99 ? 1 : pct >= 10 ? 0 : 1)}%`;
        }
        const LEGACY_START_STAT_KEYS = ['speed', 'stamina', 'power', 'guts', 'wit'];
        const LEGACY_START_STAT_SHORT = {
            speed: 'SPD',
            stamina: 'STA',
            power: 'PWR',
            guts: 'GUT',
            wit: 'WIT'
        };
        const LEGACY_START_STAT_NAME_TO_KEY = {
            speed: 'speed',
            stamina: 'stamina',
            power: 'power',
            guts: 'guts',
            wit: 'wit'
        };
        const LEGACY_START_APTITUDE_SPECS = [
            { name: 'Turf', key: 'turf', label: 'Turf' },
            { name: 'Dirt', key: 'dirt', label: 'Dirt' },
            { name: 'Short', key: 'sprint', label: 'Sprint' },
            { name: 'Mile', key: 'mile', label: 'Mile' },
            { name: 'Medium', key: 'medium', label: 'Medium' },
            { name: 'Long', key: 'long', label: 'Long' },
            { name: 'Front Runner', key: 'front', label: 'Front' },
            { name: 'Pace Chaser', key: 'pace', label: 'Pace' },
            { name: 'Late Surger', key: 'late', label: 'Late' },
            { name: 'End Closer', key: 'end', label: 'End' }
        ];
        const LEGACY_ADVANCED_APTITUDE_GROUPS = [
            { label: 'Track', keys: ['turf', 'dirt'] },
            { label: 'Distance', keys: ['sprint', 'mile', 'medium', 'long'] },
            { label: 'Style', keys: ['front', 'pace', 'late', 'end'] }
        ];
        const LEGACY_START_BLUE_STAR_BONUS = { 1: 5, 2: 12, 3: 21 };
        function createLegacyStartStatTotals() {
            return { speed: 0, stamina: 0, power: 0, guts: 0, wit: 0 };
        }
        function legacyBlueStatValue(stars) {
            const normalized = Math.max(0, Math.min(3, Number(stars) || 0));
            return LEGACY_START_BLUE_STAR_BONUS[normalized] || 0;
        }
        function parentLegacyStatBonuses(parent, nodes = ['self', 'p1', 'p2']) {
            const totals = createLegacyStartStatTotals();
            collectFactorEntries(parent, nodes).forEach(entry => {
                if (entry.group !== 'stat') return;
                const key = LEGACY_START_STAT_NAME_TO_KEY[String(entry.name || '').trim().toLowerCase()];
                if (!key) return;
                totals[key] += legacyBlueStatValue(entry.stars);
            });
            return totals;
        }
        function combineLegacyStatBonuses(parents, nodes = ['self', 'p1', 'p2']) {
            const totals = createLegacyStartStatTotals();
            (Array.isArray(parents) ? parents : []).filter(Boolean).forEach(parent => {
                const add = parentLegacyStatBonuses(parent, nodes);
                LEGACY_START_STAT_KEYS.forEach(key => {
                    totals[key] += Number(add[key] || 0);
                });
            });
            return totals;
        }
        function pinkAptitudeDelta(totalStars) {
            const stars = Math.max(0, Number(totalStars) || 0);
            if (stars < 1) return 0;
            return Math.min(4, Math.floor((stars - 1) / 3) + 1);
        }
        function combinedLegacyAptitudePreview(trainee, parents, nodes = ['self', 'p1', 'p2']) {
            const traineeApt = charaAptitudeFor(trainee && (trainee.card_id || trainee.id));
            const baseAptitudes = (traineeApt && traineeApt.aptitudes) || {};
            if (!traineeApt || !baseAptitudes) return [];
            const totals = {};
            LEGACY_START_APTITUDE_SPECS.forEach(spec => { totals[spec.key] = 0; });
            (Array.isArray(parents) ? parents : []).filter(Boolean).forEach(parent => {
                collectFactorEntries(parent, nodes).forEach(entry => {
                    if (entry.group !== 'aptitude') return;
                    const spec = LEGACY_START_APTITUDE_SPECS.find(row => row.name.toLowerCase() === String(entry.name || '').trim().toLowerCase());
                    if (!spec) return;
                    totals[spec.key] += Math.max(0, Number(entry.stars) || 0);
                });
            });
            return LEGACY_START_APTITUDE_SPECS.map(spec => {
                const baseRank = String(baseAptitudes[spec.key] || '').toUpperCase();
                if (!(baseRank in aptRank)) return null;
                const rawDelta = pinkAptitudeDelta(totals[spec.key]);
                if (!rawDelta) return null;
                const nextValue = Math.min(aptRank.A, aptRank[baseRank] + rawDelta);
                const appliedDelta = Math.max(0, nextValue - aptRank[baseRank]);
                if (!appliedDelta) return null;
                return {
                    key: spec.key,
                    label: spec.label,
                    base: baseRank,
                    next: aptLetterByVal[nextValue],
                    stars: totals[spec.key],
                    delta: appliedDelta
                };
            }).filter(Boolean);
        }
        function formatLegacyStatBonusText(totals) {
            return LEGACY_START_STAT_KEYS
                .map(key => Number(totals && totals[key] || 0) > 0 ? `+${Number(totals[key] || 0)} ${LEGACY_START_STAT_SHORT[key]}` : '')
                .filter(Boolean)
                .join(' · ');
        }
        function formatLegacyAptitudeBonusText(rows) {
            return (Array.isArray(rows) ? rows : [])
                .map(row => `${row.label} +${row.delta}`)
                .join(' · ');
        }
        function renderLegacyStartStatStrip(totals, options = {}) {
            const includeZero = options.includeZero !== false;
            const entries = LEGACY_START_STAT_KEYS
                .map(key => ({
                    key,
                    label: LEGACY_START_STAT_SHORT[key],
                    value: Number(totals && totals[key] || 0)
                }))
                .filter(entry => includeZero || entry.value > 0);
            if (!entries.length) return '';
            return `<div class="legacy-start-stat-strip">${entries.map(entry => `
                <span class="legacy-start-stat-chip ${entry.value > 0 ? 'is-boosted' : 'is-zero'} stat-${entry.key}">
                    <em>${entry.label}</em>
                    <strong>+${entry.value}</strong>
                </span>
            `).join('')}</div>`;
        }
        function renderLegacyAptitudeUpgradeStrip(rows, options = {}) {
            const includeHeading = options.includeHeading !== false;
            const list = Array.isArray(rows) ? rows : [];
            if (!list.length) return '';
            return `<div class="legacy-start-apt-strip">
                ${includeHeading ? '<span class="legacy-start-apt-title">Aptitude</span>' : ''}
                <div class="legacy-start-apt-list">${list.map(row => `
                    <span class="legacy-start-apt-chip">
                        <em>${escapeHtml(row.label)}</em>
                        <strong>${escapeHtml(row.base)}&rarr;${escapeHtml(row.next)}</strong>
                    </span>
                `).join('')}</div>
            </div>`;
        }
        function renderLegacyStartPreviewPanel(preview, options = {}) {
            if (!preview) return '';
            const statStrip = renderLegacyStartStatStrip(preview.statBonuses, { includeZero: options.includeZeroStats !== false });
            const aptitudeStrip = renderLegacyAptitudeUpgradeStrip(preview.aptitudeBonuses, { includeHeading: options.includeAptitudeHeading !== false });
            if (!statStrip && !aptitudeStrip) return '';
            const heading = options.heading ? `<span class="legacy-start-preview-title">${escapeHtml(options.heading)}</span>` : '';
            return `<div class="legacy-start-preview-panel ${options.compact ? 'is-compact' : ''}">
                ${heading}
                ${statStrip}
                ${aptitudeStrip}
            </div>`;
        }
        function legacyStartPreview(trainee, parents, nodes = ['self', 'p1', 'p2']) {
            const list = (Array.isArray(parents) ? parents : []).filter(Boolean);
            if (!trainee || !list.length) return null;
            const statBonuses = combineLegacyStatBonuses(list, nodes);
            const aptitudeBonuses = combinedLegacyAptitudePreview(trainee, list, nodes);
            const statText = formatLegacyStatBonusText(statBonuses);
            const aptitudeText = formatLegacyAptitudeBonusText(aptitudeBonuses);
            if (!statText && !aptitudeText) return null;
            return { statBonuses, aptitudeBonuses, statText, aptitudeText };
        }
        function renderLegacyGrowthBonusStrip(trainee) {
            const apt = charaAptitudeFor(trainee && (trainee.card_id || trainee.id)) || {};
            const growths = Array.isArray(apt.growths) ? apt.growths : [];
            if (!growths.length) return '';
            return `<div class="legacy-growth-strip">${growths.map(row => `
                <span class="legacy-growth-chip growth-${escapeAttr(String((row.stat || '').toLowerCase()))}">
                    <em>${escapeHtml(row.stat || '')}</em>
                    <strong>+${row.pct != null ? escapeHtml(String(row.pct)) : '?'}%</strong>
                </span>
            `).join('')}</div>`;
        }
        function renderLegacyCompactGainGrid(totals) {
            return `<div class="legacy-gain-grid">${LEGACY_START_STAT_KEYS.map(key => {
                const value = Number(totals && totals[key] || 0);
                return `<div class="legacy-gain-cell stat-${key} ${value > 0 ? 'is-boosted' : 'is-zero'}">
                    <span class="legacy-gain-label">${escapeHtml(LEGACY_START_STAT_SHORT[key])}</span>
                    <span class="legacy-gain-value">+${value}</span>
                </div>`;
            }).join('')}</div>`;
        }
        function buildLegacyAptitudeRows(trainee, aptitudeBonuses) {
            const apt = charaAptitudeFor(trainee && (trainee.card_id || trainee.id)) || {};
            const baseAptitudes = (apt && apt.aptitudes) || {};
            const bonusMap = {};
            (Array.isArray(aptitudeBonuses) ? aptitudeBonuses : []).forEach(row => {
                if (row && row.key) bonusMap[row.key] = row;
            });
            return LEGACY_ADVANCED_APTITUDE_GROUPS.map(group => ({
                label: group.label,
                rows: group.keys.map(key => {
                    const spec = LEGACY_START_APTITUDE_SPECS.find(item => item.key === key);
                    const base = String(baseAptitudes[key] || '').toUpperCase() || '?';
                    const bonus = bonusMap[key] || null;
                    return {
                        key,
                        label: spec ? spec.label : key,
                        base,
                        next: bonus ? bonus.next : base,
                        changed: !!(bonus && bonus.next && bonus.next !== base),
                        delta: bonus ? bonus.delta : 0,
                    };
                })
            }));
        }
        function renderLegacyAptitudeTable(trainee, aptitudeBonuses) {
            const groups = buildLegacyAptitudeRows(trainee, aptitudeBonuses);
            return `<div class="legacy-aptitude-table">${groups.map(group => `
                <div class="legacy-aptitude-row">
                    <span class="legacy-aptitude-row-label">${escapeHtml(group.label)}</span>
                    <div class="legacy-aptitude-row-cells">${group.rows.map(row => `
                        <div class="legacy-aptitude-cell ${row.changed ? 'is-boosted' : ''}">
                            <span class="legacy-aptitude-cell-name">${escapeHtml(row.label)}</span>
                            <span class="legacy-aptitude-cell-rank">${escapeHtml(row.base)}${row.changed ? ` <strong>&rarr; ${escapeHtml(row.next)}</strong>` : ''}</span>
                        </div>
                    `).join('')}</div>
                </div>
            `).join('')}</div>`;
        }
        function renderLegacyParentContributionList(trainee, parents) {
            const labels = ['Parent 1', 'Parent 2'];
            const items = (Array.isArray(parents) ? parents : []).filter(Boolean).map((parent, index) => {
                const preview = legacyStartPreview(trainee, [parent]);
                const imgId = parent.card_id || '100101';
                const rank = rankLabel(parent);
                return `
                    <div class="legacy-parent-row">
                        <div class="legacy-parent-head">
                            <img class="legacy-parent-portrait" src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                            <div class="legacy-parent-meta">
                                <span class="legacy-parent-role">${labels[index] || `Parent ${index + 1}`}</span>
                                <span class="legacy-parent-name">${escapeHtml(parent.name || 'Unknown')}</span>
                                <span class="legacy-parent-rank">${escapeHtml(rank)}${parent.score != null ? ` · ${formatNumber(parent.score)}` : ''}</span>
                            </div>
                        </div>
                        ${preview ? `
                            ${renderLegacyStartStatStrip(preview.statBonuses, { includeZero: false })}
                            ${renderLegacyAptitudeUpgradeStrip(preview.aptitudeBonuses, { includeHeading: false })}
                        ` : '<div class="legacy-parent-empty">No inheritable start bonus detected.</div>'}
                    </div>`;
            });
            if (!items.length) return '';
            return `<div class="legacy-parent-list">${items.join('')}</div>`;
        }
        function renderLegacySetupDetailsPanel(trainee, parents) {
            const preview = legacyStartPreview(trainee, parents);
            if (!trainee || !preview) return '';
            const imgId = trainee.id || trainee.card_id || '100101';
            return `<div class="legacy-dashboard-panel legacy-dashboard-panel-setup">
                <div class="legacy-dashboard-header">
                    <div class="legacy-dashboard-identity">
                        <div class="legacy-dashboard-portrait"><img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)"></div>
                        <div class="legacy-dashboard-meta">
                            <span class="legacy-dashboard-name">${escapeHtml(trainee.name || 'Unknown')}</span>
                            <span class="legacy-dashboard-sub">Legacy start gains from selected parents</span>
                        </div>
                    </div>
                    <span class="legacy-dashboard-tag">LEGACY</span>
                </div>
                ${renderLegacyCompactGainGrid(preview.statBonuses)}
                <div class="legacy-dashboard-advanced-body">
                    ${renderLegacyGrowthBonusStrip(trainee)}
                    ${renderLegacyAptitudeTable(trainee, preview.aptitudeBonuses)}
                    ${renderLegacyParentContributionList(trainee, parents)}
                </div>
            </div>`;
        }
        function renderSetupLegacyDetails() {
            if (!els.setupLegacySection || !els.setupLegacyDetailsBody || !els.setupLegacySummary) return;
            const trainee = selection.trainee || null;
            const parent1 = selection.veterans[0] || null;
            const parent2 = selectedComboParent2();
            const parents = [parent1, parent2].filter(Boolean);
            const preview = legacyStartPreview(trainee, parents);
            if (!trainee || !parents.length || !preview) {
                els.setupLegacySection.hidden = true;
                els.setupLegacySummary.textContent = '';
                els.setupLegacyDetailsBody.innerHTML = '';
                return;
            }
            const summaryBits = [];
            if (preview.statText) summaryBits.push(preview.statText);
            if (preview.aptitudeText) summaryBits.push(preview.aptitudeText);
            els.setupLegacySection.hidden = false;
            els.setupLegacySummary.textContent = summaryBits.join(' • ');
            els.setupLegacyDetailsBody.innerHTML = renderLegacySetupDetailsPanel(trainee, parents);
        }
        function renderComboAffinitySummary() {
            if (!els.teamComboAffinity) return;
            const trainee = selection.trainee || null;
            const parent1 = selection.veterans[0] || null;
            const parent2 = selectedComboParent2();
            // Show the panel as long as the trainee and at least one parent
            // are picked. With only one parent we render the single-parent
            // affinity so the user can read the score before completing the
            // combo.
            if (!trainee || !parent1) {
                els.teamComboAffinity.hidden = true;
                els.teamComboAffinity.innerHTML = '';
                return;
            }
            const detail = comboAffinityDetail();
            if (!detail) {
                els.teamComboAffinity.hidden = false;
                els.teamComboAffinity.innerHTML = `
                    <div class="combo-affinity-main combo-affinity-loading">
                        <span class="combo-affinity-score">...</span>
                        <span class="combo-affinity-label">${parent2 ? 'Total affinity' : 'Parent 1 affinity'}</span>
                        <span class="combo-affinity-source">Loading compatibility reference</span>
                    </div>
                    <div class="combo-affinity-kpis">
                        <span class="combo-affinity-kpi"><strong>...</strong><em>Gold inspiration odds</em></span>
                    </div>
                `;
                return;
            }
            const symbol = affinitySymbol(detail.total);
            const isSingle = !!detail.singleParent;
            const gold = isSingle
                ? parentGoldInspirationOdds(parent1, detail.total)
                : comboGoldInspirationOdds(detail);
            const source = isSingle
                ? (detail.exact ? 'single-parent compatibility' : 'single-parent base estimate')
                : (detail.exact ? 'full race/base compatibility' : 'base estimate');
            const label = isSingle ? 'Parent 1 affinity' : 'Total affinity';
            const sideText = isSingle
                ? ''
                : [
                    detail.side1 != null ? `P1 ${detail.side1}` : '',
                    detail.side2 != null ? `P2 ${detail.side2}` : ''
                ].filter(Boolean).join(' / ');
            const legacyPreview = legacyStartPreview(trainee, [parent1, parent2]);
            els.teamComboAffinity.hidden = false;
            els.teamComboAffinity.innerHTML = `
                <div class="combo-affinity-main">
                    <span class="aff-icon ${symbol.cls}">${symbol.symbol}</span>
                    <span class="combo-affinity-score">${detail.total}</span>
                    <span class="combo-affinity-label">${label}</span>
                    <span class="combo-affinity-source">${escapeHtml(source)}</span>
                </div>
                <div class="combo-affinity-kpis">
                    <span class="combo-affinity-kpi" title="Estimated chance that at least one selected parent-side 2★/3★ spark procs. The gold event is an indicator, not a separate extra roll.">
                        <strong>${formatProbability(gold.probability)}</strong>
                        <em>Gold inspiration odds</em>
                    </span>
                    <span class="combo-affinity-kpi">
                        <strong>${gold.eligible || 0}</strong>
                        <em>2★/3★ eligible sparks</em>
                    </span>
                    ${sideText ? `<span class="combo-affinity-kpi combo-affinity-side"><strong>${escapeHtml(sideText)}</strong><em>Side affinity</em></span>` : ''}
                    ${legacyPreview && legacyPreview.statText ? `<span class="combo-affinity-kpi combo-affinity-legacy"><strong>${escapeHtml(legacyPreview.statText)}</strong><em>Start gains</em></span>` : ''}
                    ${legacyPreview && legacyPreview.aptitudeText ? `<span class="combo-affinity-kpi combo-affinity-legacy"><strong>${escapeHtml(legacyPreview.aptitudeText)}</strong><em>Aptitude upgrades</em></span>` : ''}
                </div>
            `;
        }
        function closeCareerModal() {
            els.careerModal.style.display = 'none';
            els.careerModalCopy.innerText = 'This will force-delete the ongoing career.';
            els.careerDeleteBtn.innerText = 'DELETE';
            state.isDeletingCareer = false;
        }
        function openCareerModal() {
            const career = state.account && state.account.career;
            if (!career || !career.active) return;
            els.careerModalCopy.innerText = 'This will force-delete the ongoing career.';
            els.careerModal.style.display = 'flex';
        }
        async function deleteCareer() {
            const career = state.account && state.account.career;
            if (!career || !career.active || state.isDeletingCareer) return;
            state.isDeletingCareer = true;
            els.careerDeleteBtn.innerText = 'DELETING';
            els.careerModalCopy.innerText = 'Deleting ongoing career...';
            try {
                const data = await apiJson('/api/career/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ current_turn: career.turn || 0 })
                });
                if (!data.success) throw new Error(data.detail || 'Delete failed');
                renderAccountStrip(data.account);
                closeCareerModal();
            } catch (e) {
                els.careerModalCopy.innerText = e.message || 'Delete failed';
                els.careerDeleteBtn.innerText = 'RETRY';
                state.isDeletingCareer = false;
            }
        }
        els.careerCancelBtn.addEventListener('click', closeCareerModal);
        els.careerDeleteBtn.addEventListener('click', deleteCareer);
        els.careerModal.addEventListener('click', event => {
            if (event.target === els.careerModal) closeCareerModal();
        });
        const CAREER_STAT_FIELDS = [
            { key: 'speed', label: 'Speed', cls: 'stat-speed', max: 1200 },
            { key: 'stamina', label: 'Stamina', cls: 'stat-stamina', max: 1200 },
            { key: 'power', label: 'Power', cls: 'stat-power', max: 1200 },
            { key: 'guts', label: 'Guts', cls: 'stat-guts', max: 1200 },
            { key: 'wit', label: 'Wit', cls: 'stat-wit', max: 1200 },
            { key: 'skill_point', label: 'Skill Pt', cls: 'stat-skill-point', max: 0 }
        ];
        const MOTIVATION_LABELS = {
            1: 'Awful',
            2: 'Bad',
            3: 'Normal',
            4: 'Good',
            5: 'Great'
        };
        function setStartStatusMessage(message, isError = false) {
            if (!els.startStatus) return;
            els.startStatus.classList.remove('has-history');
            els.startStatus.classList.toggle('error', Boolean(isError));
            els.startStatus.textContent = message || '';
        }
        function motivationLabel(value) {
            const numeric = Number(value || 0);
            return MOTIVATION_LABELS[numeric] || (numeric > 0 ? String(numeric) : '--');
        }
        function hasPlausibleCareerStats(stats) {
            if (!stats || typeof stats !== 'object') return false;
            return [
                'hp', 'motivation', 'speed', 'stamina', 'power', 'guts', 'wit', 'skill_point'
            ].some(key => Number(stats[key] || 0) > 0);
        }
        function latestRunnerHistoryStats(runner) {
            if (!runner) return null;
            const rows = Array.isArray(runner.action_history) && runner.action_history.length
                ? runner.action_history
                : deriveActionHistory(runner.log || []);
            for (let i = rows.length - 1; i >= 0; i -= 1) {
                const stats = rows[i] && rows[i].stats;
                if (hasPlausibleCareerStats(stats)) return stats;
            }
            return null;
        }
        function careerStatsSource(account = state.account, runner = state.runnerSnapshot) {
            const career = account && account.career ? account.career : null;
            const rawRunnerStats = runner && runner.current_stats && Object.keys(runner.current_stats).length ? runner.current_stats : null;
            const runnerStats = hasPlausibleCareerStats(rawRunnerStats) ? rawRunnerStats : latestRunnerHistoryStats(runner);
            const useRunnerStats = Boolean(runnerStats && runner && runner.running);
            if (!useRunnerStats && !(career && career.active)) return null;
            const stats = useRunnerStats ? runnerStats : {
                hp: Number(career && career.vital || 0),
                max_hp: Number(career && career.max_vital || 100),
                motivation: Number(career && career.motivation || 0),
                speed: Number(career && career.speed || 0),
                stamina: Number(career && career.stamina || 0),
                power: Number(career && career.power || 0),
                guts: Number(career && career.guts || 0),
                wit: Number(career && career.wit || 0),
                skill_point: Number(career && career.skill_point || 0)
            };
            const cardId = String((useRunnerStats && runner && runner.current_card_id) || (career && career.card_id) || (selection.trainee && selection.trainee.id) || '');
            const name = (career && career.name) || (selection.trainee && selection.trainee.name) || 'Current trainee';
            const turn = Number((runner && runner.turn) || (career && career.turn) || 0);
            const subParts = [];
            if (turn > 0) subParts.push(`Turn ${turn}`);
            if (runner && runner.running && runner.last_action) subParts.push(String(runner.last_action));
            else if (career && career.fans != null) subParts.push(`${formatNumber(career.fans || 0)} fans`);
            return { cardId, name, turn, stats, sub: subParts.join(' · ') };
        }
        function renderCareerStatBar(account = state.account, runner = state.runnerSnapshot) {
            if (!els.careerStatsPanel) return;
            const source = careerStatsSource(account, runner);
            if (!source) {
                els.careerStatsPanel.hidden = true;
                if (els.careerStatsGrid) els.careerStatsGrid.innerHTML = '';
                return;
            }
            const stats = source.stats || {};
            els.careerStatsPanel.hidden = false;
            if (els.careerStatsPortrait) {
                els.careerStatsPortrait.innerHTML = source.cardId
                    ? `<img src="/api/images/${escapeAttr(source.cardId)}.png" onerror="hideBrokenImage(this)">`
                    : '';
            }
            if (els.careerStatsName) els.careerStatsName.textContent = source.name || 'Current trainee';
            if (els.careerStatsSub) els.careerStatsSub.textContent = source.sub || 'Stats update live while the career runs.';
            if (els.careerStatsHp) els.careerStatsHp.textContent = `HP ${stats.hp ?? 0}/${stats.max_hp ?? 100}`;
            if (els.careerStatsMood) els.careerStatsMood.textContent = `Mood ${motivationLabel(stats.motivation)}`;
            if (els.careerStatsSp) els.careerStatsSp.textContent = `SP ${formatNumber(stats.skill_point || 0)}`;
            if (els.careerStatsClocks) {
                const clocks = Number((runner && runner.alarm_clocks_used) || 0);
                const carats = Number((runner && runner.carat_race_retries) || 0);
                if (clocks > 0 || carats > 0) {
                    els.careerStatsClocks.hidden = false;
                    els.careerStatsClocks.textContent = carats > 0
                        ? `⏰ ${clocks} · 🪙 ${carats}`
                        : `⏰ ${clocks}`;
                    els.careerStatsClocks.title = `Alarm clocks used: ${clocks}` + (carats > 0 ? ` · carat-bought retries: ${carats}` : '');
                } else {
                    els.careerStatsClocks.hidden = true;
                }
            }
            if (els.careerStatsGrid) {
                els.careerStatsGrid.innerHTML = CAREER_STAT_FIELDS.map(field => {
                    const value = Number(stats[field.key] || 0);
                    const suffix = field.max ? `<span>/${field.max}</span>` : '';
                    return `
                        <div class="career-stat-tile ${field.cls}">
                            <span class="career-stat-label">${field.label}</span>
                            <span class="career-stat-value">${formatNumber(value)}${suffix}</span>
                        </div>
                    `;
                }).join('');
            }
        }
        function deriveTpForDisplay(tp) {
            const raw = tp || {};
            const current = Number(raw.current || raw.current_tp || 0) || 0;
            const max = Number(raw.max || raw.max_tp || 0) || 0;
            const maxRecoveryTime = Number(raw.max_recovery_time || 0) || 0;
            const interval = Number(raw.recovery_seconds_per_point || 300) || 300;
            const now = Math.floor(Date.now() / 1000);
            let derived = current;
            let nextRecoveryTime = Number(raw.next_recovery_time || 0) || 0;
            let secondsToNext = Number(raw.seconds_to_next || 0) || 0;
            if (max > 0 && maxRecoveryTime > 0) {
                if (current >= max || maxRecoveryTime <= now) {
                    derived = max;
                    nextRecoveryTime = 0;
                    secondsToNext = 0;
                } else {
                    const missing = Math.ceil(Math.max(0, maxRecoveryTime - now) / interval);
                    derived = Math.max(current, Math.max(0, Math.min(max, max - missing)));
                    if (derived < max) {
                        const missingAfterCurrent = max - derived;
                        nextRecoveryTime = maxRecoveryTime - ((missingAfterCurrent - 1) * interval);
                        secondsToNext = Math.max(0, nextRecoveryTime - now);
                    }
                }
            }
            return {
                ...raw,
                current: Math.max(0, Math.min(derived, max || derived)),
                max,
                max_recovery_time: maxRecoveryTime,
                next_recovery_time: nextRecoveryTime,
                seconds_to_next: secondsToNext,
                recovery_seconds_per_point: interval
            };
        }
        function deriveAccountTpForDisplay(account) {
            if (!account) return account;
            account.tp = deriveTpForDisplay(account.tp || {});
            return account;
        }
        function renderAccountStrip(account) {
            account = deriveAccountTpForDisplay(account);
            state.account = account || null;
            if (!account) {
                if (!state.runnerRunning && !state.loopActive) state.runnerSnapshot = null;
                els.accountStrip.style.display = 'none';
                els.accountStrip.innerHTML = '';
                renderCareerStatBar(null, state.runnerSnapshot);
                return;
            }
            const tp = account.tp || {};
            const career = account.career;
            const careerHtml = career && career.active ? `
                <button type="button" id="career-pill" class="account-pill account-pill-career account-pill-clickable">ONGOING <strong>CAREER</strong></button>
            ` : `<span class="account-pill account-pill-career">NO CAREER</span>`;
            const carrots = account.carrots || {};
            const tpTitle = tp.seconds_to_next > 0 ? ` title="Next TP in ${tp.seconds_to_next}s"` : '';
            els.accountStrip.innerHTML = `
                <span class="account-pill"${tpTitle}>TP <strong>${tp.current || 0}/${tp.max || 0}</strong></span>
                <span class="account-pill">FREE CARROTS <strong>${formatNumber(carrots.free)}</strong></span>
                <span class="account-pill">PAID CARROTS <strong>${formatNumber(carrots.paid)}</strong></span>
                <span class="account-pill">TOUGHNESS 30 <strong>${formatNumber(account.toughness || 0)}</strong></span>
                <span class="account-pill">GOLD <strong>${formatNumber(account.gold)}</strong></span>
                ${careerHtml}
            `;
            els.accountStrip.style.display = 'flex';
            const careerPill = document.getElementById('career-pill');
            if (careerPill) careerPill.addEventListener('click', openCareerModal);
            renderCareerStatBar(account, state.runnerSnapshot);
        }
        const rankMap = {
            1: 'G', 2: 'G+', 3: 'F', 4: 'F+', 5: 'E', 6: 'E+',
            7: 'D', 8: 'D+', 9: 'C', 10: 'C+', 11: 'B', 12: 'B+',
            13: 'A', 14: 'A+', 15: 'S', 16: 'S+', 17: 'SS', 18: 'SS+',
            19: 'UG', 20: 'UF', 21: 'UE', 22: 'UD'
        };
        let dashData = null;
        const selection = { deck: null, friend: null, trainee: null, veterans: [], guestParent: null };

        async function syncSelectionToServer() {
            try {
                const payload = {
                    deck: selection.deck,
                    friend: selection.friend,
                    trainee: selection.trainee,
                    veterans: selection.veterans,
                    guestParent: selection.guestParent
                };
                await apiJson('/api/selection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ selection: payload })
                });
            } catch (e) {}
        }

        function deselect(action, idx) {
            let refreshFriends = false;
            if (action === 'deck') {
                document.querySelectorAll('.deck-container.selected').forEach(el => el.classList.remove('selected'));
                selection.deck = null;
                refreshFriends = true;
            } else if (action === 'friend') {
                document.querySelectorAll('#friend-grid .grid-card.selected').forEach(el => el.classList.remove('selected'));
                selection.friend = null;
                refreshFriends = true;
            } else if (action === 'trainee') {
                document.querySelectorAll('#uma-grid .grid-card.selected').forEach(el => el.classList.remove('selected'));
                selection.trainee = null;
                refreshFriends = true;
            } else if (action === 'vet') {
                selection.veterans.splice(idx, 1);
                renderParents((dashData && dashData.parents) || []);
                bindSparkTooltips();
                attachSelectionHandlers();
                updateVetSelectability();
            } else if (action === 'guest') {
                selection.guestParent = null;
                renderBorrowUmas((dashData && dashData.borrowUmas) || []);
                attachBorrowUmaHandlers();
                bindSparkTooltips();
            }
            if (refreshFriends) renderFriends();
            renderTeamPanel();
            syncSelectionToServer();
        }
        function getStartMissingReason() {
            const activeCareer = state.account && state.account.career && state.account.career.active;
            if (!state.selectedPreset) return 'Select a preset';
            if (activeCareer && !state.loopEnabled) return '';
            if (!selection.deck) return 'Select a deck';
            const selectedDeckCards = Array.isArray(selection.deck.cards) ? selection.deck.cards : [];
            if (selectedDeckCards.length !== 5) return `Deck needs 5 support cards (${selectedDeckCards.length}/5)`;
            const activeCareerFriend = activeCareer && activeCareer.friend_viewer_id && activeCareer.friend_card_id;
            if (!selection.friend && !activeCareerFriend) return 'Select a friend support';
            if (!selection.trainee) return 'Select a trainee';
            // Parent slot rules:
            //   With guest: at least 1 own veteran required; vet 2 is optional (used as
            //     fallback when borrows run out mid-loop).
            //   Without guest: 2 own veterans required.
            const hasGuest = selection.guestParent && selection.guestParent.viewer_id && selection.guestParent.trained_chara_id;
            const minVets = hasGuest ? 1 : 2;
            if (selection.veterans.length < minVets) {
                return hasGuest ? 'Select a Parent 1 veteran (the guest fills slot 2)' : 'Select two parents';
            }
            const parentError = getParentSelectionError();
            if (parentError) return parentError;
            const tp = state.account && state.account.tp ? Number(state.account.tp.current || 0) : 0;
            if (state.account && tp < 30 && !normalizeTpRecoveryMode()) return `Not enough TP: ${tp}/30`;
            return '';
        }
        function getParentLineageCards(parent) {
            if (!parent || !parent.tree) return [];
            return ['self', 'p1', 'p2', 'gp1', 'gp2', 'gp3', 'gp4']
                .map(key => Number(parent.tree[key] && parent.tree[key].card_id))
                .filter(Boolean);
        }
        function normalizeCharaName(value) {
            return String(value || '').toLowerCase().replace(/\([^)]*\)/g, '').replace(/[^a-z0-9]+/g, '');
        }
        function getParentSelectionError() {
            if (!selection.trainee) return '';
            const traineeId = Number(selection.trainee.id);
            const traineeName = normalizeCharaName(selection.trainee.name);
            // Trainee chara can't appear as any deck support card.
            if (traineeName && selection.deck) {
                for (const card of (selection.deck.cards || [])) {
                    if (normalizeCharaName(card.name) === traineeName) {
                        return 'Deck contains a support of the same character as the trainee';
                    }
                }
            }
            // Trainee chara can't be the borrowed guest either.
            if (traineeName && selection.guestParent) {
                if (normalizeCharaName(selection.guestParent.chara_name) === traineeName) {
                    return 'Guest is the same character as the trainee';
                }
            }
            const lineages = selection.veterans.map(getParentLineageCards);
            if (lineages.some(cards => cards[0] === traineeId)) return 'Direct parent is trainee';
            // Both parents must be different characters, AND each parent must be a different
            // character from the borrowed guest. Otherwise the game rejects the start.
            const vet1Chara = selection.veterans[0] ? normalizeCharaName(selection.veterans[0].name) : '';
            const vet2Chara = selection.veterans[1] ? normalizeCharaName(selection.veterans[1].name) : '';
            const guestChara = selection.guestParent ? normalizeCharaName(selection.guestParent.chara_name) : '';
            if (vet1Chara && vet2Chara && vet1Chara === vet2Chara) {
                return 'Both selected parents are the same character';
            }
            if (vet1Chara && guestChara && vet1Chara === guestChara) {
                return 'Parent 1 and guest are the same character';
            }
            if (vet2Chara && guestChara && vet2Chara === guestChara) {
                return 'Parent 2 (fallback) and guest are the same character';
            }
            return '';
        }
        function normalizeLoopMode(value = state.loopMode) {
            const mode = String(value || state.loopMode || 'forever').toLowerCase();
            return ['forever', 'careers', 'fans'].includes(mode) ? mode : 'forever';
        }
        function normalizePositiveInt(value, fallback, max) {
            const parsed = Number.parseInt(value, 10);
            if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
            return Math.max(1, Math.min(parsed, max));
        }
        function normalizeLoopCareerLimit(value = state.loopCareerLimit) {
            return normalizePositiveInt(value, 10, 999);
        }
        function normalizeLoopFanLimit(value = state.loopFanLimit) {
            return normalizePositiveInt(value, 100000000, 999999999);
        }
        function normalizeTpRecoveryMode(value = els.tpRecoverySelect && els.tpRecoverySelect.value) {
            const parsed = Number.parseInt(value, 10);
            return [0, 1, 2, 3].includes(parsed) ? parsed : 0;
        }
        function parseShowtimeSelection(value) {
            if (!value) return { difficulty_id: 0, difficulty: 0 };
            const parts = String(value).split(':');
            return {
                difficulty_id: Number(parts[0] || 0),
                difficulty: Number(parts[1] || 0)
            };
        }
        function showtimeSelectionValue(row) {
            if (!row) return '';
            return `${Number(row.difficulty_id || 0)}:${Number(row.difficulty || 0)}`;
        }
        function raceRecordSelectValue(row, key) {
            const value = Number((row || {})[key] || 0);
            return value > 0 ? String(value) : '';
        }
        function dailyRecordLabel(row, fallbackPrefix) {
            const record = row || {};
            const id = Number(record.record_id || record.daily_race_id || record.legend_race_id || 0);
            const base = record.label || record.display_name || (id ? `${fallbackPrefix} #${id}` : fallbackPrefix);
            const status = record.status_label || (Number(record.is_played || 0) ? 'Played' : 'Unplayed');
            const course = record.course_summary ? ` - ${record.course_summary}` : '';
            return `${base} (${status})${course}`;
        }
        function renderRaceRecordOptions(select, rows, key, selectedValue, autoLabel) {
            if (!select) return '';
            const list = Array.isArray(rows) ? rows : [];
            const normalizedSelected = String(selectedValue || '');
            const sorted = list.slice().sort((a, b) => Number(a?.is_played || 0) - Number(b?.is_played || 0));
            const values = new Set(sorted.map(row => raceRecordSelectValue(row, key)).filter(Boolean));
            select.innerHTML = `<option value="">${escapeHtml(autoLabel || 'Auto first unplayed')}</option>` + sorted.map(row => {
                const value = raceRecordSelectValue(row, key);
                if (!value) return '';
                return `<option value="${escapeAttr(value)}">${escapeHtml(dailyRecordLabel(row, autoLabel || 'Race'))}</option>`;
            }).join('');
            select.value = values.has(normalizedSelected) ? normalizedSelected : '';
            return select.value;
        }
        function setDailyEventTab(tabName) {
            const key = tabName === 'assignments' ? 'assignments' : 'run';
            state.activeDailyEventTab = key;
            safeLocalSet('activeDailyEventTab', key);
            [
                [els.dailyEventTabRun, 'run'],
                [els.dailyEventTabAssignments, 'assignments']
            ].forEach(([btn, value]) => btn && btn.classList.toggle('is-active', value === key));
            if (els.dailyEventRunPanel) els.dailyEventRunPanel.classList.toggle('is-active', key === 'run');
            if (els.dailyEventAssignmentsPanel) els.dailyEventAssignmentsPanel.classList.toggle('is-active', key === 'assignments');
        }
        function dailyCharacterRows() {
            return []
                .concat((dashData && dashData.parents) || [])
                .filter(row => row && row.instance_id);
        }
        function dailyCharacterOptionHtml(current = '') {
            const rows = dailyCharacterRows();
            return `<option value="">Choose trained character</option>` + rows.slice(0, 500).map(row => {
                const value = String(row.instance_id || '');
                const score = row.score || row.rank_score || 0;
                const label = `${row.name || 'Uma'} - ${score || 'no score'} - ID ${value}`;
                return `<option value="${escapeAttr(value)}"${value === String(current || '') ? ' selected' : ''}>${escapeHtml(label)}</option>`;
            }).join('');
        }
        function dailyStyleOptions(current = '2') {
            const selected = String(current || '2');
            return [
                ['1', 'Front'],
                ['2', 'Pace'],
                ['3', 'Late'],
                ['4', 'End']
            ].map(([value, label]) => `<option value="${value}"${value === selected ? ' selected' : ''}>${label}</option>`).join('');
        }
        function assignmentForKey(key) {
            state.dailyAssignments = state.dailyAssignments || loadDailyAssignments();
            state.dailyAssignments[key] = state.dailyAssignments[key] || defaultDailyAssignment(state.selectedDailyRunningStyle);
            return state.dailyAssignments[key];
        }
        function assignmentCourseText(key) {
            if (key === 'all') return 'Copies this character/style to Daily Race, Legend Race, and Daily Legend Race.';
            const section = (state.dailyEvents || {})[key] || {};
            const selectedId = key === 'daily_race' ? state.selectedDailyRaceId : key === 'legend_race' ? state.selectedLegendRaceId : state.selectedDailyLegendRaceId;
            const idKey = key === 'daily_race' ? 'daily_race_id' : 'legend_race_id';
            const record = (section.records || []).find(row => String(row[idKey] || '') === String(selectedId || ''))
                || (section.records || []).find(row => !Number(row.is_played || 0))
                || (section.records || [])[0];
            if (!record) return 'No race entries are populated from game data yet. Refresh game data after opening this race screen in-game.';
            if (record.course_summary) return record.course_summary;
            if (record.course_info && record.course_info.length) {
                return record.course_info.map(item => `${item.label}: ${item.value}`).join(' / ');
            }
            return `${record.label || DAILY_ASSIGNMENT_LABELS[key]} - course details unavailable until the game exposes this record in load/index.`;
        }
        function renderDailyAssignments() {
            const targets = {
                all: els.dailyAssignmentAll,
                daily_race: els.dailyAssignmentDailyRace,
                legend_race: els.dailyAssignmentLegendRace,
                daily_legend_race: els.dailyAssignmentDailyLegendRace
            };
            Object.entries(targets).forEach(([key, container]) => {
                if (!container) return;
                const assignment = assignmentForKey(key);
                const applyAll = key === 'all' ? '<button class="btn btn-sm daily-assignment-apply-all" type="button">APPLY ALL</button>' : '';
                container.innerHTML = `
                    <div class="daily-assignment-card-title">
                        <span>${escapeHtml(DAILY_ASSIGNMENT_LABELS[key] || key)}</span>
                        ${applyAll}
                    </div>
                    <div class="daily-assignment-fields">
                        <select class="skill-profile-select daily-assignment-character" data-assignment-key="${escapeAttr(key)}">
                            ${dailyCharacterOptionHtml(assignment.trained_chara_id)}
                        </select>
                        <select class="skill-profile-select daily-assignment-style" data-assignment-key="${escapeAttr(key)}">
                            ${dailyStyleOptions(assignment.running_style)}
                        </select>
                    </div>
                    <div class="daily-assignment-course">${escapeHtml(assignmentCourseText(key))}</div>
                `;
            });
        }
        function persistAssignmentChange(key, field, value) {
            const assignment = assignmentForKey(key);
            assignment[field] = String(value || '');
            if (field === 'running_style' && !assignment[field]) assignment[field] = '2';
            saveDailyAssignments();
            if (els.dailyAssignmentStatus) {
                els.dailyAssignmentStatus.textContent = `${DAILY_ASSIGNMENT_LABELS[key] || key} assignment saved.`;
                els.dailyAssignmentStatus.style.color = '';
            }
        }
        function applyAllDailyAssignments() {
            const all = assignmentForKey('all');
            DAILY_ASSIGNMENT_KEYS.forEach(key => {
                state.dailyAssignments[key] = {
                    trained_chara_id: String(all.trained_chara_id || ''),
                    running_style: String(all.running_style || '2')
                };
            });
            saveDailyAssignments();
            renderDailyAssignments();
            if (els.dailyAssignmentStatus) {
                els.dailyAssignmentStatus.textContent = 'All daily/legend race tags now use the All Tags assignment.';
                els.dailyAssignmentStatus.style.color = '';
            }
        }
        function normalizedDailyAssignmentsPayload() {
            const payload = {};
            DAILY_ASSIGNMENT_KEYS.forEach(key => {
                const row = assignmentForKey(key);
                const trained = Number(row.trained_chara_id || 0);
                const style = Number(row.running_style || 0);
                if (trained || style) {
                    payload[key] = { trained_chara_id: trained, running_style: style };
                }
            });
            return payload;
        }
        function racePickerConfig(kind) {
            const configs = {
                daily_race: {
                    title: 'Daily Race',
                    section: (state.dailyEvents || {}).daily_race || {},
                    select: els.dailyRaceIdSelect,
                    stateKey: 'selectedDailyRaceId',
                    storageKey: 'selectedDailyRaceId',
                    idKey: 'daily_race_id'
                },
                legend_race: {
                    title: 'Legend Race',
                    section: (state.dailyEvents || {}).legend_race || {},
                    select: els.legendRaceIdInput,
                    stateKey: 'selectedLegendRaceId',
                    storageKey: 'selectedLegendRaceId',
                    idKey: 'legend_race_id'
                },
                daily_legend_race: {
                    title: 'Daily Legend Race',
                    section: (state.dailyEvents || {}).daily_legend_race || {},
                    select: els.dailyLegendRaceIdSelect,
                    stateKey: 'selectedDailyLegendRaceId',
                    storageKey: 'selectedDailyLegendRaceId',
                    idKey: 'legend_race_id'
                }
            };
            return configs[kind] || configs.daily_race;
        }
        function renderDailyRacePicker() {
            if (!els.dailyRacePickerList || !state.activeDailyRacePicker) return;
            const config = racePickerConfig(state.activeDailyRacePicker);
            const rows = Array.isArray(config.section.records) ? config.section.records.slice() : [];
            const query = String(state.dailyRacePickerQuery || '').trim().toLowerCase();
            const selected = String(state[config.stateKey] || '');
            const filtered = rows
                .filter(row => {
                    if (!query) return true;
                    const haystack = [
                        row.label,
                        row.display_name,
                        row.status_label,
                        row.course_summary,
                        ...(row.course_info || []).map(item => `${item.label} ${item.value}`)
                    ].join(' ').toLowerCase();
                    return haystack.includes(query);
                })
                .sort((a, b) => Number(a.is_played || 0) - Number(b.is_played || 0));
            if (!filtered.length) {
                els.dailyRacePickerList.innerHTML = `<div class="daily-race-option-empty">No ${escapeHtml(config.title)} entries are populated. Refresh game data after opening that race screen in-game.</div>`;
                return;
            }
            els.dailyRacePickerList.innerHTML = filtered.map(row => {
                const value = raceRecordSelectValue(row, config.idKey);
                const info = (row.course_info || []).map(item => `${item.label}: ${item.value}`).join(' / ');
                return `<button class="daily-race-option ${String(value) === selected ? 'is-selected' : ''}" type="button" data-race-value="${escapeAttr(value)}">
                    <div class="daily-race-option-main">
                        <span>${escapeHtml(row.label || row.display_name || `${config.title} #${value}`)}</span>
                        <span>${escapeHtml(row.status_label || '')}</span>
                    </div>
                    <div class="daily-race-option-meta">ID ${escapeHtml(value || '0')}</div>
                    <div class="daily-race-option-course">${escapeHtml(info || row.course_summary || 'Course details unavailable from current game data.')}</div>
                </button>`;
            }).join('');
        }
        function openDailyRacePicker(kind) {
            state.activeDailyRacePicker = kind;
            state.dailyRacePickerQuery = '';
            const config = racePickerConfig(kind);
            if (els.dailyRacePickerTitle) els.dailyRacePickerTitle.textContent = `${config.title} Picker`;
            if (els.dailyRacePickerSubtitle) {
                const count = Array.isArray(config.section.records) ? config.section.records.length : 0;
                els.dailyRacePickerSubtitle.textContent = `${count} entries loaded. Choose one, or keep auto first unplayed.`;
            }
            if (els.dailyRacePickerSearch) els.dailyRacePickerSearch.value = '';
            if (els.dailyRacePickerOverlay) els.dailyRacePickerOverlay.classList.add('is-open');
            renderDailyRacePicker();
        }
        function closeDailyRacePicker() {
            if (els.dailyRacePickerOverlay) els.dailyRacePickerOverlay.classList.remove('is-open');
            state.activeDailyRacePicker = null;
            state.dailyRacePickerQuery = '';
        }
        function chooseDailyRacePickerValue(value) {
            if (!state.activeDailyRacePicker) return;
            const config = racePickerConfig(state.activeDailyRacePicker);
            state[config.stateKey] = String(value || '');
            safeLocalSet(config.storageKey, state[config.stateKey]);
            if (config.select) config.select.value = state[config.stateKey];
            renderDailyAssignments();
            closeDailyRacePicker();
        }
        function setDailyEventStatus(message, isError) {
            if (!els.dailyEventStatus) return;
            els.dailyEventStatus.textContent = message || '';
            els.dailyEventStatus.style.color = isError ? '#ff6d8e' : '';
        }
        function dailyEventStatusSummary(status) {
            if (!status) return 'Refresh game data to inspect available daily/event tasks.';
            const showtime = status.showtime || {};
            const daily = status.daily_race || {};
            const legend = status.legend_race || {};
            const team = status.team_trials || {};
            const shops = (status.shops && status.shops.limited_shop) || {};
            return [
                showtime.available ? `Showtime ${showtime.difficulty_options?.length || 0} options` : 'Showtime unavailable',
                `Daily unplayed ${daily.unplayed_count || 0}`,
                `Legend unplayed ${legend.unplayed_count || 0}`,
                `Daily Legend Race unplayed ${((status.daily_legend_race || {}).unplayed_count) || 0}`,
                `RP ${team.rp_current || 0}/${team.rp_max || 0}`,
                shops.available ? `Limited shop open (${shops.open_count || 0})` : 'Limited shop closed'
            ].join(' · ');
        }
        function renderDailyEventPanel(status) {
            if (!els.dailyEventPanel) return;
            state.dailyEvents = status || state.dailyEvents || null;
            els.dailyEventPanel.hidden = false;
            if (els.dailyEventSummary) els.dailyEventSummary.textContent = dailyEventStatusSummary(state.dailyEvents);

            const options = (((state.dailyEvents || {}).showtime || {}).difficulty_options || []);
            if (els.showtimeDifficultySelect) {
                const current = state.selectedShowtimeDifficulty || els.showtimeDifficultySelect.value || '';
                els.showtimeDifficultySelect.innerHTML = `<option value="">No Showtime difficulty</option>` + options.map(row => {
                    const value = showtimeSelectionValue(row);
                    return `<option value="${escapeAttr(value)}">${escapeHtml(row.label || value)}</option>`;
                }).join('');
                const values = new Set(options.map(showtimeSelectionValue));
                els.showtimeDifficultySelect.value = values.has(current) ? current : '';
                state.selectedShowtimeDifficulty = els.showtimeDifficultySelect.value;
                safeLocalSet('selectedShowtimeDifficulty', state.selectedShowtimeDifficulty);
            }
            if (els.dailyRunningStyleSelect) {
                els.dailyRunningStyleSelect.value = String(state.selectedDailyRunningStyle || '2');
            }
            if (els.dailyTrainedCharaSelect) {
                const current = state.selectedDailyTrainedCharaId || els.dailyTrainedCharaSelect.value || '';
                const rows = dailyCharacterRows();
                els.dailyTrainedCharaSelect.innerHTML = `<option value="">Choose trained character</option>` + rows.slice(0, 300).map(row => {
                    const value = String(row.instance_id || '');
                    const label = `${row.name || 'Uma'} · ${row.score || 0} · ID ${value}`;
                    return `<option value="${escapeAttr(value)}">${escapeHtml(label)}</option>`;
                }).join('');
                const values = new Set(rows.map(row => String(row.instance_id || '')));
                els.dailyTrainedCharaSelect.value = values.has(current) ? current : '';
                state.selectedDailyTrainedCharaId = els.dailyTrainedCharaSelect.value;
                safeLocalSet('selectedDailyTrainedCharaId', state.selectedDailyTrainedCharaId);
            }
            const daily = (state.dailyEvents || {}).daily_race || {};
            const legend = (state.dailyEvents || {}).legend_race || {};
            const dailyLegend = (state.dailyEvents || {}).daily_legend_race || {};
            state.selectedDailyRaceId = renderRaceRecordOptions(
                els.dailyRaceIdSelect,
                daily.records || [],
                'daily_race_id',
                state.selectedDailyRaceId,
                daily.next_daily_race_id ? `Auto #${daily.next_daily_race_id}` : 'Auto first unplayed'
            );
            safeLocalSet('selectedDailyRaceId', state.selectedDailyRaceId);
            state.selectedLegendRaceId = renderRaceRecordOptions(
                els.legendRaceIdInput,
                legend.records || [],
                'legend_race_id',
                state.selectedLegendRaceId,
                legend.next_legend_race_id ? `Auto #${legend.next_legend_race_id}` : 'Auto first unplayed'
            );
            safeLocalSet('selectedLegendRaceId', state.selectedLegendRaceId);
            state.selectedDailyLegendRaceId = renderRaceRecordOptions(
                els.dailyLegendRaceIdSelect,
                dailyLegend.records || [],
                'legend_race_id',
                state.selectedDailyLegendRaceId,
                dailyLegend.next_legend_race_id ? `Auto #${dailyLegend.next_legend_race_id}` : 'Auto first unplayed'
            );
            safeLocalSet('selectedDailyLegendRaceId', state.selectedDailyLegendRaceId);
            setDailyEventTab(state.activeDailyEventTab);
            renderDailyAssignments();
        }
        async function refreshDailyEvents(force = false) {
            if (state.dailyEventsLoading) return;
            state.dailyEventsLoading = true;
            if (els.dailyEventRefreshBtn) els.dailyEventRefreshBtn.disabled = true;
            try {
                const data = await apiJson(`/api/dailies/status?refresh=${force ? '1' : '0'}&t=${Date.now()}`);
                if (!data.success) throw new Error(data.detail || 'Daily/event status failed');
                renderDailyEventPanel(data);
                setDailyEventStatus('', false);
            } catch (err) {
                setDailyEventStatus(err.message || 'Daily/event status failed', true);
            } finally {
                state.dailyEventsLoading = false;
                if (els.dailyEventRefreshBtn) els.dailyEventRefreshBtn.disabled = false;
            }
        }
        async function runSelectedDailyEvents() {
            if (state.dailyEventsRunning) return;
            state.dailyEventsRunning = true;
            if (els.dailyEventRunBtn) els.dailyEventRunBtn.disabled = true;
            const showtime = parseShowtimeSelection(state.selectedShowtimeDifficulty || (els.showtimeDifficultySelect && els.showtimeDifficultySelect.value) || '');
            const payload = {
                run_team_trials_once: Boolean(els.dailyRunTeamTrials && els.dailyRunTeamTrials.checked),
                run_daily_race: Boolean(els.dailyRunDailyRace && els.dailyRunDailyRace.checked),
                run_legend_race: Boolean(els.dailyRunLegendRace && els.dailyRunLegendRace.checked),
                run_daily_legend_race: Boolean(els.dailyRunDailyLegendRace && els.dailyRunDailyLegendRace.checked),
                drain_daily_shops: Boolean(els.dailyDrainShops && els.dailyDrainShops.checked),
                daily_race_id: Number((els.dailyRaceIdSelect && els.dailyRaceIdSelect.value) || state.selectedDailyRaceId || 0),
                legend_race_id: Number((els.legendRaceIdInput && els.legendRaceIdInput.value) || state.selectedLegendRaceId || 0),
                daily_legend_race_id: Number((els.dailyLegendRaceIdSelect && els.dailyLegendRaceIdSelect.value) || state.selectedDailyLegendRaceId || 0),
                trained_chara_id: Number(state.selectedDailyTrainedCharaId || (els.dailyTrainedCharaSelect && els.dailyTrainedCharaSelect.value) || 0),
                running_style: Number(state.selectedDailyRunningStyle || (els.dailyRunningStyleSelect && els.dailyRunningStyleSelect.value) || 0),
                difficulty_id: showtime.difficulty_id,
                difficulty: showtime.difficulty,
                assignments: normalizedDailyAssignmentsPayload()
            };
            try {
                const data = await apiJson('/api/dailies/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                renderDailyEventPanel(data.status || state.dailyEvents);
                if (!data.success) throw new Error(data.detail || 'Daily/event run failed');
                setDailyEventStatus(data.detail || 'Daily/event run complete', false);
                await refreshDailyEvents(true);
            } catch (err) {
                setDailyEventStatus(err.message || 'Daily/event run failed', true);
            } finally {
                state.dailyEventsRunning = false;
                if (els.dailyEventRunBtn) els.dailyEventRunBtn.disabled = false;
            }
        }
        function bindDailyEventControls() {
            els.dailyEventRefreshBtn?.addEventListener('click', () => refreshDailyEvents(true));
            els.dailyEventRunBtn?.addEventListener('click', runSelectedDailyEvents);
            els.dailyEventTabRun?.addEventListener('click', () => setDailyEventTab('run'));
            els.dailyEventTabAssignments?.addEventListener('click', () => setDailyEventTab('assignments'));
            els.dailyRacePickerBtn?.addEventListener('click', () => openDailyRacePicker('daily_race'));
            els.legendRacePickerBtn?.addEventListener('click', () => openDailyRacePicker('legend_race'));
            els.dailyLegendRacePickerBtn?.addEventListener('click', () => openDailyRacePicker('daily_legend_race'));
            els.dailyRacePickerClose?.addEventListener('click', closeDailyRacePicker);
            els.dailyRacePickerCancel?.addEventListener('click', closeDailyRacePicker);
            els.dailyRacePickerAuto?.addEventListener('click', () => chooseDailyRacePickerValue(''));
            els.dailyRacePickerSearch?.addEventListener('input', () => {
                state.dailyRacePickerQuery = els.dailyRacePickerSearch.value || '';
                renderDailyRacePicker();
            });
            els.dailyRacePickerList?.addEventListener('click', event => {
                const row = event.target.closest('.daily-race-option');
                if (!row) return;
                chooseDailyRacePickerValue(row.dataset.raceValue || '');
            });
            els.dailyRacePickerOverlay?.addEventListener('click', event => {
                if (event.target === els.dailyRacePickerOverlay) closeDailyRacePicker();
            });
            [
                els.dailyAssignmentAll,
                els.dailyAssignmentDailyRace,
                els.dailyAssignmentLegendRace,
                els.dailyAssignmentDailyLegendRace
            ].forEach(container => {
                container?.addEventListener('change', event => {
                    const key = event.target.dataset.assignmentKey || container.dataset.assignmentKey;
                    if (!key) return;
                    if (event.target.classList.contains('daily-assignment-character')) {
                        persistAssignmentChange(key, 'trained_chara_id', event.target.value || '');
                    }
                    if (event.target.classList.contains('daily-assignment-style')) {
                        persistAssignmentChange(key, 'running_style', event.target.value || '2');
                    }
                });
                container?.addEventListener('click', event => {
                    if (event.target.closest('.daily-assignment-apply-all')) applyAllDailyAssignments();
                });
            });
            els.showtimeDifficultySelect?.addEventListener('change', () => {
                state.selectedShowtimeDifficulty = els.showtimeDifficultySelect.value || '';
                safeLocalSet('selectedShowtimeDifficulty', state.selectedShowtimeDifficulty);
            });
            els.dailyTrainedCharaSelect?.addEventListener('change', () => {
                state.selectedDailyTrainedCharaId = els.dailyTrainedCharaSelect.value || '';
                safeLocalSet('selectedDailyTrainedCharaId', state.selectedDailyTrainedCharaId);
                renderDailyAssignments();
            });
            els.dailyRunningStyleSelect?.addEventListener('change', () => {
                state.selectedDailyRunningStyle = els.dailyRunningStyleSelect.value || '2';
                safeLocalSet('selectedDailyRunningStyle', state.selectedDailyRunningStyle);
            });
            els.dailyRaceIdSelect?.addEventListener('change', () => {
                state.selectedDailyRaceId = els.dailyRaceIdSelect.value || '';
                safeLocalSet('selectedDailyRaceId', state.selectedDailyRaceId);
                renderDailyAssignments();
            });
            els.legendRaceIdInput?.addEventListener('change', () => {
                state.selectedLegendRaceId = els.legendRaceIdInput.value || '';
                safeLocalSet('selectedLegendRaceId', state.selectedLegendRaceId);
                renderDailyAssignments();
            });
            els.dailyLegendRaceIdSelect?.addEventListener('change', () => {
                state.selectedDailyLegendRaceId = els.dailyLegendRaceIdSelect.value || '';
                safeLocalSet('selectedDailyLegendRaceId', state.selectedDailyLegendRaceId);
                renderDailyAssignments();
            });
            setDailyEventTab(state.activeDailyEventTab);
            renderDailyAssignments();
        }
        function syncTpRecoveryControl() {
            if (!els.tpRecoverySelect) return;
            const activeRun = state.runnerRunning || state.loopActive || state.isStartingCareer || state.isVerifyingStart;
            els.tpRecoverySelect.value = String(state.tpRecoveryMode);
            els.tpRecoverySelect.disabled = activeRun;
        }
        function syncLoopControls() {
            const activeRun = state.runnerRunning || state.loopActive || state.isStartingCareer || state.isVerifyingStart;
            if (els.loopToggleBtn) {
                els.loopToggleBtn.classList.toggle('is-active', state.loopEnabled);
                els.loopToggleBtn.innerText = state.loopEnabled ? 'LOOP ON' : 'LOOP OFF';
                els.loopToggleBtn.setAttribute('aria-pressed', String(state.loopEnabled));
                els.loopToggleBtn.disabled = activeRun;
            }
            state.loopMode = normalizeLoopMode();
            state.loopCareerLimit = normalizeLoopCareerLimit();
            state.loopFanLimit = normalizeLoopFanLimit();
            if (els.loopModeSelect) {
                els.loopModeSelect.value = state.loopMode;
                els.loopModeSelect.disabled = !state.loopEnabled || activeRun;
            }
            const careerWrap = els.loopCareerLimitInput && els.loopCareerLimitInput.closest('.loop-field-wrap');
            const fanWrap = els.loopFanLimitInput && els.loopFanLimitInput.closest('.loop-field-wrap');
            if (careerWrap) careerWrap.classList.toggle('is-hidden', state.loopMode !== 'careers');
            if (fanWrap) fanWrap.classList.toggle('is-hidden', state.loopMode !== 'fans');
            if (els.loopCareerLimitInput) {
                els.loopCareerLimitInput.disabled = !state.loopEnabled || activeRun || state.loopMode !== 'careers';
                els.loopCareerLimitInput.value = String(state.loopCareerLimit);
            }
            if (els.loopFanLimitInput) {
                els.loopFanLimitInput.disabled = !state.loopEnabled || activeRun || state.loopMode !== 'fans';
                els.loopFanLimitInput.value = String(state.loopFanLimit);
            }
            if (els.stopRunnerBtn) {
                els.stopRunnerBtn.style.display = (state.runnerRunning || state.loopActive) ? '' : 'none';
                els.stopRunnerBtn.disabled = state.isStoppingRunner;
                els.stopRunnerBtn.innerText = state.isStoppingRunner ? 'STOPPING...' : 'STOP';
            }
            if (els.endCareerBtn) {
                const activeCareer = Boolean((state.account && state.account.career && state.account.career.active) || state.runnerRunning || state.loopActive);
                els.endCareerBtn.style.display = activeCareer ? '' : 'none';
                els.endCareerBtn.disabled = state.isEndingCareer || state.isStoppingRunner;
                els.endCareerBtn.innerText = state.isEndingCareer ? 'ENDING...' : 'END CAREER';
            }
            syncCareerNotifyToggle();
        }
        function syncStartButton() {
            const reason = getStartMissingReason();
            const activeRun = state.runnerRunning || state.loopActive;
            const busy = state.isStartingCareer || state.isVerifyingStart;
            els.startCareerBtn.disabled = Boolean(reason) || busy || activeRun;
            if (els.verifyStartBtn) {
                els.verifyStartBtn.disabled = Boolean(reason) || busy || activeRun;
                els.verifyStartBtn.innerText = state.isVerifyingStart ? 'VERIFYING...' : 'VERIFY START';
            }
            if (els.syncDashboardBtn) {
                els.syncDashboardBtn.disabled = state.isSyncingDashboard || busy || activeRun;
            }
            if (els.refreshBackendBtn) {
                els.refreshBackendBtn.disabled = state.isRefreshingBackend || state.isSyncingDashboard || busy || activeRun;
                els.refreshBackendBtn.innerText = state.isRefreshingBackend ? 'REFRESHING...' : 'REFRESH BACKEND';
            }
            if (state.isVerifyingStart) {
                setStartStatusMessage('Verifying live start state...');
            } else if (state.isStartingCareer) {
                els.startCareerBtn.innerText = 'RUNNING...';
                setStartStatusMessage('Starting runner...');
            } else if (activeRun) {
                els.startCareerBtn.innerText = state.loopActive ? 'LOOPING...' : 'RUNNING...';
            } else {
                const activeCareer = state.account && state.account.career && state.account.career.active;
                els.startCareerBtn.innerText = activeCareer ? 'RESUME CAREER' : 'RUN CAREER';
                setStartStatusMessage(reason);
            }
            syncTpRecoveryControl();
            syncLoopControls();
        }
        function getSupportUncapPlan(supports) {
            return (Array.isArray(supports) ? supports : [])
                .map(card => {
                    const limitBreakCount = Number(card && card.limit_break_count || 0) || 0;
                    const stock = Number(card && card.stock || 0) || 0;
                    return {
                        ...(card || {}),
                        limit_break_count: limitBreakCount,
                        stock: stock,
                        availableSteps: Math.max(0, Math.min(stock, 4 - limitBreakCount))
                    };
                })
                .filter(card => Number(card.id || 0) > 0 && card.availableSteps > 0);
        }
        function renderSupportInventoryControls() {
            const plan = getSupportUncapPlan((dashData && dashData.supports) || []);
            const totalSteps = plan.reduce((sum, row) => sum + Number(row.availableSteps || 0), 0);
            if (els.cardUncapAllBtn) {
                els.cardUncapAllBtn.disabled = state.supportInventoryBusy || !plan.length;
                els.cardUncapAllBtn.textContent = state.supportInventoryBusy
                    ? 'UNCAPPING...'
                    : 'UNCAP ALL DUPES';
            }
            if (els.cardInventoryStatus) {
                if (state.supportInventoryBusy) {
                    els.cardInventoryStatus.textContent = 'Applying live duplicate support uncaps...';
                } else if (state.supportInventoryStatusMessage) {
                    const suffix = plan.length ? ` Ready: ${plan.length} card(s), ${totalSteps} uncaps still available.` : '';
                    els.cardInventoryStatus.textContent = `${state.supportInventoryStatusMessage}${suffix}`;
                } else if (plan.length) {
                    els.cardInventoryStatus.textContent = `Ready: ${plan.length} card(s), ${totalSteps} duplicate uncaps available.`;
                } else {
                    els.cardInventoryStatus.textContent = 'No duplicate support uncaps currently available.';
                }
            }
        }
        async function uncapAllOwnedSupportCards() {
            const plan = getSupportUncapPlan((dashData && dashData.supports) || []);
            const totalSteps = plan.reduce((sum, row) => sum + Number(row.availableSteps || 0), 0);
            if (!plan.length) {
                state.supportInventoryStatusMessage = 'No duplicate support uncaps are available right now.';
                renderSupportInventoryControls();
                return;
            }
            const prompt = `Consume duplicate support-card stock to apply ${totalSteps} live uncaps across ${plan.length} card(s)?`;
            if (!window.confirm(prompt)) return;
            state.supportInventoryBusy = true;
            renderSupportInventoryControls();
            try {
                const data = await apiJson('/api/supports/limit_break_all', { method: 'POST' });
                if (data.dashboard) {
                    await renderDashboard(data.dashboard, { animateIntro: false, waitForIntro: false });
                }
                if (!data.success) throw new Error(data.detail || 'Live support uncap failed');
                state.supportInventoryStatusMessage = data.detail || `Applied ${totalSteps} support uncaps.`;
                if (!data.dashboard) {
                    renderSupportInventoryControls();
                    renderSupports((dashData && dashData.supports) || []);
                    await loadDeckAdvice(true);
                }
            } catch (e) {
                state.supportInventoryStatusMessage = e && e.message ? e.message : 'Live support uncap failed';
                renderSupportInventoryControls();
                throw e;
            } finally {
                state.supportInventoryBusy = false;
                renderSupportInventoryControls();
            }
        }
        function bindSupportInventoryControls() {
            renderSupportInventoryControls();
            if (!els.cardUncapAllBtn || els.cardUncapAllBtn.dataset.bound === '1') return;
            els.cardUncapAllBtn.dataset.bound = '1';
            els.cardUncapAllBtn.addEventListener('click', event => {
                event.preventDefault();
                uncapAllOwnedSupportCards().catch(e => alert(e.message || 'Live support uncap failed'));
            });
        }
        function deckAdviceRequestKey() {
            const deckId = Number((selection.deck && selection.deck.id) || 0);
            const deckSet = ((dashData && dashData.validDecks) || []).map(deck => Number(deck.id || 0)).filter(Boolean).join(',');
            const traineeId = Number((selection.trainee && selection.trainee.id) || 0);
            const friendId = Number((selection.friend && (selection.friend.support_card_id || selection.friend.id)) || 0);
            const supportSig = ((dashData && dashData.supports) || [])
                .map(card => `${Number(card.id || 0)}:${Number(card.limit_break_count || 0)}:${Number(card.support_card_level || 0)}`)
                .join(',');
            return `${selectedPresetName()}::${deckId}::${traineeId}::${friendId}::${deckSet}::${supportSig}`;
        }
        function setDeckAdviceExpanded(expanded) {
            state.deckAdviceExpanded = Boolean(expanded);
            renderDeckAdvice();
        }
        function bindDeckAdviceToggle() {
            if (!els.deckAdviceToggle || els.deckAdviceToggle.dataset.bound === '1') return;
            els.deckAdviceToggle.dataset.bound = '1';
            els.deckAdviceToggle.addEventListener('click', event => {
                event.preventDefault();
                setDeckAdviceExpanded(!state.deckAdviceExpanded);
            });
        }
        function renderDeckAdvice() {
            if (!els.deckAdvicePanel) return;
            const decks = (dashData && dashData.validDecks) || [];
            if (!decks.length) {
                els.deckAdvicePanel.hidden = true;
                return;
            }
            const advice = state.deckAdvice;
            els.deckAdvicePanel.hidden = false;
            if (state.deckAdviceLoading) {
                els.deckAdvicePanel.classList.add('is-collapsed');
                if (els.deckAdviceToggle) els.deckAdviceToggle.hidden = true;
                if (els.deckAdviceConfidence) els.deckAdviceConfidence.textContent = 'loading';
                if (els.deckAdviceMessage) els.deckAdviceMessage.textContent = 'Scoring saved decks and building a fresh support recommendation...';
                if (els.deckAdviceMeta) els.deckAdviceMeta.textContent = '';
                if (els.deckAdviceList) els.deckAdviceList.innerHTML = '';
                return;
            }
            if (!advice || advice.success === false) {
                els.deckAdvicePanel.classList.add('is-collapsed');
                if (els.deckAdviceToggle) els.deckAdviceToggle.hidden = true;
                if (els.deckAdviceConfidence) els.deckAdviceConfidence.textContent = 'unavailable';
                if (els.deckAdviceMessage) els.deckAdviceMessage.textContent = 'Deck advice is not available yet.';
                if (els.deckAdviceMeta) els.deckAdviceMeta.textContent = '';
                if (els.deckAdviceList) els.deckAdviceList.innerHTML = '';
                return;
            }
            const recommendedBuild = advice.recommended_build && Array.isArray(advice.recommended_build.cards) && advice.recommended_build.cards.length
                ? advice.recommended_build
                : null;
            const legacyRows = Array.isArray(advice.alternatives) ? advice.alternatives : [];
            const hasExpandableDetails = Boolean(
                (recommendedBuild && (
                    (Array.isArray(recommendedBuild.cards) && recommendedBuild.cards.length) ||
                    (Array.isArray(recommendedBuild.swap_suggestions) && recommendedBuild.swap_suggestions.length) ||
                    (Array.isArray(recommendedBuild.current_weaknesses) && recommendedBuild.current_weaknesses.length)
                )) ||
                (!recommendedBuild && legacyRows.length)
            );
            els.deckAdvicePanel.classList.toggle('is-collapsed', hasExpandableDetails && !state.deckAdviceExpanded);
            if (els.deckAdviceToggle) {
                els.deckAdviceToggle.hidden = !hasExpandableDetails;
                els.deckAdviceToggle.textContent = state.deckAdviceExpanded ? 'HIDE DETAILS' : 'SHOW DETAILS';
                els.deckAdviceToggle.setAttribute('aria-expanded', state.deckAdviceExpanded ? 'true' : 'false');
            }
            if (recommendedBuild) {
                if (els.deckAdviceConfidence) els.deckAdviceConfidence.textContent = String(recommendedBuild.confidence || advice.confidence || 'low').toUpperCase();
                if (els.deckAdviceMessage) els.deckAdviceMessage.textContent = recommendedBuild.message || advice.message || 'No deck recommendation available.';
                if (els.deckAdviceMeta) {
                    const goal = advice.goal_label ? `${advice.goal_label} goal` : 'balanced goal';
                    const parts = [goal];
                    const sampleCount = Number(recommendedBuild.sample_count || advice.sample_count || 0);
                    parts.push(`${sampleCount} matching samples`);
                    const sameTrainee = Number(recommendedBuild.same_trainee_samples || 0);
                    if (sameTrainee > 0) parts.push(`${sameTrainee} same-trainee runs`);
                    if (typeof recommendedBuild.score_gain === 'number') {
                        const delta = Number(recommendedBuild.score_gain || 0);
                        parts.push(`vs current ${delta >= 0 ? '+' : ''}${delta.toFixed(2)}`);
                    }
                    const weaknesses = Array.isArray(recommendedBuild.current_weaknesses)
                        ? recommendedBuild.current_weaknesses.filter(Boolean).slice(0, 2)
                        : [];
                    if (weaknesses.length) parts.push(`watch: ${weaknesses.join('; ')}`);
                    els.deckAdviceMeta.textContent = parts.join(' | ');
                }
                if (els.deckAdviceList) {
                    const cardRows = recommendedBuild.cards.map(row => {
                        const slotLabel = `${row.type || 'Unknown'} ${row.rarity || '?'} | LB${Number(row.limit_break_count || 0)} | Lv${Number(row.level || 0)}`;
                        const reasons = Array.isArray(row.reasons) ? row.reasons.slice(0, 3).join('. ') : '';
                        return `<div class="deck-advice-card is-best">
                            <div class="deck-advice-card-head">
                                <span class="deck-advice-card-name">${escapeHtml(row.name || `Card ${row.id || ''}`)}</span>
                                <span class="deck-advice-card-score">${escapeHtml(slotLabel)}</span>
                            </div>
                            <div class="deck-advice-card-copy">${escapeHtml(reasons || 'Fits the current parent-farming goal better than weaker pool options.')}</div>
                        </div>`;
                    });
                    const swapRows = (Array.isArray(recommendedBuild.swap_suggestions) ? recommendedBuild.swap_suggestions : []).slice(0, 3).map(row => {
                        const addName = ((row.add && row.add.name) || 'Add card');
                        const removeName = ((row.remove && row.remove.name) || 'remove card');
                        return `<div class="deck-advice-card">
                            <div class="deck-advice-card-head">
                                <span class="deck-advice-card-name">${escapeHtml(`Swap in ${addName}`)}</span>
                                <span class="deck-advice-card-score">UPGRADE</span>
                            </div>
                            <div class="deck-advice-card-copy">${escapeHtml(row.reason || `${addName} looks stronger than ${removeName}.`)}</div>
                        </div>`;
                    });
                    const weaknessRows = (Array.isArray(recommendedBuild.current_weaknesses) ? recommendedBuild.current_weaknesses : []).slice(0, 2).map(text => {
                        return `<div class="deck-advice-card">
                            <div class="deck-advice-card-head">
                                <span class="deck-advice-card-name">Current deck weakness</span>
                                <span class="deck-advice-card-score">WATCH</span>
                            </div>
                            <div class="deck-advice-card-copy">${escapeHtml(text || 'No weakness recorded.')}</div>
                        </div>`;
                    });
                    els.deckAdviceList.innerHTML = [...cardRows, ...swapRows, ...weaknessRows].join('');
                }
                return;
            }
            if (els.deckAdviceConfidence) els.deckAdviceConfidence.textContent = String(advice.confidence || 'low').toUpperCase();
            if (els.deckAdviceMessage) els.deckAdviceMessage.textContent = advice.message || 'No deck recommendation available.';
            if (els.deckAdviceMeta) {
                const goal = advice.goal_label ? `${advice.goal_label} goal` : 'balanced goal';
                const sampleCount = Number(advice.sample_count || 0);
                const fallback = advice.fallback_mode ? ' using all deck-tagged runs' : '';
                els.deckAdviceMeta.textContent = `${goal} · ${sampleCount} matching samples${fallback}`;
            }
            const bestId = Number((advice.best_deck && advice.best_deck.deck_id) || 0);
            const rows = legacyRows;
            if (els.deckAdviceList) {
                els.deckAdviceList.innerHTML = rows.map(row => {
                    const isBest = Number(row.deck_id || 0) === bestId;
                    const reasons = Array.isArray(row.reasons) ? row.reasons.slice(0, 2).join(' ') : '';
                    const exact = row.exact_history || {};
                    const exactText = Number(exact.sample_count || 0) > 0
                        ? `${Number(exact.sample_count || 0)} seen · ${Number(row.score || 0).toFixed(1)}`
                        : `${Number(row.score || 0).toFixed(1)} inferred`;
                    return `<div class="deck-advice-card ${isBest ? 'is-best' : ''}">
                        <div class="deck-advice-card-head">
                            <span class="deck-advice-card-name">${escapeHtml(row.name || `Deck ${row.deck_id || ''}`)}</span>
                            <span class="deck-advice-card-score">${escapeHtml(exactText)}</span>
                        </div>
                        <div class="deck-advice-card-copy">${escapeHtml(reasons || 'No stronger reason available yet.')}</div>
                    </div>`;
                }).join('');
            }
        }
        async function loadDeckAdvice(force = false) {
            if (!els.deckAdvicePanel) return;
            if (!dashData || !Array.isArray(dashData.validDecks) || !dashData.validDecks.length) {
                state.deckAdvice = null;
                state.deckAdviceLoading = false;
                renderDeckAdvice();
                return;
            }
            const key = deckAdviceRequestKey();
            if (!force && state.deckAdvice && state.deckAdviceKey === key) {
                renderDeckAdvice();
                return;
            }
            if (state.deckAdviceKey !== key) {
                state.deckAdviceExpanded = false;
            }
            state.deckAdviceLoading = true;
            state.deckAdviceKey = key;
            renderDeckAdvice();
            const requestId = ++state.deckAdviceRequestId;
            try {
                const params = new URLSearchParams({
                    preset_name: selectedPresetName(),
                    deck_id: String(Number((selection.deck && selection.deck.id) || 0))
                });
                const data = await apiJson(`/api/decks/advice?${params.toString()}`);
                if (requestId !== state.deckAdviceRequestId) return;
                if (!data.success) throw new Error(data.detail || 'Deck advice failed');
                state.deckAdvice = data.advice || null;
            } catch (e) {
                if (requestId !== state.deckAdviceRequestId) return;
                state.deckAdvice = {
                    success: false,
                    message: e.message || 'Deck advice failed'
                };
            } finally {
                if (requestId === state.deckAdviceRequestId) {
                    state.deckAdviceLoading = false;
                    renderDeckAdvice();
                }
            }
        }
        function renderTeamPanel() {
            document.getElementById('dashboard-view').classList.add('active');
            function setSlot(id, role, content, action, idx, emptyText = 'select') {
                const el = document.getElementById(id);
                el.className = content ? 'team-item filled' : 'team-item';
                el.onclick = content ? () => deselect(action, idx) : null;
                const clear = content ? '<span class="team-item-clear">clear</span>' : '';
                const empty = `<div class="team-item-empty">${emptyText}</div>`;
                el.innerHTML = `
                    <div class="team-item-head">
                        <span class="team-item-role">${role}</span>
                        ${clear}
                    </div>
                    ${content || empty}
                `;
            }
            const selectedParent2 = selectedComboParent2();
            if (selection.deck) {
                const thumbs = selection.deck.cards.map(c =>
                    `<img class="team-item-thumb" src="/api/images/${c.id || '10001'}.png" onerror="hideBrokenImage(this)">`
                ).join('');
                setSlot('team-slot-deck', 'Deck', `
                    <div class="team-item-body">
                        <div class="team-item-thumbs">${thumbs}</div>
                        <div class="team-item-text">
                            <span class="team-item-name">${selection.deck.name}</span>
                            <span class="team-item-sub">Slot ${selection.deck.id}</span>
                        </div>
                    </div>
                `, 'deck', null, 'select deck');
            } else {
                setSlot('team-slot-deck', 'Deck', null, 'deck', null, 'select deck');
            }
            if (selection.friend) {
                setSlot('team-slot-friend', 'Friend', `
                    <div class="team-item-body">
                        <img class="team-item-portrait" src="/api/images/${selection.friend.support_card_id || '10001'}.png" onerror="hideBrokenImage(this)">
                        <div class="team-item-text">
                            <span class="team-item-name">${selection.friend.support_name || 'Unknown'}</span>
                            <span class="team-item-sub">LB${selection.friend.limit_break_count ?? '?'}</span>
                        </div>
                    </div>
                `, 'friend', null, 'select friend');
            } else {
                setSlot('team-slot-friend', 'Friend', null, 'friend', null, 'select friend');
            }
            if (selection.trainee) {
                setSlot('team-slot-trainee', 'Trainee', `
                    <div class="team-item-body">
                        <img class="team-item-portrait" src="/api/images/${selection.trainee.id || '100101'}.png" onerror="hideBrokenImage(this)">
                        <div class="team-item-text">
                            <span class="team-item-name">${selection.trainee.name || 'Unknown'}</span>
                        </div>
                    </div>
                `, 'trainee', null, 'select trainee');
            } else {
                setSlot('team-slot-trainee', 'Trainee', null, 'trainee', null, 'select trainee');
            }
            const hasGuest = Boolean(selection.guestParent && selection.guestParent.viewer_id && selection.guestParent.trained_chara_id);
            // Parent 1 — always the user's veterans[0]
            const vet1 = selection.veterans[0];
            if (vet1) {
                const vet1Legacy = legacyStartPreview(selection.trainee || null, [vet1]);
                setSlot('team-slot-vet1', 'Parent 1', `
                    <div class="team-item-body">
                        <img class="team-item-portrait" src="/api/images/${vet1.card_id || '100101'}.png" onerror="hideBrokenImage(this)">
                        <div class="team-item-text">
                            <span class="team-item-name">${vet1.name || 'Unknown'}</span>
                            <span class="team-item-sub">${rankMap[vet1.rank] || '??'}${vet1.score != null ? ' · ' + formatNumber(vet1.score) : ''}</span>
                            ${vet1Legacy && vet1Legacy.statText ? `<span class="team-item-sub team-item-legacy-sub">Solo: ${escapeHtml(vet1Legacy.statText)}</span>` : ''}
                            ${vet1Legacy && vet1Legacy.aptitudeText ? `<span class="team-item-sub team-item-legacy-sub">Solo apt: ${escapeHtml(vet1Legacy.aptitudeText)}</span>` : ''}
                        </div>
                    </div>
                `, 'vet', 0, 'select parent');
            } else {
                setSlot('team-slot-vet1', 'Parent 1', null, 'vet', 0, 'select parent');
            }
            // Parent 2 slot is shared: it's filled by the GUEST when one is selected,
            // otherwise by the user's veterans[1]. When both are set, the guest takes the
            // slot and veterans[1] becomes the implicit fallback (shown as a sub-line).
            if (hasGuest) {
                const g = selection.guestParent;
                const vet2 = selection.veterans[1];
                const guestLegacy = legacyStartPreview(selection.trainee || null, [normalizeBorrowUmaSelection(g)]);
                const fallbackLine = vet2
                    ? `<span class="team-item-sub">Fallback: ${vet2.name || 'Unknown'} (${rankMap[vet2.rank] || '??'}${vet2.score != null ? ' · ' + formatNumber(vet2.score) : ''})</span>`
                    : `<span class="team-item-sub" style="opacity:.6">No fallback set</span>`;
                setSlot('team-slot-vet2', 'Guest (Parent 2)', `
                    <div class="team-item-body">
                        <img class="team-item-portrait" src="/api/images/${g.card_id || '100101'}.png" onerror="hideBrokenImage(this)">
                        <div class="team-item-text">
                            <span class="team-item-name">${g.chara_name || 'Unknown'}</span>
                            <span class="team-item-sub">${g.trainer_name ? 'Trainer: ' + g.trainer_name : ''}</span>
                            ${fallbackLine}
                            ${guestLegacy && guestLegacy.statText ? `<span class="team-item-sub team-item-legacy-sub">Solo: ${escapeHtml(guestLegacy.statText)}</span>` : ''}
                            ${guestLegacy && guestLegacy.aptitudeText ? `<span class="team-item-sub team-item-legacy-sub">Solo apt: ${escapeHtml(guestLegacy.aptitudeText)}</span>` : ''}
                        </div>
                    </div>
                `, 'guest', null, 'select guest');
            } else {
                const vet2 = selection.veterans[1];
                if (vet2) {
                    const vet2Legacy = legacyStartPreview(selection.trainee || null, [vet2]);
                    setSlot('team-slot-vet2', 'Parent 2', `
                        <div class="team-item-body">
                        <img class="team-item-portrait" src="/api/images/${vet2.card_id || '100101'}.png" onerror="hideBrokenImage(this)">
                        <div class="team-item-text">
                            <span class="team-item-name">${vet2.name || 'Unknown'}</span>
                            <span class="team-item-sub">${rankMap[vet2.rank] || '??'}${vet2.score != null ? ' · ' + formatNumber(vet2.score) : ''}</span>
                            ${vet2Legacy && vet2Legacy.statText ? `<span class="team-item-sub team-item-legacy-sub">Solo: ${escapeHtml(vet2Legacy.statText)}</span>` : ''}
                            ${vet2Legacy && vet2Legacy.aptitudeText ? `<span class="team-item-sub team-item-legacy-sub">Solo apt: ${escapeHtml(vet2Legacy.aptitudeText)}</span>` : ''}
                        </div>
                    </div>
                `, 'vet', 1, 'select parent');
                } else {
                    setSlot('team-slot-vet2', 'Parent 2', null, 'vet', 1, 'select parent');
                }
            }
            renderComboAffinitySummary();
            renderSetupLegacyDetails();
            syncStartButton();
            loadDeckAdvice();
        }
        function updateVetSelectability() {
            const full = selection.veterans.length >= 2;
            document.querySelectorAll('#parent-grid .grid-card').forEach(card => {
                if (card.classList.contains('selected')) {
                    card.classList.remove('vet-full');
                } else {
                    card.classList.toggle('vet-full', full);
                }
            });
            syncStartButton();
        }
        function normalizeSearchValue(value) {
            return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
        }
        function matchesLibrarySearch(item, query, fieldReaders) {
            const rawQuery = String(query || '').trim().toLowerCase();
            const compactQuery = normalizeSearchValue(rawQuery);
            if (!rawQuery && !compactQuery) return true;
            const haystack = fieldReaders.map(reader => {
                try {
                    return reader(item);
                } catch (e) {
                    return '';
                }
            }).join(' ').toLowerCase();
            return haystack.includes(rawQuery) || normalizeSearchValue(haystack).includes(compactQuery);
        }
        function traineeKey(uma) {
            return String(uma && uma.id != null ? uma.id : '');
        }
        function parentKey(parent) {
            if (!parent) return '';
            return String(parent.instance_id || `${parent.card_id || ''}:${parent.name || ''}:${parent.rank || ''}`);
        }
        function resetSessionParentStore() {
            retuned.sessionParentBaselineReady = false;
            retuned.sessionParentOrder = [];
            retuned.sessionParentSnapshots = {};
        }
        function sessionParentItems() {
            return retuned.sessionParentOrder
                .map(id => retuned.sessionParentSnapshots[id])
                .filter(Boolean);
        }
        function isTrackableSessionParent(parent) {
            if (!parent) return false;
            if (parent.made_by_bot) return true;
            return String(parent.source_kind || '').toLowerCase() === 'bot';
        }
        function trackSessionParents(parents, options = {}) {
            const list = (Array.isArray(parents) ? parents : []).filter(isTrackableSessionParent);
            const liveById = {};
            const liveIds = [];
            list.forEach(parent => {
                const key = parentKey(parent);
                if (!key) return;
                liveById[key] = parent;
                liveIds.push(key);
            });
            retuned.sessionParentOrder = retuned.sessionParentOrder.filter(id => !!liveById[id]);
            Object.keys(retuned.sessionParentSnapshots || {}).forEach(id => {
                if (liveById[id]) retuned.sessionParentSnapshots[id] = liveById[id];
                else delete retuned.sessionParentSnapshots[id];
            });
            if (options.fromCache) return;
            if (!retuned.sessionParentBaselineReady) {
                retuned.sessionParentBaselineReady = true;
                liveIds.forEach(id => { retuned.sessionParentSnapshots[id] = retuned.sessionParentSnapshots[id] || liveById[id]; });
                return;
            }
            list.forEach(parent => {
                const key = parentKey(parent);
                if (!key) return;
                if (retuned.sessionParentSnapshots[key]) {
                    retuned.sessionParentSnapshots[key] = parent;
                    return;
                }
                retuned.sessionParentSnapshots[key] = parent;
                retuned.sessionParentOrder.unshift(key);
            });
        }
        function mergeRunnerParents(parents, options = {}) {
            const list = Array.isArray(parents) ? parents : [];
            if (!dashData) dashData = {};
            const current = Array.isArray(dashData.parents) ? dashData.parents : [];
            const currentKeys = current.map(parentKey);
            const nextKeys = list.map(parentKey);
            const changed = current.length !== list.length || currentKeys.some((key, idx) => key !== nextKeys[idx]);
            trackSessionParents(list, options);
            if (!changed) {
                if (retuned.currentPane === 'session') renderSessionParentsRetuned();
                else updateRailCounts();
                return;
            }
            dashData.parents = list;
            if (selection.veterans && selection.veterans.length) {
                const byKey = new Map(list.map(parent => [parentKey(parent), parent]));
                selection.veterans = selection.veterans.map(parent => byKey.get(parentKey(parent)) || parent).filter(Boolean);
            }
            if (retuned.currentPane === 'parents') renderParentsRetuned(list);
            if (retuned.currentPane === 'session') renderSessionParentsRetuned();
            else updateRailCounts();
            renderTeamPanel();
            syncStartButton();
        }
        function favoriteBucket(type) {
            if (type === 'parents') return state.favorites.parents;
            if (type === 'borrowUmas') return state.favorites.borrowUmas;
            return state.favorites.trainees;
        }
        function favoriteKey(type, item) {
            if (type === 'parents') return parentKey(item);
            if (type === 'borrowUmas') {
                return String((item && (item._borrowKey || (item.viewer_id && (item.trained_chara_id || item.instance_id) ? `${item.viewer_id}:${item.trained_chara_id || item.instance_id}` : ''))) || '');
            }
            return traineeKey(item);
        }
        function isFavorite(type, item) {
            const key = favoriteKey(type, item);
            return Boolean(key && favoriteBucket(type)[key]);
        }
        function favoriteButtonHtml(type, item) {
            const key = favoriteKey(type, item);
            const active = isFavorite(type, item);
            const label = `${active ? 'Unfavorite' : 'Favorite'} ${item && item.name ? item.name : 'item'}`;
            return `<button type="button" class="favorite-toggle ${active ? 'is-active' : ''}" data-fav-type="${escapeAttr(type)}" data-fav-key="${escapeAttr(key)}" aria-label="${escapeAttr(label)}" title="${escapeAttr(label)}">★</button>`;
        }
        function visibleLibraryItems(items, type, query, fieldReaders) {
            return (items || []).map((item, index) => ({ item, index }))
                .filter(entry => matchesLibrarySearch(entry.item, query, fieldReaders))
                .sort((a, b) => {
                    const aFav = isFavorite(type, a.item) ? 1 : 0;
                    const bFav = isFavorite(type, b.item) ? 1 : 0;
                    return bFav - aFav || a.index - b.index;
                })
                .map(entry => ({ ...entry.item, _gridIdx: entry.index }));
        }
        function toggleFavorite(type, key) {
            if (!key || !['trainees', 'parents', 'borrowUmas'].includes(type)) return;
            const bucket = favoriteBucket(type);
            if (bucket[key]) delete bucket[key];
            else bucket[key] = 1;
            saveFavoriteState();
            if (type === 'trainees') {
                renderTrainees((dashData && dashData.umas) || []);
                attachSelectionHandlers();
            } else {
                if (type === 'borrowUmas') {
                    if (dashData && dashData.borrowUmas) renderBorrowUmasRetuned(dashData.borrowUmas);
                } else {
                    if (dashData && dashData.parents) renderParentsRetuned(dashData.parents);
                    renderSessionParentsRetuned();
                }
            }
            updateVetSelectability();
        }
        function attachFavoriteHandlers() {
            document.querySelectorAll('.favorite-toggle').forEach(button => {
                if (button.dataset.favoriteBound === '1') return;
                button.dataset.favoriteBound = '1';
                button.addEventListener('click', event => {
                    event.preventDefault();
                    event.stopPropagation();
                    toggleFavorite(button.dataset.favType, button.dataset.favKey);
                });
            });
        }
        function filterDecks(decks) {
            return (decks || []).filter(deck => matchesLibrarySearch(deck, state.librarySearch.decks, [
                item => item.name,
                item => item.id,
                item => (item.cards || []).map(card => `${card.id || ''} ${card.name || ''} ${card.rarity || ''} ${card.type || ''}`).join(' ')
            ]));
        }
        function filterSupports(supports) {
            return (supports || []).filter(card => matchesLibrarySearch(card, state.librarySearch.cards, [
                item => item.name,
                item => item.id,
                item => item.rarity,
                item => item.type
            ]));
        }
        function bindLibrarySearchHandlers() {
            if (bindLibrarySearchHandlers.bound) return;
            bindLibrarySearchHandlers.bound = true;
            const bindings = [
                [els.deckSearchInput, 'decks', () => { renderDecks((dashData && dashData.validDecks) || []); attachDeckHandlers(); }],
                [els.friendSearchInput, 'friends', () => renderFriends()],
                [els.cardBorrowSearchInput, 'cardBorrows', () => renderCardBorrows()],
                [els.teamTrialsSearchInput, 'teamTrials', () => renderTeamTrialsPlayers()],
                [els.traineeSearchInput, 'trainees', () => { renderTrainees((dashData && dashData.umas) || []); attachSelectionHandlers(); }],
                [els.parentSearchInput, 'parents', () => { renderParents((dashData && dashData.parents) || []); bindSparkTooltips(); attachSelectionHandlers(); updateVetSelectability(); }],
                [els.cardSearchInput, 'cards', () => renderSupports((dashData && dashData.supports) || [])]
            ];
            bindings.forEach(([input, key, render]) => {
                if (!input) return;
                input.value = state.librarySearch[key] || '';
                input.addEventListener('input', () => {
                    state.librarySearch[key] = input.value;
                    render();
                });
            });
        }
        function clampValue(value, min, max) {
            return Math.min(Math.max(value, min), max);
        }
        let activeSparkCard = null;
        let activeSparkTooltip = null;
        function positionSparkTooltip(card, tooltip = (card && card.querySelector ? card.querySelector('.sparks-tooltip') : null)) {
            if (!card || !tooltip || !card.isConnected) return;
            const rect = card.getBoundingClientRect();
            // Bail if the card has zero dimensions — happens when it's been re-rendered out
            // from under us. The next mouseover on the new card will reposition correctly.
            if (rect.width === 0 && rect.height === 0) return;
            const tooltipRect = tooltip.getBoundingClientRect();
            const tooltipWidth = Math.min(tooltipRect.width || 620, window.innerWidth - 16);
            const tooltipHeight = tooltipRect.height || 320;
            const x = clampValue(rect.left + rect.width / 2, tooltipWidth / 2 + 8, window.innerWidth - tooltipWidth / 2 - 8);
            const y = Math.max(8, rect.top - tooltipHeight - 10);
            tooltip.style.setProperty('--tooltip-left', `${x}px`);
            tooltip.style.setProperty('--tooltip-top', `${y}px`);
        }
        // Delegated tooltip handlers attached once at startup. Bind/rebind on grid re-render
        // would orphan closures whenever cards get replaced (which can happen mid-loop because
        // of borrow_quota polling) and the tooltip would end up positioned against a detached
        // 0,0,0,0 rect — visible at the top-left. Delegating to document keeps the handler
        // alive across all DOM mutations.
        document.addEventListener('mouseover', (event) => {
            const card = event.target.closest && event.target.closest('.grid-card');
            if (!card) return;
            if (!card.matches('#parent-grid .grid-card, #borrow-uma-grid .grid-card')) return;
            let tooltip = card.querySelector('.sparks-tooltip');
            if (!tooltip) tooltip = card._detachedSparksTooltip || null;
            if (!tooltip) return;
            // Hide any OTHER body-level tooltips that are still marked visible from a prior
            // hover that was cut short by a re-render (mouseout never fired on the now-detached
            // card). Without this, two tooltips can stack and both stay visible.
            document.querySelectorAll('body > .sparks-tooltip.is-visible').forEach(other => {
                if (other !== tooltip) other.classList.remove('is-visible');
            });
            if (tooltip.parentElement !== document.body) {
                document.body.appendChild(tooltip);
                card._detachedSparksTooltip = tooltip;
            }
            activeSparkCard = card;
            activeSparkTooltip = tooltip;
            positionSparkTooltip(card, tooltip);
            tooltip.classList.add('is-visible');
        });
        document.addEventListener('mouseout', (event) => {
            const card = event.target.closest && event.target.closest('.grid-card');
            if (!card) return;
            // Only fire hide when leaving the card to something outside it.
            if (event.relatedTarget && card.contains(event.relatedTarget)) return;
            if (activeSparkTooltip && activeSparkCard === card) {
                if (event.relatedTarget && activeSparkTooltip.contains(event.relatedTarget)) return;
                activeSparkTooltip.classList.remove('is-visible');
                activeSparkCard = null;
                activeSparkTooltip = null;
            }
        });
        function bindSparkTooltips() {
            // Re-renders detach old cards from the DOM; their body-appended tooltips become
            // orphans. Remove any body-level tooltip whose owner card is no longer in the
            // document, otherwise stale tooltips linger and overlap the next hover's tooltip.
            document.querySelectorAll('body > .sparks-tooltip').forEach(tooltip => {
                let stillOwned = false;
                document.querySelectorAll('#parent-grid .grid-card, #borrow-uma-grid .grid-card').forEach(card => {
                    if (card._detachedSparksTooltip === tooltip) stillOwned = true;
                });
                if (!stillOwned) {
                    tooltip.classList.remove('is-visible');
                    tooltip.remove();
                }
            });
            if (activeSparkTooltip && !activeSparkTooltip.isConnected) {
                activeSparkTooltip = null;
                activeSparkCard = null;
            }
            // Ensure every card with sparks data gets the .has-sparks marker so the CSS
            // hover styling applies. The delegated mouseover handler does the actual show.
            document.querySelectorAll('#parent-grid .grid-card, #borrow-uma-grid .grid-card').forEach(card => {
                if (card.querySelector('.sparks-tooltip') || card._detachedSparksTooltip) {
                    card.classList.add('has-sparks');
                }
            });
        }
        document.addEventListener('scroll', () => {
            if (activeSparkCard && activeSparkTooltip) positionSparkTooltip(activeSparkCard, activeSparkTooltip);
        }, true);
        window.addEventListener('resize', () => {
            if (activeSparkCard && activeSparkTooltip) positionSparkTooltip(activeSparkCard, activeSparkTooltip);
        });
        function friendKey(friend) {
            return `${friend.viewer_id}:${friend.support_card_id}`;
        }
        function friendViewerKey(friend) {
            return String((friend && friend.viewer_id) || '');
        }
        function normalizedCardName(value) {
            return String(value || '').toLowerCase().replace(/\([^)]*\)/g, '').replace(/[^a-z0-9]+/g, '');
        }
        function parseServerDate(value) {
            const raw = String(value || '').trim();
            if (!raw || raw.startsWith('0000-00-00')) return null;
            const normalized = raw.replace(' ', 'T');
            const parsed = new Date(normalized);
            if (!Number.isFinite(parsed.getTime())) return null;
            return parsed;
        }
        function formatRelativeTime(value) {
            const parsed = parseServerDate(value);
            if (!parsed) return 'Unknown';
            const diffMs = Date.now() - parsed.getTime();
            const diffMin = Math.max(0, Math.floor(diffMs / 60000));
            if (diffMin < 1) return 'just now';
            if (diffMin < 60) return `${diffMin}m ago`;
            const diffHr = Math.floor(diffMin / 60);
            if (diffHr < 24) return `${diffHr}h ago`;
            const diffDay = Math.floor(diffHr / 24);
            if (diffDay < 30) return `${diffDay}d ago`;
            return parsed.toLocaleDateString();
        }
        function formatLargeNumber(value) {
            const num = Number(value || 0);
            if (!Number.isFinite(num) || num <= 0) return '0';
            return num.toLocaleString();
        }
        function getFriendFollowQuota() {
            const quota = (dashData && dashData.friendFollowQuota) || {};
            const used = Math.max(0, Number(quota.used || 0) || 0);
            const max = Math.max(1, Number(quota.max || 20) || 20);
            return { used, max, remaining: Math.max(0, Number(quota.remaining || (max - used)) || 0) };
        }
        function renderFriendFollowQuota() {
            if (!els.friendFollowingQuota) return;
            const quota = getFriendFollowQuota();
            els.friendFollowingQuota.textContent = `Following ${quota.used}/${quota.max}`;
        }
        function friendAllowed(friend) {
            if (!friend) return false;
            const friendId = String(friend.support_card_id || '');
            const friendName = normalizedCardName(friend.support_name);
            if (selection.deck) {
                const deckIds = new Set(selection.deck.cards.map(card => String(card.id || '')));
                if (deckIds.has(friendId)) return false;
                const deckNames = new Set(selection.deck.cards.map(card => normalizedCardName(card.name)));
                if (friendName && deckNames.has(friendName)) return false;
            }
            if (selection.trainee && friendName && normalizedCardName(selection.trainee.name) === friendName) return false;
            return true;
        }
        function getVisibleFriendProfiles() {
            const rows = (dashData && dashData.friendsList) || [];
            return rows.filter(friend => matchesLibrarySearch(friend, state.librarySearch.friends, [
                item => item.name,
                item => item.comment,
                item => item.support_name,
                item => item.viewer_id,
                item => item.circle_name,
                item => item.leader_name
            ]));
        }
        function getVisibleCardBorrows() {
            const friends = (dashData && dashData.friends) || [];
            return friends
                .filter(friendAllowed)
                .filter(friend => matchesLibrarySearch(friend, state.librarySearch.cardBorrows, [
                    item => item.name,
                    item => item.support_name,
                    item => item.rarity,
                    item => item.type,
                    item => item.support_card_id,
                    item => item.viewer_id,
                    item => item.limit_break_count
                ]));
        }
        function clearInvalidFriendSelection() {
            if (selection.friend && !friendAllowed(selection.friend)) {
                selection.friend = null;
            }
        }
        function findSupportSelectionForProfile(profile) {
            if (!profile || !dashData) return null;
            const viewerId = String(profile.viewer_id || '');
            const supportCardId = String(profile.support_card_id || '');
            const supportRows = (dashData.friends || []);
            return supportRows.find(row =>
                String(row.viewer_id || '') === viewerId &&
                String(row.support_card_id || '') === supportCardId
            ) || null;
        }
        function isFriendProfileSelected(profile) {
            const selected = selection.friend;
            if (!selected || !profile) return false;
            return friendKey(selected) === friendKey(profile);
        }
        function isFriendProfileUsable(profile) {
            const support = findSupportSelectionForProfile(profile);
            return Boolean(support && friendAllowed(support));
        }
        function isFriendSupportSelected(friend) {
            const selected = selection.friend;
            if (!selected || !friend) return false;
            return friendKey(selected) === friendKey(friend);
        }
        function syncFriendSelection() {
            const visibleProfiles = (dashData && dashData.visibleFriendsList) || [];
            document.querySelectorAll('#friend-grid .friend-list-row').forEach((el, i) => {
                const friend = visibleProfiles[i];
                el.classList.toggle('selected', Boolean(selection.friend && friend && friendKey(selection.friend) === friendKey(friend)));
            });
        }
        function syncCardBorrowSelection() {
            const visibleSupports = (dashData && dashData.visibleCardBorrows) || [];
            document.querySelectorAll('#card-borrow-grid .friend-list-row').forEach((el, i) => {
                const friend = visibleSupports[i];
                const selected = isFriendSupportSelected(friend);
                el.classList.toggle('selected', selected);
                const button = el.querySelector('[data-action="use"]');
                if (button) button.textContent = selected ? 'SELECTED' : 'USE SUPPORT';
            });
        }
        function selectFriendSupport(friend) {
            if (!friend || !friendAllowed(friend)) return;
            selection.friend = isFriendSupportSelected(friend) ? null : friend;
            syncFriendSelection();
            syncCardBorrowSelection();
            renderTeamPanel();
            syncSelectionToServer();
        }
        function renderCardBorrows() {
            if (!els.cardBorrowGrid) return;
            clearInvalidFriendSelection();
            const supports = (dashData && dashData.friends) || [];
            const borrowableCount = supports.filter(friendAllowed).length;
            const visibleSupports = getVisibleCardBorrows();
            if (dashData) dashData.visibleCardBorrows = visibleSupports;
            els.cardBorrowGrid.innerHTML = visibleSupports.length ? visibleSupports.map(friend => {
                const imgId = friend.support_card_id || '10001';
                const selected = isFriendSupportSelected(friend);
                const trainerName = friend.name || `Viewer ${friend.viewer_id || '?'}`;
                return `<div class="friend-list-row ${selected ? 'selected' : ''}" data-friend-key="${escapeAttr(friendKey(friend))}">
                    <div class="friend-list-art">
                        <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    </div>
                    <div class="friend-list-main">
                        <div class="friend-list-name-row">
                            <span class="friend-list-name">${escapeHtml(friend.support_name || 'Unknown support')}</span>
                            <span class="friend-list-login">${escapeHtml(trainerName)}</span>
                        </div>
                        <div class="friend-list-meta">${escapeHtml(friend.rarity || '?')} / ${escapeHtml(friend.type || 'Unknown')} / LB${escapeHtml(String(friend.limit_break_count ?? '?'))} / Viewer ${escapeHtml(String(friend.viewer_id || ''))}</div>
                        <div class="friend-list-comment">Borrow support from ${escapeHtml(trainerName)}.</div>
                    </div>
                    <div class="friend-list-actions">
                        <button class="btn btn-sm friend-use-btn" type="button" data-action="use">${selected ? 'SELECTED' : 'USE SUPPORT'}</button>
                    </div>
                </div>`;
            }).join('') : '<div class="friend-list-empty">No friend support borrows match the current search.</div>';
            if (els.cardBorrowStatus) {
                if (!supports.length) {
                    els.cardBorrowStatus.textContent = 'No friend support borrows loaded yet.';
                } else if (!borrowableCount) {
                    els.cardBorrowStatus.textContent = 'No friend supports fit the current deck / trainee restrictions.';
                } else {
                    els.cardBorrowStatus.textContent = `Showing ${visibleSupports.length}/${borrowableCount} borrowable friend supports.`;
                }
            }
            attachCardBorrowHandlers();
            syncCardBorrowSelection();
            updateRailCounts();
        }
        function setFriendProfileStatus(message, isError = false) {
            if (!els.friendProfileStatus) return;
            els.friendProfileStatus.textContent = message || '';
            els.friendProfileStatus.classList.toggle('error', Boolean(isError));
        }
        function closeFriendProfile() {
            if (els.friendProfileModal) els.friendProfileModal.classList.remove('is-open');
            state.activeFriendProfile = null;
            setFriendProfileStatus('');
        }
        function renderFriendProfileModal(profile) {
            if (!els.friendProfileHero || !els.friendProfileBody || !profile) return;
            const supportCardId = Number(profile.support_card_id || 0);
            const leaderCardId = Number(profile.leader_card_id || 0);
            const supportImage = supportCardId > 0 ? `/api/images/${supportCardId}.png` : '/broom.png';
            const leaderImage = leaderCardId > 0 ? `/api/images/${leaderCardId}.png` : '/broom.png';
            const usable = isFriendProfileUsable(profile);
            const selected = isFriendProfileSelected(profile);
            els.friendProfileHero.innerHTML = `
                <div class="friend-profile-support-art">
                    <img src="${escapeAttr(supportImage)}" onerror="this.src='/broom.png'">
                </div>
                <div class="friend-profile-hero-copy">
                    <div class="friend-profile-name-row">
                        <span class="friend-profile-name">${escapeHtml(profile.name || `Trainer ${profile.viewer_id || '?'}`)}</span>
                        <span class="friend-profile-last-login">Last login ${escapeHtml(formatRelativeTime(profile.last_login_time))}</span>
                    </div>
                    <div class="friend-profile-meta-row">
                        <span class="friend-profile-meta-chip">Viewer ${escapeHtml(String(profile.viewer_id || ''))}</span>
                        <span class="friend-profile-meta-chip">${escapeHtml(profile.support_name || 'Unknown support')}</span>
                        <span class="friend-profile-meta-chip">LB${escapeHtml(String(profile.limit_break_count ?? '?'))}</span>
                    </div>
                    <div class="friend-profile-comment">${escapeHtml(profile.comment || 'No trainer comment.')}</div>
                </div>
            `;
            els.friendProfileBody.innerHTML = `
                <div class="friend-profile-detail-grid">
                    <div class="friend-profile-detail"><span>Circle</span><strong>${escapeHtml(profile.circle_name || 'None')}</strong></div>
                    <div class="friend-profile-detail"><span>Followed</span><strong>${escapeHtml(formatRelativeTime(profile.follow_time))}</strong></div>
                    <div class="friend-profile-detail"><span>Fans</span><strong>${escapeHtml(formatLargeNumber(profile.fan))}</strong></div>
                    <div class="friend-profile-detail"><span>Trainer Score</span><strong>${escapeHtml(formatLargeNumber(profile.rank_score))}</strong></div>
                    <div class="friend-profile-detail"><span>Stadium Wins</span><strong>${escapeHtml(formatLargeNumber(profile.team_stadium_win_count))}</strong></div>
                    <div class="friend-profile-detail"><span>Career Runs</span><strong>${escapeHtml(formatLargeNumber(profile.single_mode_play_count))}</strong></div>
                </div>
                <div class="friend-profile-section">
                    <div class="friend-profile-section-title">Star Umamusume</div>
                    <div class="friend-profile-leader-card">
                        <img class="friend-profile-leader-art" src="${escapeAttr(leaderImage)}" onerror="this.src='/broom.png'">
                        <div class="friend-profile-leader-copy">
                            <strong>${escapeHtml(profile.leader_name || 'Unknown')}</strong>
                            <span>Rank score ${escapeHtml(formatLargeNumber(profile.leader_rank_score))}</span>
                            <span>${escapeHtml(profile.leader_registered_at ? `Registered ${profile.leader_registered_at}` : 'Registration time unavailable')}</span>
                        </div>
                    </div>
                </div>
                <div class="friend-profile-section">
                    <div class="friend-profile-section-title">Career Support</div>
                    <div class="friend-profile-support-card">
                        <img class="friend-profile-support-thumb" src="${escapeAttr(supportImage)}" onerror="this.src='/broom.png'">
                        <div class="friend-profile-support-copy">
                            <strong>${escapeHtml(profile.support_name || 'Unknown support')}</strong>
                            <span>${escapeHtml(profile.support_rarity || '?')} ${escapeHtml(profile.support_type || 'Unknown')}</span>
                            <span>${usable ? (selected ? 'Currently selected for runs' : 'Available for current deck') : 'Unavailable for the current deck/trainee setup'}</span>
                        </div>
                    </div>
                </div>
            `;
            if (els.friendProfileUseBtn) {
                els.friendProfileUseBtn.disabled = !usable;
                els.friendProfileUseBtn.textContent = selected ? 'SELECTED' : 'USE SUPPORT';
            }
            if (els.friendProfileUnfollowBtn) {
                els.friendProfileUnfollowBtn.disabled = state.isUnfollowingFriend;
            }
            setFriendProfileStatus('');
        }
        function openFriendProfile(profile) {
            if (!profile || !els.friendProfileModal) return;
            state.activeFriendProfile = profile;
            renderFriendProfileModal(profile);
            els.friendProfileModal.classList.add('is-open');
        }
        function useFriendProfileSupport(profile) {
            const support = findSupportSelectionForProfile(profile);
            if (!support || !friendAllowed(support)) return;
            selection.friend = support;
            renderTeamPanel();
            syncStartButton();
            syncFriendSelection();
            syncCardBorrowSelection();
            renderFriends();
            renderFriendProfileModal(profile);
            syncSelectionToServer();
        }
        async function unfollowActiveFriend() {
            const profile = state.activeFriendProfile;
            if (!profile || state.isUnfollowingFriend) return;
            state.isUnfollowingFriend = true;
            if (els.friendProfileUnfollowBtn) els.friendProfileUnfollowBtn.disabled = true;
            setFriendProfileStatus(`Unfollowing ${profile.name || profile.viewer_id}...`);
            try {
                const data = await apiJson('/api/friends/unfollow', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ viewer_id: Number(profile.viewer_id || 0) })
                });
                if (!data.success) throw new Error(data.detail || 'Unfollow failed');
                dashData.friends = data.friends || [];
                dashData.friendsList = data.friends_list || [];
                dashData.friendFollowQuota = data.follow_quota || null;
                dashData.borrowUmas = data.borrow_umas || [];
                dashData.borrowQuota = data.borrow_quota || null;
                appendSeenFriendIds(data.exclude_viewer_ids || []);
                if (selection.friend && String(selection.friend.viewer_id || '') === String(profile.viewer_id || '')) {
                    selection.friend = null;
                }
                renderFriends();
                renderBorrowUmas(dashData.borrowUmas);
                attachBorrowUmaHandlers();
                bindSparkTooltips();
                renderTeamPanel();
                syncStartButton();
                syncSelectionToServer();
                updateRailCounts();
                if (els.friendStatus && data.detail) els.friendStatus.innerText = data.detail;
                closeFriendProfile();
            } catch (e) {
                setFriendProfileStatus(e.message || 'Unfollow failed.', true);
            } finally {
                state.isUnfollowingFriend = false;
                if (els.friendProfileUnfollowBtn) els.friendProfileUnfollowBtn.disabled = false;
            }
        }
        function bindFriendProfileModal() {
            if (els.friendProfileModal && els.friendProfileModal.dataset.bound !== '1') {
                els.friendProfileModal.dataset.bound = '1';
                els.friendProfileModal.addEventListener('click', event => {
                    if (event.target === els.friendProfileModal) closeFriendProfile();
                });
            }
            if (els.friendProfileCloseBtn && els.friendProfileCloseBtn.dataset.bound !== '1') {
                els.friendProfileCloseBtn.dataset.bound = '1';
                els.friendProfileCloseBtn.addEventListener('click', closeFriendProfile);
            }
            if (els.friendProfileCloseXBtn && els.friendProfileCloseXBtn.dataset.bound !== '1') {
                els.friendProfileCloseXBtn.dataset.bound = '1';
                els.friendProfileCloseXBtn.addEventListener('click', closeFriendProfile);
            }
            if (els.friendProfileUseBtn && els.friendProfileUseBtn.dataset.bound !== '1') {
                els.friendProfileUseBtn.dataset.bound = '1';
                els.friendProfileUseBtn.addEventListener('click', () => {
                    if (state.activeFriendProfile) useFriendProfileSupport(state.activeFriendProfile);
                });
            }
            if (els.friendProfileUnfollowBtn && els.friendProfileUnfollowBtn.dataset.bound !== '1') {
                els.friendProfileUnfollowBtn.dataset.bound = '1';
                els.friendProfileUnfollowBtn.addEventListener('click', unfollowActiveFriend);
            }
            if (!state.friendProfileEscBound) {
                state.friendProfileEscBound = true;
                document.addEventListener('keydown', event => {
                    if (event.key === 'Escape' && els.friendProfileModal?.classList.contains('is-open')) {
                        closeFriendProfile();
                    }
                });
            }
        }
        function normalizeRaceStyleValue(value) {
            const key = String(value || '')
                .toLowerCase()
                .replace(/[_-]+/g, ' ')
                .replace(/\s+/g, ' ')
                .trim();
            return RACE_STYLE_ALIAS_MAP[key] || '';
        }
        function raceStyleLabel(style) {
            return RACE_STYLE_LABELS[normalizeRaceStyleValue(style)] || '';
        }
        function raceStyleOptionsHtml(selectedStyle) {
            const normalized = normalizeRaceStyleValue(selectedStyle);
            return RACE_STYLE_OPTIONS.map(option => `<option value="${escapeAttr(option.value)}"${option.value === normalized ? ' selected' : ''}>${escapeHtml(option.label)}</option>`).join('');
        }
        function raceById(raceId) {
            const numericId = Number(raceId);
            if (Number.isNaN(numericId)) return null;
            return (state.raceData || []).find(r => Number(r.id) === numericId) || null;
        }
        function raceSortKey(race) {
            if (!race) return Number.MAX_SAFE_INTEGER;
            const parsed = _parseRaceDate(race.date || '');
            const yearOrder = { junior: 0, classic: 1, senior: 2 }[parsed.year] ?? 9;
            const turnOrder = RACE_TURN_LABELS.indexOf(parsed.turn);
            return (yearOrder * 100) + (turnOrder >= 0 ? turnOrder : 99);
        }
        function pruneRaceStyleMap(styleMap, picks = state.selectedRaces) {
            const keep = new Set(Array.from(picks || []).map(id => String(Number(id))).filter(id => id && id !== 'NaN'));
            const next = {};
            Object.entries(styleMap || {}).forEach(([raceId, style]) => {
                const normalizedId = String(Number(raceId));
                const normalizedStyle = normalizeRaceStyleValue(style);
                if (keep.has(normalizedId) && normalizedStyle) next[normalizedId] = normalizedStyle;
            });
            return next;
        }
        function setSelectedRaceStylesFromEntries(entries) {
            const next = {};
            (entries || []).forEach(entry => {
                const raceId = Number(entry && (entry.race_id ?? entry.id));
                const style = normalizeRaceStyleValue(entry && (entry.style || entry.tactic || entry.strategy));
                if (!Number.isNaN(raceId) && style) next[String(raceId)] = style;
            });
            state.selectedRaceStyles = pruneRaceStyleMap(next, state.selectedRaces);
        }
        function selectedRaceStylePayload(picks = state.selectedRaces, styles = state.selectedRaceStyles) {
            return pruneRaceStyleMap(styles, picks);
        }
        function selectedRaceEntries(picks = state.selectedRaces, styles = state.selectedRaceStyles) {
            return Array.from(picks || [])
                .map(id => raceById(id))
                .filter(Boolean)
                .map(race => ({
                    ...race,
                    selectedStyle: normalizeRaceStyleValue(styles && styles[String(Number(race.id))])
                }))
                .sort((a, b) => raceSortKey(a) - raceSortKey(b) || String(a.name || '').localeCompare(String(b.name || '')));
        }
        function defaultPresetName() {
            const list = Array.isArray(state.presets) ? state.presets : [];
            const first = list.find(p => p && p.name);
            return String((first && first.name) || '').trim();
        }
        function selectedPresetName() {
            return String(state.selectedPreset || '').trim() || defaultPresetName();
        }
        function persistSelectedPreset(name = selectedPresetName()) {
            state.selectedPreset = String(name || defaultPresetName()).trim();
            safeLocalSet('selectedPreset', state.selectedPreset);
            state.deckAdviceKey = '';
        }
        function findSelectedPreset(presets) {
            const list = Array.isArray(presets) ? presets : [];
            const selected = String(state.selectedPreset || '').trim();
            return (selected ? list.find(p => p && p.name === selected) : null)
                || list[0]
                || null;
        }
        function setTeamBundlePresetStatus(message, isError = false) {
            if (!els.teamBundlePresetStatus) return;
            els.teamBundlePresetStatus.textContent = message || "";
            els.teamBundlePresetStatus.classList.toggle('error', Boolean(isError));
        }
        function selectedTeamBundlePresetName() {
            return String(state.selectedTeamBundlePreset || '').trim();
        }
        function findTeamBundlePreset(name = selectedTeamBundlePresetName()) {
            const wanted = String(name || '').trim().toLowerCase();
            return (state.teamBundlePresets || []).find(p => String(p.name || '').trim().toLowerCase() === wanted) || null;
        }
        function setTeamBundleMenuOpen(open) {
            state.isTeamBundleMenuOpen = Boolean(open);
            if (els.teamBundlePopover) els.teamBundlePopover.hidden = !state.isTeamBundleMenuOpen;
            if (els.teamBundleToggleBtn) els.teamBundleToggleBtn.setAttribute('aria-expanded', state.isTeamBundleMenuOpen ? 'true' : 'false');
            if (els.teamBundleMenu) els.teamBundleMenu.classList.toggle('open', state.isTeamBundleMenuOpen);
        }
        function teamBundleSelectionIsComplete() {
            return Boolean(
                selection.deck &&
                selection.friend &&
                selection.trainee &&
                selection.veterans &&
                selection.veterans[0] &&
                (selection.veterans[1] || selection.guestParent)
            );
        }
        function defaultTeamBundlePresetName() {
            const parts = [
                selection.trainee && selection.trainee.name,
                selection.deck && selection.deck.name
            ].filter(Boolean);
            return parts.join(' / ') || selectedTeamBundlePresetName() || 'team bundle';
        }
        function compactSelectionForTeamBundle() {
            const deck = selection.deck ? {
                id: selection.deck.id,
                name: selection.deck.name
            } : null;
            const friend = selection.friend ? {
                viewer_id: selection.friend.viewer_id,
                support_card_id: selection.friend.support_card_id,
                name: selection.friend.name || selection.friend.trainer_name || '',
                support_name: selection.friend.support_name || selection.friend.card_name || ''
            } : null;
            const trainee = selection.trainee ? {
                id: selection.trainee.id,
                card_id: selection.trainee.card_id,
                name: selection.trainee.name
            } : null;
            const veterans = (selection.veterans || []).slice(0, 2).map(parent => ({
                instance_id: parent.instance_id,
                card_id: parent.card_id,
                chara_id: parent.chara_id,
                name: parent.name
            }));
            const guestParent = selection.guestParent ? {
                viewer_id: selection.guestParent.viewer_id,
                trained_chara_id: selection.guestParent.trained_chara_id,
                card_id: selection.guestParent.card_id,
                chara_id: selection.guestParent.chara_id,
                name: selection.guestParent.name || selection.guestParent.chara_name || ''
            } : null;
            return { deck, friend, trainee, veterans, guestParent };
        }
        function renderTeamBundlePresetControls() {
            if (!els.teamBundlePresetSelect) return;
            const presets = Array.isArray(state.teamBundlePresets) ? state.teamBundlePresets : [];
            const options = ['<option value="">No saved bundle</option>'].concat(
                presets.map(p => `<option value="${escapeAttr(p.name || '')}">${escapeHtml(p.name || 'Unnamed')}</option>`)
            );
            els.teamBundlePresetSelect.innerHTML = options.join('');
            const selected = findTeamBundlePreset(state.selectedTeamBundlePreset);
            state.selectedTeamBundlePreset = selected ? selected.name : '';
            els.teamBundlePresetSelect.value = state.selectedTeamBundlePreset;
            if (els.teamBundlePresetNameInput && !els.teamBundlePresetNameInput.value && state.selectedTeamBundlePreset) {
                els.teamBundlePresetNameInput.value = state.selectedTeamBundlePreset;
            }
            const hasSelection = Boolean(state.selectedTeamBundlePreset);
            if (els.teamBundlePresetApplyBtn) els.teamBundlePresetApplyBtn.disabled = !hasSelection || state.isSavingTeamBundlePreset;
            if (els.teamBundlePresetDeleteBtn) els.teamBundlePresetDeleteBtn.disabled = !hasSelection || state.isSavingTeamBundlePreset;
            if (els.teamBundlePresetSaveBtn) els.teamBundlePresetSaveBtn.disabled = state.isSavingTeamBundlePreset;
        }
        async function loadTeamBundlePresets() {
            if (!els.teamBundlePresetSelect) return;
            try {
                const data = await apiJson('/api/team_bundle/presets');
                if (!data.success) throw new Error(data.detail || 'Team bundle preset load failed');
                state.teamBundlePresets = data.presets || [];
                if (state.selectedTeamBundlePreset && !findTeamBundlePreset(state.selectedTeamBundlePreset)) {
                    state.selectedTeamBundlePreset = '';
                    safeLocalSet('selectedTeamBundlePreset', '');
                }
                renderTeamBundlePresetControls();
            } catch (e) {
                setTeamBundlePresetStatus(e.message || 'Team bundle preset load failed.', true);
            }
        }
        function currentTeamBundlePresetPayload(name) {
            return {
                name,
                selection: compactSelectionForTeamBundle()
            };
        }
        async function saveTeamBundlePreset() {
            if (!els.teamBundlePresetSaveBtn || state.isSavingTeamBundlePreset) return;
            if (!teamBundleSelectionIsComplete()) {
                setTeamBundlePresetStatus('Fill Deck, Friend, Trainee, P1 and P2 before saving.', true);
                return;
            }
            const rawName = (els.teamBundlePresetNameInput && els.teamBundlePresetNameInput.value.trim()) || selectedTeamBundlePresetName() || defaultTeamBundlePresetName();
            const name = rawName.trim();
            if (!name) {
                setTeamBundlePresetStatus('Name required.', true);
                return;
            }
            state.isSavingTeamBundlePreset = true;
            renderTeamBundlePresetControls();
            setTeamBundlePresetStatus('Saving team bundle...');
            try {
                const data = await apiJson('/api/team_bundle/presets', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name,
                        preset: currentTeamBundlePresetPayload(name)
                    })
                });
                if (!data.success) throw new Error(data.detail || 'Team bundle preset save failed');
                state.teamBundlePresets = data.presets || [];
                state.selectedTeamBundlePreset = data.preset && data.preset.name ? data.preset.name : name;
                safeLocalSet('selectedTeamBundlePreset', state.selectedTeamBundlePreset);
                if (els.teamBundlePresetNameInput) els.teamBundlePresetNameInput.value = state.selectedTeamBundlePreset;
                renderTeamBundlePresetControls();
                setTeamBundlePresetStatus(`Saved ${state.selectedTeamBundlePreset}.`);
            } catch (e) {
                setTeamBundlePresetStatus(e.message || 'Team bundle preset save failed.', true);
            } finally {
                state.isSavingTeamBundlePreset = false;
                renderTeamBundlePresetControls();
            }
        }
        function rerenderTeamBundleSelectionViews() {
            if (!dashData) return;
            renderDecks(dashData.validDecks || []);
            renderParents(dashData.parents || []);
            renderTrainees(dashData.umas || []);
            renderBorrowUmas(dashData.borrowUmas || []);
            renderFriends();
            attachSelectionHandlers();
            attachBorrowUmaHandlers();
            bindSparkTooltips();
            renderTeamPanel();
            syncStartButton();
        }
        function applyTeamBundlePresetObject(preset) {
            if (!preset) return false;
            resetSelection();
            selection.guestParent = null;
            applyServerSelection(preset.selection || {});
            rerenderTeamBundleSelectionViews();
            syncSelectionToServer();
            return true;
        }
        async function applySelectedTeamBundlePreset() {
            const preset = findTeamBundlePreset();
            if (!preset) {
                setTeamBundlePresetStatus('Select a team bundle preset.', true);
                return;
            }
            if (!applyTeamBundlePresetObject(preset)) return;
            setTeamBundlePresetStatus(`Applied ${preset.name}.`);
        }
        async function deleteSelectedTeamBundlePreset() {
            const name = selectedTeamBundlePresetName();
            if (!name || state.isSavingTeamBundlePreset) return;
            state.isSavingTeamBundlePreset = true;
            renderTeamBundlePresetControls();
            setTeamBundlePresetStatus('Deleting team bundle...');
            try {
                const data = await apiJson('/api/team_bundle/presets/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name })
                });
                if (!data.success) throw new Error(data.detail || 'Team bundle preset delete failed');
                state.teamBundlePresets = data.presets || [];
                state.selectedTeamBundlePreset = '';
                safeLocalSet('selectedTeamBundlePreset', '');
                if (els.teamBundlePresetNameInput) els.teamBundlePresetNameInput.value = '';
                renderTeamBundlePresetControls();
                setTeamBundlePresetStatus(`Deleted ${name}.`);
            } catch (e) {
                setTeamBundlePresetStatus(e.message || 'Team bundle preset delete failed.', true);
            } finally {
                state.isSavingTeamBundlePreset = false;
                renderTeamBundlePresetControls();
            }
        }
        function normalizeAlarmClockMode(value) {
            const mode = String(value || '').toLowerCase().replace(/[\s-]+/g, '_').trim();
            if (mode === 'none' || mode === 'off' || mode === 'disabled') return 'none';
            if (mode === 'carats' || mode === 'carat' || mode === 'with_carats' || mode === 'clock_carats') return 'carats';
            return 'normal';
        }
        function alarmClockModeFromPreset(preset) {
            if (!preset) return 'none';
            const explicit = normalizeAlarmClockMode(preset.alarm_clock_mode);
            const limit = Number(preset.clock_use_limit || 0);
            if (explicit === 'none' || limit <= 0) return 'none';
            return preset.clock_allow_carats ? 'carats' : explicit;
        }
        function alarmClockLimitFromPreset(preset) {
            const raw = Number((preset && (preset.alarm_clock_use_limit || preset.clock_use_limit)) || 0);
            if (!Number.isFinite(raw)) return 0;
            return Math.max(0, Math.min(5, Math.floor(raw)));
        }
        function renderAlarmClockControls() {
            if (els.alarmClockModeSelect) els.alarmClockModeSelect.value = normalizeAlarmClockMode(state.alarmClockMode);
            if (els.alarmClockLimitInput) els.alarmClockLimitInput.value = String(Math.max(0, Math.min(5, Number(state.alarmClockLimit || 0))));
        }
        function setAlarmClockStatus(message, isError = false) {
            if (!els.alarmClockStatus) return;
            els.alarmClockStatus.textContent = message || "";
            els.alarmClockStatus.classList.toggle('error', Boolean(isError));
        }
        function skillPlanCacheKey(presetName = selectedPresetName()) {
            return `sweepySkillPlan:${String(presetName || defaultPresetName()).trim() || 'default'}`;
        }
        // Read a value from a seg-group/hidden-select pair using whichever
        // source has user-visible authority. The seg-group's active button
        // is the source of truth — if it disagrees with the hidden select,
        // that's a desync from a re-render and the button wins. Falls back
        // to the hidden select when no group is bound.
        function readSegGroupValue(selectId) {
            const sel = document.getElementById(selectId);
            const group = document.querySelector(`.seg-group[data-seg-target="${selectId}"]`);
            if (group) {
                const active = group.querySelector('.seg-btn.active');
                if (active) {
                    const v = active.getAttribute('data-seg-value') || '';
                    // Sync the hidden select so any downstream code that
                    // reads it (state caches, etc.) gets the right value
                    if (sel && sel.value !== v) sel.value = v;
                    return v;
                }
            }
            return sel ? sel.value : "";
        }
        function syncSkillPlanInputsToState() {
            state.skillBuyOnSight = els.skillBuyInput ? els.skillBuyInput.value : "";
            state.skillBlacklist = els.skillBlacklistInput ? els.skillBlacklistInput.value : "";
            state.skillProfileStyle = readSegGroupValue('skill-style-select');
            state.skillProfileDistance = readSegGroupValue('skill-distance-select');
            state.skillBuyTiming = els.skillBuyTimingSelect ? els.skillBuyTimingSelect.value : "end_of_career";
            state.parentGoalBlue = els.parentGoalBlueInput ? els.parentGoalBlueInput.value : "";
            state.parentGoalPink = els.parentGoalPinkInput ? els.parentGoalPinkInput.value : "";
            state.parentGoalGreen = els.parentGoalGreenInput ? els.parentGoalGreenInput.value : "";
            state.parentGoalWhite = els.parentGoalWhiteInput ? els.parentGoalWhiteInput.value : "";
            state.alarmClockMode = normalizeAlarmClockMode(els.alarmClockModeSelect ? els.alarmClockModeSelect.value : state.alarmClockMode);
            state.alarmClockLimit = Math.max(0, Math.min(5, Number(els.alarmClockLimitInput ? els.alarmClockLimitInput.value : state.alarmClockLimit) || 0));
        }
        function syncRacePlannerInputsToState() {
            state.racePlanText = els.racePlanInput ? els.racePlanInput.value : state.racePlanText || "";
        }
        function skillPlanSnapshotFromState() {
            return {
                buy_on_sight: state.skillBuyOnSight || "",
                blacklist: state.skillBlacklist || "",
                style: state.skillProfileStyle || "",
                distance: state.skillProfileDistance || "",
                buy_timing: state.skillBuyTiming || "end_of_career",
                desired_sparks: {
                    blue: state.parentGoalBlue || "",
                    pink: state.parentGoalPink || "",
                    green: state.parentGoalGreen || "",
                    white: state.parentGoalWhite || ""
                },
                alarm_clock_mode: normalizeAlarmClockMode(state.alarmClockMode),
                alarm_clock_limit: Math.max(0, Math.min(5, Number(state.alarmClockLimit || 0)))
            };
        }
        function setPlannerProfileStatus(message, isError = false) {
            if (!els.plannerProfileStatus) return;
            els.plannerProfileStatus.textContent = message || "";
            els.plannerProfileStatus.classList.toggle('error', Boolean(isError));
        }
        function plannerProfilePayloadFromState(profileName = "") {
            syncSkillPlanInputsToState();
            syncRacePlannerInputsToState();
            const selectedEntries = selectedRaceEntries(state.selectedRaces, state.selectedRaceStyles);
            const schedulerEntries = selectedEntries
                .map(entry => ({
                    race_id: Number(entry && (entry.id ?? entry.race_id)),
                    style: normalizeRaceStyleValue(entry && (entry.selectedStyle || entry.style || entry.tactic || entry.strategy)),
                }))
                .filter(entry => Number.isFinite(entry.race_id) && entry.race_id > 0);
            const normalizedName = String(
                profileName
                || (els.plannerProfileNameInput ? els.plannerProfileNameInput.value : "")
                || state.selectedPlannerProfile
                || selectedPresetName()
            ).trim() || "planner_profile";
            return {
                schema: "sweepy_planner_profile_v1",
                name: normalizedName,
                saved_at: new Date().toISOString(),
                source_preset_name: selectedPresetName(),
                skill_plan: {
                    style: state.skillProfileStyle || "",
                    distance: state.skillProfileDistance || "",
                    buy_timing: state.skillBuyTiming || "end_of_career",
                    alarm_clock_mode: normalizeAlarmClockMode(state.alarmClockMode),
                    alarm_clock_limit: Math.max(0, Math.min(5, Number(state.alarmClockLimit || 0))),
                    final_priorities: String(state.skillBuyOnSight || "").replace(/,/g, '\n').split(/\r?\n/).map(v => v.trim()).filter(Boolean),
                    blacklist: String(state.skillBlacklist || "").replace(/,/g, '\n').split(/\r?\n/).map(v => v.trim()).filter(Boolean),
                    desired_sparks: {
                        blue: state.parentGoalBlue || "",
                        pink: state.parentGoalPink || "",
                        green: state.parentGoalGreen || "",
                        white: state.parentGoalWhite || ""
                    }
                },
                race_scheduler: {
                    race_plan_text: state.racePlanText || "",
                    selected_race_ids: Array.from(state.selectedRaces || []).map(id => Number(id)).filter(id => Number.isFinite(id) && id > 0),
                    race_styles: selectedRaceStylePayload(),
                    custom_race_schedule: schedulerEntries
                }
            };
        }
        function syncPlannerProfileControls() {
            if (els.plannerProfileSelect) {
                const current = String(state.selectedPlannerProfile || "").trim();
                els.plannerProfileSelect.value = current;
            }
            if (els.plannerProfileNameInput) {
                const selected = String(state.selectedPlannerProfile || "").trim();
                if (selected && !String(els.plannerProfileNameInput.value || "").trim()) {
                    els.plannerProfileNameInput.value = selected;
                }
            }
        }
        function renderPlannerProfileOptions(profiles = state.plannerProfiles) {
            if (!els.plannerProfileSelect) return;
            const options = Array.isArray(profiles) ? profiles : [];
            const current = String(state.selectedPlannerProfile || "").trim();
            els.plannerProfileSelect.innerHTML = '';
            const currentOption = document.createElement('option');
            currentOption.value = '';
            currentOption.textContent = 'Current UI state';
            els.plannerProfileSelect.appendChild(currentOption);
            options.forEach(profile => {
                const name = String((profile && profile.name) || '').trim();
                if (!name) return;
                const savedAt = String((profile && profile.saved_at) || '').trim();
                const source = String((profile && profile.source_preset_name) || '').trim();
                const meta = [source, savedAt].filter(Boolean).join(' · ');
                const option = document.createElement('option');
                option.value = name;
                option.textContent = meta ? `${name} — ${meta}` : name;
                els.plannerProfileSelect.appendChild(option);
            });
            els.plannerProfileSelect.value = current;
        }
        async function loadPlannerProfiles(preferredName = "") {
            try {
                const data = await apiJson('/api/planner_profiles');
                if (!data.success) throw new Error(data.detail || 'Planner profile load failed');
                state.plannerProfiles = Array.isArray(data.profiles) ? data.profiles : [];
                let selected = String(preferredName || state.selectedPlannerProfile || "").trim();
                if (selected && !state.plannerProfiles.some(profile => String((profile && profile.name) || '').trim() === selected)) {
                    selected = "";
                }
                state.selectedPlannerProfile = selected;
                safeLocalSet('selectedPlannerProfile', selected);
                renderPlannerProfileOptions();
                syncPlannerProfileControls();
            } catch (e) {
                setPlannerProfileStatus(e.message || "Planner profile load failed.", true);
            }
        }
        function cacheSkillPlanSnapshot(presetName = selectedPresetName()) {
            const name = String(presetName || selectedPresetName()).trim() || 'default';
            persistSelectedPreset(name);
            try {
                localStorage.setItem(skillPlanCacheKey(name), JSON.stringify({
                    schema: 'sweepy_skill_plan_cache_v1',
                    preset_name: name,
                    saved_at: Date.now(),
                    plan: skillPlanSnapshotFromState()
                }));
            } catch (e) {}
        }
        function loadCachedSkillPlanSnapshot(presetName = selectedPresetName()) {
            try {
                const parsed = JSON.parse(localStorage.getItem(skillPlanCacheKey(presetName)) || 'null');
                return parsed && parsed.plan && typeof parsed.plan === 'object' ? parsed.plan : null;
            } catch (e) {
                return null;
            }
        }
        function applyCachedSkillPlanSnapshot(plan) {
            if (!plan || typeof plan !== 'object') return false;
            state.skillBuyOnSight = String(plan.buy_on_sight || "");
            state.skillBlacklist = String(plan.blacklist || "");
            state.skillProfileStyle = String(plan.style || "");
            state.skillProfileDistance = String(plan.distance || "");
            state.skillBuyTiming = String(plan.buy_timing || "end_of_career");
            const goals = plan.desired_sparks || {};
            state.parentGoalBlue = String(goals.blue || "");
            state.parentGoalPink = String(goals.pink || "");
            state.parentGoalGreen = String(goals.green || "");
            state.parentGoalWhite = String(goals.white || "");
            state.alarmClockMode = normalizeAlarmClockMode(plan.alarm_clock_mode);
            state.alarmClockLimit = Math.max(0, Math.min(5, Number(plan.alarm_clock_limit || 0)));
            return true;
        }
        async function loadRaceData() {
            try {
                const raceRes = await fetch('/assets/data/uma_race_data.json');
                const data = await raceRes.json();
                state.raceData = Array.isArray(data.races) ? data.races : [];
                
                const presetRes = await apiJson('/api/presets');
                if (presetRes.success) {
                    state.presets = presetRes.presets || [];
                    const activePreset = findSelectedPreset(state.presets);
                    if (activePreset && activePreset.name) persistSelectedPreset(activePreset.name);
                    if (activePreset && activePreset.extra_race_list) {
                        state.selectedRaces = new Set(activePreset.extra_race_list.map(id => parseInt(id)));
                    }
                    if (activePreset) {
                        if (!state.selectedRaces.size && Array.isArray(activePreset.custom_race_schedule)) {
                            state.selectedRaces = new Set(activePreset.custom_race_schedule.map(entry => parseInt(entry.race_id, 10)).filter(id => !Number.isNaN(id)));
                        }
                        setSelectedRaceStylesFromEntries(activePreset.custom_race_schedule || []);
                        state.racePlanText = String(activePreset.race_plan_text || "");
                        renderRacePlanControls();
                        state.skillBuyOnSight = Array.isArray(activePreset.skill_buy_on_sight) ? activePreset.skill_buy_on_sight.join('\n') : String(activePreset.skill_buy_on_sight || "");
                        const blacklist = activePreset.skill_blacklist_custom || activePreset.learn_skill_blacklist || [];
                        state.skillBlacklist = Array.isArray(blacklist) ? blacklist.join('\n') : String(blacklist || "");
                        state.skillProfileStyle = String(activePreset.skill_profile_style || "");
                        state.skillProfileDistance = String(activePreset.skill_profile_distance || "");
                        state.skillBuyTiming = activePreset.manual_purchase_at_end === false ? "throughout" : "end_of_career";
                        const goals = activePreset.desired_parent_sparks || {};
                        const goalText = key => Array.isArray(goals[key]) ? goals[key].join('\n') : String(goals[key] || "");
                        state.parentGoalBlue = goalText('blue');
                        state.parentGoalPink = goalText('pink');
                        state.parentGoalGreen = goalText('green');
                        state.parentGoalWhite = goalText('white');
                        state.alarmClockMode = alarmClockModeFromPreset(activePreset);
                        state.alarmClockLimit = alarmClockLimitFromPreset(activePreset);
                        state.deckAdviceKey = '';
                        renderSkillPlanControls();
                        renderAlarmClockControls();
                        cacheSkillPlanSnapshot(activePreset.name || selectedPresetName());
                    } else if (applyCachedSkillPlanSnapshot(loadCachedSkillPlanSnapshot(selectedPresetName()))) {
                        state.deckAdviceKey = '';
                        renderSkillPlanControls();
                        renderAlarmClockControls();
                    }
                    if (activePreset && activePreset.allow_recover_tp != null) {
                        state.tpRecoveryMode = normalizeTpRecoveryMode(activePreset.allow_recover_tp);
                        syncStartButton();
                    }
                }
                renderRaces();
                loadDeckAdvice(true);
            } catch (e) {
                console.error("Failed to load race data", e);
            }
        }

        function renderRacePlanControls() {
            if (els.racePlanInput) els.racePlanInput.value = state.racePlanText || "";
        }

        function setRacePlanStatus(message, isError = false) {
            if (!els.racePlanStatus) return;
            els.racePlanStatus.textContent = message || "";
            els.racePlanStatus.classList.toggle('error', Boolean(isError));
        }

        function renderSkillPlanControls() {
            if (els.skillBuyInput) els.skillBuyInput.value = state.skillBuyOnSight || "";
            if (els.skillBlacklistInput) els.skillBlacklistInput.value = state.skillBlacklist || "";
            if (els.skillStyleSelect) els.skillStyleSelect.value = state.skillProfileStyle || "";
            if (els.skillDistanceSelect) els.skillDistanceSelect.value = state.skillProfileDistance || "";
            if (els.skillBuyTimingSelect) els.skillBuyTimingSelect.value = state.skillBuyTiming || "end_of_career";
            if (els.parentGoalBlueInput) els.parentGoalBlueInput.value = state.parentGoalBlue || "";
            if (els.parentGoalPinkInput) els.parentGoalPinkInput.value = state.parentGoalPink || "";
            if (els.parentGoalGreenInput) els.parentGoalGreenInput.value = state.parentGoalGreen || "";
            if (els.parentGoalWhiteInput) els.parentGoalWhiteInput.value = state.parentGoalWhite || "";
        }

        function setSkillPlanStatus(message, isError = false) {
            if (!els.skillPlanStatus) return;
            els.skillPlanStatus.textContent = message || "";
            els.skillPlanStatus.classList.toggle('error', Boolean(isError));
        }

        async function savePlannerProfile() {
            if (!els.plannerProfileSaveBtn) return;
            const requestedName = String(
                (els.plannerProfileNameInput ? els.plannerProfileNameInput.value : "")
                || state.selectedPlannerProfile
                || selectedPresetName()
            ).trim();
            if (!requestedName) {
                setPlannerProfileStatus("Enter a profile name before saving.", true);
                return;
            }
            const profile = plannerProfilePayloadFromState(requestedName);
            setPlannerProfileStatus("Saving planner profile...");
            els.plannerProfileSaveBtn.disabled = true;
            try {
                const data = await apiJson('/api/planner_profiles/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        preset_name: selectedPresetName(),
                        profile_name: requestedName,
                        profile
                    })
                });
                if (!data.success) throw new Error(data.detail || 'Planner profile save failed');
                const savedName = String((data.profile && data.profile.name) || requestedName).trim();
                state.selectedPlannerProfile = savedName;
                safeLocalSet('selectedPlannerProfile', savedName);
                if (els.plannerProfileNameInput) els.plannerProfileNameInput.value = savedName;
                if (Array.isArray(data.profiles)) {
                    state.plannerProfiles = data.profiles;
                    renderPlannerProfileOptions();
                    syncPlannerProfileControls();
                } else {
                    await loadPlannerProfiles(savedName);
                }
                setPlannerProfileStatus(`Saved planner profile ${savedName}.`);
            } catch (e) {
                setPlannerProfileStatus(e.message || "Planner profile save failed.", true);
            } finally {
                els.plannerProfileSaveBtn.disabled = false;
            }
        }

        async function loadPlannerProfile() {
            if (!els.plannerProfileLoadBtn) return;
            const selectedName = String(
                (els.plannerProfileSelect ? els.plannerProfileSelect.value : "")
                || state.selectedPlannerProfile
            ).trim();
            if (!selectedName) {
                setPlannerProfileStatus("Choose a saved planner profile to load.", true);
                return;
            }
            setPlannerProfileStatus(`Loading planner profile ${selectedName}...`);
            els.plannerProfileLoadBtn.disabled = true;
            try {
                const data = await apiJson('/api/planner_profiles/load', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        preset_name: selectedPresetName(),
                        profile_name: selectedName
                    })
                });
                if (!data.success) throw new Error(data.detail || 'Planner profile load failed');
                state.selectedPlannerProfile = String((data.profile && data.profile.name) || selectedName).trim();
                safeLocalSet('selectedPlannerProfile', state.selectedPlannerProfile);
                if (els.plannerProfileNameInput) els.plannerProfileNameInput.value = state.selectedPlannerProfile;
                await loadRaceData();
                await loadPlannerProfiles(state.selectedPlannerProfile);
                setPlannerProfileStatus(`Loaded planner profile ${state.selectedPlannerProfile} into ${selectedPresetName()}.`);
            } catch (e) {
                setPlannerProfileStatus(e.message || "Planner profile load failed.", true);
            } finally {
                els.plannerProfileLoadBtn.disabled = false;
            }
        }

        function exportPlannerProfile() {
            const profile = plannerProfilePayloadFromState();
            const filename = `${browserSlugify(profile.name || selectedPresetName())}.json`;
            downloadTextFile(filename, JSON.stringify(profile, null, 2));
            setPlannerProfileStatus(`Exported ${filename}.`);
        }

        async function importPlannerProfileFile(event) {
            const file = event.target.files && event.target.files[0];
            if (!file) return;
            setPlannerProfileStatus(`Importing ${file.name}...`);
            try {
                const text = await file.text();
                const parsed = JSON.parse(text);
                const importedName = String((parsed && parsed.name) || file.name.replace(/\.json$/i, '') || 'planner_profile').trim() || 'planner_profile';
                const saveResult = await apiJson('/api/planner_profiles/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        preset_name: selectedPresetName(),
                        profile_name: importedName,
                        profile: parsed
                    })
                });
                if (!saveResult.success) throw new Error(saveResult.detail || 'Planner profile import save failed');
                const loadResult = await apiJson('/api/planner_profiles/load', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        preset_name: selectedPresetName(),
                        profile_name: importedName,
                        profile: parsed
                    })
                });
                if (!loadResult.success) throw new Error(loadResult.detail || 'Planner profile import load failed');
                state.selectedPlannerProfile = String((loadResult.profile && loadResult.profile.name) || importedName).trim();
                safeLocalSet('selectedPlannerProfile', state.selectedPlannerProfile);
                if (els.plannerProfileNameInput) els.plannerProfileNameInput.value = state.selectedPlannerProfile;
                await loadRaceData();
                await loadPlannerProfiles(state.selectedPlannerProfile);
                setPlannerProfileStatus(`Imported and loaded planner profile ${state.selectedPlannerProfile}.`);
            } catch (e) {
                setPlannerProfileStatus(e.message || "Planner profile import failed.", true);
            } finally {
                event.target.value = "";
            }
        }

        async function saveSkillPlan() {
            if (!els.skillPlanSaveBtn) return;
            syncSkillPlanInputsToState();
            setSkillPlanStatus("Saving skill plan...");
            els.skillPlanSaveBtn.disabled = true;
            try {
                const data = await apiJson('/api/presets/save_skill_plan', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        preset_name: selectedPresetName(),
                        buy_on_sight: state.skillBuyOnSight,
                        blacklist: state.skillBlacklist,
                        style: state.skillProfileStyle,
                        distance: state.skillProfileDistance,
                        buy_timing: state.skillBuyTiming,
                        desired_sparks: {
                            blue: state.parentGoalBlue,
                            pink: state.parentGoalPink,
                            green: state.parentGoalGreen,
                            white: state.parentGoalWhite
                        },
                        alarm_clock_mode: state.alarmClockMode,
                        alarm_clock_limit: state.alarmClockLimit
                    })
                });
                if (!data.success) throw new Error(data.detail || 'Skill plan save failed');
                const splitSkills = value => String(value || '').replace(/,/g, '\n').split(/\r?\n/).map(v => v.trim()).filter(Boolean);
                const buyCount = splitSkills(state.skillBuyOnSight).length;
                const totalCount = (data.rows || []).reduce((count, row) => count + (Array.isArray(row) ? row.length : 0), 0);
                const profileCount = Math.max(0, totalCount - buyCount);
                cacheSkillPlanSnapshot(selectedPresetName());
                renderAlarmClockControls();
                setAlarmClockStatus("Alarm-clock settings saved.");
                setSkillPlanStatus(`Saved ${buyCount} final-priority and ${profileCount} profile skills. Alarm clocks: ${state.alarmClockMode}, max ${state.alarmClockLimit}/career.`);
            } catch (e) {
                setSkillPlanStatus(e.message || "Skill plan save failed.", true);
            } finally {
                els.skillPlanSaveBtn.disabled = false;
            }
        }

        async function saveAlarmClockSettings() {
            if (!els.alarmClockSaveBtn) return;
            state.alarmClockMode = normalizeAlarmClockMode(els.alarmClockModeSelect ? els.alarmClockModeSelect.value : state.alarmClockMode);
            state.alarmClockLimit = Math.max(0, Math.min(5, Number(els.alarmClockLimitInput ? els.alarmClockLimitInput.value : state.alarmClockLimit) || 0));
            setAlarmClockStatus("Saving alarm-clock settings...");
            els.alarmClockSaveBtn.disabled = true;
            try {
                const data = await apiJson('/api/presets/save_race_continue', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        preset_name: selectedPresetName(),
                        mode: state.alarmClockMode,
                        limit: state.alarmClockLimit
                    })
                });
                if (!data.success) throw new Error(data.detail || 'Alarm-clock save failed');
                state.alarmClockMode = data.mode || state.alarmClockMode;
                state.alarmClockLimit = Number(data.limit || 0);
                cacheSkillPlanSnapshot(selectedPresetName());
                renderAlarmClockControls();
                const label = state.alarmClockMode === 'none'
                    ? 'disabled'
                    : state.alarmClockMode === 'carats'
                        ? `normal clocks + carat exchange, max ${state.alarmClockLimit}/career`
                        : `normal clocks only, max ${state.alarmClockLimit}/career`;
                setAlarmClockStatus(`Saved: ${label}.`);
            } catch (e) {
                setAlarmClockStatus(e.message || "Alarm-clock save failed.", true);
            } finally {
                els.alarmClockSaveBtn.disabled = false;
            }
        }

        function getYearSlots(yearIdx) {
            const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
            const periods = ['Early', 'Late'];
            const yearLabels = ['Junior Year', 'Classic Year', 'Senior Year'];
            const slots = [];
            for (const month of months) {
                for (const period of periods) {
                    const label = period + ' ' + month;
                    const datePrefix = yearLabels[yearIdx] + ' ' + label;
                    const races = state.raceData.filter(r => r.date.includes(datePrefix));
                    slots.push({ period: label, races: races, yearIdx: yearIdx });
                }
            }
            return slots;
        }

        function renderRaces() {
            if (!els.raceOptionsContent) return;
            els.raceOptionsContent.innerHTML = '';
            
            const yearLabels = ['Junior Year', 'Classic Year', 'Senior Year'];
            yearLabels.forEach((label, yi) => {
                const block = document.createElement('div');
                block.className = 'race-year-block';
                block.innerHTML = `<div class="race-year-title">${label}</div>`;
                
                const grid = document.createElement('div');
                grid.className = 'race-time-grid';
                
                const slots = getYearSlots(yi);
                slots.forEach((slot, si) => {
                    const cell = document.createElement('div');
                    cell.className = 'race-time-cell';
                    const selected = slot.races.find(r => state.selectedRaces.has(r.id));
                    const selectedStyle = selected ? normalizeRaceStyleValue(state.selectedRaceStyles[String(Number(selected.id))]) : '';
                    
                    let html = `<div class="race-time-label">${slot.period}</div>`;
                    if (selected) {
                        html += `
                            <div class="race-cell-selected-img">
                                <img src="/races/${encodeURIComponent(selected.name)}.png" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex'">
                                <div class="race-image-fallback" style="display:none">${selected.type}</div>
                                <span class="race-cell-selected-grade badge-${selected.type.toLowerCase().replace('-', '')}">${selected.type}</span>
                            </div>
                            <div class="race-cell-selected-name">${escapeHtml(selected.name)}</div>
                            ${selectedStyle ? `<div class="race-cell-selected-style">${escapeHtml(raceStyleLabel(selectedStyle))}</div>` : ''}
                        `;
                    } else {
                        html += `<div class="race-time-plus">+</div>`;
                    }
                    
                    cell.innerHTML = html;
                    cell.onclick = () => openSlotPopup(slot, yi);
                    grid.appendChild(cell);
                });
                
                block.appendChild(grid);
                els.raceOptionsContent.appendChild(block);
            });
        }

        function openSlotPopup(slot, yearIdx) {
            const yearLabels = ['Junior Year', 'Classic Year', 'Senior Year'];
            els.racePopupTitle.textContent = `${yearLabels[yearIdx]} - ${slot.period}`;
            els.racePopupBody.innerHTML = '';
            
            if (slot.races.length === 0) {
                els.racePopupBody.innerHTML = '<div class="race-slot-popup-empty">No races available</div>';
            } else {
                const list = document.createElement('div');
                list.className = 'race-slot-popup-list';
                slot.races.forEach(race => {
                    const item = document.createElement('div');
                    item.className = `race-slot-popup-item ${state.selectedRaces.has(race.id) ? 'on' : ''}`;
                    item.innerHTML = `
                        <div class="race-slot-popup-img">
                            <img src="/races/${encodeURIComponent(race.name)}.png" onerror="this.src='/broom.png'">
                        </div>
                        <div class="race-slot-popup-info">
                            <div class="race-slot-popup-name-row">
                                <span class="race-slot-popup-grade badge-${race.type.toLowerCase().replace('-', '')}">${race.type}</span>
                                <span class="race-slot-popup-name">${escapeHtml(race.name)}</span>
                            </div>
                            <div class="race-slot-popup-meta">
                                <span class="race-slot-popup-terrain ${race.terrain.toLowerCase()}">${race.terrain}</span>
                                <span class="race-slot-popup-distance">${race.distance}</span>
                            </div>
                        </div>
                        <div class="race-slot-popup-check">✓</div>
                    `;
                    item.onclick = async () => {
                        const slotIds = slot.races.map(r => r.id);
                        if (state.selectedRaces.has(race.id)) {
                            state.selectedRaces.delete(race.id);
                            delete state.selectedRaceStyles[String(Number(race.id))];
                        } else {
                            slotIds.forEach(id => {
                                state.selectedRaces.delete(id);
                                delete state.selectedRaceStyles[String(Number(id))];
                            });
                            state.selectedRaces.add(race.id);
                        }
                        state.racePlanText = "";
                        if (els.racePlanInput) els.racePlanInput.value = "";
                        openSlotPopup(slot, yearIdx);
                        renderRaces();
                        await autoSaveRaces();
                        setRacePlanStatus("Manual race picker saved; custom JSON plan cleared.");
                    };
                    list.appendChild(item);
                });
                els.racePopupBody.appendChild(list);
            }
            els.racePopupOverlay.style.display = 'flex';
        }

        async function autoSaveRaces() {
            try {
                await apiJson('/api/presets/save_races', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        preset_name: selectedPresetName(),
                        races: Array.from(state.selectedRaces),
                        ...currentRacePlanPayload()
                    })
                });
            } catch (e) {
                console.error("Auto-save failed:", e);
            }
        }

        function currentRacePlanPayload() {
            return {
                styles: selectedRaceStylePayload()
            };
        }

        function formatRacePlanErrors(errors) {
            return (errors || []).slice(0, 4).map(err => {
                const line = err.line ? `line ${err.line}: ` : "";
                return `${line}${err.error || "invalid race"}`;
            }).join(" | ");
        }

        async function saveRacePlan() {
            if (!els.racePlanInput || !els.racePlanSaveBtn) return;
            const text = els.racePlanInput.value.trim();
            if (!text) {
                setRacePlanStatus("Paste JSON or race lines before importing.", true);
                return;
            }
            state.racePlanText = text;
            setRacePlanStatus("Parsing race plan...");
            els.racePlanSaveBtn.disabled = true;
            try {
                const data = await apiJson('/api/presets/save_race_plan', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        preset_name: selectedPresetName(),
                        text,
                        ...currentRacePlanPayload()
                    })
                });
                if (!data.success) {
                    setRacePlanStatus(formatRacePlanErrors(data.errors) || data.detail || "Race plan import failed.", true);
                    return;
                }
                state.selectedRaces = new Set((data.race_ids || []).map(id => parseInt(id, 10)));
                setSelectedRaceStylesFromEntries(data.entries || []);
                renderRaces();
                if (retuned.calendarOpen) {
                    hydrateRaceCalendarDraftFromSaved();
                    populateRaceCalendarGrid();
                    setRaceCalendarStatus(`Imported ${(data.entries || []).length} scheduled race${(data.entries || []).length === 1 ? '' : 's'} into the agenda planner.`);
                }
                const count = (data.entries || []).length;
                setRacePlanStatus(`Imported ${count} scheduled races. Stamina rescue checks run 5 turns before matching races.`);
            } catch (e) {
                setRacePlanStatus("Race plan import failed.", true);
            } finally {
                els.racePlanSaveBtn.disabled = false;
            }
        }

        async function loadRacePlanFile(event) {
            const file = event.target.files && event.target.files[0];
            if (!file || !els.racePlanInput) return;
            try {
                const text = await file.text();
                state.racePlanText = text;
                els.racePlanInput.value = text;
                setRacePlanStatus(`Loaded ${file.name}; click IMPORT PLAN to save it.`);
            } catch (e) {
                setRacePlanStatus("Could not read race plan file.", true);
            } finally {
                event.target.value = "";
            }
        }

        function getTurnFromDate(dateStr) {
            const match = dateStr.match(/(\d+)年(\d+)月(前|後)半/);
            if (!match) return 0;
            const year = parseInt(match[1]);
            const month = parseInt(match[2]);
            const half = match[3] === '前' ? 0 : 1;
            return (year - 1) * 24 + (month - 1) * 2 + half + 1;
        }

        function bindRaceHandlers() {
            if (bindRaceHandlers.bound) return;
            bindRaceHandlers.bound = true;
            els.racePopupClose?.addEventListener('click', () => {
                els.racePopupOverlay.style.display = 'none';
            });
            els.racePopupOverlay?.addEventListener('click', (e) => {
                if (e.target === els.racePopupOverlay) els.racePopupOverlay.style.display = 'none';
            });
            els.racePlanSaveBtn?.addEventListener('click', saveRacePlan);
            els.racePlanFile?.addEventListener('change', loadRacePlanFile);
        }

        function bindSkillHandlers() {
            if (bindSkillHandlers.bound) return;
            bindSkillHandlers.bound = true;
            els.skillPlanSaveBtn?.addEventListener('click', saveSkillPlan);
            els.plannerProfileSaveBtn?.addEventListener('click', savePlannerProfile);
            els.plannerProfileLoadBtn?.addEventListener('click', loadPlannerProfile);
            els.plannerProfileExportBtn?.addEventListener('click', exportPlannerProfile);
            els.plannerProfileFile?.addEventListener('change', importPlannerProfileFile);
            els.plannerProfileSelect?.addEventListener('change', () => {
                state.selectedPlannerProfile = String(els.plannerProfileSelect.value || '').trim();
                safeLocalSet('selectedPlannerProfile', state.selectedPlannerProfile);
                if (els.plannerProfileNameInput && state.selectedPlannerProfile) {
                    els.plannerProfileNameInput.value = state.selectedPlannerProfile;
                }
            });
            els.skillBuyInput?.addEventListener('input', () => {
                state.skillBuyOnSight = els.skillBuyInput.value;
            });
            els.skillBlacklistInput?.addEventListener('input', () => {
                state.skillBlacklist = els.skillBlacklistInput.value;
            });
            els.skillStyleSelect?.addEventListener('change', () => {
                state.skillProfileStyle = els.skillStyleSelect.value;
            });
            els.skillDistanceSelect?.addEventListener('change', () => {
                state.skillProfileDistance = els.skillDistanceSelect.value;
            });
            els.alarmClockModeSelect?.addEventListener('change', () => {
                state.alarmClockMode = normalizeAlarmClockMode(els.alarmClockModeSelect.value);
            });
            els.alarmClockLimitInput?.addEventListener('input', () => {
                state.alarmClockLimit = Math.max(0, Math.min(5, Number(els.alarmClockLimitInput.value) || 0));
            });
            els.alarmClockSaveBtn?.addEventListener('click', saveAlarmClockSettings);
            makeSectionToggle('skills-toggle', 'skills-chevron', 'skills-body', false);
        }

        async function loadPresets() {
            syncStartButton();
            await loadRaceData();
            await loadPlannerProfiles();
        }

        function renderFriends() {
            const friends = (dashData && dashData.friendsList) || [];
            clearInvalidFriendSelection();
            const visibleFriends = getVisibleFriendProfiles();
            if (dashData) dashData.visibleFriendsList = visibleFriends;

            if (state.pendingFriendSelection) {
                const f = ((dashData && dashData.friends) || []).find(v => 
                    String(v.viewer_id) === state.pendingFriendSelection.viewer_id && 
                    String(v.support_card_id) === state.pendingFriendSelection.support_card_id
                );
                if (f) {
                    selection.friend = f;
                    state.pendingFriendSelection = null;
                }
            }

            els.friendCount.innerText = `(${visibleFriends.length}/${friends.length})`;
            renderFriendFollowQuota();
            els.friendGrid.innerHTML = visibleFriends.length ? visibleFriends.map(friend => {
                const imgId = friend.support_card_id || '10001';
                const usable = isFriendProfileUsable(friend);
                const selected = isFriendProfileSelected(friend);
                return `<div class="friend-list-row ${selected ? 'selected' : ''}" data-viewer-id="${escapeAttr(friendViewerKey(friend))}">
                    <div class="friend-list-art">
                        <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    </div>
                    <div class="friend-list-main">
                        <div class="friend-list-name-row">
                            <span class="friend-list-name">${escapeHtml(friend.name || 'Unknown')}</span>
                            <span class="friend-list-login">Last login ${escapeHtml(formatRelativeTime(friend.last_login_time))}</span>
                        </div>
                        <div class="friend-list-meta">${escapeHtml(friend.support_name || 'Unknown support')} / LB${escapeHtml(String(friend.limit_break_count ?? '?'))}${friend.circle_name ? ` / ${escapeHtml(friend.circle_name)}` : ''}</div>
                        <div class="friend-list-comment">${escapeHtml(friend.comment || 'No trainer comment.')}</div>
                    </div>
                    <div class="friend-list-actions">
                        <button class="btn btn-sm friend-use-btn" type="button" data-action="use"${usable ? '' : ' disabled'}>${selected ? 'SELECTED' : 'USE SUPPORT'}</button>
                        <button class="btn btn-sm" type="button" data-action="profile">PROFILE</button>
                    </div>
                </div>`;
            }).filter(Boolean).join('') : '<div class="friend-list-empty">No following trainers match the current search.</div>';
            attachFriendHandlers();
            syncFriendSelection();
            renderCardBorrows();
            renderTeamPanel();
            updateRailCounts();
        }
        function appendSeenFriendIds(ids) {
            if (!dashData) return;
            const seen = new Set(dashData.friendExcludeIds || []);
            (ids || []).forEach(id => {
                if (id) seen.add(id);
            });
            dashData.friendExcludeIds = Array.from(seen);
        }
        function setFriendIdStatus(message, isError = false) {
            if (!els.friendIdStatus) return;
            els.friendIdStatus.innerText = message || '';
            els.friendIdStatus.classList.toggle('error', Boolean(isError));
        }
        async function loadFriends(refresh = false) {
            if (!dashData || state.isFetchingFriends) return;
            state.isFetchingFriends = true;
            els.friendRefreshBtn.disabled = true;
            els.friendStatus.classList.remove('error');
            els.friendStatus.innerText = refresh ? 'Refreshing friends...' : 'Loading friends...';
            const excludeIds = refresh ? (dashData.friendExcludeIds || []) : [];
            try {
                const data = await apiJson('/api/career/friends', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ exclude_viewer_ids: excludeIds, force_refresh: Boolean(refresh) })
                });
                if (!data.success) throw new Error(data.detail || 'Friend load failed');
                if (Array.isArray(data.decks) && data.decks.length > ((dashData.decks || []).length)) {
                    dashData.decks = data.decks;
                    dashData.deckDebug = data.deckDebug || dashData.deckDebug;
                    dashData.validDecks = dashData.decks.filter(isValidDeck);
                    renderDecks(dashData.validDecks);
                    attachDeckHandlers();
                }
                dashData.friends = data.friends || [];
                dashData.friendsList = data.friends_list || [];
                dashData.friendFollowQuota = data.follow_quota || null;
                dashData.borrowUmas = data.borrow_umas || [];
                dashData.borrowQuota = data.borrow_quota || null;
                appendSeenFriendIds(data.exclude_viewer_ids || []);
                renderFriends();
                renderBorrowUmas(dashData.borrowUmas);
                attachBorrowUmaHandlers();
                bindSparkTooltips();
                const source = data.source === 'initial' ? 'initial' : 'refresh';
                const visibleCount = ((dashData && dashData.visibleFriendsList) || []).length;
                const quota = getFriendFollowQuota();
                els.friendStatus.innerText = `${source} following: ${visibleCount}/${dashData.friendsList.length} trainers / ${quota.used}/${quota.max} followed`;
            } catch (e) {
                els.friendStatus.innerText = e.message || 'Friend load failed';
                els.friendStatus.classList.add('error');
            } finally {
                state.isFetchingFriends = false;
                els.friendRefreshBtn.disabled = false;
            }
        }
        async function addFriendById() {
            if (!dashData || state.isAddingFriendById) return;
            const raw = String((els.friendIdInput && els.friendIdInput.value) || '').trim().replace(/\s+/g, '');
            if (!raw) {
                setFriendIdStatus('Enter a trainer ID first.', true);
                return;
            }
            if (!/^\d+$/.test(raw)) {
                setFriendIdStatus('Trainer ID must contain digits only.', true);
                return;
            }

            state.isAddingFriendById = true;
            if (els.friendIdAddBtn) els.friendIdAddBtn.disabled = true;
            if (els.friendIdInput) els.friendIdInput.disabled = true;
            setFriendIdStatus(`Adding trainer ID ${raw}...`, false);

            try {
                const data = await apiJson('/api/friends/add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ viewer_id: Number(raw) })
                });
                if (!data.success) throw new Error(data.detail || 'Trainer ID follow failed');
                if (Array.isArray(data.decks) && data.decks.length > ((dashData.decks || []).length)) {
                    dashData.decks = data.decks;
                    dashData.deckDebug = data.deckDebug || dashData.deckDebug;
                    dashData.validDecks = dashData.decks.filter(isValidDeck);
                    renderDecks(dashData.validDecks);
                    attachDeckHandlers();
                }
                dashData.friends = data.friends || [];
                dashData.friendsList = data.friends_list || [];
                dashData.friendFollowQuota = data.follow_quota || null;
                dashData.borrowUmas = data.borrow_umas || [];
                dashData.borrowQuota = data.borrow_quota || null;
                appendSeenFriendIds(data.exclude_viewer_ids || []);
                renderFriends();
                renderBorrowUmas(dashData.borrowUmas);
                attachBorrowUmaHandlers();
                bindSparkTooltips();
                if (els.friendStatus && data.detail) els.friendStatus.innerText = data.detail;
                const profile = data.profile || {};
                const profileLabel = profile.name ? `${profile.name} (${profile.viewer_id || raw})` : raw;
                setFriendIdStatus(
                    data.already_followed
                        ? `Already following ${profileLabel}.`
                        : `Added ${profileLabel} to follows.`,
                    false
                );
                if (els.friendIdInput) els.friendIdInput.value = '';
            } catch (e) {
                setFriendIdStatus(e.message || 'Trainer ID follow failed.', true);
            } finally {
                state.isAddingFriendById = false;
                if (els.friendIdAddBtn) els.friendIdAddBtn.disabled = false;
                if (els.friendIdInput) els.friendIdInput.disabled = false;
            }
        }
        function attachFriendHandlers() {
            const visibleFriends = (dashData && dashData.visibleFriendsList) || [];
            document.querySelectorAll('#friend-grid .friend-list-row').forEach((el, i) => {
                el.addEventListener('click', event => {
                    const friend = visibleFriends[i];
                    if (!friend) return;
                    const action = event.target.closest('button')?.getAttribute('data-action') || '';
                    if (action === 'profile') {
                        openFriendProfile(friend);
                        return;
                    }
                    if (action === 'use') {
                        useFriendProfileSupport(friend);
                        return;
                    }
                    openFriendProfile(friend);
                });
            });
        }
        function attachCardBorrowHandlers() {
            const visibleSupports = (dashData && dashData.visibleCardBorrows) || [];
            document.querySelectorAll('#card-borrow-grid .friend-list-row').forEach((el, i) => {
                el.addEventListener('click', event => {
                    const friend = visibleSupports[i];
                    if (!friend) return;
                    const action = event.target.closest('button')?.getAttribute('data-action') || 'use';
                    if (action === 'use') selectFriendSupport(friend);
                });
            });
        }
        function buildRunCareerPayload() {
            const activeCareer = state.account && state.account.career && state.account.career.active;
            state.loopMode = normalizeLoopMode(els.loopModeSelect ? els.loopModeSelect.value : state.loopMode);
            state.loopCareerLimit = normalizeLoopCareerLimit(els.loopCareerLimitInput ? els.loopCareerLimitInput.value : state.loopCareerLimit);
            state.loopFanLimit = normalizeLoopFanLimit(els.loopFanLimitInput ? els.loopFanLimitInput.value : state.loopFanLimit);
            const loopPayload = {
                loop_enabled: state.loopEnabled,
                loop_mode: state.loopEnabled ? state.loopMode : 'forever',
                loop_career_limit: state.loopEnabled && state.loopMode === 'careers' ? state.loopCareerLimit : 0,
                loop_fan_limit: state.loopEnabled && state.loopMode === 'fans' ? state.loopFanLimit : 0,
                loop_count: state.loopEnabled && state.loopMode === 'careers' ? state.loopCareerLimit : 1
            };
            state.tpRecoveryMode = normalizeTpRecoveryMode();
            const tpRecoveryPayload = {
                allow_recover_tp: state.tpRecoveryMode
            };
            const showtime = parseShowtimeSelection(state.selectedShowtimeDifficulty || (els.showtimeDifficultySelect && els.showtimeDifficultySelect.value) || '');
            const includeNewCareerOnlyOptions = !activeCareer || state.loopEnabled;
            const restartFriend = selection.friend || (activeCareer ? {
                viewer_id: activeCareer.friend_viewer_id,
                support_card_id: activeCareer.friend_card_id
            } : null);
            const restartGuest = selection.guestParent || (activeCareer ? {
                viewer_id: activeCareer.rental_viewer_id,
                trained_chara_id: activeCareer.rental_trained_chara_id
            } : null);
            // Slot logic: the game treats Legacy 2 as either an own veteran OR the rental
            // guest — not both. So when a guest is selected, parent_id_2 is sent as 0 and
            // the guest fills slot 2. veterans[1] (if present) rides along as borrow_fallback_id
            // — the backend swaps it into parent_id_2 mid-loop when daily borrows hit 0.
            const hasGuest = Boolean(restartGuest && restartGuest.viewer_id && restartGuest.trained_chara_id);
            const vet2Id = (selection.veterans[1] && selection.veterans[1].instance_id)
                ? Number(selection.veterans[1].instance_id)
                : Number((activeCareer && activeCareer.parent_id_2) || 0);
            const startPayload = {
                card_id: Number((selection.trainee && selection.trainee.id) || (activeCareer && activeCareer.card_id) || 0),
                support_card_ids: selection.deck ? selection.deck.cards.map(card => Number(card.id)) : [],
                friend_viewer_id: Number((restartFriend && restartFriend.viewer_id) || 0),
                friend_card_id: Number((restartFriend && restartFriend.support_card_id) || 0),
                parent_id_1: Number((selection.veterans[0] && selection.veterans[0].instance_id) || (activeCareer && activeCareer.parent_id_1) || 0),
                parent_id_2: hasGuest ? 0 : vet2Id,
                rental_viewer_id: Number((restartGuest && restartGuest.viewer_id) || 0),
                rental_trained_chara_id: Number((restartGuest && restartGuest.trained_chara_id) || 0),
                borrow_fallback_id: hasGuest ? vet2Id : 0,
                deck_id: Number((selection.deck && selection.deck.id) || (activeCareer && activeCareer.deck_id) || 1),
                scenario_id: 4,
                use_tp: 30,
                // Showtime difficulty is a start-only choice. When resuming an
                // existing career without looping, do not send stale difficulty
                // metadata because the server has no in-career way to apply it.
                difficulty_id: includeNewCareerOnlyOptions ? showtime.difficulty_id : 0,
                difficulty: includeNewCareerOnlyOptions ? showtime.difficulty : 0,
                is_boost: includeNewCareerOnlyOptions && showtime.difficulty_id ? 1 : 0,
                boost_story_event_id: includeNewCareerOnlyOptions && showtime.difficulty_id ? Number((((state.dailyEvents || {}).showtime || {}).story_event_id) || 0) : 0,
                preset_name: selectedPresetName(),
                max_steps: 2500,
                ...tpRecoveryPayload,
                ...loopPayload
            };
            return startPayload;
        }
        // ---- Calibrate button: fast deck-specific sim sweep ----------
        // Opens a separate console window where the calibrate_deck.py
        // script runs a tight 3-5 min optimizer pass against the current
        // deck context. While it runs, the UI polls /api/calibrate/status
        // every 5 s and reflects progress + final report inline.
        let _calibratePollTimer = null;

        function setCalibrateStatus(message, isError) {
            if (!els.calibrateStatus) return;
            if (!message) {
                els.calibrateStatus.style.display = 'none';
                els.calibrateStatus.textContent = '';
                return;
            }
            els.calibrateStatus.style.display = 'block';
            els.calibrateStatus.textContent = message;
            els.calibrateStatus.style.color = isError ? '#c0392b' : '#1c7c54';
        }

        function stopCalibratePoll() {
            if (_calibratePollTimer) {
                clearInterval(_calibratePollTimer);
                _calibratePollTimer = null;
            }
        }

        async function pollCalibrateOnce() {
            try {
                const r = await apiJson('/api/calibrate/status');
                if (!r.success) return;
                const st = r.state || {};
                const report = st.last_report;
                if (report) {
                    stopCalibratePoll();
                    const ssr = (report.winner_ss_rate ?? report.baseline_ss_rate ?? 0);
                    const mean = Math.round(report.winner_mean ?? report.baseline_mean ?? 0);
                    const saved = report.saved_to_cache ? 'saved to cache' : 'no save';
                    const reason = report.reason || '';
                    setCalibrateStatus(
                        `Calibration done — SS rate ${(ssr * 100).toFixed(0)}% · ` +
                        `mean ${mean} · ${saved}${reason ? ' · ' + reason : ''}`,
                        false
                    );
                    if (els.calibrateBtn) els.calibrateBtn.disabled = false;
                } else if (st.running) {
                    const elapsed = st.started_at
                        ? Math.round(Date.now() / 1000 - st.started_at)
                        : 0;
                    setCalibrateStatus(
                        `Calibrating in separate console… ${elapsed}s elapsed. ` +
                        `Watch the console window for live probe progress.`,
                        false
                    );
                } else {
                    stopCalibratePoll();
                    if (els.calibrateBtn) els.calibrateBtn.disabled = false;
                }
            } catch (err) {
                // network blip — keep polling
            }
        }

        async function startCalibrate() {
            if (!els.calibrateBtn) return;
            if (els.calibrateBtn.disabled) return;
            els.calibrateBtn.disabled = true;
            setCalibrateStatus('Launching calibration console…', false);
            try {
                const r = await apiJson('/api/calibrate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({}),
                });
                if (!r.success) {
                    setCalibrateStatus(`Calibrate failed to start: ${r.error || 'unknown'}`, true);
                    els.calibrateBtn.disabled = false;
                    return;
                }
                setCalibrateStatus(
                    'Calibration running in a new console window. ' +
                    'This page will update when it finishes (~3-5 min).',
                    false
                );
                stopCalibratePoll();
                _calibratePollTimer = setInterval(pollCalibrateOnce, 5000);
                // Also poll immediately so user sees the 'running' state right away
                pollCalibrateOnce();
            } catch (err) {
                setCalibrateStatus(`Calibrate request failed: ${err.message || err}`, true);
                els.calibrateBtn.disabled = false;
            }
        }

        async function verifyStart() {
            const reason = getStartMissingReason();
            if (reason || state.isStartingCareer || state.isVerifyingStart) {
                syncStartButton();
                return;
            }
            state.isVerifyingStart = true;
            syncStartButton();
            let finalMessage = '';
            let finalIsError = false;
            try {
                const data = await apiJson('/api/career/run/preflight', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(buildRunCareerPayload())
                });
                if (!data.success) throw new Error(data.detail || 'Start verification failed');
                const warnings = data.proof && data.proof.warnings && data.proof.warnings.length
                    ? ` (${data.proof.warnings.length} warning${data.proof.warnings.length === 1 ? '' : 's'})`
                    : '';
                finalMessage = `${data.detail || 'Start proof passed'}${warnings}`;
                refreshBotView();
            } catch (e) {
                finalMessage = e.message || 'Start verification failed';
                finalIsError = true;
            } finally {
                state.isVerifyingStart = false;
                syncStartButton();
                if (finalMessage) {
                    setStartStatusMessage(finalMessage, finalIsError);
                }
            }
        }
        async function startCareer() {
            const reason = getStartMissingReason();
            if (reason || state.isStartingCareer) {
                syncStartButton();
                return;
            }
            state.isStartingCareer = true;
            syncStartButton();
            let finalMessage = '';
            let finalIsError = false;
            try {
                const data = await apiJson('/api/career/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(buildRunCareerPayload())
                });
                if (!data.success) throw new Error(data.detail || 'Start failed');
                renderAccountStrip(data.account);
                state.runnerRunning = Boolean(data.runner && data.runner.running);
                state.loopActive = Boolean(data.loop && data.loop.active);
                startRunnerPolling();
                finalMessage = state.loopActive ? 'Career loop started' : 'Career runner started';
            } catch (e) {
                finalMessage = e.message || 'Start failed';
                finalIsError = true;
            } finally {
                state.isStartingCareer = false;
                syncStartButton();
                if (finalMessage) {
                    setStartStatusMessage(finalMessage, finalIsError);
                }
            }
        }
        async function refreshRunnerStatus() {
            try {
                const data = await apiJson('/api/career/runner');
                if (!data.success || !data.runner) return;
                const runner = data.runner;
                const loop = data.loop || {};
                state.runnerSnapshot = runner;
                state.runnerRunning = Boolean(runner.running);
                state.loopActive = Boolean(loop.active);
                if (loop.active) {
                    state.loopEnabled = true;
                    safeLocalSet('loopEnabled', '1');
                    const loopMode = normalizeLoopMode(loop.mode || state.loopMode);
                    state.loopMode = loopMode;
                    safeLocalSet('loopMode', loopMode);
                }
                if (Array.isArray(data.parents)) mergeRunnerParents(data.parents);
                if (data.account) renderAccountStrip(data.account);
                else renderCareerStatBar(state.account, runner);
                if (data.borrow_quota && dashData) {
                    const prev = dashData.borrowQuota || {};
                    dashData.borrowQuota = data.borrow_quota;
                    if (prev.remaining !== data.borrow_quota.remaining || prev.max !== data.borrow_quota.max) {
                        renderBorrowUmas((dashData.borrowUmas) || []);
                        attachBorrowUmaHandlers();
                        bindSparkTooltips();
                    }
                }
                syncStartButton();
                const rows = (runner.action_history && runner.action_history.length) ? runner.action_history : deriveActionHistory(runner.log || []);
                if (rows.length) renderActionHistory(rows, loop);
                if (runner.finished && !runner.running) {
                    notifyCareerCompletion(runner, loop);
                }
                if (runner.running) {
                    if (!rows.length) setStartStatusMessage(runnerStatusText(runner, loop));
                    return;
                }
                if (loop.active) {
                    if (!rows.length) setStartStatusMessage(runnerStatusText(runner, loop));
                    return;
                }
                if (state.runnerTimer) {
                    window.clearInterval(state.runnerTimer);
                    state.runnerTimer = 0;
                }
                if (runner.last_error) {
                    if (!rows.length) setStartStatusMessage(runner.last_error, true);
                } else if (loop.last_error) {
                    if (!rows.length) setStartStatusMessage(loop.last_error, true);
                } else if (runner.steps) {
                    if (!rows.length) setStartStatusMessage(loop.completed ? loopStatusText(loop) : `Runner stopped after ${runner.steps} steps`);
                }
            } catch (e) {}
        }
        function loopStatusText(loop = {}) {
            if (!loop || (!loop.active && !loop.completed && !loop.last_message && !loop.last_error)) return '';
            const mode = String(loop.mode || 'forever').toLowerCase();
            const careerLimit = Number(loop.career_limit || loop.requested || 0);
            const fanLimit = Number(loop.fan_limit || 0);
            const fans = Number(loop.fans || 0);
            const current = Number(loop.current || 0);
            const completed = Number(loop.completed || 0);
            if (loop.waiting_for_tp) {
                return `${loopStatusText({ ...loop, waiting_for_tp: false })} / WAITING TP ${loop.tp_current || 0}/${loop.tp_required || 0}`;
            }
            let base;
            if (mode === 'careers') {
                const total = careerLimit > 0 ? careerLimit : 'INF';
                base = loop.active ? `CAREERS ${Math.max(current, completed + 1)}/${total}` : `CAREERS ${completed}/${total}`;
            } else if (mode === 'fans') {
                base = `FANS ${formatNumber(fans)}/${formatNumber(fanLimit)} / CAREERS ${loop.active ? Math.max(current, completed + 1) : completed}`;
            } else {
                base = `LOOP FOREVER / CAREERS ${loop.active ? Math.max(current, completed + 1) : completed}`;
            }
            return `${base}${loop.last_message ? ' / ' + loop.last_message : ''}`;
        }
        function runnerStatusText(runner, loop = {}) {
            const loopText = loopStatusText(loop);
            const runnerText = `Turn ${runner.turn || '?'} / ${runner.last_action || 'running'} / ${runner.steps || 0}`;
            return loopText ? `${loopText} / ${runnerText}` : runnerText;
        }
        function renderActionHistory(rows, loop = {}) {
            if (!els.startStatus) return;
            if (!rows.length) {
                setStartStatusMessage('');
                return;
            }
            const previousWrap = els.startStatus.querySelector('.action-history-wrap');
            const previousScrollTop = previousWrap ? previousWrap.scrollTop : 0;
            const previousPinnedToBottom = !previousWrap
                || ((previousWrap.scrollHeight - previousWrap.clientHeight - previousWrap.scrollTop) <= 24);
            const historyStyleLabel = value => {
                const numeric = Number(value);
                if (Number.isFinite(numeric) && numeric > 0) {
                    return ({ 1: 'Front', 2: 'Pace', 3: 'Late', 4: 'End' })[numeric] || '';
                }
                const normalized = raceStyleLabel(value);
                if (normalized) return normalized;
                const text = String(value || '').trim();
                return ['Front', 'Pace', 'Late', 'End'].includes(text) ? text : '';
            };
            const raceStrategyDetail = row => {
                const raceResult = row.race_result || {};
                const styleChange = row.style_change && typeof row.style_change === 'object'
                    ? row.style_change
                    : (raceResult.style_change && typeof raceResult.style_change === 'object' ? raceResult.style_change : null);
                const used = row.running_style_label
                    || raceResult.running_style_label
                    || historyStyleLabel(row.running_style)
                    || historyStyleLabel(raceResult.running_style)
                    || historyStyleLabel(styleChange && (styleChange.applied_running_style || styleChange.applied_style));
                const desired = historyStyleLabel(
                    row.desired_running_style
                    || raceResult.desired_running_style
                    || (styleChange && styleChange.desired_style)
                );
                const failed = Boolean(styleChange && styleChange.attempted && styleChange.succeeded === false);
                if (used && desired && used.toLowerCase() !== desired.toLowerCase()) {
                    return `STRAT ${used} (wanted ${desired}${failed ? ', change failed' : ''})`;
                }
                if (used) return `STRAT ${used}${failed ? ' (change failed)' : ''}`;
                if (desired) return `WANTED ${desired}${failed ? ' (change failed)' : ''}`;
                return '';
            };
            const formatStatsDetail = row => {
                const stats = row.stats || {};
                const raceResult = row.race_result || {};
                const rank = Number(row.result_rank || raceResult.finish_rank || raceResult.result_rank || 0);
                const wonFlag = row.won ?? raceResult.won;
                const flagWon = wonFlag === true || wonFlag === 1 || String(wonFlag).toLowerCase() === 'true' || String(wonFlag).toLowerCase() === 'won';
                const resultWon = rank > 0 ? rank === 1 : flagWon;
                const resultLabel = rank ? `${resultWon ? 'WON' : 'LOST'} #${rank}` : '';
                // Retry / alarm-clock annotation: backend's _annotate_race_continue_result
                // attaches continued/continue_resources/continue_attempts to race_result
                // when a race used continues. Build a compact tag like "⏰ x2" or "🪙 x1".
                let retryTag = '';
                if (raceResult.continued || row.continued) {
                    const resources = Array.isArray(raceResult.continue_resources || row.continue_resources)
                        ? (raceResult.continue_resources || row.continue_resources)
                        : [];
                    const clockCount  = resources.filter(r => r === 'alarm_clock').length;
                    const caratCount  = resources.filter(r => r === 'carats').length;
                    const freeCount   = resources.filter(r => r === 'free_retry').length;
                    const partsRetry = [];
                    if (clockCount > 0) partsRetry.push(`⏰×${clockCount}`);
                    if (caratCount > 0) partsRetry.push(`🪙×${caratCount}`);
                    if (freeCount > 0)  partsRetry.push(`FREE×${freeCount}`);
                    if (partsRetry.length === 0) {
                        const attempts = Number(raceResult.continue_attempts || row.continue_attempts || 0);
                        if (attempts > 0) partsRetry.push(`RETRY×${attempts}`);
                    }
                    if (partsRetry.length) retryTag = `RETRIED ${partsRetry.join(' ')}`;
                }
                const strategyTag = normalizeHistoryAction(row).action === 'race' ? raceStrategyDetail(row) : '';
                if (!Object.keys(stats).length) {
                    const tail = [resultLabel, strategyTag, retryTag].filter(Boolean).join(' | ');
                    return tail || row.detail || '';
                }
                const parts = [
                    `HP ${stats.hp ?? 0}/${stats.max_hp ?? 100}`,
                    `MOOD ${stats.motivation ?? 0}`,
                    `SPD ${stats.speed ?? 0} STA ${stats.stamina ?? 0} PWR ${stats.power ?? 0} GUT ${stats.guts ?? 0} WIT ${stats.wit ?? 0} SP ${stats.skill_point ?? 0}`
                ];
                if (resultLabel) parts.unshift(resultLabel);
                if (strategyTag) parts.splice(resultLabel ? 1 : 0, 0, strategyTag);
                if (retryTag) parts.splice(resultLabel ? 1 : 0, 0, retryTag);
                return parts.join(' | ');
            };
            const loopLine = loopStatusText(loop);
            const body = rows.map(row => `
                    <tr>
                        <td>${escapeHtml(row.turn)}</td>
                        <td><span class="action-pill action-pill-${escapeAttr(normalizeHistoryAction(row).action)}">${escapeHtml(normalizeHistoryAction(row).action)}</span></td>
                        <td>${escapeHtml(row.facility)}</td>
                        <td class="action-history-detail">${escapeHtml(formatStatsDetail(row))}</td>
                    </tr>
                `).join('');
            els.startStatus.innerHTML = `
                ${loopLine ? `<div class="loop-status-line">${escapeHtml(loopLine)}</div>` : ''}
                <div class="action-history-wrap">
                    <table class="action-history-table">
                        <thead>
                            <tr>
                                <th>TURN</th>
                                <th>ACTION</th>
                                <th>FACILITY</th>
                                <th>DETAIL</th>
                            </tr>
                        </thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
            `;
            els.startStatus.classList.remove('error');
            els.startStatus.classList.add('has-history');
            const wrap = els.startStatus.querySelector('.action-history-wrap');
            if (wrap) {
                if (previousPinnedToBottom) {
                    wrap.scrollTop = wrap.scrollHeight;
                } else {
                    wrap.scrollTop = Math.min(
                        previousScrollTop,
                        Math.max(0, wrap.scrollHeight - wrap.clientHeight),
                    );
                }
            }
        }
        function deriveActionHistory(log) {
            return log.filter(item => ['command', 'race', 'race_progress', 'finish', 'api_delay', 'turn_delay', 'complex_delay'].includes(item.action)).map(item => {
                const detail = String(item.detail || '');
                let action = item.action;
                let facility = '';
                if (action === 'command') {
                    if (detail.startsWith('training ')) {
                        action = 'train';
                        facility = detail.replace('training ', '');
                    } else if (detail.startsWith('rest ')) {
                        action = 'rest';
                        facility = detail.replace('rest ', '');
                        if (['301', '302', '303', '304', '305', '390'].includes(facility)) action = 'recreation';
                    } else if (detail.startsWith('challenge ')) {
                        action = 'rest';
                        facility = detail.replace('challenge ', '');
                    } else if (detail.startsWith('recreation ')) {
                        action = 'recreation';
                        facility = detail.replace('recreation ', '');
                    } else if (detail.startsWith('command 8:')) {
                        action = 'medic';
                    }
                } else if (action === 'race_progress') {
                    action = 'race';
                }
                return { turn: item.turn, action, facility, detail };
            });
        }
        function normalizeHistoryAction(row) {
            const facility = String(row.facility ?? '');
            if (row.action === 'race_progress') {
                return { ...row, action: 'race' };
            }
            if (row.action === 'rest' && ['301', '302', '303', '304', '305', '390'].includes(facility)) {
                return { ...row, action: 'recreation' };
            }
            return row;
        }
        function refreshLocalTpTick() {
            if (!state.account || !state.account.tp) return;
            const before = Number(state.account.tp.current || 0);
            deriveAccountTpForDisplay(state.account);
            const after = Number(state.account.tp.current || 0);
            if (after !== before) renderAccountStrip(state.account);
        }
        async function refreshSessionAccountState() {
            if (!dashData) return;
            try {
                const data = await apiJson('/api/session?t=' + Date.now());
                if (!data || !data.success) return;
                if (data.account) renderAccountStrip(data.account);
                state.loopActive = Boolean(data.loop && data.loop.active);
                syncStartButton();
            } catch (e) {}
        }
        function startAccountSyncPolling() {
            if (!state.tpTickTimer) {
                state.tpTickTimer = window.setInterval(refreshLocalTpTick, 1000);
            }
            if (!state.accountSyncTimer) {
                state.accountSyncTimer = window.setInterval(refreshSessionAccountState, 15000);
            }
        }
        function stopAccountSyncPolling() {
            if (state.accountSyncTimer) {
                window.clearInterval(state.accountSyncTimer);
                state.accountSyncTimer = 0;
            }
            if (state.tpTickTimer) {
                window.clearInterval(state.tpTickTimer);
                state.tpTickTimer = 0;
            }
        }
        function startRunnerPolling() {
            if (state.runnerTimer) window.clearInterval(state.runnerTimer);
            refreshRunnerStatus();
            state.runnerTimer = window.setInterval(refreshRunnerStatus, 1500);
        }
        async function stopRunner() {
            if (state.isStoppingRunner) return;
            state.isStoppingRunner = true;
            syncLoopControls();
            try {
                await apiJson('/api/career/runner/stop', { method: 'POST' });
                startRunnerPolling();
            } catch (e) {
                setStartStatusMessage('Stop failed', true);
            } finally {
                state.isStoppingRunner = false;
                syncLoopControls();
            }
        }
        async function endCareer() {
            if (state.isEndingCareer) return;
            const activeCareer = Boolean((state.account && state.account.career && state.account.career.active) || state.runnerRunning || state.loopActive);
            if (!activeCareer) {
                setStartStatusMessage('No active career to end.', true);
                return;
            }
            if (!window.confirm('End the current career now? This force-ends the run and will not be learned as a full career.')) {
                return;
            }
            state.isEndingCareer = true;
            syncLoopControls();
            try {
                const currentTurn = Number((state.runnerSnapshot && state.runnerSnapshot.turn) || (state.account && state.account.career && state.account.career.turn) || 0);
                const data = await apiJson('/api/career/end', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ current_turn: currentTurn })
                });
                if (!data.success) throw new Error(data.detail || 'End career failed');
                state.runnerRunning = Boolean(data.runner && data.runner.running);
                state.loopActive = Boolean(data.loop && data.loop.active);
                state.runnerSnapshot = data.runner || state.runnerSnapshot;
                if (data.account) {
                    renderAccountStrip(data.account);
                }
                startRunnerPolling();
                setStartStatusMessage(data.detail || 'Career ended.');
            } catch (e) {
                setStartStatusMessage(e.message || 'End career failed', true);
            } finally {
                state.isEndingCareer = false;
                syncLoopControls();
                syncStartButton();
            }
        }
        els.loopToggleBtn?.addEventListener('click', () => {
            if (state.runnerRunning || state.loopActive || state.isStartingCareer) return;
            state.loopEnabled = !state.loopEnabled;
            safeLocalSet('loopEnabled', state.loopEnabled ? '1' : '0');
            syncLoopControls();
            syncStartButton();
        });
        els.careerNotifyToggleBtn?.addEventListener('click', async () => {
            const next = !state.careerCompleteNotifyEnabled;
            if (next) {
                const granted = await ensureNotificationPermission();
                if (!granted) {
                    state.careerCompleteNotifyEnabled = false;
                    safeLocalSet('careerCompleteNotifyEnabled', '0');
                    syncCareerNotifyToggle();
                    setStartStatusMessage('Browser notifications are blocked or unavailable.', true);
                    return;
                }
            }
            state.careerCompleteNotifyEnabled = next;
            safeLocalSet('careerCompleteNotifyEnabled', next ? '1' : '0');
            syncCareerNotifyToggle();
            setStartStatusMessage(next ? 'Career completion notifications enabled.' : 'Career completion notifications disabled.');
        });
        els.loopModeSelect?.addEventListener('change', () => {
            state.loopMode = normalizeLoopMode(els.loopModeSelect.value);
            safeLocalSet('loopMode', state.loopMode);
            syncLoopControls();
        });
        els.loopCareerLimitInput?.addEventListener('input', () => {
            state.loopCareerLimit = normalizeLoopCareerLimit(els.loopCareerLimitInput.value);
            safeLocalSet('loopCareerLimit', state.loopCareerLimit);
            syncLoopControls();
        });
        els.loopFanLimitInput?.addEventListener('input', () => {
            state.loopFanLimit = normalizeLoopFanLimit(els.loopFanLimitInput.value);
            safeLocalSet('loopFanLimit', state.loopFanLimit);
            syncLoopControls();
        });
        els.tpRecoverySelect?.addEventListener('change', () => {
            state.tpRecoveryMode = normalizeTpRecoveryMode();
            syncStartButton();
        });
        els.endCareerBtn?.addEventListener('click', endCareer);
        els.stopRunnerBtn?.addEventListener('click', stopRunner);
        els.friendRefreshBtn.addEventListener('click', event => {
            event.stopPropagation();
            loadFriends(true);
        });
        els.cardBorrowRefreshBtn?.addEventListener('click', event => {
            event.stopPropagation();
            if (els.cardBorrowStatus) {
                els.cardBorrowStatus.classList.remove('error');
                els.cardBorrowStatus.innerText = 'Refreshing friend support borrows...';
            }
            loadFriends(true);
        });
        els.friendIdAddBtn?.addEventListener('click', event => {
            event.stopPropagation();
            addFriendById();
        });
        els.friendIdInput?.addEventListener('keydown', event => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            addFriendById();
        });
        if (els.borrowUmaRefreshBtn) {
            els.borrowUmaRefreshBtn.addEventListener('click', event => {
                event.stopPropagation();
                if (els.borrowUmaStatus) {
                    els.borrowUmaStatus.classList.remove('error');
                    els.borrowUmaStatus.innerText = 'Refreshing borrowable parents...';
                }
                loadFriends(true);
            });
        }
        if (els.borrowUmaSearchInput) {
            els.borrowUmaSearchInput.addEventListener('input', () => {
                state.librarySearch.borrowUmas = els.borrowUmaSearchInput.value || '';
                renderBorrowUmas((dashData && dashData.borrowUmas) || []);
                attachBorrowUmaHandlers();
                bindSparkTooltips();
            });
        }
        els.botViewRefreshBtn?.addEventListener('click', event => {
            event.stopPropagation();
            refreshBotView();
        });
        els.teamBundleToggleBtn?.addEventListener('click', event => {
            event.stopPropagation();
            setTeamBundleMenuOpen(!state.isTeamBundleMenuOpen);
        });
        els.teamBundlePresetSelect?.addEventListener('change', () => {
            state.selectedTeamBundlePreset = els.teamBundlePresetSelect.value || '';
            safeLocalSet('selectedTeamBundlePreset', state.selectedTeamBundlePreset);
            if (els.teamBundlePresetNameInput) els.teamBundlePresetNameInput.value = state.selectedTeamBundlePreset;
            renderTeamBundlePresetControls();
            setTeamBundlePresetStatus('');
        });
        els.teamBundlePresetNameInput?.addEventListener('input', () => {
            if (els.teamBundlePresetNameInput.value.trim()) setTeamBundlePresetStatus('');
        });
        els.teamBundlePresetApplyBtn?.addEventListener('click', applySelectedTeamBundlePreset);
        els.teamBundlePresetSaveBtn?.addEventListener('click', saveTeamBundlePreset);
        els.teamBundlePresetDeleteBtn?.addEventListener('click', deleteSelectedTeamBundlePreset);
        document.addEventListener('click', event => {
            if (!state.isTeamBundleMenuOpen || !els.teamBundleMenu) return;
            if (!els.teamBundleMenu.contains(event.target)) setTeamBundleMenuOpen(false);
        });
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && state.isTeamBundleMenuOpen) setTeamBundleMenuOpen(false);
        });
        els.startCareerBtn.addEventListener('click', startCareer);
        els.verifyStartBtn?.addEventListener('click', verifyStart);
        els.calibrateBtn?.addEventListener('click', startCalibrate);

        function selectDeck(index, element) {
            const deck = ((dashData && dashData.visibleDecks) || [])[index];
            if (!deck) return;
            const alreadySelected = selection.deck && Number(selection.deck.id) === Number(deck.id);
            document.querySelectorAll('.deck-container.selected').forEach(card => card.classList.remove('selected'));
            selection.deck = null;
            if (!alreadySelected) {
                element.classList.add('selected');
                selection.deck = deck;
            }
            renderFriends();
            renderTeamPanel();
            syncSelectionToServer();
        }
        function selectTrainee(index, element) {
            const uma = ((dashData && dashData.visibleTrainees) || [])[index];
            if (!uma) return;
            const alreadySelected = selection.trainee && traineeKey(selection.trainee) === traineeKey(uma);
            document.querySelectorAll('#uma-grid .grid-card.selected').forEach(card => card.classList.remove('selected'));
            selection.trainee = null;
            if (!alreadySelected) {
                element.classList.add('selected');
                selection.trainee = uma;
            }
            renderFriends();
            updateVetSelectability();
            renderTeamPanel();
            syncSelectionToServer();
        }
        function selectParent(index, element) {
            if (element.classList.contains('vet-full')) return;
            const parent = ((dashData && dashData.visibleParents) || [])[index];
            if (!parent) return;
            const key = parentKey(parent);
            if (element.classList.contains('selected')) {
                element.classList.remove('selected');
                selection.veterans = selection.veterans.filter(vet => parentKey(vet) !== key);
            } else if (selection.veterans.length < 2) {
                element.classList.add('selected');
                selection.veterans.push({ ...parent, _gridIdx: parent._gridIdx });
            }
            updateVetSelectability();
            renderTeamPanel();
            syncSelectionToServer();
        }
        function attachSelectionHandlers() {
            attachDeckHandlers();
            attachFavoriteHandlers();
            document.querySelectorAll('#uma-grid .grid-card').forEach((element, index) => {
                if (element.dataset.selectBound === '1') return;
                element.dataset.selectBound = '1';
                element.classList.add('selectable');
                element.addEventListener('click', () => selectTrainee(index, element));
            });
            document.querySelectorAll('#parent-grid .grid-card').forEach((element, index) => {
                if (element.dataset.selectBound === '1') return;
                element.dataset.selectBound = '1';
                element.classList.add('selectable');
                element.addEventListener('click', () => selectParent(index, element));
            });
        }
        function attachDeckHandlers() {
            document.querySelectorAll('.deck-container').forEach((element, index) => {
                if (element.dataset.selectBound === '1') return;
                element.dataset.selectBound = '1';
                const editButton = element.querySelector('.deck-edit-btn');
                if (editButton) {
                    editButton.addEventListener('click', event => {
                        event.preventDefault();
                        event.stopPropagation();
                        const deck = ((dashData && dashData.visibleDecks) || [])[index];
                        if (deck) showDeckDetail(deck);
                    });
                }
                element.addEventListener('click', event => {
                    if (event.target.closest('.deck-edit-btn')) return;
                    selectDeck(index, element);
                });
            });
        }
        function isValidDeck(deck) {
            const cards = Array.isArray(deck.cards) ? deck.cards : [];
            if (cards.length > 5) return false;
            return cards.every(card => {
                const id = String(card.id || '');
                return /^\d+$/.test(id) && Number(id) > 0;
            });
        }
        function renderCounts(data) {
            els.umaCount.innerText = `(${data.umas.length})`;
            els.cardCount.innerText = `(${data.supports.length})`;
            els.parentCount.innerText = `(${data.parents.length})`;
        }
        function renderDecks(decks) {
            const visibleDecks = filterDecks(decks);
            if (dashData) dashData.visibleDecks = visibleDecks;
            els.deckList.innerHTML = visibleDecks.map(deck => {
                const deckCards = Array.isArray(deck.cards) ? deck.cards : [];
                const cards = deckCards.map(card => {
                    const imgId = card.id || '10001';
                    return `<div class="grid-card deck-card">
                        <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                        <div class="grid-card-overlay">
                            <span class="grid-card-kicker">${escapeHtml(card.rarity || '?')}</span>
                            <span class="grid-card-name">${escapeHtml(card.name || 'Unknown')}</span>
                        </div>
                    </div>`;
                }).join('');
                const selected = selection.deck && Number(selection.deck.id) === Number(deck.id);
                return `<div class="deck-container ${selected ? 'selected' : ''}">
                    <div class="deck-header">
                        <span>${escapeHtml(String(deck.name || `Deck ${deck.id || ''}`).toUpperCase())}${deck.edited ? ' <em class="deck-edited-chip">EDITED</em>' : ''}</span>
                        <span class="deck-header-actions">
                            <button class="deck-edit-btn" type="button" data-deck-id="${Number(deck.id || 0)}">EDIT</button>
                            <span style="font-size:0.85rem; opacity:0.8">SLOT ${escapeHtml(String(deck.id || ''))}</span>
                        </span>
                    </div>
                    <div class="deck-cards">${cards}</div>
                </div>`;
            }).join('');
        }
        async function refreshBotView() {
            if (!els.botViewOutput) return;
            els.botViewOutput.textContent = 'Loading bot view...';
            if (els.botViewRefreshBtn) els.botViewRefreshBtn.disabled = true;
            try {
                const [deckResult, startResult] = await Promise.allSettled([
                    apiJson('/api/debug/decks/probe?t=' + Date.now(), { method: 'POST' }),
                    apiJson('/api/debug/start?t=' + Date.now())
                ]);
                const data = {
                    decks_probe: deckResult.status === 'fulfilled'
                        ? deckResult.value
                        : { success: false, detail: deckResult.reason?.message || 'Deck probe failed' },
                    start_debug: startResult.status === 'fulfilled'
                        ? startResult.value
                        : { success: false, detail: startResult.reason?.message || 'Start debug failed' }
                };
                if (!data.decks_probe.success && !data.start_debug.success) {
                    throw new Error(data.decks_probe.detail || data.start_debug.detail || 'Bot view failed');
                }
                if (data.decks_probe.success && Array.isArray(data.decks_probe.decks) && dashData) {
                    const supportById = new Map((dashData.supports || []).map(card => [String(card.id), card]));
                    dashData.decks = data.decks_probe.decks.map(deck => ({
                        ...deck,
                        cards: (deck.card_ids || []).map(id => {
                            const support = supportById.get(String(id));
                            return support || { id: String(id), name: `Unknown (${id})`, rarity: '?', type: '?' };
                        })
                    }));
                    dashData.validDecks = dashData.decks.filter(isValidDeck);
                    renderDecks(dashData.validDecks);
                    attachDeckHandlers();
                }
                els.botViewOutput.textContent = JSON.stringify(data, null, 2);
            } catch (e) {
                els.botViewOutput.textContent = e.message || 'Bot view failed';
            } finally {
                if (els.botViewRefreshBtn) els.botViewRefreshBtn.disabled = false;
            }
        }
        function renderFactors(factors) {
            const star = String.fromCharCode(9733);
            function factorBadgeTitle(factor) {
                const effect = String((factor && factor.effect_summary) || '').trim();
                if (effect) return effect;
                const name = String((factor && factor.name) || '').trim();
                return name ? `Factor: ${name}` : 'Factor';
            }
            return factors.map(factor => `
                <div class="factor-badge f-${factor.category}" title="${escapeAttr(factorBadgeTitle(factor))}" aria-label="${escapeAttr(factorBadgeTitle(factor))}">
                    ${factor.name} <span class="stars">${star.repeat(factor.stars)}</span>
                </div>
            `).join('');
        }
        function renderWins(wins) {
            if (!wins || !wins.total) return '<span class="spark-win-chip">Wins --</span>';
            return `
                <span class="spark-win-chip">G1 ${wins.g1 || 0}</span>
                <span class="spark-win-chip">G2 ${wins.g2 || 0}</span>
                <span class="spark-win-chip">G3 ${wins.g3 || 0}</span>
            `;
        }
        function renderParentSparks(parent, fallbackImgId) {
            const tree = parent.tree || {};
            return ['self', 'p1', 'p2'].map(key => {
                const node = tree[key];
                if (!node || !node.factors || node.factors.length === 0) return '';
                const nodeImg = node.card_id || fallbackImgId;
                const nodeClass = key === 'self' ? 'spark-node spark-node-self' : 'spark-node';
                return `<div class="${nodeClass}" style="--node-bg: url('/api/images/${nodeImg}.png')">
                    <div class="spark-node-header">
                        <img class="spark-node-portrait" src="/api/images/${nodeImg}.png" onerror="hideBrokenImage(this)">
                        <div class="spark-node-meta">
                            <div class="spark-node-title">${node.name || `Card ${node.card_id || '?'}`}</div>
                            <div class="spark-win-row">${renderWins(node.wins)}</div>
                        </div>
                    </div>
                    <div class="spark-factor-list">
                        ${renderFactors(node.factors)}
                    </div>
                </div>`;
            }).join('');
        }
        function renderParents(parents) {
            const visibleParents = visibleLibraryItems(parents, 'parents', state.librarySearch.parents, [
                item => item.name,
                item => item.card_id,
                item => item.instance_id,
                item => rankMap[item.rank],
                item => Object.values(item.tree || {}).map(node => node && node.name).filter(Boolean).join(' ')
            ]);
            if (dashData) dashData.visibleParents = visibleParents;
            els.parentCount.innerText = `(${visibleParents.length}/${parents.length})`;
            els.parentGrid.innerHTML = visibleParents.map(parent => {
                const imgId = parent.card_id || '100101';
                const selected = selection.veterans.some(vet => parentKey(vet) === parentKey(parent));
                return `<div class="grid-card ${selected ? 'selected' : ''}">
                    ${favoriteButtonHtml('parents', parent)}
                    <div class="rank-badge">${rankMap[parent.rank] || '??'}</div>
                    ${parent.is_new ? '<div class="new-badge">[NEW]</div>' : ''}
                    <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    <div class="sparks-tooltip" style="--spark-bg: url('/api/images/${imgId}.png')">
                        <div class="sparks-tooltip-title"></div>
                        <div class="sparks-tooltip-scroll">
                            <div class="sparks-lineage-grid">
                                ${renderParentSparks(parent, imgId)}
                            </div>
                        </div>
                    </div>
                    <div class="grid-card-overlay">
                        <span class="grid-card-kicker">ID: ${parent.instance_id || '?'}</span>
                        <span class="grid-card-name">${parent.name || 'Unknown'}</span>
                    </div>
                </div>`;
            }).join('');
        }
        function aptLetter(score) {
            const map = {8: 'S', 7: 'A', 6: 'B', 5: 'C', 4: 'D', 3: 'E', 2: 'F', 1: 'G'};
            return map[score] || '?';
        }
        function styleLabel(rs) {
            return ({1: 'Front', 2: 'Pace', 3: 'Late', 4: 'End'})[rs] || '?';
        }
        function borrowUmaKey(uma) {
            return `${uma.viewer_id}:${uma.trained_chara_id}`;
        }
        function renderBorrowUmas(umas) {
            const list = Array.isArray(umas) ? umas : [];
            const query = (state.librarySearch.borrowUmas || '').trim().toLowerCase();
            const visible = query
                ? list.filter(u =>
                    String(u.chara_name || '').toLowerCase().includes(query) ||
                    String(u.trainer_name || '').toLowerCase().includes(query)
                  )
                : list;
            const quota = dashData && dashData.borrowQuota;
            if (els.borrowUmaCount) {
                els.borrowUmaCount.innerText = quota ? `(${quota.remaining}/${quota.max} borrows left today)` : `(${list.length})`;
            }
            if (els.borrowUmaStatus) {
                if (!list.length) {
                    els.borrowUmaStatus.innerText = 'No borrowable parents loaded. Click REFRESH.';
                } else {
                    els.borrowUmaStatus.innerText = `${list.length} borrowable parent${list.length === 1 ? '' : 's'}. Click one to use as Guest, click again to clear.`;
                }
            }
            if (!els.borrowUmaGrid) return;
            els.borrowUmaGrid.innerHTML = visible.map(uma => {
                const imgId = uma.card_id || '100101';
                const selected = selection.guestParent && borrowUmaKey(selection.guestParent) === borrowUmaKey(uma);
                const resolvedRank = Number(uma.rank || 0) || Number(uma.chara_grade || 0) || 0;
                const rankLabel = rankMap[resolvedRank] || (uma.rarity ? '★'.repeat(uma.rarity) : '??');
                return `<div class="grid-card borrow-uma-card selectable ${selected ? 'selected' : ''}" data-key="${borrowUmaKey(uma)}">
                    <div class="rank-badge">${rankLabel}</div>
                    <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    <div class="sparks-tooltip" style="--spark-bg: url('/api/images/${imgId}.png')">
                        <div class="sparks-tooltip-title"></div>
                        <div class="sparks-tooltip-scroll">
                            <div class="sparks-lineage-grid">
                                ${renderParentSparks(uma, imgId)}
                            </div>
                        </div>
                    </div>
                    <div class="grid-card-overlay">
                        <span class="grid-card-kicker">${uma.trainer_name || '?'}</span>
                        <span class="grid-card-name">${uma.chara_name || 'Unknown'}</span>
                    </div>
                </div>`;
            }).join('');
        }
        function attachBorrowUmaHandlers() {
            if (!els.borrowUmaGrid) return;
            els.borrowUmaGrid.querySelectorAll('.borrow-uma-card').forEach(card => {
                card.addEventListener('click', () => {
                    const key = card.getAttribute('data-key');
                    const list = (dashData && dashData.borrowUmas) || [];
                    const uma = list.find(u => borrowUmaKey(u) === key);
                    if (!uma) return;
                    if (selection.guestParent && borrowUmaKey(selection.guestParent) === key) {
                        selection.guestParent = null;
                    } else {
                        selection.guestParent = normalizeBorrowUmaSelection(uma);
                    }
                    renderBorrowUmas(list);
                    attachBorrowUmaHandlers();
                    bindSparkTooltips();
                    renderTeamPanel();
                    syncStartButton();
                    syncSelectionToServer();
                });
            });
        }
        function renderTrainees(umas) {
            const visibleTrainees = visibleLibraryItems(umas, 'trainees', state.librarySearch.trainees, [
                item => item.name,
                item => item.id
            ]);
            if (dashData) dashData.visibleTrainees = visibleTrainees;
            els.umaCount.innerText = `(${visibleTrainees.length}/${umas.length})`;
            els.umaGrid.innerHTML = visibleTrainees.map(uma => {
                const imgId = uma.id || '100101';
                const selected = selection.trainee && traineeKey(selection.trainee) === traineeKey(uma);
                return `<div class="grid-card ${selected ? 'selected' : ''}">
                    ${favoriteButtonHtml('trainees', uma)}
                    <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    <div class="grid-card-overlay"><span class="grid-card-name">${uma.name || 'Unknown'}</span></div>
                </div>`;
            }).join('');
        }
        function renderSupports(supports) {
            const rows = Array.isArray(supports) ? supports : [];
            const visibleSupports = filterSupports(rows);
            els.cardCount.innerText = `(${visibleSupports.length}/${rows.length})`;
            renderSupportInventoryControls();
            els.cardGrid.innerHTML = visibleSupports.map(card => {
                const imgId = card.id || '10001';
                return `<div class="grid-card support-card">
                    <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    <div class="grid-card-overlay">
                        <span class="grid-card-kicker">${(card.rarity || '?') + ' | ' + (card.type || '?')}</span>
                        <span class="grid-card-name">${card.name || 'Unknown'}</span>
                        <span class="grid-card-submeta">LB${Number(card.limit_break_count || 0)} | Stock ${Number(card.stock || 0)} | Lv${Number(card.support_card_level || card.level || 0)}</span>
                    </div>
                </div>`;
            }).join('');
        }
        function showDashboardView(data) {
            document.body.classList.add('dashboard-mode');
            els.loginView.style.display = 'none';
            if (els.teamTrialsScreen) els.teamTrialsScreen.hidden = true;
            els.dashboardView.style.display = '';
            els.dashboardView.classList.add('active');
            els.logoutBtn.style.display = 'block';
            if (els.teamBundleMenu) els.teamBundleMenu.style.display = 'block';
            if (els.topAuthRefreshBtn) els.topAuthRefreshBtn.style.display = 'block';
            if (els.teamTrialsScreenBtn) els.teamTrialsScreenBtn.style.display = 'block';
            if (els.syncDashboardBtn) els.syncDashboardBtn.style.display = 'block';
            if (els.refreshBackendBtn) els.refreshBackendBtn.style.display = 'block';
            showNavbar();
            renderAccountStrip(data.account);
            syncCareerNotifyToggle();
            syncDashboardHeight();
        }

        function autoLoadCareerSelection() {
            const activeCareer = state.account && state.account.career && state.account.career.active ? state.account.career : null;
            if (!activeCareer) return;

            if (activeCareer.deck_id && dashData.validDecks) {
                const deckIdx = dashData.validDecks.findIndex(d => Number(d.id) === Number(activeCareer.deck_id));
                if (deckIdx >= 0) {
                    selection.deck = dashData.validDecks[deckIdx];
                    const deckEls = document.querySelectorAll('.deck-container');
                    if (deckEls[deckIdx]) deckEls[deckIdx].classList.add('selected');
                }
            }

            if (activeCareer.card_id && dashData.umas) {
                const umaIdx = dashData.umas.findIndex(u => String(u.id) === String(activeCareer.card_id));
                if (umaIdx >= 0) {
                    selection.trainee = dashData.umas[umaIdx];
                    const umaEls = document.querySelectorAll('#uma-grid .grid-card');
                    if (umaEls[umaIdx]) umaEls[umaIdx].classList.add('selected');
                }
            }

            if (dashData.parents) {
                const p1 = activeCareer.parent_id_1;
                const p2 = activeCareer.parent_id_2;
                
                if (p1 || p2) {
                    dashData.parents.forEach((p, idx) => {
                        const pId = Number(p.instance_id);
                        if ((p1 && pId === Number(p1)) || (p2 && pId === Number(p2))) {
                            if (selection.veterans.length < 2 && !selection.veterans.find(v => Number(v.instance_id) === pId)) {
                                p._gridIdx = idx;
                                selection.veterans.push(p);
                                const parentEls = document.querySelectorAll('#parent-grid .grid-card');
                                if (parentEls[idx]) parentEls[idx].classList.add('selected');
                            }
                        }
                    });
                    updateVetSelectability();
                }
            }

            if (activeCareer.friend_viewer_id && activeCareer.friend_card_id) {
                state.pendingFriendSelection = {
                    viewer_id: String(activeCareer.friend_viewer_id),
                    support_card_id: String(activeCareer.friend_card_id)
                };
            }
        }

        function applyServerSelection(serverSelection) {
            if (!serverSelection) return;
            if (serverSelection.deck && dashData.validDecks) {
                const deckIdx = dashData.validDecks.findIndex(d => Number(d.id) === Number(serverSelection.deck.id));
                if (deckIdx >= 0) {
                    selection.deck = dashData.validDecks[deckIdx];
                    const deckEls = document.querySelectorAll('.deck-container');
                    if (deckEls[deckIdx]) deckEls[deckIdx].classList.add('selected');
                }
            }
            if (serverSelection.trainee && dashData.umas) {
                const umaIdx = dashData.umas.findIndex(u => String(u.id) === String(serverSelection.trainee.id));
                if (umaIdx >= 0) {
                    selection.trainee = dashData.umas[umaIdx];
                    const umaEls = document.querySelectorAll('#uma-grid .grid-card');
                    if (umaEls[umaIdx]) umaEls[umaIdx].classList.add('selected');
                }
            }
            if (serverSelection.veterans && dashData.parents) {
                serverSelection.veterans.forEach(v => {
                    const pIdx = dashData.parents.findIndex(p => Number(p.instance_id) === Number(v.instance_id));
                    if (pIdx >= 0 && selection.veterans.length < 2) {
                        const parent = dashData.parents[pIdx];
                        parent._gridIdx = pIdx;
                        selection.veterans.push(parent);
                        const parentEls = document.querySelectorAll('#parent-grid .grid-card');
                        if (parentEls[pIdx]) parentEls[pIdx].classList.add('selected');
                    }
                });
                updateVetSelectability();
            }
            if (serverSelection.friend) {
                state.pendingFriendSelection = {
                    viewer_id: String(serverSelection.friend.viewer_id),
                    support_card_id: String(serverSelection.friend.support_card_id)
                };
            }
            if (serverSelection.guestParent && serverSelection.guestParent.viewer_id && serverSelection.guestParent.trained_chara_id) {
                selection.guestParent = normalizeBorrowUmaSelection(serverSelection.guestParent);
            }
        }

        async function renderDashboard(data, options = {}) {
            dashData = data;
            state.loopActive = Boolean(data.loop && data.loop.active);
            if (state.loopActive) {
                state.loopEnabled = true;
                safeLocalSet('loopEnabled', '1');
                const loopMode = normalizeLoopMode((data.loop && data.loop.mode) || state.loopMode);
                state.loopMode = loopMode;
                safeLocalSet('loopMode', loopMode);
            }
            dashData.validDecks = data.decks.filter(isValidDeck);
            dashData.friends = data.friends || [];
            dashData.friendsList = data.friends_list || data.friendsList || [];
            dashData.friendFollowQuota = data.follow_quota || data.friendFollowQuota || null;
            dashData.friendExcludeIds = data.friendExcludeIds || [];
            dashData.borrowUmas = data.borrow_umas || dashData.borrowUmas || [];
            dashData.borrowQuota = data.borrow_quota || dashData.borrowQuota || null;
            if (data.dailyEvents) {
                renderDailyEventPanel(data.dailyEvents);
            }
            showDashboardView(data);
            bindLibrarySearchHandlers();
            renderCounts(data);
            renderDecks(dashData.validDecks);
            renderParents(data.parents);
            renderTrainees(dashData.umas);
            renderSupports(data.supports);
            resetSelection();
            if (data.selection) applyServerSelection(data.selection);
            autoLoadCareerSelection();
            renderDecks(dashData.validDecks);
            renderParents(data.parents);
            renderTrainees(dashData.umas);
            renderSupports(data.supports);
            renderBorrowUmas(dashData.borrowUmas);
            attachBorrowUmaHandlers();
            bindSparkTooltips();
            
            await loadPresets();
            await loadTeamBundlePresets();
            if (!dashData.friends.length) {
                loadFriends(false);
            } else {
                renderFriends();
            }
            bindSparkTooltips();
            attachSelectionHandlers();
            bindRaceHandlers();
            bindSkillHandlers();
            renderTeamPanel();
            ensureAffinityReference();
            
            startAccountSyncPolling();
            startRunnerPolling();
            await waitForDomPaint(2);
            setLoadingScreen(false);
            await waitForDomPaint(2);
            if (options.animateIntro !== false) {
                playBrandIntro();
                if (options.waitForIntro) await sleep(780);
            }
        }

        async function restoreSession() {
            try {
                const data = await apiJson('/api/session?t=' + Date.now());
                if (data && data.success) await renderDashboard(data, { animateIntro: true, waitForIntro: false });
                else {
                    hideNavbar();
                    setLoadingScreen(false);
                }
            } catch (e) {
                hideNavbar();
                setLoadingScreen(false);
            }
        }
        bindDelayControls();
        bindDeckAdviceToggle();
        bindSupportInventoryControls();
        bindDailyEventControls();
        bindFriendProfileModal();
        setLoadingScreen(true);
        restoreSession();

        /* ============================================================
           SWEEPY 改二 — RETUNED UI runtime
           Phase 2: account-strip retune + status bar
           Phase 3: library rail
           Phase 4: segmented controls
           Phase 5: race calendar modal
           Phase 6: rich parent cards
           Phase 7/8: filter systems
           Phase 9: deck detail
           Phase 10: borrow fallback picker
           + affinity computation
           ============================================================ */
        const retuned = {
            currentPane: 'parents',
            parentFilters: [],
            parentQuick: 'all',
            parentQuery: null,
            traineeFilters: [],
            borrowFilters: [],
            borrowQuick: 'all',
            borrowQuery: null,
            deckDetail: null,
            charaAptitudeMap: {},
            charaAptitudeReady: false,
            affinityReference: null,
            affinityReady: false,
            affinityPromise: null,
            calendarPicks: new Set(),
            calendarStyles: {},
            calendarOpen: false,
            sessionParentBaselineReady: false,
            sessionParentOrder: [],
            sessionParentSnapshots: {},
            charaNameLookup: {},
            factorCatalog: { stat: [], aptitude: [], green: [], white: [] },
            calendarSearch: ''
        };

        const aptRank = { G: 0, F: 1, E: 2, D: 3, C: 4, B: 5, A: 6, S: 7 };
        const aptLetterByVal = { 7: 'S', 6: 'A', 5: 'B', 4: 'C', 3: 'D', 2: 'E', 1: 'F', 0: 'G' };

        // Parent filters split between "generic" rows and "spark" rows.
        // Generic rows: { kind: 'generic', field, op, value }
        // Spark rows:   { kind: 'spark', sparkName, category, node, minStars }
        const PARENT_FILTER_FIELDS = [
            { id: 'name',     label: 'Name',          type: 'text'   },
            { id: 'affinity', label: 'Affinity',      type: 'number' },
            { id: 'whites',   label: 'White Factors', type: 'number' },
            { id: 'score',    label: 'Score',         type: 'number' }
        ];
        const NODE_GROUPS = {
            any:          ['self','p1','p2'],
            self:         ['self'],
            parents:      ['p1','p2']
        };
        const NODE_LABELS = { any: 'Any node', self: 'Self only', parents: 'Parents only' };
        const SPARK_CATEGORY_LABELS = {
            any:      'Any color',
            stat:     'Blue (stat)',
            aptitude: 'Pink (aptitude)',
            scenario: 'Green (unique)',
            chara:    'Green (unique)',
            skill:    'White (skill / race)',
            race:     'White (skill / race)'
        };
        const SPARK_CATEGORY_OPTIONS = [
            { id: 'any',      label: 'Any color' },
            { id: 'stat',     label: 'Blue (stat)' },
            { id: 'aptitude', label: 'Pink (aptitude)' },
            { id: 'green',    label: 'Green (unique)' },
            { id: 'white',    label: 'White (skill / race)' }
        ];
        function _matchesCategoryGroup(factCategory, group) {
            factCategory = normalizeSparkCategory(factCategory);
            if (group === 'any') return true;
            if (group === 'stat') return factCategory === 'stat';
            if (group === 'aptitude') return factCategory === 'aptitude';
            if (group === 'green') return factCategory === 'scenario' || factCategory === 'unique';
            if (group === 'white') return factCategory === 'skill' || factCategory === 'race';
            return false;
        }
        const LEGACY_FILTER_SORT_LABELS = {
            'best-fit': 'Best Match',
            bot: 'BOT Tag',
            starred: 'Starred',
            'date-made': 'Date Made',
            affinity: 'Affinity',
            score: 'Score',
            wins: 'Wins',
            whites: 'White Factors',
            'blue-stars': 'Blue Stars',
            'pink-stars': 'Pink Stars',
            'green-stars': 'Green Stars',
            'white-stars': 'White Stars',
            name: 'Name'
        };
        const LEGACY_FACTOR_GROUP_CONFIG = {
            stat:     { label: 'Blue',       datalist: 'factor-options-stat',     placeholder: 'Speed' },
            aptitude: { label: 'Pink',       datalist: 'factor-options-aptitude', placeholder: 'Turf' },
            green:    { label: 'Green',      datalist: 'factor-options-green',    placeholder: 'Any' },
            white:    { label: 'White',      datalist: 'factor-options-white',    placeholder: 'Skill or race name' },
            preferred:{ label: 'Pref White', datalist: 'factor-options-white',    placeholder: 'Preferred white factor' }
        };
        function createLegacyFilterState() {
            return {
                open: true,
                sortMode: 'best-fit',
                sortDir: 'desc',
                mainFactors: [],
                inheritanceFactors: [],
                mainMinWhites: 0,
                general: {
                    minAffinity: 0,
                    minWins: 0,
                    minWhites: 0,
                    minScore: 0
                },
                totals: {
                    stat: 0,
                    aptitude: 0,
                    green: 0,
                    white: 0
                }
            };
        }
        retuned.parentQuery = retuned.parentQuery || createLegacyFilterState();
        retuned.borrowQuery = retuned.borrowQuery || createLegacyFilterState();
        const TRAINEE_FILTER_FIELDS = [
            { id: 'name',       label: 'Name',          type: 'text' },
            { id: 'rarity',     label: 'Rarity',        type: 'enum', options: ['3★','4★','5★'] },
            { id: 'growth',     label: 'Growth Bonus',  type: 'enum', options: ['Speed','Stamina','Power','Guts','Wit'] },
            { id: 'aptTurf',   label: 'Turf apt ≥',    type: 'aptitude' },
            { id: 'aptDirt',   label: 'Dirt apt ≥',    type: 'aptitude' },
            { id: 'aptSprint', label: 'Sprint apt ≥',  type: 'aptitude' },
            { id: 'aptMile',   label: 'Mile apt ≥',    type: 'aptitude' },
            { id: 'aptMedium', label: 'Medium apt ≥',  type: 'aptitude' },
            { id: 'aptLong',   label: 'Long apt ≥',    type: 'aptitude' }
        ];

        function fieldDef(list, id) { return list.find(f => f.id === id) || list[0]; }
        function opsForField(field) {
            if (field.type === 'text') return ['contains'];
            if (field.type === 'enum') return ['='];
            if (field.type === 'aptitude') return ['at least'];
            return ['≥', '≤', '='];
        }

        /* ---------- chara aptitude / lineage data ---------- */
        async function ensureCharaAptitudeMap() {
            if (retuned.charaAptitudeReady) return retuned.charaAptitudeMap;
            try {
                const res = await fetch('/assets/data/chara_aptitude_map.json?t=' + Date.now());
                if (res.ok) {
                    const json = await res.json();
                    retuned.charaAptitudeMap = json && typeof json === 'object' ? json : {};
                }
            } catch (e) {}
            retuned.charaAptitudeReady = true;
            return retuned.charaAptitudeMap;
        }
        function charaAptitudeFor(cardOrCharaId) {
            if (!cardOrCharaId) return null;
            const map = retuned.charaAptitudeMap || {};
            const cid = String(cardOrCharaId);
            if (map[cid]) return map[cid];
            // chara_id derived from card_id (first 4 digits)
            const charaId = cid.slice(0, 4);
            return map[charaId] || null;
        }

        /* ---------- Affinity computation ----------
           Uses shared blue/pink/green factor names across the two parents' "self" nodes,
           plus shared base aptitude (terrain + distance) when available. Returns:
             { score: int, symbol: '◎'|'○'|'△'|'×', label: 'double'|'circle'|'triangle'|'cross' }
        */
        function _factorKey(f) { return normalizeSparkCategory(f && f.category, f) + ':' + ((f && f.name) || '').toLowerCase(); }
        function _factorMap(factors) {
            const m = {};
            (factors || []).forEach(f => {
                const k = _factorKey(f);
                if (!k) return;
                m[k] = (m[k] || 0) + (f.stars || 1);
            });
            return m;
        }
        function _pairwiseFactorScore(aFactors, bFactors) {
            const a = _factorMap(aFactors);
            const b = _factorMap(bFactors);
            let score = 0;
            Object.keys(a).forEach(k => {
                if (!b[k]) return;
                const minStars = Math.min(a[k], b[k]);
                const cat = k.split(':')[0];
                const weight = cat === 'aptitude' ? 24 : cat === 'stat' ? 18 : cat === 'skill' ? 9 : 14;
                score += weight * minStars;
            });
            return score;
        }
        function _pairwiseAptitudeBonus(aChara, bChara) {
            if (!aChara || !bChara) return 0;
            let s = 0;
            if (aChara.terrain && bChara.terrain && aChara.terrain === bChara.terrain) s += 18;
            if (aChara.distance && bChara.distance && aChara.distance === bChara.distance) s += 18;
            if (aChara.style && bChara.style && aChara.style === bChara.style) s += 12;
            return s;
        }
        function computeParentPairAffinity(p1, p2) {
            const selfA = (p1 && p1.tree && p1.tree.self) || {};
            const selfB = (p2 && p2.tree && p2.tree.self) || {};
            const factorScore = _pairwiseFactorScore(selfA.factors, selfB.factors);
            const aptA = charaAptitudeFor(p1 && p1.card_id);
            const aptB = charaAptitudeFor(p2 && p2.card_id);
            const aptBonus = _pairwiseAptitudeBonus(aptA, aptB);
            return Math.min(220, factorScore + aptBonus);
        }
        function computeTriangleAffinity(trainee, parent1, parent2) {
            const tApt = charaAptitudeFor(trainee && (trainee.card_id || trainee.id));
            let total = 0;
            if (parent1) {
                const p1Apt = charaAptitudeFor(parent1.card_id);
                total += _pairwiseAptitudeBonus(tApt, p1Apt);
            }
            if (parent2) {
                const p2Apt = charaAptitudeFor(parent2.card_id);
                total += _pairwiseAptitudeBonus(tApt, p2Apt);
            }
            if (parent1 && parent2) total += computeParentPairAffinity(parent1, parent2);
            return Math.min(220, total);
        }
        /* Trainee × Parent only (no other parent selected). Used so the parents
           list still has something to sort/show when the user has picked a
           trainee but no veterans yet. */
        function computeTraineeParentAffinity(trainee, parent) {
            const tApt = charaAptitudeFor(trainee && (trainee.card_id || trainee.id));
            const pApt = charaAptitudeFor(parent && parent.card_id);
            let score = _pairwiseAptitudeBonus(tApt, pApt);
            const tree = (parent && parent.tree) || {};
            // Effective inheritance only comes from the selected parent plus its two direct parents.
            const nodeWeight = { self: 1.0, p1: 0.55, p2: 0.55, gp1: 0.18, gp2: 0.18, gp3: 0.18, gp4: 0.18 };
            LINEAGE_NODES.forEach(nodeId => {
                const node = tree[nodeId];
                if (!node || !node.factors) return;
                const w = nodeWeight[nodeId] || 0;
                node.factors.forEach(f => { score += (f.stars || 0) * w; });
            });
            // Bonus for factor names aligning with the trainee's preferred terrain / distance
            if (tApt) {
                const target = [tApt.terrain, tApt.distance].filter(Boolean).map(s => s.toLowerCase());
                ['self', 'p1', 'p2'].forEach(nodeId => {
                    const node = tree[nodeId];
                    if (!node || !node.factors) return;
                    node.factors.forEach(f => {
                        const fname = String(f.name || '').toLowerCase();
                        if (target.some(t => fname === t || fname.includes(t))) {
                            score += (f.stars || 0) * 6;
                        }
                    });
                });
            }
            return Math.min(220, Math.round(score));
        }
        function affinitySymbol(score) {
            if (score >= 150) return { symbol: '◎', label: 'double', cls: 'aff-icon-double' };
            if (score >= 50)  return { symbol: '○', label: 'circle', cls: 'aff-icon-circle' };
            if (score >= 25)  return { symbol: '△', label: 'triangle', cls: 'aff-icon-triangle' };
            return { symbol: '×', label: 'cross', cls: 'aff-icon-cross' };
        }

        /* ---------- Spark aggregation across full 7-node lineage ----------
           Returns a Map keyed by "category:name" with:
             { category, name, maxStars, totalStars, count, nodes[{node,stars}],
               perInsp, perRun, selfStars }
           Per-run %: probability the spark contributes to a single career via
           inspiration events. Uses a simple node-weight × stars/9 model summed
           over nodes, then 1 - (1-p)^3 for 3 inspirations per career.
        */
        function cardToCharaId(cardOrCharaId) {
            const raw = Number(cardOrCharaId || 0);
            if (!Number.isFinite(raw) || raw <= 0) return 0;
            return raw >= 100000 ? Math.floor(raw / 100) : Math.trunc(raw);
        }
        function normalizeBorrowUmaSelection(uma) {
            if (!uma) return null;
            return {
                ...uma,
                viewer_id: Number(uma.viewer_id || 0),
                trained_chara_id: Number(uma.trained_chara_id || uma.instance_id || 0),
                instance_id: Number(uma.instance_id || uma.trained_chara_id || 0),
                rank: Number(uma.rank || uma.chara_grade || 0),
                chara_name: uma.chara_name || uma.name || '',
                trainer_name: uma.trainer_name || '',
                card_id: Number(uma.card_id || 0),
                tree: uma.tree || {},
                stats: uma.stats || statsFromParentFields(uma),
                skills: normalizedParentSkills(uma),
                estimated_skill_points: estimatedParentSkillPoints(uma),
                score: uma.score != null ? Number(uma.score) : (uma.rank_score != null ? Number(uma.rank_score) : null),
                created_at: uma.created_at || uma.date_made || '',
                updated_at: uma.updated_at || '',
                _borrowKey: uma._borrowKey || (uma.viewer_id && uma.trained_chara_id ? borrowUmaKey(uma) : '')
            };
        }
        async function ensureAffinityReference() {
            if (retuned.affinityReady && retuned.affinityReference) return retuned.affinityReference;
            if (retuned.affinityPromise) return retuned.affinityPromise;
            retuned.affinityPromise = (async () => {
                try {
                    const [relationRes, memberRes] = await Promise.all([
                        fetch('/assets/data/succession_relation.json?t=' + Date.now()),
                        fetch('/assets/data/succession_relation_member.json?t=' + Date.now())
                    ]);
                    if (!relationRes.ok || !memberRes.ok) throw new Error('affinity reference load failed');
                    const [relationJson, memberJson] = await Promise.all([
                        relationRes.json(),
                        memberRes.json()
                    ]);
                    const pointsByType = {};
                    (Array.isArray(relationJson) ? relationJson : []).forEach(row => {
                        const typeId = Number(row && row.relation_type);
                        if (!Number.isFinite(typeId)) return;
                        pointsByType[typeId] = Number(row && row.relation_point) || 0;
                    });
                    const relationTypesByCharaId = {};
                    (Array.isArray(memberJson) ? memberJson : []).forEach(row => {
                        const charaId = Number(row && row.chara_id);
                        const typeId = Number(row && row.relation_type);
                        if (!Number.isFinite(charaId) || !Number.isFinite(typeId)) return;
                        if (!relationTypesByCharaId[charaId]) relationTypesByCharaId[charaId] = new Set();
                        relationTypesByCharaId[charaId].add(typeId);
                    });
                    retuned.affinityReference = {
                        pointsByType,
                        relationTypesByCharaId
                    };
                } catch (e) {
                    console.error('Failed to load affinity reference data', e);
                    retuned.affinityReference = null;
                }
                retuned.affinityReady = true;
                retuned.affinityPromise = null;
                if (dashData && dashData.parents) renderParentsRetuned(dashData.parents);
                if (dashData && dashData.borrowUmas) renderBorrowUmasRetuned(dashData.borrowUmas);
                renderTeamPanel();
                return retuned.affinityReference;
            })();
            return retuned.affinityPromise;
        }
        function getDirectLineage(parent) {
            const tree = (parent && parent.tree) || {};
            const self = tree.self || {};
            const p1 = tree.p1 || {};
            const p2 = tree.p2 || {};
            return {
                self: {
                    charaId: cardToCharaId(self.card_id || parent && parent.card_id),
                    saddleIds: Array.isArray(self.win_saddle_ids) ? self.win_saddle_ids.map(Number).filter(Boolean) : []
                },
                p1: {
                    charaId: cardToCharaId(p1.card_id),
                    saddleIds: Array.isArray(p1.win_saddle_ids) ? p1.win_saddle_ids.map(Number).filter(Boolean) : []
                },
                p2: {
                    charaId: cardToCharaId(p2.card_id),
                    saddleIds: Array.isArray(p2.win_saddle_ids) ? p2.win_saddle_ids.map(Number).filter(Boolean) : []
                }
            };
        }
        function lineageNodeHasRaceField(node) {
            return !!(node && Array.isArray(node.win_saddle_ids));
        }
        function parentHasAffinityRaceData(parent) {
            const tree = (parent && parent.tree) || {};
            return lineageNodeHasRaceField(tree.self) || lineageNodeHasRaceField(tree.p1) || lineageNodeHasRaceField(tree.p2);
        }
        function affinityWarningText() {
            if (!selection.trainee) return '';
            const parentList = Array.isArray(dashData && dashData.parents) ? dashData.parents : [];
            const borrowList = Array.isArray(dashData && dashData.borrowUmas) ? dashData.borrowUmas : [];
            if (parentList.length && !parentList.some(parentHasAffinityRaceData)) {
                return 'Affinity is base-only: restart the backend and Sync Game Data to load saddle overlap.';
            }
            if (borrowList.length && !borrowList.some(parentHasAffinityRaceData)) {
                return 'Borrow affinity is base-only: refresh borrow data to load saddle overlap.';
            }
            return '';
        }
        function relationTypesForChara(charaId) {
            const ref = retuned.affinityReference;
            const relationTypesByCharaId = ref && ref.relationTypesByCharaId;
            return (relationTypesByCharaId && relationTypesByCharaId[Number(charaId)]) || new Set();
        }
        function sumSharedRelationSets() {
            const ref = retuned.affinityReference;
            if (!ref) return 0;
            const sets = Array.from(arguments);
            if (sets.length < 2 || sets.some(set => !set || !set.size)) return 0;
            let total = 0;
            sets[0].forEach(typeId => {
                const shared = sets.slice(1).every(set => set.has(typeId));
                if (shared) total += Number(ref.pointsByType[typeId]) || 0;
            });
            return total;
        }
        function sharedRelationPoints() {
            const charaIds = Array.from(arguments).map(Number).filter(Boolean);
            if (charaIds.length < 2) return 0;
            const sets = charaIds.map(relationTypesForChara);
            return sumSharedRelationSets.apply(null, sets);
        }
        function overlapSaddlePoints(parentSaddleIds, grandparentSaddleIds) {
            const gpSet = new Set((grandparentSaddleIds || []).map(Number).filter(Boolean));
            if (!gpSet.size) return 0;
            let matches = 0;
            for (const rawId of (parentSaddleIds || [])) {
                const saddleId = Number(rawId);
                if (gpSet.has(saddleId)) matches += 1;
            }
            return matches;
        }
        function computeSingleParentAffinityGame(trainee, parent) {
            if (!retuned.affinityReference || !trainee || !parent) return null;
            const traineeId = cardToCharaId(trainee.card_id || trainee.id);
            const lineage = getDirectLineage(parent);
            const selfId = lineage.self.charaId;
            if (!traineeId || !selfId || traineeId === selfId) return null;
            const gp1AffinityId = (lineage.p1.charaId && lineage.p1.charaId !== traineeId) ? lineage.p1.charaId : 0;
            const gp2AffinityId = (lineage.p2.charaId && lineage.p2.charaId !== traineeId) ? lineage.p2.charaId : 0;
            const mainParent = sharedRelationPoints(traineeId, selfId);
            const grandparent11 = gp1AffinityId ? sharedRelationPoints(traineeId, selfId, gp1AffinityId) : 0;
            const grandparent12 = gp2AffinityId ? sharedRelationPoints(traineeId, selfId, gp2AffinityId) : 0;
            const raceBonusTotal =
                overlapSaddlePoints(lineage.self.saddleIds, lineage.p1.saddleIds) +
                overlapSaddlePoints(lineage.self.saddleIds, lineage.p2.saddleIds);
            return {
                total: mainParent + grandparent11 + grandparent12 + raceBonusTotal,
                breakdown: {
                    mainParent1: mainParent,
                    mainParent2: 0,
                    grandparent11,
                    grandparent12,
                    grandparent21: 0,
                    grandparent22: 0,
                    parents: 0,
                    raceBonusTotal,
                    epithetBonusTotal: 0
                }
            };
        }
        function computeProjectedAffinityGame(trainee, parent1, parent2) {
            if (!retuned.affinityReference || !trainee || !parent1 || !parent2) return null;
            const side1 = computeSingleParentAffinityGame(trainee, parent1);
            const side2 = computeSingleParentAffinityGame(trainee, parent2);
            if (!side1 || !side2) return null;
            const left = getDirectLineage(parent1);
            const right = getDirectLineage(parent2);
            const parents = sharedRelationPoints(left.self.charaId, right.self.charaId);
            const raceBonusTotal = side1.breakdown.raceBonusTotal + side2.breakdown.raceBonusTotal;
            return {
                total: side1.total + side2.total + parents,
                breakdown: {
                    mainParent1: side1.breakdown.mainParent1,
                    mainParent2: side2.breakdown.mainParent1,
                    grandparent11: side1.breakdown.grandparent11,
                    grandparent12: side1.breakdown.grandparent12,
                    grandparent21: side2.breakdown.grandparent11,
                    grandparent22: side2.breakdown.grandparent12,
                    parents,
                    raceBonusTotal,
                    epithetBonusTotal: 0
                }
            };
        }
        function directParentCharaId(parent) {
            if (!parent) return 0;
            return cardToCharaId(parent.card_id || parent.tree && parent.tree.self && parent.tree.self.card_id);
        }
        function candidateAffinityDetail(parent, source = null) {
            if (!retuned.affinityReference || !selection.trainee || !parent) return null;
            const inferredSource = source || (parent && parent._borrowKey ? 'borrow' : 'owned');
            const candidateCharaId = directParentCharaId(parent);
            const traineeCharaId = cardToCharaId(selection.trainee && (selection.trainee.card_id || selection.trainee.id));
            if (!candidateCharaId || !traineeCharaId || candidateCharaId === traineeCharaId) return null;

            const vet0 = selection.veterans[0] || null;
            const vet1 = selection.veterans[1] || null;
            const guest = selection.guestParent || null;
            const candidateKey = parentKey(parent);

            if (inferredSource === 'borrow') {
                const ownParent = vet0 || null;
                if (ownParent && directParentCharaId(ownParent) === candidateCharaId) return null;
                return ownParent
                    ? computeProjectedAffinityGame(selection.trainee, ownParent, parent)
                    : computeSingleParentAffinityGame(selection.trainee, parent);
            }

            if (guest) {
                if (directParentCharaId(guest) === candidateCharaId && parentKey(guest) !== candidateKey) return null;
                return computeProjectedAffinityGame(selection.trainee, parent, guest);
            }

            if (vet0 && vet1) {
                const isVet0 = parentKey(vet0) === candidateKey;
                const isVet1 = parentKey(vet1) === candidateKey;
                if (isVet0 || isVet1) return computeProjectedAffinityGame(selection.trainee, vet0, vet1);
                return null;
            }

            if (vet0) {
                if (parentKey(vet0) === candidateKey) return computeSingleParentAffinityGame(selection.trainee, parent);
                if (directParentCharaId(vet0) === candidateCharaId) return null;
                return computeProjectedAffinityGame(selection.trainee, vet0, parent);
            }

            return computeSingleParentAffinityGame(selection.trainee, parent);
        }
        function affinitySymbol(score) {
            if (score > 150) return { symbol: '◎', label: 'double', cls: 'aff-icon-double' };
            if (score > 50) return { symbol: '○', label: 'circle', cls: 'aff-icon-circle' };
            return { symbol: '△', label: 'triangle', cls: 'aff-icon-triangle' };
        }
        function affinitySymbol(score) {
            if (score >= 150) return { symbol: '\u25CE', label: 'double', cls: 'aff-icon-double' };
            if (score >= 50) return { symbol: '\u25CB', label: 'circle', cls: 'aff-icon-circle' };
            if (score >= 25) return { symbol: '\u25B3', label: 'triangle', cls: 'aff-icon-triangle' };
            return { symbol: '\u00D7', label: 'cross', cls: 'aff-icon-cross' };
        }
        const EFFECTIVE_SPARK_NODES = ['self','p1','p2'];
        const NODE_WEIGHTS = { self: 0.30, p1: 0.22, p2: 0.22, gp1: 0.065, gp2: 0.065, gp3: 0.065, gp4: 0.065 };
        const LINEAGE_NODES = ['self','p1','p2','gp1','gp2','gp3','gp4'];
        function normalizeSparkCategory(category, factor = null) {
            const raw = String(category || (factor && factor.category) || '').toLowerCase();
            const id = Number(factor && factor.id || 0);
            const baseId = Number.isFinite(id) && id > 0 ? Math.floor(id / 100) : 0;
            if (raw === 'blue') return 'stat';
            if (raw === 'pink') return 'aptitude';
            if (raw === 'green' || raw === 'chara' || raw === 'character') return 'unique';
            if (raw === 'white') return 'skill';
            if (raw === 'scenario') return 'scenario';
            if (raw === 'unique') return 'unique';
            if (raw === 'skill' && baseId >= 100000 && baseId < 200000) return 'unique';
            if (raw === 'stat' || raw === 'aptitude' || raw === 'race' || raw === 'skill') return raw;
            if (baseId >= 100000 && baseId < 200000) return 'unique';
            if (baseId >= 30000 && baseId < 40000) return 'scenario';
            if (baseId >= 20000 && baseId < 30000) return 'skill';
            if (baseId >= 10000 && baseId < 20000) return 'race';
            if (baseId >= 1 && baseId <= 5) return 'stat';
            if (baseId >= 11 && baseId <= 34) return 'aptitude';
            return raw || 'other';
        }
        function sparkGroupFromCategory(category, factor = null) {
            const normalized = normalizeSparkCategory(category, factor);
            if (normalized === 'stat') return 'blue';
            if (normalized === 'aptitude') return 'pink';
            if (normalized === 'scenario' || normalized === 'unique') return 'green';
            return 'white';
        }
        function computeSparkAggregates(parent, nodes = EFFECTIVE_SPARK_NODES) {
            const tree = (parent && parent.tree) || {};
            const map = {};
            (nodes || EFFECTIVE_SPARK_NODES).forEach(nodeId => {
                const node = tree[nodeId];
                if (!node || !Array.isArray(node.factors)) return;
                node.factors.forEach(f => {
                    if (!f) return;
                    const category = normalizeSparkCategory(f.category, f);
                    const key = category + ':' + String(f.name || '').toLowerCase();
                    if (!map[key]) map[key] = { category, name: f.name, maxStars: 0, totalStars: 0, count: 0, nodes: [], selfStars: 0 };
                    const e = map[key];
                    const s = f.stars || 0;
                    e.maxStars = Math.max(e.maxStars, s);
                    e.totalStars += s;
                    e.count += 1;
                    e.nodes.push({ node: nodeId, stars: s });
                    if (nodeId === 'self') e.selfStars = s;
                });
            });
            Object.values(map).forEach(e => {
                let perInsp = 0;
                e.nodes.forEach(({ node, stars }) => {
                    perInsp += (NODE_WEIGHTS[node] || 0) * (stars / 9);
                });
                e.perInsp = perInsp;
                e.perRun = 1 - Math.pow(1 - perInsp, 3);
            });
            return map;
        }
        function sparkAggList(parent, nodes = EFFECTIVE_SPARK_NODES) { return Object.values(computeSparkAggregates(parent, nodes)); }
        function parentMatchesSparkFilter(parent, spec) {
            // spec: { sparkName, category, node, minStars }
            const tree = (parent && parent.tree) || {};
            const targetName = String(spec.sparkName || '').trim().toLowerCase();
            const targetCat = spec.category || 'any';
            const nodes = NODE_GROUPS[spec.node || 'any'] || NODE_GROUPS.any;
            let totalStars = 0;
            for (const nodeId of nodes) {
                const node = tree[nodeId];
                if (!node || !node.factors) continue;
                for (const f of node.factors) {
                    if (!f) continue;
                    if (targetName && !String(f.name || '').toLowerCase().includes(targetName)) continue;
                    if (!_matchesCategoryGroup(normalizeSparkCategory(f.category, f), targetCat)) continue;
                    totalStars += (f.stars || 0);
                }
            }
            return totalStars >= (Number(spec.minStars) || 0);
        }
        function factorGroupFromCategory(category, factor = null) {
            category = normalizeSparkCategory(category, factor);
            if (category === 'stat') return 'stat';
            if (category === 'aptitude') return 'aptitude';
            if (category === 'scenario' || category === 'unique') return 'green';
            if (category === 'skill' || category === 'race') return 'white';
            return null;
        }
        function collectFactorEntries(parent, nodes = EFFECTIVE_SPARK_NODES) {
            const tree = (parent && parent.tree) || {};
            const list = [];
            nodes.forEach(nodeId => {
                const node = tree[nodeId];
                if (!node || !Array.isArray(node.factors)) return;
                node.factors.forEach(f => {
                    if (!f) return;
                    list.push({
                        node: nodeId,
                        category: normalizeSparkCategory(f.category, f),
                        group: factorGroupFromCategory(f.category, f),
                        name: String(f.name || ''),
                        stars: Number(f.stars) || 0
                    });
                });
            });
            return list;
        }
        function factorTotalsByGroup(parent, nodes = EFFECTIVE_SPARK_NODES) {
            const totals = { stat: 0, aptitude: 0, green: 0, white: 0 };
            collectFactorEntries(parent, nodes).forEach(entry => {
                if (!entry.group) return;
                totals[entry.group] += entry.stars;
            });
            return totals;
        }
        function countFactorGroup(parent, group, nodes = EFFECTIVE_SPARK_NODES) {
            return collectFactorEntries(parent, nodes).filter(entry => entry.group === group).length;
        }
        function countWhiteFactors(parent, nodes = EFFECTIVE_SPARK_NODES) {
            return countFactorGroup(parent, 'white', nodes);
        }
        function countMainWhiteFactors(parent) {
            return countWhiteFactors(parent, ['self']);
        }
        function countEffectiveWins(parent) {
            const tree = (parent && parent.tree) || {};
            return EFFECTIVE_SPARK_NODES.reduce((sum, nodeId) => {
                const wins = tree[nodeId] && tree[nodeId].wins;
                return sum + (wins && Number.isFinite(Number(wins.total)) ? Number(wins.total) : 0);
            }, 0);
        }
        function matchFactorSpec(parent, scope, spec) {
            const nodes = scope === 'main' ? ['self'] : ['p1','p2'];
            const entries = collectFactorEntries(parent, nodes).filter(entry => {
                if (entry.group !== spec.category) return false;
                const targetName = String(spec.name || '').trim().toLowerCase();
                if (!targetName || targetName === 'any') return true;
                return entry.name.toLowerCase().includes(targetName);
            });
            const totalStars = entries.reduce((sum, entry) => sum + entry.stars, 0);
            const minStars = Math.max(0, Number(spec.minStars) || 0);
            const maxStars = Math.max(0, Number(spec.maxStars) || 0);
            const passesMin = totalStars >= minStars;
            const passesMax = !maxStars || totalStars <= maxStars;
            return {
                totalStars,
                matches: entries.length,
                pass: passesMin && passesMax
            };
        }
        function collectFactorCatalog() {
            const catalog = { stat: new Set(), aptitude: new Set(), green: new Set(), white: new Set() };
            const lists = [];
            if (Array.isArray(dashData && dashData.parents)) lists.push(dashData.parents);
            if (Array.isArray(dashData && dashData.borrowUmas)) {
                lists.push(dashData.borrowUmas.map(uma => normalizeBorrowUmaSelection(uma)));
            }
            lists.forEach(list => {
                list.forEach(parent => {
                    collectFactorEntries(parent, EFFECTIVE_SPARK_NODES).forEach(entry => {
                        if (entry.group && entry.name) catalog[entry.group].add(entry.name);
                    });
                });
            });
            retuned.factorCatalog = {
                stat: Array.from(catalog.stat).sort((a, b) => a.localeCompare(b)),
                aptitude: Array.from(catalog.aptitude).sort((a, b) => a.localeCompare(b)),
                green: Array.from(catalog.green).sort((a, b) => a.localeCompare(b)),
                white: Array.from(catalog.white).sort((a, b) => a.localeCompare(b))
            };
            Object.entries({
                stat: 'factor-options-stat',
                aptitude: 'factor-options-aptitude',
                green: 'factor-options-green',
                white: 'factor-options-white'
            }).forEach(([group, id]) => {
                const el = document.getElementById(id);
                if (!el) return;
                el.innerHTML = retuned.factorCatalog[group].map(name => `<option value="${escapeAttr(name)}"></option>`).join('');
            });
            return retuned.factorCatalog;
        }
        function filterStateFor(kind) {
            return kind === 'borrow' ? retuned.borrowQuery : retuned.parentQuery;
        }
        function factorListFor(query, scope) {
            return scope === 'main' ? query.mainFactors : query.inheritanceFactors;
        }
        function createFactorSpec(category, preferred = false) {
            return {
                category,
                preferred: !!preferred,
                name: '',
                minStars: 1,
                maxStars: ''
            };
        }
        function evaluateLegacyCandidate(parent, query, options = {}) {
            const source = options.source || 'owned';
            const affinity = parentMetric(parent, 'affinity', { source });
            const totals = factorTotalsByGroup(parent, EFFECTIVE_SPARK_NODES);
            const whiteCount = countMainWhiteFactors(parent);
            const mainWhiteCount = countMainWhiteFactors(parent);
            const wins = countEffectiveWins(parent);
            const score = parent && parent.score != null ? Number(parent.score) : null;
            let preferredMatches = 0;
            let preferredStars = 0;

            for (const scope of ['inheritance', 'main']) {
                const rows = factorListFor(query, scope);
                for (const row of rows) {
                    const activeName = String(row.name || '').trim();
                    const activeRange = Number(row.minStars) > 0 || Number(row.maxStars) > 0;
                    if (!activeName && !activeRange) continue;
                    const match = matchFactorSpec(parent, scope, row);
                    if (row.preferred) {
                        if (match.pass && match.matches > 0) {
                            preferredMatches += 1;
                            preferredStars += match.totalStars;
                        }
                    } else if (!match.pass || !match.matches) {
                        return { passes: false, metrics: null };
                    }
                }
            }

            if (Number(query.mainMinWhites) > 0 && mainWhiteCount < Number(query.mainMinWhites)) {
                return { passes: false, metrics: null };
            }
            if (Number(query.general.minAffinity) > 0 && ((affinity == null ? -1 : affinity) < Number(query.general.minAffinity))) {
                return { passes: false, metrics: null };
            }
            if (Number(query.general.minWins) > 0 && wins < Number(query.general.minWins)) {
                return { passes: false, metrics: null };
            }
            if (Number(query.general.minWhites) > 0 && whiteCount < Number(query.general.minWhites)) {
                return { passes: false, metrics: null };
            }
            if (Number(query.general.minScore) > 0 && ((score == null ? -1 : score) < Number(query.general.minScore))) {
                return { passes: false, metrics: null };
            }
            if (Number(query.totals.stat) > 0 && totals.stat < Number(query.totals.stat)) {
                return { passes: false, metrics: null };
            }
            if (Number(query.totals.aptitude) > 0 && totals.aptitude < Number(query.totals.aptitude)) {
                return { passes: false, metrics: null };
            }
            if (Number(query.totals.green) > 0 && totals.green < Number(query.totals.green)) {
                return { passes: false, metrics: null };
            }
            if (Number(query.totals.white) > 0 && totals.white < Number(query.totals.white)) {
                return { passes: false, metrics: null };
            }

            return {
                passes: true,
                metrics: {
                    bot: parent && parent.made_by_bot ? 1 : 0,
                    affinity,
                    wins,
                    whites: whiteCount,
                    score,
                    mainWhiteCount,
                    totals,
                    preferredMatches,
                    preferredStars
                }
            };
        }
        function legacyPrimarySortValue(metrics, sortMode) {
            if (!metrics) return null;
            switch (sortMode) {
                case 'bot': return metrics.bot;
                case 'affinity': return metrics.affinity;
                case 'score': return metrics.score;
                case 'wins': return metrics.wins;
                case 'whites': return metrics.whites;
                case 'blue-stars': return metrics.totals.stat;
                case 'pink-stars': return metrics.totals.aptitude;
                case 'green-stars': return metrics.totals.green;
                case 'white-stars': return metrics.totals.white;
                case 'name': return null;
                case 'best-fit':
                default:
                    return (metrics.preferredMatches * 1000) + (metrics.preferredStars * 100) + (metrics.affinity || 0);
            }
        }
        function coerceDateSortValue(raw) {
            if (raw == null || raw === '') return null;
            if (typeof raw === 'number') {
                if (!Number.isFinite(raw) || raw <= 0) return null;
                return raw > 1e12 ? raw : (raw > 1e9 ? raw * 1000 : null);
            }
            const text = String(raw || '').trim();
            if (!text) return null;
            if (/^\d+$/.test(text)) {
                const numeric = Number(text);
                if (!Number.isFinite(numeric) || numeric <= 0) return null;
                return numeric > 1e12 ? numeric : (numeric > 1e9 ? numeric * 1000 : null);
            }
            const parsed = Date.parse(text);
            return Number.isFinite(parsed) ? parsed : null;
        }
        function parentDateMadeSortValue(parent, source = 'owned') {
            const info = (parent && parent.bot_parent_info) || {};
            const direct = [
                parent && parent.date_made,
                parent && parent.created_at,
                parent && parent.registered_at,
                parent && parent.updated_at,
                parent && parent.trained_at,
                parent && parent.created_time,
                info && info.registered_at,
                info && info.created_at,
            ];
            for (const value of direct) {
                const coerced = coerceDateSortValue(value);
                if (coerced != null) return coerced;
            }
            if (source === 'borrow' || (parent && (parent.viewer_id || parent._borrowKey))) {
                const trainedId = Number(parent && (parent.trained_chara_id || parent.instance_id || 0));
                return Number.isFinite(trainedId) && trainedId > 0 ? trainedId : null;
            }
            const instanceId = Number(parent && (parent.instance_id || 0));
            return Number.isFinite(instanceId) && instanceId > 0 ? instanceId : null;
        }
        function legacyFavoriteValue(parent, source = 'owned') {
            const type = source === 'borrow' || (parent && (parent.viewer_id || parent._borrowKey)) ? 'borrowUmas' : 'parents';
            return isFavorite(type, parent) ? 1 : 0;
        }
        function compareNullableNumber(a, b, dir = 'desc') {
            const nullSentinel = dir === 'asc' ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY;
            const av = a == null ? nullSentinel : Number(a);
            const bv = b == null ? nullSentinel : Number(b);
            return dir === 'asc' ? av - bv : bv - av;
        }
        function sortLegacyCandidates(items, query) {
            const sortMode = query.sortMode || 'best-fit';
            const sortDir = query.sortDir || 'desc';
            return items.slice().sort((left, right) => {
                const leftSource = left && left.parent && (left.parent.viewer_id || left.parent._borrowKey) ? 'borrow' : 'owned';
                const rightSource = right && right.parent && (right.parent.viewer_id || right.parent._borrowKey) ? 'borrow' : 'owned';
                if (sortMode === 'name') {
                    const cmp = String(left.parent.name || '').localeCompare(String(right.parent.name || ''));
                    if (cmp !== 0) return sortDir === 'asc' ? cmp : -cmp;
                } else if (sortMode === 'starred') {
                    const starred = compareNullableNumber(
                        legacyFavoriteValue(left.parent, leftSource),
                        legacyFavoriteValue(right.parent, rightSource),
                        sortDir
                    );
                    if (starred !== 0) return starred;
                } else if (sortMode === 'date-made') {
                    const dated = compareNullableNumber(
                        parentDateMadeSortValue(left.parent, leftSource),
                        parentDateMadeSortValue(right.parent, rightSource),
                        sortDir
                    );
                    if (dated !== 0) return dated;
                } else {
                    const primary = compareNullableNumber(
                        legacyPrimarySortValue(left.metrics, sortMode),
                        legacyPrimarySortValue(right.metrics, sortMode),
                        sortDir
                    );
                    if (primary !== 0) return primary;
                }
                const fallbacks = [
                    compareNullableNumber(legacyFavoriteValue(left.parent, leftSource), legacyFavoriteValue(right.parent, rightSource), 'desc'),
                    compareNullableNumber(parentDateMadeSortValue(left.parent, leftSource), parentDateMadeSortValue(right.parent, rightSource), 'desc'),
                    compareNullableNumber(left.metrics && left.metrics.preferredMatches, right.metrics && right.metrics.preferredMatches, 'desc'),
                    compareNullableNumber(left.metrics && left.metrics.preferredStars, right.metrics && right.metrics.preferredStars, 'desc'),
                    compareNullableNumber(left.metrics && left.metrics.affinity, right.metrics && right.metrics.affinity, 'desc'),
                    compareNullableNumber(left.metrics && left.metrics.score, right.metrics && right.metrics.score, 'desc'),
                    compareNullableNumber(left.metrics && left.metrics.wins, right.metrics && right.metrics.wins, 'desc'),
                    compareNullableNumber(left.metrics && left.metrics.whites, right.metrics && right.metrics.whites, 'desc')
                ];
                for (const cmp of fallbacks) {
                    if (cmp !== 0) return cmp;
                }
                return String(left.parent.name || '').localeCompare(String(right.parent.name || ''));
            });
        }
        function countActiveLegacyFilters(query) {
            let count = 0;
            ['mainFactors', 'inheritanceFactors'].forEach(key => {
                (query[key] || []).forEach(row => {
                    const hasName = !!String(row.name || '').trim();
                    const hasRange = Number(row.minStars) > 0 || Number(row.maxStars) > 0;
                    if (hasName || hasRange) count += 1;
                });
            });
            if (Number(query.mainMinWhites) > 0) count += 1;
            if (Number(query.general.minAffinity) > 0) count += 1;
            if (Number(query.general.minWins) > 0) count += 1;
            if (Number(query.general.minWhites) > 0) count += 1;
            if (Number(query.general.minScore) > 0) count += 1;
            if (Number(query.totals.stat) > 0) count += 1;
            if (Number(query.totals.aptitude) > 0) count += 1;
            if (Number(query.totals.green) > 0) count += 1;
            if (Number(query.totals.white) > 0) count += 1;
            return count;
        }

        /* ---------- Parent metrics helpers ---------- */
        function countAllFactors(parent) {
            const tree = (parent && parent.tree) || {};
            return EFFECTIVE_SPARK_NODES.reduce((sum, k) => {
                const n = tree[k];
                if (!n || !n.factors) return sum;
                return sum + n.factors.length;
            }, 0);
        }
        function countLineageFactors(parent, category) {
            const tree = (parent && parent.tree) || {};
            const wanted = normalizeSparkCategory(category);
            return EFFECTIVE_SPARK_NODES.reduce((sum, k) => {
                const n = tree[k];
                if (!n || !n.factors) return sum;
                return sum + n.factors.filter(f => f && normalizeSparkCategory(f.category, f) === wanted).length;
            }, 0);
        }
        function countLineage3StarSparks(parent) {
            const tree = (parent && parent.tree) || {};
            return EFFECTIVE_SPARK_NODES.reduce((sum, k) => {
                const n = tree[k];
                if (!n || !n.factors) return sum;
                return sum + n.factors.filter(f => f && (f.stars || 0) >= 3).length;
            }, 0);
        }
        function countWinsByGrade(parent, grade) {
            const tree = (parent && parent.tree) || {};
            return ['self','p1','p2','gp1','gp2','gp3','gp4'].reduce((sum, k) => {
                const n = tree[k];
                if (!n || !n.wins) return sum;
                return sum + (n.wins[grade] || 0);
            }, 0);
        }
        function countMainWinsByGrade(parent, grade) {
            const tree = (parent && parent.tree) || {};
            const self = tree.self || {};
            const wins = self.wins || {};
            return Number(wins[grade] || 0) || 0;
        }
        function rankLabel(parent) { return rankMap[parent && parent.rank] || '??'; }
        function rankCoinColor(rankLbl) {
            if (!rankLbl) return '#888';
            const r = rankLbl.replace('+','').toUpperCase();
            if (r === 'SS' || r === 'S') return '#ffd866';
            if (r === 'A')  return '#c896ff';
            if (r === 'B')  return '#7ed5a8';
            if (r === 'C')  return '#6db1ff';
            if (r === 'D' || r === 'E') return '#8a8a8a';
            return '#888';
        }
        function parentMetric(parent, field, options = {}) {
            switch (field) {
                case 'bot':      return parent && parent.made_by_bot ? 1 : 0;
                case 'rank':     return rankLabel(parent);
                case 'affinity': {
                    const detail = candidateAffinityDetail(parent, options.source || null);
                    return detail ? detail.total : null;
                }
                case 'g1wins':   return countWinsByGrade(parent, 'g1');
                case 'g2wins':   return countWinsByGrade(parent, 'g2');
                case 'g3wins':   return countWinsByGrade(parent, 'g3');
                case 'whites':   return countWhiteFactors(parent, EFFECTIVE_SPARK_NODES);
                case 'score':    return parent && parent.score != null ? Number(parent.score) : null;
                case 'sparks3':  return countLineage3StarSparks(parent);
                case 'name':     return (parent && parent.name) || '';
                default:         return null;
            }
        }
        function compareFilter(value, op, target) {
            if (value == null) return false;
            if (op === '≥') return Number(value) >= Number(target);
            if (op === '≤') return Number(value) <= Number(target);
            if (op === '=') return String(value) === String(target);
            if (op === 'contains') return String(value).toLowerCase().includes(String(target).toLowerCase());
            if (op === 'at least') {
                const av = typeof value === 'string' ? (aptRank[value] != null ? aptRank[value] : -1) : Number(value);
                const tv = typeof target === 'string' ? (aptRank[target] != null ? aptRank[target] : -1) : Number(target);
                return av >= tv;
            }
            return false;
        }
        function passesParentFilters(parent) {
            for (const f of retuned.parentFilters) {
                if (f.kind === 'spark') {
                    if (!parentMatchesSparkFilter(parent, f)) return false;
                } else {
                    const val = parentMetric(parent, f.field);
                    if (!compareFilter(val, f.op, f.value)) return false;
                }
            }
            return true;
        }
        function passesQuickPreset() {
            // Quick chips now replace retuned.parentFilters with concrete filter rows;
            // the actual filtering is done by passesParentFilters. Kept for compatibility.
            return true;
        }

        /* ---------- Segmented control binding ---------- */
        function _syncSegGroupFromSelect(group) {
            const targetId = group.getAttribute('data-seg-target');
            const target = document.getElementById(targetId);
            if (!target) return;
            const cur = String(target.value || '');
            group.querySelectorAll('.seg-btn').forEach(btn => {
                const v = btn.getAttribute('data-seg-value') || '';
                btn.classList.toggle('active', v === cur);
                btn.classList.toggle('accent', v === cur);
            });
        }
        function resyncSegmentedControls() {
            document.querySelectorAll('.seg-group[data-seg-target]').forEach(_syncSegGroupFromSelect);
        }
        function bindSegmentedControls(root = document) {
            root.querySelectorAll('.seg-group[data-seg-target]').forEach(group => {
                if (group.dataset.bound === '1') return;
                group.dataset.bound = '1';
                const targetId = group.getAttribute('data-seg-target');
                const target = document.getElementById(targetId);
                if (!target) return;
                _syncSegGroupFromSelect(group);
                group.addEventListener('click', evt => {
                    const btn = evt.target.closest('.seg-btn');
                    if (!btn || !group.contains(btn)) return;
                    const v = btn.getAttribute('data-seg-value') || '';
                    target.value = v;
                    target.dispatchEvent(new Event('change', { bubbles: true }));
                    group.querySelectorAll('.seg-btn').forEach(b => {
                        b.classList.toggle('active', b === btn);
                        b.classList.toggle('accent', b === btn);
                    });
                });
                // Also listen for programmatic changes on the hidden select (renderSkillPlanControls etc. writes to it)
                target.addEventListener('change', () => _syncSegGroupFromSelect(group));
            });
            const loopGroup = document.getElementById('loop-seg-group');
            if (loopGroup && loopGroup.dataset.bound !== '1') {
                loopGroup.dataset.bound = '1';
                // map current state.loopMode + state.loopActive → which seg is "active"
                const activeKey = state.loopEnabled ? state.loopMode : 'off';
                loopGroup.querySelectorAll('.seg-btn').forEach(btn => {
                    btn.classList.toggle('active', btn.getAttribute('data-loop') === activeKey);
                    btn.classList.toggle('accent', btn.getAttribute('data-loop') === activeKey);
                });
                loopGroup.addEventListener('click', evt => {
                    const btn = evt.target.closest('.seg-btn');
                    if (!btn || !loopGroup.contains(btn)) return;
                    if (evt.target.tagName === 'INPUT') return; // don't toggle when clicking the input
                    const mode = btn.getAttribute('data-loop');
                    loopGroup.querySelectorAll('.seg-btn').forEach(b => {
                        b.classList.toggle('active', b === btn);
                        b.classList.toggle('accent', b === btn);
                    });
                    if (mode === 'off') {
                        state.loopEnabled = false;
                    } else {
                        state.loopEnabled = true;
                        state.loopMode = mode === 'careers' ? 'careers' : mode === 'fans' ? 'fans' : 'forever';
                        if (els.loopModeSelect) els.loopModeSelect.value = state.loopMode;
                    }
                    safeLocalSet('loopEnabled', state.loopEnabled ? '1' : '0');
                    safeLocalSet('loopMode', state.loopMode);
                    if (els.loopToggleBtn) {
                        els.loopToggleBtn.setAttribute('aria-pressed', state.loopEnabled ? 'true' : 'false');
                        els.loopToggleBtn.classList.toggle('on', state.loopEnabled);
                        els.loopToggleBtn.textContent = state.loopEnabled ? `LOOP ${state.loopMode.toUpperCase()}` : 'LOOP OFF';
                    }
                    if (typeof syncLoopControls === 'function') syncLoopControls();
                    if (typeof syncStartButton === 'function') syncStartButton();
                });
                loopGroup.querySelectorAll('.seg-input').forEach(input => {
                    input.addEventListener('click', e => e.stopPropagation());
                    input.addEventListener('change', () => {
                        if (input.id === 'loop-career-limit-input') {
                            state.loopCareerLimit = Number(input.value) || state.loopCareerLimit;
                            safeLocalSet('loopCareerLimit', state.loopCareerLimit);
                        } else if (input.id === 'loop-fan-limit-input') {
                            state.loopFanLimit = Number(input.value) || state.loopFanLimit;
                            safeLocalSet('loopFanLimit', state.loopFanLimit);
                        }
                    });
                });
            }
        }

        /* ---------- Library rail switching ---------- */
        function bindLibraryRail() {
            const rail = document.getElementById('lib-rail');
            if (!rail || rail.dataset.bound === '1') return;
            rail.dataset.bound = '1';
            rail.addEventListener('click', evt => {
                const btn = evt.target.closest('.rail-item');
                if (!btn) return;
                switchLibraryPane(btn.getAttribute('data-cat'));
            });
        }
        function switchLibraryPane(cat) {
            if (!cat) return;
            retuned.currentPane = cat;
            document.querySelectorAll('.lib-rail .rail-item').forEach(b => b.classList.toggle('active', b.getAttribute('data-cat') === cat));
            document.querySelectorAll('.lib-content .lib-pane').forEach(p => p.classList.toggle('active', p.getAttribute('data-pane') === cat));
            if (cat === 'session' && typeof renderSessionParentsRetuned === 'function') renderSessionParentsRetuned();
            const label = document.getElementById('lib-current-label');
            if (label) {
                const counts = retuned.lastCounts || {};
                const name = ({decks:'DECKS', trainees:'TRAINEES', parents:'PARENTS', session:'SESSION PARENTS', borrow:'BORROW', 'card-borrow':'CARD BORROW', friends:'FRIENDS', cards:'OWNED CARDS', bot:'BOT VIEW', test:'TEST 12'})[cat] || cat.toUpperCase();
                const n = counts[cat];
                label.innerText = n != null ? `${name} · ${n}` : name;
            }
        }
        function updateRailCounts() {
            const counts = {
                decks: (dashData && dashData.validDecks ? dashData.validDecks.length : null),
                trainees: (dashData && dashData.umas ? dashData.umas.length : null),
                parents: (dashData && dashData.parents ? dashData.parents.length : null),
                session: sessionParentItems().length,
                borrow: null,
                'card-borrow': (dashData && dashData.friends ? dashData.friends.length : null),
                friends: null,
                cards: (dashData && dashData.supports ? dashData.supports.length : null)
            };
            if (dashData && dashData.friendsList) counts.friends = dashData.friendsList.length;
            if (dashData && dashData.borrowQuota) counts.borrow = `${dashData.borrowQuota.remaining}/${dashData.borrowQuota.max}`;
            else if (dashData && dashData.borrowUmas) counts.borrow = dashData.borrowUmas.length;
            retuned.lastCounts = counts;
            Object.keys(counts).forEach(key => {
                const el = document.getElementById('rail-count-' + key);
                if (el && counts[key] != null) {
                    el.innerText = counts[key];
                    el.classList.toggle('rail-count-warn', key === 'borrow' && typeof counts[key] === 'string' && counts[key].startsWith('0/'));
                }
            });
            const label = document.getElementById('lib-current-label');
            if (label && counts[retuned.currentPane] != null) {
                const name = ({decks:'DECKS', trainees:'TRAINEES', parents:'PARENTS', session:'SESSION PARENTS', borrow:'BORROW', 'card-borrow':'CARD BORROW', friends:'FRIENDS', cards:'OWNED CARDS', bot:'BOT VIEW', test:'TEST 12'})[retuned.currentPane] || retuned.currentPane.toUpperCase();
                label.innerText = `${name} · ${counts[retuned.currentPane]}`;
            }
        }

        function teamTrialsRankLabel(value) {
            return rankMap[Number(value || 0)] || (value ? String(value) : '--');
        }
        function teamTrialsRankClass(position) {
            const n = Number(position || 0);
            if (n === 1) return 'is-first';
            if (n === 2) return 'is-second';
            if (n === 3) return 'is-third';
            return '';
        }
        function teamTrialsMatchesSearch(team, query) {
            query = String(query || '').trim().toLowerCase();
            if (!query) return true;
            const haystack = [
                team.trainer_name,
                team.trainer_id,
                team.trainer_id_label,
                team.team_rank_rating,
                team.class_label,
                team.score_label,
                team.source_kind,
                team.source_endpoint
            ];
            (team.members || []).forEach(member => {
                haystack.push(member.name, member.card_id, member.trained_chara_id, member.rank_label, member.rank_score, member.style, member.distance);
                (member.skills || []).forEach(skill => haystack.push(skill.name, skill.skill_id));
                (member.support_cards || []).forEach(card => haystack.push(card.name, card.support_card_id, card.rarity, card.type));
            });
            return haystack.map(value => String(value || '').toLowerCase()).join(' ').includes(query);
        }
        function teamTrialsTeams() {
            const teams = (state.teamTrialsData && Array.isArray(state.teamTrialsData.teams)) ? state.teamTrialsData.teams : [];
            return teams.filter(team => teamTrialsMatchesSearch(team, state.librarySearch.teamTrials || ''));
        }
        function findTeamTrialTeam(key) {
            return teamTrialsTeams().find(team => String(team.key) === String(key)) || null;
        }
        function findTeamTrialCharacter(team, key) {
            const members = team && Array.isArray(team.members) ? team.members : [];
            return members.find(member => String(member.key) === String(key)) || null;
        }
        function teamTrialsSetView(view) {
            if (els.teamTrialsListView) els.teamTrialsListView.hidden = view !== 'list';
            if (els.teamTrialsTeamView) els.teamTrialsTeamView.hidden = view !== 'team';
            if (els.teamTrialsCharacterView) els.teamTrialsCharacterView.hidden = view !== 'character';
        }
        function teamTrialsAptBadge(label, row) {
            const rank = row && row.rank ? row.rank : '--';
            return `<span class="team-trials-apt-badge"><span>${escapeHtml(label)}</span><strong>${escapeHtml(rank)}</strong></span>`;
        }
        function teamTrialsAptitudeHtml(aptitudes = {}) {
            const track = aptitudes.track || {};
            const distance = aptitudes.distance || {};
            const style = aptitudes.style || {};
            return `
                <div class="team-trials-apt-row"><b>Track</b>${teamTrialsAptBadge('Turf', track.turf)}${teamTrialsAptBadge('Dirt', track.dirt)}</div>
                <div class="team-trials-apt-row"><b>Distance</b>${teamTrialsAptBadge('Sprint', distance.sprint)}${teamTrialsAptBadge('Mile', distance.mile)}${teamTrialsAptBadge('Medium', distance.medium)}${teamTrialsAptBadge('Long', distance.long)}</div>
                <div class="team-trials-apt-row"><b>Style</b>${teamTrialsAptBadge('Front', style.front)}${teamTrialsAptBadge('Pace', style.pace)}${teamTrialsAptBadge('Late', style.late)}${teamTrialsAptBadge('End', style.end)}</div>
            `;
        }
        function teamTrialsStatHtml(member) {
            const stats = member && member.stats ? member.stats : {};
            const rows = [
                ['Speed', stats.speed],
                ['Stamina', stats.stamina],
                ['Power', stats.power],
                ['Guts', stats.guts],
                ['Wit', stats.wit]
            ];
            return rows.map(([label, value]) => `
                <div class="team-trials-stat">
                    <span>${escapeHtml(label)}</span>
                    <strong>${formatNumber(value || 0)}</strong>
                </div>
            `).join('');
        }
        function setTeamTrialsSourceLabel(text) {
            if (els.teamTrialsSourceLabel) els.teamTrialsSourceLabel.textContent = text || 'Source not loaded';
        }
        async function loadTeamTrialsData(refresh = false, source = 'live') {
            if (state.teamTrialsLoading) return;
            if (!refresh && !state.teamTrialsData && source !== 'local') refresh = true;
            state.teamTrialsLoading = true;
            const isLocal = source === 'local';
            state.teamTrialsSourceKind = isLocal ? 'local_fallback' : 'in_game_leaderboard';
            if (els.teamTrialsStatus) {
                els.teamTrialsStatus.textContent = isLocal
                    ? 'Loading local saved Team Trials fallback exports...'
                    : 'Loading in-game Team Trials leaderboard...';
            }
            setTeamTrialsSourceLabel(isLocal ? 'Local fallback exports' : 'In-game leaderboard');
            try {
                const endpoint = isLocal
                    ? `/api/team_trials/data?limit=100&refresh=${refresh ? '1' : '0'}`
                    : `/api/team_trials/live?limit=100`;
                const data = await apiJson(endpoint);
                if (!data || data.success === false) {
                    const probe = data && Array.isArray(data.operations) ? ` (${data.operations.length} endpoint probe${data.operations.length === 1 ? '' : 's'} attempted)` : '';
                    throw new Error(((data && data.detail) || 'Team Trials load failed') + probe);
                }
                state.teamTrialsData = data;
                renderTeamTrialsPlayers();
            } catch (e) {
                if (els.teamTrialsStatus) els.teamTrialsStatus.textContent = e.message || 'Team Trials load failed';
                setTeamTrialsSourceLabel(isLocal ? 'Local fallback failed' : 'Live leaderboard unavailable');
            } finally {
                state.teamTrialsLoading = false;
            }
        }
        function renderTeamTrialsPlayers() {
            const teams = teamTrialsTeams();
            teamTrialsSetView('list');
            if (els.teamTrialsStatus) {
                const data = state.teamTrialsData || {};
                const isLive = data.source_kind === 'in_game_leaderboard' || data.schema === 'sweepy_team_trials_live_v1';
                const source = isLive
                    ? `Source: in-game ${data.source_endpoint || 'leaderboard endpoint'}`
                    : (data.source_dir ? `Local fallback source: ${data.source_dir}` : 'Source not loaded');
                els.teamTrialsStatus.textContent = teams.length
                    ? `Showing ${formatNumber(teams.length)} player${teams.length === 1 ? '' : 's'}. ${source}`
                    : `No Team Trials players found. ${source}`;
                setTeamTrialsSourceLabel(isLive ? 'In-game leaderboard' : 'Local fallback exports');
            }
            if (!els.teamTrialsPlayerList) return;
            if (!teams.length) {
                els.teamTrialsPlayerList.innerHTML = `<div class="empty-state">No Team Trials players matched the search or source.</div>`;
                return;
            }
            els.teamTrialsPlayerList.innerHTML = teams.map(team => {
                const leader = team.leader || {};
                const rankPos = Number(team.display_rank || 0);
                const rating = Number(team.team_rank_rating || 0);
                const suffix = rankPos === 1 ? 'st' : rankPos === 2 ? 'nd' : rankPos === 3 ? 'rd' : 'th';
                return `
                    <button type="button" class="team-trials-player-card ${teamTrialsRankClass(rankPos)}" data-team-key="${escapeAttr(team.key)}">
                        <div class="team-trials-rank-ribbon">${rankPos ? `${rankPos}${suffix}` : '--'}</div>
                        <div class="team-trials-player-portrait">
                            <img src="/api/images/${escapeAttr(team.leader_card_id || leader.card_id || '100101')}.png" onerror="hideBrokenImage(this)">
                            <span>${escapeHtml(team.max_rank_label || teamTrialsRankLabel(team.max_rank))}</span>
                        </div>
                        <div class="team-trials-player-info">
                            <div class="team-trials-player-name">${escapeHtml(team.trainer_name || 'Unknown Trainer')}</div>
                            <div class="team-trials-player-id">${escapeHtml(team.trainer_id_label || (team.trainer_id ? `ID ${team.trainer_id}` : 'ID unavailable'))}</div>
                            <div class="team-trials-player-line"><span>Class</span><strong>${escapeHtml(team.class_label || '--')}</strong></div>
                            <div class="team-trials-player-line"><span>Score</span><strong>${rating ? `${formatNumber(rating)} pts` : escapeHtml(team.score_label || 'Score unavailable')}</strong></div>
                            <div class="team-trials-player-line"><span>Source</span><strong>${escapeHtml(team.source_kind === 'in_game_leaderboard' ? 'In-game' : (team.captured_at || team.source_file || 'Local fallback'))}</strong></div>
                        </div>
                    </button>
                `;
            }).join('');
        }
        async function loadTeamTrialsProfile(team) {
            if (!team || team.profile_loaded || !team.trainer_id || state.teamTrialsLoading) return team;
            state.teamTrialsLoading = true;
            if (els.teamTrialsStatus) els.teamTrialsStatus.textContent = `Loading in-game profile for ${team.trainer_name || team.trainer_id}...`;
            try {
                const params = new URLSearchParams();
                params.set('viewer_id', String(team.trainer_id));
                if (team.team_class) params.set('team_class', String(team.team_class));
                if (team.display_rank) params.set('rank', String(team.display_rank));
                if (team.term_id) params.set('term_id', String(team.term_id));
                if (team.team_rank_rating) params.set('team_rank_rating', String(team.team_rank_rating));
                if (team.trainer_name) params.set('trainer_name', String(team.trainer_name));
                if (team.source_payload && team.source_payload.ranking_type) params.set('ranking_type', String(team.source_payload.ranking_type));
                const data = await apiJson(`/api/team_trials/live_profile?${params.toString()}`);
                if (!data || data.success === false || !data.team) throw new Error((data && data.detail) || 'Profile load failed');
                const merged = { ...team, ...data.team, key: team.key, display_rank: team.display_rank || data.team.display_rank };
                const teams = (state.teamTrialsData && Array.isArray(state.teamTrialsData.teams)) ? state.teamTrialsData.teams : [];
                const idx = teams.findIndex(row => String(row.key) === String(team.key));
                if (idx >= 0) teams[idx] = merged;
                return merged;
            } catch (e) {
                team.profile_error = e.message || 'Profile load failed';
                team.profile_loaded = false;
                return team;
            } finally {
                state.teamTrialsLoading = false;
            }
        }
        async function openTeamTrialsTeam(teamKey) {
            const team = findTeamTrialTeam(teamKey);
            if (!team) return;
            state.teamTrialsSelectedTeamKey = String(teamKey);
            state.teamTrialsSelectedCharacterKey = '';
            const resolved = (team.source_kind === 'in_game_leaderboard' && !(team.members || []).length)
                ? await loadTeamTrialsProfile(team)
                : team;
            if (els.teamTrialsTeamTitle) els.teamTrialsTeamTitle.textContent = resolved.trainer_name || 'Team Trials Team';
            if (els.teamTrialsTeamMeta) {
                const parts = [
                    resolved.trainer_id ? `ID ${resolved.trainer_id}` : 'ID unavailable',
                    resolved.team_rank_rating ? `${formatNumber(resolved.team_rank_rating)} pts` : 'score unavailable',
                    `${formatNumber(resolved.member_count || 0)} members`,
                    resolved.source_kind === 'in_game_profile' || resolved.source_kind === 'in_game_leaderboard' ? 'in-game source' : 'local fallback',
                    resolved.profile_error || resolved.source_file || resolved.source_endpoint || ''
                ].filter(Boolean);
                els.teamTrialsTeamMeta.textContent = parts.join(' | ');
            }
            renderTeamTrialsTeam(resolved);
            teamTrialsSetView('team');
            if (els.teamTrialsStatus) {
                els.teamTrialsStatus.textContent = resolved.profile_error
                    ? `Leaderboard loaded, but detailed team profile is unavailable: ${resolved.profile_error}`
                    : `Showing ${resolved.trainer_name || 'trainer'} team details.`;
            }
        }
        function renderTeamTrialsTeam(team) {
            if (!els.teamTrialsTeamLayout) return;
            const distances = [
                ['sprint', 'Sprint'],
                ['mile', 'Mile'],
                ['medium', 'Medium'],
                ['long', 'Long'],
                ['dirt', 'Dirt']
            ];
            const groups = team.members_by_distance || {};
            els.teamTrialsTeamLayout.innerHTML = distances.map(([key, label]) => {
                const members = groups[key] || [];
                return `
                    <section class="team-trials-distance-col">
                        <div class="team-trials-distance-head">${escapeHtml(label)}</div>
                        <div class="team-trials-distance-list">
                            ${members.length ? members.map(member => `
                                <button type="button" class="team-trials-uma-card" data-character-key="${escapeAttr(member.key)}">
                                    ${member.is_ace ? '<span class="team-trials-ace">ACE</span>' : '<span class="team-trials-spacer"></span>'}
                                    <div class="team-trials-uma-portrait">
                                        <img src="/api/images/${escapeAttr(member.card_id || '100101')}.png" onerror="hideBrokenImage(this)">
                                        <span>${escapeHtml(member.rank_label || teamTrialsRankLabel(member.rank))}</span>
                                    </div>
                                    <div class="team-trials-uma-name">${escapeHtml(member.name || 'Unknown')}</div>
                                    <div class="team-trials-uma-meta">${escapeHtml(member.style || 'style ?')} | ${formatNumber(member.career_wins || 0)} wins</div>
                                </button>
                            `).join('') : '<div class="team-trials-empty-slot">No export data</div>'}
                        </div>
                    </section>
                `;
            }).join('');
        }
        function openTeamTrialsCharacter(characterKey) {
            const team = findTeamTrialTeam(state.teamTrialsSelectedTeamKey);
            const member = findTeamTrialCharacter(team, characterKey);
            if (!team || !member) return;
            state.teamTrialsSelectedCharacterKey = String(characterKey);
            if (els.teamTrialsCharacterTitle) els.teamTrialsCharacterTitle.textContent = member.name || 'Umamusume Details';
            if (els.teamTrialsCharacterMeta) {
                els.teamTrialsCharacterMeta.textContent = [
                    team.trainer_name || '',
                    member.distance || '',
                    member.rank_label || teamTrialsRankLabel(member.rank),
                    member.rank_score ? formatNumber(member.rank_score) : '',
                ].filter(Boolean).join(' | ');
            }
            renderTeamTrialsCharacter(team, member);
            teamTrialsSetView('character');
        }
        function renderTeamTrialsCharacter(team, member) {
            if (!els.teamTrialsCharacterDetail) return;
            const skills = member.skills || [];
            const supports = member.support_cards || [];
            const parents = member.parents || [];
            const races = (member.races && member.races.history) || [];
            els.teamTrialsCharacterDetail.innerHTML = `
                <div class="team-trials-detail-hero">
                    <div class="team-trials-detail-portrait">
                        <img src="/api/images/${escapeAttr(member.card_id || '100101')}.png" onerror="hideBrokenImage(this)">
                        <span>${escapeHtml(member.rank_label || teamTrialsRankLabel(member.rank))}</span>
                    </div>
                    <div class="team-trials-detail-main">
                        <div class="team-trials-detail-name">${escapeHtml(member.name || 'Unknown')}</div>
                        <div class="team-trials-detail-sub">${escapeHtml(team.trainer_name || '')} | ${escapeHtml(member.distance || '')} | ${escapeHtml(member.style || '')}</div>
                        <div class="team-trials-stat-grid">${teamTrialsStatHtml(member)}</div>
                    </div>
                </div>
                <div class="team-trials-aptitudes">${teamTrialsAptitudeHtml(member.aptitudes || {})}</div>
                <div class="team-trials-detail-tabs">
                    <button type="button" class="team-trials-tab is-active" data-team-trials-tab="skills">Skills</button>
                    <button type="button" class="team-trials-tab" data-team-trials-tab="career">Career Info</button>
                    <button type="button" class="team-trials-tab" data-team-trials-tab="inspiration">Inspiration</button>
                </div>
                <section class="team-trials-tab-panel is-active" data-team-trials-panel="skills">
                    ${skills.length ? `<div class="team-trials-skill-grid">${skills.map(skill => `<span class="team-trials-skill">${escapeHtml(skill.name || `Skill ${skill.skill_id || ''}`)}${skill.level ? ` Lv ${escapeHtml(skill.level)}` : ''}</span>`).join('')}</div>` : '<div class="team-trials-unavailable">No skill data in this export.</div>'}
                </section>
                <section class="team-trials-tab-panel" data-team-trials-panel="career">
                    <div class="team-trials-info-grid">
                        <div><span>Career wins</span><strong>${formatNumber(member.career_wins || 0)}</strong></div>
                        <div><span>Deck RB</span><strong>${member.deck_race_bonus_available ? `${member.deck_race_bonus_pct}%` : 'Unavailable'}</strong></div>
                        <div><span>Strategy</span><strong>${escapeHtml(member.style || 'Unavailable')}</strong></div>
                        <div><span>Source</span><strong>${escapeHtml(member.source_file || '')}</strong></div>
                    </div>
                    <h4>Support Cards</h4>
                    ${supports.length ? `<div class="team-trials-support-row">${supports.map(card => `<div class="team-trials-support-card"><img src="/api/images/${escapeAttr(card.support_card_id || card.id || '10001')}.png" onerror="hideBrokenImage(this)"><span>${escapeHtml(card.name || `Support ${card.support_card_id || ''}`)}</span></div>`).join('')}</div>` : '<div class="team-trials-unavailable">Deck unavailable in this saved export. It appears only when a matching detailed veteran record exists.</div>'}
                    <h4>Race History</h4>
                    ${races.length ? `<div class="team-trials-race-list">${races.map(race => `<div class="team-trials-race-row"><strong>${escapeHtml(race.name || `Program ${race.program_id || ''}`)}</strong><span>Turn ${escapeHtml(race.turn || '?')} | ${escapeHtml(race.style || '')} | Place ${escapeHtml(race.result_rank || '?')}</span></div>`).join('')}</div>` : '<div class="team-trials-unavailable">Career race list unavailable in this saved export.</div>'}
                </section>
                <section class="team-trials-tab-panel" data-team-trials-panel="inspiration">
                    ${parents.length ? `<div class="team-trials-parent-grid">${parents.map(parent => `<div class="team-trials-parent-card"><img src="/api/images/${escapeAttr(parent.card_id || '100101')}.png" onerror="hideBrokenImage(this)"><strong>${escapeHtml(parent.name || 'Unknown')}</strong><span>${escapeHtml(parent.rank_label || '')}</span></div>`).join('')}</div>` : '<div class="team-trials-unavailable">Parent/legacy data unavailable in this saved export.</div>'}
                </section>
            `;
        }
        function bindTeamTrialsHandlers() {
            if (bindTeamTrialsHandlers.bound) return;
            bindTeamTrialsHandlers.bound = true;
            els.teamTrialsScreenBtn?.addEventListener('click', () => showTeamTrialsScreen());
            els.teamTrialsBackDashboardBtn?.addEventListener('click', () => showDashboardFromTeamTrials());
            els.teamTrialsRefreshBtn?.addEventListener('click', () => loadTeamTrialsData(true, 'live'));
            els.teamTrialsLocalBtn?.addEventListener('click', () => loadTeamTrialsData(true, 'local'));
            els.teamTrialsTeamBackBtn?.addEventListener('click', () => {
                state.teamTrialsSelectedTeamKey = '';
                state.teamTrialsSelectedCharacterKey = '';
                renderTeamTrialsPlayers();
            });
            els.teamTrialsCharacterBackBtn?.addEventListener('click', () => {
                const team = findTeamTrialTeam(state.teamTrialsSelectedTeamKey);
                if (team) {
                    renderTeamTrialsTeam(team);
                    teamTrialsSetView('team');
                } else {
                    renderTeamTrialsPlayers();
                }
            });
            els.teamTrialsPlayerList?.addEventListener('click', event => {
                const card = event.target.closest('.team-trials-player-card');
                if (!card) return;
                openTeamTrialsTeam(card.dataset.teamKey);
            });
            els.teamTrialsTeamLayout?.addEventListener('click', event => {
                const card = event.target.closest('.team-trials-uma-card');
                if (!card) return;
                openTeamTrialsCharacter(card.dataset.characterKey);
            });
            els.teamTrialsCharacterDetail?.addEventListener('click', event => {
                const tab = event.target.closest('.team-trials-tab');
                if (!tab) return;
                const key = tab.dataset.teamTrialsTab;
                els.teamTrialsCharacterDetail.querySelectorAll('.team-trials-tab').forEach(btn => btn.classList.toggle('is-active', btn === tab));
                els.teamTrialsCharacterDetail.querySelectorAll('.team-trials-tab-panel').forEach(panel => {
                    panel.classList.toggle('is-active', panel.dataset.teamTrialsPanel === key);
                });
            });
        }

        function showTeamTrialsScreen() {
            document.body.classList.add('dashboard-mode');
            if (els.loginView) els.loginView.style.display = 'none';
            if (els.dashboardView) {
                els.dashboardView.style.display = 'none';
                els.dashboardView.classList.remove('active');
            }
            if (els.teamTrialsScreen) els.teamTrialsScreen.hidden = false;
            showNavbar();
            syncDashboardHeight();
            teamTrialsSetView('list');
            if (!state.teamTrialsData) loadTeamTrialsData(true, 'live');
            else renderTeamTrialsPlayers();
        }

        function showDashboardFromTeamTrials() {
            if (els.teamTrialsScreen) els.teamTrialsScreen.hidden = true;
            if (els.dashboardView) {
                els.dashboardView.style.display = '';
                els.dashboardView.classList.add('active');
            }
            syncDashboardHeight();
            deriveStatusFromState();
        }

        /* ---------- Status bar ---------- */
        function updateStatusBar(text, opts = {}) {
            const bar = document.getElementById('status-bar');
            if (!bar) return;
            const stext = document.getElementById('status-text');
            const swarn = document.getElementById('status-warn');
            const warnText = opts.warn != null ? opts.warn : affinityWarningText();
            if (stext) stext.innerHTML = text || 'Idle';
            if (swarn) swarn.innerHTML = warnText || '';
            bar.classList.toggle('is-running', !!opts.running);
            bar.classList.toggle('is-error', !!opts.error);
        }
        function deriveStatusFromState() {
            if (state.runnerRunning) {
                const loop = state.loopEnabled ? ` · loop ${state.loopMode}` : '';
                updateStatusBar(`Running${loop}`, { running: true });
            } else if (state.account && state.account.career && state.account.career.active) {
                updateStatusBar(`Ongoing career — <strong>${state.account.career.name || 'unnamed'}</strong>`, {});
            } else {
                updateStatusBar('Idle', {});
            }
        }

        /* ---------- Account strip retune (Phase 2) ---------- */
        function renderAccountStripRetuned() {
            deriveAccountTpForDisplay(state.account);
            const a = state.account;
            if (!a || !els.accountStrip) return;
            const tp = a.tp || {};
            const carrots = a.carrots || {};
            const totalCarats = (Number(carrots.free) || 0) + (Number(carrots.paid) || 0);
            const career = a.career;
            const careerHtml = career && career.active
                ? `<button type="button" id="career-pill" class="account-pill account-pill-career account-pill-clickable">ONGOING <strong>CAREER</strong></button>`
                : `<span class="account-pill account-pill-career">NO CAREER</span>`;
            const tpTitle = tp.seconds_to_next > 0 ? ` title="Next TP in ${tp.seconds_to_next}s"` : '';
            els.accountStrip.innerHTML = `
                <span class="account-pill"${tpTitle}>TP <strong>${tp.current || 0}/${tp.max || 0}</strong></span>
                <span class="account-pill" title="Free ${formatNumber(carrots.free)} · Paid ${formatNumber(carrots.paid)}">CARATS <strong>${formatNumber(totalCarats)}</strong></span>
                <span class="account-pill">GOLD <strong>${formatNumber(a.gold)}</strong></span>
                <span class="account-pill">T30 <strong>${formatNumber(a.toughness || 0)}</strong></span>
                ${careerHtml}
            `;
            els.accountStrip.style.display = 'flex';
            const careerPill = document.getElementById('career-pill');
            if (careerPill) careerPill.addEventListener('click', openCareerModal);
            renderCareerStatBar(a, state.runnerSnapshot);
            deriveStatusFromState();
        }
        // wrap original renderAccountStrip so both signatures work
        const _origRenderAccountStrip = renderAccountStrip;
        renderAccountStrip = function(account) {
            _origRenderAccountStrip(account);
            if (state.account === account || state.account === (account || null)) {
                renderAccountStripRetuned();
            }
        };

        /* ---------- Rich parent card (Phase 6) ---------- */
        function _initials(name) {
            if (!name) return '?';
            return String(name).split(/\s+/).filter(Boolean).slice(0, 2).map(s => s[0].toUpperCase()).join('') || '?';
        }
        function _factorPillHtml(factor) {
            const cat = normalizeSparkCategory(factor.category, factor);
            const cls = cat === 'stat' ? 'pill-stat'
                       : cat === 'aptitude' ? 'pill-apt'
                       : cat === 'skill' ? 'pill-white'
                       : cat === 'race' ? 'pill-white'
                       : cat === 'scenario' || cat === 'unique' ? 'pill-unique'
                       : 'pill-white';
            const stars = '★'.repeat(factor.stars || 1);
            const pct = factor.inherit_pct != null ? `${factor.inherit_pct}%` : '';
            return `<span class="pill ${cls}"><span class="pill-stars">${stars}</span><span class="pill-name">${escapeHtml(factor.name || '')}</span>${pct ? `<span class="pill-pct">${pct}</span>` : ''}</span>`;
        }
        function _gatherLineagePills(parent) {
            const tree = (parent && parent.tree) || {};
            const seen = {};
            const all = [];
            ['self','p1','p2','gp1','gp2','gp3','gp4'].forEach(key => {
                const node = tree[key]; if (!node || !node.factors) return;
                node.factors.forEach(f => {
                    const k = _factorKey(f) + ':' + (f.stars || 1);
                    if (seen[k]) return;
                    seen[k] = true;
                    all.push(f);
                });
            });
            // sort: aptitude > stat > unique > skill, then stars desc
            const catRank = { aptitude: 0, stat: 1, scenario: 2, unique: 2, skill: 3, race: 3 };
            all.sort((a, b) => {
                const ca = catRank[normalizeSparkCategory(a.category, a)] == null ? 4 : catRank[normalizeSparkCategory(a.category, a)];
                const cb = catRank[normalizeSparkCategory(b.category, b)] == null ? 4 : catRank[normalizeSparkCategory(b.category, b)];
                if (ca !== cb) return ca - cb;
                return (b.stars || 0) - (a.stars || 0);
            });
            return all;
        }
        function renderRichParentCard(parent, options = {}) {
            const imgId = parent.card_id || '100101';
            const name = parent.name || 'Unknown';
            const variant = parent.variant_name || parent.variant || '';
            const isBorrow = !!options.borrow;
            const favoriteType = options.favoriteType || (isBorrow ? 'borrowUmas' : 'parents');
            const trainerName = isBorrow ? (parent.trainer_name || '') : '';
            const rank = rankLabel(parent);
            const score = parent.score != null ? Number(parent.score) : null;
            const affinity = parentMetric(parent, 'affinity', { source: options.source || (isBorrow ? 'borrow' : 'owned') });
            const affinityLabel = (selection.trainee && !parentHasAffinityRaceData(parent)) ? 'BASE AFF' : 'AFFINITY';
            const g1Wins = countMainWinsByGrade(parent, 'g1');
            const whiteCount = countMainWhiteFactors(parent);
            const sparks3 = countLineage3StarSparks(parent);
            const selected = options.selected || (selection.veterans.some(v => parentKey(v) === parentKey(parent))) || (options.guestKey && options.guestKey === parentKey(parent));
            const botBadgeHtml = parent.made_by_bot ? '<span class="source-tag bot">BOT</span>' : '';
            const sparkPipsHtml = (() => {
                const tree = parent.tree || {};
                const self = tree.self || {};
                const sparks = (self.factors || []).slice(0, 5);
                if (!sparks.length) return Array(3).fill('<span class="spark-pip empty"></span>').join('');
                return sparks.map(f => {
                    const cat = normalizeSparkCategory(f.category, f);
                    const color = cat === 'stat' ? '#85B7EB' : cat === 'aptitude' ? '#ff8fc8' : (cat === 'scenario' || cat === 'unique') ? '#5ed68d' : '#EF9F27';
                    return `<span class="spark-pip" style="background:${color}"></span>`;
                }).join('');
            })();
            const affLine = (() => {
                if (affinity == null) return '';
                const sym = affinitySymbol(affinity);
                return `<span class="aff-icon ${sym.cls}">${sym.symbol}</span><span style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted)">${affinity}</span>`;
            })();
            // tooltip
            const pills = _gatherLineagePills(parent);
            const pillsHtml = pills.slice(0, 12).map(_factorPillHtml).join('') + (pills.length > 12 ? `<span class="pill pill-more">+${pills.length - 12} more</span>` : '');
            const treeNodes = parent.tree || {};
            const lineageNodeHtml = (node) => {
                if (!node) return `<div class="lineage-node"><div class="portrait-sm">?</div><span class="lineage-name" style="color:var(--text-dim)">—</span></div>`;
                const nm = node.name || 'Unknown';
                const cid = node.card_id || '';
                const img = cid ? `<img src="/api/images/${cid}.png" onerror="hideBrokenImage(this)">` : _initials(nm);
                return `<div class="lineage-node"><div class="portrait-sm">${img}</div><span class="lineage-name">${escapeHtml(nm)}</span></div>`;
            };
            const subLine = isBorrow
                ? `<span class="borrow-tag">GUEST</span>${escapeHtml(trainerName)} · ${escapeHtml(name)}${variant ? ' · ' + escapeHtml(variant) : ''}`
                : `${botBadgeHtml}${variant ? escapeHtml(variant) : `${whiteCount} white factor${whiteCount === 1 ? '' : 's'}`}`;
            return `
            <div class="parent-card-rich ${selected ? 'selected' : ''}" data-pkey="${parentKey(parent)}" data-card-id="${imgId}">
                ${favoriteButtonHtml(favoriteType, parent)}
                <button class="sparks-btn" type="button" data-sparks-pkey="${parentKey(parent)}" title="Open full lineage breakdown">Sparks</button>
                <div class="card-head">
                    <div class="portrait-md"><img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)"></div>
                    <div class="card-meta">
                        <div class="card-name">${escapeHtml(name)}</div>
                        <div class="card-sub">${subLine}</div>
                    </div>
                </div>
                <div class="card-stats">
                    <div class="stat-cell stat-affinity"><span class="stat-num">${affinity != null ? affinity : '—'}</span><span class="stat-tag">${affinityLabel}</span></div>
                    <div class="stat-cell stat-g1"><span class="stat-num">${g1Wins}</span><span class="stat-tag">G1 WINS</span></div>
                    <div class="stat-cell stat-white"><span class="stat-num">${whiteCount}</span><span class="stat-tag">WHITE FACTORS</span></div>
                </div>
                <div class="card-score-row">
                    <div class="rank-coin" style="background:${rankCoinColor(rank)}">${rank}</div>
                    <div class="score-block">
                        <span class="score-num">${score != null ? formatNumber(score) : '—'}</span>
                        <span class="score-tag">SCORE</span>
                    </div>
                    <div class="card-sparks-mini">${sparkPipsHtml}</div>
                </div>
            </div>`;
        }
        function renderParentsRetuned(parents) {
            const list = Array.isArray(parents) ? parents : [];
            const query = (state.librarySearch.parents || '').trim().toLowerCase();
            let visible = list.filter(p => {
                if (query) {
                    const blob = [(p.name||''), (p.card_id||''), (p.instance_id||''), rankLabel(p)].join(' ').toLowerCase();
                    if (!blob.includes(query)) return false;
                }
                if (!passesQuickPreset(p)) return false;
                if (!passesParentFilters(p)) return false;
                return true;
            });
            // Sort by affinity desc when a trainee or vet is selected (so highest-compat parents float to the top)
            const shouldSortByAffinity = !!selection.trainee || (selection.veterans && selection.veterans.length > 0);
            if (shouldSortByAffinity) {
                visible = visible.slice().sort((a, b) => {
                    const aa = parentMetric(a, 'affinity', { source: 'owned' }); const bb = parentMetric(b, 'affinity', { source: 'owned' });
                    return (bb == null ? -1 : bb) - (aa == null ? -1 : aa);
                });
            }
            if (dashData) dashData.visibleParents = visible;
            const grid = els.parentGrid;
            if (!grid) return;
            grid.innerHTML = visible.map(p => renderRichParentCard(p, { source: 'owned' })).join('');
            const summary = document.getElementById('parent-filter-summary');
            if (summary) {
                const fc = retuned.parentFilters.length + (retuned.parentQuick !== 'all' ? 1 : 0);
                summary.innerHTML = `Showing <strong>${visible.length}</strong> of ${list.length} · ${fc} filter${fc === 1 ? '' : 's'} active`;
            }
            // attach selection + tooltip flip
            grid.querySelectorAll('.parent-card-rich').forEach(card => {
                card.addEventListener('click', evt => {
                    // Sparks button → open modal, don't toggle selection
                    if (evt.target.closest('.sparks-btn')) {
                        evt.stopPropagation();
                        const key = evt.target.closest('.sparks-btn').getAttribute('data-sparks-pkey');
                        const p = list.find(x => parentKey(x) === key);
                        if (p) openSparksModal(p);
                        return;
                    }
                    const key = card.getAttribute('data-pkey');
                    const parent = list.find(p => parentKey(p) === key);
                    if (!parent) return;
                    if (selection.veterans.some(v => parentKey(v) === key)) {
                        selection.veterans = selection.veterans.filter(v => parentKey(v) !== key);
                    } else if (selection.veterans.length < 2) {
                        selection.veterans.push(parent);
                    } else {
                        return; // 2 already selected — ignore
                    }
                    renderParentsRetuned(list);
                    renderTeamPanel();
                    syncStartButton();
                    syncSelectionToServer();
                    renderBorrowFallbackPicker();
                    // affinity changes for borrow cards too when a vet is added/removed
                    if (dashData && dashData.borrowUmas) renderBorrowUmasRetuned(dashData.borrowUmas);
                });
            });
            updateRailCounts();
            deriveStatusFromState();
        }
        /* ---------- Borrow uma → parent-like shape, then render with parent-card-rich ---------- */
        function _normalizeBorrowUma(uma) {
            return {
                name: uma.chara_name || uma.name || 'Unknown',
                card_id: uma.card_id,
                instance_id: uma.trained_chara_id || uma.instance_id,
                rank: uma.rank != null ? uma.rank : uma.chara_grade,
                tree: uma.tree || {},
                score: uma.score != null ? Number(uma.score) : (uma.rank_score != null ? Number(uma.rank_score) : null),
                stats: uma.stats || statsFromParentFields(uma),
                skills: normalizedParentSkills(uma),
                skill_array: uma.skill_array || [],
                estimated_skill_points: estimatedParentSkillPoints(uma),
                trainer_name: uma.trainer_name,
                viewer_id: uma.viewer_id,
                trained_chara_id: uma.trained_chara_id || uma.instance_id,
                created_at: uma.created_at || uma.date_made || '',
                updated_at: uma.updated_at || '',
                _borrowKey: borrowUmaKey(uma)
            };
        }
        function passesBorrowFilters(p) {
            for (const f of retuned.borrowFilters) {
                if (f.kind === 'spark' || f.field === 'spark') {
                    if (!parentMatchesSparkFilter(p, f)) return false;
                } else {
                    const val = parentMetric(p, f.field, { source: 'borrow' });
                    if (!compareFilter(val, f.op, f.value)) return false;
                }
            }
            return true;
        }
        function renderBorrowUmasRetuned(umas) {
            const list = Array.isArray(umas) ? umas : [];
            const query = (state.librarySearch.borrowUmas || '').trim().toLowerCase();
            const normalized = list.map(_normalizeBorrowUma);
            let visible = normalized.filter(p => {
                if (query) {
                    const blob = [p.name, p.trainer_name, p.card_id, p.instance_id].join(' ').toLowerCase();
                    if (!blob.includes(query)) return false;
                }
                return passesBorrowFilters(p);
            });
            const shouldSortByAffinity = !!selection.trainee || (selection.veterans && selection.veterans.length > 0);
            if (shouldSortByAffinity) {
                visible = visible.slice().sort((a, b) => {
                    const aa = parentMetric(a, 'affinity', { source: 'borrow' }); const bb = parentMetric(b, 'affinity', { source: 'borrow' });
                    return (bb == null ? -1 : bb) - (aa == null ? -1 : aa);
                });
            }
            const quota = dashData && dashData.borrowQuota;
            if (els.borrowUmaCount) {
                els.borrowUmaCount.innerText = quota ? `(${quota.remaining}/${quota.max} borrows left today)` : `(${list.length})`;
            }
            if (els.borrowUmaStatus) {
                if (!list.length) {
                    els.borrowUmaStatus.innerText = 'No borrowable parents loaded. Click REFRESH.';
                } else {
                    els.borrowUmaStatus.innerText = `${list.length} borrowable parent${list.length === 1 ? '' : 's'}. Click a card to set as Guest, click again to clear.`;
                }
            }
            if (!els.borrowUmaGrid) return;
            els.borrowUmaGrid.innerHTML = visible.map(p => renderRichParentCard(p, {
                borrow: true,
                source: 'borrow',
                guestKey: selection.guestParent ? borrowUmaKey(selection.guestParent) : null,
                selected: selection.guestParent && p._borrowKey === borrowUmaKey(selection.guestParent)
            })).join('');
            const summary = document.getElementById('borrow-filter-summary');
            if (summary) {
                const fc = retuned.borrowFilters.length + (retuned.borrowQuick !== 'all' ? 1 : 0);
                summary.innerHTML = `Showing <strong>${visible.length}</strong> of ${list.length} · ${fc} filter${fc === 1 ? '' : 's'} active`;
            }
            // Click handling: sparks btn → modal; otherwise toggle guest selection
            els.borrowUmaGrid.querySelectorAll('.parent-card-rich').forEach(card => {
                card.addEventListener('click', evt => {
                    if (evt.target.closest('.sparks-btn')) {
                        evt.stopPropagation();
                        const key = evt.target.closest('.sparks-btn').getAttribute('data-sparks-pkey');
                        const p = visible.find(x => parentKey(x) === key);
                        if (p) openSparksModal(p);
                        return;
                    }
                    const key = card.getAttribute('data-pkey');
                    const p = visible.find(x => parentKey(x) === key);
                    if (!p) return;
                    // map back to original borrow uma for selection.guestParent
                    const origUma = list.find(u => borrowUmaKey(u) === p._borrowKey);
                    if (!origUma) return;
                    if (selection.guestParent && borrowUmaKey(selection.guestParent) === p._borrowKey) {
                        selection.guestParent = null;
                    } else {
                        selection.guestParent = normalizeBorrowUmaSelection(origUma);
                    }
                    renderBorrowUmasRetuned(list);
                    renderTeamPanel();
                    syncStartButton();
                    syncSelectionToServer();
                    deriveStatusFromState();
                });
            });
            deriveStatusFromState();
        }
        // Override renderBorrowUmas globally
        const _origRenderBorrowUmas = renderBorrowUmas;
        renderBorrowUmas = function(umas) {
            try { renderBorrowUmasRetuned(umas || []); }
            catch (e) { console.error('renderBorrowUmasRetuned failed', e); _origRenderBorrowUmas(umas); }
        };

        // Replace renderParents to use the rich card
        const _origRenderParents = renderParents;
        renderParents = function(parents) {
            try { renderParentsRetuned(parents || []); }
            catch (e) { console.error('renderParentsRetuned failed', e); _origRenderParents(parents); }
        };

        /* ---------- Trainee card aptitude strip (Phase 8) ---------- */
        const _origRenderTrainees = renderTrainees;
        renderTrainees = function(umas) {
            try { renderTraineesRetuned(umas || []); }
            catch (e) { console.error('renderTraineesRetuned failed', e); _origRenderTrainees(umas); }
        };
        function _aptForTrainee(uma) {
            const cid = uma.id || uma.card_id;
            const apt = charaAptitudeFor(cid);
            if (!apt) return null;
            return apt;
        }
        const TRAINEE_APTITUDE_GROUPS = [
            {
                title: 'Surface',
                className: 'is-surface',
                cells: [
                    { key: 'turf', label: 'Turf' },
                    { key: 'dirt', label: 'Dirt' }
                ]
            },
            {
                title: 'Distance',
                className: 'is-distance',
                cells: [
                    { key: 'sprint', label: 'Spr' },
                    { key: 'mile', label: 'Mile' },
                    { key: 'medium', label: 'Med' },
                    { key: 'long', label: 'Long' }
                ]
            }
        ];
        function renderTraineeAptitudePanel(aptVals) {
            const values = aptVals && typeof aptVals === 'object' ? aptVals : {};
            const hasAnyAptitude = TRAINEE_APTITUDE_GROUPS.some(group => group.cells.some(cell => values[cell.key]));
            if (!hasAnyAptitude) return '';
            return `<div class="trainee-apt-panel">${TRAINEE_APTITUDE_GROUPS.map(group => {
                const cellsHtml = group.cells.map(cell => {
                    const value = values[cell.key] || '?';
                    return `<div class="trainee-apt-cell">
                        <span class="trainee-apt-val apt-${value}">${value}</span>
                        <span class="trainee-apt-lbl">${cell.label}</span>
                    </div>`;
                }).join('');
                return `<div class="trainee-apt-group">
                    <div class="trainee-apt-group-title">${group.title}</div>
                    <div class="trainee-apt-strip ${group.className}">${cellsHtml}</div>
                </div>`;
            }).join('')}</div>`;
        }
        function passesTraineeFilters(uma) {
            const apt = _aptForTrainee(uma) || {};
            for (const f of retuned.traineeFilters) {
                if (f.field === 'growth') {
                    // Multi-growth: pass if ANY of the chara's growth stats matches the picked stat
                    const gs = Array.isArray(apt.growths) ? apt.growths.map(g => g.stat) : (apt.growth ? [apt.growth] : []);
                    if (!gs.includes(f.value)) return false;
                    continue;
                }
                let v = null;
                switch (f.field) {
                    case 'name':      v = uma.name || ''; break;
                    case 'rarity':    v = uma.rarity ? `${uma.rarity}★` : ''; break;
                    case 'aptTurf':   v = (apt.aptitudes || {}).turf; break;
                    case 'aptDirt':   v = (apt.aptitudes || {}).dirt; break;
                    case 'aptSprint': v = (apt.aptitudes || {}).sprint; break;
                    case 'aptMile':   v = (apt.aptitudes || {}).mile; break;
                    case 'aptMedium': v = (apt.aptitudes || {}).medium; break;
                    case 'aptLong':   v = (apt.aptitudes || {}).long; break;
                    default: v = null;
                }
                if (!compareFilter(v, f.op, f.value)) return false;
            }
            return true;
        }
        function renderTraineesRetuned(umas) {
            const list = Array.isArray(umas) ? umas : [];
            const query = (state.librarySearch.trainees || '').trim().toLowerCase();
            const visible = list.filter(u => {
                if (query && !String(u.name || '').toLowerCase().includes(query)) return false;
                if (!passesTraineeFilters(u)) return false;
                return true;
            });
            if (dashData) dashData.visibleTrainees = visible;
            if (!els.umaGrid) return;
            els.umaGrid.innerHTML = visible.map(uma => {
                const imgId = uma.id || '100101';
                const selected = selection.trainee && traineeKey(selection.trainee) === traineeKey(uma);
                const apt = _aptForTrainee(uma) || {};
                const aptVals = apt.aptitudes || {};
                const rarity = uma.rarity ? `${uma.rarity}★` : '';
                // Multi-growth support: new schema has growths: [{stat, pct}]; fall back to legacy single "growth" string
                const growths = Array.isArray(apt.growths)
                    ? apt.growths
                    : (apt.growth ? [{ stat: apt.growth, pct: null }] : []);
                const growthsHtml = growths.length
                    ? `<div class="trainee-growths">${growths.map((g, idx) => `<span class="trainee-growth-chip ${idx > 0 ? 'growth-secondary' : ''}">+${g.pct != null ? g.pct + '%' : ''} ${escapeHtml(g.stat || '')}</span>`).join('')}</div>`
                    : '';
                const aptPanel = renderTraineeAptitudePanel(aptVals);
                return `<div class="grid-card trainee-card ${selected ? 'selected' : ''}" data-tkey="${traineeKey(uma)}">
                    ${favoriteButtonHtml('trainees', uma)}
                    <img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">
                    <div class="grid-card-overlay"><span class="grid-card-name">${escapeHtml(uma.name || 'Unknown')}</span></div>
                    ${rarity ? `<div class="trainee-meta-row"><span class="meta-rarity">${rarity}</span></div>` : ''}
                    ${growthsHtml}
                    ${aptPanel}
                </div>`;
            }).join('');
            els.umaGrid.querySelectorAll('.trainee-card').forEach(card => {
                card.addEventListener('click', () => {
                    const key = card.getAttribute('data-tkey');
                    const t = list.find(u => traineeKey(u) === key);
                    if (!t) return;
                    if (selection.trainee && traineeKey(selection.trainee) === key) {
                        selection.trainee = null;
                    } else {
                        selection.trainee = t;
                    }
                    renderTraineesRetuned(list);
                    renderTeamPanel();
                    syncStartButton();
                    syncSelectionToServer();
                    // re-render parents AND borrow umas because affinity changes
                    if (dashData && dashData.parents) renderParentsRetuned(dashData.parents);
                    if (dashData && dashData.borrowUmas) renderBorrowUmasRetuned(dashData.borrowUmas);
                });
            });
            const summary = document.getElementById('trainee-filter-summary');
            if (summary) {
                summary.innerHTML = retuned.traineeFilters.length
                    ? `Showing <strong>${visible.length}</strong> of ${list.length} · ${retuned.traineeFilters.length} filter${retuned.traineeFilters.length === 1 ? '' : 's'} active`
                    : '';
            }
            updateRailCounts();
        }

        /* ---------- Filter row UI (parent rows can be either generic or spark) ---------- */
        function _defaultFilterRow(field, defs) {
            const def = fieldDef(defs, field);
            if (def.type === 'spark') {
                return { field: 'spark', sparkName: 'Power', category: 'stat', node: 'any', minStars: 3 };
            }
            return {
                field,
                op: opsForField(def)[0],
                value: def.type === 'enum' ? def.options[0] : def.type === 'aptitude' ? 'S' : def.type === 'text' ? '' : 0
            };
        }
        function _renderFilterRow(f, i, defs) {
            const def = fieldDef(defs, f.field);
            const fieldSelect = `<select class="filter-field" data-i="${i}" data-prop="field">${defs.map(d => `<option value="${d.id}" ${d.id===f.field?'selected':''}>${d.label}</option>`).join('')}</select>`;
            if (def.type === 'spark') {
                const catOpts = SPARK_CATEGORY_OPTIONS.map(c => `<option value="${c.id}" ${c.id===(f.category||'any')?'selected':''}>${c.label}</option>`).join('');
                const nodeOpts = Object.keys(NODE_LABELS).map(k => `<option value="${k}" ${k===(f.node||'any')?'selected':''}>${NODE_LABELS[k]}</option>`).join('');
                return `<div class="filter-row filter-row-spark">
                    ${fieldSelect}
                    <input class="filter-spark-name" data-i="${i}" data-prop="sparkName" type="text" placeholder="Spark name e.g. Power, Stamina, Turf, Long, Cut and Drive!" value="${escapeAttr(String(f.sparkName||''))}">
                    <select class="filter-op" data-i="${i}" data-prop="category">${catOpts}</select>
                    <select class="filter-node" data-i="${i}" data-prop="node">${nodeOpts}</select>
                    <span style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.05em;">total ≥</span>
                    <input class="filter-val" data-i="${i}" data-prop="minStars" type="number" min="0" step="1" value="${escapeAttr(String(f.minStars||0))}">
                    <span style="font-size:10px;color:var(--text-dim);">★</span>
                    <button class="filter-remove" data-i="${i}" type="button">×</button>
                </div>`;
            }
            const ops = opsForField(def);
            let valHtml;
            if (def.type === 'enum') {
                valHtml = `<select class="filter-val" data-i="${i}" data-prop="value">${def.options.map(o => `<option value="${o}" ${o===f.value?'selected':''}>${o}</option>`).join('')}</select>`;
            } else if (def.type === 'aptitude') {
                valHtml = `<select class="filter-val" data-i="${i}" data-prop="value">${['S','A','B','C','D','E','F','G'].map(o => `<option value="${o}" ${o===f.value?'selected':''}>${o}</option>`).join('')}</select>`;
            } else if (def.type === 'text') {
                valHtml = `<input class="filter-val-text" data-i="${i}" data-prop="value" type="text" value="${escapeAttr(String(f.value||''))}">`;
            } else {
                valHtml = `<input class="filter-val" data-i="${i}" data-prop="value" type="number" value="${escapeAttr(String(f.value||0))}">`;
            }
            return `<div class="filter-row">
                ${fieldSelect}
                <select class="filter-op" data-i="${i}" data-prop="op">${ops.map(o => `<option value="${o}" ${o===f.op?'selected':''}>${o}</option>`).join('')}</select>
                ${valHtml}
                <button class="filter-remove" data-i="${i}" type="button">×</button>
            </div>`;
        }
        function _renderFilterRows(target, list, defs) {
            target.innerHTML = list.map((f, i) => _renderFilterRow(f, i, defs)).join('');
        }
        function bindParentFilters() {
            const addBtn = document.getElementById('parent-add-filter-btn');
            const rows   = document.getElementById('parent-filter-rows');
            const chips  = document.getElementById('parent-quick-chips');
            if (!addBtn || !rows || !chips) return;
            if (addBtn.dataset.bound === '1') return;
            addBtn.dataset.bound = '1';
            addBtn.addEventListener('click', () => {
                retuned.parentFilters.push(_defaultFilterRow('spark', PARENT_FILTER_FIELDS));
                _renderFilterRows(rows, retuned.parentFilters, PARENT_FILTER_FIELDS);
                if (dashData && dashData.parents) renderParentsRetuned(dashData.parents);
            });
            rows.addEventListener('change', evt => {
                const t = evt.target;
                const i = Number(t.getAttribute('data-i'));
                const prop = t.getAttribute('data-prop');
                if (!prop || Number.isNaN(i)) return;
                const f = retuned.parentFilters[i];
                if (!f) return;
                if (prop === 'field') {
                    retuned.parentFilters[i] = _defaultFilterRow(t.value, PARENT_FILTER_FIELDS);
                } else if (prop === 'minStars') {
                    f.minStars = Number(t.value) || 0;
                } else {
                    f[prop] = t.value;
                }
                _renderFilterRows(rows, retuned.parentFilters, PARENT_FILTER_FIELDS);
                if (dashData && dashData.parents) renderParentsRetuned(dashData.parents);
            });
            rows.addEventListener('input', evt => {
                // live-update text/number changes without re-rendering rows (avoids losing focus)
                const t = evt.target;
                const i = Number(t.getAttribute('data-i'));
                const prop = t.getAttribute('data-prop');
                if (!prop || Number.isNaN(i)) return;
                const f = retuned.parentFilters[i];
                if (!f) return;
                if (prop === 'minStars') f.minStars = Number(t.value) || 0;
                else f[prop] = t.value;
                if (dashData && dashData.parents) renderParentsRetuned(dashData.parents);
            });
            rows.addEventListener('click', evt => {
                const btn = evt.target.closest('.filter-remove');
                if (!btn) return;
                const i = Number(btn.getAttribute('data-i'));
                retuned.parentFilters.splice(i, 1);
                _renderFilterRows(rows, retuned.parentFilters, PARENT_FILTER_FIELDS);
                if (dashData && dashData.parents) renderParentsRetuned(dashData.parents);
            });
            chips.addEventListener('click', evt => {
                const chip = evt.target.closest('.chip');
                if (!chip) return;
                chips.querySelectorAll('.chip').forEach(c => c.classList.toggle('active', c === chip));
                const quick = chip.getAttribute('data-quick') || 'all';
                retuned.parentQuick = quick;
                // For spark presets, replace filters with a one-row spec for convenience
                const presets = {
                    'power3':    { field: 'spark', sparkName: 'Power',   category: 'stat',     node: 'any',  minStars: 3 },
                    'stamina3':  { field: 'spark', sparkName: 'Stamina', category: 'stat',     node: 'any',  minStars: 3 },
                    'turfself3': { field: 'spark', sparkName: 'Turf',    category: 'aptitude', node: 'self', minStars: 3 },
                    'longself3': { field: 'spark', sparkName: 'Long',    category: 'aptitude', node: 'self', minStars: 3 },
                    'aff150':    { field: 'affinity', op: '≥', value: 150 }
                };
                if (presets[quick]) {
                    retuned.parentFilters = [presets[quick]];
                    _renderFilterRows(rows, retuned.parentFilters, PARENT_FILTER_FIELDS);
                } else if (quick === 'all') {
                    retuned.parentFilters = [];
                    _renderFilterRows(rows, retuned.parentFilters, PARENT_FILTER_FIELDS);
                }
                if (dashData && dashData.parents) renderParentsRetuned(dashData.parents);
            });
        }
        /* ---------- Borrow filters (parity with parent filters) ---------- */
        function bindBorrowFilters() {
            const addBtn = document.getElementById('borrow-add-filter-btn');
            const rows   = document.getElementById('borrow-filter-rows');
            const chips  = document.getElementById('borrow-quick-chips');
            if (!addBtn || !rows || !chips) return;
            if (addBtn.dataset.bound === '1') return;
            addBtn.dataset.bound = '1';
            addBtn.addEventListener('click', () => {
                retuned.borrowFilters.push(_defaultFilterRow('spark', PARENT_FILTER_FIELDS));
                _renderFilterRowsBorrow();
                if (dashData && dashData.borrowUmas) renderBorrowUmasRetuned(dashData.borrowUmas);
            });
            rows.addEventListener('change', evt => {
                const t = evt.target;
                const i = Number(t.getAttribute('data-i'));
                const prop = t.getAttribute('data-prop');
                if (!prop || Number.isNaN(i)) return;
                const f = retuned.borrowFilters[i];
                if (!f) return;
                if (prop === 'field') {
                    retuned.borrowFilters[i] = _defaultFilterRow(t.value, PARENT_FILTER_FIELDS);
                } else if (prop === 'minStars') {
                    f.minStars = Number(t.value) || 0;
                } else {
                    f[prop] = t.value;
                }
                _renderFilterRowsBorrow();
                if (dashData && dashData.borrowUmas) renderBorrowUmasRetuned(dashData.borrowUmas);
            });
            rows.addEventListener('input', evt => {
                const t = evt.target;
                const i = Number(t.getAttribute('data-i'));
                const prop = t.getAttribute('data-prop');
                if (!prop || Number.isNaN(i)) return;
                const f = retuned.borrowFilters[i];
                if (!f) return;
                if (prop === 'minStars') f.minStars = Number(t.value) || 0;
                else f[prop] = t.value;
                if (dashData && dashData.borrowUmas) renderBorrowUmasRetuned(dashData.borrowUmas);
            });
            rows.addEventListener('click', evt => {
                const btn = evt.target.closest('.filter-remove');
                if (!btn) return;
                const i = Number(btn.getAttribute('data-i'));
                retuned.borrowFilters.splice(i, 1);
                _renderFilterRowsBorrow();
                if (dashData && dashData.borrowUmas) renderBorrowUmasRetuned(dashData.borrowUmas);
            });
            chips.addEventListener('click', evt => {
                const chip = evt.target.closest('.chip');
                if (!chip) return;
                chips.querySelectorAll('.chip').forEach(c => c.classList.toggle('active', c === chip));
                const quick = chip.getAttribute('data-quick') || 'all';
                retuned.borrowQuick = quick;
                const presets = {
                    'power3':    { field: 'spark', sparkName: 'Power',   category: 'stat',     node: 'any',  minStars: 3 },
                    'stamina3':  { field: 'spark', sparkName: 'Stamina', category: 'stat',     node: 'any',  minStars: 3 },
                    'turfself3': { field: 'spark', sparkName: 'Turf',    category: 'aptitude', node: 'self', minStars: 3 },
                    'longself3': { field: 'spark', sparkName: 'Long',    category: 'aptitude', node: 'self', minStars: 3 },
                    'aff150':    { field: 'affinity', op: '≥', value: 150 }
                };
                if (presets[quick]) {
                    retuned.borrowFilters = [presets[quick]];
                } else if (quick === 'all') {
                    retuned.borrowFilters = [];
                }
                _renderFilterRowsBorrow();
                if (dashData && dashData.borrowUmas) renderBorrowUmasRetuned(dashData.borrowUmas);
            });
        }
        function _renderFilterRowsBorrow() {
            const rows = document.getElementById('borrow-filter-rows');
            if (rows) _renderFilterRows(rows, retuned.borrowFilters, PARENT_FILTER_FIELDS);
        }

        function bindTraineeFilters() {
            const addBtn = document.getElementById('trainee-add-filter-btn');
            const rows   = document.getElementById('trainee-filter-rows');
            if (!addBtn || !rows) return;
            if (addBtn.dataset.bound === '1') return;
            addBtn.dataset.bound = '1';
            addBtn.addEventListener('click', () => {
                retuned.traineeFilters.push({ field: 'rarity', op: '=', value: '5★' });
                _renderFilterRows(rows, retuned.traineeFilters, TRAINEE_FILTER_FIELDS);
                if (dashData && dashData.umas) renderTraineesRetuned(dashData.umas);
            });
            rows.addEventListener('change', evt => {
                const t = evt.target;
                const i = Number(t.getAttribute('data-i'));
                const prop = t.getAttribute('data-prop');
                if (!prop || isNaN(i)) return;
                const f = retuned.traineeFilters[i];
                if (!f) return;
                if (prop === 'field') {
                    f.field = t.value;
                    const def = fieldDef(TRAINEE_FILTER_FIELDS, f.field);
                    f.op = opsForField(def)[0];
                    f.value = def.type === 'enum' ? def.options[0] : def.type === 'aptitude' ? 'S' : def.type === 'text' ? '' : 0;
                } else {
                    f[prop] = t.value;
                }
                _renderFilterRows(rows, retuned.traineeFilters, TRAINEE_FILTER_FIELDS);
                if (dashData && dashData.umas) renderTraineesRetuned(dashData.umas);
            });
            rows.addEventListener('click', evt => {
                const btn = evt.target.closest('.filter-remove');
                if (!btn) return;
                const i = Number(btn.getAttribute('data-i'));
                retuned.traineeFilters.splice(i, 1);
                _renderFilterRows(rows, retuned.traineeFilters, TRAINEE_FILTER_FIELDS);
                if (dashData && dashData.umas) renderTraineesRetuned(dashData.umas);
            });
        }

        /* ---------- Borrow fallback picker (Phase 10) ---------- */
        function renderBorrowFallbackPicker() {
            const picker = document.getElementById('borrow-fallback-picker');
            if (!picker) return;
            // fallback = veteran[1] (the implicit fallback used by the backend when guest exhausted)
            const fb = (selection.veterans && selection.veterans[1]) || null;
            if (fb && fb.card_id) {
                picker.classList.add('has-value');
                picker.innerHTML = `
                    <div class="picker-portrait"><img src="/api/images/${fb.card_id}.png" onerror="hideBrokenImage(this)"></div>
                    <span class="picker-name">${escapeHtml(fb.name || 'Selected fallback')}</span>
                    <span class="picker-arrow">›</span>`;
            } else {
                picker.classList.remove('has-value');
                picker.innerHTML = `<div class="picker-portrait">+</div><span class="picker-name">Pick a 2nd parent — used as fallback when guest is exhausted</span><span class="picker-arrow">›</span>`;
            }
        }
        /* ---------- Sparks modal (full-screen lineage detail) ---------- */
        const NODE_DISPLAY = { self: 'SELF', p1: 'P1', p2: 'P2', gp1: 'GP1', gp2: 'GP2', gp3: 'GP3', gp4: 'GP4' };
        function _sparkColorClass(category) {
            category = normalizeSparkCategory(category);
            if (category === 'stat') return 'pill-stat';
            if (category === 'aptitude') return 'pill-apt';
            if (category === 'scenario' || category === 'unique') return 'pill-unique';
            if (category === 'skill' || category === 'race') return 'pill-white';
            return 'pill-white';
        }
        function _sparkGroupId(category) {
            return sparkGroupFromCategory(category);
        }
        function _renderSparksPill(agg, mode) {
            const cls = _sparkColorClass(agg.category);
            const selfMark = agg.selfStars > 0
                ? `<span class="pill-self-mark" title="Main parent has this spark at ${agg.selfStars}★">👤 ${agg.selfStars}★</span>`
                : '';
            const pct = mode === 'per-insp' ? agg.perInsp : agg.perRun;
            const pctStr = (pct * 100).toFixed(pct < 0.1 ? 2 : pct < 0.5 ? 1 : 1) + '%';
            const title = agg.count > 1 ? ` title="${agg.count} nodes have this spark; combined ${agg.totalStars}★"` : '';
            return `<span class="sparks-pill ${cls}"${title}>
                <span class="pill-max-stars">${agg.totalStars || agg.maxStars}★</span>
                <span class="pill-name">${escapeHtml(agg.name || '')}</span>
                ${selfMark}
                <span class="pill-pct">${pctStr}</span>
            </span>`;
        }
        function _renderSparksLineage(parent) {
            const tree = parent.tree || {};
            const node = (id, role) => {
                const n = tree[id];
                if (!n) return `<div class="sparks-lineage-node"><div class="portrait-md"></div><span class="sparks-lineage-name" style="color:var(--text-dim)">—</span><span class="sparks-lineage-role">${role}</span></div>`;
                const cid = n.card_id || '';
                const img = cid ? `<img src="/api/images/${cid}.png" onerror="hideBrokenImage(this)">` : '';
                return `<div class="sparks-lineage-node">
                    <div class="portrait-md">${img}</div>
                    <span class="sparks-lineage-name">${escapeHtml(n.name || 'Unknown')}</span>
                    <span class="sparks-lineage-role">${role}</span>
                </div>`;
            };
            return `
                <div class="sparks-lineage-self">${node('self', 'SELF')}</div>
                <div class="sparks-lineage-pair">${node('p1', 'PARENT 1')}${node('p2', 'PARENT 2')}</div>
                <div class="sparks-lineage-gpair">${node('gp1', 'GP1')}${node('gp2', 'GP2')}</div>
                <div class="sparks-lineage-gpair">${node('gp3', 'GP3')}${node('gp4', 'GP4')}</div>`;
        }
        function statsFromParentFields(parent) {
            parent = parent || {};
            const stats = parent.stats && typeof parent.stats === 'object' ? parent.stats : {};
            const read = (...keys) => {
                for (const key of keys) {
                    for (const raw of [stats[key], parent[key]]) {
                        const value = Number(raw);
                        if (Number.isFinite(value) && value > 0) return value;
                    }
                }
                return 0;
            };
            return {
                speed: read('speed'),
                stamina: read('stamina'),
                power: read('power', 'pow'),
                guts: read('guts'),
                wit: read('wit', 'wiz'),
                skill_point: read('skill_point', 'skill_pt'),
                estimated_skill_points: read('estimated_skill_points'),
                max_speed: read('max_speed') || 1200,
                max_stamina: read('max_stamina') || 1200,
                max_power: read('max_power') || 1200,
                max_guts: read('max_guts') || 1200,
                max_wit: read('max_wit', 'max_wiz') || 1200
            };
        }
        function hasParentStatline(parent) {
            const stats = statsFromParentFields(parent);
            return ['speed', 'stamina', 'power', 'guts', 'wit', 'skill_point', 'estimated_skill_points'].some(key => Number(stats[key] || 0) > 0)
                || estimatedParentSkillPoints(parent) > 0;
        }
        function estimateParentSkillCost(skill) {
            const skillId = Number(skill && (skill.skill_id || skill.id) || 0);
            const explicit = Number(skill && (skill.estimated_cost || skill.cost || skill.skill_point_cost) || 0);
            if (!skillId && Number.isFinite(explicit) && explicit > 0) return explicit;
            const name = String(skill && skill.name || '');
            const hintLevel = Math.max(0, Math.min(5, Number(skill && skill.hint_level || 0) || 0));
            if (skillId > 0 && skillId < 200000) return 0;
            let base = 120;
            if (name.includes('\u25cb') || name.includes('\u25ef') || name.includes('â—‹') || name.includes('â—¯')) {
                base = 110;
            } else if (skillId >= 900000) {
                base = 200;
            } else if (skillId % 10 >= 2) {
                base = 180;
            }
            return Math.max(1, Math.floor(base * (100 - hintLevel * 10) / 100));
        }
        function normalizedParentSkills(parent) {
            const source = (parent && (parent.skills || parent.skill_array || (parent.tree && parent.tree.self && parent.tree.self.skills))) || [];
            if (!Array.isArray(source)) return [];
            return source.map(row => {
                const skillId = Number(row && (row.skill_id || row.id) || 0);
                const level = Number(row && row.level || 1);
                const fallback = skillId ? `Skill ${skillId}` : 'Unknown skill';
                return {
                    skill_id: skillId,
                    group_id: Number(row && row.group_id || (skillId >= 100000 ? Math.floor(skillId / 10) : skillId) || 0),
                    level: Number.isFinite(level) && level > 0 ? level : 1,
                    name: String(row && row.name || fallback),
                    estimated_cost: estimateParentSkillCost(row)
                };
            }).filter(row => row.skill_id || row.name).sort((a, b) => a.name.localeCompare(b.name));
        }
        function estimatedParentSkillPoints(parent) {
            const skillRows = normalizedParentSkills(parent);
            if (skillRows.length) {
                return skillRows.reduce((sum, skill) => sum + estimateParentSkillCost(skill), 0);
            }
            const direct = Number(parent && (parent.estimated_skill_points || (parent.stats && parent.stats.estimated_skill_points)) || 0);
            if (Number.isFinite(direct) && direct > 0) return direct;
            return 0;
        }
        function renderParentStatline(parent) {
            const container = document.getElementById('sparks-modal-statline');
            if (!container) return;
            if (!hasParentStatline(parent)) {
                container.innerHTML = '';
                container.hidden = true;
                return;
            }
            const stats = statsFromParentFields(parent);
            const estimatedSp = estimatedParentSkillPoints(parent);
            const actualSp = Number(stats.skill_point || 0);
            const spField = actualSp > 0
                ? { key: 'skill_point', max: null, label: 'Skill Pt', cls: 'stat-skill-point' }
                : {
                    key: 'estimated_skill_points',
                    value: estimatedSp,
                    display: estimatedSp > 0 ? `~${formatNumber(estimatedSp)}` : '0',
                    max: null,
                    label: 'Est. SP',
                    cls: 'stat-skill-point stat-est-skill-point',
                    title: 'Estimated from learned skills; exact hint discounts are not present in veteran data.'
                };
            const fields = [
                { key: 'speed', max: 'max_speed', label: 'Speed', cls: 'stat-speed' },
                { key: 'stamina', max: 'max_stamina', label: 'Stamina', cls: 'stat-stamina' },
                { key: 'power', max: 'max_power', label: 'Power', cls: 'stat-power' },
                { key: 'guts', max: 'max_guts', label: 'Guts', cls: 'stat-guts' },
                { key: 'wit', max: 'max_wit', label: 'Wit', cls: 'stat-wit' },
                spField
            ];
            container.hidden = false;
            container.innerHTML = fields.map(field => {
                const value = field.value != null ? Number(field.value || 0) : Number(stats[field.key] || 0);
                const maxValue = field.max ? Number(stats[field.max] || 1200) : 0;
                const suffix = field.max ? `<span>/${formatNumber(maxValue)}</span>` : '';
                const displayValue = field.display != null ? field.display : formatNumber(value);
                const title = field.title ? ` title="${escapeHtml(field.title)}"` : '';
                return `<div class="modal-stat-tile ${field.cls}"${title}>
                    <span class="modal-stat-label">${field.label}</span>
                    <span class="modal-stat-value">${displayValue}${suffix}</span>
                </div>`;
            }).join('');
        }
        function renderParentSkills(parent) {
            const target = document.getElementById('sparks-modal-skills');
            if (!target) return;
            const skills = normalizedParentSkills(parent);
            const estimatedSp = estimatedParentSkillPoints(parent);
            if (!skills.length) {
                target.innerHTML = '<div class="modal-empty-copy">No learned skill data is available for this parent yet. Sync Game Data after restarting the backend if this is an older cached card.</div>';
                return;
            }
            target.innerHTML = `
                <div class="sparks-pill-group-header">
                    Purchased / learned skills
                    <span class="sparks-pill-group-bar bar-white"></span>
                    ${estimatedSp > 0 ? `<span class="modal-skill-total">~${formatNumber(estimatedSp)} SP est.</span>` : ''}
                </div>
                <div class="modal-skill-grid">
                    ${skills.map(skill => `<span class="modal-skill-pill">
                        <span class="modal-skill-name">${escapeHtml(skill.name)}</span>
                        ${skill.level > 1 ? `<span class="modal-skill-level">Lv ${skill.level}</span>` : ''}
                    </span>`).join('')}
                </div>`;
        }
        function parentRaceHistory(parent) {
            const self = parent && parent.tree && parent.tree.self ? parent.tree.self : {};
            const history = Array.isArray(self.race_history) ? self.race_history : [];
            if (history.length) return history.map((row, index) => {
                const rank = Number(row.result_rank || row.finish_rank || row.rank || 0);
                return {
                    ...row,
                    _order: Number.isFinite(Number(row._order)) ? Number(row._order) : index,
                    result_rank: rank,
                    result: rank === 1 ? 'won' : rank > 1 ? 'lost' : (row.result || 'unknown')
                };
            });
            const raceIds = Array.isArray(self.win_race_ids) ? self.win_race_ids : [];
            const saddleIds = Array.isArray(self.win_saddle_ids) ? self.win_saddle_ids : [];
            return raceIds.map((raceId, i) => ({
                _order: i,
                race_id: Number(raceId) || 0,
                race_instance_id: Number(raceId) || 0,
                saddle_id: Number(saddleIds[i]) || 0,
                program_id: Number(saddleIds[i]) || 0,
                name: raceId ? `Race ${raceId}` : 'Unknown race',
                grade: '',
                source: 'win_saddle_id_array',
                result_rank: 1,
                result: 'won'
            }));
        }
        function modalRaceStyleLabel(row) {
            const raw = row && (row.style || row.strategy || row.tactic || row.running_style);
            const numeric = Number(raw);
            if (Number.isFinite(numeric) && numeric > 0) {
                return ({ 1: 'Front', 2: 'Pace', 3: 'Late', 4: 'End' })[numeric] || '';
            }
            return raceStyleLabel(raw);
        }
        function formatRaceDateLabel(row) {
            const name = String(row && row.name || '');
            const climaxMatch = name.match(/Climax Race\s*(\d+)/i);
            if (climaxMatch) return `Late Jan TS Climax Race ${climaxMatch[1]}`;
            const months = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
            const explicitDate = String(row && row.date || '').trim();
            const month = Number(row && row.month || 0);
            const half = Number(row && row.half || 0);
            const turn = Number(row && row.turn || 0);
            const parts = [];
            if (explicitDate) parts.push(explicitDate);
            if (!explicitDate && month >= 1 && month <= 12) parts.push(half === 1 ? 'Early' : half === 2 ? 'Late' : '', months[month]);
            if (turn > 0) parts.push(`Turn ${turn}`);
            return parts.filter(Boolean).join(' ');
        }
        function raceHistorySortKey(row) {
            const name = String(row && row.name || '');
            const climaxMatch = name.match(/Climax Race\s*(\d+)/i);
            if (climaxMatch) return (75 + Number(climaxMatch[1] || 0)) * 1000;
            const turn = Number(row && row.turn || 0);
            if (turn > 0) return turn * 1000 + Number(row && row.program_id || row && row.saddle_id || 0);
            const month = Number(row && row.month || 0);
            const half = Number(row && row.half || 0);
            if (month > 0) return month * 2 + half;
            return Number(row && (row.program_id || row.saddle_id || row.race_id) || 0);
        }
        function ordinalRank(rank) {
            const n = Number(rank || 0);
            if (!n) return '#1';
            const mod100 = n % 100;
            if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
            const mod10 = n % 10;
            if (mod10 === 1) return `${n}st`;
            if (mod10 === 2) return `${n}nd`;
            if (mod10 === 3) return `${n}rd`;
            return `${n}th`;
        }
        function renderParentRaceHistory(parent) {
            const target = document.getElementById('sparks-modal-races');
            if (!target) return;
            const rawRows = parentRaceHistory(parent);
            const winSaddleOnly = rawRows.length && rawRows.every(row => row.source === 'win_saddle_id_array');
            const rows = rawRows.slice().sort((a, b) => {
                if (winSaddleOnly) return Number(a._order || 0) - Number(b._order || 0);
                return (raceHistorySortKey(a) - raceHistorySortKey(b)) || (Number(a._order || 0) - Number(b._order || 0));
            });
            if (!rows.length) {
                target.innerHTML = '<div class="modal-empty-copy">No race history data is available for this parent yet.</div>';
                return;
            }
            const lossCount = rows.filter(row => Number(row.result_rank || 0) > 1).length;
            target.innerHTML = `
                <div class="sparks-pill-group-header">Parent race history <span class="sparks-pill-group-bar bar-white"></span></div>
                <div class="modal-race-note">${winSaddleOnly
                    ? 'Imported veterans expose legacy race-win titles only. Full history, losses, and strategy require race_result_array/race_history data from the game payload.'
                    : `Chronological career race rows from live/session data${lossCount ? `, including ${lossCount} non-win result${lossCount === 1 ? '' : 's'}` : ''}. Strategy is shown when the API row includes it.`}</div>
                <div class="modal-race-list">
                    ${rows.map(row => {
                        const grade = String(row.grade || 'RACE').toUpperCase();
                        const gradeClass = grade.toLowerCase().replace(/[^a-z0-9]+/g, '-');
                        const date = formatRaceDateLabel(row);
                        const style = modalRaceStyleLabel(row);
                        const desiredStyle = raceStyleLabel(
                            row.desired_running_style
                            || (row.style_change && row.style_change.desired_style)
                            || ''
                        );
                        const styleChange = row.style_change && typeof row.style_change === 'object' ? row.style_change : null;
                        let strategyText = '';
                        if (style && desiredStyle && style.toLowerCase() !== desiredStyle.toLowerCase()) {
                            strategyText = `Strategy ${style} (wanted ${desiredStyle})`;
                        } else if (style) {
                            strategyText = `Strategy ${style}`;
                        } else if (desiredStyle) {
                            strategyText = `Wanted ${desiredStyle}`;
                        }
                        const styleStatus = styleChange && styleChange.attempted && styleChange.succeeded === false
                            ? 'style change failed'
                            : '';
                        const rank = Number(row.result_rank || 0);
                        const result = String(rank === 1 ? 'won' : rank > 1 ? 'lost' : (row.result || 'unknown')).toLowerCase();
                        const ids = row.source === 'win_saddle_id_array' ? [
                            row.saddle_id ? `Legacy win #${row.saddle_id}` : '',
                        ] : [
                            strategyText,
                            styleStatus,
                            row.program_id ? `Program ${row.program_id}` : '',
                            (row.race_instance_id || row.race_id) ? `Race ${row.race_instance_id || row.race_id}` : ''
                        ];
                        const idsText = ids.filter(Boolean).join(' / ');
                        const sub = [date, idsText].filter(Boolean).join(' - ');
                        return `<div class="modal-race-row">
                            <div class="modal-race-copy">
                                <div class="modal-race-main">
                                    <span class="modal-race-grade grade-${gradeClass}">${escapeHtml(grade)}</span>
                                    <span class="modal-race-name">${escapeHtml(row.name || 'Unknown race')}</span>
                                </div>
                                <div class="modal-race-sub">${escapeHtml(sub || idsText || 'No race metadata')}</div>
                            </div>
                            <div class="modal-race-result result-${escapeAttr(result)}">${escapeHtml(ordinalRank(rank || 1))}</div>
                        </div>`;
                    }).join('')}
                </div>`;
        }
        let _sparksModalParent = null;
        let _sparksModalMode = 'per-run';
        let _sparksModalScope = 'lineage';
        function _sparksModalNodes() {
            return _sparksModalScope === 'self' ? ['self'] : EFFECTIVE_SPARK_NODES;
        }
        function openSparksModal(parent) {
            const overlay = document.getElementById('sparks-modal-overlay');
            if (!overlay || !parent) return;
            _sparksModalParent = parent;
            const imgId = parent.card_id || '100101';
            const name = parent.name || 'Unknown';
            const rank = rankLabel(parent);
            const score = parent.score != null ? formatNumber(parent.score) : '—';
            const affinity = parentMetric(parent, 'affinity');
            const g1 = countWinsByGrade(parent, 'g1');
            const whites = countWhiteFactors(parent, EFFECTIVE_SPARK_NODES);
            const portrait = document.getElementById('sparks-modal-portrait');
            const nameEl = document.getElementById('sparks-modal-name');
            const subEl = document.getElementById('sparks-modal-sub');
            const kpis = document.getElementById('sparks-modal-kpis');
            const lineage = document.getElementById('sparks-modal-lineage');
            if (portrait) portrait.innerHTML = `<img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">`;
            if (nameEl) nameEl.textContent = name;
            if (subEl) {
                const parts = [parent.instance_id ? `ID ${parent.instance_id}` : `Card ${imgId}`];
                if (parent.made_by_bot) parts.push('BOT-made');
                const botInfo = parent.bot_parent_info || {};
                if (botInfo.deck_name || botInfo.deck_id) parts.push(`Deck ${botInfo.deck_name || botInfo.deck_id}`);
                if (parent.variant_name) parts.push(parent.variant_name);
                subEl.textContent = parts.join(' | ');
            }
            if (kpis) kpis.innerHTML = `
                <div class="kpi kpi-affinity"><span class="kpi-val">${affinity != null ? affinity : '—'}</span><span class="kpi-lbl">Affinity</span></div>
                <div class="kpi kpi-g1"><span class="kpi-val">${g1}</span><span class="kpi-lbl">G1 Wins</span></div>
                <div class="kpi kpi-white"><span class="kpi-val">${whites}</span><span class="kpi-lbl">White Factors</span></div>
                <div class="kpi kpi-score"><span class="kpi-val">${score}</span><span class="kpi-lbl">Score</span></div>
                <div class="tt-rank-coin" style="background:${rankCoinColor(rank)}">${rank}</div>`;
            if (lineage) lineage.innerHTML = _renderSparksLineage(parent);
            renderParentStatline(parent);
            renderParentSkills(parent);
            renderParentRaceHistory(parent);
            _refreshSparksModalPills();
            overlay.classList.add('is-open');
        }
        function _refreshSparksModalPills() {
            if (!_sparksModalParent) return;
            const showSkills = _sparksModalMode === 'skills';
            const showRaces = _sparksModalMode === 'races';
            const skillsEl = document.getElementById('sparks-modal-skills');
            const racesEl = document.getElementById('sparks-modal-races');
            const scopeEl = document.querySelector('.sparks-scope-toggle');
            if (skillsEl) skillsEl.hidden = !showSkills;
            if (racesEl) racesEl.hidden = !showRaces;
            if (scopeEl) scopeEl.hidden = showSkills || showRaces;
            ['blue', 'pink', 'green', 'white'].forEach(gid => {
                const groupEl = document.getElementById('sparks-modal-pills-' + gid);
                if (groupEl) groupEl.hidden = showSkills || showRaces;
            });
            if (showSkills || showRaces) return;
            const aggs = sparkAggList(_sparksModalParent, _sparksModalNodes());
            // group by category
            const groups = { blue: [], pink: [], green: [], white: [] };
            aggs.forEach(a => { groups[_sparkGroupId(a.category)].push(a); });
            // sort each group by per-run % desc, then total stars desc
            Object.keys(groups).forEach(g => {
                groups[g].sort((a, b) => (b.perRun - a.perRun) || ((b.totalStars || b.maxStars) - (a.totalStars || a.maxStars)));
            });
            const mode = _sparksModalMode;
            const renderInto = (gid, label) => {
                const groupEl = document.getElementById('sparks-modal-pills-' + gid);
                if (!groupEl) return;
                const list = groupEl.querySelector('.sparks-pill-list');
                if (!list) return;
                const items = groups[gid] || [];
                list.innerHTML = items.length ? items.map(a => _renderSparksPill(a, mode)).join('') : '';
            };
            renderInto('blue');  renderInto('pink');  renderInto('green');  renderInto('white');
        }
        function closeSparksModal() {
            const overlay = document.getElementById('sparks-modal-overlay');
            if (overlay) overlay.classList.remove('is-open');
            _sparksModalParent = null;
        }
        function bindSparksModal() {
            const overlay = document.getElementById('sparks-modal-overlay');
            const closeBtn = document.getElementById('sparks-modal-close');
            const perRunBtn = document.getElementById('sparks-mode-per-run');
            const perInspBtn = document.getElementById('sparks-mode-per-insp');
            const skillsBtn = document.getElementById('sparks-mode-skills');
            const racesBtn = document.getElementById('sparks-mode-races');
            const lineageScopeBtn = document.getElementById('sparks-scope-lineage');
            const selfScopeBtn = document.getElementById('sparks-scope-self');
            if (!overlay) return;
            const setMode = (mode) => {
                _sparksModalMode = mode;
                [
                    [perRunBtn, 'per-run'],
                    [perInspBtn, 'per-insp'],
                    [skillsBtn, 'skills'],
                    [racesBtn, 'races']
                ].forEach(([btn, value]) => {
                    if (!btn) return;
                    btn.classList.toggle('active', value === mode);
                    btn.classList.toggle('accent', value === mode);
                });
                _refreshSparksModalPills();
            };
            const setScope = (scope) => {
                _sparksModalScope = scope === 'self' ? 'self' : 'lineage';
                [
                    [lineageScopeBtn, 'lineage'],
                    [selfScopeBtn, 'self']
                ].forEach(([btn, value]) => {
                    if (!btn) return;
                    btn.classList.toggle('active', value === _sparksModalScope);
                    btn.classList.toggle('accent', value === _sparksModalScope);
                });
                _refreshSparksModalPills();
            };
            if (overlay.dataset.bound !== '1') {
                overlay.dataset.bound = '1';
                overlay.addEventListener('click', evt => {
                    if (evt.target === overlay) closeSparksModal();
                });
            }
            if (closeBtn && closeBtn.dataset.bound !== '1') {
                closeBtn.dataset.bound = '1';
                closeBtn.addEventListener('click', closeSparksModal);
            }
            if (perRunBtn && perRunBtn.dataset.bound !== '1') {
                perRunBtn.dataset.bound = '1';
                perRunBtn.addEventListener('click', () => setMode('per-run'));
            }
            if (perInspBtn && perInspBtn.dataset.bound !== '1') {
                perInspBtn.dataset.bound = '1';
                perInspBtn.addEventListener('click', () => setMode('per-insp'));
            }
            if (skillsBtn && skillsBtn.dataset.bound !== '1') {
                skillsBtn.dataset.bound = '1';
                skillsBtn.addEventListener('click', () => setMode('skills'));
            }
            if (racesBtn && racesBtn.dataset.bound !== '1') {
                racesBtn.dataset.bound = '1';
                racesBtn.addEventListener('click', () => setMode('races'));
            }
            if (lineageScopeBtn && lineageScopeBtn.dataset.bound !== '1') {
                lineageScopeBtn.dataset.bound = '1';
                lineageScopeBtn.addEventListener('click', () => setScope('lineage'));
            }
            if (selfScopeBtn && selfScopeBtn.dataset.bound !== '1') {
                selfScopeBtn.dataset.bound = '1';
                selfScopeBtn.addEventListener('click', () => setScope('self'));
            }
            if (!retuned._sparksEscBound) {
                retuned._sparksEscBound = true;
                document.addEventListener('keydown', evt => {
                    if (evt.key === 'Escape') {
                        const o = document.getElementById('sparks-modal-overlay');
                        if (o && o.classList.contains('is-open')) closeSparksModal();
                    }
                });
            }
        }

        /* ---------- Team-bar RUN button mirror (forwards click + mirrors disabled state) ---------- */
        /* ---------- Team-bar empty-slot click → switch to the appropriate library pane ---------- */
        function bindEmptyTeamSlots() {
            const slotPaneMap = {
                'team-slot-deck':    'decks',
                'team-slot-friend':  'friends',
                'team-slot-trainee': 'trainees',
                'team-slot-vet1':    'parents',
                'team-slot-vet2':    'parents'
            };
            Object.keys(slotPaneMap).forEach(slotId => {
                const el = document.getElementById(slotId);
                if (!el || el.dataset.emptyJumpBound === '1') return;
                el.dataset.emptyJumpBound = '1';
                // Use capture phase so we run BEFORE renderTeamPanel's onclick (which mutates DOM)
                el.addEventListener('click', () => {
                    if (el.classList.contains('filled')) return; // filled → let the existing onclick (deselect) run
                    if (typeof switchLibraryPane === 'function') switchLibraryPane(slotPaneMap[slotId]);
                }, true);
            });
        }

        /* Removed: deck-list click delegation.
           `attachDeckHandlers` already binds per-element click handlers after
           every `renderDecks`. Adding a delegated handler on top caused
           `selectDeck` to fire TWICE per click (toggle → toggle = no net
           selection change). The decks appeared un-clickable. */
        function bindGridSelectionDelegation() { /* intentional no-op */ }

        /* ---------- Team-bar RUN button mirror (forwards click + mirrors disabled state) ---------- */
        function bindTeamBarRunButton() {
            const barBtn = document.getElementById('start-career-bar-btn');
            const origBtn = document.getElementById('start-career-btn');
            if (!barBtn || !origBtn) return;
            if (barBtn.dataset.bound === '1') {
                barBtn.disabled = origBtn.disabled;
                return;
            }
            barBtn.dataset.bound = '1';
            barBtn.disabled = origBtn.disabled;
            barBtn.addEventListener('click', evt => {
                if (barBtn.disabled) return;
                evt.preventDefault();
                origBtn.click();
            });
            // Mirror disabled state when the original toggles
            const obs = new MutationObserver(() => { barBtn.disabled = origBtn.disabled; });
            obs.observe(origBtn, { attributes: true, attributeFilter: ['disabled'] });
        }

        function bindBorrowFallback() {
            const clearBtn = document.getElementById('borrow-fallback-clear-btn');
            if (clearBtn && clearBtn.dataset.bound !== '1') {
                clearBtn.dataset.bound = '1';
                clearBtn.addEventListener('click', () => {
                    if (selection.veterans && selection.veterans.length > 1) {
                        selection.veterans = selection.veterans.slice(0, 1);
                        renderBorrowFallbackPicker();
                        renderTeamPanel();
                        if (dashData && dashData.parents) renderParentsRetuned(dashData.parents);
                        syncSelectionToServer();
                    }
                });
            }
            const picker = document.getElementById('borrow-fallback-picker');
            if (picker && picker.dataset.bound !== '1') {
                picker.dataset.bound = '1';
                picker.addEventListener('click', () => switchLibraryPane('parents'));
            }
        }

        /* ---------- Deck list/detail toggle (Phase 9) ---------- */
        function showDeckList() {
            retuned.deckDetail = null;
            const lv = document.getElementById('deck-list-view');
            const dv = document.getElementById('deck-detail-view');
            if (lv) lv.classList.remove('is-hidden');
            if (dv) dv.classList.remove('is-active');
        }
        function showDeckDetail(deck) {
            retuned.deckDetail = deck;
            const lv = document.getElementById('deck-list-view');
            const dv = document.getElementById('deck-detail-view');
            const nm = document.getElementById('deck-detail-name');
            const mt = document.getElementById('deck-detail-meta');
            const slotsHost = document.getElementById('deck-slots');
            if (lv) lv.classList.add('is-hidden');
            if (dv) dv.classList.add('is-active');
            if (nm) nm.innerText = deck.name || deck.title || `Deck ${deck.id || ''}`;
            const slots = Array.isArray(deck.cards) ? deck.cards : Array.isArray(deck.supports) ? deck.supports : [];
            if (mt) mt.innerText = `${slots.length} cards${deck.last_used ? ' · last used ' + deck.last_used : ''}`;
            if (!slotsHost) return;
            slotsHost.innerHTML = (slots.length ? slots : Array(6).fill({})).slice(0, 6).map((c, idx) => {
                const imgId = c.id || c.card_id;
                const rarity = c.rarity || '';
                const rarityCls = (rarity === 'SSR' || rarity === 'SR' || rarity === 'R') ? `rarity-${rarity}` : '';
                return `<div class="deck-slot-card">
                    <span class="deck-slot-label">Slot ${idx + 1}</span>
                    ${rarity ? `<span class="rarity-pill ${rarityCls}">${rarity}</span>` : ''}
                    <div class="deck-slot-portrait">${imgId ? `<img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">` : '—'}</div>
                    <div class="deck-slot-name">${escapeHtml(c.name || (imgId ? '#' + imgId : 'Empty'))}</div>
                </div>`;
            }).join('');
        }
        function bindDeckDetail() {
            const back = document.getElementById('deck-back-btn');
            if (back && back.dataset.bound !== '1') {
                back.dataset.bound = '1';
                back.addEventListener('click', showDeckList);
            }
            const list = document.getElementById('deck-list');
            if (list && list.dataset.detailBound !== '1') {
                list.dataset.detailBound = '1';
                list.addEventListener('dblclick', evt => {
                    const container = evt.target.closest('.deck-container');
                    if (!container) return;
                    const all = Array.from(list.querySelectorAll('.deck-container'));
                    const idx = all.indexOf(container);
                    const decks = (dashData && dashData.visibleDecks) || (dashData && dashData.validDecks) || [];
                    if (idx >= 0 && decks[idx]) showDeckDetail(decks[idx]);
                });
            }
        }

        const DECK_CARD_LIMIT = 5;
        function supportCardId(card) {
            return Number(card && (card.id || card.support_card_id || card.card_id) || 0) || 0;
        }
        function deckCards(deck) {
            if (!deck) return [];
            if (Array.isArray(deck.cards)) return deck.cards;
            if (Array.isArray(deck.supports)) return deck.supports;
            return [];
        }
        function deckCardIds(deck) {
            return deckCards(deck).map(supportCardId).filter(id => id > 0).slice(0, DECK_CARD_LIMIT);
        }
        function findDashboardDeck(deckId) {
            const id = Number(deckId || 0);
            if (!id || !dashData) return null;
            const buckets = [dashData.decks, dashData.validDecks, dashData.visibleDecks];
            for (const bucket of buckets) {
                const deck = (bucket || []).find(item => Number(item && item.id) === id);
                if (deck) return deck;
            }
            return null;
        }
        function deckSupportInventory() {
            return Array.isArray(dashData && dashData.supports) ? dashData.supports : [];
        }
        function deckEditorCardLabel(card) {
            const parts = [];
            if (card && card.rarity) parts.push(card.rarity);
            if (card && card.type) parts.push(card.type);
            const level = Number(card && (card.support_card_level || card.level) || 0);
            if (level) parts.push(`Lv${level}`);
            parts.push(`LB${Number(card && card.limit_break_count || 0)}`);
            return parts.join(' / ');
        }
        function deckEditorMatches(card, query) {
            const q = String(query || '').trim().toLowerCase();
            if (!q) return true;
            return [
                card && card.id,
                card && card.support_card_id,
                card && card.name,
                card && card.rarity,
                card && card.type
            ].some(value => String(value || '').toLowerCase().includes(q));
        }
        function setDeckEditorStatus(message, isError = false) {
            if (!els.deckEditorStatus) return;
            els.deckEditorStatus.textContent = String(message || '').trim();
            els.deckEditorStatus.classList.toggle('error', !!isError);
        }
        function replaceDeckInDashboard(updatedDeck, dashboard = null) {
            if (!dashData) return updatedDeck || null;
            if (dashboard && Array.isArray(dashboard.decks)) dashData.decks = dashboard.decks;
            if (dashboard && Array.isArray(dashboard.supports)) dashData.supports = dashboard.supports;
            if (updatedDeck && updatedDeck.id) {
                const decks = Array.isArray(dashData.decks) ? dashData.decks.slice() : [];
                const idx = decks.findIndex(deck => Number(deck && deck.id) === Number(updatedDeck.id));
                if (idx >= 0) decks[idx] = updatedDeck;
                else decks.push(updatedDeck);
                dashData.decks = decks;
            }
            dashData.validDecks = (dashData.decks || []).filter(isValidDeck);
            const deckId = Number((updatedDeck && updatedDeck.id) || (retuned.deckDetail && retuned.deckDetail.id) || 0);
            const resolved = findDashboardDeck(deckId) || updatedDeck || null;
            if (selection.deck && Number(selection.deck.id) === deckId && resolved) {
                selection.deck = resolved;
                syncSelectionToServer();
            }
            renderDecks(dashData.validDecks);
            attachDeckHandlers();
            renderTeamPanel();
            syncStartButton();
            return resolved;
        }
        function renderDeckEditorPicker(deck) {
            if (!els.deckEditorCardList) return;
            if (els.deckEditorCardSearch && els.deckEditorCardSearch.value !== state.deckEditorSearch) {
                els.deckEditorCardSearch.value = state.deckEditorSearch || '';
            }
            const ids = deckCardIds(deck);
            const selected = new Set(ids.map(String));
            if (ids.length >= DECK_CARD_LIMIT) {
                els.deckEditorCardList.innerHTML = '<div class="deck-editor-empty">Deck is full. Remove a card before adding another.</div>';
                return;
            }
            const rarityOrder = { SSR: 0, SR: 1, R: 2 };
            const rows = deckSupportInventory()
                .filter(card => {
                    const id = supportCardId(card);
                    return id > 0 && !selected.has(String(id)) && deckEditorMatches(card, state.deckEditorSearch);
                })
                .sort((a, b) => {
                    const ar = rarityOrder[String(a.rarity || '').toUpperCase()] ?? 9;
                    const br = rarityOrder[String(b.rarity || '').toUpperCase()] ?? 9;
                    return ar - br || String(a.type || '').localeCompare(String(b.type || '')) || String(a.name || '').localeCompare(String(b.name || ''));
                })
                .slice(0, 80);
            if (!rows.length) {
                els.deckEditorCardList.innerHTML = '<div class="deck-editor-empty">No owned cards match this search.</div>';
                return;
            }
            els.deckEditorCardList.innerHTML = rows.map(card => {
                const id = supportCardId(card);
                return `<div class="deck-picker-card">
                    <div class="deck-picker-thumb"><img src="/api/images/${id || '10001'}.png" onerror="hideBrokenImage(this)"></div>
                    <div class="deck-picker-main">
                        <div class="deck-picker-name">${escapeHtml(card.name || `Support ${id}`)}</div>
                        <div class="deck-picker-meta">${escapeHtml(deckEditorCardLabel(card))}</div>
                    </div>
                    <button class="deck-add-card-btn" type="button" data-card-id="${id}" ${state.deckEditorBusy ? 'disabled' : ''}>ADD</button>
                </div>`;
            }).join('');
        }
        function renderDeckSlots(deck) {
            const slotsHost = document.getElementById('deck-slots');
            if (!slotsHost) return;
            const slots = deckCards(deck).slice(0, DECK_CARD_LIMIT);
            const displaySlots = Array.from({ length: DECK_CARD_LIMIT }, (_, idx) => slots[idx] || null);
            slotsHost.innerHTML = displaySlots.map((c, idx) => {
                const imgId = supportCardId(c);
                const rarity = c && c.rarity ? String(c.rarity) : '';
                const rarityCls = (rarity === 'SSR' || rarity === 'SR' || rarity === 'R') ? `rarity-${rarity}` : '';
                return `<div class="deck-slot-card ${imgId ? '' : 'is-empty'}">
                    <span class="deck-slot-label">Slot ${idx + 1}</span>
                    ${rarity ? `<span class="rarity-pill ${rarityCls}">${escapeHtml(rarity)}</span>` : ''}
                    ${imgId ? `<button class="deck-slot-remove" type="button" data-slot-index="${idx}" ${state.deckEditorBusy ? 'disabled' : ''}>REMOVE</button>` : ''}
                    <div class="deck-slot-portrait">${imgId ? `<img src="/api/images/${imgId}.png" onerror="hideBrokenImage(this)">` : '+'}</div>
                    <div class="deck-slot-name">${escapeHtml(c && c.name ? c.name : (imgId ? '#' + imgId : 'Empty'))}</div>
                    ${imgId ? `<div class="deck-slot-meta">${escapeHtml(deckEditorCardLabel(c))}</div>` : '<div class="deck-slot-meta">Pick a card below</div>'}
                </div>`;
            }).join('');
        }
        async function saveDeckEdit(deck, supportIds, options = {}) {
            const deckId = Number(deck && deck.id || 0);
            if (!deckId) {
                setDeckEditorStatus('Cannot save: deck id is missing.', true);
                return;
            }
            state.deckEditorBusy = true;
            renderDeckSlots(deck);
            renderDeckEditorPicker(deck);
            setDeckEditorStatus(options.clear ? 'Resetting deck to synced game data...' : 'Saving deck edit...');
            try {
                const payload = options.clear
                    ? { deck_id: deckId, clear_override: true }
                    : { deck_id: deckId, name: deck.name || `Deck ${deckId}`, support_card_ids: supportIds };
                const data = await apiJson('/api/decks/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!data.success) throw new Error(data.detail || 'Deck save failed');
                state.deckEditorBusy = false;
                const updated = replaceDeckInDashboard(data.deck || null, data.dashboard || null) || findDashboardDeck(deckId) || deck;
                retuned.deckDetail = updated;
                showDeckDetail(updated);
                const count = deckCardIds(updated).length;
                setDeckEditorStatus(options.clear
                    ? `Reset to synced deck (${count}/${DECK_CARD_LIMIT}).`
                    : `Saved deck edit (${count}/${DECK_CARD_LIMIT}). Changes will be used when starting the bot.`);
            } catch (e) {
                state.deckEditorBusy = false;
                showDeckDetail(retuned.deckDetail || deck);
                setDeckEditorStatus(e.message || 'Deck save failed', true);
            }
        }
        function addCardToDeck(cardId) {
            const deck = retuned.deckDetail;
            const id = Number(cardId || 0);
            if (!deck || !id || state.deckEditorBusy) return;
            const ids = deckCardIds(deck);
            if (ids.includes(id)) {
                setDeckEditorStatus('That card is already in this deck.', true);
                return;
            }
            if (ids.length >= DECK_CARD_LIMIT) {
                setDeckEditorStatus('Deck is full. Remove a card first.', true);
                return;
            }
            saveDeckEdit(deck, ids.concat(id));
        }
        function removeCardFromDeck(slotIndex) {
            const deck = retuned.deckDetail;
            const idx = Number(slotIndex);
            if (!deck || !Number.isInteger(idx) || state.deckEditorBusy) return;
            const ids = deckCardIds(deck);
            if (idx < 0 || idx >= ids.length) return;
            ids.splice(idx, 1);
            saveDeckEdit(deck, ids);
        }
        function showDeckList() {
            retuned.deckDetail = null;
            const lv = document.getElementById('deck-list-view');
            const dv = document.getElementById('deck-detail-view');
            if (lv) lv.classList.remove('is-hidden');
            if (dv) dv.classList.remove('is-active');
        }
        function showDeckDetail(deck) {
            const resolved = findDashboardDeck(deck && deck.id) || deck;
            if (!resolved) return;
            retuned.deckDetail = resolved;
            const lv = document.getElementById('deck-list-view');
            const dv = document.getElementById('deck-detail-view');
            const nm = document.getElementById('deck-detail-name');
            const mt = document.getElementById('deck-detail-meta');
            if (lv) lv.classList.add('is-hidden');
            if (dv) dv.classList.add('is-active');
            if (nm) nm.innerText = resolved.name || resolved.title || `Deck ${resolved.id || ''}`;
            const slots = deckCards(resolved);
            if (mt) mt.innerText = `${slots.length}/${DECK_CARD_LIMIT} cards${resolved.edited ? ' - local edit' : ''}${resolved.last_used ? ' - last used ' + resolved.last_used : ''}`;
            renderDeckSlots(resolved);
            renderDeckEditorPicker(resolved);
            setDeckEditorStatus(resolved.edited
                ? `Local deck edit active (${slots.length}/${DECK_CARD_LIMIT}). Changes are used when starting the bot.`
                : `Editing synced deck slot ${resolved.id || ''} (${slots.length}/${DECK_CARD_LIMIT}).`);
        }
        function bindDeckDetail() {
            const back = document.getElementById('deck-back-btn');
            if (back && back.dataset.bound !== '1') {
                back.dataset.bound = '1';
                back.addEventListener('click', showDeckList);
            }
            if (els.deckResetBtn && els.deckResetBtn.dataset.bound !== '1') {
                els.deckResetBtn.dataset.bound = '1';
                els.deckResetBtn.addEventListener('click', () => {
                    if (retuned.deckDetail && !state.deckEditorBusy) {
                        saveDeckEdit(retuned.deckDetail, [], { clear: true });
                    }
                });
            }
            if (els.deckEditorCardSearch && els.deckEditorCardSearch.dataset.bound !== '1') {
                els.deckEditorCardSearch.dataset.bound = '1';
                els.deckEditorCardSearch.addEventListener('input', () => {
                    state.deckEditorSearch = els.deckEditorCardSearch.value || '';
                    renderDeckEditorPicker(retuned.deckDetail);
                });
            }
            const slotsHost = document.getElementById('deck-slots');
            if (slotsHost && slotsHost.dataset.bound !== '1') {
                slotsHost.dataset.bound = '1';
                slotsHost.addEventListener('click', evt => {
                    const button = evt.target.closest('.deck-slot-remove');
                    if (!button) return;
                    evt.preventDefault();
                    evt.stopPropagation();
                    removeCardFromDeck(Number(button.dataset.slotIndex));
                });
            }
            if (els.deckEditorCardList && els.deckEditorCardList.dataset.bound !== '1') {
                els.deckEditorCardList.dataset.bound = '1';
                els.deckEditorCardList.addEventListener('click', evt => {
                    const button = evt.target.closest('.deck-add-card-btn');
                    if (!button) return;
                    evt.preventDefault();
                    evt.stopPropagation();
                    addCardToDeck(Number(button.dataset.cardId));
                });
            }
            const list = document.getElementById('deck-list');
            if (list && list.dataset.detailBound !== '1') {
                list.dataset.detailBound = '1';
                list.addEventListener('dblclick', evt => {
                    if (evt.target.closest('.deck-edit-btn')) return;
                    const container = evt.target.closest('.deck-container');
                    if (!container) return;
                    const all = Array.from(list.querySelectorAll('.deck-container'));
                    const idx = all.indexOf(container);
                    const decks = (dashData && dashData.visibleDecks) || (dashData && dashData.validDecks) || [];
                    if (idx >= 0 && decks[idx]) showDeckDetail(decks[idx]);
                });
            }
        }

        /* ---------- Race calendar modal (Phase 5) ---------- */
        const RACE_TURN_LABELS = [
            'Early Jan','Late Jan','Early Feb','Late Feb','Early Mar','Late Mar',
            'Early Apr','Late Apr','Early May','Late May','Early Jun','Late Jun',
            'Early Jul','Late Jul','Early Aug','Late Aug','Early Sep','Late Sep',
            'Early Oct','Late Oct','Early Nov','Late Nov','Early Dec','Late Dec'
        ];
        const RACE_TURN_ROW_SIZE = 4;
        const YEAR_KEYS = { junior: 'Junior Year', classic: 'Classic Year', senior: 'Senior Year' };
        function _parseRaceDate(dateStr) {
            // Real format: "Junior Year Late Jul", "Classic Year Early Jan", "Senior Year Early Mar"
            const s = String(dateStr || '');
            let year = null;
            if (s.startsWith('Junior')) year = 'junior';
            else if (s.startsWith('Classic')) year = 'classic';
            else if (s.startsWith('Senior')) year = 'senior';
            const rest = s.replace(/^(Junior|Classic|Senior)\s+Year\s+/i, '').trim();
            return { year, turn: rest };
        }
        function _isOffSeason(year, turnLabel) {
            if (year !== 'junior') return false;
            // Junior canon: only Jul–Dec are live; everything before Early Jul is off-season
            const idx = RACE_TURN_LABELS.indexOf(turnLabel);
            // index 12 = Early Jul (Jan early=0 ... Jun late=11, Jul early=12)
            return idx >= 0 && idx < 12;
        }
        function setRaceCalendarStatus(message, isError = false) {
            if (!els.raceModalStatus) return;
            els.raceModalStatus.textContent = String(message || '').trim() || 'Build a clean three-year race agenda, then save it back into the preset.';
            els.raceModalStatus.classList.toggle('is-error', !!isError);
        }
        function hydrateRaceCalendarDraftFromSaved() {
            retuned.calendarPicks = new Set(Array.from(state.selectedRaces || []).map(Number).filter(n => !Number.isNaN(n)));
            retuned.calendarStyles = { ...selectedRaceStylePayload() };
        }
        function isRaceCalendarDraftShape(data) {
            if (!data || typeof data !== 'object') return false;
            return Array.isArray(data.race_ids)
                || Array.isArray(data.races)
                || Array.isArray(data.selected_race_ids)
                || Array.isArray(data.entries)
                || Array.isArray(data.custom_race_schedule)
                || (data.styles && typeof data.styles === 'object');
        }
        function applyRaceCalendarDraftData(data) {
            const picks = new Set();
            const styleMap = {};
            const addId = (value) => {
                const id = Number(value);
                if (!Number.isNaN(id) && id > 0) picks.add(id);
            };
            const addStyle = (value, styleValue) => {
                const id = Number(value);
                const style = normalizeRaceStyleValue(styleValue);
                if (!Number.isNaN(id) && id > 0 && style) styleMap[String(id)] = style;
            };
            const raceIds = Array.isArray(data?.race_ids) ? data.race_ids
                : Array.isArray(data?.races) ? data.races
                : Array.isArray(data?.selected_race_ids) ? data.selected_race_ids
                : [];
            raceIds.forEach(addId);
            if (data && typeof data.styles === 'object' && data.styles) {
                Object.entries(data.styles).forEach(([rid, styleValue]) => {
                    addId(rid);
                    addStyle(rid, styleValue);
                });
            }
            const entryLists = [];
            if (Array.isArray(data?.entries)) entryLists.push(data.entries);
            if (Array.isArray(data?.custom_race_schedule)) entryLists.push(data.custom_race_schedule);
            entryLists.forEach(entries => {
                entries.forEach(entry => {
                    const raceId = entry?.race_id ?? entry?.id;
                    addId(raceId);
                    addStyle(raceId, entry?.style ?? entry?.selectedStyle);
                });
            });
            retuned.calendarPicks = picks;
            retuned.calendarStyles = selectedRaceStylePayload(picks, styleMap);
        }
        async function persistRaceCalendarDraft(message) {
            state.selectedRaces = new Set(Array.from(retuned.calendarPicks));
            state.selectedRaceStyles = selectedRaceStylePayload(retuned.calendarPicks, retuned.calendarStyles);
            state.racePlanText = "";
            if (els.racePlanInput) els.racePlanInput.value = "";
            if (typeof autoSaveRaces === 'function') await autoSaveRaces();
            if (typeof renderRaces === 'function') { try { renderRaces(); } catch (e) {} }
            setRacePlanStatus(message || "Race calendar updated.");
        }
        async function importRaceCalendarDraftFile(event) {
            const file = event.target.files && event.target.files[0];
            if (!file) return;
            try {
                const text = await file.text();
                const parsed = JSON.parse(text);
                if (isRaceCalendarDraftShape(parsed)) {
                    applyRaceCalendarDraftData(parsed);
                    await persistRaceCalendarDraft(`Imported ${retuned.calendarPicks.size} race pick${retuned.calendarPicks.size === 1 ? '' : 's'} from ${file.name}.`);
                    populateRaceCalendarGrid();
                    setRaceCalendarStatus(`Imported ${retuned.calendarPicks.size} race pick${retuned.calendarPicks.size === 1 ? '' : 's'} from ${file.name}.`);
                } else {
                    const data = await apiJson('/api/presets/save_race_plan', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            preset_name: selectedPresetName(),
                            text,
                            ...currentRacePlanPayload()
                        })
                    });
                    if (!data.success) {
                        throw new Error(formatRacePlanErrors(data.errors) || data.detail || "Race plan import failed.");
                    }
                    state.selectedRaces = new Set((data.race_ids || []).map(id => parseInt(id, 10)));
                    setSelectedRaceStylesFromEntries(data.entries || []);
                    if (typeof renderRaces === 'function') { try { renderRaces(); } catch (e) {} }
                    hydrateRaceCalendarDraftFromSaved();
                    populateRaceCalendarGrid();
                    const count = (data.entries || []).length;
                    setRacePlanStatus(`Imported ${count} scheduled race${count === 1 ? '' : 's'} from ${file.name}.`);
                    setRaceCalendarStatus(`Imported ${count} scheduled race${count === 1 ? '' : 's'} from ${file.name}.`);
                }
            } catch (e) {
                const message = e && e.message ? e.message : 'Could not import that agenda file.';
                setRacePlanStatus(message, true);
                setRaceCalendarStatus(message, true);
            } finally {
                event.target.value = '';
            }
        }
        function renderRaceCalendarStyleList() {
            if (!els.raceStyleList) return;
            const entries = selectedRaceEntries(retuned.calendarPicks, retuned.calendarStyles);
            const overrideCount = Object.keys(selectedRaceStylePayload(retuned.calendarPicks, retuned.calendarStyles)).length;
            const search = String(retuned.calendarSearch || '').trim().toLowerCase();
            const visibleEntries = search ? entries.filter(race => {
                const haystack = [
                    race.name || '',
                    race.date || '',
                    race.type || '',
                    race.terrain || '',
                    race.distance || '',
                    race.venue || ''
                ].join(' ').toLowerCase();
                return haystack.includes(search);
            }) : entries;
            if (els.raceStyleCount) {
                const suffix = overrideCount ? ` | ${overrideCount} override${overrideCount === 1 ? '' : 's'}` : '';
                els.raceStyleCount.textContent = `${entries.length} selected${suffix}`;
            }
            if (!entries.length) {
                els.raceStyleList.innerHTML = `<div class="race-style-empty">Pick races on the calendar, then set an override only on the races that need a different tactic.</div>`;
                return;
            }
            if (!visibleEntries.length) {
                els.raceStyleList.innerHTML = `<div class="race-style-empty">No selected races match the current search.</div>`;
                return;
            }
            els.raceStyleList.innerHTML = visibleEntries.map(race => `
                <div class="race-style-item" data-rid="${race.id}">
                    <div class="race-style-item-top">
                        <span class="race-style-turn">${escapeHtml(race.date || '')}</span>
                        <span class="race-style-grade">${escapeHtml(String(race.type || '').toUpperCase())}</span>
                    </div>
                    <div class="race-style-race">${escapeHtml(race.name || 'Race')}</div>
                    <div class="race-style-select-row">
                        <select class="race-style-select" data-rid="${race.id}">
                            ${raceStyleOptionsHtml(race.selectedStyle)}
                        </select>
                        <button type="button" class="btn btn-sm race-style-clear" data-clear-rid="${race.id}">Clear</button>
                    </div>
                </div>
            `).join('');
        }
        function openRaceCalendar() {
            const overlay = document.getElementById('race-modal-overlay');
            if (!overlay) return;
            overlay.classList.add('is-open');
            retuned.calendarOpen = true;
            hydrateRaceCalendarDraftFromSaved();
            retuned.calendarSearch = '';
            if (els.raceModalSearchInput) els.raceModalSearchInput.value = '';
            setRaceCalendarStatus('Click a slot to add, replace, or clear a race. Save when the agenda looks right.');
            populateRaceCalendarGrid();
        }
        function closeRaceCalendar() {
            const overlay = document.getElementById('race-modal-overlay');
            if (!overlay) return;
            overlay.classList.remove('is-open');
            retuned.calendarOpen = false;
            if (els.raceModalSearchInput) els.raceModalSearchInput.value = '';
            retuned.calendarSearch = '';
        }
        function _gradeOf(r) {
            const t = String(r && r.type || '').toUpperCase().replace(/[\s-]/g, '');
            if (t === 'G1' || t === 'G2' || t === 'G3') return t;
            if (t === 'OP')    return 'OP';
            if (t === 'PREOP') return 'PRE';
            return '';
        }
        function populateRaceCalendarGrid() {
            const races = (state.raceData || []).map(r => ({...r, _parsed: _parseRaceDate(r.date)}));
            const search = String(retuned.calendarSearch || '').trim().toLowerCase();
            ['junior','classic','senior'].forEach(year => {
                const host = document.getElementById('cal-grid-' + year);
                if (!host) return;
                const slots = RACE_TURN_LABELS.map(turnLabel => {
                    if (_isOffSeason(year, turnLabel)) {
                        return `<div class="cal-slot off-season"><span class="cal-cell-label">${turnLabel}</span></div>`;
                    }
                    const candidates = races.filter(r => r._parsed.year === year && r._parsed.turn === turnLabel);
                    if (!candidates.length) {
                        return `<div class="cal-slot empty" data-year="${year}" data-turn="${escapeAttr(turnLabel)}"><span class="cal-cell-label">${turnLabel}</span></div>`;
                    }
                    // pick the highest-grade race for display when multiple share a slot
                    candidates.sort((a, b) => {
                        const order = { G1: 0, G2: 1, G3: 2, OP: 3 };
                        return (order[_gradeOf(a)] ?? 9) - (order[_gradeOf(b)] ?? 9)
                            || String(a.name || '').localeCompare(String(b.name || ''));
                    });
                    const selectedCandidate = candidates.find(candidate => retuned.calendarPicks.has(Number(candidate.id)));
                    const r = selectedCandidate || candidates[0];
                    const grade = _gradeOf(r);
                    const picked = Boolean(selectedCandidate);
                    const styleLabel = picked ? raceStyleLabel(retuned.calendarStyles[String(Number(r.id))]) : '';
                    const matchesSearch = !search || candidates.some(candidate => {
                        const haystack = [
                            candidate.name || '',
                            candidate.type || '',
                            candidate.terrain || '',
                            candidate.distance || '',
                            candidate.venue || ''
                        ].join(' ').toLowerCase();
                        return haystack.includes(search);
                    });
                    const allIds = candidates.map(c => c.id).join(',');
                    if (!picked) {
                        return `<div class="cal-slot available is-pickable ${search ? (matchesSearch ? 'search-match' : 'search-dim') : ''}" data-year="${year}" data-turn="${escapeAttr(turnLabel)}" data-rid="${r.id}" data-rids="${allIds}" data-grade="${grade}">
                            <span class="cal-cell-label">${turnLabel}</span>
                        </div>`;
                    }
                    return `<div class="cal-slot picked is-pickable ${search ? (matchesSearch ? 'search-match' : 'search-dim') : ''}" data-year="${year}" data-turn="${escapeAttr(turnLabel)}" data-rid="${r.id}" data-rids="${allIds}" data-grade="${grade}">
                        ${grade ? `<span class="race-grade-pill">${grade}</span>` : ''}
                        <span class="race-label">${escapeHtml(r.name || 'Race')}</span>
                        ${styleLabel ? `<span class="cal-style-pill">${escapeHtml(styleLabel)}</span>` : ''}
                        <span class="cal-cell-label">${turnLabel}</span>
                    </div>`;
                });
                const rows = [];
                for (let i = 0; i < slots.length; i += RACE_TURN_ROW_SIZE) {
                    rows.push(`<div class="cal-month-row">${slots.slice(i, i + RACE_TURN_ROW_SIZE).join('')}</div>`);
                }
                host.innerHTML = rows.join('');
            });
            renderRaceCalendarStyleList();
        }
        function pickCalendarRaceForSlot(candidates, race) {
            if (!Array.isArray(candidates) || !race) return;
            const raceId = Number(race.id);
            if (Number.isNaN(raceId)) return;
            const slotIds = candidates.map(candidate => Number(candidate.id)).filter(id => !Number.isNaN(id));
            const wasPicked = retuned.calendarPicks.has(raceId);
            slotIds.forEach(id => {
                retuned.calendarPicks.delete(id);
                delete retuned.calendarStyles[String(id)];
            });
            if (!wasPicked) {
                retuned.calendarPicks.add(raceId);
            }
            populateRaceCalendarGrid();
        }
        function openRaceCalendarSlotPicker(year, turnLabel, candidates) {
            if (!els.racePopupOverlay || !els.racePopupTitle || !els.racePopupBody) return;
            if (els.racePopupOverlay.parentElement !== document.body) {
                document.body.appendChild(els.racePopupOverlay);
            }
            const yearLabel = YEAR_KEYS[year] || year;
            els.racePopupTitle.textContent = `${yearLabel} - ${turnLabel}`;
            const selectedRace = candidates.find(race => retuned.calendarPicks.has(Number(race.id)));
            els.racePopupBody.innerHTML = '';

            const list = document.createElement('div');
            list.className = 'race-slot-popup-list';
            candidates.forEach(race => {
                const raceId = Number(race.id);
                const isSelected = selectedRace && Number(selectedRace.id) === raceId;
                const grade = _gradeOf(race).toLowerCase().replace('-', '');
                const item = document.createElement('button');
                item.type = 'button';
                item.className = `race-slot-popup-item ${isSelected ? 'on' : ''}`;
                item.innerHTML = `
                    <div class="race-slot-popup-img">
                        <img src="/races/${encodeURIComponent(race.name)}.png" onerror="this.src='/broom.png'">
                    </div>
                    <div class="race-slot-popup-info">
                        <div class="race-slot-popup-name-row">
                            <span class="race-slot-popup-grade ${grade}">${escapeHtml(_gradeOf(race) || race.type || '')}</span>
                            <span class="race-slot-popup-name">${escapeHtml(race.name || 'Race')}</span>
                        </div>
                        <div class="race-slot-popup-meta">
                            <span class="race-slot-popup-terrain ${String(race.terrain || '').toLowerCase()}">${escapeHtml(race.terrain || '')}</span>
                            <span class="race-slot-popup-distance">${escapeHtml(race.distance || '')}</span>
                            <span>${escapeHtml(race.venue || '')}</span>
                        </div>
                    </div>
                    <div class="race-slot-popup-check">✓</div>
                `;
                item.addEventListener('click', () => {
                    pickCalendarRaceForSlot(candidates, race);
                    els.racePopupOverlay.style.display = 'none';
                });
                list.appendChild(item);
            });

            if (selectedRace) {
                const clear = document.createElement('button');
                clear.type = 'button';
                clear.className = 'btn btn-sm race-slot-clear-date';
                clear.textContent = 'Clear this date';
                clear.addEventListener('click', () => {
                    candidates.forEach(race => {
                        const id = Number(race.id);
                        retuned.calendarPicks.delete(id);
                        delete retuned.calendarStyles[String(id)];
                    });
                    populateRaceCalendarGrid();
                    els.racePopupOverlay.style.display = 'none';
                });
                els.racePopupBody.appendChild(clear);
            }
            els.racePopupBody.appendChild(list);
            els.racePopupOverlay.style.display = 'flex';
        }
        function bindRaceCalendarModal() {
            const overlay = document.getElementById('race-modal-overlay');
            const openBtn = document.getElementById('open-race-calendar-btn');
            const closeBtn = document.getElementById('race-modal-close');
            const cancelBtn = document.getElementById('race-modal-cancel-btn');
            const saveBtn = document.getElementById('race-modal-save-btn');
            if (openBtn && openBtn.dataset.bound !== '1') {
                openBtn.dataset.bound = '1';
                openBtn.addEventListener('click', openRaceCalendar);
            }
            if (closeBtn && closeBtn.dataset.bound !== '1') {
                closeBtn.dataset.bound = '1';
                closeBtn.addEventListener('click', closeRaceCalendar);
            }
            if (cancelBtn && cancelBtn.dataset.bound !== '1') {
                cancelBtn.dataset.bound = '1';
                cancelBtn.addEventListener('click', closeRaceCalendar);
            }
            if (overlay && overlay.dataset.bound !== '1') {
                overlay.dataset.bound = '1';
                overlay.addEventListener('click', evt => {
                    if (evt.target === overlay) closeRaceCalendar();
                });
                ['junior','classic','senior'].forEach(year => {
                    const grid = document.getElementById('cal-grid-' + year);
                    if (!grid) return;
                    grid.addEventListener('click', evt => {
                        const slot = evt.target.closest('.cal-slot.is-pickable');
                        if (!slot) return;
                        const turnLabel = slot.getAttribute('data-turn') || '';
                        const candidateIds = String(slot.getAttribute('data-rids') || '')
                            .split(',')
                            .map(id => Number(id))
                            .filter(id => !Number.isNaN(id));
                        const candidates = candidateIds
                            .map(id => raceById(id))
                            .filter(Boolean)
                            .sort((a, b) => {
                                const order = { G1: 0, G2: 1, G3: 2, OP: 3 };
                                return (order[_gradeOf(a)] ?? 9) - (order[_gradeOf(b)] ?? 9)
                                    || String(a.name || '').localeCompare(String(b.name || ''));
                            });
                        if (candidates.length > 1) {
                            openRaceCalendarSlotPicker(year, turnLabel, candidates);
                            return;
                        }
                        const race = candidates[0] || raceById(Number(slot.getAttribute('data-rid')));
                        if (!race) return;
                        if (retuned.calendarPicks.has(Number(race.id))) {
                            retuned.calendarPicks.delete(Number(race.id));
                            delete retuned.calendarStyles[String(Number(race.id))];
                        } else {
                            retuned.calendarPicks.add(Number(race.id));
                        }
                        populateRaceCalendarGrid();
                    });
                });
            }
            if (els.raceModalSearchInput && els.raceModalSearchInput.dataset.bound !== '1') {
                els.raceModalSearchInput.dataset.bound = '1';
                els.raceModalSearchInput.addEventListener('input', evt => {
                    retuned.calendarSearch = String(evt.target.value || '').trim();
                    populateRaceCalendarGrid();
                });
            }
            if (els.raceStyleList && els.raceStyleList.dataset.bound !== '1') {
                els.raceStyleList.dataset.bound = '1';
                els.raceStyleList.addEventListener('change', evt => {
                    const select = evt.target.closest('.race-style-select');
                    if (!select) return;
                    const rid = Number(select.getAttribute('data-rid'));
                    if (Number.isNaN(rid)) return;
                    const style = normalizeRaceStyleValue(select.value);
                    if (style) retuned.calendarStyles[String(rid)] = style;
                    else delete retuned.calendarStyles[String(rid)];
                    populateRaceCalendarGrid();
                });
                els.raceStyleList.addEventListener('click', evt => {
                    const clearBtn = evt.target.closest('[data-clear-rid]');
                    if (!clearBtn) return;
                    const rid = Number(clearBtn.getAttribute('data-clear-rid'));
                    if (Number.isNaN(rid)) return;
                    delete retuned.calendarStyles[String(rid)];
                    populateRaceCalendarGrid();
                });
            }
            if (els.raceModalLoadBtn && els.raceModalLoadBtn.dataset.bound !== '1') {
                els.raceModalLoadBtn.dataset.bound = '1';
                els.raceModalLoadBtn.addEventListener('click', () => {
                    hydrateRaceCalendarDraftFromSaved();
                    populateRaceCalendarGrid();
                    setRaceCalendarStatus('Reloaded the draft from the preset’s currently saved race selections.');
                });
            }
            if (els.raceModalImportBtn && els.raceModalImportBtn.dataset.bound !== '1') {
                els.raceModalImportBtn.dataset.bound = '1';
                els.raceModalImportBtn.addEventListener('click', () => {
                    if (els.raceModalImportFile) els.raceModalImportFile.click();
                });
            }
            if (els.raceModalImportFile && els.raceModalImportFile.dataset.bound !== '1') {
                els.raceModalImportFile.dataset.bound = '1';
                els.raceModalImportFile.addEventListener('change', importRaceCalendarDraftFile);
            }
            if (els.raceModalResetBtn && els.raceModalResetBtn.dataset.bound !== '1') {
                els.raceModalResetBtn.dataset.bound = '1';
                els.raceModalResetBtn.addEventListener('click', () => {
                    retuned.calendarPicks = new Set();
                    retuned.calendarStyles = {};
                    populateRaceCalendarGrid();
                    setRaceCalendarStatus('Cleared every draft race pick. Save if you want to overwrite the preset.');
                });
            }
            if (saveBtn && saveBtn.dataset.bound !== '1') {
                saveBtn.dataset.bound = '1';
                saveBtn.addEventListener('click', async () => {
                    state.selectedRaces = new Set(Array.from(retuned.calendarPicks));
                    state.selectedRaceStyles = selectedRaceStylePayload(retuned.calendarPicks, retuned.calendarStyles);
                    state.racePlanText = "";
                    if (els.racePlanInput) els.racePlanInput.value = "";
                    if (typeof autoSaveRaces === 'function') await autoSaveRaces();
                    if (typeof renderRaces === 'function') { try { renderRaces(); } catch (e) {} }
                    setRacePlanStatus("Manual race picker saved; custom JSON plan cleared.");
                    setRaceCalendarStatus(`Saved ${state.selectedRaces.size} race pick${state.selectedRaces.size === 1 ? '' : 's'} back into the preset.`);
                    closeRaceCalendar();
                });
            }
            if (!retuned._escBound) {
                retuned._escBound = true;
                document.addEventListener('keydown', evt => {
                    if (evt.key === 'Escape' && retuned.calendarOpen) closeRaceCalendar();
                });
            }
        }

        /* ---------- Structured parent / borrow filtering ---------- */
        function _legacyFactorRows(query, scope) {
            return scope === 'main' ? query.mainFactors : query.inheritanceFactors;
        }
        function _legacyRangeLabel(row) {
            const min = Math.max(0, Number(row.minStars) || 0);
            const max = Math.max(0, Number(row.maxStars) || 0);
            if (min && max) return `${min}-${max}*`;
            if (min) return `${min}+*`;
            if (max) return `<=${max}*`;
            return 'any';
        }
        function _legacyFactorChip(scope, row) {
            const labelKey = row.preferred ? 'preferred' : row.category;
            const cfg = LEGACY_FACTOR_GROUP_CONFIG[labelKey] || LEGACY_FACTOR_GROUP_CONFIG.white;
            const name = String(row.name || '').trim() || 'Any';
            return `${scope === 'main' ? 'Main' : 'Inherit'} ${cfg.label} ${name} ${_legacyRangeLabel(row)}`;
        }
        function _legacyFactorRowHtml(scope, row, index) {
            const labelKey = row.preferred ? 'preferred' : row.category;
            const cfg = LEGACY_FACTOR_GROUP_CONFIG[labelKey] || LEGACY_FACTOR_GROUP_CONFIG.white;
            const maxStars = scope === 'main' ? 3 : 6;
            const tagClass = row.preferred ? 'tag-preferred' : `tag-${row.category}`;
            return `<div class="legacy-factor-row" data-scope="${scope}" data-i="${index}">
                <span class="legacy-factor-tag ${tagClass}">${escapeHtml(cfg.label)}</span>
                <input class="legacy-factor-name" data-prop="name" type="text" list="${cfg.datalist}" placeholder="${escapeAttr(cfg.placeholder)}" value="${escapeAttr(String(row.name || ''))}">
                <label class="legacy-factor-bound">
                    <span>Min</span>
                    <input data-prop="minStars" type="number" min="0" max="${maxStars}" step="1" value="${escapeAttr(String(row.minStars || 0))}">
                </label>
                <label class="legacy-factor-bound">
                    <span>Max</span>
                    <input data-prop="maxStars" type="number" min="0" max="${maxStars}" step="1" value="${escapeAttr(String(row.maxStars || ''))}">
                </label>
                <button class="legacy-factor-remove" data-action="remove-factor" type="button" aria-label="Remove factor filter">&times;</button>
            </div>`;
        }
        function _renderLegacyFactorList(kind, scope) {
            const host = document.getElementById(`${kind}-${scope}-factor-list`);
            if (!host) return;
            const rows = _legacyFactorRows(filterStateFor(kind), scope);
            host.innerHTML = rows.length
                ? rows.map((row, index) => _legacyFactorRowHtml(scope, row, index)).join('')
                : `<span class="filter-empty-state">No ${scope} filters</span>`;
        }
        function _renderLegacyActiveChips(kind) {
            const host = document.getElementById(`${kind}-active-filter-chips`);
            if (!host) return;
            const query = filterStateFor(kind);
            const chips = [];
            ['inheritance', 'main'].forEach(scope => {
                _legacyFactorRows(query, scope).forEach(row => {
                    const hasName = !!String(row.name || '').trim();
                    const hasRange = Number(row.minStars) > 0 || Number(row.maxStars) > 0;
                    if (!hasName && !hasRange) return;
                    chips.push(`<span class="active-filter-chip chip-scope-${scope}">${escapeHtml(_legacyFactorChip(scope, row))}</span>`);
                });
            });
            if (Number(query.mainMinWhites) > 0) chips.push(`<span class="active-filter-chip chip-scope-main">Main Whites ${Number(query.mainMinWhites)}+</span>`);
            if (Number(query.general.minAffinity) > 0) chips.push(`<span class="active-filter-chip">Affinity ${Number(query.general.minAffinity)}+</span>`);
            if (Number(query.general.minWins) > 0) chips.push(`<span class="active-filter-chip">Wins ${Number(query.general.minWins)}+</span>`);
            if (Number(query.general.minWhites) > 0) chips.push(`<span class="active-filter-chip">Whites ${Number(query.general.minWhites)}+</span>`);
            if (Number(query.general.minScore) > 0) chips.push(`<span class="active-filter-chip">Score ${formatNumber(Number(query.general.minScore))}+</span>`);
            if (Number(query.totals.stat) > 0) chips.push(`<span class="active-filter-chip">Blue ${Number(query.totals.stat)}+*</span>`);
            if (Number(query.totals.aptitude) > 0) chips.push(`<span class="active-filter-chip">Pink ${Number(query.totals.aptitude)}+*</span>`);
            if (Number(query.totals.green) > 0) chips.push(`<span class="active-filter-chip">Green ${Number(query.totals.green)}+*</span>`);
            if (Number(query.totals.white) > 0) chips.push(`<span class="active-filter-chip">White ${Number(query.totals.white)}+*</span>`);
            host.innerHTML = chips.length ? chips.join('') : `<span class="filter-empty-state">No active filters</span>`;
        }
        function _syncLegacyFilterControls(kind) {
            const query = filterStateFor(kind);
            const panel = document.getElementById(`${kind}-filter-panel`);
            const toggle = document.getElementById(`${kind}-filter-toggle-btn`);
            const sortMode = document.getElementById(`${kind}-sort-mode`);
            const sortDir = document.getElementById(`${kind}-sort-dir`);
            if (panel) panel.hidden = !query.open;
            if (toggle) toggle.textContent = query.open ? 'Hide Filters' : 'Show Filters';
            if (sortMode) sortMode.value = query.sortMode || 'best-fit';
            if (sortDir) sortDir.value = query.sortDir || 'desc';
            const values = {
                'main-min-whites': query.mainMinWhites,
                'min-affinity': query.general.minAffinity,
                'min-wins': query.general.minWins,
                'min-whites': query.general.minWhites,
                'min-score': query.general.minScore,
                'total-blue': query.totals.stat,
                'total-pink': query.totals.aptitude,
                'total-green': query.totals.green,
                'total-white': query.totals.white
            };
            Object.entries(values).forEach(([suffix, value]) => {
                const input = document.getElementById(`${kind}-${suffix}`);
                if (input) input.value = String(value || 0);
            });
        }
        function renderLegacyFilterUI(kind) {
            collectFactorCatalog();
            _renderLegacyFactorList(kind, 'inheritance');
            _renderLegacyFactorList(kind, 'main');
            _renderLegacyActiveChips(kind);
            _syncLegacyFilterControls(kind);
        }
        function _rerenderLegacyResults(kind) {
            _renderLegacyActiveChips(kind);
            if (kind === 'borrow') {
                if (dashData && dashData.borrowUmas) renderBorrowUmasRetuned(dashData.borrowUmas);
            } else {
                if (dashData && dashData.parents) renderParentsRetuned(dashData.parents);
            }
        }
        function _bindLegacyFilters(kind) {
            const panel = document.getElementById(`${kind}-filter-panel`);
            if (!panel || panel.dataset.bound === '1') return;
            panel.dataset.bound = '1';
            const bar = panel.closest('.filter-bar');
            if (!bar) return;
            renderLegacyFilterUI(kind);
            bar.addEventListener('click', evt => {
                const toggle = evt.target.closest(`#${kind}-filter-toggle-btn`);
                if (toggle) {
                    const query = filterStateFor(kind);
                    query.open = !query.open;
                    _syncLegacyFilterControls(kind);
                    return;
                }
                const clear = evt.target.closest(`#${kind}-filter-clear-btn`);
                if (clear) {
                    const fresh = createLegacyFilterState();
                    fresh.open = filterStateFor(kind).open;
                    if (kind === 'borrow') retuned.borrowQuery = fresh;
                    else retuned.parentQuery = fresh;
                    renderLegacyFilterUI(kind);
                    _rerenderLegacyResults(kind);
                    return;
                }
                const add = evt.target.closest('.filter-action-btn[data-action="add-factor"]');
                if (add && add.closest(`[data-filter-kind="${kind}"]`)) {
                    const scope = add.closest('[data-scope]').getAttribute('data-scope');
                    const category = add.getAttribute('data-category') || 'white';
                    const preferred = add.getAttribute('data-preferred') === '1';
                    _legacyFactorRows(filterStateFor(kind), scope).push(createFactorSpec(category, preferred));
                    _renderLegacyFactorList(kind, scope);
                    _renderLegacyActiveChips(kind);
                    _rerenderLegacyResults(kind);
                    return;
                }
                const remove = evt.target.closest('.legacy-factor-remove[data-action="remove-factor"]');
                if (remove) {
                    const row = remove.closest('.legacy-factor-row');
                    if (!row) return;
                    const scope = row.getAttribute('data-scope');
                    const index = Number(row.getAttribute('data-i'));
                    _legacyFactorRows(filterStateFor(kind), scope).splice(index, 1);
                    _renderLegacyFactorList(kind, scope);
                    _renderLegacyActiveChips(kind);
                    _rerenderLegacyResults(kind);
                }
            });
            bar.addEventListener('change', evt => {
                const target = evt.target;
                const query = filterStateFor(kind);
                if (target.id === `${kind}-sort-mode`) {
                    query.sortMode = target.value || 'best-fit';
                    _rerenderLegacyResults(kind);
                    return;
                }
                if (target.id === `${kind}-sort-dir`) {
                    query.sortDir = target.value || 'desc';
                    _rerenderLegacyResults(kind);
                    return;
                }
                const row = target.closest('.legacy-factor-row');
                if (row) {
                    const scope = row.getAttribute('data-scope');
                    const index = Number(row.getAttribute('data-i'));
                    const prop = target.getAttribute('data-prop');
                    const entry = _legacyFactorRows(query, scope)[index];
                    if (!entry || !prop) return;
                    entry[prop] = prop === 'name' ? target.value : (target.value === '' ? '' : Math.max(0, Number(target.value) || 0));
                    _renderLegacyActiveChips(kind);
                    _rerenderLegacyResults(kind);
                    return;
                }
                const fieldMap = {
                    [`${kind}-main-min-whites`]: ['mainMinWhites'],
                    [`${kind}-min-affinity`]: ['general', 'minAffinity'],
                    [`${kind}-min-wins`]: ['general', 'minWins'],
                    [`${kind}-min-whites`]: ['general', 'minWhites'],
                    [`${kind}-min-score`]: ['general', 'minScore'],
                    [`${kind}-total-blue`]: ['totals', 'stat'],
                    [`${kind}-total-pink`]: ['totals', 'aptitude'],
                    [`${kind}-total-green`]: ['totals', 'green'],
                    [`${kind}-total-white`]: ['totals', 'white']
                };
                const path = fieldMap[target.id];
                if (!path) return;
                const nextVal = Math.max(0, Number(target.value) || 0);
                if (path.length === 1) query[path[0]] = nextVal;
                else query[path[0]][path[1]] = nextVal;
                _renderLegacyActiveChips(kind);
                _rerenderLegacyResults(kind);
            });
            bar.addEventListener('input', evt => {
                const row = evt.target.closest('.legacy-factor-row');
                if (!row) return;
                const scope = row.getAttribute('data-scope');
                const index = Number(row.getAttribute('data-i'));
                const prop = evt.target.getAttribute('data-prop');
                const entry = _legacyFactorRows(filterStateFor(kind), scope)[index];
                if (!entry || !prop) return;
                entry[prop] = prop === 'name' ? evt.target.value : (evt.target.value === '' ? '' : Math.max(0, Number(evt.target.value) || 0));
                _renderLegacyActiveChips(kind);
                _rerenderLegacyResults(kind);
            });
        }
        function bindParentFilters() {
            _bindLegacyFilters('parent');
        }
        function bindBorrowFilters() {
            _bindLegacyFilters('borrow');
        }
        function renderParentsRetuned(parents) {
            const list = Array.isArray(parents) ? parents : [];
            const searchQuery = state.librarySearch.parents || '';
            const filterQuery = filterStateFor('parent');
            collectFactorCatalog();
            let visible = list.map(parent => {
                const evaluation = evaluateLegacyCandidate(parent, filterQuery, { source: 'owned' });
                return { parent, metrics: evaluation.metrics, passes: evaluation.passes };
            }).filter(item => {
                if (searchQuery && !matchesLibrarySearch(item.parent, searchQuery, [
                    p => p.name || '',
                    p => p.card_id || '',
                    p => p.instance_id || '',
                    p => rankLabel(p),
                    p => p.score != null ? String(p.score) : '',
                    p => p.score != null ? formatNumber(p.score) : '',
                    p => p.made_by_bot ? 'bot bot-made bottag' : 'user'
                ])) return false;
                return item.passes;
            });
            visible = sortLegacyCandidates(visible, filterQuery);
            if (dashData) dashData.visibleParents = visible.map(item => item.parent);
            const grid = els.parentGrid;
            if (!grid) return;
            grid.innerHTML = visible.map(item => renderRichParentCard(item.parent, { source: 'owned' })).join('');
            attachFavoriteHandlers();
            const summary = document.getElementById('parent-filter-summary');
            if (summary) {
                const fc = countActiveLegacyFilters(filterQuery);
                summary.innerHTML = `Showing <strong>${visible.length}</strong> of ${list.length} | ${fc} filter${fc === 1 ? '' : 's'} active | Sort ${LEGACY_FILTER_SORT_LABELS[filterQuery.sortMode] || 'Best Match'}`;
            }
            grid.querySelectorAll('.parent-card-rich').forEach(card => {
                card.addEventListener('click', evt => {
                    if (evt.target.closest('.favorite-toggle')) {
                        evt.stopPropagation();
                        return;
                    }
                    if (evt.target.closest('.sparks-btn')) {
                        evt.stopPropagation();
                        const key = evt.target.closest('.sparks-btn').getAttribute('data-sparks-pkey');
                        const entry = visible.find(x => parentKey(x.parent) === key);
                        const parent = entry ? entry.parent : list.find(x => parentKey(x) === key);
                        if (parent) openSparksModal(parent);
                        return;
                    }
                    const key = card.getAttribute('data-pkey');
                    const entry = visible.find(x => parentKey(x.parent) === key);
                    const parent = entry ? entry.parent : list.find(p => parentKey(p) === key);
                    if (!parent) return;
                    if (selection.veterans.some(v => parentKey(v) === key)) {
                        selection.veterans = selection.veterans.filter(v => parentKey(v) !== key);
                    } else if (selection.veterans.length < 2) {
                        selection.veterans.push(parent);
                    } else {
                        return;
                    }
                    renderParentsRetuned(list);
                    renderTeamPanel();
                    syncStartButton();
                    syncSelectionToServer();
                    renderBorrowFallbackPicker();
                    if (dashData && dashData.borrowUmas) renderBorrowUmasRetuned(dashData.borrowUmas);
                });
            });
            updateRailCounts();
            deriveStatusFromState();
        }
        function renderSessionParentsRetuned() {
            const grid = document.getElementById('session-parent-grid');
            const summary = document.getElementById('session-parent-summary');
            if (!grid) return;
            const items = sessionParentItems();
            if (summary) {
                summary.innerHTML = items.length
                    ? `Showing <strong>${items.length}</strong> bot-made parent${items.length === 1 ? '' : 's'} created this session`
                    : 'No bot-made parents created in this browser session yet';
            }
            if (!items.length) {
                grid.innerHTML = '';
                updateRailCounts();
                return;
            }
            grid.innerHTML = items.map(parent => renderRichParentCard(parent, { source: 'owned' })).join('');
            attachFavoriteHandlers();
            grid.querySelectorAll('.parent-card-rich').forEach(card => {
                card.addEventListener('click', evt => {
                    if (evt.target.closest('.favorite-toggle')) {
                        evt.stopPropagation();
                        return;
                    }
                    if (evt.target.closest('.sparks-btn')) {
                        evt.stopPropagation();
                        const key = evt.target.closest('.sparks-btn').getAttribute('data-sparks-pkey');
                        const parent = items.find(x => parentKey(x) === key);
                        if (parent) openSparksModal(parent);
                        return;
                    }
                    const key = card.getAttribute('data-pkey');
                    const parent = items.find(x => parentKey(x) === key);
                    if (!parent) return;
                    if (selection.veterans.some(v => parentKey(v) === key)) {
                        selection.veterans = selection.veterans.filter(v => parentKey(v) !== key);
                    } else if (selection.veterans.length < 2) {
                        selection.veterans.push(parent);
                    } else {
                        return;
                    }
                    renderSessionParentsRetuned();
                    if (dashData && dashData.parents) renderParentsRetuned(dashData.parents);
                    renderTeamPanel();
                    syncStartButton();
                    syncSelectionToServer();
                    renderBorrowFallbackPicker();
                    if (dashData && dashData.borrowUmas) renderBorrowUmasRetuned(dashData.borrowUmas);
                });
            });
            updateRailCounts();
        }
        function renderBorrowUmasRetuned(umas) {
            const list = Array.isArray(umas) ? umas : [];
            const searchQuery = state.librarySearch.borrowUmas || '';
            const normalized = list.map(_normalizeBorrowUma);
            const filterQuery = filterStateFor('borrow');
            collectFactorCatalog();
            let visible = normalized.map(parent => {
                const evaluation = evaluateLegacyCandidate(parent, filterQuery, { source: 'borrow' });
                return { parent, metrics: evaluation.metrics, passes: evaluation.passes };
            }).filter(item => {
                if (searchQuery && !matchesLibrarySearch(item.parent, searchQuery, [
                    p => p.name || '',
                    p => p.trainer_name || '',
                    p => p.card_id || '',
                    p => p.instance_id || '',
                    p => p.score != null ? String(p.score) : '',
                    p => p.score != null ? formatNumber(p.score) : '',
                    p => p.made_by_bot ? 'bot bot-made bottag' : 'guest'
                ])) return false;
                return item.passes;
            });
            visible = sortLegacyCandidates(visible, filterQuery);
            const quota = dashData && dashData.borrowQuota;
            if (els.borrowUmaCount) {
                els.borrowUmaCount.innerText = quota ? `(${quota.remaining}/${quota.max} borrows left today)` : `(${list.length})`;
            }
            if (els.borrowUmaStatus) {
                if (!list.length) {
                    els.borrowUmaStatus.innerText = 'No borrowable parents loaded. Click REFRESH.';
                } else {
                    els.borrowUmaStatus.innerText = `${list.length} borrowable parent${list.length === 1 ? '' : 's'}. Click a card to set as Guest, click again to clear.`;
                }
            }
            if (!els.borrowUmaGrid) return;
            els.borrowUmaGrid.innerHTML = visible.map(item => renderRichParentCard(item.parent, {
                borrow: true,
                source: 'borrow',
                favoriteType: 'borrowUmas',
                guestKey: selection.guestParent ? borrowUmaKey(selection.guestParent) : null,
                selected: selection.guestParent && item.parent._borrowKey === borrowUmaKey(selection.guestParent)
            })).join('');
            attachFavoriteHandlers();
            const summary = document.getElementById('borrow-filter-summary');
            if (summary) {
                const fc = countActiveLegacyFilters(filterQuery);
                summary.innerHTML = `Showing <strong>${visible.length}</strong> of ${list.length} | ${fc} filter${fc === 1 ? '' : 's'} active | Sort ${LEGACY_FILTER_SORT_LABELS[filterQuery.sortMode] || 'Best Match'}`;
            }
            els.borrowUmaGrid.querySelectorAll('.parent-card-rich').forEach(card => {
                card.addEventListener('click', evt => {
                    if (evt.target.closest('.favorite-toggle')) {
                        evt.stopPropagation();
                        return;
                    }
                    if (evt.target.closest('.sparks-btn')) {
                        evt.stopPropagation();
                        const key = evt.target.closest('.sparks-btn').getAttribute('data-sparks-pkey');
                        const entry = visible.find(x => parentKey(x.parent) === key);
                        if (entry) openSparksModal(entry.parent);
                        return;
                    }
                    const key = card.getAttribute('data-pkey');
                    const entry = visible.find(x => parentKey(x.parent) === key);
                    const parent = entry ? entry.parent : null;
                    if (!parent) return;
                    const origUma = list.find(u => borrowUmaKey(u) === parent._borrowKey);
                    if (!origUma) return;
                    if (selection.guestParent && borrowUmaKey(selection.guestParent) === parent._borrowKey) {
                        selection.guestParent = null;
                    } else {
                        selection.guestParent = normalizeBorrowUmaSelection(origUma);
                    }
                    renderBorrowUmasRetuned(list);
                    renderTeamPanel();
                    syncStartButton();
                    syncSelectionToServer();
                    deriveStatusFromState();
                });
            });
            deriveStatusFromState();
        }

        /* ---------- master init (run on each dashboard render) ---------- */
        function initRetunedUI() {
            ensureCharaAptitudeMap().then(() => {
                if (dashData && dashData.parents) renderParentsRetuned(dashData.parents);
                if (dashData && dashData.umas) renderTraineesRetuned(dashData.umas);
                renderSessionParentsRetuned();
            });
            bindSegmentedControls();
            resyncSegmentedControls();
            bindLibraryRail();
            bindParentFilters();
            bindBorrowFilters();
            bindTraineeFilters();
            bindBorrowFallback();
            bindDeckDetail();
            bindRaceCalendarModal();
            bindTeamBarRunButton();
            bindTeamTrialsHandlers();
            bindSparksModal();
            bindEmptyTeamSlots();
            bindGridSelectionDelegation();
            renderBorrowFallbackPicker();
            updateRailCounts();
            deriveStatusFromState();
            // theme toggle is already wired to els.themeToggle at file top — do NOT bind a second handler here
            // sync skill profile selects on segmented selection (rebroadcast change so existing handlers fire)
            ['skill-style-select','skill-distance-select','skill-buy-timing-select','tp-recovery-select','alarm-clock-mode-select'].forEach(id => {
                const el = document.getElementById(id);
                if (el && !el.dataset.retuneSynced) {
                    el.dataset.retuneSynced = '1';
                    el.addEventListener('change', () => {
                        // existing handlers already attached elsewhere; no-op
                    });
                }
            });
        }

        // wrap renderSkillPlanControls so seg buttons re-sync when the legacy code writes select.value
        if (typeof renderSkillPlanControls === 'function') {
            const _origRenderSkillPlanControls = renderSkillPlanControls;
            renderSkillPlanControls = function() {
                _origRenderSkillPlanControls.apply(this, arguments);
                try { resyncSegmentedControls(); } catch (e) {}
            };
        }
        // same for syncTpRecoveryControl
        if (typeof syncTpRecoveryControl === 'function') {
            const _origSyncTp = syncTpRecoveryControl;
            syncTpRecoveryControl = function() {
                _origSyncTp.apply(this, arguments);
                try { resyncSegmentedControls(); } catch (e) {}
            };
        }
        // same for syncLoopControls — keep my loop seg in sync
        if (typeof syncLoopControls === 'function') {
            const _origSyncLoop = syncLoopControls;
            syncLoopControls = function() {
                _origSyncLoop.apply(this, arguments);
                try {
                    const loopGroup = document.getElementById('loop-seg-group');
                    if (loopGroup) {
                        const activeKey = state.loopEnabled ? state.loopMode : 'off';
                        loopGroup.querySelectorAll('.seg-btn').forEach(btn => {
                            btn.classList.toggle('active', btn.getAttribute('data-loop') === activeKey);
                            btn.classList.toggle('accent', btn.getAttribute('data-loop') === activeKey);
                        });
                    }
                } catch (e) {}
            };
        }

        // wrap renderDashboard so it runs the retune init after the original
        const _origRenderDashboard = renderDashboard;
        renderDashboard = async function(data, options) {
            await _origRenderDashboard(data, options);
            try { trackSessionParents(data && data.parents, { fromCache: !!(options && options.fromCache) }); } catch (e) { console.error('trackSessionParents failed', e); }
            try { initRetunedUI(); } catch (e) { console.error('initRetunedUI failed', e); }
            // Snapshot dashboard data so reloads skip the login bounce
            try { _saveDashCache(data); } catch (e) {}
        };
        // also run on initial load (in case renderDashboard already fired before patch)
        if (dashData) {
            try { trackSessionParents(dashData.parents); } catch (e) {}
            try { initRetunedUI(); } catch (e) {}
        }

        /* ============================================================
           DEV WORKFLOW — cached dashboard + live-reload on file changes
           Cache lets reloads land on the dashboard instead of the login
           screen (no re-auth required just to see UI tweaks). Live-reload
           auto-refreshes the page when styles.css, app.js, or the backend process changes.
           Disable by setting localStorage.sweepy_devmode = 'off'.
           ============================================================ */
        const DASH_CACHE_KEY = 'sweepy_dashCache_v1';
        const DASH_CACHE_TTL_MS = 24 * 3600 * 1000;
        function _saveDashCache(data) {
            if (!data || !data.success) return;
            try { localStorage.setItem(DASH_CACHE_KEY, JSON.stringify({ ts: Date.now(), data })); } catch (e) {}
        }
        function _loadDashCache() {
            try {
                const raw = localStorage.getItem(DASH_CACHE_KEY);
                if (!raw) return null;
                const obj = JSON.parse(raw);
                if (!obj || !obj.data || (Date.now() - obj.ts) > DASH_CACHE_TTL_MS) return null;
                return obj.data;
            } catch (e) { return null; }
        }
        // Patch hideNavbar so a failed /api/session doesn't tear down a cached preview
        const _origHideNavbar = hideNavbar;
        hideNavbar = function() {
            if (retuned.cacheRendered) {
                // Show a small banner instead — server unreachable but cache is live
                const warn = document.getElementById('status-warn');
                if (warn && !warn.dataset.cacheNote) {
                    warn.dataset.cacheNote = '1';
                    warn.innerHTML = '<span style="color:var(--warn)">Cached preview — server session is dead, log in for live data</span>';
                }
                return;
            }
            _origHideNavbar();
        };
        // Cache-boot: if we have a recent cache and the live session hasn't filled in yet,
        // render the dashboard from cache so we land on the dashboard immediately.
        if (localStorage.getItem('sweepy_devmode') !== 'off') {
            const cached = _loadDashCache();
            if (cached) {
                setTimeout(() => {
                    if (!dashData) {
                        retuned.cacheRendered = true;
                        try {
                            renderDashboard(cached, { animateIntro: false, waitForIntro: false, fromCache: true });
                            const warn = document.getElementById('status-warn');
                            if (warn) warn.innerHTML = '<span style="color:var(--text-dim)">Cached preview — server reconnecting…</span>';
                        } catch (e) { console.error('cache-boot failed', e); }
                    }
                }, 0);
            }

            /* --- Live-reload poller --- */
            const LR_FILES = ['/styles.css', '/app.js', '/api/dev/version'];
            const LR_INTERVAL_MS = 2000;
            const lrState = {};
            async function _lrCheck(path) {
                try {
                    const res = await fetch(path + '?lr=' + Date.now(), { method: 'HEAD', cache: 'no-store' });
                    return res.headers.get('last-modified') || res.headers.get('etag') || res.headers.get('content-length') || '';
                } catch (e) { return ''; }
            }
            (async function liveReloadLoop() {
                // Seed initial fingerprints
                for (const f of LR_FILES) lrState[f] = await _lrCheck(f);
                while (true) {
                    await new Promise(r => setTimeout(r, LR_INTERVAL_MS));
                    for (const f of LR_FILES) {
                        const cur = await _lrCheck(f);
                        if (cur && lrState[f] && cur !== lrState[f]) {
                            console.log('[live-reload]', f, 'changed →', cur, '(was', lrState[f] + ')');
                            location.reload();
                            return;
                        }
                        if (cur) lrState[f] = cur;
                    }
                }
            })();
        }
})();
