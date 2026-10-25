/* Applied before the first frame; only the user's colour preference is cached. */
(() => {
  const app = window.Telegram?.WebApp;
  const storageKey = `gym16-theme:${app?.initDataUnsafe?.user?.id || 'guest'}`;
  const allowed = new Set(['auto', 'light', 'dark']);
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let mode = 'auto';
  try { const saved = localStorage.getItem(storageKey); if (allowed.has(saved)) mode = saved; } catch (_) {}
  const validColour = value => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value);
  function luminance(hex) {
    const rgb = hex.slice(1).match(/../g).map(value => parseInt(value, 16) / 255)
      .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
    return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
  }
  function buttonText(background, preferred) {
    const light = luminance(background);
    const contrast = colour => { const other = luminance(colour); return (Math.max(light, other) + 0.05) / (Math.min(light, other) + 0.05); };
    if (validColour(preferred) && contrast(preferred) >= 4.5) return preferred;
    return contrast('#000000') > contrast('#ffffff') ? '#000000' : '#ffffff';
  }
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
      '--g-line': params.section_separator_color, '--g-blue': params.button_color,
      '--g-button-text': validColour(params.button_color) ? buttonText(params.button_color, params.button_text_color) : undefined};
    Object.entries(colours).forEach(([key, value]) => {
      if (validColour(value)) root.style.setProperty(key, value);
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
