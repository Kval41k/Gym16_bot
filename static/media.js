/* Private images use the same Telegram proof as JSON requests, never URL tokens. */
(() => {
  const placeholder = 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';
  const cache = new Map();
  const pending = new Map();
  const escape = value => String(value).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  function publicImage(value) {
    try {
      const url=new URL(value,location.origin);
      return url.protocol==='https:' && !url.username && !url.password &&
        (url.hostname==='t.me'||url.hostname.endsWith('.telegram.org')) ? url.href : '';
    } catch {return '';}
  }
  function privatePath(value) {
    try {
      const url = new URL(value, location.origin);
      return url.origin === location.origin && /^\/(uploads\/|api\/media\/)/.test(url.pathname) ? url.pathname : null;
    } catch (_) { return null; }
  }
  async function imageBlob(path) {
    if (cache.has(path)) return cache.get(path);
    if (pending.has(path)) return pending.get(path);
    const task = (async () => {
      const response = await fetch(path, {headers:{'X-Telegram-Init-Data':window.Telegram?.WebApp?.initData || ''},cache:'no-store'});
      if (!response.ok) throw new Error('Изображение недоступно');
      const blob = await response.blob();
      if (!blob.type.startsWith('image/') || blob.size > 10 * 1024 * 1024) throw new Error('Некорректное изображение');
      const url = URL.createObjectURL(blob);
      cache.set(path, url);
      if (cache.size > 24) { const first = cache.keys().next().value; URL.revokeObjectURL(cache.get(first)); cache.delete(first); }
      return url;
    })();
    pending.set(path, task);
    try { return await task; } finally { pending.delete(path); }
  }
  function hydrate(image) {
    const path = image.dataset.protectedSrc;
    if (!path || image.dataset.protectedLoading === path || image.dataset.protectedLoaded === path) return;
    image.dataset.protectedLoading = path;
    imageBlob(path).then(url => {
      if (image.dataset.protectedSrc === path) { image.dataset.protectedLoaded = path; image.src = url; }
    }).catch(() => { if (image.dataset.protectedSrc === path) image.alt = 'Не удалось загрузить изображение'; })
      .finally(() => { delete image.dataset.protectedLoading; });
  }
  window.protectedImageAttrs = value => {
    const path = privatePath(value);
    return path ? `src="${placeholder}" data-protected-src="${escape(path)}"` : `src="${escape(publicImage(value))}"`;
  };
  window.setProtectedImage = (image, value) => {
    if (!image) return;
    delete image.dataset.protectedLoaded;
    const path = privatePath(value);
    if (path) { image.dataset.protectedSrc = path; image.src = placeholder; hydrate(image); }
    else { delete image.dataset.protectedSrc; image.src = publicImage(value); }
  };
  function scan(node) {
    if (node.nodeType !== 1) return;
    if (node.matches('img[data-protected-src]')) hydrate(node);
    node.querySelectorAll?.('img[data-protected-src]').forEach(hydrate);
  }
  document.addEventListener('DOMContentLoaded', () => {
    scan(document.documentElement);
    new MutationObserver(records => records.forEach(record => {
      if (record.type === 'attributes') hydrate(record.target);
      else record.addedNodes.forEach(scan);
    })).observe(document.body, {subtree:true,childList:true,attributes:true,attributeFilter:['data-protected-src']});
  });
  window.addEventListener('pagehide', () => { cache.forEach(url => URL.revokeObjectURL(url)); cache.clear(); });
})();
