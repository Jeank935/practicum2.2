const rulesRoot = document.querySelector('[data-draft-id]');
const rulesMessage = document.querySelector('#rules-message');
const rulesApi = '/api/v1/admin/rule-config';
const editableFields = [...document.querySelectorAll('[data-active-value]')];
const savedValues = new Map(editableFields.map(field => [field, field.value]));
let navigatingAfterSave = false;

function hasUnsavedChanges() {
  return editableFields.some(field => field.value !== savedValues.get(field));
}

function selectRule(key, updateHash = true) {
  const selected = document.querySelector(`[data-rule-panel="${key}"]`);
  if (!selected) return;
  document.querySelectorAll('[data-rule-panel]').forEach(panel => {
    panel.hidden = panel !== selected;
    panel.open = panel === selected;
  });
  document.querySelectorAll('[data-rule-select]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.ruleSelect === key));
  });
  const picker = document.querySelector('[data-rule-picker]');
  if (picker) picker.value = key;
  if (updateHash) history.replaceState(null, '', `${location.pathname}${location.search}#rule-${key}`);
}

function updateChanges() {
  let total = 0;
  document.querySelectorAll('[data-rule-panel]').forEach(panel => {
    let count = 0;
    panel.querySelectorAll('[data-active-value]').forEach(field => {
      const changed = field.value !== field.dataset.activeValue;
      field.closest('.rules-field').classList.toggle('is-changed', changed);
      field.closest('.rules-field').querySelector('.rules-change-label').hidden = !changed;
      if (changed) count += 1;
    });
    const label = document.querySelector(`[data-rule-change-count="${panel.dataset.rulePanel}"]`);
    if (label) label.textContent = count ? `${count} ${count === 1 ? 'parámetro diferente' : 'parámetros diferentes'}` : '';
    total += count;
  });
  const summary = document.querySelector('[data-diff-summary]');
  if (summary) summary.textContent = total ? `${total} ${total === 1 ? 'ajuste' : 'ajustes'} frente a la versión activa` : 'Sin cambios frente a la versión activa';
  const unsaved = document.querySelector('[data-unsaved-indicator]');
  if (unsaved) unsaved.hidden = !hasUnsavedChanges();
}

function updateSeverityRanges() {
  const form = document.querySelector('[data-scoring-form]');
  if (!form) return;
  const medium = Number(form.elements.severity_medium.value);
  const high = Number(form.elements.severity_high.value);
  const critical = Number(form.elements.severity_critical.value);
  const valid = medium > 0 && medium < high && high < critical && critical <= 100;
  form.elements.severity_critical.setCustomValidity(valid ? '' : 'Los umbrales deben aumentar: Media < Alta < Crítica, hasta 100.');
  const ranges = { low: `0–${medium - 1}`, medium: `${medium}–${high - 1}`, high: `${high}–${critical - 1}`, critical: `${critical}–100` };
  Object.entries(ranges).forEach(([key, range]) => {
    document.querySelector(`[data-score-range="${key}"]`).textContent = valid ? range : 'Revisa los umbrales';
  });
}

if (rulesRoot) {
  rulesRoot.classList.add('rules-enhanced');
  const availableKeys = [...document.querySelectorAll('[data-rule-select]')].map(button => button.dataset.ruleSelect);
  const hashKey = location.hash.replace('#rule-', '');
  selectRule(availableKeys.includes(hashKey) ? hashKey : availableKeys[0], false);
  document.querySelectorAll('[data-rule-select]').forEach(button => button.addEventListener('click', () => selectRule(button.dataset.ruleSelect)));
  document.querySelector('[data-rule-picker]')?.addEventListener('change', event => selectRule(event.currentTarget.value));
  document.querySelectorAll('[data-rule-panel] summary').forEach(summary => summary.addEventListener('click', event => event.preventDefault()));
  editableFields.forEach(field => field.addEventListener('input', () => { updateChanges(); updateSeverityRanges(); }));
  updateChanges();
  updateSeverityRanges();
}

window.addEventListener('beforeunload', event => {
  if (!navigatingAfterSave && hasUnsavedChanges()) { event.preventDefault(); event.returnValue = ''; }
});

function reloadSaved() {
  navigatingAfterSave = true;
  location.reload();
}

function confirmOtherEdits(form) {
  const otherEdits = editableFields.some(field => field.form !== form && field.value !== savedValues.get(field));
  return !otherEdits || window.confirm('Hay cambios sin guardar en otra regla. Al guardar esta regla se recargará la página y esos cambios se perderán. ¿Continuar?');
}

function ruleHeaders() {
  return {
    'Content-Type': 'application/json',
    'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || '',
  };
}

async function ruleRequest(url, method, body) {
  const response = await fetch(url, { method, headers: ruleHeaders(), body: body ? JSON.stringify(body) : undefined });
  if (response.status === 401) { location.assign('/auth/login'); throw new Error('Sesión caducada'); }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'No se pudo completar la operación. Revise los campos e inténtelo de nuevo.');
  return payload;
}

async function action(button, operation) {
  if (button.disabled) return;
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  const originalLabel = button.textContent;
  button.textContent = 'Procesando…';
  rulesMessage.classList.remove('is-error');
  rulesMessage.textContent = 'Procesando…';
  try { await operation(); }
  catch (error) {
    rulesMessage.classList.add('is-error');
    rulesMessage.textContent = error instanceof TypeError ? 'No se pudo conectar con el servidor. Tus cambios siguen aquí; vuelve a intentarlo.' : error.message;
    rulesMessage.scrollIntoView({ block: 'nearest' });
    button.disabled = false;
    button.textContent = originalLabel;
    button.removeAttribute('aria-busy');
  }
}

document.querySelector('[data-create-draft]')?.addEventListener('click', event => action(event.currentTarget, async () => {
  const draft = await ruleRequest(`${rulesApi}/drafts`, 'POST');
  location.assign(`/admin/rules?draft_id=${encodeURIComponent(draft.version_id)}`);
}));

document.querySelectorAll('[data-rule-form]').forEach(form => form.addEventListener('submit', event => {
  event.preventDefault();
  if (!confirmOtherEdits(form)) return;
  action(form.querySelector('button'), async () => {
    const changes = Object.fromEntries([...new FormData(form)].map(([name, value]) => [name, name === 'enabled' ? value === 'true' : Number(value)]));
    await ruleRequest(`${rulesApi}/drafts/${rulesRoot.dataset.draftId}/rules/${form.dataset.ruleForm}`, 'PATCH', { expected_hash: rulesRoot.dataset.draftHash, changes });
    reloadSaved();
  });
}));

document.querySelector('[data-scoring-form]')?.addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  if (!confirmOtherEdits(form)) return;
  action(form.querySelector('button'), async () => {
    const fields = Object.fromEntries([...new FormData(form)].map(([name, value]) => [name, Number(value)]));
    const changes = { volume_bonus_per_event: fields.volume_bonus_per_event, max_volume_bonus: fields.max_volume_bonus,
      severity_thresholds: { low: 0, medium: fields.severity_medium, high: fields.severity_high, critical: fields.severity_critical } };
    await ruleRequest(`${rulesApi}/drafts/${rulesRoot.dataset.draftId}/scoring`, 'PATCH', { expected_hash: rulesRoot.dataset.draftHash, changes });
    reloadSaved();
  });
});

document.querySelector('[data-preview-form]')?.addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  action(form.querySelector('button'), async () => {
    if (hasUnsavedChanges()) throw new Error('Guarda los cambios de cada regla antes de simular el borrador.');
    const values = new FormData(form);
    if (new Date(values.get('from')) >= new Date(values.get('to'))) throw new Error('La fecha de inicio debe ser anterior a la fecha de fin.');
    await ruleRequest(`${rulesApi}/drafts/${rulesRoot.dataset.draftId}/preview`, 'POST', {
      source: values.get('source'), from_utc: new Date(values.get('from')).toISOString(),
      to_utc: new Date(values.get('to')).toISOString(),
    });
    reloadSaved();
  });
});

document.querySelector('[data-preview-form] select[name="source"]')?.addEventListener('change', event => {
  const form = event.currentTarget.form;
  form.querySelector('input[name="from"]').value = '';
  form.querySelector('input[name="to"]').value = '';
});

document.querySelector('[data-publish-form]')?.addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  action(form.querySelector('button'), async () => {
    if (hasUnsavedChanges()) throw new Error('Guarda los ajustes y vuelve a comparar antes de publicar.');
    await ruleRequest(`${rulesApi}/drafts/${rulesRoot.dataset.draftId}/publish`, 'POST', {
      justification: new FormData(form).get('justification'),
    });
    navigatingAfterSave = true;
    location.assign('/admin/rules');
  });
});

document.querySelector('[data-restore-form]')?.addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget; const values = new FormData(form);
  action(form.querySelector('button'), async () => {
    await ruleRequest(`${rulesApi}/versions/${encodeURIComponent(values.get('version_id'))}/restore`, 'POST', {
      justification: values.get('justification'),
    });
    reloadSaved();
  });
});
