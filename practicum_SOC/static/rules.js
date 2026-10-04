const rulesRoot = document.querySelector('[data-draft-id]');
const rulesMessage = document.querySelector('#rules-message');
const rulesApi = '/api/v1/admin/rule-config';

function ruleHeaders() {
  return {
    'Content-Type': 'application/json',
    'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || '',
  };
}

async function ruleRequest(url, method, body) {
  const response = await fetch(url, { method, headers: ruleHeaders(), body: body ? JSON.stringify(body) : undefined });
  if (response.status === 401) { location.assign('/auth/login'); throw new Error('Sesión caducada'); }
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'No se pudo completar la operación. Revise los campos e inténtelo de nuevo.');
  return payload;
}

async function action(button, operation) {
  button.disabled = true;
  rulesMessage.classList.remove('is-error');
  rulesMessage.textContent = 'Procesando…';
  try { await operation(); }
  catch (error) { rulesMessage.classList.add('is-error'); rulesMessage.textContent = error.message; button.disabled = false; }
}

document.querySelector('[data-create-draft]')?.addEventListener('click', event => action(event.currentTarget, async () => {
  const draft = await ruleRequest(`${rulesApi}/drafts`, 'POST');
  location.assign(`/admin/rules?draft_id=${encodeURIComponent(draft.version_id)}`);
}));

document.querySelectorAll('[data-rule-form]').forEach(form => form.addEventListener('submit', event => {
  event.preventDefault();
  action(form.querySelector('button'), async () => {
    const changes = Object.fromEntries([...new FormData(form)].map(([name, value]) => [name, name === 'enabled' ? value === 'true' : Number(value)]));
    await ruleRequest(`${rulesApi}/drafts/${rulesRoot.dataset.draftId}/rules/${form.dataset.ruleForm}`, 'PATCH', { expected_hash: rulesRoot.dataset.draftHash, changes });
    location.reload();
  });
}));

document.querySelector('[data-scoring-form]')?.addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  action(form.querySelector('button'), async () => {
    const fields = Object.fromEntries([...new FormData(form)].map(([name, value]) => [name, Number(value)]));
    const changes = { volume_bonus_per_event: fields.volume_bonus_per_event, max_volume_bonus: fields.max_volume_bonus,
      severity_thresholds: { low: 0, medium: fields.severity_medium, high: fields.severity_high, critical: fields.severity_critical } };
    await ruleRequest(`${rulesApi}/drafts/${rulesRoot.dataset.draftId}/scoring`, 'PATCH', { expected_hash: rulesRoot.dataset.draftHash, changes });
    location.reload();
  });
});

document.querySelector('[data-preview-form]')?.addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  action(form.querySelector('button'), async () => {
    const values = new FormData(form);
    await ruleRequest(`${rulesApi}/drafts/${rulesRoot.dataset.draftId}/preview`, 'POST', {
      source: values.get('source'), from_utc: new Date(values.get('from')).toISOString(),
      to_utc: new Date(values.get('to')).toISOString(),
    });
    location.reload();
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
    await ruleRequest(`${rulesApi}/drafts/${rulesRoot.dataset.draftId}/publish`, 'POST', {
      justification: new FormData(form).get('justification'),
    });
    location.assign('/admin/rules');
  });
});

document.querySelector('[data-restore-form]')?.addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget; const values = new FormData(form);
  action(form.querySelector('button'), async () => {
    await ruleRequest(`${rulesApi}/versions/${encodeURIComponent(values.get('version_id'))}/restore`, 'POST', {
      justification: values.get('justification'),
    });
    location.reload();
  });
});
