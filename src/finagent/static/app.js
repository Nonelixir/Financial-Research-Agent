const state = {
  companies: [], citationNumbers: new Map(), controller: null, streaming: false,
};

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));
const labels = { complete: '已完成', incomplete: '未完成', error: '失败', refused: '证据不足',
  verified: '已核验', missing: '缺失', mismatch: '不一致', revenue: '营收',
  net_income: '净利润', operating_income: '营业利润' };
const api = async (path, options = {}) => {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.json();
};

const streamApi = async (payload, onEvent, signal) => {
  const response = await fetch('/api/ask/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || !response.body) throw new Error(`研究服务不可用 (${response.status})`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let terminal = false;
  try {
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done }).replace(/\r\n/g, '\n');
    let boundary = buffer.indexOf('\n\n');
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const event = block.split('\n').find((line) => line.startsWith('event:'))?.slice(6).trim();
      const data = block.split('\n').filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim()).join('\n');
      if (event && data) {
        onEvent(event, JSON.parse(data));
        if (event === 'done') terminal = true;
      }
      boundary = buffer.indexOf('\n\n');
    }
    if (done) break;
  }
  if (!terminal) throw new Error('连接中断，回答尚未完成校验，请重试');
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
};

const scope = () => ({
  companies: state.companies,
  forms: [...document.querySelectorAll('.checks input:checked')].map((item) => item.value),
  fiscal_years: $('#years').value.split(',').map(Number).filter(Boolean),
  restatement_policy: 'latest_restated',
});

const renderCompanies = () => {
  $('#selected-companies').innerHTML = state.companies.map((company) => `
    <button class="company-chip" data-cik="${escapeHtml(company.cik)}">
      ${escapeHtml(company.ticker)}<span>×</span>
    </button>`).join('');
  document.querySelectorAll('.company-chip').forEach((button) => {
    button.onclick = () => {
      state.companies = state.companies.filter((item) => item.cik !== button.dataset.cik);
      renderCompanies();
    };
  });
};

$('#company-search').onclick = async () => {
  const query = $('#company-query').value.trim();
  if (!query) return;
  $('#company-results').textContent = '搜索中…';
  try {
    const companies = await api(`/api/companies/search?q=${encodeURIComponent(query)}`);
    $('#company-results').innerHTML = companies.map((company) => `
      <button data-company='${escapeHtml(JSON.stringify(company))}'>
        <strong>${escapeHtml(company.ticker)}</strong><span>${escapeHtml(company.name)}</span>
      </button>`).join('') || '<p>未找到公司</p>';
    document.querySelectorAll('#company-results button').forEach((button) => {
      button.onclick = () => {
        const company = JSON.parse(button.dataset.company);
        if (state.companies.length < 3 && !state.companies.some((item) => item.cik === company.cik)) {
          state.companies.push(company);
          renderCompanies();
        }
      };
    });
  } catch (error) {
    $('#company-results').textContent = error.message;
  }
};

const citationButton = (id) => {
  if (!state.citationNumbers.has(id)) state.citationNumbers.set(id, state.citationNumbers.size + 1);
  return `<button class="citation" data-id="${escapeHtml(id)}" title="查看原文来源">[${state.citationNumbers.get(id)}]</button>`;
};
const bindCitations = () => {
  document.querySelectorAll('.citation').forEach((button) => {
    button.onclick = async () => {
      $('#source-panel').textContent = '正在加载原文来源…';
      try {
      const source = await api(`/api/sources/${encodeURIComponent(button.dataset.id)}`);
      const locator = source.locator;
      $('#source-panel').innerHTML = `
        <h2>${escapeHtml(source.source.ticker)} · ${escapeHtml(source.source.form)}</h2>
        <p><strong>文件编号</strong><br>${escapeHtml(source.source.accession_no)}</p>
        <p><strong>定位</strong><br>${escapeHtml(locator.section || locator.concept || locator.operation)}</p>
        ${locator.exact_quote ? `<blockquote>${escapeHtml(locator.exact_quote)}</blockquote>` : ''}
        <a href="${escapeHtml(source.source.sec_url)}" target="_blank" rel="noreferrer">打开 SEC 原文 ↗</a>`;
      } catch (error) { $('#source-panel').textContent = error.message; }
    };
  });
};

const resetRun = (question) => {
  $('#run-title').textContent = question;
  $('#source-summary').textContent = '正在建立来源注册表';
  $('#answer').className = 'answer loading';
  $('#answer').innerHTML = '<div class="answer-skeleton"><span></span><span></span><span></span></div>';
  document.querySelectorAll('.status-step').forEach((step) => {
    step.className = 'status-step';
    step.querySelector('small').textContent = '等待';
  });
};

const updateStatus = (data) => {
  const step = document.querySelector(`.status-step[data-phase="${data.phase}"]`);
  if (step) {
    step.className = `status-step ${data.state}`;
    step.querySelector('small').textContent = data.state === 'complete' ? '完成'
      : data.state === 'warning' ? '需注意' : '进行中';
  }
  $('#live-status').className = `live-status ${data.state || ''}`;
  $('#live-status').innerHTML = `<span class="status-dot"></span><span>${escapeHtml(data.message)}</span>`;
};

const renderAnswer = (answer, isDone = false) => {
  $('#answer').className = `answer ${isDone ? '' : 'streaming'}`;
  const warning = answer.status !== 'complete' && isDone
    ? `<div class="status-warning">${escapeHtml(labels[answer.status] || answer.status)} · ${escapeHtml(answer.status_reason || '')}</div>` : '';
  const claims = answer.claims.map((claim, index) => `
    <article class="claim">
      <span class="claim-index">${String(index + 1).padStart(2, '0')}</span>
      <p>${escapeHtml(claim.text)} ${claim.citation_ids.map(citationButton).join('')}</p>
    </article>`).join('');
  const caveats = answer.caveats.map((item) => `<p class="caveat">${escapeHtml(item)}</p>`).join('');
  $('#answer').innerHTML = `${warning}${answer.message ? `<p>${escapeHtml(answer.message)}</p>` : ''}${claims}${caveats}${isDone ? '' : '<span class="stream-caret"></span>'}`;
  bindCitations();
};

const setStreaming = (value) => {
  state.streaming = value;
  $('#ask').disabled = value;
  $('#ask').textContent = value ? '研究进行中' : '开始研究';
  $('#stop').hidden = !value;
  $('#answer').setAttribute('aria-busy', String(value));
  document.querySelectorAll('.scope-panel input, .scope-panel button').forEach((item) => { item.disabled = value; });
};

$('#ask').onclick = async () => {
  if (!state.companies.length) return alert('请先选择公司');
  const question = $('#question').value.trim();
  if (!question) return;
  if (state.streaming) return;
  resetRun(question);
  setStreaming(true);
  state.controller = new AbortController();
  let latest = null;
  let failure = null;
  try {
    await streamApi(
      { question, scope: scope() },
      (event, data) => {
        if (event === 'status') updateStatus(data);
        if (event === 'sources') {
          $('#source-summary').innerHTML = `<strong>${data.count}</strong> 条来源 · `
            + `${data.xbrl_count} 数值 / ${data.narrative_count} 原文`;
        }
        if (event === 'answer.snapshot') {
          latest = !data.claims.length && ['error', 'refused'].includes(data.status) && latest
            ? { ...data, claims: latest.claims, caveats: [...data.caveats, '以上为未通过最终校验的临时内容。'] }
            : data;
          renderAnswer(latest, false);
        }
        if (event === 'error') failure = data.message;
        if (event === 'done' && latest) renderAnswer(latest, true);
      },
      state.controller.signal,
    );
    if (failure) throw new Error(failure);
  } catch (error) {
    if (error.name === 'AbortError') {
      $('#live-status').className = 'live-status warning';
      $('#live-status').innerHTML = '<span class="status-dot"></span><span>已停止生成</span>';
      renderAnswer({ ...(latest || { claims: [], caveats: [] }), status: 'incomplete', status_reason: '已手动停止；当前内容未通过最终校验' }, true);
    } else {
      updateStatus({ phase: 'generation', state: 'warning', message: error.message });
      renderAnswer({ ...(latest || { claims: [], caveats: [] }), status: 'error', status_reason: error.message }, true);
    }
    document.querySelectorAll('.status-step.active').forEach((step) => {
      step.className = 'status-step warning';
      step.querySelector('small').textContent = '已中断';
    });
  } finally {
    setStreaming(false);
    state.controller = null;
  }
};

$('#stop').onclick = () => state.controller?.abort();

const tablePayload = () => ({
  scope: scope(),
  metrics: ['revenue', 'net_income', 'operating_income'],
  periods: scope().fiscal_years.map((year) => `${year}-FY`),
});

$('#compare').onclick = async () => {
  if (!state.companies.length) return alert('请先选择公司');
  $('#table-wrap').innerHTML = '<p>正在生成并独立核验…</p>';
  try {
    const table = await api('/api/tables', { method: 'POST', body: JSON.stringify(tablePayload()) });
    $('#table-wrap').innerHTML = `
      <div class="table-heading"><h2>${escapeHtml(table.title)}</h2><span>${table.verified ? '✓ 已核验' : '⚠ 核验未通过'}</span></div>
      <div class="table-scroll"><table><thead><tr><th>公司</th><th>指标</th><th>期间</th><th>值</th><th>状态</th><th>来源</th></tr></thead>
      <tbody>${table.rows.map((row) => `<tr>
        <td>${escapeHtml(row.company.ticker)}</td><td>${escapeHtml(labels[row.metric] || row.metric)}</td><td>${escapeHtml(row.period)}</td>
        <td>${escapeHtml(row.cell.display_value)} ${escapeHtml(row.cell.unit || '')}</td><td>${escapeHtml(labels[row.cell.verification.status] || row.cell.verification.status)}</td>
        <td>${row.cell.source_citation_ids.map(citationButton).join(' ')}</td>
      </tr>`).join('')}</tbody></table></div>`;
    bindCitations();
  } catch (error) {
    $('#table-wrap').textContent = error.message;
  }
};

$('#export').onclick = async () => {
  if (!state.companies.length) return alert('请先选择公司');
  const response = await fetch('/api/exports/xlsx', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(tablePayload()),
  });
  if (!response.ok) return alert((await response.json()).detail);
  const anchor = document.createElement('a');
  anchor.href = URL.createObjectURL(await response.blob());
  anchor.download = 'financial-comparison.xlsx';
  anchor.click();
  URL.revokeObjectURL(anchor.href);
};

api('/api/health').then(() => { $('#health').textContent = '● 服务正常'; })
  .catch(() => { $('#health').textContent = '● 服务离线'; });
