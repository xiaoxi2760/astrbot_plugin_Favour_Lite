/**
 * 好感度 Lite · WebUI 控制中心
 * 基于上游 nuomicici/astrbot_plugin_Favour_Ultra v4.4.5「WebUI 深度重构与美术升级」
 * (Neo-Bento 设计系统 + 全局定制下拉选单 + 数据中心多维排序) 移植并裁剪。
 *
 * 裁剪说明（本 fork 已删除的功能，UI 中不得残留）：
 *   - 主动搭话 (active_chat) 整个 Tab
 *   - 会话隔离 / 迁移同步 (session_sync + sessions API) 整个 Tab
 *   - is_global_favour / enable_relationship_table 两个开关
 *   - advanced_config 下的会话黑/白名单列表
 *
 * 后端契约（main.py::_register_page_apis，仅这 5 个端点）：
 *   GET  config        -> 完整配置 JSON
 *   POST config        -> {success, error?}
 *   GET  datarecords   -> {records:[{id,user_id,username,favour,relationship,is_unique,last_interaction,session_id}]}
 *   POST datarecords   -> {action:'update'|'delete', id, ...}
 *   GET|POST backups   -> GET {backups:[{filename,size_kb,created,path}], config:{...}}
 *                        POST {action:'backup_now'|'restore'|'delete', filename}
 *   GET  version       -> {version:"v1.1.0"}
 */

const PLUGIN_NAME = 'astrbot_plugin_Favour_Lite';

let config = {};
let originalConfig = {};
let isDirtyState = false;

// ==================== Bridge 桥接与 API 请求封装 ====================

function getBridge() {
  return window.AstrBotPluginPage || null;
}

async function waitForBridge(timeoutMs = 3000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const b = getBridge();
    if (b && typeof b.ready === 'function') {
      try {
        await b.ready();
      } catch (e) {
        console.warn('Bridge ready warning:', e);
      }
      return b;
    }
    await new Promise((r) => setTimeout(r, 40));
  }
  return getBridge();
}

// 仅允许访问上面列出的 4 个相对名，防止误打未注册端点
const ALLOWED_ENDPOINTS = ['config', 'datarecords', 'backups', 'version'];

function assertEndpoint(endpoint) {
  if (!ALLOWED_ENDPOINTS.includes(endpoint)) {
    throw new Error('未注册的后端端点: ' + endpoint);
  }
}

async function apiGet(endpoint, params = {}) {
  assertEndpoint(endpoint);
  const bridge = getBridge();
  if (bridge && typeof bridge.apiGet === 'function') {
    return await bridge.apiGet(endpoint, params);
  }
  // 降级 Fetch（bridge 不可用时）
  const qs = new URLSearchParams(params).toString();
  const url = `/${PLUGIN_NAME}/${endpoint}${qs ? '?' + qs : ''}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  return await res.json();
}

async function apiPost(endpoint, data = {}) {
  assertEndpoint(endpoint);
  const bridge = getBridge();
  if (bridge && typeof bridge.apiPost === 'function') {
    return await bridge.apiPost(endpoint, data);
  }
  // 降级 Fetch（bridge 不可用时）
  const url = `/${PLUGIN_NAME}/${endpoint}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  return await res.json();
}

// ==================== 自定义弹窗 Modal 系统 ====================

let _modalResolve = null;

function showConfirmModal({ title = '操作确认', desc = '确定要执行此操作吗？', iconColor = 'rose' } = {}) {
  return new Promise((resolve) => {
    _modalResolve = resolve;
    const backdrop = document.getElementById('modal-backdrop');
    const titleEl = document.getElementById('modal-title');
    const descEl = document.getElementById('modal-desc');
    const iconWrap = document.getElementById('modal-icon');

    if (titleEl) titleEl.textContent = title;
    if (descEl) descEl.textContent = desc;

    if (iconWrap) {
      iconWrap.style.background = iconColor === 'amber' ? 'var(--accent-amber-bg)' : 'var(--accent-rose-bg)';
      iconWrap.style.color = iconColor === 'amber' ? 'var(--accent-amber)' : 'var(--accent-rose)';
    }

    if (backdrop) backdrop.classList.remove('hidden');
  });
}

function closeModal(result) {
  const backdrop = document.getElementById('modal-backdrop');
  if (backdrop) backdrop.classList.add('hidden');
  if (_modalResolve) {
    _modalResolve(result);
    _modalResolve = null;
  }
}

// ==================== Toast 提示系统 ====================
// 语义与本 fork v1.1.0 保持一致：
//   ok / warn -> 匀速上升 + 渐隐后自动消失
//   err       -> 常驻不自动消失，需手动点 × 关闭

function toast(msg, type = 'ok', duration = 3000) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const item = document.createElement('div');
  item.className = 'toast-item ' + type;

  const textSpan = document.createElement('span');
  textSpan.textContent = msg;
  item.appendChild(textSpan);

  const closeBtn = document.createElement('button');
  closeBtn.className = 'toast-close';
  closeBtn.innerHTML = '&times;';
  item.appendChild(closeBtn);

  container.appendChild(item);
  item.classList.add('toast-leave');
  // 强制回流后再移除 leave，保证入场动画可播放
  void item.offsetWidth;
  item.classList.remove('toast-leave');

  const remove = () => {
    if (!item.parentElement) return;
    item.classList.add('toast-leave');
    setTimeout(() => item.remove(), 220);
  };

  closeBtn.onclick = remove;
  if (type !== 'err') {
    setTimeout(remove, duration);
  }
}

// ==================== 状态徽章 / 未保存指示 ====================
// type: 'loading' | 'ok' | 'warn' | 'err'（映射到 CSS 的 status-dot 同名修饰类）

function status(text, type = 'ok') {
  const label = document.getElementById('status');
  const dot = document.getElementById('status-dot');
  if (label) label.textContent = text;
  if (dot) dot.className = 'status-dot ' + type;
}

function markDirty(dirty = true) {
  isDirtyState = dirty;
  const indicator = document.getElementById('dirty-indicator');
  if (indicator) {
    if (dirty) indicator.classList.remove('hidden');
    else indicator.classList.add('hidden');
  }
}

// ==================== 初始化与数据加载 ====================

async function init() {
  try {
    status('正在连接...', 'loading');
    config = await apiGet('config');
    originalConfig = deepClone(config);

    markDirty(false);
    status('已就绪', 'ok');
    renderTab('basic');

    // 动态读取并展示插件真实版本号（失败不影响主流程）
    loadVersionBadge();
  } catch (err) {
    console.error('初始化配置失败:', err);
    status('加载失败', 'err');
    toast('加载配置失败: ' + err.message, 'err');
  }
}

async function loadVersionBadge() {
  const tag = document.getElementById('brand-version-tag');
  if (!tag) return;
  try {
    const res = await apiGet('version');
    const ver = res && res.version ? String(res.version) : '';
    tag.textContent = ver ? (ver.startsWith('v') ? ver : 'v' + ver) : '--';
  } catch (err) {
    console.warn('读取插件版本号失败:', err);
    tag.textContent = '--';
  }
}

// ==================== 选项卡切换 ====================

function setupNavTabs() {
  const tabs = document.querySelectorAll('#tabs .nav-tab');
  tabs.forEach((tab) => {
    tab.onclick = () => {
      // [FIX-1] 切换前先把当前 Tab 的输入框（含未失焦）回写内存，避免重渲染丢数据
      collectFormData();
      tabs.forEach((t) => t.classList.remove('on'));
      tab.classList.add('on');
      renderTab(tab.dataset.t);
    };
  });

  const saveBtn = document.getElementById('btn-save');
  if (saveBtn) saveBtn.onclick = () => saveConfig();

  const cancelModalBtn = document.getElementById('modal-btn-cancel');
  const confirmModalBtn = document.getElementById('modal-btn-confirm');
  if (cancelModalBtn) cancelModalBtn.onclick = () => closeModal(false);
  if (confirmModalBtn) confirmModalBtn.onclick = () => closeModal(true);

  // 全局点击监听：点击外部自动收起所有下拉菜单
  document.addEventListener('click', (e) => {
    const isInsideSelect = e.target.closest ? e.target.closest('[data-custom-select]') : null;
    document.querySelectorAll('[data-custom-select].open').forEach((sel) => {
      if (sel !== isInsideSelect) sel.classList.remove('open');
    });
  });

  // ESC 键收起弹窗与下拉菜单
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      document.querySelectorAll('[data-custom-select].open').forEach((sel) => {
        sel.classList.remove('open');
      });
      const backdrop = document.getElementById('modal-backdrop');
      if (backdrop && !backdrop.classList.contains('hidden')) closeModal(false);
    }
  });
}

function currentTabName() {
  const activeTab = document.querySelector('#tabs .nav-tab.on');
  return activeTab ? activeTab.dataset.t : 'basic';
}

// Tab 路由表 —— 与 index.html 中的 data-t 一一对应（恰好 8 个）
function renderTab(tabKey) {
  const bodyEl = document.getElementById('body');
  if (!bodyEl) return;

  const tabRenderers = {
    basic: renderBasicTab,
    levels: renderLevelsTab,
    decay: renderDecayTab,
    perm: renderPermTab,
    adv: renderAdvTab,
    cold: renderColdTab,
    data: renderDataTab,
    backup: renderBackupTab,
  };

  const renderer = tabRenderers[tabKey] || renderBasicTab;
  bodyEl.innerHTML = renderer();
  bindTabEvents(tabKey);
  bindCustomSelects();

  if (tabKey === 'levels') {
    updateLevelSpectrum();
  } else if (tabKey === 'data') {
    initDataTabLogic();
  } else if (tabKey === 'backup') {
    initBackupTabLogic();
  }
}

// ==================== 工具函数 ====================

function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

function getVal(path, defVal = null) {
  const keys = path.split('.');
  let curr = config;
  for (const k of keys) {
    if (curr == null || typeof curr !== 'object') return defVal;
    curr = curr[k];
  }
  return curr !== undefined ? curr : defVal;
}

function setVal(path, value) {
  const keys = path.split('.');
  let curr = config;
  for (let i = 0; i < keys.length - 1; i++) {
    const k = keys[i];
    if (!(k in curr) || typeof curr[k] !== 'object') curr[k] = {};
    curr = curr[k];
  }
  curr[keys[keys.length - 1]] = value;
}

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function escapeRegExp(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// 搜索命中高亮（仅用于只读单元格，避免污染 contenteditable 的回写值）
function highlightText(str, query) {
  const safe = escapeHtml(str);
  if (!query) return safe;
  return safe.replace(new RegExp(escapeRegExp(escapeHtml(query)), 'gi'), (m) => `<mark class="hl">${m}</mark>`);
}

// ==================== UI 控件构建器 ====================

function uiBentoCard({ title, desc = '', iconSvg = '', content = '', fullWidth = false }) {
  return `
    <div class="bento-card ${fullWidth ? 'full-width' : ''}">
      <div class="bento-header">
        <div class="bento-title-group">
          ${iconSvg ? `<div class="bento-icon-badge">${iconSvg}</div>` : ''}
          <div>
            <div class="bento-title">${title}</div>
            ${desc ? `<div class="bento-desc">${desc}</div>` : ''}
          </div>
        </div>
      </div>
      <div class="bento-body">
        ${content}
      </div>
    </div>
  `;
}

function uiSwitch({ path, label, desc = '' }) {
  const checked = getVal(path, false);
  const id = 'sw-' + path.replace(/\./g, '-');
  return `
    <div class="form-group">
      <input type="checkbox" id="${id}" class="hidden-checkbox" data-p="${path}" ${checked ? 'checked' : ''}>
      <label for="${id}" class="switch-card ${checked ? 'active' : ''}">
        <div class="switch-info">
          <div class="switch-title">${label}</div>
          ${desc ? `<div class="switch-desc">${desc}</div>` : ''}
        </div>
        <div class="switch-ctrl"></div>
      </label>
    </div>
  `;
}

function uiInput({ path, label, type = 'text', hint = '', placeholder = '' }) {
  const val = getVal(path, '');
  return `
    <div class="form-group">
      <label class="form-label">
        <span>${label}</span>
        ${hint ? `<span class="form-label-hint">${hint}</span>` : ''}
      </label>
      <input type="${type}" class="form-input" data-p="${path}" value="${escapeHtml(val)}" placeholder="${placeholder}">
    </div>
  `;
}

function uiNumber({ path, label, hint = '', placeholder = '', min = null, max = null, defVal = 0 }) {
  const val = getVal(path, defVal);
  return `
    <div class="form-group">
      <label class="form-label">
        <span>${label}</span>
        ${hint ? `<span class="form-label-hint">${hint}</span>` : ''}
      </label>
      <input type="number" class="form-input" data-p="${path}" value="${val != null ? escapeHtml(val) : ''}"
        placeholder="${placeholder}" ${min !== null ? `min="${min}"` : ''} ${max !== null ? `max="${max}"` : ''}>
    </div>
  `;
}

// 绑定到配置路径的定制下拉选单（隐藏 input 承载真实值，data-p 与原生 select 等价）
function uiSelect({ path, label, options = [], hint = '' }) {
  const currVal = getVal(path, '');
  const selectedOpt = options.find(([val]) => String(val) === String(currVal)) || options[0] || ['', '请选择'];
  const currLabel = selectedOpt[1];

  return `
    <div class="form-group">
      <label class="form-label">
        <span>${label}</span>
        ${hint ? `<span class="form-label-hint">${hint}</span>` : ''}
      </label>
      <div class="custom-select-container" data-custom-select data-p="${path}">
        <input type="hidden" data-p="${path}" value="${escapeHtml(currVal)}">
        <button type="button" class="custom-select-trigger" aria-haspopup="listbox">
          <span class="custom-select-value">${escapeHtml(currLabel)}</span>
          <svg class="custom-select-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </button>
        <div class="custom-select-menu" role="listbox">
          ${options.map(([optVal, optLabel]) => {
            const isSelected = String(currVal) === String(optVal);
            return `
              <div class="custom-select-option ${isSelected ? 'selected' : ''}" data-val="${escapeHtml(optVal)}" role="option">
                <span class="custom-select-option-text">${escapeHtml(optLabel)}</span>
                <svg class="custom-select-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    </div>
  `;
}

// 行内独立下拉（工具栏排序用，不绑定配置路径）
function renderStandaloneCustomSelect({ id, value, options = [], placeholder = '请选择', extraClass = '' }) {
  const selectedOpt = options.find(([val]) => String(val) === String(value)) || options[0] || ['', placeholder];
  const currLabel = selectedOpt[1];

  return `
    <div class="custom-select-container ${extraClass}" data-custom-select id="${id}">
      <input type="hidden" value="${escapeHtml(value)}">
      <button type="button" class="custom-select-trigger" aria-haspopup="listbox">
        <span class="custom-select-value">${escapeHtml(currLabel)}</span>
        <svg class="custom-select-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
      </button>
      <div class="custom-select-menu" role="listbox">
        ${options.map(([optVal, optLabel]) => {
          const isSelected = String(value) === String(optVal);
          return `
            <div class="custom-select-option ${isSelected ? 'selected' : ''}" data-val="${escapeHtml(optVal)}" role="option">
              <span class="custom-select-option-text">${escapeHtml(optLabel)}</span>
              <svg class="custom-select-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

function uiTextarea({ path, label, rows = 4, hint = '', placeholder = '', pills = [] }) {
  const val = getVal(path, '');
  return `
    <div class="form-group full">
      <label class="form-label">
        <span>${label}</span>
        ${hint ? `<span class="form-label-hint">${hint}</span>` : ''}
      </label>
      <textarea class="form-textarea" data-p="${path}" rows="${rows}" placeholder="${placeholder}">${escapeHtml(val)}</textarea>
      ${pills.length ? `
        <div class="pill-group">
          ${pills.map((p) => `<span class="pill-tag" data-insert="${p.code}" title="${p.desc}">+ ${p.code}</span>`).join('')}
        </div>
      ` : ''}
    </div>
  `;
}

function uiStringList({ path, label, placeholder = '输入项...' }) {
  const list = getVal(path, []) || [];
  return `
    <div class="form-group full">
      <label class="form-label">${label}</label>
      <div class="dyn-list-container">
        ${list.map((item, idx) => `
          <div class="dyn-row-card">
            <span class="dyn-index-badge">${idx + 1}</span>
            <input type="text" class="form-input" data-list-p="${path}" data-list-idx="${idx}" value="${escapeHtml(item)}" placeholder="${placeholder}">
            <button class="btn-ghost-danger" data-act="del-list-item" data-path="${path}" data-idx="${idx}" title="删除此项">&times;</button>
          </div>
        `).join('')}
      </div>
      <button class="btn-dashed-add" data-act="add-list-item" data-path="${path}">+ 添加一项</button>
    </div>
  `;
}

// ==================== 1. 基础设置 Tab ====================

function renderBasicTab() {
  return `
    <div class="bento-grid">
      ${uiBentoCard({
        title: '好感度运行模式',
        desc: '调整好感度评定准则与排序机制',
        iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20V10M18 20V4M6 20v-4"/></svg>',
        content: `
          <div class="form-row">
            ${uiSelect({
              path: 'favour_mode',
              label: '判定模式',
              options: [
                ['galgame', 'Galgame 模式（容易提升，情感丰富）'],
                ['realistic', '拟真模式（严格严谨，步长适中）']
              ],
              hint: '影响提升好感度的宽容度'
            })}
            ${uiSelect({
              path: 'group_sort_by',
              label: '列表排序方式',
              options: [
                ['default', '默认（添加时间）'],
                ['favour', '按好感度降序'],
                ['nickname', '按用户昵称'],
                ['userid', '按用户 ID']
              ]
            })}
          </div>
        `
      })}

      ${uiBentoCard({
        title: '好感度极值与初始值',
        desc: '好感度点数边界约束',
        iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 16V4M17 20v-8M3 20h18"/></svg>',
        content: `
          <div class="form-row">
            ${uiNumber({ path: 'min_favour_value', label: '好感度下限', hint: '默认 -200' })}
            ${uiNumber({ path: 'max_favour_value', label: '好感度上限', hint: '默认 1000' })}
            ${uiNumber({ path: 'default_favour', label: '新用户初始好感', hint: '默认 0' })}
          </div>
        `
      })}

      ${uiBentoCard({
        title: '冷暴力总开关',
        desc: '连续降低好感时的惩罚行为（本 fork 的好感度为纯全局单池，所有用户共用一份数据）',
        fullWidth: true,
        iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>',
        content: `
          <div class="form-row">
            ${uiSwitch({
              path: 'enable_cold_violence',
              label: '启用冷暴力系统',
              desc: '当好感度连续降低时触发惩罚与冷淡回复'
            })}
          </div>
        `
      })}
    </div>
  `;
}

// ==================== 2. 好感分级 Tab ====================

function renderLevelsTab() {
  const levels = getVal('favour_levels', []) || [];
  return `
    <div class="bento-card full-width">
      <div class="bento-header">
        <div class="bento-title-group">
          <div class="bento-icon-badge">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
          </div>
          <div>
            <div class="bento-title">好感度等级区间与人设反应</div>
            <div class="bento-desc">至少设置 3 个分级；前 7 个描述可选，第 8 个起描述必填。</div>
          </div>
        </div>
      </div>

      <!-- 可视化连续谱（按配置的 min/max 区间动态渲染） -->
      <div class="spectrum-container">
        <div class="spectrum-header">
          <span>好感度连续谱预览</span>
          <span id="spectrum-summary">${levels.length} 个等级阶段</span>
        </div>
        <div class="spectrum-bar-wrap" id="level-spectrum-bar"></div>
        <div class="spectrum-scale" id="level-spectrum-scale"></div>
      </div>

      <!-- 分级列表 -->
      <div class="dyn-list-container" id="level-list-body">
        ${levels.map((lv, idx) => `
          <div class="dyn-row-card">
            <span class="dyn-index-badge">${idx + 1}</span>
            <div class="dyn-fields">
              <input type="number" class="form-input" style="max-width:90px" id="lv-min-${idx}" value="${escapeHtml(lv.min)}" placeholder="Min" title="最低分">
              <span style="color:var(--text-dim)">~</span>
              <input type="number" class="form-input" style="max-width:90px" id="lv-max-${idx}" value="${escapeHtml(lv.max)}" placeholder="Max" title="最高分">
              <input type="text" class="form-input" style="max-width:130px" id="lv-name-${idx}" value="${escapeHtml(lv.name)}" placeholder="等级名称">
              <input type="text" class="form-input" style="flex:1;min-width:200px" id="lv-desc-${idx}" value="${escapeHtml(lv.desc || '')}" placeholder="${idx >= 7 ? '(必填) 角色态度描述' : '(可选) 角色态度描述'}">
            </div>
            <button class="btn-ghost-danger" data-act="del-level-row" data-idx="${idx}" title="删除该分级">&times;</button>
          </div>
        `).join('')}
      </div>

      <button class="btn-dashed-add" data-act="add-level-row">+ 添加新分级</button>
    </div>
  `;
}

// 冷 → 暖 的色带采样，用于连续谱（长春藤紫 → 冰空蓝 → 暖粉）
const SPECTRUM_RAMP = ['#4F46E5', '#6366F1', '#38BDF8', '#34D399', '#FBBF24', '#F472B6', '#F43F5E'];

function hexToRgb(hex) {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function sampleRamp(stops, t) {
  const clamped = Math.min(1, Math.max(0, t));
  const pos = clamped * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(pos));
  const f = pos - i;
  const a = hexToRgb(stops[i]);
  const b = hexToRgb(stops[i + 1]);
  const mix = a.map((v, k) => Math.round(v + (b[k] - v) * f));
  return '#' + mix.map((v) => v.toString(16).padStart(2, '0')).join('');
}

// [FIX-3] 分级区间连续谱：段宽按 (max-min+1) 占比，颜色按段中点在整体区间中的位置插值
function updateLevelSpectrum() {
  const bar = document.getElementById('level-spectrum-bar');
  const scale = document.getElementById('level-spectrum-scale');
  const summary = document.getElementById('spectrum-summary');
  if (!bar) return;

  const levels = getVal('favour_levels', []) || [];
  if (!levels.length) {
    bar.innerHTML = '<div style="padding:4px 12px;font-size:0.75rem;color:var(--text-dim)">暂无分级数据</div>';
    if (scale) scale.innerHTML = '';
    if (summary) summary.textContent = '0 个等级阶段';
    return;
  }

  const spans = levels.map((lv) => Math.max(0, (+lv.max || 0) - (+lv.min || 0) + 1));
  const totalSpan = spans.reduce((s, n) => s + n, 0) || levels.length;
  const globalMin = Math.min(...levels.map((lv) => +lv.min || 0));
  const globalMax = Math.max(...levels.map((lv) => +lv.max || 0));
  const globalSpan = (globalMax - globalMin) || 1;

  let acc = 0;
  let html = '';
  levels.forEach((lv, idx) => {
    const width = (spans[idx] / totalSpan) * 100;
    const midPos = acc + spans[idx] / 2;
    acc += spans[idx];
    const color = sampleRamp(SPECTRUM_RAMP, midPos / totalSpan);
    html += `
      <div class="spectrum-segment" style="flex:0 0 ${width.toFixed(3)}%;background:${color}"
        title="${escapeHtml(lv.name)} (${lv.min} ~ ${lv.max})">
        ${width >= 7 ? escapeHtml(lv.name) : ''}
      </div>
    `;
  });
  bar.innerHTML = html;

  if (scale) {
    scale.innerHTML = `<span>${globalMin}</span><span>连续谱总跨度 ${totalSpan} 点</span><span>${globalMax}</span>`;
  }
  if (summary) summary.textContent = `${levels.length} 个等级阶段 · 跨度 ${globalSpan + 1} 点`;
}

// ==================== 3. 衰减机制 Tab ====================

function renderDecayTab() {
  const mode = getVal('favour_decay.mode', 'linear');
  const advRules = getVal('favour_decay.advanced_rules', []) || [];

  return `
    <div class="bento-grid">
      ${uiBentoCard({
        title: '衰减基本控制',
        desc: '控制好感度在长时间未互动时的自然流失',
        fullWidth: true,
        iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
        content: `
          <div class="form-row">
            ${uiSwitch({
              path: 'favour_decay.enabled',
              label: '启用好感度衰减',
              desc: '开启后将按设定的周期自动检查并扣减好感'
            })}
            ${uiSelect({
              path: 'favour_decay.mode',
              label: '衰减模式',
              options: [
                ['linear', '线性衰减（统一未互动天数与扣除点数）'],
                ['advanced', '分级衰减（按好感度区间动态调整）']
              ]
            })}
            ${uiNumber({
              path: 'favour_decay.floor_favour',
              label: '全局衰减底线',
              hint: '留空则为好感度下限',
              placeholder: '留空表示不限制底线',
              defVal: ''
            })}
          </div>
        `
      })}

      ${mode === 'linear' ? uiBentoCard({
        title: '线性衰减规则',
        desc: '所有用户统一遵循的衰减参数',
        fullWidth: true,
        iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20L20 4M20 4H10M20 4v10"/></svg>',
        content: `
          <div class="form-row">
            ${uiNumber({ path: 'favour_decay.inactive_days', label: '无互动触发天数', hint: '例如 7 天' })}
            ${uiNumber({ path: 'favour_decay.decay_amount', label: '每次衰减点数', hint: '例如 5 点' })}
          </div>
        `
      }) : uiBentoCard({
        title: '分级衰减规则表',
        desc: '按当前好感度区间匹配不同的流失速度',
        fullWidth: true,
        iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18M7 16l4-4 4 4 6-6"/></svg>',
        content: `
          <div class="dyn-list-container">
            ${advRules.map((r, idx) => `
              <div class="dyn-row-card">
                <span class="dyn-index-badge">${idx + 1}</span>
                <div class="dyn-fields">
                  <input type="number" class="form-input" style="max-width:90px" id="adv-min-${idx}" value="${escapeHtml(r.min_favour)}" placeholder="Min 好感">
                  <span style="color:var(--text-dim)">~</span>
                  <input type="number" class="form-input" style="max-width:90px" id="adv-max-${idx}" value="${escapeHtml(r.max_favour)}" placeholder="Max 好感">
                  <input type="number" class="form-input" style="max-width:100px" id="adv-days-${idx}" value="${escapeHtml(r.inactive_days)}" placeholder="天数">
                  <input type="number" class="form-input" style="max-width:100px" id="adv-amt-${idx}" value="${escapeHtml(r.decay_amount)}" placeholder="衰减量">
                  <input type="number" class="form-input" style="max-width:100px" id="adv-floor-${idx}" value="${r.floor != null ? escapeHtml(r.floor) : ''}" placeholder="衰减底线">
                </div>
                <button class="btn-ghost-danger" data-act="del-adv-row" data-idx="${idx}" title="删除规则">&times;</button>
              </div>
            `).join('')}
          </div>
          <button class="btn-dashed-add" data-act="add-adv-row">+ 添加衰减规则</button>
        `
      })}
    </div>
  `;
}

// ==================== 4. 权限体系 Tab ====================

function renderPermTab() {
  return `
    <div class="bento-grid">
      ${uiBentoCard({
        title: '好感度查询权限',
        desc: '控制普通用户是否能够使用查询指令（管理员始终可查）',
        iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>',
        content: `
          <div class="form-row">
            ${uiSelect({
              path: 'query_permission.group_normal_user',
              label: '群聊普通用户查询',
              options: [
                [true, '允许所有人查询'],
                [false, '仅管理员可查']
              ]
            })}
            ${uiSelect({
              path: 'query_permission.private_normal_user',
              label: '私聊普通用户查询',
              options: [
                [true, '允许所有人查询'],
                [false, '仅管理员可查']
              ]
            })}
          </div>
        `
      })}

      ${uiBentoCard({
        title: '管理指令权限门槛',
        desc: '修改好感度等特权指令所需的最低身份',
        iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>',
        content: `
          <div class="form-row">
            ${uiSelect({
              path: 'advanced_config.modify_favour_permission',
              label: '修改好感度最低权限',
              options: [
                ['admin', '群管理员及以上 (Admin)'],
                ['owner', '群主及以上 (Owner)'],
                ['superuser', '仅 Bot 管理员 (Superuser)']
              ]
            })}
          </div>
        `
      })}
    </div>
  `;
}

// ==================== 5. 高级调节 Tab ====================

function renderAdvTab() {
  return `
    <div class="bento-grid">
      ${uiBentoCard({
        title: '好感度增减步长限制',
        desc: '单次互动好感度上升与下降的波动范围',
        fullWidth: true,
        iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20V10M18 20V4M6 20v-4"/></svg>',
        content: `
          <div class="form-row">
            ${uiNumber({ path: 'advanced_config.favour_increase_min', label: '好感上升最小值', hint: '默认 1' })}
            ${uiNumber({ path: 'advanced_config.favour_increase_max', label: '好感上升最大值', hint: '默认 3' })}
            ${uiNumber({ path: 'advanced_config.favour_decrease_min', label: '好感下降最小值', hint: '默认 1' })}
            ${uiNumber({ path: 'advanced_config.favour_decrease_max', label: '好感下降最大值', hint: '默认 5' })}
          </div>
        `
      })}

      ${uiBentoCard({
        title: '管理与群等级阈值',
        desc: '特权与初始好感配置',
        iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="8.5" cy="7" r="4"/></svg>',
        content: `
          <div class="form-row">
            ${uiNumber({ path: 'advanced_config.admin_default_favour', label: '管理员初始好感', hint: '默认 50' })}
            ${uiNumber({ path: 'advanced_config.level_threshold', label: '群等级阈值', hint: '默认 50' })}
          </div>
        `
      })}

      ${uiBentoCard({
        title: '好感度特使名单',
        desc: '特殊身份用户列表（不受常规好感度惩罚等）',
        content: uiStringList({ path: 'advanced_config.favour_envoys', label: '特使 User ID 列表', placeholder: '输入用户 ID...' })
      })}
    </div>
  `;
}

// ==================== 6. 冷暴力 Tab ====================

function renderColdTab() {
  return `
    <div class="bento-grid">
      ${uiBentoCard({
        title: '冷暴力触发机制',
        desc: '连续惹恼 Bot 时的惩罚行为控制',
        fullWidth: true,
        iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>',
        content: `
          <div class="form-row">
            ${uiNumber({ path: 'cold_violence_config.consecutive_decrease_threshold', label: '连续降低好感触发次数', hint: '默认 3 次' })}
            ${uiNumber({ path: 'cold_violence_config.duration_minutes', label: '冷暴力持续时间 (分钟)', hint: '默认 30 分钟' })}
          </div>
          <div class="form-row" style="margin-top:12px;">
            ${uiSwitch({
              path: 'cold_violence_config.is_global',
              label: '跨会话全局冷暴力',
              desc: '开启后该用户在所有群聊/私聊都将被同时冷落'
            })}
            ${uiSwitch({
              path: 'cold_violence_config.auto_blacklist_on_min',
              label: '达好感下限时自动拉黑',
              desc: '好感度跌至最低值时不再响应并拉黑该用户'
            })}
          </div>
        `
      })}

      ${uiBentoCard({
        title: '自定义冷淡回复词条',
        desc: '占位符 {time_str} 将自动替换为剩余冷却时间',
        fullWidth: true,
        iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>',
        content: `
          <div class="form-row">
            ${uiInput({ path: 'cold_violence_config.replies.on_trigger', label: '刚触发冷暴力时的附加提示' })}
            ${uiInput({ path: 'cold_violence_config.replies.on_message', label: '冷暴力期间拦截对话的回复' })}
            ${uiInput({ path: 'cold_violence_config.replies.on_query', label: '冷暴力期间查询好感时的回复' })}
          </div>
        `
      })}
    </div>
  `;
}

// ==================== 7. 数据中心 Tab（纯全局数据，平铺总表） ====================
// 本 fork 的 session_id 恒为 "global"，所有用户记录在同一数据池，
// 因此不做会话分组/折叠，直接平铺一张总表。

let _dataRecords = null;   // 后端返回的记录数组
let _dataSearchQuery = '';
let _dataSortMode = 'favour_desc'; // favour_desc | favour_asc | uid_asc | uid_desc | unique_first | username_asc
let _dataRuntimeBackupConf = null; // GET backups 里附带的运行时配置（只读展示）

function renderDataTab() {
  const sortOptions = [
    ['favour_desc', '好感度 (高 → 低)'],
    ['favour_asc', '好感度 (低 → 高)'],
    ['uid_asc', '按 UID 升序 (0 → 9)'],
    ['uid_desc', '按 UID 降序 (9 → 0)'],
    ['unique_first', '唯一关系优先'],
    ['username_asc', '按用户昵称 (A → Z)']
  ];

  return `
    <div>
      <!-- 统计指标卡片 -->
      <div class="stats-banner" id="data-stats-banner">
        <div class="stat-box">
          <div class="stat-icon-wrap indigo">
            <svg style="width:20px;height:20px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/></svg>
          </div>
          <div class="stat-content">
            <div class="stat-val" id="stat-total-records">--</div>
            <div class="stat-lbl">总好感记录</div>
          </div>
        </div>

        <div class="stat-box">
          <div class="stat-icon-wrap emerald">
            <svg style="width:20px;height:20px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
          </div>
          <div class="stat-content">
            <div class="stat-val" id="stat-peak-favour">--</div>
            <div class="stat-lbl">最高好感度</div>
          </div>
        </div>

        <div class="stat-box">
          <div class="stat-icon-wrap amber">
            <svg style="width:20px;height:20px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 17l6-6 4 4 8-8"/><path d="M21 7v6h-6"/></svg>
          </div>
          <div class="stat-content">
            <div class="stat-val" id="stat-min-favour">--</div>
            <div class="stat-lbl">最低好感度</div>
          </div>
        </div>

        <div class="stat-box">
          <div class="stat-icon-wrap rose">
            <svg style="width:20px;height:20px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l2.4 7.4H22l-6 4.6 2.3 7.4L12 17l-6.3 4.4L8 14 2 9.4h7.6z"/></svg>
          </div>
          <div class="stat-content">
            <div class="stat-val" id="stat-unique-count">--</div>
            <div class="stat-lbl">唯一关系数</div>
          </div>
        </div>
      </div>

      <!-- 搜索与排序工具栏 -->
      <div class="data-toolbar-card">
        <div class="data-search-row">
          <div class="search-input-wrap">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input type="text" id="data-search-box" class="search-input" placeholder="实时搜索 用户ID / 用户昵称 / 关系称号...">
          </div>

          <div class="sort-control-container">
            <div class="sort-label">
              <svg style="width:14px;height:14px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M6 12h12M10 18h4"/></svg>
              <span>排序:</span>
            </div>
            ${renderStandaloneCustomSelect({
              id: 'data-sort-select',
              value: _dataSortMode,
              options: sortOptions,
              extraClass: 'inline-sort'
            })}
          </div>
        </div>

        <div class="filter-pills-row">
          <div class="stat-lbl" style="font-size:0.75rem;">
            提示：本 fork 好感度为纯全局单池，所有用户记录在同一张表中，可直接编辑后保存。
          </div>
          <div class="toolbar-actions-right">
            <button class="btn-outline" style="padding:4px 10px;font-size:0.78rem" id="btn-refresh-data">
              <svg style="width:13px;height:13px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg>
              <span>刷新</span>
            </button>
          </div>
        </div>
      </div>

      <!-- 平铺总表 -->
      <div id="data-records-view">
        <div class="loading-hint">正在加载数据中心...</div>
      </div>
    </div>
  `;
}

async function initDataTabLogic() {
  const searchBox = document.getElementById('data-search-box');
  if (searchBox) {
    searchBox.oninput = (e) => {
      _dataSearchQuery = e.target.value.trim().toLowerCase();
      renderDataRecords();
    };
  }

  const refreshBtn = document.getElementById('btn-refresh-data');
  if (refreshBtn) {
    refreshBtn.onclick = () => loadDataRecords(true);
  }

  await loadDataRecords();
}

// 归一化后端响应：主用 {records:[...]}，同时兼容 {global:[...], non_global:[...]} 形态
function normalizeRecords(res) {
  if (!res || typeof res !== 'object') return [];
  if (Array.isArray(res.records)) return res.records;
  if (Array.isArray(res.global) || Array.isArray(res.non_global)) {
    return [...(res.global || []), ...(res.non_global || [])];
  }
  return [];
}

async function loadDataRecords(force = false) {
  const view = document.getElementById('data-records-view');
  if (!view) return;

  try {
    if (_dataRecords === null || force) {
      view.innerHTML = '<div class="loading-hint">正在加载好感度记录...</div>';
      _dataRecords = normalizeRecords(await apiGet('datarecords'));
    }
    updateDataStats();
    renderDataRecords();
  } catch (err) {
    console.error('加载数据失败:', err);
    view.innerHTML = `<div class="loading-hint" style="color:var(--accent-rose)">加载失败: ${escapeHtml(err.message)}</div>`;
  }
}

function updateDataStats() {
  if (!_dataRecords) return;
  const totalEl = document.getElementById('stat-total-records');
  const peakEl = document.getElementById('stat-peak-favour');
  const minEl = document.getElementById('stat-min-favour');
  const uniqueEl = document.getElementById('stat-unique-count');

  if (totalEl) totalEl.textContent = _dataRecords.length;
  if (peakEl || minEl) {
    if (_dataRecords.length > 0) {
      const favs = _dataRecords.map((r) => Number(r.favour) || 0);
      if (peakEl) peakEl.textContent = Math.max(...favs);
      if (minEl) minEl.textContent = Math.min(...favs);
    } else {
      if (peakEl) peakEl.textContent = '0';
      if (minEl) minEl.textContent = '0';
    }
  }
  if (uniqueEl) uniqueEl.textContent = _dataRecords.filter((r) => r.is_unique).length;
}

// 记录排序算法
function sortRecords(records, mode) {
  return [...records].sort((a, b) => {
    if (mode === 'favour_desc') {
      return (Number(b.favour) || 0) - (Number(a.favour) || 0);
    } else if (mode === 'favour_asc') {
      return (Number(a.favour) || 0) - (Number(b.favour) || 0);
    } else if (mode === 'uid_asc') {
      return String(a.user_id).localeCompare(String(b.user_id), undefined, { numeric: true });
    } else if (mode === 'uid_desc') {
      return String(b.user_id).localeCompare(String(a.user_id), undefined, { numeric: true });
    } else if (mode === 'unique_first') {
      if (!!a.is_unique !== !!b.is_unique) return a.is_unique ? -1 : 1;
      return (Number(b.favour) || 0) - (Number(a.favour) || 0);
    } else if (mode === 'username_asc') {
      return String(a.username || '').localeCompare(String(b.username || ''));
    }
    return 0;
  });
}

function favourBadgeClass(f) {
  const v = Number(f) || 0;
  if (v > 0) return 'positive';
  if (v < 0) return 'negative';
  return 'neutral';
}

function renderDataRecords() {
  const view = document.getElementById('data-records-view');
  if (!view || _dataRecords === null) return;

  const query = _dataSearchQuery;
  const matched = query
    ? _dataRecords.filter((r) => [r.user_id, r.username, r.relationship].join(' ').toLowerCase().includes(query))
    : _dataRecords;
  const rows = sortRecords(matched, _dataSortMode);

  if (!rows.length) {
    view.innerHTML = `
      <div class="bento-card flat-table-card">
        <div class="empty-hint">${query ? '没有匹配的好感度记录' : '暂无任何好感度记录'}</div>
      </div>
    `;
    return;
  }

  let html = `
    <div class="bento-card flat-table-card">
      <div class="table-responsive">
        <table class="modern-table">
          <thead>
            <tr>
              <th>用户 ID (UID)</th>
              <th>用户昵称</th>
              <th>好感度数值</th>
              <th>关系称号</th>
              <th style="text-align:center">唯一关系</th>
              <th>最后互动</th>
              <th class="col-actions" style="text-align:right">操作</th>
            </tr>
          </thead>
          <tbody>
  `;

  rows.forEach((r) => {
    const fav = Number(r.favour) || 0;
    html += `
      <tr id="rec-row-${r.id}">
        <td class="cell-uid">${highlightText(r.user_id, query)}</td>
        <td>
          <span contenteditable="true" class="editable-chip" data-id="${r.id}" data-field="username" title="点击编辑昵称">${escapeHtml(r.username)}</span>
        </td>
        <td>
          <span class="favour-cell">
            <input type="number" class="form-input" value="${fav}" data-id="${r.id}" data-field="favour" title="直接修改好感度">
            <span class="favour-badge ${favourBadgeClass(fav)}">${fav}</span>
          </span>
        </td>
        <td>
          <span contenteditable="true" class="editable-chip" data-id="${r.id}" data-field="relationship" title="点击编辑关系">${escapeHtml(r.relationship)}</span>
        </td>
        <td style="text-align:center">
          <input type="checkbox" data-id="${r.id}" data-field="is_unique" ${r.is_unique ? 'checked' : ''} title="关系是否唯一">
        </td>
        <td class="cell-muted-mono">${escapeHtml(fmtTime(r.last_interaction))}</td>
        <td class="col-actions" style="text-align:right;white-space:nowrap">
          <button class="btn-outline" style="padding:4px 8px" data-act="save-single-rec" data-id="${r.id}" title="保存修改">
            <svg style="width:13px;height:13px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
          </button>
          <button class="btn-ghost-danger" style="padding:4px 8px" data-act="del-single-rec" data-id="${r.id}" title="删除记录">
            <svg style="width:13px;height:13px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
          </button>
        </td>
      </tr>
    `;
  });

  html += `
          </tbody>
        </table>
      </div>
    </div>
  `;

  view.innerHTML = html;
  bindDataRowActions();
  setupTableScrollState();
}

/* 表格横向溢出状态：只有真的溢出时才给右侧钉靠列加投影，
   并随面板宽度变化实时刷新（WebUI 跑在 iframe 里，宽度由父框架决定）。 */
function setupTableScrollState() {
  const wrap = document.querySelector('.table-responsive');
  if (!wrap) return;
  const sync = () => {
    wrap.classList.toggle('is-scrollable', wrap.scrollWidth - wrap.clientWidth > 1);
  };
  wrap.addEventListener('scroll', sync, { passive: true });
  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(sync).observe(wrap);
  } else {
    window.addEventListener('resize', sync);
  }
  sync();
}

function bindDataRowActions() {
  document.querySelectorAll('[data-act="save-single-rec"]').forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const id = +btn.dataset.id;
      const row = document.getElementById('rec-row-' + id);
      if (!row) return;

      const updates = { action: 'update', id };
      const favourInp = row.querySelector('input[data-field="favour"]');
      if (favourInp) updates.favour = parseInt(favourInp.value) || 0;

      const uniqueCb = row.querySelector('input[data-field="is_unique"]');
      if (uniqueCb) updates.is_unique = uniqueCb.checked;

      row.querySelectorAll('.editable-chip').forEach((chip) => {
        updates[chip.dataset.field] = chip.textContent.trim();
      });

      try {
        const res = await apiPost('datarecords', updates);
        if (res && res.success) {
          toast('记录已保存更新', 'ok');
          if (_dataRecords) {
            _dataRecords = _dataRecords.map((r) => {
              if (r.id !== id) return r;
              return {
                ...r,
                favour: updates.favour !== undefined ? updates.favour : r.favour,
                username: updates.username !== undefined ? updates.username : r.username,
                relationship: updates.relationship !== undefined ? updates.relationship : r.relationship,
                is_unique: updates.is_unique !== undefined ? updates.is_unique : r.is_unique
              };
            });
          }
          updateDataStats();
          renderDataRecords();
        } else {
          toast('保存失败: ' + ((res && res.error) || ''), 'err');
        }
      } catch (err) {
        toast('请求失败: ' + err.message, 'err');
      }
    };
  });

  document.querySelectorAll('[data-act="del-single-rec"]').forEach((btn) => {
    btn.onclick = async (e) => {
      e.stopPropagation();
      const id = +btn.dataset.id;
      const confirmed = await showConfirmModal({
        title: '删除好感度记录',
        desc: `确定要删除该好感度记录 (#${id}) 吗？此操作无法撤销。`,
        iconColor: 'rose'
      });
      if (!confirmed) return;

      try {
        const res = await apiPost('datarecords', { action: 'delete', id });
        if (res && res.success) {
          toast('记录已删除', 'ok');
          if (_dataRecords) _dataRecords = _dataRecords.filter((r) => r.id !== id);
          updateDataStats();
          renderDataRecords();
        } else {
          toast('删除失败: ' + ((res && res.error) || ''), 'err');
        }
      } catch (err) {
        toast('请求失败: ' + err.message, 'err');
      }
    };
  });
}

// ==================== 8. 备份快照 Tab ====================

function renderBackupTab() {
  return `
    <div class="bento-grid">
      ${uiBentoCard({
        title: '自动备份调度与轮转',
        desc: '定期创建好感度数据库快照，并在过期后自动清理',
        fullWidth: true,
        iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
        content: `
          <div class="form-row">
            ${uiSwitch({
              path: 'backup.enabled',
              label: '启用自动备份',
              desc: '按指定时间间隔自动创建本地快照'
            })}
            ${uiNumber({ path: 'backup.interval_hours', label: '备份间隔 (小时)', hint: '默认 3 小时', defVal: '' })}
            ${uiNumber({ path: 'backup.retention_hours', label: '保留时间 (小时)', hint: '默认 24 小时', defVal: '' })}
          </div>
          <div style="font-size:0.75rem;color:var(--text-muted);margin-top:10px;">
            提示：修改上述自动备份周期设置后，请点击顶部「保存配置」按钮持久化。
          </div>
        `
      })}

      ${uiBentoCard({
        title: '快照归档历史',
        desc: '查看已有备份，支持一键恢复与手动快照',
        fullWidth: true,
        iconSvg: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4"/></svg>',
        content: `
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;gap:10px;flex-wrap:wrap;">
            <button class="btn-primary" id="btn-create-backup-now">
              <svg style="width:14px;height:14px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
              <span>立即创建备份快照</span>
            </button>
            <button class="btn-outline" id="btn-refresh-backups">刷新备份列表</button>
          </div>
          <div id="backup-runtime-confirm" style="font-size:0.75rem;color:var(--text-muted);margin-bottom:10px;"></div>
          <div id="backups-list-view">
            <div class="loading-hint">正在加载快照列表...</div>
          </div>
        `
      })}
    </div>
  `;
}

async function initBackupTabLogic() {
  const createBtn = document.getElementById('btn-create-backup-now');
  const refreshBtn = document.getElementById('btn-refresh-backups');

  if (createBtn) {
    createBtn.onclick = async () => {
      try {
        status('备份中...', 'warn');
        const res = await apiPost('backups', { action: 'backup_now' });
        if (res && res.success) {
          status('备份完成', 'ok');
          toast('快照创建成功', 'ok');
          loadBackupsList();
        } else {
          status('备份失败', 'err');
          toast('备份失败: ' + ((res && res.error) || '未知错误'), 'err');
        }
      } catch (err) {
        status('请求失败', 'err');
        toast('创建备份失败: ' + err.message, 'err');
      }
    };
  }

  if (refreshBtn) {
    refreshBtn.onclick = () => loadBackupsList();
  }

  loadBackupsList();
}

async function loadBackupsList() {
  const view = document.getElementById('backups-list-view');
  if (!view) return;

  try {
    const data = await apiGet('backups');
    const list = (data && data.backups) || [];
    _dataRuntimeBackupConf = (data && data.config) || null;

    const confBox = document.getElementById('backup-runtime-confirm');
    if (confBox) {
      const c = _dataRuntimeBackupConf;
      confBox.textContent = c
        ? `后端当前生效：${c.enabled ? '自动备份已启用' : '自动备份已停用'} · 间隔 ${c.interval_hours}h · 留存 ${c.retention_hours}h`
        : '';
    }

    if (!list.length) {
      view.innerHTML = '<div class="empty-hint">暂无备份文件</div>';
      return;
    }

    let html = '';
    list.forEach((b) => {
      const size = (typeof b.size_kb === 'number' ? b.size_kb : 0).toFixed(1);
      const created = b.created ? fmtTime(b.created) : '时间未知';
      html += `
        <div class="backup-item">
          <div class="backup-file-info">
            <div class="backup-icon-wrap">
              <svg style="width:16px;height:16px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            </div>
            <div>
              <div class="backup-name">${escapeHtml(b.filename)}</div>
              <div class="backup-meta">${size} KB · ${escapeHtml(created)}</div>
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            <button class="btn-outline" data-act="restore-backup-file" data-fn="${escapeHtml(b.filename)}">
              <svg style="width:13px;height:13px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/></svg>
              <span>恢复此备份</span>
            </button>
            <button class="btn-ghost-danger" data-act="del-backup-file" data-fn="${escapeHtml(b.filename)}" title="删除此备份">&times;</button>
          </div>
        </div>
      `;
    });

    view.innerHTML = html;

    view.querySelectorAll('[data-act="restore-backup-file"]').forEach((btn) => {
      btn.onclick = async () => {
        const fn = btn.dataset.fn;
        const confirmed = await showConfirmModal({
          title: '确认恢复备份',
          desc: `确定要使用快照 "${fn}" 恢复数据库吗？恢复将覆盖当前的好感度数据。`,
          iconColor: 'amber'
        });
        if (!confirmed) return;

        try {
          status('恢复中...', 'warn');
          const res = await apiPost('backups', { action: 'restore', filename: fn });
          if (res && res.success) {
            status('恢复成功', 'ok');
            toast('快照已成功恢复: ' + (res.message || ''), 'ok');
            _dataRecords = null; // 清除数据缓存，下次进入数据中心重新拉取
          } else {
            status('恢复失败', 'err');
            toast('恢复失败: ' + ((res && (res.error || res.message)) || ''), 'err');
          }
        } catch (err) {
          status('请求失败', 'err');
          toast('恢复请求失败: ' + err.message, 'err');
        }
      };
    });

    view.querySelectorAll('[data-act="del-backup-file"]').forEach((btn) => {
      btn.onclick = async () => {
        const fn = btn.dataset.fn;
        const confirmed = await showConfirmModal({
          title: '删除快照',
          desc: `确定要永久删除快照 "${fn}" 吗？`,
          iconColor: 'rose'
        });
        if (!confirmed) return;

        try {
          const res = await apiPost('backups', { action: 'delete', filename: fn });
          if (res && res.success) {
            status('已删除', 'ok');
            toast('快照已删除', 'ok');
            loadBackupsList();
          } else {
            status('删除失败', 'err');
            toast('删除失败: ' + ((res && (res.error || res.message)) || ''), 'err');
          }
        } catch (err) {
          toast('删除请求失败: ' + err.message, 'err');
        }
      };
    });
  } catch (err) {
    view.innerHTML = `<div class="empty-hint" style="color:var(--accent-rose)">加载备份失败: ${escapeHtml(err.message)}</div>`;
  }
}

// ==================== 表单事件绑定与数据收集 ====================

function bindCustomSelects() {
  document.querySelectorAll('[data-custom-select]').forEach((container) => {
    const trigger = container.querySelector('.custom-select-trigger');
    const hiddenInput = container.querySelector('input[type="hidden"]');
    const valueDisplay = container.querySelector('.custom-select-value');
    const options = container.querySelectorAll('.custom-select-option');

    if (!trigger) return;

    trigger.onclick = (e) => {
      e.stopPropagation();
      const wasOpen = container.classList.contains('open');
      document.querySelectorAll('[data-custom-select].open').forEach((other) => {
        if (other !== container) other.classList.remove('open');
      });
      container.classList.toggle('open', !wasOpen);
    };

    options.forEach((opt) => {
      opt.onclick = (e) => {
        e.stopPropagation();
        const newVal = opt.dataset.val;
        const text = (opt.querySelector('.custom-select-option-text') || {}).textContent || '';

        options.forEach((o) => o.classList.remove('selected'));
        opt.classList.add('selected');

        if (valueDisplay) valueDisplay.textContent = text;
        if (hiddenInput) {
          hiddenInput.value = newVal;
          hiddenInput.dispatchEvent(new Event('input', { bubbles: true }));
          hiddenInput.dispatchEvent(new Event('change', { bubbles: true }));
        }

        container.classList.remove('open');
        markDirty(true);

        const path = container.dataset.p;
        if (path) {
          let parsedVal = newVal;
          if (newVal === 'true') parsedVal = true;
          else if (newVal === 'false') parsedVal = false;
          setVal(path, parsedVal);

          // [FIX-3] 切换 favour_decay.mode 前先回写当前表单，避免 linear 分支的
          // inactive_days / decay_amount 被 advanced_rules 重渲染吞掉
          if (path === 'favour_decay.mode') {
            collectFormData();
            renderTab('decay');
          }
        }

        // 数据中心排序联动
        if (container.id === 'data-sort-select') {
          _dataSortMode = newVal;
          renderDataRecords();
        }
      };
    });
  });
}

function bindTabEvents(tabKey) {
  // 监听输入改动
  document.querySelectorAll('#body input, #body textarea').forEach((el) => {
    el.oninput = el.onchange = () => {
      markDirty(true);
      if (tabKey === 'levels') {
        collectFormData();
        updateLevelSpectrum();
      }
    };
  });

  // 占位符药丸插入事件
  document.querySelectorAll('.pill-tag[data-insert]').forEach((pill) => {
    pill.onclick = () => {
      const code = pill.dataset.insert;
      const textarea = pill.closest('.form-group') ? pill.closest('.form-group').querySelector('textarea') : null;
      if (textarea) {
        const start = textarea.selectionStart || textarea.value.length;
        const end = textarea.selectionEnd || textarea.value.length;
        const text = textarea.value;
        textarea.value = text.substring(0, start) + code + text.substring(end);
        textarea.focus();
        textarea.selectionStart = textarea.selectionEnd = start + code.length;
        markDirty(true);
      }
    };
  });

  // 动态操作按钮事件
  document.querySelectorAll('#body [data-act]').forEach((btn) => {
    btn.onclick = () => {
      const act = btn.dataset.act;
      // [FIX-2] 增删动态项前先整块回写，避免重渲染丢掉未失焦的输入值
      collectFormData();

      if (act === 'add-level-row') {
        const levels = getVal('favour_levels', []) || [];
        const last = levels[levels.length - 1] || { max: -101 };
        levels.push({
          min: (Number(last.max) || -101) + 1,
          max: (Number(last.max) || -101) + 50,
          name: '等级 ' + (levels.length + 1),
          desc: ''
        });
        markDirty(true);
        renderTab('levels');
      } else if (act === 'del-level-row') {
        const levels = getVal('favour_levels', []) || [];
        levels.splice(+btn.dataset.idx, 1);
        markDirty(true);
        renderTab('levels');
      } else if (act === 'add-adv-row') {
        const rules = getVal('favour_decay.advanced_rules', []) || [];
        rules.push({ min_favour: 0, max_favour: 100, inactive_days: 7, decay_amount: 5, floor: null });
        markDirty(true);
        renderTab('decay');
      } else if (act === 'del-adv-row') {
        const rules = getVal('favour_decay.advanced_rules', []) || [];
        rules.splice(+btn.dataset.idx, 1);
        markDirty(true);
        renderTab('decay');
      } else if (act === 'add-list-item') {
        const list = getVal(btn.dataset.path, []) || [];
        list.push('');
        markDirty(true);
        renderTab(currentTabName());
      } else if (act === 'del-list-item') {
        const list = getVal(btn.dataset.path, []) || [];
        list.splice(+btn.dataset.idx, 1);
        markDirty(true);
        renderTab(currentTabName());
      }
    };
  });
}

// ==================== 收集表单数据 ====================

function collectFormData() {
  document.querySelectorAll('#body [data-p]').forEach((el) => {
    const path = el.dataset.p;
    // 定制下拉的外层容器也带 data-p，真正的值在它内部的隐藏 input 上
    if (el.tagName === 'DIV' && el.hasAttribute('data-custom-select')) return;

    if (el.type === 'checkbox') {
      setVal(path, el.checked);
    } else if (el.type === 'number') {
      const valStr = String(el.value).trim();
      setVal(path, valStr === '' ? null : parseFloat(valStr));
    } else if (el.type === 'hidden') {
      const val = String(el.value).trim();
      if (val === 'true') setVal(path, true);
      else if (val === 'false') setVal(path, false);
      else setVal(path, val);
    } else if (el.tagName === 'SELECT') {
      const val = String(el.value).trim();
      if (val === 'true') setVal(path, true);
      else if (val === 'false') setVal(path, false);
      else setVal(path, val);
    } else {
      setVal(path, el.value);
    }
  });

  // 收集字符串数组
  const listGroups = {};
  document.querySelectorAll('[data-list-p]').forEach((el) => {
    const path = el.dataset.listP;
    if (!listGroups[path]) listGroups[path] = [];
    listGroups[path].push(String(el.value).trim());
  });
  for (const [path, items] of Object.entries(listGroups)) setVal(path, items);

  const tab = currentTabName();
  if (tab === 'levels') {
    const levels = [];
    for (let i = 0; ; i++) {
      const minInp = document.getElementById('lv-min-' + i);
      if (!minInp) break;
      const maxInp = document.getElementById('lv-max-' + i);
      const nameInp = document.getElementById('lv-name-' + i);
      const descInp = document.getElementById('lv-desc-' + i);
      levels.push({
        min: parseInt(minInp.value) || 0,
        max: parseInt(maxInp ? maxInp.value : '') || 0,
        name: (nameInp ? nameInp.value : '') || '',
        desc: (descInp ? descInp.value : '') || ''
      });
    }
    if (levels.length) setVal('favour_levels', levels);
  } else if (tab === 'decay' && getVal('favour_decay.mode', 'linear') === 'advanced') {
    const advs = [];
    for (let i = 0; ; i++) {
      const minInp = document.getElementById('adv-min-' + i);
      if (!minInp) break;
      const maxInp = document.getElementById('adv-max-' + i);
      const daysInp = document.getElementById('adv-days-' + i);
      const amtInp = document.getElementById('adv-amt-' + i);
      const floorInp = document.getElementById('adv-floor-' + i);
      const floorVal = floorInp ? String(floorInp.value).trim() : '';
      advs.push({
        min_favour: parseInt(minInp.value) || 0,
        max_favour: parseInt(maxInp ? maxInp.value : '') || 0,
        inactive_days: parseInt(daysInp ? daysInp.value : '') || 7,
        decay_amount: parseInt(amtInp ? amtInp.value : '') || 5,
        floor: floorVal === '' ? null : parseInt(floorVal) || 0
      });
    }
    if (advs.length) setVal('favour_decay.advanced_rules', advs);
  }
}

// ==================== 保存配置 ====================

async function saveConfig() {
  try {
    status('正在保存...', 'loading');
    collectFormData();

    // 校验分级规则（与 config_manager.update_from_webui 的后端校验保持一致）
    const levels = getVal('favour_levels', []) || [];
    if (levels.length < 3) {
      throw new Error('好感度分级至少需要配置 3 个级别');
    }

    const sorted = [...levels].sort((a, b) => a.min - b.min);
    for (let i = 0; i < sorted.length - 1; i++) {
      if (sorted[i].max >= sorted[i + 1].min) {
        throw new Error(`分级区间重叠："${sorted[i].name}" (${sorted[i].min}~${sorted[i].max}) 与 "${sorted[i + 1].name}" (${sorted[i + 1].min}~${sorted[i + 1].max})`);
      }
    }

    for (let i = 0; i < sorted.length; i++) {
      if (i >= 7 && (!sorted[i].desc || !sorted[i].desc.trim())) {
        throw new Error(`第 ${i + 1} 个分级 "${sorted[i].name}" 的人设描述为必填项`);
      }
    }

    const res = await apiPost('config', config);
    if (res && res.success) {
      originalConfig = deepClone(config);
      markDirty(false);
      status('已就绪', 'ok');
      toast('配置已成功保存并热生效', 'ok');
    } else {
      throw new Error((res && res.error) || '保存失败');
    }
  } catch (err) {
    console.error('保存配置错误:', err);
    status('保存失败', 'err');
    toast('保存失败: ' + err.message, 'err', 5000);
  }
}

// ==================== 启动入口 ====================

async function startApp() {
  setupNavTabs();

  const bridge = await waitForBridge(3000);
  if (bridge && typeof bridge.onContext === 'function') {
    // bridge SDK 已自动在 <html> 上设置 data-theme，这里仅作监听占位
    bridge.onContext((ctx) => {
      console.debug('[Favour Lite] context 更新:', ctx);
    });
  }

  await init();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startApp);
} else {
  startApp();
}