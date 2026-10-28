// Global upload file reference (prevents TDZ / initialization order issues)
    window.selectedImageFile = null;
    var cachedAdminUsers = [];
    window.cachedAdminUsers = cachedAdminUsers;

    // Live schedule time formatter (e.g. "1 час и 15 минут", "25 мин")
    function formatMinutesHuman(minutes) {
      if (minutes < 60) {
        return `${minutes} мин`;
      }
      const h = Math.floor(minutes / 60);
      const m = minutes % 60;

      let hUnit = "часов";
      const hMod100 = h % 100;
      const hMod10 = h % 10;
      if (hMod100 >= 11 && hMod100 <= 14) {
        hUnit = "часов";
      } else if (hMod10 === 1) {
        hUnit = "час";
      } else if (hMod10 >= 2 && hMod10 <= 4) {
        hUnit = "часа";
      }

      if (m === 0) {
        return `${h} ${hUnit}`;
      }

      let mUnit = "минут";
      const mMod100 = m % 100;
      const mMod10 = m % 10;
      if (mMod100 >= 11 && mMod100 <= 14) {
        mUnit = "минут";
      } else if (mMod10 === 1) {
        mUnit = "минута";
      } else if (mMod10 >= 2 && mMod10 <= 4) {
        mUnit = "минуты";
      }

      return `${h} ${hUnit} и ${m} ${mUnit}`;
    }
    window.formatMinutesHuman = formatMinutesHuman;

    // --------------------------------------------------------
    // Telegram WebApp Initialization & Theme Binding
    // --------------------------------------------------------
    const tg = window.Telegram?.WebApp;
    if (tg) {
      tg.ready();
      tg.expand();
      window.GymTheme?.apply();
    }

    // Haptic feedback helper
    function haptic(type = 'light') {
      try {
        if (tg?.HapticFeedback) {
          if (type === 'selection') tg.HapticFeedback.selectionChanged();
          else if (type === 'success') tg.HapticFeedback.notificationOccurred('success');
          else if (type === 'warning') tg.HapticFeedback.notificationOccurred('warning');
          else tg.HapticFeedback.impactOccurred(type);
        }
      } catch (e) {}
    }

    // --------------------------------------------------------
    // LocalStorage Cache Helper
    // --------------------------------------------------------
    const STORAGE_KEY = 'gym16_student_profile';
    function loadSavedProfile() {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        const profile = raw ? JSON.parse(raw) : null;
        const telegramId = tg?.initDataUnsafe?.user?.id;
        return profile && (!telegramId || Number(profile.id) === Number(telegramId)) ? profile : null;
      } catch (e) {
        return null;
      }
    }

    function saveProfileLocally(profileData) {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(profileData));
      } catch (e) {}
    }

    // --------------------------------------------------------
    // Global State
    // --------------------------------------------------------
    const savedLocal = loadSavedProfile();

    
    // This client-side identity check only controls whether the admin tab is
    // visible. Admin API routes independently validate Telegram initData on
    // the server before allowing any action.
    function checkIsAdmin() {
      if (!state.user) return false;
      return Boolean(state.user.is_admin);
    }

    function checkCanEdit() { return checkIsAdmin() || state.user?.role === "editor"; }

    function updateAdminNavigation() {
      const navTabAdmin = document.getElementById('nav-tab-admin');
      if (navTabAdmin) navTabAdmin.classList.toggle('hidden', !checkCanEdit());
      window.communityRoleUI?.();
    }

    const state = {
      // User info (pre-populated from localStorage or Telegram WebApp)
      user: {
        id: tg?.initDataUnsafe?.user?.id || savedLocal?.id || 0,
        first_name: savedLocal?.first_name || tg?.initDataUnsafe?.user?.first_name || 'Гимназист',
        last_name: savedLocal?.last_name || tg?.initDataUnsafe?.user?.last_name || '',
        username: tg?.initDataUnsafe?.user?.username || savedLocal?.username || null,
        photo_url: tg?.initDataUnsafe?.user?.photo_url || null,
        class_name: savedLocal?.class_name || null,
        profile_name: savedLocal?.profile_name || null,
        is_admin: Boolean(savedLocal?.is_admin),
        is_onboarded: Boolean(savedLocal?.class_name && savedLocal?.profile_name)
      },
      ege: {
        activeSubject: 'russian',
        selectedTask: null,
        subjects: [],
        materials: []
      },
      selectedProfileFilter: 'all',
      // App structure
      structure: {
        classes: ['11А', '11Б', '11В', '11Г', '11Д', '11Ж'],
        class_profiles: {
          '11А': ['Соц-гум', 'Филологический'],
          '11Б': ['Физмат'],
          '11В': ['Инфотех', 'Инженерный'],
          '11Г': ['Химбио'],
          '11Д': ['Инфотех'],
          '11Ж': ['Инфотех']
        },
        all_profiles: ['Соц-гум', 'Филологический', 'Физмат', 'Инфотех', 'Инженерный', 'Химбио']
      },
      // Viewing state for schedule (can differ from user's own class!)
      viewingClass: savedLocal?.class_name || '11А',
      selectedDay: new Date().getDay() === 0 ? 0 : Math.min(new Date().getDay() - 1, 5), // 0=Mon..5=Sat
      onlyMyProfile: true,
      bells: [],
      // News state
      news: [],
      activePostForComments: null
    };

    // Show the tab immediately for the configured Telegram account, even if
    // an existing local profile cache delays or prevents the profile sync.
    updateAdminNavigation();

    // --------------------------------------------------------
    // Security: HTML Sanitization Helper (XSS Protection)
    // --------------------------------------------------------
    function escapeHtml(str) {
      if (str === null || str === undefined) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }
    window.escapeHtml = escapeHtml;

    function safeImageUrl(value) {
      if (!value || typeof value !== 'string') return '';
      const url = value.trim();
      if (/^\/uploads\/[A-Za-z0-9_.-]+$/.test(url)) return url;
      if (/^\/api\/media\/[A-Za-z0-9_-]{10,250}$/.test(url)) return url;
      try {
        const parsed = new URL(url, window.location.origin);
        if (parsed.protocol === 'https:' && !parsed.username && !parsed.password && (parsed.origin === window.location.origin || parsed.hostname === 't.me' || parsed.hostname.endsWith('.telegram.org'))) return parsed.href;
      } catch (_) {}
      return '';
    }

    function safeHttpsUrl(value) {
      try {
        const parsed = new URL(String(value || ''), window.location.origin);
        if (parsed.protocol === 'https:' && !parsed.username && !parsed.password) return parsed.href;
      } catch (_) {}
      return '';
    }

    document.addEventListener('click', (event) => {
      const image = event.target.closest('.safe-image-open');
      if (!image) return;
      const url = safeImageUrl(image.dataset.imageUrl || '');
      if (url) window.open(url, '_blank', 'noopener,noreferrer');
    });

    // --------------------------------------------------------
    // Authenticated API Helper (Cryptographic Telegram InitData)
    // --------------------------------------------------------
    const API = {
      _getHeaders(extra = {}) {
        const initData = window.Telegram?.WebApp?.initData || '';
        const headers = { ...extra };
        if (initData) {
          headers['X-Telegram-Init-Data'] = initData;
        }
        return headers;
      },
      async get(url) {
        try {
          const res = await fetch(url, { headers: this._getHeaders() });
          if (!res.ok) {
            let errorMsg = `HTTP ${res.status}`;
            try {
              const errBody = await res.json();
              if (errBody && errBody.detail) {
                errorMsg = typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail);
              }
            } catch (_) {}
            throw new Error(errorMsg);
          }
          return await res.json();
        } catch (e) {
          console.error(`API GET ${url} error:`, e);
          throw e;
        }
      },
      async post(url, data) {
        try {
          const res = await fetch(url, {
            method: 'POST',
            headers: this._getHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(data)
          });
          if (!res.ok) {
            let errorMsg = `HTTP ${res.status}`;
            try {
              const errBody = await res.json();
              if (errBody && errBody.detail) {
                errorMsg = typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail);
              }
            } catch (_) {}
            throw new Error(errorMsg);
          }
          return await res.json();
        } catch (e) {
          console.error(`API POST ${url} error:`, e);
          throw e;
        }
      },
      async put(url, data) {
        try {
          const res = await fetch(url, {
            method: 'PUT',
            headers: this._getHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(data)
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return await res.json();
        } catch (e) {
          console.error(`API PUT ${url} error:`, e);
          return null;
        }
      },
      async delete(url) {
        try {
          const res = await fetch(url, {
            method: 'DELETE',
            headers: this._getHeaders()
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return await res.json();
        } catch (e) {
          console.error(`API DELETE ${url} error:`, e);
          return null;
        }
      },
      async upload(file) {
        try {
          const formData = new FormData();
          formData.append('file', file);
          const res = await fetch('/api/upload', {
            method: 'POST',
            headers: this._getHeaders(),
            body: formData
          });
          if (!res.ok) throw new Error(`Upload error ${res.status}`);
          return await res.json();
        } catch (e) {
          console.error('File upload error:', e);
          return null;
        }
      }
    };

    // --------------------------------------------------------
    // Tab Navigation
    // --------------------------------------------------------
    const tabButtons = document.querySelectorAll('.nav-tab-btn');
    const tabPages = document.querySelectorAll('.tab-page');
    const appTitle = document.getElementById('app-title');
    const headerActionBtn = document.getElementById('header-action-btn');

    // Tab button events are handled via inline data-gym-click="haabf077e995a"

    function switchTab(tabId) {
      try {
        const pages = document.querySelectorAll('.tab-page');
        pages.forEach(p => p.classList.add('hidden'));
        const targetPage = document.getElementById(tabId);
        if (targetPage) targetPage.classList.remove('hidden');
        window.scrollTo({top: 0, behavior: 'instant'});

        const buttons = document.querySelectorAll('.nav-tab-btn');
        buttons.forEach(b => {
          if (b.getAttribute('data-tab') === tabId) {
            b.classList.remove('text-ios-secondaryText');
            b.classList.add('text-ios-blue');
          } else {
            b.classList.remove('text-ios-blue');
            b.classList.add('text-ios-secondaryText');
          }
        });

        const appTitleEl = document.getElementById('app-title');
        const headerBtn = document.getElementById('header-action-btn');

        if (tabId === 'tab-schedule') {
          if (appTitleEl) appTitleEl.textContent = 'Расписание';
          if (headerBtn) headerBtn.classList.add('hidden');
          loadSchedule().catch(() => {});
        } else if (tabId === 'tab-news') {
          if (appTitleEl) appTitleEl.textContent = 'Новости';
          if (headerBtn) headerBtn.classList.add('hidden');
          loadNews().catch(() => {});
          checkPendingNewsCount().catch(() => {});
        } else if (tabId === 'tab-ege') {
          if (appTitleEl) appTitleEl.textContent = 'ЕГЭ';
          if (headerBtn) headerBtn.classList.add('hidden');
          const isAdmin = checkCanEdit();
          if (isAdmin) {
            const egeBtn = document.getElementById('ege-add-mat-btn');
            if (egeBtn) { egeBtn.classList.remove('hidden'); egeBtn.classList.add('flex'); }
          } else {
            if (headerBtn) headerBtn.classList.add('hidden');
          }
          loadEgeMaterials().catch(() => {});
        } else if (tabId === 'tab-profile') {
          if (appTitleEl) appTitleEl.textContent = 'Профиль';
          if (headerBtn) headerBtn.classList.add('hidden');
          updateProfileUI();
        } else if (tabId === 'tab-admin') {
          if (appTitleEl) appTitleEl.textContent = 'Админ панель';
          if (headerBtn) headerBtn.classList.add('hidden');
          loadAdminPendingNews().catch(() => {});
          if (checkIsAdmin()) loadAdminUsers().catch(() => {});
        }
      } catch (err) {
        console.error('switchTab error:', err);
      }
    }
    window.switchTab = switchTab;

    // --------------------------------------------------------
    // User Sync & Onboarding
    // --------------------------------------------------------
    async function initUser() {
      // 1. Immediate local UI & Schedule rendering (0ms delay, zero waiting!)
      updateProfileUI();
      updateLiveScheduleStatus().catch(() => {});
      loadSchedule().catch(console.error);

      // 2. Parallel background sync & metadata fetching (never blocks schedule display!)
      try {
        Promise.allSettled([
          API.get('/api/meta/structure').then(struct => { if (struct) state.structure = struct; }),
          loadBells(),
          checkPendingNewsCount(),
          API.post('/api/user/sync', {
            id: state.user.id,
            first_name: state.user.first_name,
            last_name: state.user.last_name,
            username: state.user.username,
            photo_url: state.user.photo_url,
            class_name: state.user.class_name || savedLocal?.class_name || null,
            profile_name: state.user.profile_name || savedLocal?.profile_name || null
          }).then(syncedUser => {
            if (syncedUser) {
              state.user = {
                ...state.user,
                ...syncedUser,
                first_name: syncedUser.first_name || state.user.first_name,
                last_name: syncedUser.last_name !== null ? syncedUser.last_name : state.user.last_name
              };
              saveProfileLocally(state.user);
              updateProfileUI();

              // Ban check lockout
              if (syncedUser.is_banned) {
                const overlay = document.getElementById("banned-overlay");
                if (overlay) {
                  overlay.classList.remove("hidden");
                  overlay.classList.add("flex");
                }
                const nav = document.querySelector("nav");
                if (nav) nav.classList.add("hidden");
                return;
              }

              if (window.communityAccessGate?.(syncedUser)) return;
              updateAdminNavigation();
              window.loadPersonalTools?.();
              loadNews().catch(() => {});

              if (checkIsAdmin()) {
                if (state.news && state.news.length > 0) {
                  const container = document.getElementById("news-posts-list");
                  if (container) {
                    container.innerHTML = state.news.map(p => renderNewsPost(p)).join("");
                  }
                }
              }
              if (!syncedUser.is_onboarded) {
                openOnboardingModal();
              } else if (syncedUser.class_name && syncedUser.class_name !== state.viewingClass) {
                state.viewingClass = syncedUser.class_name;
                loadSchedule().catch(() => {});
              }
            }
          })
        ]).finally(() => {
          updateLiveScheduleStatus().catch(() => {});
        });
      } catch (err) {
        console.error("initUser background sync error:", err);
      }

      // Start live interval
      setInterval(updateLiveScheduleStatus, 15000);
    }

    function updateProfileUI() {
      const fullName = `${state.user.first_name || ''} ${state.user.last_name || ''}`.trim() || 'Гимназист';
      document.getElementById('profile-name').textContent = fullName;
      document.getElementById('profile-fullname-display').textContent = fullName;

      const tgUser = state.user.username ? `@${state.user.username}` : `ID: ${state.user.id}`;
      document.getElementById('profile-username').textContent = tgUser;
      document.getElementById('profile-tg-display').textContent = tgUser;
      document.getElementById('onboard-tg-username').textContent = tgUser;

      document.getElementById('profile-class-display').textContent = state.user.class_name || 'Не выбран';
      document.getElementById('profile-profile-display').textContent = state.user.profile_name || 'Не выбран';
      document.getElementById('app-subtitle').textContent = `${state.user.class_name || '11 класс'} • ${state.user.profile_name || 'Параллель'}`;

      // Update Schedule view label
      document.getElementById('viewing-class-badge').textContent = state.viewingClass || state.user.class_name || '11А';

      if (state.user.photo_url) {
        const avatarEl = document.getElementById('profile-avatar');
        avatarEl.innerHTML = `<img src="${escapeHtml(safeImageUrl(state.user.photo_url))}" alt="Фото профиля" class="w-full h-full object-cover">`;
      } else {
        const initials = (state.user.first_name ? state.user.first_name.charAt(0) : 'Г') + (state.user.last_name ? state.user.last_name.charAt(0) : '');
        document.getElementById('profile-avatar').textContent = initials || 'Г16';
      }
    }

    // --------------------------------------------------------
    // Onboarding Modal Handling
    // --------------------------------------------------------
    const onboardingModal = document.getElementById('onboarding-modal');
    let tempSelectedClass = '11А';
    let tempSelectedProfile = 'Соц-гум';

    function openOnboardingModal() {
      tempSelectedClass = state.user.class_name || '11А';
      const availableProfiles = state.structure.class_profiles?.[tempSelectedClass] || ['Общий'];
      tempSelectedProfile = state.user.profile_name && availableProfiles.includes(state.user.profile_name) 
        ? state.user.profile_name 
        : availableProfiles[0];

      // Prefill Name and Surname
      document.getElementById('onboard-first-name').value = state.user.first_name || '';
      document.getElementById('onboard-last-name').value = state.user.last_name || '';

      const closeBtn = document.getElementById('close-onboarding-modal-btn');
      if (closeBtn) {
        if (!state.user.is_onboarded) {
          closeBtn.classList.add('hidden');
        } else {
          closeBtn.classList.remove('hidden');
        }
      }

      renderOnboardingControls();
      onboardingModal.classList.remove('hidden');
      onboardingModal.classList.add('flex');
    }

    function closeOnboardingModal() {
      if (!state.user.is_onboarded) {
        alert("Для входа в приложение необходимо зарегистрироваться: укажите имя, фамилию, класс и профиль.");
        return;
      }
      onboardingModal.classList.add('hidden');
      onboardingModal.classList.remove('flex');
    }

    function renderOnboardingControls() {
      // 1. Classes Grid (11А, 11Б, 11В, 11Г, 11Д, 11Ж)
      const classesContainer = document.getElementById('onboarding-classes-grid');
      classesContainer.innerHTML = state.structure.classes.map(cls => `
        <button type="button" data-val="${cls}" class="onboard-class-btn py-2.5 rounded-xl font-bold text-sm text-center border active-press transition-all ${
          cls === tempSelectedClass 
            ? 'border-ios-blue bg-blue-50 text-ios-blue dark:bg-blue-950/60 dark:text-blue-400' 
            : 'border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300'
        }">${cls}</button>
      `).join('');

      classesContainer.querySelectorAll('.onboard-class-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          tempSelectedClass = btn.getAttribute('data-val');
          const availableProfiles = state.structure.class_profiles?.[tempSelectedClass] || ['Общий'];
          if (!availableProfiles.includes(tempSelectedProfile)) {
            tempSelectedProfile = availableProfiles[0];
          }
          renderOnboardingControls();
          haptic('selection');
        });
      });

      // 2. Profiles for selected class
      const profilesContainer = document.getElementById('onboarding-profiles-list');
      const availableProfiles = state.structure.class_profiles?.[tempSelectedClass] || ['Общий'];

      if (availableProfiles.length > 1) {
        // Multiple profiles available (11А, 11В) -> show selector
        profilesContainer.innerHTML = `
          <div class="text-[11px] text-ios-secondaryText mb-1.5 font-medium">Выберите направление для ${tempSelectedClass}:</div>
          <div class="space-y-2">
            ${availableProfiles.map(prof => `
              <button type="button" data-val="${prof}" class="onboard-prof-btn w-full px-3.5 py-2.5 rounded-xl text-left border text-xs font-semibold active-press transition-all flex items-center justify-between ${
                prof === tempSelectedProfile 
                  ? 'border-ios-blue bg-blue-50 text-ios-blue dark:bg-blue-950/60 dark:text-blue-400' 
                  : 'border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300'
              }">
                <span class="truncate">${prof}</span>
                ${prof === tempSelectedProfile ? '<span class="text-ios-blue font-bold">✓</span>' : ''}
              </button>
            `).join('')}
          </div>
        `;

        profilesContainer.querySelectorAll('.onboard-prof-btn').forEach(btn => {
          btn.addEventListener('click', () => {
            tempSelectedProfile = btn.getAttribute('data-val');
            renderOnboardingControls();
            haptic('selection');
          });
        });
      } else {
        // Single profile class (11Б, 11Г, 11Д, 11Ж) -> auto-assigned banner
        tempSelectedProfile = availableProfiles[0];
        profilesContainer.innerHTML = `
          <div class="p-3.5 rounded-2xl bg-zinc-50 dark:bg-ios-cardDark2 border border-zinc-200/60 dark:border-zinc-800/80 flex items-center justify-between">
            <div>
              <div class="text-[11px] text-ios-secondaryText font-medium">Профиль класса</div>
              <div class="text-sm font-bold text-zinc-900 dark:text-white mt-0.5">${availableProfiles[0]}</div>
            </div>
            <span class="px-2.5 py-1 rounded-full text-[10px] font-bold bg-blue-50 text-ios-blue dark:bg-blue-950 dark:text-blue-300">
              Единый профиль
            </span>
          </div>
        `;
      }
    }

    document.getElementById('save-onboarding-btn')?.addEventListener('click', async () => {
      const inputFirstName = document.getElementById('onboard-first-name').value.trim();
      const inputLastName = document.getElementById('onboard-last-name').value.trim();

      if (!inputFirstName || !inputLastName) {
        alert('Пожалуйста, укажите и имя, и фамилию (нельзя оставить только одно поле)');
        return;
      }

      const updated = await API.put(`/api/user/${state.user.id}/profile`, {
        class_name: tempSelectedClass,
        profile_name: tempSelectedProfile,
        first_name: inputFirstName,
        last_name: inputLastName,
        subgroup: document.getElementById("school-profile-group")?.value ? Number(document.getElementById("school-profile-group").value) : null
      });

      if (updated) {
        state.user = { ...state.user, ...updated };
        state.viewingClass = updated.class_name;
        saveProfileLocally(state.user);
        updateProfileUI();
        closeOnboardingModal();
        haptic('success');
        await loadSchedule();
      }
    });

    document.getElementById('edit-profile-btn')?.addEventListener('click', openOnboardingModal);

    // --------------------------------------------------------
    // View Another Class (Modal & Switching)
    // --------------------------------------------------------
    const viewClassModal = document.getElementById('view-class-modal');
    const openClassPickerBtn = document.getElementById('open-class-picker-btn');
    const closeViewClassModalBtn = document.getElementById('close-view-class-modal-btn');
    const resetToMyClassBtn = document.getElementById('reset-to-my-class-btn');
    const otherClassNotice = document.getElementById('other-class-notice');
    const otherClassName = document.getElementById('other-class-name');
    const otherClassCloseBtn = document.getElementById('other-class-close-btn');

    function openViewClassModal() {
      const container = document.getElementById('view-class-grid');
      container.innerHTML = state.structure.classes.map(cls => {
        const isMyClass = cls === state.user.class_name;
        const isViewing = cls === state.viewingClass;
        return `
          <button type="button" data-class="${cls}" class="pick-view-class-btn p-3 rounded-2xl border text-center active-press transition-all ${
            isViewing 
              ? 'border-ios-blue bg-blue-50 text-ios-blue dark:bg-blue-950/70 dark:text-blue-300 font-bold ring-2 ring-ios-blue/30' 
              : 'border-zinc-200 dark:border-zinc-800 text-zinc-800 dark:text-zinc-200 font-semibold'
          }">
            <div class="text-base">${cls}</div>
            <div class="text-[10px] mt-0.5 text-ios-secondaryText">${isMyClass ? 'Мой класс' : 'Класс'}</div>
          </button>
        `;
      }).join('');

      container.querySelectorAll('.pick-view-class-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const selected = btn.getAttribute('data-class');

          // 1. Immediately switch visual active button state inside the modal
          container.querySelectorAll('.pick-view-class-btn').forEach(b => {
            const cls = b.getAttribute('data-class');
            if (cls === selected) {
              b.className = 'pick-view-class-btn p-3 rounded-2xl border text-center active-press transition-all border-ios-blue bg-blue-50 text-ios-blue dark:bg-blue-950/70 dark:text-blue-300 font-bold ring-2 ring-ios-blue/30';
            } else {
              b.className = 'pick-view-class-btn p-3 rounded-2xl border text-center active-press transition-all border-zinc-200 dark:border-zinc-800 text-zinc-800 dark:text-zinc-200 font-semibold';
            }
          });

          // 2. Immediately update state, badge and sync profile filter pills
          state.viewingClass = selected;
          state.selectedProfileFilter = 'all';

          const badgeEl = document.getElementById('viewing-class-badge');
          if (badgeEl) badgeEl.textContent = selected;

          // Synchronously hide/show profile filters
          renderScheduleProfileFilters();
          updateClassViewUI();
          loadSchedule();

          haptic('selection');

          // 3. Smooth auto-close modal after 180ms
          setTimeout(() => {
            closeViewClassModal();
          }, 180);
        });
      });

      viewClassModal.classList.remove('hidden');
      viewClassModal.classList.add('flex');
    }

    function closeViewClassModal() {
      viewClassModal.classList.add('hidden');
      viewClassModal.classList.remove('flex');
    }

    function switchToClassView(targetClass) {
      state.viewingClass = targetClass;
      state.selectedProfileFilter = 'all';
      renderScheduleProfileFilters();
      updateClassViewUI();
      loadSchedule();
    }

    function updateClassViewUI() {
      const isViewingOther = state.viewingClass !== state.user.class_name;
      const badge = document.getElementById('viewing-class-badge');
      if (badge) badge.textContent = state.viewingClass;

      if (isViewingOther) {
        resetToMyClassBtn.classList.remove('hidden');
        otherClassNotice.classList.remove('hidden');
        otherClassName.textContent = state.viewingClass;
      } else {
        resetToMyClassBtn.classList.add('hidden');
        otherClassNotice.classList.add('hidden');
      }

      // Hide or show "Мой профиль" vs "Весь класс" toggle
      const modeSwitchContainer = document.getElementById('mode-switch-container');
      if (isViewingOther) {
        state.onlyMyProfile = false;
        if (typeof modeAllClassBtn !== 'undefined' && modeAllClassBtn) {
          modeAllClassBtn.className = 'px-2.5 py-1 rounded-lg transition-all bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs';
        }
        if (typeof modeMyProfileBtn !== 'undefined' && modeMyProfileBtn) {
          modeMyProfileBtn.className = 'px-2.5 py-1 rounded-lg transition-all text-ios-secondaryText hover:text-zinc-900 dark:hover:text-white';
        }
      }

      // Synchronously keep profile filter pills strictly in sync
      renderScheduleProfileFilters();
    }

    openClassPickerBtn?.addEventListener('click', openViewClassModal);
    closeViewClassModalBtn?.addEventListener('click', closeViewClassModal);
    resetToMyClassBtn?.addEventListener('click', () => {
      switchToClassView(state.user.class_name || '11А');
      haptic('selection');
    });
    otherClassCloseBtn?.addEventListener('click', () => {
      switchToClassView(state.user.class_name || '11А');
      haptic('selection');
    });

    // --------------------------------------------------------
    // Schedule Mode Toggle & Day Segmented Selector
    // --------------------------------------------------------
    const modeMyProfileBtn = document.getElementById('mode-my-profile-btn');
    const modeAllClassBtn = document.getElementById('mode-all-class-btn');

    modeMyProfileBtn?.addEventListener('click', () => {
      state.onlyMyProfile = true;
      if (modeMyProfileBtn) modeMyProfileBtn.className = 'px-2.5 py-1 rounded-lg transition-all bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs';
      if (modeAllClassBtn) modeAllClassBtn.className = 'px-2.5 py-1 rounded-lg transition-all text-ios-secondaryText hover:text-zinc-900 dark:hover:text-white';
      haptic('selection');
      loadSchedule();
    });

    modeAllClassBtn?.addEventListener('click', () => {
      state.onlyMyProfile = false;
      modeAllClassBtn.className = 'px-2.5 py-1 rounded-lg transition-all bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs';
      modeMyProfileBtn.className = 'px-2.5 py-1 rounded-lg transition-all text-ios-secondaryText hover:text-zinc-900 dark:hover:text-white';
      haptic('selection');
      loadSchedule();
    });

    // Day buttons (0=Пн..5=Сб)
    
    // --------------------------------------------------------
    // Select Day Function (0=Пн..5=Сб)
    // --------------------------------------------------------
    function selectDay(d) {
      try {
        state.selectedDay = d;
        const dayButtons = document.querySelectorAll('.day-btn');
        dayButtons.forEach(b => {
          if (parseInt(b.getAttribute('data-day')) === d) {
            b.className = 'day-btn flex-1 py-1.5 text-xs font-semibold rounded-xl text-center transition-all bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm active-press';
          } else {
            b.className = 'day-btn flex-1 py-1.5 text-xs font-semibold rounded-xl text-center transition-all text-ios-secondaryText active-press';
          }
        });
        loadSchedule();
        haptic('selection');
      } catch (err) {
        console.error('selectDay error:', err);
      }
    }
    window.selectDay = selectDay;

    const dayButtons = document.querySelectorAll('.day-btn');
    // Set initial active day button
    dayButtons.forEach(b => {
      if (parseInt(b.getAttribute('data-day')) === state.selectedDay) {
        b.className = 'day-btn flex-1 py-1.5 text-xs font-semibold rounded-xl text-center transition-all bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm active-press';
      } else {
        b.className = 'day-btn flex-1 py-1.5 text-xs font-semibold rounded-xl text-center transition-all text-ios-secondaryText active-press';
      }
    });

    // --------------------------------------------------------
    // Live Countdown & Bell Schedule (100% Reliable UTC+5 Calculation)
    // --------------------------------------------------------
    function getTyumenDate() {
      // Tyumen is strictly UTC+5 (MSK+2) with no daylight saving time
      const now = new Date();
      const utcMs = now.getTime() + (now.getTimezoneOffset() * 60000);
      return new Date(utcMs + 5 * 3600000);
    }

    function getTyumenTime() {
      const d = getTyumenDate();
      const h = String(d.getHours()).padStart(2, "0");
      const m = String(d.getMinutes()).padStart(2, "0");
      return `${h}:${m}`;
    }

    function liveScheduleParams() {
      const targetClass = state.viewingClass || state.user?.class_name || '11А';
      const selected = state.selectedProfileFilter;
      const profile = selected && selected !== 'all' ? selected : (targetClass === state.user?.class_name ? state.user?.profile_name : '');
      const params = new URLSearchParams({class_name: targetClass});
      if (profile) params.set('profile_name', profile);
      if (targetClass === state.user?.class_name && state.user?.subgroup) params.set('subgroup', state.user.subgroup);
      return params;
    }

    function calculateLiveStatusLocally() {
      const timeEl = document.getElementById('live-status-time');
      const message = document.getElementById('live-status-message');
      const title = document.getElementById('live-status-title');
      const data = state.liveStatusScope === liveScheduleParams().toString() && Date.now() - (state.liveStatusReceivedAt || 0) < 60000 ? state.liveStatus : null;
      if (timeEl) timeEl.textContent = data?.current_time || getTyumenTime();
      if (message) message.textContent = data?.message || 'Уточняем время занятий…';
      if (title) {
        title.textContent = data?.state === 'lesson' ? 'Идёт занятие' : data?.state === 'break' ? 'Перемена' : 'Статус занятий';
        title.className = 'text-xs font-semibold text-ios-blue uppercase tracking-wider';
      }
    }

    async function loadBells() {
      const data = await API.get("/api/schedule/bells");
      if (data) state.bells = data;
    }

    async function updateLiveScheduleStatus() {
      const params = liveScheduleParams();
      try {
        const data = await API.get(`/api/schedule/live?${params}`);
        if (data && params.toString() === liveScheduleParams().toString()) {
          state.liveStatus = data;
          state.liveStatusScope = params.toString();
          state.liveStatusReceivedAt = Date.now();
        }
      } finally {
        calculateLiveStatusLocally();
      }
    }

    // --------------------------------------------------------
    // Schedule Rendering
    // --------------------------------------------------------
    async function loadSchedule() {
      const container = document.getElementById('schedule-cards-list');
      container.innerHTML = `
        <div class="py-12 text-center text-xs text-ios-secondaryText space-y-2">
          <div class="inline-block animate-spin rounded-full h-5 w-5 border-2 border-ios-blue border-t-transparent"></div>
          <p>Загрузка расписания...</p>
        </div>
      `;

      const targetClass = state.viewingClass || state.user.class_name || '11А';
      const isMyClass = targetClass === state.user.class_name;
      
      renderScheduleProfileFilters();

      const filterVal = state.selectedProfileFilter || 'all';
      const filterByProfile = (targetClass === '11А' || targetClass === '11В') && filterVal !== 'all';

      const params = new URLSearchParams({
        class_name: targetClass,
        day_of_week: state.selectedDay,
        only_my_profile: filterByProfile,
        profile_name: filterByProfile ? filterVal : ''
      });
      if (isMyClass && state.user.subgroup) params.append('subgroup', state.user.subgroup);

      const scheduleData = await API.get(`/api/schedule/lessons?${params.toString()}`);

      if (!scheduleData || !scheduleData.slots || scheduleData.slots.length === 0) {
        const noScheduleUploaded = scheduleData && scheduleData.schedule_loaded === false;
        container.innerHTML = `
          <div class="py-16 text-center space-y-2">
            <div class="w-12 h-12 rounded-2xl bg-zinc-100 dark:bg-ios-cardDark2 text-zinc-400 mx-auto flex items-center justify-center text-xl">${noScheduleUploaded ? '📚' : '☕️'}</div>
            <h4 class="text-sm font-bold text-zinc-800 dark:text-zinc-200">${noScheduleUploaded ? 'Расписание ещё не загружено' : 'Уроков нет'}</h4>
            <p class="text-xs text-ios-secondaryText">${noScheduleUploaded ? `Для ${escapeHtml(targetClass)} класса расписание ещё не добавлено` : (isMyClass ? 'В этот день в расписании пока нет занятий' : `Для ${escapeHtml(targetClass)} класса расписание на этот день пока не загружено`)}</p>
          </div>
        `;
        return;
      }

      const todayDayIdx = getTyumenDate().getDay() === 0 ? 6 : getTyumenDate().getDay() - 1;
      if (state.selectedDay === todayDayIdx) {
        state.todayLessons = scheduleData.slots;
      }
      calculateLiveStatusLocally();
      container.innerHTML = scheduleData.slots.map(slot => renderLessonSlot(slot)).join('');
    }

    function renderLessonSlot(slot) {
      const timeStr = (slot.start_time && slot.end_time) ? `${slot.start_time} – ${slot.end_time}` : '';

      // Single lesson card or split cards
      if (!slot.is_split && slot.lessons.length === 1) {
        const l = slot.lessons[0];
        const profileBadge = l.profile_name 
          ? `<span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-purple-50 text-purple-600 dark:bg-purple-950/70 dark:text-purple-300">${l.profile_name}</span>` 
          : '';

        return `
          <div class="rounded-2xl p-4 bg-white dark:bg-ios-cardDark border border-zinc-200/60 dark:border-zinc-800/80 shadow-ios-card active-press transition-all">
            <div class="flex items-center justify-between text-xs text-ios-secondaryText mb-1.5">
              <span class="font-bold text-ios-blue flex items-center space-x-1.5">
                <span class="w-5 h-5 rounded-md bg-blue-50 dark:bg-blue-950 text-ios-blue flex items-center justify-center text-xs font-bold">${slot.lesson_number}</span>
                <span>${timeStr}</span>
              </span>
              <span class="px-2 py-0.5 rounded-lg font-bold bg-zinc-100 dark:bg-ios-cardDark2 text-zinc-700 dark:text-zinc-300">
                каб. ${l.cabinet}
              </span>
            </div>
            
            <h3 class="text-base font-bold text-zinc-900 dark:text-white leading-snug">${l.subject}</h3>
            
            <div class="mt-2 flex items-center justify-between text-xs">
              <span class="text-ios-secondaryText font-medium">${l.teacher_name}</span>
              <div class="flex items-center space-x-1">
                ${profileBadge}
              </div>
            </div>
          </div>
        `;
      } else {
        // Split Card (Раздвоенная карточка для параллельных профилей)
        return `
          <div class="rounded-2xl p-4 bg-white dark:bg-ios-cardDark border border-zinc-200/60 dark:border-zinc-800/80 shadow-ios-card space-y-3">
            <div class="flex items-center justify-between text-xs text-ios-secondaryText pb-1 border-b border-zinc-100 dark:border-zinc-800">
              <span class="font-bold text-ios-blue flex items-center space-x-1.5">
                <span class="w-5 h-5 rounded-md bg-blue-50 dark:bg-blue-950 text-ios-blue flex items-center justify-center text-xs font-bold">${slot.lesson_number}</span>
                <span>${timeStr}</span>
              </span>
              <span class="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-md bg-amber-50 text-amber-600 dark:bg-amber-950 dark:text-amber-300">
                Разделение профилей
              </span>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              ${slot.lessons.map(l => `
                <div class="p-3 rounded-xl bg-zinc-50 dark:bg-ios-cardDark2 border border-zinc-200/50 dark:border-zinc-800/50 flex flex-col justify-between space-y-1.5">
                  <div class="flex items-start justify-between">
                    <h4 class="text-xs font-bold text-zinc-900 dark:text-white leading-tight">${l.subject}</h4>
                    <span class="text-[10px] font-bold px-1.5 py-0.5 rounded bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300">
                      ${l.cabinet}
                    </span>
                  </div>
                  <div class="text-[11px] text-ios-secondaryText">${l.teacher_name}</div>
                  <div class="flex items-center space-x-1 pt-0.5">
                    ${l.profile_name ? `<span class="px-1.5 py-0.5 rounded text-[9px] font-bold bg-purple-100 text-purple-700 dark:bg-purple-900/60 dark:text-purple-300">${l.profile_name}</span>` : ''}
                  </div>
                </div>
              `).join('')}
            </div>
          </div>
        `;
      }
    }

// --------------------------------------------------------
    // News Feed Rendering & Interactions
    // --------------------------------------------------------
    async function loadNews() {
      const container = document.getElementById("news-posts-list");
      if (!container) return;
      container.innerHTML = `
        <div class="py-12 text-center text-xs text-ios-secondaryText space-y-2">
          <div class="inline-block animate-spin rounded-full h-5 w-5 border-2 border-ios-blue border-t-transparent"></div>
          <p>Загрузка новостей...</p>
        </div>
      `;

      try {
        const uid = state.user?.id || '';
        const posts = await API.get(`/api/news?user_id=${uid}`);
        if (posts === null) {
          container.innerHTML = `
            <div class="py-16 text-center space-y-2">
              <div class="w-12 h-12 rounded-2xl bg-red-50 dark:bg-red-950/40 text-red-500 mx-auto flex items-center justify-center text-xl">⚠️</div>
              <h4 class="text-sm font-bold text-zinc-800 dark:text-zinc-200">Не удалось загрузить новости</h4>
              <p class="text-xs text-ios-secondaryText">Проверьте соединение с интернетом</p>
              <button data-gym-click="h84dc45fa52e5" class="mt-2 px-3.5 py-1.5 rounded-xl bg-ios-blue text-white text-xs font-semibold active-press">Повторить</button>
            </div>
          `;
          return;
        }

        if (posts.length === 0) {
          container.innerHTML = `
            <div class="py-16 text-center space-y-2">
              <div class="w-12 h-12 rounded-2xl bg-zinc-100 dark:bg-ios-cardDark2 text-zinc-400 mx-auto flex items-center justify-center text-xl">📰</div>
              <h4 class="text-sm font-bold text-zinc-800 dark:text-zinc-200">Пока нет новостей</h4>
              <p class="text-xs text-ios-secondaryText">Будь первым, кто предложит новость в ленту!</p>
            </div>
          `;
          return;
        }

        state.news = posts;
        container.innerHTML = posts.map(p => renderNewsPost(p)).join("");
      } catch (err) {
        console.error("loadNews error:", err);
        container.innerHTML = `
          <div class="py-16 text-center space-y-2">
            <div class="w-12 h-12 rounded-2xl bg-red-50 dark:bg-red-950/40 text-red-500 mx-auto flex items-center justify-center text-xl">⚠️</div>
            <h4 class="text-sm font-bold text-zinc-800 dark:text-zinc-200">Ошибка при отображении</h4>
            <button data-gym-click="h84dc45fa52e5" class="mt-2 px-3.5 py-1.5 rounded-xl bg-ios-blue text-white text-xs font-semibold active-press">Повторить</button>
          </div>
        `;
      }
    }

    // Each news action uses a single inline handler.
    function renderReactionBar(postId, reactions) {
      if (!reactions || !Array.isArray(reactions)) return "";
      return reactions.map(r => `
        <button data-gym-click="h9324a72da623" data-gym-args="${encodeURIComponent(JSON.stringify([(postId),(r.emoji)]))}" class="reaction-btn px-2.5 py-1 rounded-full text-xs font-semibold flex items-center space-x-1 active-press transition-all ${
          r.user_reacted 
            ? "bg-blue-100 text-ios-blue border border-ios-blue/40 dark:bg-blue-950/80 dark:text-blue-300 ring-1 ring-ios-blue/30 font-bold" 
            : "bg-zinc-100 text-zinc-700 dark:bg-ios-cardDark2 dark:text-zinc-300"
        }">
          <span>${r.emoji}</span>
          <span>${r.count}</span>
        </button>
      `).join("");
    }

    function renderNewsPost(post) {
      const isAnon = post.is_anonymous;
      let avatarHtml = "";
      if (isAnon) {
        avatarHtml = `<div class="w-9 h-9 rounded-full bg-zinc-200 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 text-sm font-bold flex items-center justify-center shadow-xs">🎭</div>`;
      } else if (safeImageUrl(post.author_photo_url)) {
        avatarHtml = `<img src="${escapeHtml(safeImageUrl(post.author_photo_url))}" alt="${escapeHtml(post.author_name)}" class="w-9 h-9 rounded-full object-cover shadow-xs border border-zinc-200/50 dark:border-zinc-700/50">`;
      } else {
        const initial = post.author_name ? post.author_name.charAt(0) : "Г";
        avatarHtml = `<div class="w-9 h-9 rounded-full bg-gradient-to-tr from-ios-blue to-ios-indigo text-white text-xs font-bold flex items-center justify-center shadow-xs">${escapeHtml(initial)}</div>`;
      }

      const authorSafe = escapeHtml(post.author_name);
      const titleSafe = escapeHtml(post.title);
      const contentSafe = escapeHtml(post.content);
      const dateSafe = escapeHtml(post.created_at);

      const authorClassBadge = (!isAnon && post.author_class)
        ? `<span class="px-1.5 py-0.5 rounded-md bg-blue-50 text-ios-blue dark:bg-blue-950 dark:text-blue-300 text-[10px] font-bold border border-blue-200/50 dark:border-blue-900/50">${escapeHtml(post.author_class)}</span>`
        : "";

      const isAdmin = checkCanEdit();
      const adminActions = isAdmin ? `
        <div class="flex items-center space-x-1.5 ml-auto">
          <button data-gym-click="h45cf8a5abf92" data-gym-args="${encodeURIComponent(JSON.stringify([(post.id)]))}" data-post-id="${post.id}" class="delete-news-btn px-2.5 py-1 rounded-lg bg-red-50 hover:bg-red-100 dark:bg-red-950/60 dark:hover:bg-red-900/80 text-red-600 dark:text-red-400 text-xs font-medium flex items-center space-x-1 active-press cursor-pointer">
            <span>🗑</span>
            <span>Удалить</span>
          </button>
        </div>
      ` : "";

      // Natural uncropped aspect ratio for news media
      const imageUrl = safeImageUrl(post.image_url);
      const imageHtml = imageUrl
        ? `<div class="mt-3 rounded-2xl overflow-hidden border border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/30">
             <img ${window.protectedImageAttrs(imageUrl)} data-image-url="${escapeHtml(imageUrl)}" alt="Новость" class="safe-image-open w-full h-auto rounded-2xl cursor-pointer block" loading="lazy">
           </div>`
        : "";

      return `
        <article class="rounded-3xl p-5 bg-white dark:bg-ios-cardDark border border-zinc-200/60 dark:border-zinc-800/80 shadow-ios-card space-y-3">
          
          <!-- Post Author Header with Name, Class or Anonymous Badge & Admin Controls -->
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2.5">
              ${avatarHtml}
              <div>
                <div class="text-xs font-bold text-zinc-900 dark:text-white leading-tight flex items-center space-x-1.5">
                  <span>${authorSafe}</span>
                  ${authorClassBadge}
                </div>
                <div class="text-[10px] text-ios-secondaryText">${dateSafe}</div>
              </div>
            </div>
            ${adminActions}
          </div>

          <!-- Post Content -->
          <div>
            <h3 class="text-base font-bold text-zinc-900 dark:text-white leading-snug">${titleSafe}</h3>
            <p class="mt-1 text-xs text-zinc-600 dark:text-zinc-300 whitespace-pre-line leading-relaxed">${contentSafe}</p>
          </div>

          ${imageHtml}

          <!-- Reactions & Comments Bar -->
          <div class="pt-2 flex items-center justify-between border-t border-zinc-100 dark:border-zinc-800/60">
            <div id="reaction-bar-${post.id}" class="flex items-center space-x-1.5 flex-wrap gap-y-1">
              ${renderReactionBar(post.id, post.reactions)}
            </div>

            <button data-post-id="${post.id}" data-gym-click="h7d5601e7e01b" data-gym-args="${encodeURIComponent(JSON.stringify([(post.id)]))}" class="open-comments-btn px-3 py-1 rounded-full text-xs font-medium text-ios-secondaryText hover:text-zinc-900 dark:hover:text-white flex items-center space-x-1 active-press flex-shrink-0">
              <span>💬</span>
              <span id="comment-count-${post.id}">${post.comments_count || 0}</span>
            </button>
          </div>

        </article>
      `;
    }

    // --------------------------------------------------------
    // Propose News Modal Handling
    // --------------------------------------------------------
    function openProposeNewsModal() {
      window.communityDraftOpen?.();
      const modal = document.getElementById("propose-news-modal");
      if (modal) {
        modal.classList.remove("hidden");
        modal.classList.add("flex");
      }
      const fullName = `${state.user?.first_name || ""} ${state.user?.last_name || ""}`.trim() || state.user?.first_name || "Гимназист";
      const authorDisp = document.getElementById("propose-author-display");
      if (authorDisp) authorDisp.textContent = fullName;
      const classDisp = document.getElementById("propose-class-display");
      if (classDisp) classDisp.textContent = state.user?.class_name || "11А";
      haptic("selection");
    }

    async function closeProposeNewsModal() {
      if (window.communityDraftClose && !await window.communityDraftClose()) return;
      const modal = document.getElementById("propose-news-modal");
      if (modal) {
        modal.classList.add("hidden");
        modal.classList.remove("flex");
      }
      const titleEl = document.getElementById("propose-title");
      if (titleEl) titleEl.value = "";
      const contentEl = document.getElementById("propose-content");
      if (contentEl) contentEl.value = "";
      window.selectedImageFile = null;
      const fn = document.getElementById("propose-file-name");
      if (fn) fn.textContent = "Файл не выбран";
      const pr = document.getElementById("propose-image-preview");
      if (pr) pr.classList.add("hidden");
      const fileInput = document.getElementById("propose-file");
      if (fileInput) fileInput.value = "";
    }


    // Backdrop click to close propose modal
    document.getElementById("propose-news-modal")?.addEventListener("click", (e) => {
      if (e.target.id === "propose-news-modal") closeProposeNewsModal();
    });

    function handleImageUrlInput(val) {
      const url = val ? val.trim() : "";
      const pr = document.getElementById("propose-image-preview");
      const imgTag = document.getElementById("propose-img-tag");
      const fn = document.getElementById("propose-file-name");
      if (url && (url.startsWith("http://") || url.startsWith("https://"))) {
        if (imgTag) window.setProtectedImage(imgTag, url);
        if (pr) {
          pr.classList.remove("hidden");
          pr.style.display = "flex";
        }
        if (fn) {
          fn.textContent = "Ссылка указана ✓";
          fn.className = "text-xs font-bold text-ios-blue truncate max-w-[180px]";
        }
      } else if (!window.selectedImageFile) {
        if (pr) {
          pr.classList.add("hidden");
          pr.style.display = "none";
        }
        if (imgTag) window.setProtectedImage(imgTag, "");
        if (fn) {
          fn.textContent = "Файл не выбран";
          fn.className = "text-xs text-ios-secondaryText truncate max-w-[180px]";
        }
      }
    }
    window.handleImageUrlInput = handleImageUrlInput;

    function handleProposeFileChange(input) {
      const file = input && input.files && input.files[0];
      if (!file) return;
      window.selectedImageFile = file;

      const fn = document.getElementById("propose-file-name");
      if (fn) fn.textContent = file.name || "Фото выбрано";

      const reader = new FileReader();
      reader.onload = function(re) {
        const imgTag = document.getElementById("propose-img-tag");
        if (imgTag) window.setProtectedImage(imgTag, re.target.result);
        const pr = document.getElementById("propose-image-preview");
        if (pr) pr.classList.remove("hidden");
      };
      reader.readAsDataURL(file);
      haptic("selection");
    }
    window.handleProposeFileChange = handleProposeFileChange;

    function removeSelectedPhoto() {
      window.selectedImageFile = null;
      const fileInput = document.getElementById("propose-file");
      if (fileInput) fileInput.value = "";
      const fn = document.getElementById("propose-file-name");
      if (fn) fn.textContent = "Файл не выбран";
      const pr = document.getElementById("propose-image-preview");
      if (pr) pr.classList.add("hidden");
      const imgTag = document.getElementById("propose-img-tag");
      if (imgTag) window.setProtectedImage(imgTag, "");
      haptic("impact");
    }
    window.removeSelectedPhoto = removeSelectedPhoto;

    document.getElementById("propose-file")?.addEventListener("change", function(e) {
      handleProposeFileChange(e.target);
    });

    async function handleSubmitProposeNews() {
      const submitBtn = document.getElementById("submit-news-btn");
      if (submitBtn?.disabled) return;
      const titleInput = document.getElementById("propose-title");
      const contentInput = document.getElementById("propose-content");
      const title = titleInput ? titleInput.value.trim() : "";
      const content = contentInput ? contentInput.value.trim() : "";

      if (!title || title.length < 3) {
        alert("Пожалуйста, введите заголовок новости (не менее 3 символов)");
        return;
      }
      if (!content || content.length < 5) {
        alert("Пожалуйста, введите текст новости (не менее 5 символов)");
        return;
      }

      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "Отправка...";
        [titleInput, contentInput, document.getElementById("propose-anonymous")].forEach(el => { if (el) el.disabled = true; });
      }

      try {
        await window.communityDraftFlush?.();
        let imageUrl = document.getElementById("propose-image-url-input")?.value.trim() || null;
        if (window.selectedImageFile) {
          try {
            const uploadRes = await API.upload(window.selectedImageFile);
            if (uploadRes && uploadRes.url) {
              imageUrl = uploadRes.url;
            }
          } catch (uploadErr) {
            throw new Error("Фото не загрузилось. Попробуйте ещё раз: " + uploadErr.message);
          }
        }

        const isAnonymous = document.getElementById("propose-anonymous") ? document.getElementById("propose-anonymous").checked : false;
        const authorClass = state.user?.class_name || "11А";
        const authorName = `${state.user?.first_name || ""} ${state.user?.last_name || ""}`.trim() || state.user?.first_name || "Гимназист";
        const rawId = state.user?.id;
        const authorId = (rawId && !isNaN(parseInt(rawId, 10))) ? parseInt(rawId, 10) : (state.user?.id || null);

        const postRes = await API.post("/api/news", {
          title: title,
          content: content,
          image_url: imageUrl,
          author_id: authorId,
          author_name: authorName,
          author_class: authorClass,
          author_username: state.user?.username || (window.Telegram?.WebApp?.initDataUnsafe?.user?.username) || null,
          is_anonymous: isAnonymous
        });

        if (postRes) {
          haptic("success");
          await window.communityDraftSent?.();
          await closeProposeNewsModal();
          alert("Спасибо! Твоя новость успешно отправлена на модерацию администратору.");
          await checkPendingNewsCount();
          await loadNews();
        }
      } catch (err) {
        console.error("Submit news error:", err);
        alert("Ошибка при отправке новости: " + (err.message || "попробуйте позже"));
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "Отправить на модерацию";
          [titleInput, contentInput, document.getElementById("propose-anonymous")].forEach(el => { if (el) el.disabled = false; });
        }
      }
    }
    window.handleSubmitProposeNews = handleSubmitProposeNews;

    document.getElementById("submit-news-btn")?.addEventListener("click", handleSubmitProposeNews);

    // --------------------------------------------------------
    // Edit News Post Handling (Admin)
    // --------------------------------------------------------
    const editModal = document.getElementById("edit-news-modal");
    const closeEditModalBtn = document.getElementById("close-edit-modal-btn");
    const saveEditPostBtn = document.getElementById("save-edit-post-btn");

    window.editSelectedImageFile = null;
    window.editCurrentImageUrl = null;

    function openEditModal(postId) {
      const post = state.news.find(p => p.id === postId);
      if (!post) return;
      document.getElementById("edit-post-id").value = post.id;
      document.getElementById("edit-post-title").value = post.title || "";
      document.getElementById("edit-post-content").value = post.content || "";

      window.editSelectedImageFile = null;
      window.editCurrentImageUrl = post.image_url || null;

      const fileInput = document.getElementById("edit-post-file");
      if (fileInput) fileInput.value = "";

      const fileNameEl = document.getElementById("edit-post-file-name");
      if (fileNameEl) fileNameEl.textContent = "Файл не выбран";

      const urlInput = document.getElementById("edit-post-image-url-input");
      if (urlInput) urlInput.value = post.image_url || "";

      const previewContainer = document.getElementById("edit-post-image-preview");
      const imgTag = document.getElementById("edit-post-img-tag");
      if (post.image_url && imgTag && previewContainer) {
        window.setProtectedImage(imgTag, post.image_url);
        previewContainer.classList.remove("hidden");
        previewContainer.classList.add("flex");
      } else if (previewContainer) {
        previewContainer.classList.add("hidden");
        previewContainer.classList.remove("flex");
        if (imgTag) window.setProtectedImage(imgTag, "");
      }

      if (editModal) {
        editModal.classList.remove("hidden");
        editModal.classList.add("flex");
      }
      haptic("selection");
    }

    function closeEditModal() {
      if (editModal) {
        editModal.classList.add("hidden");
        editModal.classList.remove("flex");
      }
      window.editSelectedImageFile = null;
    }


    function handleEditFileChange(input) {
      if (!input || !input.files || input.files.length === 0) return;
      const file = input.files[0];
      window.editSelectedImageFile = file;

      const fileNameEl = document.getElementById("edit-post-file-name");
      if (fileNameEl) fileNameEl.textContent = file.name;

      const urlInput = document.getElementById("edit-post-image-url-input");
      if (urlInput) urlInput.value = "";

      const previewContainer = document.getElementById("edit-post-image-preview");
      const imgTag = document.getElementById("edit-post-img-tag");
      if (previewContainer && imgTag) {
        try {
          const previewUrl = URL.createObjectURL(file);
          window.setProtectedImage(imgTag, previewUrl);
          previewContainer.classList.remove("hidden");
          previewContainer.classList.add("flex");
        } catch (e) {
          const reader = new FileReader();
          reader.onload = function(evt) {
            window.setProtectedImage(imgTag, evt.target.result);
            previewContainer.classList.remove("hidden");
            previewContainer.classList.add("flex");
          };
          reader.readAsDataURL(file);
        }
      }
      haptic("selection");
    }
    window.handleEditFileChange = handleEditFileChange;

    function handleEditImageUrlInput(val) {
      const url = val ? val.trim() : "";
      window.editSelectedImageFile = null;
      window.editCurrentImageUrl = url || null;

      const fileNameEl = document.getElementById("edit-post-file-name");
      if (fileNameEl) fileNameEl.textContent = url ? "По ссылке" : "Файл не выбран";

      const previewContainer = document.getElementById("edit-post-image-preview");
      const imgTag = document.getElementById("edit-post-img-tag");
      if (previewContainer && imgTag) {
        if (url) {
          window.setProtectedImage(imgTag, url);
          previewContainer.classList.remove("hidden");
          previewContainer.classList.add("flex");
        } else {
          previewContainer.classList.add("hidden");
          previewContainer.classList.remove("flex");
          window.setProtectedImage(imgTag, "");
        }
      }
    }
    window.handleEditImageUrlInput = handleEditImageUrlInput;

    function removeEditPhoto() {
      window.editSelectedImageFile = null;
      window.editCurrentImageUrl = "";

      const fileInput = document.getElementById("edit-post-file");
      if (fileInput) fileInput.value = "";

      const fileNameEl = document.getElementById("edit-post-file-name");
      if (fileNameEl) fileNameEl.textContent = "Файл не выбран";

      const urlInput = document.getElementById("edit-post-image-url-input");
      if (urlInput) urlInput.value = "";

      const previewContainer = document.getElementById("edit-post-image-preview");
      const imgTag = document.getElementById("edit-post-img-tag");
      if (previewContainer) {
        previewContainer.classList.add("hidden");
        previewContainer.classList.remove("flex");
      }
      if (imgTag) window.setProtectedImage(imgTag, "");
      haptic("impact");
    }
    window.removeEditPhoto = removeEditPhoto;

    async function saveEditPost() {
      if (document.getElementById("save-edit-post-btn")?.disabled) return;
      const postId = parseInt(document.getElementById("edit-post-id").value, 10);
      const title = document.getElementById("edit-post-title").value.trim();
      const content = document.getElementById("edit-post-content").value.trim();
      const saveBtn = document.getElementById("save-edit-post-btn");

      if (!title || title.length < 3) {
        alert("Заполните заголовок (не менее 3 символов)");
        return;
      }
      if (!content || content.length < 5) {
        alert("Заполните текст новости (не менее 5 символов)");
        return;
      }

      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = "Сохранение...";
      }

      try {
        let finalImageUrl = window.editCurrentImageUrl;
        if (window.editSelectedImageFile) {
          try {
            const uploadRes = await API.upload(window.editSelectedImageFile);
            if (uploadRes && uploadRes.url) {
              finalImageUrl = uploadRes.url;
            }
          } catch (uploadErr) {
            console.warn("Upload failed:", uploadErr);
          }
        }

        const uid = state.user?.id || 0;
        const updated = await API.put(`/api/admin/news/${postId}`, {
          title: title,
          content: content,
          image_url: finalImageUrl,
          admin_id: parseInt(uid, 10)
        });

        if (updated) {
          closeEditModal();
          haptic("success");
          await loadNews();
        }
      } catch (err) {
        console.error("Save edit post error:", err);
        alert("Ошибка при сохранении: " + (err.message || "попробуйте позже"));
      } finally {
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.textContent = "Сохранить изменения";
        }
      }
    }
    window.saveEditPost = saveEditPost;
    window.openEditModal = openEditModal;
    window.closeEditModal = closeEditModal;

    // --------------------------------------------------------
    // Admin Moderation Modal Handling
    // --------------------------------------------------------
    const moderationModal = document.getElementById("admin-moderation-modal");
    const openModerationBtn = document.getElementById("admin-moderation-btn");
    const closeModerationBtn = document.getElementById("close-moderation-modal-btn");

    async function checkPendingNewsCount() {
      if (!checkCanEdit()) return;
      try {
        const uid = state.user?.id || 0;
        const pending = await API.get(`/api/admin/news/pending?admin_id=${uid}`);
        const count = (pending && Array.isArray(pending)) ? pending.length : 0;
        
        const navAdminBadge = document.getElementById("nav-admin-badge");
        const subtabBadge = document.getElementById("admin-subtab-pending-badge");
        const adminBadge = document.getElementById("admin-pending-badge");

        if (adminBadge) adminBadge.textContent = count;
        if (count > 0) {
          if (navAdminBadge) {
            navAdminBadge.textContent = count;
            navAdminBadge.classList.remove("hidden");
          }
          if (subtabBadge) {
            subtabBadge.textContent = count;
            subtabBadge.classList.remove("hidden");
          }
        } else {
          if (navAdminBadge) navAdminBadge.classList.add("hidden");
          if (subtabBadge) subtabBadge.classList.add("hidden");
        }
      } catch (e) {
        console.error("checkPendingNewsCount error:", e);
      }
    }

    function renderPendingNews(posts) {
      const container = document.getElementById("admin-pending-list");
      if (!container) return;
      if (!posts || posts.length === 0) {
        container.innerHTML = `
          <div class="py-12 text-center text-xs text-ios-secondaryText space-y-1">
            <p class="text-2xl">🎉</p>
            <p class="font-bold text-zinc-700 dark:text-zinc-300">Все новости промодерированы</p>
            <p>В предложке нет ожидающих публикаций</p>
          </div>
        `;
        return;
      }

      container.innerHTML = posts.map(p => {
        const isAnon = p.is_anonymous;
        const anonBadge = isAnon 
          ? '<span class="px-2 py-0.5 rounded-md bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300 text-[10px] font-bold">🎭 Анонимно в ленте</span>' 
          : "";
        const authorSafe = escapeHtml(p.author_name);
        const usernameSafe = p.author_username ? escapeHtml(p.author_username.replace(/^@/, '')) : '';
        const titleSafe = escapeHtml(p.title);
        const contentSafe = escapeHtml(p.content);
        const dateSafe = escapeHtml(p.created_at);

        const classBadge = p.author_class 
          ? `<span class="px-2 py-0.5 rounded-md bg-blue-100 text-ios-blue dark:bg-blue-950 dark:text-blue-300 text-[10px] font-bold">${escapeHtml(p.author_class)}</span>` 
          : "";

        // Uncropped photo preview for admin moderation
        const imageUrl = safeImageUrl(p.image_url);
        const imageHtml = imageUrl ? `
          <div class="mt-2 rounded-xl overflow-hidden border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900 flex items-center justify-center">
            <img ${window.protectedImageAttrs(imageUrl)} data-image-url="${escapeHtml(imageUrl)}" alt="Фото новости" class="safe-image-open w-full h-auto max-h-72 object-contain rounded-xl cursor-pointer">
          </div>
        ` : '<div class="mt-2 p-2 rounded-xl bg-zinc-100 dark:bg-zinc-800/50 text-[11px] text-ios-secondaryText italic">Без фотографии</div>';

        return `
          <div class="p-4 rounded-2xl bg-zinc-100/80 dark:bg-ios-cardDark2 border border-zinc-200/60 dark:border-zinc-800 space-y-2.5">
            <div class="flex items-center justify-between flex-wrap gap-1">
              <div class="flex items-center space-x-1.5 flex-wrap">
                <span class="text-xs font-bold text-zinc-900 dark:text-white">${authorSafe}</span>
                ${usernameSafe ? `<span class="text-[11px] font-semibold text-ios-blue">@${usernameSafe}</span>` : '<span class="text-[11px] text-ios-secondaryText">(нет username)</span>'}
                ${classBadge}
                ${anonBadge}
              </div>
              <span class="text-[10px] text-ios-secondaryText">${dateSafe}</span>
            </div>

            <div>
              <h4 class="text-sm font-bold text-zinc-900 dark:text-white">${titleSafe}</h4>
              <p class="mt-1 text-xs text-zinc-600 dark:text-zinc-300 whitespace-pre-line leading-relaxed">${contentSafe}</p>
            </div>

            ${imageHtml}

            <div class="pt-2 flex items-center justify-end space-x-2 border-t border-zinc-200/60 dark:border-zinc-800/80">
              <button data-gym-click="h81101468ca67" data-gym-args="${encodeURIComponent(JSON.stringify([(p.id)]))}" class="admin-reject-btn px-3 py-1.5 rounded-xl bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300 text-xs font-bold active-press cursor-pointer">
                ❌ Отклонить
              </button>
              <button data-gym-click="h3b11f751d6dd" data-gym-args="${encodeURIComponent(JSON.stringify([(p.id)]))}" class="admin-approve-btn px-3.5 py-1.5 rounded-xl bg-emerald-600 text-white text-xs font-bold shadow-xs active-press cursor-pointer">
                ✅ Опубликовать
              </button>
            </div>
          </div>
        `;
      }).join("");
    }

    async function loadAdminPendingNews() {
      if (!checkCanEdit()) return;
      const container = document.getElementById("admin-pending-list");
      if (!container) return;
      container.innerHTML = `
        <div class="py-10 text-center text-xs text-ios-secondaryText flex items-center justify-center gap-2">
          <div class="w-4 h-4 border-2 border-ios-blue border-t-transparent rounded-full animate-spin"></div>
          <span>Загрузка предложенных новостей...</span>
        </div>
      `;
      try {
        const uid = state.user?.id || 0;
        const pending = await API.get(`/api/admin/news/pending?admin_id=${uid}`);
        renderPendingNews(pending || []);
        await checkPendingNewsCount();
      } catch (err) {
        console.error("loadAdminPendingNews error:", err);
        container.innerHTML = `
          <div class="py-10 text-center text-xs text-red-500">
            Ошибка при загрузке предложки: ${escapeHtml(err.message || "попробуйте позже")}
          </div>
        `;
      }
    }
    window.loadAdminPendingNews = loadAdminPendingNews;

    function setAdminSubtab(subtab) {
      haptic('selection');
      const modBtn = document.getElementById("admin-subtab-moderation-btn");
      const usersBtn = document.getElementById("admin-subtab-users-btn");
      const modSec = document.getElementById("admin-section-moderation");
      const usersSec = document.getElementById("admin-section-users");

      if (subtab === 'moderation') {
        modBtn?.classList.add("bg-white", "dark:bg-zinc-700", "text-zinc-900", "dark:text-white", "shadow-xs");
        modBtn?.classList.remove("text-ios-secondaryText");
        usersBtn?.classList.remove("bg-white", "dark:bg-zinc-700", "text-zinc-900", "dark:text-white", "shadow-xs");
        usersBtn?.classList.add("text-ios-secondaryText");

        modSec?.classList.remove("hidden");
        usersSec?.classList.add("hidden");
        loadAdminPendingNews();
      } else {
        usersBtn?.classList.add("bg-white", "dark:bg-zinc-700", "text-zinc-900", "dark:text-white", "shadow-xs");
        usersBtn?.classList.remove("text-ios-secondaryText");
        modBtn?.classList.remove("bg-white", "dark:bg-zinc-700", "text-zinc-900", "dark:text-white", "shadow-xs");
        modBtn?.classList.add("text-ios-secondaryText");

        usersSec?.classList.remove("hidden");
        modSec?.classList.add("hidden");
        loadAdminUsers();
      }
    }
    window.setAdminSubtab = setAdminSubtab;

    async function openModerationModal() {
      switchTab('tab-admin');
      setAdminSubtab('moderation');
    }

    function closeModerationModal() {
      // Compatibility stub
    }

    async function handleModeratePost(postId, action) {
      haptic("impact");
      const uid = state.user?.id || 0;
      try {
        await API.post(`/api/admin/news/${postId}/moderate`, {
          action: action,
          admin_id: parseInt(uid, 10)
        });
        await loadAdminPendingNews();
        await checkPendingNewsCount();
        await loadNews();
      } catch (err) {
        alert("Ошибка модерации: " + err.message);
      }
    }

    // --------------------------------------------------------
    // Admin Users Management & Ban System
    // --------------------------------------------------------
    async function openUsersModal() {
      switchTab('tab-admin');
      setAdminSubtab('users');
    }
    window.openUsersModal = openUsersModal;

    function closeUsersModal() {
      // Compatibility stub
    }
    window.closeUsersModal = closeUsersModal;

    async function loadAdminUsers() {
      const listContainer = document.getElementById("admin-users-list");
      if (!listContainer) return;
      listContainer.innerHTML = `
        <div class="py-10 text-center text-xs text-ios-secondaryText flex items-center justify-center gap-2">
          <div class="w-4 h-4 border-2 border-ios-blue border-t-transparent rounded-full animate-spin"></div>
          <span>Загрузка списка пользователей...</span>
        </div>
      `;

      try {
        const adminId = state.user?.id || 0;
        const users = await API.get(`/api/admin/users?admin_id=${adminId}`);
        cachedAdminUsers = Array.isArray(users) ? users : [];
        window.cachedAdminUsers = cachedAdminUsers;
        updateUsersStats(cachedAdminUsers);
        renderAdminUsers(cachedAdminUsers);
      } catch (err) {
        console.error("loadAdminUsers error:", err);
        listContainer.innerHTML = `
          <div class="py-10 text-center text-xs text-red-500">
            Ошибка при загрузке пользователей: ${escapeHtml(err.message || "попробуйте позже")}
          </div>
        `;
      }
    }
    window.loadAdminUsers = loadAdminUsers;

    function updateUsersStats(users) {
      const total = users.length;
      const banned = users.filter(u => u.is_banned).length;
      const active = total - banned;
      const totalEl = document.getElementById("users-stat-total");
      const activeEl = document.getElementById("users-stat-active");
      const bannedEl = document.getElementById("users-stat-banned");
      if (totalEl) totalEl.textContent = total;
      if (activeEl) activeEl.textContent = active;
      if (bannedEl) bannedEl.textContent = banned;
    }

    function renderAdminUsers(users) {
      const listContainer = document.getElementById("admin-users-list");
      if (!listContainer) return;

      if (!users || users.length === 0) {
        listContainer.innerHTML = `
          <div class="py-12 text-center text-xs text-ios-secondaryText space-y-1">
            <p class="text-2xl">👥</p>
            <p class="font-bold text-zinc-700 dark:text-zinc-300">Пользователи не найдены</p>
          </div>
        `;
        return;
      }

      listContainer.innerHTML = users.map(u => {
        const isSelfOrAdmin = u.is_admin || (state.user && u.id === state.user.id);
        const cleanUname = u.username ? u.username.replace(/^@/, '') : null;
        const unameSafe = cleanUname ? `@${escapeHtml(cleanUname)}` : null;
        const tgLink = cleanUname ? `https://t.me/${encodeURIComponent(cleanUname)}` : null;
        const fullName = `${u.first_name || 'Гимназист'} ${u.last_name || ''}`.trim();
        const nameSafe = escapeHtml(fullName);
        const classBadge = u.class_name ? `<span class="px-2 py-0.5 rounded-md bg-blue-50 text-ios-blue dark:bg-blue-950 dark:text-blue-300 text-[10px] font-bold border border-blue-200/50 dark:border-blue-900/50">${escapeHtml(u.class_name)}</span>` : '<span class="text-[10px] text-zinc-400">класс не выбран</span>';
        const profileBadge = u.profile_name ? `<span class="px-2 py-0.5 rounded-md bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300 text-[10px] font-semibold">${escapeHtml(u.profile_name)}</span>` : '';
        const roleBadge = u.is_admin ? '<span class="px-2 py-0.5 rounded-md bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300 text-[10px] font-bold">Администратор 👑</span>' : '';
        const statusBadge = u.is_banned 
          ? '<span class="px-2 py-0.5 rounded-md bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300 text-[10px] font-bold">🚫 В бане</span>'
          : '<span class="px-2 py-0.5 rounded-md bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300 text-[10px] font-bold">🟢 Активен</span>';

        let actionBtn = '';
        if (isSelfOrAdmin) {
          actionBtn = '<span class="text-[11px] text-zinc-400 italic">Защищен</span>';
        } else if (u.is_banned) {
          actionBtn = `
            <button data-gym-click="hf956c433e346" data-gym-args="${encodeURIComponent(JSON.stringify([(u.id)]))}" class="px-3 py-1 rounded-xl bg-green-100 hover:bg-green-200 text-green-800 dark:bg-green-950 dark:hover:bg-green-900 dark:text-green-300 text-xs font-semibold active-press cursor-pointer">
              ✅ Разбанить
            </button>
          `;
        } else {
          actionBtn = `
            <button data-gym-click="h25e5f50fa331" data-gym-args="${encodeURIComponent(JSON.stringify([(u.id)]))}" class="px-3 py-1 rounded-xl bg-red-100 hover:bg-red-200 text-red-700 dark:bg-red-950 dark:hover:bg-red-900 dark:text-red-300 text-xs font-semibold active-press cursor-pointer">
              🚫 Забанить
            </button>
          `;
        }

        return `
          <div class="p-3.5 rounded-2xl bg-zinc-50 dark:bg-ios-cardDark2 border border-zinc-200/60 dark:border-zinc-800 space-y-2">
            <div class="flex items-start justify-between gap-2">
              <div>
                <div class="text-xs font-bold text-zinc-900 dark:text-white flex items-center gap-1.5 flex-wrap">
                  <span>${nameSafe}</span>
                  ${roleBadge}
                  ${u.role === "editor" ? '<span class="g-badge">Редактор</span>' : ""}
                  ${u.role === "headman" ? `<span class="g-badge">Староста ${escapeHtml(u.headman_class_name||u.class_name||"—")}</span>` : ""}
                  ${statusBadge}
                </div>
                <div class="flex items-center gap-2 mt-0.5 text-[11px] text-ios-secondaryText flex-wrap">
                  ${unameSafe ? `<a href="${tgLink}" target="_blank" class="text-ios-blue font-medium hover:underline flex items-center gap-0.5"><span>💬</span> ${unameSafe}</a>` : '<span>(нет @username)</span>'}
                  <span>• ID: <code>${u.id}</code></span>
                </div>
              </div>
              <div>${actionBtn}${!isSelfOrAdmin ? `<button class="g-btn" data-gym-click="haa6ca87f4155" data-gym-args="${encodeURIComponent(JSON.stringify([(u.id),(u.role === "editor" ? "student" : "editor")]))}">${u.role === "editor" ? "Снять роль редактора" : "Назначить редактором"}</button><button class="g-btn" data-gym-click="h7e21b831fe3a" data-gym-args="${encodeURIComponent(JSON.stringify([(u.id),(u.role === "headman")]))}">${u.role === "headman" ? "Снять роль старосты" : "Назначить старостой"}</button>` : ""}</div>
            </div>

            <div class="flex items-center justify-between text-xs pt-1 border-t border-zinc-200/40 dark:border-zinc-800/60">
              <div class="flex items-center gap-1.5 flex-wrap">
                ${classBadge}
                ${profileBadge}
              </div>
              <span class="text-[10px] text-ios-secondaryText">${escapeHtml(u.created_at || '')}</span>
            </div>
          </div>
        `;
      }).join('');
    }

    async function toggleUserBan(userId, isBanned) {
      const actionText = isBanned ? "заблокировать" : "разблокировать";
      if (!confirm(`Вы действительно хотите ${actionText} этого пользователя?`)) return;
      haptic("impact");

      try {
        const adminId = state.user?.id || 0;
        const res = await API.post(`/api/admin/users/${userId}/ban`, {
          admin_id: parseInt(adminId, 10),
          is_banned: isBanned
        });

        if (res && res.status === "success") {
          haptic("success");
          const target = cachedAdminUsers.find(u => u.id === userId);
          if (target) {
            target.is_banned = isBanned;
          }
          updateUsersStats(cachedAdminUsers);
          filterUsersList();
        } else {
          alert("Не удалось изменить статус пользователя");
        }
      } catch (err) {
        console.error("toggleUserBan error:", err);
        alert("Ошибка: " + (err.message || "попробуйте позже"));
      }
    }
    window.toggleUserBan = toggleUserBan;

    function filterUsersList() {
      const input = document.getElementById("users-search-input");
      const q = input ? input.value.trim().toLowerCase() : "";
      if (!q) {
        renderAdminUsers(cachedAdminUsers);
        return;
      }
      const filtered = cachedAdminUsers.filter(u => {
        const name = `${u.first_name || ''} ${u.last_name || ''}`.toLowerCase();
        const uname = (u.username || '').toLowerCase();
        const cls = (u.class_name || '').toLowerCase();
        const prof = (u.profile_name || '').toLowerCase();
        const uid = String(u.id);
        return name.includes(q) || uname.includes(q) || cls.includes(q) || prof.includes(q) || uid.includes(q);
      });
      renderAdminUsers(filtered);
    }
    window.filterUsersList = filterUsersList;

    async function downloadUsersCsv() {
      haptic("impact");
      try {
        const adminId = state.user?.id || 0;
        const initData = window.Telegram?.WebApp?.initData || '';
        const headers = initData ? { 'X-Telegram-Init-Data': initData } : {};
        const res = await fetch(`/api/admin/users/export?admin_id=${adminId}`, { headers });
        if (!res.ok) throw new Error("Ошибка доступа");
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "gym16_users.csv";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
      } catch (e) {
        alert("Не удалось скачать файл: " + (e.message || "ошибка доступа"));
      }
    }
    window.downloadUsersCsv = downloadUsersCsv;

    async function togglePostReaction(postId, emoji) {
      haptic("impact");
      const uid = state.user?.id || 0;
      const updatedReactions = await API.post(`/api/news/${postId}/react`, {
        user_id: parseInt(uid, 10),
        emoji: emoji
      });
      if (updatedReactions) {
        const post = state.news.find(item => item.id === postId);
        if (post) {
          post.reactions = updatedReactions;
          const bar = document.getElementById(`reaction-bar-${postId}`);
          if (bar) bar.innerHTML = renderReactionBar(postId, updatedReactions);
        }
      }
    }

    async function handleDeleteNewsPost(postId) {
      if (!confirm("Вы действительно хотите удалить этот пост из школьной ленты новостей?")) return;
      haptic("impact");
      const uid = state.user?.id || 0;
      const res = await API.delete(`/api/admin/news/${postId}?admin_id=${uid}`);
      if (res) {
        haptic("success");
        state.news = state.news.filter(p => p.id !== postId);
        const container = document.getElementById("news-posts-list");
        if (container) {
          container.innerHTML = state.news.map(p => renderNewsPost(p)).join("");
        }
        await loadNews();
      }
    }

    async function sendNewComment() {
      const input = document.getElementById("new-comment-input");
      const btn = document.getElementById("send-comment-btn");
      if (btn?.disabled) return;
      const text = input ? input.value.trim() : "";
      if (!text || !state.activePostForComments) return;
      if (btn) btn.disabled = true;
      haptic("impact");

      try {
        const postId = state.activePostForComments;
        const authorName = `${state.user.first_name || ""} ${state.user.last_name || ""}`.trim() || state.user.first_name || "Гимназист";
        const newComment = await API.post(`/api/news/${postId}/comments`, {
          user_id: parseInt(state.user.id || 0, 10),
          author_name: authorName,
          author_class: state.user.class_name,
          text: text
        });

        if (newComment) {
          if (state.activePostForComments === postId) {
            if (input && input.value.trim() === text) input.value = "";
            const comments = await API.get(`/api/news/${postId}/comments`);
            if (state.activePostForComments === postId && comments) renderCommentsList(comments);
          }
          const post = state.news.find(item => item.id === postId);
          if (post) {
            post.comments_count = (post.comments_count || 0) + 1;
            const countEl = document.getElementById(`comment-count-${post.id}`);
            if (countEl) countEl.textContent = post.comments_count;
          }
        }
      } catch (err) {
        console.error("Send comment error:", err);
        alert("Не удалось отправить комментарий: " + (err.message || "попробуйте позже"));
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    openModerationBtn?.addEventListener("click", openModerationModal);

    // --------------------------------------------------------
    // Bottom Sheet: Comments Handling
    // --------------------------------------------------------
    const commentsSheet = document.getElementById("comments-sheet");
    const closeCommentsBtn = document.getElementById("close-comments-btn");
    const newCommentInput = document.getElementById("new-comment-input");
    const sendCommentBtn = document.getElementById("send-comment-btn");

    async function openCommentsSheet(postId) {
      const pid = parseInt(postId, 10);
      if (isNaN(pid)) return;
      state.activePostForComments = pid;
      state.commentsLoaded = [];
      state.commentsOffset = 0;
      const sheet = document.getElementById("comments-sheet");
      if (sheet) {
        sheet.classList.remove("hidden");
        sheet.classList.add("flex");
      }

      const container = document.getElementById("comments-sheet-list");
      if (container) {
        container.innerHTML = `
          <div class="py-12 text-center text-xs text-ios-secondaryText">
            <div class="inline-block animate-spin rounded-full h-4 w-4 border-2 border-ios-blue border-t-transparent"></div>
            <p class="mt-1">Загрузка комментариев...</p>
          </div>
        `;
      }

      const comments = await API.get(`/api/news/${pid}/comments?limit=50&offset=0`);
      state.commentsLoaded = comments || [];
      state.commentsOffset = state.commentsLoaded.length;
      renderCommentsList(state.commentsLoaded, state.commentsLoaded.length === 50);
      haptic("selection");
    }

    function closeCommentsSheet() {
      const sheet = document.getElementById("comments-sheet");
      if (sheet) {
        sheet.classList.add("hidden");
        sheet.classList.remove("flex");
      }
      state.activePostForComments = null;
      const input = document.getElementById("new-comment-input");
      if (input) input.value = "";
    }


    // Backdrop click to close comments sheet
    document.getElementById("comments-sheet")?.addEventListener("click", (e) => {
      if (e.target.id === "comments-sheet") closeCommentsSheet();
    });

    function renderCommentsList(comments, hasMore = comments?.length === 50) {
      const container = document.getElementById("comments-sheet-list");
      state.commentsLoaded = comments || [];
      state.commentsHasMore = hasMore;
      state.commentsOffset = state.commentsLoaded.length;
      if (!comments || comments.length === 0) {
        container.innerHTML = `
          <div class="py-12 text-center text-xs text-ios-secondaryText space-y-1">
            <p class="font-bold text-zinc-700 dark:text-zinc-300">Пока нет комментариев</p>
            <p>Оставьте первый комментарий к этой записи</p>
          </div>
        `;
        return;
      }

      const olderButton = hasMore ? '<button type="button" class="load-older-comments w-full py-2 text-xs font-semibold text-ios-blue">Показать предыдущие комментарии</button>' : '';
      container.innerHTML = olderButton + comments.map(c => {
        const canDelete = state.user && (checkCanEdit() || c.user_id === state.user.id);
        const deleteBtn = canDelete ? `
          <button data-comment-id="${c.id}" class="delete-comment-btn p-1 text-zinc-400 hover:text-red-500 rounded-md active-press" title="Удалить комментарий">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
          </button>
        ` : "";

        const authorSafe = escapeHtml(c.author_name);
        const classSafe = c.author_class ? `<span class="text-[10px] text-ios-blue font-normal">(${escapeHtml(c.author_class)})</span>` : "";
        const textSafe = escapeHtml(c.text);
        const dateSafe = escapeHtml(c.created_at);
        const editBtn = Number(c.user_id) === Number(state.user?.id)
          ? `<button type="button" class="edit-comment-btn g-btn" data-comment-id="${c.id}" aria-label="Редактировать комментарий">Изменить</button>` : '';

        return `
          <div class="p-3 rounded-2xl bg-zinc-100 dark:bg-ios-cardDark2 space-y-1">
            <div class="flex items-center justify-between">
              <span class="text-xs font-bold text-zinc-900 dark:text-white">${authorSafe} ${classSafe}</span>
              <div class="flex items-center space-x-1.5">
                <span class="text-[10px] text-ios-secondaryText">${dateSafe}${c.is_edited ? ' · изменён' : ''}</span>
                ${editBtn}
                ${deleteBtn}
              </div>
            </div>
            <p class="text-xs text-zinc-700 dark:text-zinc-200 whitespace-pre-line leading-relaxed">${textSafe}</p>
          </div>
        `;
      }).join("");
      container.scrollTop = container.scrollHeight;
    }

    // Comment deletion listener (admin or comment author)
    document.getElementById("comments-sheet-list")?.addEventListener("click", async (e) => {
      const editBtn = e.target.closest('.edit-comment-btn');
      if (editBtn) { window.toolsEditComment?.(Number(editBtn.dataset.commentId)); return; }
      const olderBtn = e.target.closest(".load-older-comments");
      if (olderBtn && state.activePostForComments) {
        olderBtn.disabled = true;
        const older = await API.get(`/api/news/${state.activePostForComments}/comments?limit=50&offset=${state.commentsOffset || 0}`);
        if (older) {
          state.commentsLoaded = [...older, ...(state.commentsLoaded || [])];
          state.commentsOffset = (state.commentsOffset || 0) + older.length;
          renderCommentsList(state.commentsLoaded, older.length === 50);
        }
        return;
      }
      const btn = e.target.closest(".delete-comment-btn");
      if (!btn) return;
      e.stopPropagation();
      const commentId = parseInt(btn.getAttribute("data-comment-id"));
      if (!confirm("Удалить этот комментарий?")) return;
      haptic("impact");

      const res = await API.delete(`/api/admin/comments/${commentId}?user_id=${state.user.id}`);
      if (res) {
        const updatedComments = await API.get(`/api/news/${state.activePostForComments}/comments?limit=50&offset=0`);
        renderCommentsList(updatedComments || []);
        const post = state.news.find(p => p.id === state.activePostForComments);
        if (post) {
          post.comments_count = Math.max(0, (post.comments_count || 0) - 1);
          const countSpan = document.getElementById(`comment-count-${post.id}`);
          if (countSpan) countSpan.textContent = post.comments_count;
        }
      }
    });

    sendCommentBtn?.addEventListener("click", sendNewComment);

    newCommentInput?.addEventListener("keypress", (e) => {
      if (e.key === "Enter") {
        sendCommentBtn.click();
      }
    });

    // --------------------------------------------------------
    // Start Application
    // --------------------------------------------------------
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initUser);
    } else {
      initUser();
    }
  
        // --------------------------------------------------------
    // Dynamic Schedule Profile Selector (11А, 11В)
    // --------------------------------------------------------
    function renderScheduleProfileFilters() {
      const container = document.getElementById('schedule-profile-filter-container');
      if (!container) return;
      const targetClass = state.viewingClass || state.user.class_name || '11А';

      if (targetClass === '11А') {
        const profiles = [
          { id: 'all', label: 'Все' },
          { id: 'Соц-гум', label: 'Соц-гум' },
          { id: 'Филологический', label: 'Филологи' }
        ];
        container.style.display = 'flex';
        container.innerHTML = profiles.map(p => {
          const active = (state.selectedProfileFilter || 'all') === p.id;
          const cls = active 
            ? 'bg-ios-blue text-white shadow-xs font-semibold' 
            : 'bg-zinc-200/80 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-medium hover:bg-zinc-300 dark:hover:bg-zinc-700';
          return `<button data-gym-click="hdbc8d941da69" data-gym-args="${encodeURIComponent(JSON.stringify([(p.id)]))}" class="px-2.5 py-1 rounded-lg text-xs transition-all active-press ${cls}">${p.label}</button>`;
        }).join('');
      } else if (targetClass === '11В') {
        const profiles = [
          { id: 'all', label: 'Все' },
          { id: 'Инфотех', label: 'Инфотех' },
          { id: 'Инженерный', label: 'Инженеры' }
        ];
        container.style.display = 'flex';
        container.innerHTML = profiles.map(p => {
          const active = (state.selectedProfileFilter || 'all') === p.id;
          const cls = active 
            ? 'bg-ios-blue text-white shadow-xs font-semibold' 
            : 'bg-zinc-200/80 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-medium hover:bg-zinc-300 dark:hover:bg-zinc-700';
          return `<button data-gym-click="hdbc8d941da69" data-gym-args="${encodeURIComponent(JSON.stringify([(p.id)]))}" class="px-2.5 py-1 rounded-lg text-xs transition-all active-press ${cls}">${p.label}</button>`;
        }).join('');
      } else {
        container.style.display = 'none';
        container.innerHTML = '';
        state.selectedProfileFilter = 'all';
      }
    }

    function setScheduleProfileFilter(filterId) {
      state.selectedProfileFilter = filterId;
      renderScheduleProfileFilters();
      loadSchedule();
    }

    // --------------------------------------------------------
    // EGE (ЕГЭ) Preparation Functions & Official FIPI Topics
    // --------------------------------------------------------
    const FIPI_TOPICS = {
  "russian": {
    "1": "Подбор слова и смысловая связь предложений",
    "2": "Лексическое значение слова в контексте",
    "3": "Стилистический анализ текста",
    "4": "Орфоэпические нормы и ударение",
    "5": "Паронимы",
    "6": "Лексические нормы и речевая избыточность",
    "7": "Морфологические нормы",
    "8": "Грамматические ошибки в предложении",
    "9": "Гласные в корне",
    "10": "Приставки и Ы/И после приставок",
    "11": "Суффиксы",
    "12": "Окончания глаголов и суффиксы причастий",
    "13": "НЕ и НИ",
    "14": "Слитное, раздельное и дефисное написание",
    "15": "Н и НН",
    "16": "Однородные члены и сложносочинённые предложения",
    "17": "Обособленные члены предложения",
    "18": "Вводные слова и обращения",
    "19": "Сложноподчинённое предложение",
    "20": "Сложные предложения с разными видами связи",
    "21": "Пунктуационный анализ",
    "22": "Изобразительно-выразительные средства",
    "23": "Содержание исходного текста",
    "24": "Типы речи и логика текста",
    "25": "Лексический анализ текста",
    "26": "Средства связи предложений",
    "27": "Сочинение по исходному тексту"
  },
  "math": {
    "1": "Планиметрия",
    "2": "Векторы",
    "3": "Стереометрия: объёмы и площади",
    "4": "Классическая вероятность",
    "5": "Вероятность сложных событий",
    "6": "Случайные величины и математическое ожидание",
    "7": "Простейшие уравнения",
    "8": "Вычисления и преобразования",
    "9": "Производная и её графический смысл",
    "10": "Задачи с формулами и прикладными моделями",
    "11": "Текстовые задачи",
    "12": "Функции и графики",
    "13": "Текстовые задачи и личные финансы",
    "14": "Уравнения и отбор корней",
    "15": "Стереометрия: доказательство и вычисление",
    "16": "Неравенства",
    "17": "Моделирование и оптимизация",
    "18": "Планиметрия: доказательство и расчёт",
    "19": "Параметры",
    "20": "Числа, делимость и последовательности"
  }
};

    function setEgeSubject(subCode) {
      state.ege.activeSubject = subCode;
      state.ege.selectedTask = null;
      
      const rusBtn = document.getElementById('ege-sub-russian-btn');
      const mathBtn = document.getElementById('ege-sub-math-btn');
      const hint = document.getElementById('ege-task-count-hint');

      if (subCode === 'russian') {
        if (rusBtn) rusBtn.className = 'flex-1 py-2 rounded-xl transition-all text-center flex items-center justify-center gap-1.5 bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs';
        if (mathBtn) mathBtn.className = 'flex-1 py-2 rounded-xl transition-all text-center flex items-center justify-center gap-1.5 text-ios-secondaryText hover:text-zinc-900 dark:hover:text-white';
        if (hint) hint.textContent = 'Задания 1–27';
      } else {
        if (mathBtn) mathBtn.className = 'flex-1 py-2 rounded-xl transition-all text-center flex items-center justify-center gap-1.5 bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs';
        if (rusBtn) rusBtn.className = 'flex-1 py-2 rounded-xl transition-all text-center flex items-center justify-center gap-1.5 text-ios-secondaryText hover:text-zinc-900 dark:hover:text-white';
        if (hint) hint.textContent = 'Задания 1–20';
      }
      
      renderEgeTaskPills();
      loadEgeMaterials();
    }

    function renderEgeTaskPills() {
      const bar = document.getElementById('ege-task-pills-bar');
      if (!bar) return;
      const maxTasks = state.ege.activeSubject === 'russian' ? 27 : 20;
      
      let html = '';
      const allActive = state.ege.selectedTask === null;
      html += `<button data-gym-click="h6ea2beebfd00" class="px-3 py-1.5 rounded-xl text-xs font-semibold whitespace-nowrap transition-all active-press ${allActive ? 'bg-ios-blue text-white shadow-xs' : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200'}">Все</button>`;
      
      for (let i = 1; i <= maxTasks; i++) {
        const isActive = state.ege.selectedTask === i;
        html += `<button data-gym-click="h7784c30b2a1d" data-gym-args="${encodeURIComponent(JSON.stringify([(i)]))}" class="px-3 py-1.5 rounded-xl text-xs font-semibold whitespace-nowrap transition-all active-press ${isActive ? 'bg-ios-blue text-white shadow-xs' : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200'}">№${i}</button>`;
      }
      bar.innerHTML = html;
    }

    function setEgeTaskFilter(taskNum) {
      state.ege.selectedTask = taskNum;
      renderEgeTaskPills();
      loadEgeMaterials();
    }

    async function loadEgeMaterials() {
      const list = document.getElementById('ege-materials-list');
      if (!list) return;
      renderEgeTaskPills();

      try {
        const params = new URLSearchParams({
          subject_code: state.ege?.activeSubject || 'russian'
        });
        if (state.ege?.selectedTask) {
          params.append('task_number', state.ege.selectedTask);
        }

        const materials = await API.get(`/api/ege/materials?${params.toString()}`);
        state.ege.materials = materials || [];
        renderEgeMaterials(state.ege.materials);
      } catch (err) {
        state.ege.materials = [];
        renderEgeMaterials([]);
      }
    }

    function renderEgeMaterials(materials) {
      const list = document.getElementById('ege-materials-list');
      if (!list) return;

      const sub = state.ege.activeSubject || 'russian';
      const topics = FIPI_TOPICS[sub] || {};
      const maxTasks = sub === 'russian' ? 27 : 20;
      const isAdmin = checkCanEdit();

      // Case A: Specific task filter is selected (e.g. №4)
      if (state.ege.selectedTask !== null) {
        const taskNum = state.ege.selectedTask;
        const topicName = topics[taskNum] || `Задание №${taskNum}`;

        const topicBanner = `
          <div class="rounded-2xl p-4 bg-gradient-to-r from-blue-500/10 to-indigo-500/10 dark:from-blue-900/30 dark:to-indigo-900/30 border border-ios-blue/30 shadow-ios-sm space-y-1">
            <div class="flex items-center justify-between">
              <span class="px-2 py-0.5 rounded-md text-[10px] font-bold bg-ios-blue text-white uppercase tracking-wider">ЕГЭ-2027 • Задание №${taskNum}</span>
              ${isAdmin ? `<button data-gym-click="h2478096eb543" data-gym-args="${encodeURIComponent(JSON.stringify([(taskNum)]))}" class="text-xs font-semibold text-ios-blue active-press hover:underline">+ Добавить материал</button>` : ''}
            </div>
            <h3 class="text-sm font-bold text-zinc-900 dark:text-white pt-1 leading-snug">${topicName}</h3>
          </div>
        `;

        if (!materials || materials.length === 0) {
          list.innerHTML = `
            ${topicBanner}
            <div class="rounded-3xl p-6 bg-white dark:bg-ios-cardDark border border-zinc-200/60 dark:border-zinc-800/80 shadow-ios-card text-center space-y-2.5 mt-3">
              <div class="w-12 h-12 rounded-2xl bg-zinc-100 dark:bg-ios-cardDark2 text-zinc-400 mx-auto flex items-center justify-center text-xl">📝</div>
              <h4 class="text-sm font-bold text-zinc-800 dark:text-zinc-200">Материалы пока не добавлены</h4>
              <p class="text-xs text-ios-secondaryText max-w-xs mx-auto">Справочные материалы и шпаргалки по этой теме скоро появятся.</p>
              ${isAdmin ? `<button data-gym-click="h2478096eb543" data-gym-args="${encodeURIComponent(JSON.stringify([(taskNum)]))}" class="mt-2 inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-ios-blue text-white text-xs font-semibold active-press shadow-xs">+ Добавить материал</button>` : ''}
            </div>
          `;
          return;
        }

        list.innerHTML = topicBanner + materials.map(m => renderSingleEgeMaterialCard(m, isAdmin)).join('');
        return;
      }

      // Case B: "All" tasks view
      if (!materials || materials.length === 0) {
        let catalogHtml = `
          <div class="rounded-2xl p-3 bg-zinc-100 dark:bg-ios-cardDark2/80 border border-zinc-200/50 dark:border-zinc-800 text-xs text-ios-secondaryText mb-2 flex items-center justify-between">
            <span>Каталог заданий ФИПИ (${sub === 'russian' ? '27 заданий' : '20 заданий'})</span>
            ${isAdmin ? `<button data-gym-click="he6ecc958da39" class="text-xs font-bold text-ios-blue active-press">+ Добавить материал</button>` : ''}
          </div>
          <div class="space-y-2">
        `;

        for (let i = 1; i <= maxTasks; i++) {
          const tName = topics[i] || `Задание №${i}`;
          catalogHtml += `
            <div class="rounded-2xl p-3 bg-white dark:bg-ios-cardDark border border-zinc-200/60 dark:border-zinc-800/80 shadow-ios-sm flex items-center justify-between gap-3 active-press cursor-pointer hover:border-ios-blue/40" data-gym-click="h7784c30b2a1d" data-gym-args="${encodeURIComponent(JSON.stringify([(i)]))}">
              <div class="flex items-center gap-2.5 min-w-0">
                <span class="w-8 h-8 rounded-xl bg-blue-50 text-ios-blue dark:bg-blue-950/80 dark:text-blue-300 font-bold text-xs flex items-center justify-center border border-blue-200/50 dark:border-blue-900/50 flex-shrink-0">
                  ${i}
                </span>
                <div class="min-w-0">
                  <div class="text-xs font-bold text-zinc-900 dark:text-white truncate">${tName}</div>
                  <div class="text-[10px] text-ios-secondaryText mt-0.5">ФИПИ • Нажмите для просмотра</div>
                </div>
              </div>
              <div class="flex items-center gap-1.5 flex-shrink-0">
                ${isAdmin ? `<button data-gym-click="h9bbaf1417938" data-gym-args="${encodeURIComponent(JSON.stringify([(i)]))}" class="text-xs font-semibold px-2.5 py-1 rounded-lg bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 text-ios-blue">+ Добавить</button>` : `<span class="text-zinc-400 text-sm">›</span>`}
              </div>
            </div>
          `;
        }
        catalogHtml += `</div>`;
        list.innerHTML = catalogHtml;
        return;
      }

      list.innerHTML = materials.map(m => renderSingleEgeMaterialCard(m, isAdmin)).join('');
    }

    function renderSingleEgeMaterialCard(m, isAdmin) {
      const sub = state.ege.activeSubject || 'russian';
      const topics = FIPI_TOPICS[sub] || {};
      const topicName = topics[m.task_number] ? ` • ${topics[m.task_number]}` : '';

      const adminControls = isAdmin ? `
        <div class="flex items-center space-x-1.5 ml-auto">
          <button data-gym-click="h3cf4d54089af" data-gym-args="${encodeURIComponent(JSON.stringify([(m.id)]))}" class="px-2 py-1 rounded-lg bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-300 text-xs font-medium active-press flex items-center gap-1">
            <span>✏️</span><span class="hidden sm:inline">Изменить</span>
          </button>
          <button data-gym-click="h209689dcfebc" data-gym-args="${encodeURIComponent(JSON.stringify([(m.id)]))}" class="px-2 py-1 rounded-lg bg-red-50 hover:bg-red-100 dark:bg-red-950/60 text-red-600 dark:text-red-400 text-xs font-medium active-press flex items-center gap-1">
            <span>🗑</span><span class="hidden sm:inline">Удалить</span>
          </button>
        </div>
      ` : '';

      const materialImageUrl = safeImageUrl(m.image_url);
      const linkUrl = safeHttpsUrl(m.link_url);
      const imageHtml = materialImageUrl ? `
        <div class="mt-3 rounded-2xl overflow-hidden border border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/30">
          <img ${window.protectedImageAttrs(materialImageUrl)} data-image-url="${escapeHtml(materialImageUrl)}" alt="Схема / таблица" class="safe-image-open w-full h-auto rounded-2xl block object-contain cursor-pointer shadow-xs" loading="lazy">
        </div>
      ` : '';

      const linkHtml = linkUrl ? `
        <div class="mt-2.5 pt-2 border-t border-zinc-100 dark:border-zinc-800/80">
          <a href="${escapeHtml(linkUrl)}" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1.5 text-xs text-ios-blue font-semibold hover:underline">
            <span>🔗 Источник / Разбор</span>
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
          </a>
        </div>
      ` : '';

      const formattedTheory = m.theory
        .split('\n')
        .map(line => {
          line = line.trim();
          if (!line) return '<div class="h-1.5"></div>';
          if (line.startsWith('📌') || line.startsWith('•') || line.startsWith('-')) {
            return `<div class="text-xs leading-relaxed font-medium pl-1 text-zinc-800 dark:text-zinc-200">${escapeHtml(line)}</div>`;
          }
          return `<p class="text-xs leading-relaxed text-zinc-700 dark:text-zinc-300">${escapeHtml(line)}</p>`;
        })
        .join('');

      return `
        <article class="rounded-3xl p-5 bg-white dark:bg-ios-cardDark border border-zinc-200/60 dark:border-zinc-800/80 shadow-ios-card space-y-2.5">
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <span class="px-2.5 py-1 rounded-xl text-xs font-bold bg-blue-50 text-ios-blue dark:bg-blue-950/80 dark:text-blue-300 border border-blue-200/50 dark:border-blue-900/50">
                Задание №${m.task_number}
              </span>
              <span class="text-[11px] text-ios-secondaryText">${escapeHtml(m.created_at || '')}</span>
            </div>
            ${adminControls}
          </div>

          <div>
            <h3 class="text-base font-bold text-zinc-900 dark:text-white leading-snug">${escapeHtml(m.title)}</h3>
            ${topicName ? `<div class="text-[11px] text-ios-secondaryText mt-0.5">${topicName}</div>` : ''}
          </div>
          
          <div class="bg-zinc-50/80 dark:bg-zinc-900/40 p-3.5 rounded-2xl border border-zinc-100 dark:border-zinc-800/60 space-y-1 font-sans">
            <details class="school-theory" ${state.ege.selectedTask ? "open" : ""}><summary>Теория и пример решения</summary><div>${formattedTheory}</div></details>
          </div>

          ${imageHtml}
          ${linkHtml}
        </article>
      `;
    }

    function openAddEgeModal(taskNum = null) {
      document.getElementById('ege-modal-title').innerHTML = '<span>📚</span> Добавить материал ЕГЭ';
      document.getElementById('ege-edit-id').value = '';
      const sub = state.ege.activeSubject || 'russian';
      document.getElementById('ege-form-subject').value = sub;
      const tNum = taskNum || state.ege.selectedTask || '';
      document.getElementById('ege-form-task-num').value = tNum;
      if (tNum && FIPI_TOPICS[sub]?.[tNum]) {
        document.getElementById('ege-form-title').value = FIPI_TOPICS[sub][tNum];
      } else {
        document.getElementById('ege-form-title').value = '';
      }
      document.getElementById('ege-form-theory').value = '';
      document.getElementById('ege-form-image-url').value = '';
      document.getElementById('ege-form-link').value = '';
      document.getElementById('ege-form-file').value = '';
      document.getElementById('ege-material-modal').classList.remove('hidden');
    }

    function openEditEgeModal(id) {
      const mat = state.ege.materials.find(m => m.id === id);
      if (!mat) return;
      document.getElementById('ege-modal-title').innerHTML = '<span>✏️</span> Редактировать материал';
      document.getElementById('ege-edit-id').value = mat.id;
      document.getElementById('ege-form-subject').value = mat.subject_code;
      document.getElementById('ege-form-task-num').value = mat.task_number;
      document.getElementById('ege-form-title').value = mat.title;
      document.getElementById('ege-form-theory').value = mat.theory;
      document.getElementById('ege-form-image-url').value = mat.image_url || '';
      document.getElementById('ege-form-link').value = mat.link_url || '';
      document.getElementById('ege-form-file').value = '';
      document.getElementById('ege-material-modal').classList.remove('hidden');
    }

    function closeEgeModal() {
      document.getElementById('ege-material-modal').classList.add('hidden');
    }

    async function deleteEgeMaterial(id) {
      if (!confirm('Вы уверены, что хотите удалить этот справочный материал?')) return;
      try {
        await API.delete(`/api/ege/materials/${id}?admin_id=${state.user.id}`);
        await loadEgeMaterials();
      } catch (e) {
        alert('Не удалось удалить: ' + e.message);
      }
    }

    async function handleSaveEgeMaterial(e) {
      e.preventDefault();
      const editId = document.getElementById('ege-edit-id').value;
      const subject = document.getElementById('ege-form-subject').value;
      const taskNum = parseInt(document.getElementById('ege-form-task-num').value, 10);
      const title = document.getElementById('ege-form-title').value.trim();
      const theory = document.getElementById('ege-form-theory').value.trim();
      const link = document.getElementById('ege-form-link').value.trim();
      let imageUrl = document.getElementById('ege-form-image-url').value;

      const fileInput = document.getElementById('ege-form-file');
      if (fileInput && fileInput.files && fileInput.files.length > 0) {
        try {
          const upRes = await API.upload(fileInput.files[0]);
          if (upRes && upRes.url) imageUrl = upRes.url;
        } catch (err) {
          alert('Ошибка загрузки фото: ' + err.message);
          return;
        }
      }

      const payload = {
        subject_code: subject,
        task_number: taskNum,
        title: title,
        theory: theory,
        image_url: imageUrl || null,
        link_url: link || null,
        admin_id: state.user.id
      };

      try {
        if (editId) {
          await API.put(`/api/ege/materials/${editId}`, payload);
        } else {
          await API.post('/api/ege/materials', payload);
        }
        closeEgeModal();
        await loadEgeMaterials();
      } catch (err) {
        alert('Ошибка сохранения материала: ' + err.message);
      }
    }

    // --------------------------------------------------------
    // Global Window Function Exports
    // --------------------------------------------------------
    window.selectDay = selectDay;
    window.switchTab = switchTab;
    window.renderScheduleProfileFilters = renderScheduleProfileFilters;
    window.setScheduleProfileFilter = setScheduleProfileFilter;
    window.setEgeSubject = setEgeSubject;
    window.setEgeTaskFilter = setEgeTaskFilter;
    window.openAddEgeModal = openAddEgeModal;
    window.openEditEgeModal = openEditEgeModal;
    window.closeEgeModal = closeEgeModal;
    window.deleteEgeMaterial = deleteEgeMaterial;
    window.handleSaveEgeMaterial = handleSaveEgeMaterial;
    window.openOnboardingModal = openOnboardingModal;
    window.closeOnboardingModal = closeOnboardingModal;
    window.openProposeNewsModal = openProposeNewsModal;
    window.closeProposeNewsModal = closeProposeNewsModal;
    window.openModerationModal = openModerationModal;
    window.closeModerationModal = closeModerationModal;
    function contactDeveloper() {
      haptic("selection");
      const url = "https://t.me/kvalx";
      if (window.Telegram?.WebApp?.openTelegramLink) {
        window.Telegram.WebApp.openTelegramLink(url);
      } else {
        window.open(url, "_blank");
      }
    }
    window.contactDeveloper = contactDeveloper;

    window.handleModeratePost = handleModeratePost;
    window.togglePostReaction = togglePostReaction;
    window.handleDeleteNewsPost = handleDeleteNewsPost;
    window.openCommentsSheet = openCommentsSheet;
    window.closeCommentsSheet = closeCommentsSheet;
    window.sendNewComment = sendNewComment;
    window.openEditModal = openEditModal;
    window.closeEditModal = closeEditModal;
    window.saveEditPost = saveEditPost;
    window.openViewClassModal = openViewClassModal;
    window.closeViewClassModal = closeViewClassModal;
    
