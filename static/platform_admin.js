/* ===================================================================
   YIRIBA — Console Éditeur (back-office plateforme)
   Réservé aux emails listés dans PLATFORM_ADMIN_EMAILS.
   =================================================================== */
const API = window.location.origin;
const TOKEN_KEY = 'yiriba_platform_token';
let token = localStorage.getItem(TOKEN_KEY) || '';

if (window.location.protocol === 'file:') {
  const el = document.createElement('div');
  el.style.cssText = 'position:fixed;inset:0;background:#fff;color:#8a0000;display:flex;align-items:center;justify-content:center;font:16px sans-serif;padding:24px;text-align:center;z-index:999;';
  el.textContent = 'Cette console doit être ouverte via le serveur (http://127.0.0.1:5050/static/platform_admin.html) et non en double-cliquant sur le fichier.';
  document.body.appendChild(el);
  throw new Error('file:// non supporté');
}

const STALE_TOKEN_MSG = 'Session expirée. Reconnectez-vous.';
let currentSchools = [];
let currentOffset = 0;
const PAGE = 25;

/* -- Helpers -------------------------------------------------- */
function parseError(d) {
  if (!d) return 'Erreur inconnue';
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map(e => e.msg || e.message || String(e)).join('\n');
  if (d.detail) return typeof d.detail === 'string' ? d.detail : parseError(d.detail);
  if (d.error) return typeof d.error === 'string' ? d.error : JSON.stringify(d.error);
  return JSON.stringify(d);
}
function escapeHtml(v) {
  return String(v == null ? '' : v)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
function toast(msg, isError) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.toggle('error', !!isError);
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 5000);
}

async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${API}${path}`, { ...opts, headers });
  let data = null;
  try { data = await res.json(); } catch (_) { /* no body */ }
  if (res.status === 401) { logout(); throw new Error(STALE_TOKEN_MSG); }
  if (!res.ok) throw new Error(parseError(data));
  return data;
}

/* -- Auth ------------------------------------------------------ */
function showAuth() {
  document.getElementById('auth-screen').style.display = 'flex';
  document.getElementById('app-screen').style.display = 'none';
}
function showApp(email) {
  document.getElementById('auth-screen').style.display = 'none';
  document.getElementById('app-screen').style.display = 'block';
  document.getElementById('user-email').textContent = email;
  loadSummary();
  loadSchools();
}
function logout() {
  token = null;
  localStorage.removeItem(TOKEN_KEY);
  showAuth();
}

document.getElementById('auth-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value;
  document.getElementById('auth-error').textContent = '';
  try {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    token = data.access_token;
    localStorage.setItem(TOKEN_KEY, token);
    showApp(email);
  } catch (err) {
    document.getElementById('auth-error').textContent = err.message;
  }
});
document.getElementById('logout-btn').addEventListener('click', logout);

/* -- Summary ---------------------------------------------------- */
async function loadSummary() {
  let s;
  try { s = await api('/api/platform/summary'); } catch (err) { toast(err.message, true); return; }
  const cards = [
    ['Écoles', s.total_schools, ''],
    ['Actives', s.active_schools, s.active_schools > 0 ? 'ok' : ''],
    ['En essai', s.trial_schools, s.expired_trials > 0 ? 'warn' : ''],
    ['Expirées / gelées', s.expired_schools, s.expired_schools > 0 ? 'bad' : ''],
    ['Élèves', s.total_students, ''],
    ['Utilisateurs', s.total_users, ''],
    ['CA abonnements actifs', s.active_subscriptions_amount, 'ok'],
  ];
  document.getElementById('cards').innerHTML = cards
    .map(c => `<div class="card"><div class="k">${escapeHtml(c[0])}</div><div class="v ${escapeHtml(c[2])}">${escapeHtml(c[1])}</div></div>`)
    .join('');
}

/* -- Schools table --------------------------------------------- */
function badgeStatus(st) {
  const map = { trial: ['b-trial', 'Essai'], active: ['b-active', 'Actif'], expired: ['b-expired', 'Expiré'], cancelled: ['b-cancelled', 'Annulé'] };
  const [cls, label] = map[st] || ['b-cancelled', st || '—'];
  return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
}

async function loadSchools() {
  const q = document.getElementById('search').value.trim();
  const qs = new URLSearchParams({ q, offset: String(currentOffset), limit: String(PAGE) }).toString();
  let s;
  try { s = await api(`/api/platform/schools?${qs}`); } catch (err) { toast(err.message, true); return; }
  currentSchools = s.schools;
  const body = document.getElementById('schools-body');
  if (!s.schools.length) {
    body.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--texte-secondaire);">Aucune école.</td></tr>';
  } else {
    body.innerHTML = s.schools.map(sch => {
      const plan = sch.current_plan ? `${escapeHtml(sch.current_plan.name)}` : '—';
      const accessCls = sch.access_level === 'full_access' ? 'b-full' : 'b-read';
      const created = (sch.created_at || '').slice(0, 10);
      return `<tr data-id="${sch.id}">
        <td><strong>${escapeHtml(sch.name)}</strong><br/><span style="color:var(--texte-secondaire);font-size:12px;">${escapeHtml(sch.slug)}</span></td>
        <td>${plan}</td>
        <td>${badgeStatus(sch.subscription_status)}</td>
        <td><span class="badge ${accessCls}">${escapeHtml(sch.access_level === 'full_access' ? 'Écriture' : 'Lecture seule')}</span></td>
        <td>${sch.student_count}</td>
        <td>${sch.user_count}</td>
        <td>${escapeHtml(created)}</td>
        <td class="actions">
          <button class="primary" data-act="detail" data-id="${sch.id}">Détails</button>
          <button data-act="plan" data-id="${sch.id}">Forfait</button>
          <button data-act="reset" data-id="${sch.id}">MDP</button>
          <button data-act="freeze" data-id="${sch.id}" class="${sch.access_level === 'full_access' ? '' : 'danger'}">${sch.access_level === 'full_access' ? 'Geler' : 'Dégeler'}</button>
        </td>
      </tr>`;
    }).join('');
  }
  const total = s.total;
  document.getElementById('pager').innerHTML =
    `<button id="prev-btn" ${currentOffset === 0 ? 'disabled' : ''}>← Précédent</button>` +
    `<span>${currentOffset + 1} – ${Math.min(currentOffset + PAGE, total)} / ${total}</span>` +
    `<button id="next-btn" ${currentOffset + PAGE >= total ? 'disabled' : ''}>Suivant →</button>`;
  document.getElementById('prev-btn').addEventListener('click', () => { currentOffset = Math.max(0, currentOffset - PAGE); loadSchools(); });
  document.getElementById('next-btn').addEventListener('click', () => { currentOffset += PAGE; loadSchools(); });
}

/* -- Row actions (event delegation) ----------------------------- */
document.getElementById('schools-body').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const id = btn.dataset.id;
  const act = btn.dataset.act;
  const school = currentSchools.find(s => String(s.id) === id);
  if (act === 'detail') openDetail(id);
  else if (act === 'plan') openPlan(school);
  else if (act === 'reset') confirmAction('Réinitialiser le mot de passe', `Réinitialiser le mot de passe de l'admin de « ${school.name} » ? L'école recevra un mot de passe temporaire et devra le changer à la connexion.`, () => resetPassword(id));
  else if (act === 'freeze') {
    if (school.access_level === 'full_access') {
      confirmAction('Geler l\'école', `Couper l'accès en écriture de « ${school.name} » ? Ses données resteront en lecture seule.`, () => freeze(id));
    } else {
      confirmAction('Dégeler l\'école', `Rétablir l'accès en écriture de « ${school.name} » (nouvel essai).`, () => unfreeze(id));
    }
  }
});

/* -- Detail ----------------------------------------------------- */
async function openDetail(id) {
  try {
    const d = await api(`/api/platform/schools/${id}`);
    const s = d.school;
    const planFeats = s.plan ? Object.entries(JSON.parse(s.plan.features || '{}')).filter(([, v]) => v).map(([k]) => k).join(', ') : '';
    document.getElementById('detail-title').textContent = s.name;
    document.getElementById('detail-content').innerHTML = `
      <div class="detail-grid">
        <div>
          <h4>Profil</h4>
          <div class="row"><span class="k">Slug</span><span class="code">${escapeHtml(s.slug)}</span></div>
          <div class="row"><span class="k">Type</span><span>${escapeHtml(s.school_type || '—')}</span></div>
          <div class="row"><span class="k">Ville / Pays</span><span>${escapeHtml(s.city || '—')} / ${escapeHtml(s.country || '—')}</span></div>
          <div class="row"><span class="k">Statut</span>${badgeStatus(s.subscription_status)}</div>
          <div class="row"><span class="k">Accès</span><span>${escapeHtml(s.access_level)}</span></div>
          <div class="row"><span class="k">Élèves actifs</span><span>${s.student_count}</span></div>
          <div class="row"><span class="k">Plan</span><span>${s.plan ? escapeHtml(s.plan.name) : '—'}</span></div>
          ${s.plan ? `<div class="row"><span class="k">Prix/élève/an</span><span>${escapeHtml(s.plan.price_per_student_year)}</span></div>` : ''}
          ${planFeats ? `<div class="row"><span class="k">Fonctionnalités</span><span>${escapeHtml(planFeats)}</span></div>` : ''}
        </div>
        <div>
          <h4>Historique abonnements</h4>
          ${d.subscriptions.length ? `<table><thead><tr><th>Forfait</th><th>Statut</th><th>Montant</th><th>Élèves</th><th>Début</th></tr></thead><tbody>${d.subscriptions.map(sub => `<tr><td>${escapeHtml(sub.plan_code || '—')}</td><td>${badgeStatus(sub.status)}</td><td>${escapeHtml(sub.amount)}</td><td>${sub.student_count_at_billing}</td><td>${escapeHtml((sub.started_at || '').slice(0, 10))}</td></tr>`).join('')}</tbody></table>` : '<p style="color:var(--texte-secondaire);">Aucun.</p>'}
          <h4>Utilisateurs (${d.users.length})</h4>
          <table><thead><tr><th>Nom</th><th>Rôle</th><th>Statut</th></tr></thead><tbody>${d.users.map(u => `<tr><td>${escapeHtml(u.full_name)}<br/><span style="color:var(--texte-secondaire);font-size:12px;">${escapeHtml(u.email || '')}</span></td><td>${escapeHtml(u.role_type)}</td><td>${escapeHtml(u.status)}</td></tr>`).join('')}</tbody></table>
        </div>
      </div>
      <h4 style="margin-top:16px; color:var(--yiriba-vert-foret);">Dernières actions (audit)</h4>
      ${d.audit.length ? `<table><thead><tr><th>Action</th><th>Acteur</th><th>Quand</th></tr></thead><tbody>${d.audit.map(a => `<tr><td>${escapeHtml(a.action)}</td><td>${escapeHtml(a.actor || '—')}</td><td>${escapeHtml((a.created_at || '').slice(0, 19).replace('T', ' '))}</td></tr>`).join('')}</tbody></table>` : '<p style="color:var(--texte-secondaire);">Aucune action enregistrée.</p>'}
    `;
    document.getElementById('detail-modal').classList.add('open');
  } catch (err) { toast(err.message, true); }
}
document.getElementById('detail-close').addEventListener('click', () => document.getElementById('detail-modal').classList.remove('open'));

/* -- Plan modal ------------------------------------------------ */
let currentPlanSchool = null;
document.getElementById('plan-modal').addEventListener('click', (e) => {
  if (e.target.id === 'plan-modal') document.getElementById('plan-modal').classList.remove('open');
});
document.getElementById('plan-close').addEventListener('click', () => document.getElementById('plan-modal').classList.remove('open'));
document.getElementById('plan-close2').addEventListener('click', () => document.getElementById('plan-modal').classList.remove('open'));
function openPlan(school) {
  currentPlanSchool = school;
  document.getElementById('plan-title').textContent = `Forfait — ${school.name}`;
  document.getElementById('plan-price').value = '';
  document.getElementById('plan-amount').value = '';
  if (school.current_plan) {
    document.getElementById('plan-code').value = school.current_plan.code;
  }
  document.getElementById('plan-modal').classList.add('open');
}
document.getElementById('plan-save').addEventListener('click', async () => {
  if (!currentPlanSchool) return;
  const payload = {
    plan_code: document.getElementById('plan-code').value,
    custom_price_per_student: document.getElementById('plan-price').value.trim() || null,
    custom_amount: document.getElementById('plan-amount').value.trim() || null,
  };
  try {
    await api(`/api/subscriptions/school/${currentPlanSchool.id}/change-plan`, { method: 'POST', body: JSON.stringify(payload) });
    toast(`Forfait mis à jour pour ${currentPlanSchool.name}.`);
    document.getElementById('plan-modal').classList.remove('open');
    loadSchools(); loadSummary();
  } catch (err) { toast(err.message, true); }
});

/* -- Confirm modal --------------------------------------------- */
let onConfirm = null;
document.getElementById('confirm-ok').addEventListener('click', async () => {
  document.getElementById('confirm-modal').classList.remove('open');
  if (onConfirm) { try { await onConfirm(); } catch (err) { toast(err.message, true); } }
});
document.getElementById('confirm-cancel').addEventListener('click', () => document.getElementById('confirm-modal').classList.remove('open'));
function confirmAction(title, text, fn) {
  document.getElementById('confirm-title').textContent = title;
  document.getElementById('confirm-text').textContent = text;
  onConfirm = fn;
  document.getElementById('confirm-modal').classList.add('open');
}

async function freeze(id) {
  await api(`/api/platform/schools/${id}/freeze`, { method: 'POST' });
  toast('École gelée (lecture seule).');
  loadSchools(); loadSummary();
}
async function unfreeze(id) {
  await api(`/api/platform/schools/${id}/unfreeze`, { method: 'POST' });
  toast('Accès en écriture rétabli.');
  loadSchools(); loadSummary();
}
async function resetPassword(id) {
  const r = await api(`/api/platform/schools/${id}/reset-admin-password`, { method: 'POST' });
  toast(`${r.message}\nMot de passe temporaire : ${r.temp_password} (à transmettre à ${r.admin_email})`);
  loadSchools();
}

/* -- Search & refresh ------------------------------------------ */
document.getElementById('search-btn').addEventListener('click', () => { currentOffset = 0; loadSchools(); });
document.getElementById('search').addEventListener('keydown', (e) => { if (e.key === 'Enter') { currentOffset = 0; loadSchools(); } });
document.getElementById('refresh-btn').addEventListener('click', () => { loadSummary(); loadSchools(); });

/* -- Init ------------------------------------------------------ */
if (token) { showApp('—'); } else { showAuth(); }