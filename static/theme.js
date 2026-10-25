/* Applied before the first frame; only the user's colour preference is cached. */
(() => {
  const app = window.Telegram?.WebApp;
  const storageKey = `gym16-theme:${app?.initDataUnsafe?.user?.id || 'guest'}`;
  const allowed = new Set(['auto', 'light', 'dark']);
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let mode = 'auto';
  try { const saved = localStorage.getItem(storageKey); if (allowed.has(saved)) mode = saved; } catch (_) {}
  function apply() {
    const telegram = Boolean(app?.initData);
    const dark = mode === 'dark' || (mode === 'auto' && (telegram ? app.colorScheme === 'dark' : system.matches));
    const root = document.documentElement;
    root.classList.toggle('dark', dark);
    root.dataset.themeMode = mode;
    root.style.colorScheme = dark ? 'dark' : 'light';
    const params = mode === 'auto' && telegram ? app.themeParams || {} : {};
    const colours = {'--g-bg': params.bg_color, '--g-card': params.section_bg_color || params.secondary_bg_color,
      '--g-soft': params.secondary_bg_color, '--g-text': params.text_color, '--g-muted': params.hint_color,
      '--g-line': params.section_separator_color, '--g-blue': params.button_color};
    Object.entries(colours).forEach(([key, value]) => {
      if (typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value)) root.style.setProperty(key, value);
      else root.style.removeProperty(key);
    });
    const background = params.bg_color && /^#[0-9a-f]{6}$/i.test(params.bg_color) ? params.bg_color : dark ? '#111216' : '#F2F2F7';
    try { if (app?.isVersionAtLeast?.('6.1')) app.setBackgroundColor(background); } catch (_) {}
    try { if (app?.isVersionAtLeast?.('6.9')) app.setHeaderColor(background); } catch (_) {}
    try { if (app?.isVersionAtLeast?.('7.10')) app.setBottomBarColor(background); } catch (_) {}
    window.dispatchEvent(new CustomEvent('gym16-theme-applied', {detail: {mode, dark}}));
  }
  window.GymTheme = {
    getMode: () => mode,
    setMode(value) { if (!allowed.has(value)) return; mode = value; try { localStorage.setItem(storageKey, value); } catch (_) {} apply(); },
    apply
  };
  app?.onEvent?.('themeChanged', apply);
  if (system.addEventListener) system.addEventListener('change', apply);
  else system.addListener?.(apply);
  apply();
})();
