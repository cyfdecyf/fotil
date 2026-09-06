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

      has(p) {
        return p != null && this.selected.has(p);
      },
      unmark(p) {
        this.selected.delete(p);
      },
      picUrl(p) {
        return `/image?library=${encodeURIComponent(this.library)}&path=${encodeURIComponent(p)}&size=large`;
      },
      // The next three read the live DOM for totals; they re-evaluate when
      // lbIndex changes, which covers every path that swaps grid content.
      lbPos() {
        return `${this.lbIndex + 1} / ${gridPaths().length}${hasMore() ? '+' : ''}`;
      },
      lbAtStart() {
        return this.lbIndex <= 0;
      },
      lbAtEnd() {
        return this.lbIndex >= gridPaths().length - 1 && !hasMore();
      },
    });
    const grid = $('#grid-root');
    if (grid) {
      const st = Alpine.store('ui');
      st.library = grid.dataset.library;
      st.dir = grid.dataset.dir;
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

  // Point the lightbox at a path: store updates drive the template
  // bindings (image src, name, counter, prev/next, mark badge); only the
  // zoom reset and neighbour preloading stay imperative.
  function showInLightbox(path) {
    if (!path) return;
    ui().lbPath = path;
    setZoom(false);
    // Preload neighbours so flipping through feels instant.
    const paths = gridPaths();
    const idx = paths.indexOf(path);
    for (const i of [idx - 1, idx + 1]) {
      if (paths[i]) {
        new Image().src = ui().picUrl(paths[i]);
      }
    }
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
      // Full reload so the whole page (tree, grid, trash path) switches.
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
    $('#lightbox-img').addEventListener('click', () => setZoom(!zoomed));
    const lbImg = $('#lightbox-img');
    lbImg.addEventListener('error', () => {
      lbImg.style.display = 'none';
      const fb = $('#lightbox-fallback');
      fb.textContent = `${(ui().lbPath || '').split('/').pop()}\n(无法显示)`;
      fb.classList.remove('hidden');
    });
    lbImg.addEventListener('load', () => {
      lbImg.style.display = '';
      $('#lightbox-fallback').classList.add('hidden');
    });
    // The `close` event does not fire in some WebViews; this is only a
    // safety net for close paths outside the ones handled explicitly.
    $('#lightbox').addEventListener('close', () => {
      setZoom(false);
      const path = gridPaths()[ui().lbIndex];
      if (path) setCursor(path);
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
