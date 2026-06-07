/* MICS Variable Alignment — frontend logic */

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  alignment: {},          // {new_name: {mappings: [...]}}
  allVars: [],            // variable rows for current module (translation field included)
  cache: {},              // module_key -> [{...}]
  selectedNewVar: null,
  openItems: new Set(),
  selectedRows: new Set(), // "module:ticker:label_idx"
  searchQuery: '',
  currentModule: '',
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const moduleSelect    = $('module-select');
const searchBox       = $('search-box');
const leftList        = $('left-list');
const newVarForm      = $('new-var-form');
const newVarInput     = $('new-var-input');
const tbody           = $('var-tbody');
const tableEmpty      = $('table-empty');
const tableLoading    = $('table-loading');
const totalCountEl    = $('total-count');
const btnNewVar       = $('btn-new-var');
const btnNewVarOk     = $('btn-new-var-confirm');
const btnNewVarCancel = $('btn-new-var-cancel');
const btnAddMapping   = $('btn-add-mapping');
const btnExport       = $('btn-export');
const btnTranslate    = $('btn-translate');
const btnSelectAll    = $('btn-select-all-btn');
const btnDeselectAll  = $('btn-deselect-all');
const selectionCount  = $('selection-count');
const chkHeader       = $('chk-header');
const toast           = $('toast');

// ── Toast ─────────────────────────────────────────────────────────────────────
let toastTimer = null;
function showToast(msg, type = '') {
  toast.textContent = msg;
  toast.className = 'toast' + (type ? ' ' + type : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add('hidden'), 2500);
}

// ── API helpers ───────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Row key ───────────────────────────────────────────────────────────────────
const rowKey = v => `${v.module}:${v.ticker}:${v.label_idx ?? 0}`;

// ── Computed ──────────────────────────────────────────────────────────────────
function mappedKeys() {
  const keys = new Set();
  for (const info of Object.values(state.alignment)) {
    for (const m of info.mappings || []) {
      keys.add(`${m.module}:${m.ticker}:${m.label_idx ?? 0}`);
    }
  }
  return keys;
}

function visibleVars() {
  const mapped = mappedKeys();
  const q = state.searchQuery.toLowerCase();
  return state.allVars.filter(v => {
    if (mapped.has(rowKey(v))) return false;
    if (!q) return true;
    return (
      v.ticker.toLowerCase().includes(q) ||
      v.text.toLowerCase().includes(q) ||
      (v.translation || '').toLowerCase().includes(q)
    );
  });
}

function varsMap() {
  const m = {};
  state.allVars.forEach(v => { m[rowKey(v)] = v; });
  return m;
}

// ── Load modules ──────────────────────────────────────────────────────────────
async function loadModules() {
  const modules = await api('GET', '/api/modules');
  modules.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m.toUpperCase();
    moduleSelect.appendChild(opt);
  });
  moduleSelect.value = 'hh';
  state.currentModule = 'hh';
}

// ── Load variables (with frontend cache) ──────────────────────────────────────
async function loadVars(module) {
  const cacheKey = module || '__all__';
  tableLoading.classList.remove('hidden');
  tableEmpty.classList.add('hidden');
  tbody.innerHTML = '';

  if (state.cache[cacheKey]) {
    state.allVars = state.cache[cacheKey];
    tableLoading.classList.add('hidden');
    renderRight();
    return;
  }

  const url = module ? `/api/variables?module=${module}` : '/api/variables';
  const vars = await api('GET', url);
  state.cache[cacheKey] = vars;
  state.allVars = vars;
  tableLoading.classList.add('hidden');
  renderRight();
}

// ── Load alignment ────────────────────────────────────────────────────────────
async function loadAlignment() {
  state.alignment = await api('GET', '/api/alignment');
  renderLeft();
}

// ── Render LEFT panel ─────────────────────────────────────────────────────────
function renderLeft() {
  leftList.innerHTML = '';
  const names = Object.keys(state.alignment);

  if (names.length === 0) {
    leftList.innerHTML = '<div style="padding:20px 12px;color:var(--muted);font-size:12px;">暂无新变量，点击「新建变量」开始</div>';
    updateAddBtn();
    return;
  }

  names.forEach(name => {
    const info = state.alignment[name];
    const mappings = info.mappings || [];
    const isSelected = state.selectedNewVar === name;
    const isOpen = state.openItems.has(name);

    const item = document.createElement('div');
    item.className = 'left-item';

    const header = document.createElement('div');
    header.className = 'left-item-header' + (isSelected ? ' selected' : '') + (isOpen ? ' open' : '');
    header.innerHTML = `
      <span class="arrow">▶</span>
      <span class="left-item-name" title="${name}">${name}</span>
      <span class="left-item-count">${mappings.length}</span>
    `;
    header.addEventListener('click', () => toggleLeftItem(name));

    const body = document.createElement('div');
    body.className = 'left-item-body' + (isOpen ? ' open' : '');

    mappings.forEach(m => {
      const rounds = (m.rounds || []).join(', ');
      const cachedVar = state.allVars.find(
        v => v.module === m.module && v.ticker === m.ticker && (v.label_idx ?? 0) === (m.label_idx ?? 0)
      );
      const countries = cachedVar ? cachedVar.countries || [] : [];
      const countriesHtml = countries.length
        ? `<span class="mapping-countries" title="${countries.join('\n').replace(/"/g,'&quot;')}">${countries.length} countries</span>`
        : '';

      const row = document.createElement('div');
      row.className = 'mapping-row';
      row.innerHTML = `
        <span class="mapping-ticker">${m.ticker}</span>
        <span class="mapping-module">${m.module}</span>
        <span class="mapping-text" title="${m.text}">${m.text}</span>
        ${rounds ? `<span class="mapping-rounds">${rounds}</span>` : ''}
        ${countriesHtml}
        <button class="btn btn-danger btn-sm" title="删除此映射">✕</button>
      `;
      row.querySelector('button').addEventListener('click', e => {
        e.stopPropagation();
        deleteMapping(name, m.module, m.ticker, m.label_idx ?? 0);
      });
      body.appendChild(row);
    });

    const actions = document.createElement('div');
    actions.className = 'left-item-actions';
    actions.innerHTML = `<button class="btn btn-danger btn-sm">删除变量</button>`;
    actions.querySelector('button').addEventListener('click', () => deleteVar(name));
    body.appendChild(actions);

    item.appendChild(header);
    item.appendChild(body);
    leftList.appendChild(item);
  });

  updateAddBtn();
}

function toggleLeftItem(name) {
  if (state.selectedNewVar === name) {
    if (state.openItems.has(name)) state.openItems.delete(name);
    else state.openItems.add(name);
  } else {
    state.selectedNewVar = name;
    state.openItems.add(name);
  }
  renderLeft();
}

// ── Render RIGHT panel ────────────────────────────────────────────────────────
function renderRight() {
  const vars = visibleVars();
  tbody.innerHTML = '';
  totalCountEl.textContent = `共 ${vars.length} 条待对齐`;

  if (vars.length === 0) {
    tableEmpty.classList.remove('hidden');
    chkHeader.checked = false;
    updateSelectionUI();
    return;
  }
  tableEmpty.classList.add('hidden');

  vars.forEach(v => {
    const key = rowKey(v);
    const isSelected = state.selectedRows.has(key);

    const tr = document.createElement('tr');
    tr.dataset.key = key;
    if (isSelected) tr.classList.add('selected');

    tr.innerHTML = `
      <td class="col-check"><input type="checkbox" ${isSelected ? 'checked' : ''}></td>
      <td class="col-ticker"><span class="cell-ticker">${v.ticker}</span></td>
      <td class="col-module"><span class="cell-module">${v.module}</span></td>
      <td class="col-text"><span class="cell-text">${escHtml(v.text)}</span></td>
      <td class="col-translation"><span class="cell-translation">${escHtml(v.translation || '')}</span></td>
      <td class="col-rounds"><span class="cell-rounds">${(v.rounds || []).join(', ')}</span></td>
      <td class="col-countries">${renderCountries(v.countries || [])}</td>
    `;

    tr.querySelector('input[type=checkbox]').addEventListener('change', e => {
      if (e.target.checked) state.selectedRows.add(key);
      else state.selectedRows.delete(key);
      tr.classList.toggle('selected', e.target.checked);
      updateSelectionUI();
    });

    tr.addEventListener('click', e => {
      if (e.target.tagName === 'INPUT') return;
      const chk = tr.querySelector('input[type=checkbox]');
      chk.checked = !chk.checked;
      chk.dispatchEvent(new Event('change'));
    });

    tbody.appendChild(tr);
  });

  updateSelectionUI();
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function updateSelectionUI() {
  const n = state.selectedRows.size;
  selectionCount.textContent = `已选 ${n} 项`;
  btnTranslate.disabled = n === 0;
  updateAddBtn();
}

function updateAddBtn() {
  btnAddMapping.disabled = !(state.selectedNewVar && state.selectedRows.size > 0);
}

// ── New variable ──────────────────────────────────────────────────────────────
btnNewVar.addEventListener('click', () => {
  newVarForm.classList.remove('hidden');
  newVarInput.value = '';
  newVarInput.focus();
});
btnNewVarCancel.addEventListener('click', () => newVarForm.classList.add('hidden'));
btnNewVarOk.addEventListener('click', confirmNewVar);
newVarInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') confirmNewVar();
  if (e.key === 'Escape') newVarForm.classList.add('hidden');
});

async function confirmNewVar() {
  const name = newVarInput.value.trim();
  if (!name) return showToast('请输入变量名', 'error');
  if (state.alignment[name]) return showToast('变量名已存在', 'error');
  try {
    state.alignment = await api('POST', '/api/alignment/var', { new_name: name });
    state.selectedNewVar = name;
    state.openItems.add(name);
    newVarForm.classList.add('hidden');
    renderLeft();
    showToast(`已创建：${name}`, 'success');
  } catch (err) {
    showToast('创建失败：' + err.message, 'error');
  }
}

// ── Add mapping ───────────────────────────────────────────────────────────────
btnAddMapping.addEventListener('click', async () => {
  if (!state.selectedNewVar || state.selectedRows.size === 0) return;
  const vm = varsMap();
  const tickers = [...state.selectedRows].map(key => {
    const v = vm[key];
    return v ? { ticker: v.ticker, module: v.module, label_idx: v.label_idx ?? 0, text: v.text, rounds: v.rounds } : null;
  }).filter(Boolean);

  try {
    state.alignment = await api('POST', '/api/alignment/add', { new_name: state.selectedNewVar, tickers });
    state.selectedRows.clear();
    renderLeft();
    renderRight();
    showToast(`已添加 ${tickers.length} 项到 "${state.selectedNewVar}"`, 'success');
  } catch (err) {
    showToast('添加失败：' + err.message, 'error');
  }
});

// ── Delete mapping ────────────────────────────────────────────────────────────
async function deleteMapping(newName, module, ticker, labelIdx) {
  try {
    state.alignment = await api('DELETE',
      `/api/alignment/mapping/${encodeURIComponent(newName)}/${module}/${ticker}/${labelIdx ?? 0}`);
    invalidateCache();
    renderLeft();
    await loadVars(state.currentModule);
    showToast(`已移除映射 ${ticker}`, 'success');
  } catch (err) {
    showToast('删除失败：' + err.message, 'error');
  }
}

// ── Delete var ────────────────────────────────────────────────────────────────
async function deleteVar(name) {
  if (!confirm(`确认删除变量 "${name}" 及其所有映射？`)) return;
  try {
    state.alignment = await api('DELETE', `/api/alignment/var/${encodeURIComponent(name)}`);
    if (state.selectedNewVar === name) state.selectedNewVar = null;
    state.openItems.delete(name);
    invalidateCache();
    renderLeft();
    await loadVars(state.currentModule);
    showToast(`已删除变量 "${name}"`, 'success');
  } catch (err) {
    showToast('删除失败：' + err.message, 'error');
  }
}

// ── Translate (persist via backend) ──────────────────────────────────────────
btnTranslate.addEventListener('click', async () => {
  if (state.selectedRows.size === 0) return;
  const vm = varsMap();
  const items = [...state.selectedRows]
    .map(key => vm[key])
    .filter(v => v && v.text)
    .map(v => ({ module: v.module, ticker: v.ticker, label_idx: v.label_idx ?? 0, text: v.text }));

  if (!items.length) return;

  btnTranslate.disabled = true;
  btnTranslate.textContent = '翻译中…';
  try {
    const result = await api('POST', '/api/translate', { items });
    const translations = result.translations || [];

    // Update allVars in place so the column refreshes immediately
    const vm2 = varsMap();
    items.forEach((it, i) => {
      const key = `${it.module}:${it.ticker}:${it.label_idx}`;
      const v = vm2[key];
      if (v && translations[i]) v.translation = translations[i];
    });

    // Also update cache
    const cacheKey = state.currentModule || '__all__';
    if (state.cache[cacheKey]) {
      state.cache[cacheKey] = state.allVars;
    }

    renderRight();
    showToast(`已翻译 ${translations.length} 项`, 'success');
  } catch (err) {
    showToast('翻译失败：' + err.message, 'error');
  } finally {
    btnTranslate.disabled = false;
    btnTranslate.textContent = '翻译选中';
  }
});

// ── Select all / deselect all ─────────────────────────────────────────────────
btnSelectAll.addEventListener('click', () => {
  visibleVars().forEach(v => state.selectedRows.add(rowKey(v)));
  renderRight();
});

btnDeselectAll.addEventListener('click', () => {
  state.selectedRows.clear();
  renderRight();
});

chkHeader.addEventListener('change', () => {
  if (chkHeader.checked) visibleVars().forEach(v => state.selectedRows.add(rowKey(v)));
  else state.selectedRows.clear();
  renderRight();
});

// ── Export YAML ───────────────────────────────────────────────────────────────
btnExport.addEventListener('click', () => { window.location.href = '/api/alignment/export'; });

// ── Module selector ───────────────────────────────────────────────────────────
moduleSelect.addEventListener('change', async () => {
  state.currentModule = moduleSelect.value;
  state.selectedRows.clear();
  await loadVars(state.currentModule);
});

// ── Search ────────────────────────────────────────────────────────────────────
let searchTimer = null;
searchBox.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.searchQuery = searchBox.value; renderRight(); }, 200);
});

// ── Cache invalidation ────────────────────────────────────────────────────────
function invalidateCache() { state.cache = {}; }

// ── Countries tooltip ─────────────────────────────────────────────────────────
function renderCountries(countries) {
  if (!countries.length) return '<span class="cell-countries-none">—</span>';
  const tooltip = countries.join('\n').replace(/"/g, '&quot;');
  return `<span class="cell-countries" title="${tooltip}">${countries.length} countries</span>`;
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  await loadModules();
  await loadAlignment();
  await loadVars('hh');
}

init().catch(err => showToast('初始化失败：' + err.message, 'error'));
