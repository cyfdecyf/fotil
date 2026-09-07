(() => {
  'use strict';

  // Reactive UI state lives in the Alpine store `ui` (registered below):
  // templates bind to it and repaint themselves. This file keeps the
  // imperative behaviour — keyboard dispatch, navigation math, dialog
  // plumbing and the htmx glue. The store stays the source of truth; the two
  // per-card classes (selected/cursor) are the one exception, written
  // imperatively so a keypress or hover costs O(1) DOM work instead of
  // re-running an Alpine effect on every loaded card.
  const $ = (sel) => document.querySelector(sel);

  // Card index cache: rebuilt on boot and after every grid swap, so keyboard
  // navigation never re-queries the whole document. cardPaths follows DOM
  // order; cardEls maps path -> <figure>.
  let cardPaths = [];
  let cardEls = new Map();

  function rebuildCardIndex() {
    const cards = document.querySelectorAll('.photo-card');
    cardPaths = Array.from(cards, (c) => c.dataset.picPath);
    cardEls = new Map(Array.from(cards, (c) => [c.dataset.picPath, c]));
  }

  const gridPaths = () => cardPaths;

  const hasMore = () => !!document.getElementById('load-more');

  // Mirror the grid totals into the store so lightbox bindings that show
  // them stay reactive. Called after Alpine is up wherever the card index
  // was (re)built; the boot-time rebuild is picked up by the alpine:init
  // seeding below.
  function syncGridTotals() {
    const st = ui();
    if (!st) return;
    st.cardTotal = cardPaths.length;
    st.gridHasMore = hasMore();
  }

  // Registered on `alpine:init`; app.js loads before alpine.min.js (both
  // deferred) so the listener is in place before Alpine boots. Seeding
  // library/dir here (rather than in boot) means the tree-link bindings are
  // already correct on first paint.
  document.addEventListener('alpine:init', () => {
    Alpine.store('ui', {
      library: '',
      dir: '',
      selectMode: false,
      // Selected pic paths relative to pic_dir; survives pagination and
      // directory navigation, cleared after a cleanup.
      selected: new Set(),
      // Grid cursor: the picture keyboard ops (d/u, arrows, space) act on.
      // Follows the mouse hover and moves with the arrow keys.
      cursorPath: null,
      // Lightbox: current picture path and its index in the loaded card
      // list. The 1:1 zoom stays imperative (see setZoom).
      lbPath: null,
      lbIndex: 0,
      // EXIF segments for the lightbox picture, fetched from /exif and
      // filled in by showInLightbox; null while loading or unavailable.
      lbExif: null,
      // Grid totals, mirrored here because Alpine cannot track the live DOM
      // that gridPaths()/hasMore() read. Refreshed wherever the card index
      // is rebuilt, so lbPos/lbAtEnd recompute after every grid swap even
      // when lbIndex itself is unchanged.
      cardTotal: 0,
      gridHasMore: false,

      has(p) {
        return p != null && this.selected.has(p);
      },
      unmark(p) {
        this.selected.delete(p);
      },
      picUrl(p) {
        return `/image?library=${encodeURIComponent(this.library)}&path=${encodeURIComponent(p)}&size=large`;
      },
      // lbPos/lbAtEnd read the reactive cardTotal/gridHasMore mirrors above;
      // reading the live DOM directly would leave their bindings stale after
      // a grid swap that does not move lbIndex.
      lbPos() {
        return `${this.lbIndex + 1} / ${this.cardTotal}${this.gridHasMore ? '+' : ''}`;
      },
      lbAtStart() {
        return this.lbIndex <= 0;
      },
      lbAtEnd() {
        return this.lbIndex >= this.cardTotal - 1 && !this.gridHasMore;
      },
    });
    const grid = $('#grid-root');
    if (grid) {
      const st = Alpine.store('ui');
      st.library = grid.dataset.library;
      st.dir = grid.dataset.dir;
      syncGridTotals();
    }
  });

  const ui = () => Alpine.store('ui');

  // ---- Theme --------------------------------------------------------------

  const themePref = () => localStorage.getItem('fotil-theme') || 'auto';

  function applyTheme(pref) {
    const dark =
      pref === 'dark' ||
      (pref === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.classList.toggle('dark', dark);
    document.querySelectorAll('#theme-seg button').forEach((b) => {
      b.classList.toggle('seg-on', b.dataset.theme === pref);
    });
  }

  // ---- Grid cursor --------------------------------------------------------

  // The cursor ring is managed imperatively: remember the previous cursor
  // card so a move only touches two classLists instead of every card. The
  // store copy stays in sync — d/u, the lightbox badge and the return
  // target on close all read cursorPath. cursorEl may go stale across an
  // htmx swap; the afterSwap replay below re-derives it from cardEls.
  let cursorEl = null;

  function setCursor(path, { scroll = true } = {}) {
    if (cursorEl) cursorEl.classList.remove('cursor');
    cursorEl = path ? cardEls.get(path) || null : null;
    cursorEl?.classList.add('cursor');
    ui().cursorPath = path;
    if (cursorEl && scroll) cursorEl.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  function gridColumns() {
    const grid = document.getElementById('photo-grid');
    if (!grid) return 1;
    return getComputedStyle(grid).gridTemplateColumns.split(' ').length || 1;
  }

  // One screen of pictures: visible rows times columns.
  function pageDelta() {
    const cols = gridColumns();
    const card = document.querySelector('.photo-card');
    const main = document.getElementById('main');
    if (!card || !main) return cols;
    const rowHeight = card.getBoundingClientRect().height + 12;
    return cols * Math.max(1, Math.floor(main.clientHeight / rowHeight));
  }

  // Move the cursor by delta pictures, pulling in the next chunk when the
  // movement crosses the loaded end.
  async function navGrid(delta) {
    let paths = gridPaths();
    if (paths.length === 0) return;
    let idx = paths.indexOf(ui().cursorPath);
    if (idx === -1) {
      idx = delta < 0 ? paths.length - 1 : 0;
      setCursor(paths[idx]);
      return;
    }
    let target = idx + delta;
    if (target >= paths.length && hasMore()) {
      await loadMore();
      paths = gridPaths();
    }
    target = Math.max(0, Math.min(target, paths.length - 1));
    setCursor(paths[target]);
  }

  // Click the load-more button and resolve once new cards joined the grid.
  function loadMore() {
    return new Promise((resolve) => {
      const btn = document.getElementById('load-more');
      if (!btn) return resolve();
      const before = document.querySelectorAll('.photo-card').length;
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        document.body.removeEventListener('htmx:afterSwap', onSwap);
        resolve();
      };
      const onSwap = () => {
        if (document.querySelectorAll('.photo-card').length > before) finish();
      };
      document.body.addEventListener('htmx:afterSwap', onSwap);
      setTimeout(finish, 5000);
      btn.click();
    });
  }

  // ---- Lightbox -----------------------------------------------------------

  // Lightbox 1:1 zoom stays imperative: the scroll re-centering must run
  // right after the .zoomed layout change, and nothing else observes it.
  let zoomed = false;

  function setZoom(on) {
    zoomed = on;
    $('#lightbox-stage').classList.toggle('zoomed', on);
    if (on) {
      // Start centered on the picture.
      const sc = $('#lightbox-scroll');
      sc.scrollTop = (sc.scrollHeight - sc.clientHeight) / 2;
      sc.scrollLeft = (sc.scrollWidth - sc.clientWidth) / 2;
    }
  }

  // Display segments per path, cached across opens so flipping back and
  // forth does not refetch. Bounded by dropping everything once full: the
  // data is tiny and the server keeps its own per-file cache anyway.
  const exifCache = new Map();
  const EXIF_CACHE_MAX = 500;

  async function loadExif(path) {
    let items = exifCache.get(path);
    if (items !== undefined) return items;
    items = [];
    try {
      const url = `/exif?library=${encodeURIComponent(ui().library)}&path=${encodeURIComponent(path)}`;
      const resp = await fetch(url);
      if (resp.ok) {
        const data = await resp.json();
        if (Array.isArray(data.exif)) items = data.exif;
      }
    } catch {
      // A failed fetch just leaves the EXIF line hidden.
    }
    if (exifCache.size >= EXIF_CACHE_MAX) exifCache.clear();
    exifCache.set(path, items);
    return items;
  }

  // Cross-fade picture swapping. The new picture decodes into the hidden
  // slot, then fades in over the outgoing one; a monotonically increasing
  // token discards results for pictures the user already flipped past.
  let lbVisible = null;
  let lbPending = null;
  let lbSwapToken = 0;
  let lbShownUrl = null;
  let lbSpinnerTimer = 0;

  const lbLayers = () => [lbVisible, lbPending];

  // Wait until the picture can be shown. A picture that is already in
  // cache resolves right away; a fetched one settles on load, with
  // decode() preferred so the fade never reveals a half-decoded frame.
  // decode() is best-effort only: some WebKit builds never settle it and
  // older engines lack it, so cap the wait and fade anyway.
  function lbWhenReady(img) {
    return new Promise((resolve, reject) => {
      const settle = (ok) => {
        img.removeEventListener('load', onLoad);
        img.removeEventListener('error', onError);
        ok ? resolve() : reject(new Error('picture failed to load'));
      };
      const onLoad = () => {
        if (!img.decode) return settle(true);
        let done = false;
        const finish = () => {
          if (done) return;
          done = true;
          settle(true);
        };
        img.decode().then(finish, finish);
        setTimeout(finish, 200);
      };
      const onError = () => settle(false);
      img.addEventListener('load', onLoad);
      img.addEventListener('error', onError);
      // A cached picture may already be complete; its events never fire.
      if (img.complete) img.naturalWidth > 0 ? settle(true) : onError();
    });
  }

  function setLightboxImage(url) {
    if (!url || url === lbShownUrl) return;
    lbShownUrl = url;
    const token = ++lbSwapToken;
    const layer = lbPending;
    layer.classList.add('lb-loading');
    layer.src = url;
    // Only surface the spinner when the fetch actually takes a while, so
    // swapping to a cached neighbour never flashes it.
    clearTimeout(lbSpinnerTimer);
    lbSpinnerTimer = setTimeout(
      () => $('#lightbox-loading').classList.remove('hidden'),
      400,
    );
    lbWhenReady(layer)
      .then(() => {
        if (token !== lbSwapToken) return;
        clearTimeout(lbSpinnerTimer);
        $('#lightbox-loading').classList.add('hidden');
        $('#lightbox-fallback').classList.add('hidden');
        // The slot has been sitting at opacity 0 with the transition
        // disabled since the load started, so restoring the transition and
        // fading in is safe without waiting for a style recalc. The
        // outgoing picture fades out underneath: contain-fit boxes do not
        // cover each other across aspect ratios, and a fully opaque
        // underlay would keep the previous picture visible on screen.
        layer.classList.remove('lb-loading', 'lb-under');
        layer.classList.add('lb-top');
        lbVisible.classList.remove('lb-top');
        lbVisible.classList.add('lb-under');
        [lbVisible, lbPending] = [lbPending, lbVisible];
      })
      .catch(() => {
        if (token !== lbSwapToken) return;
        clearTimeout(lbSpinnerTimer);
        $('#lightbox-loading').classList.add('hidden');
        for (const img of lbLayers()) img.classList.add('lb-loading');
        const fb = $('#lightbox-fallback');
        fb.textContent = `${(ui().lbPath || '').split('/').pop()}\n(无法显示)`;
        fb.classList.remove('hidden');
      });
  }

  // Drop decoded pictures and restore the initial slot roles, so reopening
  // the lightbox on another picture cannot flash the stale frame.
  function resetLightboxLayers() {
    lbSwapToken++;
    clearTimeout(lbSpinnerTimer);
    lbShownUrl = null;
    $('#lightbox-loading').classList.add('hidden');
    $('#lightbox-fallback').classList.add('hidden');
    lbVisible = $('#lightbox-img');
    lbPending = $('#lightbox-img-back');
    for (const img of lbLayers()) {
      img.removeAttribute('src');
      img.classList.remove('lb-loading', 'lb-under');
    }
    lbVisible.classList.add('lb-top');
    lbPending.classList.remove('lb-top');
  }

  // Point the lightbox at a path: store updates drive the template
  // bindings (name, exif line, counter, prev/next, mark badge); only the
  // picture swap, zoom reset, neighbour preloading and the EXIF fetch stay
  // imperative.
  function showInLightbox(path) {
    if (!path) return;
    ui().lbPath = path;
    ui().lbExif = exifCache.get(path) ?? null;
    setZoom(false);
    setLightboxImage(ui().picUrl(path));
    // Preload neighbours so flipping through feels instant.
    const paths = gridPaths();
    const idx = paths.indexOf(path);
    for (const i of [idx - 1, idx + 1]) {
      if (paths[i]) {
        new Image().src = ui().picUrl(paths[i]);
        loadExif(paths[i]);
      }
    }
    loadExif(path).then((items) => {
      // Drop the response if the user already moved on to another picture.
      if (ui().lbPath === path) ui().lbExif = items.length ? items : null;
    });
  }

  function openLightbox(path) {
    const paths = gridPaths();
    ui().lbIndex = Math.max(paths.indexOf(path), 0);
    showInLightbox(path);
    $('#lightbox').showModal();
  }

  async function navLightbox(delta) {
    const st = ui();
    let paths = gridPaths();
    if (delta > 0 && st.lbIndex + delta >= paths.length && hasMore()) {
      await loadMore();
      paths = gridPaths();
    }
    const idx = Math.max(0, Math.min(st.lbIndex + delta, paths.length - 1));
    st.lbIndex = idx;
    showInLightbox(paths[idx]);
  }

  // Close and land the grid cursor on the picture that was last viewed.
  // The dialog `close` event is unreliable in some WebViews, so every close
  // path goes through here.
  function closeLightbox() {
    const path = gridPaths()[ui().lbIndex];
    if (path) setCursor(path);
    setZoom(false);
    const dlg = $('#lightbox');
    if (dlg.open) dlg.close();
  }

  // ---- Selection ----------------------------------------------------------

  function applyMark(path, mark) {
    if (!path) return;
    // Ignore stale paths whose card no longer exists (e.g. after the grid
    // refresh following a cleanup).
    const card = cardEls.get(path);
    if (!card) return;
    if (mark) {
      ui().selected.add(path);
    } else {
      ui().selected.delete(path);
    }
    card.classList.toggle('selected', mark);
  }

  // Select every loaded picture, or clear the selection if all are selected.
  function toggleSelectAll() {
    const st = ui();
    const paths = gridPaths();
    if (paths.length === 0) return;
    const allSelected = paths.every((p) => st.selected.has(p));
    for (const p of paths) {
      if (allSelected) {
        st.selected.delete(p);
      } else {
        st.selected.add(p);
      }
      cardEls.get(p)?.classList.toggle('selected', !allSelected);
    }
  }

  // ---- Events -------------------------------------------------------------

  // Click delegation so cards added by later grid chunks work too.
  document.addEventListener('click', (e) => {
    if (e.target.closest('#help-button')) {
      $('#help-dialog').showModal();
      return;
    }
    if (e.target.closest('[data-close-result]')) {
      $('#cleanup-result').textContent = '';
      return;
    }
    const card = e.target.closest('.photo-card');
    if (card) {
      const st = ui();
      const path = card.dataset.picPath;
      if (st.selectMode) {
        applyMark(path, !st.has(path));
      } else {
        setCursor(path, { scroll: false });
        openLightbox(path);
      }
    }
  });

  // Mouse hover moves the grid cursor, so keyboard ops follow the mouse.
  document.addEventListener('mouseover', (e) => {
    const card = e.target.closest ? e.target.closest('.photo-card') : null;
    if (card && card.dataset.picPath !== ui().cursorPath) {
      setCursor(card.dataset.picPath, { scroll: false });
    }
  });

  const NAV_KEYS = [
    'ArrowLeft',
    'ArrowRight',
    'ArrowUp',
    'ArrowDown',
    'Home',
    'End',
    'PageUp',
    'PageDown',
    ' ',
    'Enter',
    'd',
    'u',
    'a',
    's',
    'f',
    'Escape',
    '?',
  ];

  document.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const tag = e.target && e.target.tagName;
    if (
      tag === 'INPUT' ||
      tag === 'TEXTAREA' ||
      tag === 'SELECT' ||
      e.target.isContentEditable
    ) {
      return;
    }
    if ($('#cleanup-dialog').open) return;
    // '?' toggles the cheat sheet even while it is open.
    if ($('#help-dialog').open) {
      if (e.key === '?') {
        e.preventDefault();
        $('#help-dialog').close();
      }
      return; // Esc closes natively.
    }
    if (!NAV_KEYS.includes(e.key)) return;
    e.preventDefault();
    const lightboxOpen = $('#lightbox').open;

    if (e.key === 'd' || e.key === 'u') {
      const st = ui();
      const path = lightboxOpen ? st.lbPath : st.cursorPath;
      applyMark(path, e.key === 'd');
      return;
    }
    if (e.key === 's') {
      ui().selectMode = !ui().selectMode;
      return;
    }
    if (e.key === '?') {
      $('#help-dialog').showModal();
      return;
    }

    if (lightboxOpen) {
      if (e.key === 'ArrowRight') navLightbox(1);
      else if (e.key === 'ArrowLeft') navLightbox(-1);
      else if (e.key === 'PageDown') navLightbox(pageDelta());
      else if (e.key === 'PageUp') navLightbox(-pageDelta());
      else if (e.key === 'End') navLightbox(gridPaths().length);
      else if (e.key === 'Home') navLightbox(-ui().lbIndex);
      // Up/down only move the grid cursor, so context is kept for the
      // return to the grid; left/right switch pictures.
      else if (e.key === 'ArrowDown') navGrid(gridColumns());
      else if (e.key === 'ArrowUp') navGrid(-gridColumns());
      else if (e.key === ' ' || e.key === 'Enter' || e.key === 'Escape') {
        closeLightbox();
      } else if (e.key === 'f') setZoom(!zoomed);
      return;
    }

    if (e.key === 'ArrowRight') navGrid(1);
    else if (e.key === 'ArrowLeft') navGrid(-1);
    else if (e.key === 'ArrowDown') navGrid(gridColumns());
    else if (e.key === 'ArrowUp') navGrid(-gridColumns());
    else if (e.key === 'PageDown') navGrid(pageDelta());
    else if (e.key === 'PageUp') navGrid(-pageDelta());
    else if (e.key === 'End') navGrid(gridPaths().length);
    else if (e.key === 'Home') navGrid(-gridPaths().length);
    else if (e.key === ' ' || e.key === 'Enter') {
      if (!ui().cursorPath && gridPaths().length) setCursor(gridPaths()[0]);
      if (ui().cursorPath) openLightbox(ui().cursorPath);
    } else if (e.key === 'a') {
      toggleSelectAll();
    } else if (e.key === 'f') {
      // No zoom outside the lightbox.
    }
  });

  // Placeholder for images the browser cannot render (e.g. .jxl, corrupt
  // files). HEIF files are transcoded server side and should not hit this.
  window.fotilPicError = (img) => {
    const fig = img.closest('.photo-card');
    if (!fig) return;
    fig.classList.add('broken');
    img.remove();
    const ph = document.createElement('div');
    ph.className =
      'w-full h-full flex items-center justify-center text-[var(--secondary)] text-xs p-2 text-center break-all';
    ph.textContent = `${fig.dataset.picPath.split('/').pop()}\n(无法显示)`;
    fig.prepend(ph);
  };

  // Tree toggles: the first click lets HTMX fetch the children, afterwards
  // the node just expands/collapses. Capture phase runs before HTMX.
  document.addEventListener(
    'click',
    (e) => {
      const toggle = e.target.closest('.tree-toggle');
      if (!toggle) return;
      const node = toggle.closest('.tree-node');
      if (toggle.dataset.loaded === 'true') {
        node.classList.toggle('open');
        e.stopPropagation();
      }
    },
    true,
  );

  document.body.addEventListener('htmx:afterSwap', (e) => {
    const target = e.detail ? e.detail.target : e.target;

    if (target.classList && target.classList.contains('tree-children')) {
      const node = target.closest('.tree-node');
      node.querySelector('.tree-toggle').dataset.loaded = 'true';
      node.classList.add('open');
      return;
    }

    // Grid content swapped in: pick up the new location, rebuild the card
    // index, then replay selected/cursor onto the fresh nodes (the old
    // Alpine per-card binding is gone). This listener is registered before
    // the temporary one loadMore() attaches, so the index is already fresh
    // when loadMore resolves. A cursor whose card vanished resets to null.
    const grid = $('#grid-root');
    if (grid) {
      const st = ui();
      st.library = grid.dataset.library;
      st.dir = grid.dataset.dir;
      rebuildCardIndex();
      syncGridTotals();
      for (const [path, el] of cardEls) {
        el.classList.toggle('selected', st.selected.has(path));
      }
      if (st.cursorPath && cardEls.has(st.cursorPath)) {
        cursorEl = cardEls.get(st.cursorPath);
        cursorEl.classList.add('cursor');
      } else {
        cursorEl = null;
        st.cursorPath = null;
      }
    }
  });

  document.body.addEventListener('htmx:afterRequest', (e) => {
    // afterRequest fires on the requesting button itself; detail.target is
    // the swap target instead.
    if (
      e.target &&
      e.target.id === 'cleanup-confirm' &&
      e.detail &&
      e.detail.successful
    ) {
      $('#cleanup-dialog').close();
      const st = ui();
      st.selected.clear();
      // Card classes are imperative now, so clearing the store must also
      // strip them (the grid-refresh swap below would replay them from the
      // already-cleared Set, but only after a round trip).
      for (const el of cardEls.values()) el.classList.remove('selected');
      setCursor(null, { scroll: false });
    }
  });

  // The cleanup response carries HX-Trigger to refresh the grid, since the
  // trashed files must disappear from it.
  document.body.addEventListener('grid-refresh', () => {
    const st = ui();
    htmx.ajax(
      'GET',
      `/grid?library=${encodeURIComponent(st.library)}&dir=${encodeURIComponent(st.dir)}&offset=0`,
      { target: '#main', swap: 'innerHTML' },
    );
  });

  function boot() {
    rebuildCardIndex();
    $('#library-select').addEventListener('change', (e) => {
      // Full reload so the whole page (tree, grid, header info) switches.
      const url = new URL(location.href);
      url.searchParams.set('library', e.target.value);
      url.searchParams.delete('dir');
      location.assign(url);
    });
    $('#selected-button').addEventListener('click', () => {
      $('#selected-dialog').showModal();
    });
    $('#selected-close').addEventListener('click', () => $('#selected-dialog').close());
    $('#cleanup-button').addEventListener('click', () => {
      if (ui().selected.size > 0) $('#cleanup-dialog').showModal();
    });
    $('#cleanup-cancel').addEventListener('click', () => $('#cleanup-dialog').close());

    document.querySelectorAll('#theme-seg button').forEach((b) => {
      b.addEventListener('click', () => {
        localStorage.setItem('fotil-theme', b.dataset.theme);
        applyTheme(b.dataset.theme);
      });
    });
    // Follow live system theme changes while in auto mode.
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      applyTheme(themePref());
    });
    applyTheme(themePref());

    $('#lightbox-close').addEventListener('click', closeLightbox);
    $('#lightbox-prev').addEventListener('click', () => navLightbox(-1));
    $('#lightbox-next').addEventListener('click', () => navLightbox(1));
    // Clicking the dark area around the picture closes the lightbox; the
    // picture itself toggles 1:1 zoom.
    $('#lightbox').addEventListener('click', (e) => {
      if (
        e.target.id === 'lightbox' ||
        e.target.id === 'lightbox-stage' ||
        e.target.id === 'lightbox-scroll'
      ) {
        closeLightbox();
      }
    });
    lbVisible = $('#lightbox-img');
    lbPending = $('#lightbox-img-back');
    // Either picture slot may be the visible one; clicking the picture
    // toggles 1:1 zoom.
    $('#lightbox-scroll').addEventListener('click', (e) => {
      if (e.target.tagName === 'IMG') setZoom(!zoomed);
    });
    // The `close` event does not fire in some WebViews; this is only a
    // safety net for close paths outside the ones handled explicitly.
    $('#lightbox').addEventListener('close', () => {
      setZoom(false);
      const path = gridPaths()[ui().lbIndex];
      if (path) setCursor(path);
      resetLightboxLayers();
    });

    $('#help-close').addEventListener('click', () => $('#help-dialog').close());
    $('#help-dialog').addEventListener('click', (e) => {
      if (e.target.id === 'help-dialog') $('#help-dialog').close();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
