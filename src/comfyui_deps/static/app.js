// ── 状态 ──
var state = {
  plugins: [],
  scanned: {},
  backupCounts: {},
  currentPage: 1,
  pageSize: 10,
  searchQuery: '',
  scanAborter: null,
  scanning: false,
  detailPlugin: '',
  configName: 'default',
};
var backupResultTimer = null;

// ── DOM 引用 ──
function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

// ── Toast ──
function toast(msg, type) {
  type = type || 'info';
  var el = document.createElement('div');
  el.className = 'toast-msg toast-' + type;
  el.textContent = msg;
  $('#toast').appendChild(el);
  setTimeout(function () { el.remove(); }, 4000);
}

// ── API 辅助 ──
async function apiGet(url) {
  var r = await fetch(url);
  return r.json();
}

async function apiPost(url, body, signal) {
  var r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: signal,
  });
  return r.json().then(function (data) { return { ok: r.ok, status: r.status, data: data }; });
}

// ── 模态对话框 ──
function showModal(title, body, buttons) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = body;
  $('#modal-footer').innerHTML = '';
  buttons.forEach(function (b) {
    var btn = document.createElement('button');
    btn.className = 'btn ' + (b.cls || '');
    btn.textContent = b.label;
    btn.onclick = function () {
      hideModal();
      if (b.action) b.action();
    };
    $('#modal-footer').appendChild(btn);
  });
  $('#modal').classList.remove('hidden');
}

function hideModal() { $('#modal').classList.add('hidden'); }
$('.modal-close').onclick = hideModal;
$('#modal').onclick = function (e) { if (e.target === $('#modal')) hideModal(); };

// ── 清除备份结果 ──
function clearBackupResultLater() {
  if (backupResultTimer) clearTimeout(backupResultTimer);
  backupResultTimer = setTimeout(function () {
    var el = $('#detail-backup-result');
    if (el) { el.classList.add('hidden'); el.innerHTML = ''; }
  }, 30000);
}

// ── 标签页 ──
$$('.tab').forEach(function (t) {
  t.onclick = function () {
    $$('.tab').forEach(function (x) { x.classList.remove('active'); });
    $$('.tab-content').forEach(function (x) { x.classList.remove('active'); });
    t.classList.add('active');
    var targetTab = $('#tab-' + t.dataset.tab);
    if (targetTab) targetTab.classList.add('active');

    // 清除备份成功提示
    var el = $('#detail-backup-result');
    if (el) { el.classList.add('hidden'); el.innerHTML = ''; }

    if (t.dataset.tab === 'config') loadConfig();
    if (t.dataset.tab === 'detail') openDetail();
  };
});

// ── 打开详情页 ──
function openDetail(pluginName) {
  if (!state.detailPlugin && state.plugins.length > 0) {
    state.detailPlugin = state.plugins[0];
  }
  if (pluginName && state.plugins.indexOf(pluginName) >= 0) {
    state.detailPlugin = pluginName;
    $$('.tab').forEach(function (x) { x.classList.remove('active'); });
    $$('.tab-content').forEach(function (x) { x.classList.remove('active'); });
    var tab = document.querySelector('.tab[data-tab="detail"]');
    if (tab) tab.classList.add('active');
    var content = $('#tab-detail');
    if (content) content.classList.add('active');
  }
  if (state.detailPlugin) {
    $('#detail-plugin-input').value = state.detailPlugin;
  }
  loadDetailCheckCache();
  loadDetailBackups();
  loadFreezeList();
}

// ── 详情: 插件搜索 ──
$('#detail-plugin-input').oninput = function () {
  var q = this.value.trim().toLowerCase();
  var dropdown = $('#detail-plugin-dropdown');
  if (!q) { dropdown.classList.add('hidden'); return; }
  var matches = state.plugins.filter(function (p) { return p.toLowerCase().indexOf(q) >= 0; });
  if (matches.length === 0) { dropdown.classList.add('hidden'); return; }
  dropdown.innerHTML = matches.map(function (p) {
    return '<div class="plugin-dropdown-item" data-name="' + p + '">' + highlightMatch(p, q) + '</div>';
  }).join('');
  dropdown.classList.remove('hidden');
  $$('.plugin-dropdown-item').forEach(function (item) {
    item.onclick = function () {
      state.detailPlugin = this.dataset.name;
      $('#detail-plugin-input').value = state.detailPlugin;
      dropdown.classList.add('hidden');
      refreshDetail();
    };
  });
};

function highlightMatch(text, q) {
  var i = text.toLowerCase().indexOf(q);
  if (i < 0) return text;
  return text.substring(0, i) + '<strong>' + text.substring(i, i + q.length) + '</strong>' + text.substring(i + q.length);
}

$('#detail-plugin-input').onblur = function () {
  var val = this.value.trim();
  if (val && state.plugins.indexOf(val) >= 0) {
    state.detailPlugin = val;
    refreshDetail();
  } else if (state.detailPlugin) {
    this.value = state.detailPlugin;
  }
  setTimeout(function () { $('#detail-plugin-dropdown').classList.add('hidden'); }, 200);
};

$('#detail-plugin-input').onkeydown = function (e) {
  if (e.key === 'Enter') {
    var val = this.value.trim();
    if (val && state.plugins.indexOf(val) >= 0) {
      state.detailPlugin = val;
      $('#detail-plugin-dropdown').classList.add('hidden');
      refreshDetail();
    }
  }
};

function refreshDetail() {
  loadDetailCheckCache();
  loadDetailBackups();
  loadFreezeList();
}

// ── 详情: 检查更新 ──
async function loadDetailCheckCache() {
  if (!state.detailPlugin) return;
  var r = await apiGet('/api/cache/check?name=' + encodeURIComponent(state.detailPlugin));
  var hint = $('#detail-check-hint');
  if (r.value) {
    hint.classList.remove('hidden');
    renderCheckResult(r.value);
  } else {
    hint.classList.add('hidden');
    $('#detail-check-result').classList.add('hidden');
  }
}

async function detailCheck() {
  if (!state.detailPlugin) { toast('请先选择插件。', 'info'); return; }
  var cacheR = await apiGet('/api/cache/check?name=' + encodeURIComponent(state.detailPlugin));
  if (cacheR.value) {
    renderCheckResult(cacheR.value);
    $('#detail-check-hint').classList.remove('hidden');
    return;
  }

  $('#btn-detail-check').disabled = true;
  $('#btn-detail-check').textContent = '检查中...';
  $('#detail-check-result').classList.remove('hidden', 'error', 'warning', 'success');
  $('#detail-check-result').textContent = '正在获取...';
  $('#detail-check-hint').classList.add('hidden');

  var resp = await apiPost('/api/check', { name: state.detailPlugin });
  $('#btn-detail-check').disabled = false;
  $('#btn-detail-check').textContent = '检查更新';

  if (resp.ok && resp.data.status !== 'error') {
    await apiPost('/api/cache/check', { name: state.detailPlugin, value: resp.data });
  }
  renderCheckResult(resp.ok ? resp.data : { status: 'error', message: resp.data.error || '未知错误' });
}

function renderCheckResult(data) {
  var el = $('#detail-check-result');
  el.classList.remove('hidden', 'error', 'warning', 'success');
  if (data.status === 'up_to_date') {
    el.classList.add('success');
    el.textContent = '已是最新版本 (' + (data.branch || '?') + ' 分支)。';
  } else if (data.status === 'updates') {
    el.classList.add('warning');
    el.textContent = '有待更新 (' + (data.branch || '?') + ' 分支):\n\n' + (data.log || '');
  } else if (data.status === 'non_git') {
    el.classList.add('error');
    el.textContent = '非 Git 仓库。';
  } else {
    el.classList.add('error');
    el.textContent = data.message || '未知错误';
  }

  // 填充分支选择器
  var sel = $('#detail-update-branch');
  sel.innerHTML = '<option value="">(默认检测)</option>';
  var branches = data.remote_branches || [];
  for (var i = 0; i < branches.length; i++) {
    var opt = document.createElement('option');
    opt.value = branches[i];
    opt.textContent = branches[i];
    if (branches[i] === data.branch) { opt.selected = true; }
    sel.appendChild(opt);
  }
}

// ── 详情: 更新 ──
async function detailUpdate() {
  if (!state.detailPlugin) { toast('请先选择插件。', 'info'); return; }
  var skipBackup = $('#detail-update-skip-backup').checked;
  var skipDeps = $('#detail-update-skip-deps').checked;
  var branch = $('#detail-update-branch').value;

  $('#btn-detail-update').disabled = true;
  $('#btn-detail-update').textContent = '更新中...';
  $('#detail-update-result').classList.remove('hidden', 'error', 'warning', 'success');
  $('#detail-update-result').textContent = '正在执行...';

  var resp = await apiPost('/api/update', { name: state.detailPlugin, skip_backup: skipBackup, skip_deps: skipDeps, branch: branch });
  var el = $('#detail-update-result');
  el.classList.remove('hidden');
  if (resp.ok) {
    if (resp.data.status === 'up_to_date') {
      el.classList.add('success');
      el.textContent = '已是最新版本。';
    } else {
      el.classList.add('success');
      var txt = '';
      resp.data.steps.forEach(function (s) {
        var icon = s.status === 'ok' ? '[OK]' : s.status === 'error' ? '[XX]' : s.status === 'skipped' ? '[--]' : '[!!]';
        txt += icon + ' ' + s.name + (s.detail ? ': ' + s.detail : '') + '\n';
      });
      el.textContent = txt;
      toast('更新完成。', 'success');
      if (state.scanned[state.detailPlugin]) delete state.scanned[state.detailPlugin];
      apiPost('/api/cache/check', { name: state.detailPlugin, value: null });
    }
  } else {
    el.classList.add('error');
    if (resp.data.steps) {
      var txt2 = '';
      resp.data.steps.forEach(function (s) {
        txt2 += '[' + s.status.toUpperCase() + '] ' + s.name + (s.detail ? ': ' + s.detail : '') + '\n';
      });
      el.textContent = txt2;
    } else {
      el.textContent = '错误: ' + (resp.data.error || '未知');
    }
  }
  $('#btn-detail-update').disabled = false;
  $('#btn-detail-update').textContent = '开始更新';
}

// ── 详情: 备份 ──
async function loadDetailBackups() {
  if (!state.detailPlugin) return;
  var data = await apiGet('/api/backups?target=' + encodeURIComponent(state.detailPlugin));
  var container = $('#detail-backup-list');
  container.innerHTML = '';

  var countEl = $('#detail-backup-count');
  if (countEl) countEl.textContent = '(' + (data.entries ? data.entries.length : 0) + ' 个)';

  if (!data.entries || data.entries.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted);padding:8px;">暂无此插件的备份</div>';
    return;
  }
  var html = '';
  data.entries.forEach(function (e) {
    html +=
      '<div class="backup-entry">' +
      '<div class="backup-info">' +
      '<span class="backup-name">' + e.name + '</span>' +
      '<span class="backup-meta">大小: ' + (e.size_fmt || '-') + ' | 创建: ' + e.created + '</span>' +
      '</div>' +
      '<div class="backup-actions">' +
      '<button class="btn btn-sm btn-warning rollback-detail-btn" data-path="' + e.path + '">回滚</button>' +
      '<button class="btn btn-sm btn-danger delete-backup-btn" data-path="' + e.path + '" data-name="' + e.name + '">删除</button>' +
      '</div>' +
      '</div>';
  });
  container.innerHTML = html;

  $$('#detail-backup-list .rollback-detail-btn').forEach(function (btn) {
    btn.onclick = function () {
      showModal('确认回滚', '<p>将 <strong>' + state.detailPlugin + '</strong> 恢复到备份 <strong>' + this.dataset.path + '</strong>？</p><p style="color:var(--yellow);margin-top:8px;">这将覆盖当前目录内容。</p>', [
        { label: '取消', cls: '' },
        { label: '执行回滚', cls: 'btn-warning', action: function () {
          detailRollbackDirect(btn.dataset.path);
        }},
      ]);
    };
  });

  $$('#detail-backup-list .delete-backup-btn').forEach(function (btn) {
    btn.onclick = function () {
      showModal('确认删除', '<p>删除备份 <strong>' + this.dataset.name + '</strong>？</p><p style="color:var(--red);margin-top:8px;">此操作不可撤销。</p>', [
        { label: '取消', cls: '' },
        { label: '确认删除', cls: 'btn-danger', action: function () {
          deleteBackup(btn.dataset.path);
        }},
      ]);
    };
  });
}

async function detailBackupDir() {
  if (!state.detailPlugin) { toast('请先选择插件。', 'info'); return; }
  $('#btn-detail-backup-dir').disabled = true;
  $('#btn-detail-backup-dir').textContent = '备份中...';
  var resp = await apiPost('/api/backups/create', { name: state.detailPlugin, deps: false });
  $('#btn-detail-backup-dir').disabled = false;
  $('#btn-detail-backup-dir').textContent = '备份目录';
  var el = $('#detail-backup-result');
  el.classList.remove('hidden', 'error', 'success');
  if (resp.ok) {
    el.classList.add('success');
    var r = resp.data.results[0];
    el.textContent = '备份成功: ' + (r ? r.path : '');
    loadDetailBackups();
    loadPlugins();
    clearBackupResultLater();
  } else {
    el.classList.add('error');
    el.textContent = '备份失败: ' + (resp.data.error || '未知错误');
    clearBackupResultLater();
  }
}

async function deleteBackup(path) {
  var resp = await apiPost('/api/backups/delete', { path: path });
  if (resp.ok) {
    toast('备份已删除。', 'success');
    loadDetailBackups();
    loadPlugins();
  } else {
    toast('删除失败: ' + (resp.data.error || '未知错误'), 'error');
  }
}

async function detailRollbackDirect(backupPath) {
  var resp = await apiPost('/api/rollback', { backup: backupPath, name: state.detailPlugin, force: false });
  if (resp.ok) {
    toast('回滚完成。', 'success');
    loadDetailBackups();
  } else {
    toast('回滚失败: ' + (resp.data.error || '未知错误'), 'error');
  }
}

// ── 详情: 依赖 ──
async function detailDepsRead(install) {
  if (!state.detailPlugin) { toast('请先选择插件。', 'info'); return; }
  var cfg = await apiGet('/api/config');
  var reqPath = (cfg.custom_nodes || '') + '/' + state.detailPlugin + '/requirements.txt';
  var action = install ? '/api/deps/install' : '/api/deps/check';

  var btn = install ? $('#btn-detail-deps-read-install') : $('#btn-detail-deps-read');
  btn.disabled = true;
  btn.textContent = install ? '安装中...' : '读取中...';
  var el = $('#detail-deps-result');
  el.classList.remove('hidden', 'error', 'warning', 'success');
  el.textContent = '正在处理...';

  var resp = await apiPost(action, { name: state.detailPlugin });
  btn.disabled = false;
  btn.textContent = install ? '安装当前插件依赖' : '查看当前插件依赖';
  el.classList.remove('hidden', 'error', 'warning', 'success');
  if (resp.ok) {
    el.classList.add('success');
    el.textContent = '[读取依赖] 路径: ' + reqPath + '\n\n' + (resp.data.output || resp.data.status || '完成');
  } else if (resp.status === 404) {
    el.classList.add('warning');
    el.textContent = '未找到 requirements.txt: ' + reqPath;
  } else {
    el.classList.add('error');
    el.textContent = '错误: ' + (resp.data.error || '未知');
  }
}

async function detailDepsManual(action) {
  var pkg = $('#detail-deps-package').value.trim();
  if (!pkg) { toast('请输入包名。', 'info'); return; }

  var url = action === 'dryrun' ? '/api/deps/check' : '/api/deps/install';
  var resp = await apiPost(url, { package: pkg });
  var el = $('#detail-deps-result');
  el.classList.remove('hidden', 'error', 'warning', 'success');
  if (resp.ok) {
    if (resp.data.status === 'warning') {
      el.classList.add('warning');
      el.textContent = '核心库冲突:\n' + resp.data.conflicts.join('\n');
    } else {
      el.classList.add('success');
      el.textContent = resp.data.output || resp.data.status;
    }
  } else {
    el.classList.add('error');
    el.textContent = '错误: ' + (resp.data.error || '未知');
  }
}

async function detailFreeze() {
  $('#btn-detail-deps-freeze').disabled = true;
  $('#btn-detail-deps-freeze').textContent = '备份中...';
  var resp = await apiPost('/api/deps/freeze', { plugin_name: state.detailPlugin || '' });
  $('#btn-detail-deps-freeze').disabled = false;
  $('#btn-detail-deps-freeze').textContent = '开始备份依赖';

  var el = $('#detail-deps-result');
  el.classList.remove('hidden', 'error', 'warning', 'success');
  if (resp.ok && resp.data.status === 'ok') {
    el.classList.add('success');
    el.textContent = '备份成功: ' + resp.data.freeze_path;
    loadFreezeList();
  } else {
    el.classList.add('error');
    el.textContent = '备份失败: ' + (resp.data.error || '未知错误');
  }
}

async function loadFreezeList() {
  var data = await apiGet('/api/deps/freeze-list');
  var container = $('#detail-freeze-list');
  container.innerHTML = '';
  if (!data.entries || data.entries.length === 0) {
    container.innerHTML = '<div style="color:var(--text-muted);padding:8px;">暂无备份文件</div>';
    return;
  }
  var html = '';
  data.entries.forEach(function (e) {
    html +=
      '<div class="freeze-entry">' +
      '<div class="freeze-info">' +
      '<span class="freeze-name">' + e.name + '</span>' +
      '<span class="freeze-meta">大小: ' + e.size_fmt + (e.plugin_name ? ' | 插件: ' + e.plugin_name : '') + (e.created ? ' | ' + e.created : '') + '</span>' +
      '</div>' +
      '<div class="freeze-actions">' +
      '<button class="btn btn-sm freeze-dryrun" data-path="' + e.path + '">模拟运行</button>' +
      '<button class="btn btn-sm btn-warning freeze-restore" data-path="' + e.path + '">还原</button>' +
      '<button class="btn btn-sm btn-danger freeze-delete" data-path="' + e.path + '" data-name="' + e.name + '">删除</button>' +
      '</div>' +
      '</div>';
  });
  container.innerHTML = html;

  $$('#detail-freeze-list .freeze-dryrun').forEach(function (btn) {
    btn.onclick = async function () {
      btn.disabled = true;
      btn.textContent = '运行中...';
      var r2 = await apiPost('/api/deps/restore', { snapshot_path: this.dataset.path, dry_run: true });
      btn.disabled = false;
      btn.textContent = '模拟运行';
      var el = $('#detail-deps-result');
      el.classList.remove('hidden', 'error', 'warning', 'success');
      if (r2.ok) {
        el.classList.add('success');
        el.textContent = r2.data.output || '(空)';
        toast('模拟运行完成。', 'success');
      } else {
        el.classList.add('error');
        el.textContent = '错误: ' + (r2.data.error || '未知');
        toast('模拟运行失败。', 'error');
      }
    };
  });

  $$('#detail-freeze-list .freeze-restore').forEach(function (btn) {
    btn.onclick = function () {
      showModal('确认还原依赖', '<p>从快照文件 <strong>' + this.dataset.path + '</strong> 还原依赖？</p>', [
        { label: '取消', cls: '' },
        { label: '确认还原', cls: 'btn-warning', action: async function () {
          var resp = await apiPost('/api/deps/restore', { snapshot_path: btn.dataset.path, force: false });
          var el = $('#detail-deps-result');
          el.classList.remove('hidden', 'error', 'warning', 'success');
          if (resp.ok) {
            el.classList.add('success');
            el.textContent = '还原成功。';
            toast('依赖还原成功。', 'success');
          } else {
            el.classList.add('error');
            el.textContent = '还原失败: ' + (resp.data.error || '未知');
          }
          el.style.display = 'block';
        }},
      ]);
    };
  });

  $$('#detail-freeze-list .freeze-delete').forEach(function (btn) {
    btn.onclick = function () {
      showModal('确认删除', '<p>删除备份文件 <strong>' + this.dataset.name + '</strong>？</p>', [
        { label: '取消', cls: '' },
        { label: '确认删除', cls: 'btn-danger', action: async function () {
          var resp = await apiPost('/api/deps/freeze-delete', { path: btn.dataset.path });
          if (resp.ok) {
            toast('已删除。', 'success');
            loadFreezeList();
          } else {
            toast('删除失败: ' + (resp.data.error || '未知错误'), 'error');
          }
        }},
      ]);
    };
  });
}

// ── 搜索过滤 ──
function getFilteredPlugins() {
  if (!state.searchQuery) return state.plugins;
  var q = state.searchQuery.toLowerCase();
  return state.plugins.filter(function (p) { return p.toLowerCase().indexOf(q) >= 0; });
}

// ── 加载插件列表 ──
async function loadPlugins() {
  var data = await apiGet('/api/plugins');
  state.plugins = data.plugins || [];
  state.backupCounts = data.backup_counts || {};
  state.scanned = {};
  state.currentPage = 1;
  state.searchQuery = '';
  $('#scan-search').value = '';
  loadScanCache();
  refreshScanView();
  if (state.plugins.length > 0 && !state.detailPlugin) {
    state.detailPlugin = state.plugins[0];
  }
}

async function loadScanCache() {
  var r = await apiGet('/api/cache/scan');
  if (r.value) {
    Object.keys(r.value).forEach(function (k) {
      state.scanned[k] = r.value[k];
    });
    refreshScanView();
    updateScanStats();
    updateScanSummary();
  }
}

async function saveScanCache() {
  await apiPost('/api/cache/scan', { key: 'scan_results', value: state.scanned });
}

function getPagePlugins() {
  var filtered = getFilteredPlugins();
  var start = (state.currentPage - 1) * state.pageSize;
  return filtered.slice(start, start + state.pageSize);
}

function getTotalPages() {
  var filtered = getFilteredPlugins();
  return Math.max(1, Math.ceil(filtered.length / state.pageSize));
}

function refreshScanView() {
  renderPluginList();
  renderPagination();
  updateScanStats();
}

// ── 渲染插件列表 ──
function renderPluginList() {
  var rows = $('#plugin-rows');
  var pagePlugins = getPagePlugins();
  rows.innerHTML = '';
  if (state.plugins.length === 0) {
    rows.innerHTML = '<div class="plugin-row"><span style="grid-column:1/-1;color:var(--text-muted);text-align:center;padding:20px;">未发现插件</span></div>';
    return;
  }
  if (pagePlugins.length === 0) {
    rows.innerHTML = '<div class="plugin-row"><span style="grid-column:1/-1;color:var(--text-muted);text-align:center;padding:20px;">没有匹配的插件</span></div>';
    return;
  }
  pagePlugins.forEach(function (name) {
    var s = state.scanned[name];
    var backups = state.backupCounts[name] || 0;
    var row = document.createElement('div');
    row.className = 'plugin-row';
    if (!s) {
      row.classList.add('pending');
      var actions = '<button class="btn btn-sm scan-single" data-name="' + name + '">扫描</button>' +
        ' <button class="btn btn-sm goto-detail" data-name="' + name + '">详情</button>';
      row.innerHTML =
        '<span class="col-status"><span class="status-badge status-scanning">未扫描</span></span>' +
        '<span class="col-type">-</span>' +
        '<span class="col-name">' + name + '</span>' +
        '<span class="col-branch">-</span>' +
        '<span class="col-backups">' + (backups > 0 ? '<span class="backup-count-badge">' + backups + '</span>' : '0') + '</span>' +
        '<span class="col-actions">' + actions + '</span>';
    } else {
      var statusHtml = '';
      var typeHtml = '';
      var branchHtml = s.remote_branch || '-';
      var actionsHtml = '';
      if (!s.has_git) {
        statusHtml = '<span class="status-badge status-zip">ZIP</span>';
        typeHtml = '<span class="type-badge type-zip">zip</span>';
        branchHtml = '-';
      } else if (s.error) {
        statusHtml = '<span class="status-badge status-error">错误</span>';
        typeHtml = '<span class="type-badge type-git">git</span>';
        branchHtml = s.error;
      } else if (s.has_updates) {
        statusHtml = '<span class="status-badge status-updates">' + s.commit_count + ' 个提交</span>';
        typeHtml = '<span class="type-badge type-git">git</span>';
        actionsHtml = '<button class="btn btn-sm btn-primary update-single" data-name="' + name + '">更新</button>';
      } else {
        statusHtml = '<span class="status-badge status-ok">已是最新</span>';
        typeHtml = '<span class="type-badge type-git">git</span>';
      }
      actionsHtml +=
        ' <button class="btn btn-sm scan-single" data-name="' + name + '">重新扫描</button>' +
        ' <button class="btn btn-sm goto-detail" data-name="' + name + '">详情</button>';
      row.innerHTML =
        '<span class="col-status">' + statusHtml + '</span>' +
        '<span class="col-type">' + typeHtml + '</span>' +
        '<span class="col-name">' + name + '</span>' +
        '<span class="col-branch">' + branchHtml + '</span>' +
        '<span class="col-backups">' + (backups > 0 ? '<span class="backup-count-badge">' + backups + '</span>' : '0') + '</span>' +
        '<span class="col-actions">' + actionsHtml + '</span>';
    }
    rows.appendChild(row);
  });

  $$('.update-single').forEach(function (btn) {
    btn.onclick = function () {
      openDetail(btn.dataset.name);
    };
  });
  $$('.scan-single').forEach(function (btn) {
    btn.onclick = function () { scanSingle(btn.dataset.name); };
  });
  $$('.goto-detail').forEach(function (btn) {
    btn.onclick = function () { openDetail(btn.dataset.name); };
  });
}

// ── 渲染分页 ──
function renderPagination() {
  var totalPages = getTotalPages();
  var container = $('#pagination');
  container.innerHTML = '';
  if (totalPages <= 1) {
    container.innerHTML = '<span class="page-info">共 ' + state.plugins.length + ' 个插件' + (state.searchQuery ? ' (已过滤)' : '') + '</span>';
    return;
  }
  var firstBtn = document.createElement('button');
  firstBtn.textContent = '最前';
  firstBtn.disabled = state.currentPage === 1;
  firstBtn.onclick = function () { if (state.currentPage > 1) { state.currentPage = 1; refreshScanView(); } };
  container.appendChild(firstBtn);

  var prevBtn = document.createElement('button');
  prevBtn.textContent = '上一页';
  prevBtn.disabled = state.currentPage === 1;
  prevBtn.onclick = function () { if (state.currentPage > 1) { state.currentPage--; refreshScanView(); } };
  container.appendChild(prevBtn);

  var start = Math.max(1, state.currentPage - 2);
  var end = Math.min(totalPages, state.currentPage + 2);
  for (var i = start; i <= end; i++) {
    var btn = document.createElement('button');
    btn.textContent = i;
    if (i === state.currentPage) btn.classList.add('active');
    btn.onclick = (function (p) { return function () { state.currentPage = p; refreshScanView(); }; })(i);
    container.appendChild(btn);
  }
  var nextBtn = document.createElement('button');
  nextBtn.textContent = '下一页';
  nextBtn.disabled = state.currentPage === totalPages;
  nextBtn.onclick = function () { if (state.currentPage < totalPages) { state.currentPage++; refreshScanView(); } };
  container.appendChild(nextBtn);

  var lastBtn = document.createElement('button');
  lastBtn.textContent = '最后';
  lastBtn.disabled = state.currentPage === totalPages;
  lastBtn.onclick = function () { if (state.currentPage < totalPages) { state.currentPage = totalPages; refreshScanView(); } };
  container.appendChild(lastBtn);

  var jumpSpan = document.createElement('span');
  jumpSpan.className = 'page-jump';
  var jumpInput = document.createElement('input');
  jumpInput.type = 'number';
  jumpInput.min = 1;
  jumpInput.max = totalPages;
  jumpInput.placeholder = state.currentPage;
  jumpInput.className = 'jump-input';
  var jumpBtn = document.createElement('button');
  jumpBtn.textContent = '跳转';
  jumpBtn.className = 'btn-sm';
  jumpBtn.onclick = function () { var p = parseInt(jumpInput.value); if (p >= 1 && p <= totalPages) { state.currentPage = p; refreshScanView(); } };
  jumpInput.onkeydown = function (e) { if (e.key === 'Enter') { var p = parseInt(jumpInput.value); if (p >= 1 && p <= totalPages) { state.currentPage = p; refreshScanView(); } } };
  jumpSpan.appendChild(jumpInput);
  jumpSpan.appendChild(jumpBtn);
  container.appendChild(jumpSpan);

  var info = document.createElement('span');
  info.className = 'page-info';
  info.textContent = '第 ' + state.currentPage + '/' + totalPages + ' 页 (共 ' + state.plugins.length + ' 个)';
  container.appendChild(info);
}

// ── 扫描 ──
function startScan() {
  state.scanAborter = new AbortController();
  state.scanning = true;
  $('#btn-scan-stop').disabled = false;
  $('#btn-scan-page').disabled = true;
  $('#btn-scan-all').disabled = true;
}
function endScan() {
  state.scanAborter = null;
  state.scanning = false;
  $('#btn-scan-stop').disabled = true;
  $('#btn-scan-page').disabled = false;
  $('#btn-scan-all').disabled = false;
  saveScanCache();
}
function stopScan() {
  if (state.scanAborter) { state.scanAborter.abort(); toast('扫描已停止。', 'info'); }
}
function isAborted() { return state.scanAborter && state.scanAborter.signal.aborted; }

async function scanSingle(name) {
  startScan();
  var rows = $$('.plugin-row');
  rows.forEach(function (row) {
    var colName = row.querySelector('.col-name');
    if (!colName || colName.textContent !== name) return;
    row.querySelector('.col-status').innerHTML = '<span class="spinner"></span>';
    row.querySelector('.col-branch').textContent = '扫描中...';
    row.querySelector('.col-actions').innerHTML = '';
  });
  try {
    var resp = await apiPost('/api/scan', { names: [name] }, state.scanAborter.signal);
    if (resp.ok && resp.data.results && resp.data.results.length > 0) {
      state.scanned[resp.data.results[0].name] = resp.data.results[0];
      updateScanStats(); updateScanSummary();
    }
  } catch (e) { if (e.name !== 'AbortError') toast('扫描失败: ' + e.message, 'error'); }
  endScan(); renderPluginList();
}

async function scanCurrentPage() {
  var names = getPagePlugins();
  var unscanned = names.filter(function (n) { return !state.scanned[n]; });
  if (unscanned.length === 0) { toast('本页插件已全部扫描。', 'info'); return; }
  startScan(); renderPluginList();
  try {
    var resp = await apiPost('/api/scan', { names: names }, state.scanAborter.signal);
    if (resp.ok) {
      resp.data.results.forEach(function (r) { state.scanned[r.name] = r; });
      updateScanStats();
    } else { toast('扫描失败: ' + (resp.data.error || '未知错误'), 'error'); }
  } catch (e) { if (e.name !== 'AbortError') toast('扫描失败: ' + e.message, 'error'); }
  endScan(); renderPluginList(); updateScanSummary();
}

function showScanAllWarning() {
  var filtered = getFilteredPlugins();
  var total = state.searchQuery ? filtered.length : state.plugins.length;
  showModal('确认扫描全部', '<p>即将扫描 <strong>' + total + '</strong> 个插件。</p>' +
    '<p style="color:var(--yellow);margin-top:12px;">警告：</p>' +
    '<ul style="color:var(--text-muted);padding-left:20px;margin-top:4px;">' +
    '<li>等待时间可能较长</li><li>批量 Git 操作可能被限流</li></ul>',
    [{ label: '取消', cls: '' }, { label: '确认扫描', cls: 'btn-primary', action: doScanAll }]);
}

async function doScanAll() {
  var plugins = getFilteredPlugins();
  if (plugins.length === 0) return;
  if (!state.searchQuery) state.scanned = {};
  startScan(); $('#btn-scan-all').textContent = '扫描中...';
  var totalPages = Math.ceil(plugins.length / state.pageSize);
  for (var p = 0; p < totalPages; p++) {
    if (isAborted()) break;
    var start = p * state.pageSize;
    var names = plugins.slice(start, start + state.pageSize);
    state.currentPage = p + 1; refreshScanView();
    try {
      var resp = await apiPost('/api/scan', { names: names }, state.scanAborter.signal);
      if (resp.ok) { resp.data.results.forEach(function (r) { state.scanned[r.name] = r; }); }
      updateScanStats();
    } catch (e) { if (e.name === 'AbortError') break; }
  }
  state.currentPage = 1;
  endScan(); $('#btn-scan-all').textContent = '扫描全部';
  refreshScanView(); updateScanSummary();
  if (!isAborted()) toast('扫描完成。', 'success');
}

function updateScanStats() {
  var hasGit = 0, hasUp = 0, total = 0;
  Object.keys(state.scanned).forEach(function (k) {
    var s = state.scanned[k]; total++;
    if (s.has_git) { hasGit++; if (s.has_updates) hasUp++; }
  });
  $('#scan-stats').textContent = '已扫描: ' + total + '/' + state.plugins.length + ' (git: ' + hasGit + ', 待更新: ' + hasUp + ')';
}
function updateScanSummary() {
  var hasGit = 0, hasUp = 0, total = 0;
  Object.keys(state.scanned).forEach(function (k) {
    var s = state.scanned[k]; total++;
    if (s.has_git) { hasGit++; if (s.has_updates) hasUp++; }
  });
  var el = $('#scan-summary');
  if (total > 0) {
    el.classList.remove('hidden');
    el.innerHTML = '汇总: <strong>' + total + '/' + state.plugins.length + '</strong> 已扫描 &mdash; ' +
      '<strong>' + hasGit + '</strong> 个 git 仓库, <strong>' + hasUp + '</strong> 个有待更新。';
  } else { el.classList.add('hidden'); }
}

// ── 配置 ──
async function loadConfig() {
  var data = await apiGet('/api/config');
  state.configName = data.config_name || 'default';
  $('#cfg-comfyui_root').value = data.comfyui_root || '';
  $('#cfg-custom_nodes').value = data.custom_nodes || '';
  $('#cfg-python_home').value = data.python_home || '';
  $('#cfg-git_exe').value = data.git_exe || '';
  $('#cfg-backup_dir').value = data.backup_dir || '';
  $('#cfg-log_dir').value = data.log_dir || '.\\log';
  $('#cfg-cache_dir').value = data.cache_dir || '.\\cache';
  $('#cfg-core_libs').value = (data.core_libs || []).join(', ');

  var hintEl = document.querySelector('#tab-config .config-hint');
  var status = $('#config-status');
  if (data.configured && data.errors.length === 0) {
    if (hintEl) hintEl.className = 'config-hint ready';
    status.textContent = '[' + state.configName + '] 配置有效。';
  } else if (data.errors.length > 0) {
    if (hintEl) hintEl.className = 'config-hint empty';
    status.textContent = '[' + state.configName + '] 配置异常，请检查: ' + data.errors.join('; ');
  } else {
    if (hintEl) hintEl.className = 'config-hint empty';
    status.textContent = '[' + state.configName + '] 配置未设置，请填写下方路径。';
  }
  if (!data.configured) showWelcomeScreen();

  loadAllDirSizes();
  loadProfileList();
  return data;
}

async function loadAllDirSizes() {
  var targets = ['comfyui_root', 'custom_nodes', 'python_home', 'backup_dir', 'log_dir', 'cache_dir'];
  targets.forEach(function (key) {
    var input = $('.dir-size[data-target="cfg-' + key + '"]');
    if (!input) return;
    var pathInput = $('#cfg-' + key);
    if (!pathInput || !pathInput.value.trim()) { input.textContent = ''; return; }
    updateDirSize(key, pathInput.value.trim());
  });
}

async function updateDirSize(key, path) {
  var el = document.querySelector('.dir-size[data-target="cfg-\\' + key + '"]');
  if (!el) return;
  var data = await apiGet('/api/dirs/size?path=' + encodeURIComponent(path));
  el.textContent = data.size_fmt || '';
}

function showWelcomeScreen() {
  $$('.tab').forEach(function (x) { x.classList.remove('active'); });
  $$('.tab-content').forEach(function (x) { x.classList.remove('active'); });
  var tab = document.querySelector('.tab[data-tab="config"]');
  if (tab) tab.classList.add('active');
  var content = $('#tab-config');
  if (content) content.classList.add('active');
  toast('欢迎！请先配置 ComfyUI 路径。', 'info');
}

async function saveConfig() {
  var data = {
    comfyui_root: $('#cfg-comfyui_root').value.trim(),
    custom_nodes: $('#cfg-custom_nodes').value.trim(),
    python_home: $('#cfg-python_home').value.trim(),
    git_exe: $('#cfg-git_exe').value.trim(),
    backup_dir: $('#cfg-backup_dir').value.trim(),
    log_dir: $('#cfg-log_dir').value.trim(),
    cache_dir: $('#cfg-cache_dir').value.trim(),
    core_libs: $('#cfg-core_libs').value.split(',').map(function (s) { return s.trim(); }).filter(Boolean),
  };
  $('#btn-config-save').disabled = true;
  $('#btn-config-save').textContent = '保存中...';
  var resp = await apiPost('/api/config/save', data);
  var el = $('#config-errors');
  var statusEl = $('#config-save-status');
  if (resp.ok) {
    if (resp.data.errors && resp.data.errors.length > 0) {
      el.classList.remove('hidden');
      el.innerHTML = resp.data.errors.map(function (e) { return '<div>' + e + '</div>'; }).join('');
      statusEl.textContent = '';
      toast('已保存（有警告）。', 'info');
    } else {
      el.classList.add('hidden'); el.innerHTML = '';
      statusEl.textContent = '已保存。';
      statusEl.style.color = 'var(--green)';
      statusEl.style.color = 'var(--green)';
      $('#config-status').textContent = '[' + state.configName + '] 配置有效。';
      toast('配置已保存。', 'success');
      loadPlugins();
    }
  } else {
    el.classList.remove('hidden');
    el.innerHTML = '保存失败: ' + (resp.data.error || '未知错误');
    statusEl.textContent = '';
  }
  $('#btn-config-save').disabled = false;
  $('#btn-config-save').textContent = '保存配置';
  loadAllDirSizes();
}

// ── 配置切换 ──
async function loadProfileList() {
  var data = await apiGet('/api/config/list');
  var sel = $('#cfg-profile-select');
  var current = state.configName;
  sel.innerHTML = '';
  if (!data.configs || data.configs.length === 0) {
    var opt = document.createElement('option');
    opt.value = 'default';
    opt.textContent = 'default';
    opt.selected = true;
    sel.appendChild(opt);
    return;
  }
  data.configs.forEach(function (c) {
    var opt = document.createElement('option');
    opt.value = c.name;
    opt.textContent = c.name;
    if (c.name === current) { opt.selected = true; }
    sel.appendChild(opt);
  });
}

async function switchProfile() {
  var name = $('#cfg-profile-select').value;
  if (!name || name === state.configName) return;
  showModal('切换配置', '<p>将切换到配置 <strong>' + name + '</strong>。未保存的更改将丢失。</p>', [
    { label: '取消', cls: '' },
    { label: '确认切换', cls: 'btn-primary', action: async function () {
      var resp = await apiPost('/api/config/switch', { name: name });
      if (resp.ok) {
        state.configName = resp.data.config_name;
        toast('已切换到配置: ' + state.configName, 'success');
        loadConfig();
        loadPlugins();
      } else {
        toast('切换失败: ' + (resp.data.error || '未知错误'), 'error');
      }
    }},
  ]);
}

async function createProfile() {
  var name = prompt('请输入新配置名称:');
  if (!name || !name.trim()) return;
  name = name.trim();
  var resp = await apiPost('/api/config/create', { name: name });
  if (resp.ok) {
    state.configName = name;
    toast('已创建并切换到配置: ' + name, 'success');
    loadConfig();
    loadPlugins();
  } else {
    toast('创建失败: ' + (resp.data.error || '未知错误'), 'error');
  }
}

async function deleteProfile() {
  var name = $('#cfg-profile-select').value;
  if (!name || name === 'default') {
    toast('不能删除 default 配置。', 'info');
    return;
  }
  showModal('删除配置', '<p>将删除配置 <strong>' + name + '</strong>。此操作不可撤销。</p>', [
    { label: '取消', cls: '' },
    { label: '确认删除', cls: 'btn-danger', action: async function () {
      var resp = await apiPost('/api/config/delete', { name: name });
      if (resp.ok) {
        state.configName = 'default';
        toast('已删除配置: ' + name, 'success');
        loadConfig();
        loadPlugins();
      } else {
        toast('删除失败: ' + (resp.data.error || '未知错误'), 'error');
      }
    }},
  ]);
}

// ── 目录导航 ──
$$('.btn-dir-open').forEach(function (btn) {
  btn.onclick = function () {
    var targetId = this.dataset.target;
    var input = $('#' + targetId);
    if (!input) return;
    var path = input.value.trim();
    if (!path) { toast('请先填写路径。', 'info'); return; }
    apiPost('/api/open-folder', { path: path }).then(function (resp) {
      if (resp.ok) {
        toast('已打开文件夹: ' + path, 'success');
      } else {
        toast('无法打开: ' + (resp.data.error || '未知错误'), 'error');
      }
    }).catch(function () {
      toast('请求失败，请检查服务是否运行。', 'error');
    });
  };
});

// ── 详情页导航按钮 ──
$('#btn-detail-goto-dir').onclick = function () {
  if (!state.detailPlugin) { toast('请先选择插件。', 'info'); return; }
  apiGet('/api/config').then(function (cfg) {
    var path = (cfg.custom_nodes || '') + '/' + state.detailPlugin;
    apiPost('/api/open-folder', { path: path }).then(function (resp) {
      if (resp.ok) {
        toast('已打开目录: ' + path, 'success');
      } else {
        toast('无法打开: ' + (resp.data.error || '未知错误'), 'error');
      }
    }).catch(function () {
      toast('请求失败。', 'error');
    });
  });
};

$('#btn-detail-refresh').onclick = function () { refreshDetail(); };

// ── 事件绑定 ──
$('#btn-scan-page').onclick = scanCurrentPage;
$('#btn-scan-all').onclick = showScanAllWarning;
$('#btn-scan-stop').onclick = stopScan;
$('#page-size-select').onchange = function () {
  state.pageSize = parseInt(this.value);
  state.currentPage = 1;
  refreshScanView();
};
$('#scan-search').oninput = function () {
  state.searchQuery = this.value.trim();
  state.currentPage = 1;
  refreshScanView();
};
$('#cfg-comfyui_root').oninput = function () {
  var root = this.value.trim();
  var cn = $('#cfg-custom_nodes');
  if (root && !cn.value.trim()) {
    cn.value = root.replace(/[\\/]+$/, '') + '\\custom_nodes';
  }
};
$('#btn-detail-check').onclick = detailCheck;
$('#btn-detail-update').onclick = detailUpdate;
$('#btn-detail-backup-dir').onclick = detailBackupDir;
$('#btn-detail-deps-read').onclick = function () { detailDepsRead(false); };
$('#btn-detail-deps-read-install').onclick = function () { detailDepsRead(true); };
$('#btn-detail-deps-check').onclick = function () { detailDepsManual('dryrun'); };
$('#btn-detail-deps-install').onclick = function () { detailDepsManual('install'); };
$('#btn-detail-deps-freeze').onclick = detailFreeze;
$('#btn-config-save').onclick = saveConfig;
$('#cfg-profile-select').onchange = switchProfile;
$('#btn-config-new').onclick = createProfile;
$('#btn-config-delete').onclick = deleteProfile;

// ── 初始化 ──
loadPlugins();
loadConfig();
