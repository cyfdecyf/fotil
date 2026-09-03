(() => {
  'use strict';

  // Current library/dir, kept in sync from the grid partial's data attrs.
  const state = { library: '', dir: '' };
  // Selected pic paths relative to pic_dir; survives pagination and
  // directory navigation, cleared after a cleanup.
  const selected = new Set();

  const $ = (sel) => document.querySelector(sel);

  const picUrl = (path) =>
    `/image?library=${encodeURIComponent(state.library)}&path=${encodeURIComponent(path)}`;

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
        'absolute top-0 right-0 bg-red-600 text-white text-xs rounded-full w-5 h-5';
      btn.textContent = '×';
      btn.dataset.picPath = p;
      btn.dataset.unselect = '1';

      item.append(img, label, btn);
      box.appendChild(item);
    }
  }

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
    if (card && !card.classList.contains('broken')) {
      const path = card.dataset.picPath;
      if (selected.has(path)) {
        selected.delete(path);
      } else {
        selected.add(path);
      }
      updateSelectedUI();
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
      'w-full h-full flex items-center justify-center text-neutral-500 text-xs p-2 text-center break-all';
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
        const open = node.classList.toggle('open');
        toggle.textContent = open ? '▾' : '▸';
        e.stopPropagation();
      }
    },
    true,
  );

  document.body.addEventListener('htmx:afterSwap', (e) => {
    const target = e.detail ? e.detail.target : e.target;

    if (target.classList && target.classList.contains('tree-children')) {
      const node = target.closest('.tree-node');
      const toggle = node.querySelector('.tree-toggle');
      toggle.dataset.loaded = 'true';
      toggle.textContent = '▾';
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
    $('#selected-button').addEventListener('click', () => {
      renderSelectedPanel();
      $('#selected-dialog').showModal();
    });
    $('#selected-close').addEventListener('click', () => $('#selected-dialog').close());
    $('#cleanup-button').addEventListener('click', () => {
      if (selected.size > 0) $('#cleanup-dialog').showModal();
    });
    $('#cleanup-cancel').addEventListener('click', () => $('#cleanup-dialog').close());
    updateSelectedUI();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
