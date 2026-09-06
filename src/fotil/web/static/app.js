(() => {
  'use strict';

  // Current library/dir/mode, kept in sync from the grid partial's data
  // attrs and the header toggle.
  const state = { library: '', dir: '', selectMode: false };
  // Selected pic paths relative to pic_dir; survives pagination and
  // directory navigation, cleared after a cleanup.
  const selected = new Set();
  // Picture currently under the mouse cursor; the grid d/u keys apply to it.
  let hoveredPath = null;
  // Lightbox position within the currently loaded card list.
  let lightboxIndex = 0;

  const $ = (sel) => document.querySelector(sel);

  const picUrl = (path) =>
    `/image?library=${encodeURIComponent(state.library)}&path=${encodeURIComponent(path)}`;

  const gridPaths = () =>
    Array.from(document.querySelectorAll('.photo-card')).map((c) => c.dataset.picPath);

  const hasMore = () => !!document.getElementById('load-more');

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

  function updateSelectedUI() {
    $('#selected-count').textContent = selected.size;

    const holder = $('#cleanup-pics-inputs');
    holder.textContent = '';
    for (const p of selected) {
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'pics';
      input.value = p;
      holder.appendChild(input);
    }

    $('#cleanup-count').textContent = selected.size;
    $('#cleanup-button').disabled = selected.size === 0;

    document.querySelectorAll('[data-pic-path]').forEach((card) => {
      card.classList.toggle('selected', selected.has(card.dataset.picPath));
    });

    if ($('#selected-dialog').open) {
      renderSelectedPanel();
    }
  }

  function renderSelectedPanel() {
    const box = $('#selected-items');
    box.textContent = '';
    for (const p of selected) {
      const item = document.createElement('div');
      item.className = 'relative';

      const img = document.createElement('img');
      img.src = picUrl(p);
      img.className = 'w-full h-24 object-cover rounded';
      img.loading = 'lazy';

      const label = document.createElement('div');
      label.className = 'text-xs truncate mt-1';
      label.textContent = p.split('/').pop();

      const btn = document.createElement('button');
      btn.className =
        'absolute top-0 right-0 bg-[var(--danger)] text-white text-xs rounded-full w-5 h-5';
      btn.textContent = '×';
      btn.dataset.picPath = p;
      btn.dataset.unselect = '1';

      item.append(img, label, btn);
      box.appendChild(item);
    }
  }

  function applyMark(path, mark) {
    if (!path) return;
    // Ignore stale paths whose card no longer exists (e.g. after the grid
    // refresh following a cleanup).
    if (!document.querySelector(`.photo-card[data-pic-path="${CSS.escape(path)}"]`)) {
      return;
    }
    if (mark) {
      selected.add(path);
    } else {
      selected.delete(path);
    }
    updateSelectedUI();
    if ($('#lightbox').open) {
      updateLightboxMark();
    }
  }

  // ---- Lightbox -----------------------------------------------------------

  function openLightbox(path) {
    const paths = gridPaths();
    lightboxIndex = Math.max(paths.indexOf(path), 0);
    updateLightbox();
    $('#lightbox').showModal();
  }

  async function navLightbox(delta) {
    let paths = gridPaths();
    // Past the last loaded picture: pull in the next chunk and continue.
    if (lightboxIndex + delta >= paths.length && delta > 0 && hasMore()) {
      await loadMore();
      paths = gridPaths();
    }
    const idx = lightboxIndex + delta;
    if (idx < 0 || idx >= paths.length) return;
    lightboxIndex = idx;
    updateLightbox();
  }

  function updateLightbox() {
    const paths = gridPaths();
    const path = paths[lightboxIndex];
    if (!path) return;
    const img = $('#lightbox-img');
    if (img.dataset.path !== path) {
      img.dataset.path = path;
      img.src = picUrl(path);
    }
    $('#lightbox-name').textContent = path.split('/').pop();
    $('#lightbox-pos').textContent =
      `${lightboxIndex + 1} / ${paths.length}${hasMore() ? '+' : ''}`;
    $('#lightbox-prev').disabled = lightboxIndex <= 0;
    $('#lightbox-next').disabled = lightboxIndex >= paths.length - 1 && !hasMore();
    updateLightboxMark();
    // Preload neighbours so flipping through feels instant.
    for (const i of [lightboxIndex - 1, lightboxIndex + 1]) {
      if (paths[i]) {
        new Image().src = picUrl(paths[i]);
      }
    }
  }

  function updateLightboxMark() {
    const path = $('#lightbox-img').dataset.path;
    $('#lightbox-marked').classList.toggle('hidden', !selected.has(path));
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

  // ---- Events -------------------------------------------------------------

  // Click delegation so cards added by later grid chunks work too.
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-close-result]')) {
      $('#cleanup-result').textContent = '';
      return;
    }
    const unselect = e.target.closest('[data-unselect]');
    if (unselect) {
      selected.delete(unselect.dataset.picPath);
      updateSelectedUI();
      return;
    }
    const card = e.target.closest('.photo-card');
    if (card) {
      const path = card.dataset.picPath;
      if (state.selectMode) {
        applyMark(path, !selected.has(path));
      } else {
        openLightbox(path);
      }
    }
  });

  // Track the picture under the cursor for the grid d/u shortcuts.
  document.addEventListener('mouseover', (e) => {
    const card = e.target.closest ? e.target.closest('.photo-card') : null;
    hoveredPath = card ? card.dataset.picPath : null;
  });

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
    const lightboxOpen = $('#lightbox').open;

    if (e.key === 'd' || e.key === 'u') {
      e.preventDefault();
      if (lightboxOpen) {
        applyMark($('#lightbox-img').dataset.path, e.key === 'd');
      } else {
        applyMark(hoveredPath, e.key === 'd');
      }
    } else if (lightboxOpen && e.key === 'ArrowRight') {
      e.preventDefault();
      navLightbox(1);
    } else if (lightboxOpen && e.key === 'ArrowLeft') {
      e.preventDefault();
      navLightbox(-1);
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

    // Grid content swapped in: sync state, highlight the tree, restore marks.
    const grid = $('#grid-root');
    if (grid) {
      state.library = grid.dataset.library;
      state.dir = grid.dataset.dir;
      document.querySelectorAll('.tree-link').forEach((a) => {
        a.classList.toggle('active', a.dataset.dir === state.dir);
      });
      updateSelectedUI();
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
      selected.clear();
      updateSelectedUI();
    }
  });

  // The cleanup response carries HX-Trigger to refresh the grid, since the
  // trashed files must disappear from it.
  document.body.addEventListener('grid-refresh', () => {
    htmx.ajax(
      'GET',
      `/grid?library=${encodeURIComponent(state.library)}&dir=${encodeURIComponent(state.dir)}&offset=0`,
      { target: '#main', swap: 'innerHTML' },
    );
  });

  function boot() {
    const grid = $('#grid-root');
    if (grid) {
      state.library = grid.dataset.library;
      state.dir = grid.dataset.dir;
      document.querySelectorAll('.tree-link').forEach((a) => {
        a.classList.toggle('active', a.dataset.dir === state.dir);
      });
    }
    $('#library-select').addEventListener('change', (e) => {
      // Full reload so the whole page (tree, grid, trash path) switches.
      const url = new URL(location.href);
      url.searchParams.set('library', e.target.value);
      url.searchParams.delete('dir');
      location.assign(url);
    });
    $('#select-mode-button').addEventListener('click', () => {
      state.selectMode = !state.selectMode;
      $('#select-mode-button').classList.toggle('tinted', state.selectMode);
      $('#select-mode-button').setAttribute('aria-pressed', String(state.selectMode));
    });
    $('#selected-button').addEventListener('click', () => {
      renderSelectedPanel();
      $('#selected-dialog').showModal();
    });
    $('#selected-close').addEventListener('click', () => $('#selected-dialog').close());
    $('#cleanup-button').addEventListener('click', () => {
      if (selected.size > 0) $('#cleanup-dialog').showModal();
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

    $('#lightbox-close').addEventListener('click', () => $('#lightbox').close());
    $('#lightbox-prev').addEventListener('click', () => navLightbox(-1));
    $('#lightbox-next').addEventListener('click', () => navLightbox(1));
    // Clicking the dark area around the picture closes the lightbox.
    $('#lightbox').addEventListener('click', (e) => {
      if (e.target.id === 'lightbox' || e.target.id === 'lightbox-stage') {
        $('#lightbox').close();
      }
    });
    const lbImg = $('#lightbox-img');
    lbImg.addEventListener('error', () => {
      lbImg.style.display = 'none';
      const fb = $('#lightbox-fallback');
      fb.textContent = `${lbImg.dataset.path.split('/').pop()}\n(无法显示)`;
      fb.classList.remove('hidden');
    });
    lbImg.addEventListener('load', () => {
      lbImg.style.display = '';
      $('#lightbox-fallback').classList.add('hidden');
    });

    updateSelectedUI();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
