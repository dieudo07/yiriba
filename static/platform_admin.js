/* ===================================================================
   YIRIBA — Super Admin (console plateforme)
   Réservé aux emails listés dans PLATFORM_ADMIN_EMAILS.
   Pages : dashboard, écoles, utilisateurs, abonnements, paiements,
   activité, support, notifications, paramètres.
   =================================================================== */
const API = window.location.origin;
const TOKEN_KEY = 'yiriba_platform_token';
let token = localStorage.getItem(TOKEN_KEY) || '';

if (window.location.protocol === 'file:') {
  const el = document.createElement('div');
  el.style.cssText = 'position:fixed;inset:0;background:#fff;color:#8a0000;display:flex;align-items:center;justify-content:center;font:16px sans-serif;padding:24px;text-align:center;z-index:999;';
  el.textContent = 'Cette console doit être ouverte via le serveur (…/super-admin) et non en double-cliquant sur le fichier.';
  document.body.appendChild(el);
  throw new Error('file:// non supporté');
}

const STALE_TOKEN_MSG = 'Session expirée. Reconnectez-vous.';
const PAGE = 25;
let currentSchools = [];
let currentOffset = 0;
let allSchoolsCache = [];

/* -- Helpers -------------------------------------------------- */
function parseError(d) {
  if (!d) return 'Erreur inconnue';
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map(e => e.msg || e.message || String(e)).join('\n');
  if (d.detail) return typeof d.detail === 'string' ? d.detail : parseError(d.detail);
  return JSON.stringify(d);
}
function escapeHtml(v) {
  return String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function toast(msg, isError) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.toggle('error', !!isError);
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 5000);
}
function fmtDate(v) { return (v || '').slice(0, 10) || '—'; }
function fmtAmount(v, cur) {
  if (v == null || v === '') return '—';
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return `${n.toLocaleString('fr-FR')} ${cur || 'XOF'}`;
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

/* -- Navigation ------------------------------------------------ */
function showPage(name) {
  document.querySelectorAll('.sa-page').forEach(p => p.classList.remove('active'));
  const target = document.getElementById(`page-${name}`);
  if (target) target.classList.add('active');
  document.querySelectorAll('#sa-nav button').forEach(b => {
    b.classList.toggle('active', b.dataset.page === name);
  });
  const loaders = {
    dashboard: loadDashboard,
    schools: loadSchools,
    users: loadUsers,
    subscriptions: loadSubs,
    payments: loadPayments,
    activity: loadActivity,
    support: loadSupport,
    notifications: loadNotifications,
    settings: loadSettings,
  };
  if (loaders[name]) loaders[name]();
}
document.getElementById('sa-nav').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-page]');
  if (btn) showPage(btn.dataset.page);
});

/* -- Auth ------------------------------------------------------ */
function showAuth() {
  document.getElementById('auth-screen').style.display = 'flex';
  document.getElementById('app-screen').style.display = 'none';
}
function showApp(email) {
  document.getElementById('auth-screen').style.display = 'none';
  document.getElementById('app-screen').style.display = 'block';
  document.getElementById('user-email').textContent = email;
  showPage('dashboard');
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
    const data = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
    token = data.access_token;
    localStorage.setItem(TOKEN_KEY, token);
    showApp(email);
  } catch (err) {
    document.getElementById('auth-error').textContent = err.message;
  }
});
document.getElementById('logout-btn').addEventListener('click', logout);

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

/* -- Badges ------------------------------------------------------ */
function badge(st, map) {
  const [cls, label] = map[st] || ['b-cancelled', st || '—'];
  return `<span class="badge ${cls}">${escapeHtml(label)}</span>`;
}
const SCHOOL_BADGE = {
  active: ['b-active', '🟢 Actif'],
  trial: ['b-trial', 'Essai'],
  expired: ['b-expired', '🔴 Expiré'],
  cancelled: ['b-cancelled', 'Suspendu'],
  expiring_soon: ['b-trial', '🟠 Expire bientôt'],
  frozen: ['b-frozen', '⚫ Gelé'],
};
const USER_BADGE = {
  active: ['b-active', 'Actif'],
  pending: ['b-pending', 'En attente'],
  suspended: ['b-suspended', 'Suspendu'],
  rejected: ['b-expired', 'Rejeté'],
};
const PAY_BADGE = {
  paid: ['b-paid', 'Payé'],
  pending: ['b-pending', 'En attente'],
  failed: ['b-failed', 'Échoué'],
  refunded: ['b-refunded', 'Remboursé'],
};
const SUPPORT_BADGE = {
  new: ['b-new', 'Nouveau'],
  in_progress: ['b-in_progress', 'En cours'],
  resolved: ['b-resolved', 'Résolu'],
};

/* -- Dashboard --------------------------------------------------- */
async function loadDashboard() {
  let s;
  try { s = await api('/api/platform/summary'); } catch (err) { toast(err.message, true); return; }
  const cards = [
    ['Écoles actives', s.active_schools, 'ok'],
    ['Écoles suspendues', s.expired_schools, s.expired_schools > 0 ? 'bad' : ''],
    ['Total utilisateurs', s.total_users, ''],
    ['Élèves', s.total_students, ''],
    ['Abonnements actifs', s.active_subscriptions ?? '—', 'ok'],
    ['Revenus (abonnements actifs)', s.active_subscriptions_amount, 'ok'],
  ];
  document.getElementById('cards').innerHTML = cards
    .map(c => `<div class="card"><div class="k">${escapeHtml(c[0])}</div><div class="v ${c[2]}">${escapeHtml(c[1])}</div></div>`).join('');

  // Activité récente : dernières écoles créées + audit plateforme
  const actHtml = (s.recent_schools || []).map(sc =>
    `<div style="padding:8px 0;border-bottom:1px solid var(--border);font-size:14px;">
       🏫 Nouvelle école : <strong>${escapeHtml(sc.name)}</strong>
       <span style="color:var(--texte-secondaire);font-size:12px;">· ${fmtDate(sc.created_at)}</span>
     </div>`).join('');
  document.getElementById('recent-activity').innerHTML = actHtml || '<p class="empty">Aucune activité.</p>';

  // État des abonnements
  const parts = [
    ['Actifs', s.active_schools, 'active'],
    ['En essai', s.trial_schools, 'trial'],
    ['Expirés', s.expired_schools, 'expired'],
  ];
  document.getElementById('subs-state').innerHTML = parts.map(p =>
    `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);font-size:14px;">
       <span>${p[0]}</span><span style="display:flex;align-items:center;gap:10px;">${badge(p[2], SCHOOL_BADGE)}<strong>${p[1]}</strong></span>
     </div>`).join('');
}

/* -- Écoles ------------------------------------------------------ */
function schoolDisplayStatus(sch) {
  if (!sch.is_active) return 'frozen';
  return sch.subscription_status;
}
async function loadSchools() {
  const q = document.getElementById('search').value.trim();
  const filter = document.getElementById('filter-status').value;
  const qs = new URLSearchParams({ q, offset: String(currentOffset), limit: String(PAGE) }).toString();
  let s;
  try { s = await api(`/api/platform/schools?${qs}`); } catch (err) { toast(err.message, true); return; }
  currentSchools = s.schools;
  allSchoolsCache = s.schools.slice();
  const body = document.getElementById('schools-body');
  const visible = filter
    ? s.schools.filter(sc => filter === 'frozen' ? !sc.is_active : sc.subscription_status === filter)
    : s.schools;
  if (!visible.length) {
    body.innerHTML = '<tr><td colspan="7" class="empty">Aucune école.</td></tr>';
  } else {
    body.innerHTML = visible.map(sch => {
      const st = schoolDisplayStatus(sch);
      const frozen = !sch.is_active;
      return `<tr data-id="${sch.id}">
        <td><strong>${escapeHtml(sch.name)}</strong><br/><span style="color:var(--texte-secondaire);font-size:12px;">${escapeHtml(sch.slug)}</span></td>
        <td>${badge(st, SCHOOL_BADGE)}</td>
        <td>${sch.current_plan ? escapeHtml(sch.current_plan.name) : '—'}</td>
        <td>${sch.student_count}</td>
        <td>${sch.user_count}</td>
        <td>${fmtDate(sch.created_at)}</td>
        <td class="actions">
          <button class="primary" data-act="detail" data-id="${sch.id}">Fiche</button>
          <button data-act="data" data-id="${sch.id}">Données</button>
          <button data-act="plan" data-id="${sch.id}">Forfait</button>
          ${frozen
            ? `<button class="primary" data-act="unfreeze" data-id="${sch.id}">Réactiver l'accès</button>`
            : `<button class="danger" data-act="freeze" data-id="${sch.id}">Geler l'accès</button>`}
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
document.getElementById('search-btn').addEventListener('click', () => { currentOffset = 0; loadSchools(); });
document.getElementById('search').addEventListener('keydown', (e) => { if (e.key === 'Enter') { currentOffset = 0; loadSchools(); } });
document.getElementById('filter-status').addEventListener('change', () => loadSchools());
document.getElementById('refresh-btn').addEventListener('click', () => loadSchools());

document.getElementById('schools-body').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const id = btn.dataset.id;
  const school = currentSchools.find(s => String(s.id) === id);
  if (btn.dataset.act === 'detail') openDetail(id);
  else if (btn.dataset.act === 'data') openData(school);
  else if (btn.dataset.act === 'plan') openPlan(school);
  else if (btn.dataset.act === 'freeze') {
    confirmAction(
      'Geler cette école ?',
      `Les utilisateurs de « ${school.name} » ne pourront plus accéder à leur espace tant que l'accès restera gelé. Aucune donnée ne sera supprimée.`,
      () => freezeSchool(id, 'École gelée. Aucune donnée supprimée.'),
    );
  } else if (btn.dataset.act === 'unfreeze') {
    confirmAction(
      'Réactiver cette école ?',
      `L'accès de « ${school.name} » sera rétabli. Les utilisateurs pourront se reconnecter ; les données restent intactes.`,
      () => unfreezeSchool(id),
    );
  }
});

async function freezeSchool(id, msg) {
  try {
    const r = await api(`/api/platform/schools/${id}/freeze`, { method: 'POST' });
    toast(r.message || msg);
    loadSchools(); loadSupportBadge();
  } catch (err) { toast(err.message, true); }
}
async function unfreezeSchool(id) {
  try {
    const r = await api(`/api/platform/schools/${id}/unfreeze`, { method: 'POST' });
    toast(r.message || 'Accès rétabli.');
    loadSchools();
  } catch (err) { toast(err.message, true); }
}

/* -- Fiche détaillée d'une école ---------------------------------- */
let currentDetailSchoolId = null;
async function openDetail(id) {
  currentDetailSchoolId = id;
  try {
    const d = await api(`/api/platform/schools/${id}`);
    const s = d.school;
    const frozen = s.access_level !== 'full_access';
    const st = frozen ? 'frozen' : s.subscription_status;
    document.getElementById('detail-title').textContent = s.name;
    document.getElementById('detail-content').innerHTML = `
      <div class="detail-grid">
        <div>
          <h4>Profil</h4>
          <div class="row"><span class="k">Slug</span><span class="code">${escapeHtml(s.slug)}</span></div>
          <div class="row"><span class="k">Type</span><span>${escapeHtml(s.school_type || '—')}</span></div>
          <div class="row"><span class="k">Ville / Pays</span><span>${escapeHtml(s.city || '—')} / ${escapeHtml(s.country || '—')}</span></div>
          <div class="row"><span class="k">Créée le</span><span>${fmtDate(s.created_at)}</span></div>
          <div class="row"><span class="k">État du compte</span>${badge(st, SCHOOL_BADGE)}</div>
          <div class="row"><span class="k">Formule</span><span>${s.plan ? escapeHtml(s.plan.name) : '—'}</span></div>
          <div class="row"><span class="k">Expire le</span><span>${s.plan && s.plan.ends_at ? fmtDate(s.plan.ends_at) : (s.trial_ends_at ? fmtDate(s.trial_ends_at) : '—')}</span></div>
        </div>
        <div>
          <h4>Statistiques</h4>
          <div class="row"><span class="k">Élèves</span><span>${s.student_count}</span></div>
          <div class="row"><span class="k">Enseignants</span><span>${s.teacher_count ?? '—'}</span></div>
          <div class="row"><span class="k">Parents</span><span>${s.parent_count ?? '—'}</span></div>
          <div class="row"><span class="k">Utilisateurs</span><span>${s.active_user_count ?? '—'}</span></div>
          <div class="row"><span class="k">Email école</span><span>${escapeHtml(s.email || '—')}</span></div>
          <div class="row"><span class="k">Téléphone</span><span>${escapeHtml(s.phone || '—')}</span></div>
          <div class="row"><span class="k">Expire le</span><span>${s.trial_ends_at ? fmtDate(s.trial_ends_at) : '—'}</span></div>
          <div class="row"><span class="k">Classes</span><span>${s.class_count ?? '—'}</span></div>
        </div>
      </div>
      <h4 style="margin-top:16px;color:var(--yiriba-vert-foret);">Utilisateurs de l'école (${(d.users || []).length})</h4>
      <table><thead><tr><th>Nom</th><th>Rôle</th><th>Statut</th><th>Actions</th></tr></thead><tbody>
        ${(d.users || []).map(u => `<tr>
          <td>${escapeHtml(u.full_name)}<br/><span style="color:var(--texte-secondaire);font-size:12px;">${escapeHtml(u.email || '')}</span></td>
          <td>${escapeHtml(u.role_type)}</td>
          <td>${badge(u.status, USER_BADGE)}</td>
          <td class="actions">
            ${u.status === 'suspended'
              ? `<button data-uact="activate" data-uid="${u.id}">Réactiver</button>`
              : `<button class="danger" data-uact="suspend" data-uid="${u.id}">Suspendre</button>`}
          </td>
        </tr>`).join('')}
      </tbody></table>`;
    document.getElementById('detail-modal').classList.add('open');
  } catch (err) { toast(err.message, true); }
}
document.getElementById('detail-close').addEventListener('click', () => document.getElementById('detail-modal').classList.remove('open'));
document.getElementById('detail-content').addEventListener('click', async (e) => {
  const btn = e.target.closest('button[data-uact]');
  if (!btn) return;
  const uid = btn.dataset.uid;
  try {
    if (btn.dataset.uact === 'suspend') {
      await api(`/api/platform/users/${uid}/suspend`, { method: 'POST' });
      toast('Utilisateur suspendu.');
    } else {
      await api(`/api/platform/users/${uid}/activate`, { method: 'POST' });
      toast('Utilisateur activé.');
    }
    openDetail(currentDetailSchoolId);
  } catch (err) { toast(err.message, true); }
});

/* -- Données d'une école ------------------------------------------ */
function openData(school) {
  document.getElementById('data-title').textContent = `Données — ${school.name}`;
  document.getElementById('data-body').innerHTML = '<p style="color:#777">Chargement…</p>';
  document.getElementById('data-modal').classList.add('open');
  api(`/api/platform/schools/${school.id}/data`).then(d => {
    document.getElementById('data-body').innerHTML = `
      <div class="detail-grid">
        <div>
          <h4>Effectifs</h4>
          ${Object.entries(d.counts || {}).map(([k, v]) => `<div class="row"><span class="k">${escapeHtml(k)}</span><span>${v}</span></div>`).join('')}
        </div>
        <div>
          <h4>Export</h4>
          <p style="font-size:14px;color:var(--texte-secondaire);">Télécharger l'ensemble des données de l'école (JSON) :</p>
          <button class="actions primary" id="export-btn">⬇ Exporter</button>
        </div>
      </div>`;
    document.getElementById('export-btn').addEventListener('click', async () => {
      try {
        const data = await api(`/api/platform/schools/${school.id}/data/export`);
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `yiriba-export-${school.slug || school.id}.json`;
        a.click();
        URL.revokeObjectURL(a.href);
      } catch (err) { toast(err.message, true); }
    });
  }).catch(err => {
    document.getElementById('data-body').innerHTML = `<p class="empty">${escapeHtml(err.message)}</p>`;
  });
}
document.getElementById('data-close').addEventListener('click', () => document.getElementById('data-modal').classList.remove('open'));

/* -- Utilisateurs -------------------------------------------------- */
async function loadUsers() {
  const q = document.getElementById('users-search').value.trim();
  const schoolId = document.getElementById('users-school').value;
  const role = document.getElementById('users-role').value;
  const status = document.getElementById('users-status').value;
  const qs = new URLSearchParams({ q, limit: String(PAGE) });
  if (schoolId) qs.set('school_id', schoolId);
  if (role) qs.set('role', role);
  if (status) qs.set('status', status);
  let s;
  try { s = await api(`/api/platform/users?${qs}`); } catch (err) { toast(err.message, true); return; }
  const body = document.getElementById('users-body');
  if (!s.users.length) {
    body.innerHTML = '<tr><td colspan="7" class="empty">Aucun utilisateur.</td></tr>';
  } else {
    body.innerHTML = s.users.map(u => `<tr>
      <td>${escapeHtml(u.full_name)}</td>
      <td>${escapeHtml(u.email || u.username || '—')}</td>
      <td>${escapeHtml(u.school_name)}</td>
      <td>${escapeHtml(u.role_type)}</td>
      <td>${badge(u.status, USER_BADGE)}</td>
      <td>${u.last_login_at ? fmtDate(u.last_login_at) : 'Jamais'}</td>
      <td class="actions">
        ${u.status === 'suspended'
          ? `<button class="primary" data-uact2="activate" data-uid="${u.id}">Réactiver</button>`
          : `<button class="danger" data-uact2="suspend" data-uid="${u.id}">Suspendre</button>`}
      </td>
    </tr>`).join('');
  }
  document.getElementById('users-pager').innerHTML = `<span>${s.count} affiché(s) / ${s.total}</span>`;
  // Remplir le filtre écoles (une fois)
  const sel = document.getElementById('users-school');
  if (!sel.options.length || sel.options.length === 1) {
    try {
      const schools = await api('/api/platform/schools?limit=200');
      sel.innerHTML = '<option value="">Toutes les écoles</option>' +
        schools.schools.map(sc => `<option value="${sc.id}">${escapeHtml(sc.name)}</option>`).join('');
    } catch (_) { /* silencieux */ }
  }
}
document.getElementById('users-btn').addEventListener('click', loadUsers);
document.getElementById('users-search').addEventListener('keydown', (e) => { if (e.key === 'Enter') loadUsers(); });
document.getElementById('users-body').addEventListener('click', async (e) => {
  const btn = e.target.closest('button[data-uact2]');
  if (!btn) return;
  try {
    if (btn.dataset.uact2 === 'suspend') {
      await api(`/api/platform/users/${btn.dataset.uid}/suspend`, { method: 'POST' });
      toast('Utilisateur suspendu.');
    } else {
      await api(`/api/platform/users/${btn.dataset.uid}/activate`, { method: 'POST' });
      toast('Utilisateur activé.');
    }
    loadUsers();
  } catch (err) { toast(err.message, true); }
});

/* -- Abonnements ---------------------------------------------------- */
async function loadSubs() {
  const q = document.getElementById('subs-search').value.trim();
  const status = document.getElementById('subs-status').value;
  const qs = new URLSearchParams({ q, limit: String(PAGE) });
  let s;
  try { s = await api(`/api/platform/subscriptions?${qs}`); } catch (err) { toast(err.message, true); return; }
  const items = status ? s.subscriptions.filter(x => x.status === status) : s.subscriptions;
  const body = document.getElementById('subs-body');
  if (!items.length) {
    body.innerHTML = '<tr><td colspan="7" class="empty">Aucun abonnement.</td></tr>';
  } else {
    body.innerHTML = items.map(sub => `<tr>
      <td><strong>${escapeHtml(sub.school_name)}</strong></td>
      <td>${escapeHtml(sub.plan_name || '—')}</td>
      <td>${fmtDate(sub.started_at)}</td>
      <td>${fmtDate(sub.ends_at)}</td>
      <td>${badge(sub.is_frozen ? 'frozen' : sub.status, SCHOOL_BADGE)}</td>
      <td>${fmtAmount(sub.amount)}</td>
      <td class="actions">
        <button data-sact="extend" data-sid="${sub.school_id}" data-name="${escapeHtml(sub.school_name)}">Prolonger</button>
        <button data-sact="plan" data-sid="${sub.school_id}">Formule</button>
      </td>
    </tr>`).join('');
  }
  document.getElementById('subs-pager').innerHTML = `<span>${items.length} affiché(s) / ${s.total}</span>`;
}
document.getElementById('subs-btn').addEventListener('click', loadSubs);
document.getElementById('subs-search').addEventListener('keydown', (e) => { if (e.key === 'Enter') loadSubs(); });
document.getElementById('subs-body').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-sact]');
  if (!btn) return;
  if (btn.dataset.sact === 'extend') {
    const sid = btn.dataset.sid;
    confirmAction('Prolonger l\'abonnement', `Prolonger l'abonnement de « ${btn.dataset.name} » de 365 jours ?`, async () => {
      const r = await api(`/api/platform/schools/${sid}/extend-subscription?days=365`, { method: 'POST' });
      toast(r.message);
      loadSubs();
    });
  } else {
    const school = { id: btn.dataset.sid, name: 'École' };
    openPlan(school);
  }
});

/* -- Forfait (modal) ------------------------------------------------ */
let currentPlanSchool = null;
function openPlan(school) {
  currentPlanSchool = school;
  document.getElementById('plan-title').textContent = `Forfait — ${school.name || ''}`;
  document.getElementById('plan-price').value = '';
  document.getElementById('plan-amount').value = '';
  document.getElementById('plan-days').value = '';
  if (school.current_plan) document.getElementById('plan-code').value = school.current_plan.code;
  document.getElementById('plan-modal').classList.add('open');
}
document.getElementById('plan-modal').addEventListener('click', (e) => {
  if (e.target.id === 'plan-modal') document.getElementById('plan-modal').classList.remove('open');
});
document.getElementById('plan-close').addEventListener('click', () => document.getElementById('plan-modal').classList.remove('open'));
document.getElementById('plan-close2').addEventListener('click', () => document.getElementById('plan-modal').classList.remove('open'));
document.getElementById('plan-save').addEventListener('click', async () => {
  if (!currentPlanSchool) return;
  const days = document.getElementById('plan-days').value;
  try {
    if (days && Number(days) > 0) {
      const r = await api(`/api/platform/schools/${currentPlanSchool.id}/extend-subscription?days=${days}`, { method: 'POST' });
      toast(r.message);
    }
    const payload = {
      plan_code: document.getElementById('plan-code').value,
      custom_price_per_student: document.getElementById('plan-price').value.trim() || null,
      custom_amount: document.getElementById('plan-amount').value.trim() || null,
    };
    await api(`/api/subscriptions/school/${currentPlanSchool.id}/change-plan`, { method: 'POST', body: JSON.stringify(payload) });
    toast('Forfait mis à jour.');
    document.getElementById('plan-modal').classList.remove('open');
    loadSubs(); loadSchools();
  } catch (err) { toast(err.message, true); }
});

/* -- Paiements -------------------------------------------------------- */
async function loadPayments() {
  const q = document.getElementById('pay-search').value.trim();
  const status = document.getElementById('pay-status').value;
  const qs = new URLSearchParams({ limit: String(PAGE) });
  if (q) qs.set('q', q);
  if (status) qs.set('status', status);
  let s;
  try { s = await api(`/api/platform/payments?${qs}`); } catch (err) { toast(err.message, true); return; }
  const body = document.getElementById('pay-body');
  if (!s.payments.length) {
    body.innerHTML = '<tr><td colspan="6" class="empty">Aucun paiement.</td></tr>';
  } else {
    body.innerHTML = s.payments.map(p => `<tr>
      <td>${escapeHtml(p.school_name)}</td>
      <td><span class="code">${escapeHtml(p.reference)}</span></td>
      <td>${fmtAmount(p.amount, p.currency)}</td>
      <td>${fmtDate(p.paid_at || p.created_at)}</td>
      <td>${escapeHtml(p.method)}</td>
      <td>${badge(p.status, PAY_BADGE)}</td>
    </tr>`).join('');
  }
  document.getElementById('pay-pager').innerHTML = `<span>${s.count} affiché(s) / ${s.total}</span>`;
}
document.getElementById('pay-btn').addEventListener('click', loadPayments);
document.getElementById('pay-search').addEventListener('keydown', (e) => { if (e.key === 'Enter') loadPayments(); });
document.getElementById('pay-new').addEventListener('click', async () => {
  // Remplir la liste des écoles
  const sel = document.getElementById('paym-school');
  try {
    const schools = await api('/api/platform/schools?limit=500');
    sel.innerHTML = schools.schools.map(sc => `<option value="${sc.id}">${escapeHtml(sc.name)}</option>`).join('');
    document.getElementById('pay-modal').classList.add('open');
  } catch (err) { toast(err.message, true); }
});
document.getElementById('paym-close').addEventListener('click', () => document.getElementById('pay-modal').classList.remove('open'));
document.getElementById('paym-close2').addEventListener('click', () => document.getElementById('pay-modal').classList.remove('open'));
document.getElementById('paym-save').addEventListener('click', async () => {
  try {
    const r = await api('/api/platform/payments', {
      method: 'POST',
      body: JSON.stringify({
        school_id: Number(document.getElementById('paym-school').value),
        amount: Number(document.getElementById('paym-amount').value),
        method: document.getElementById('paym-method').value,
        status: document.getElementById('paym-status').value,
        note: document.getElementById('paym-note').value.trim() || null,
      }),
    });
    toast(r.message);
    document.getElementById('pay-modal').classList.remove('open');
    loadPayments();
  } catch (err) { toast(err.message, true); }
});

/* -- Activité / audit -------------------------------------------------- */
async function loadActivity() {
  let s;
  try { s = await api('/api/platform/audit?limit=100'); } catch (err) { toast(err.message, true); return; }
  const body = document.getElementById('activity-body');
  const rows = s.logs || s.audit || [];
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty">Aucune activité.</td></tr>';
  } else {
    body.innerHTML = rows.map(a => `<tr>
      <td>${escapeHtml((a.created_at || '').slice(0, 19).replace('T', ' '))}</td>
      <td>${a.actor_id ? '#' + escapeHtml(a.actor_id) : 'Système'}</td>
      <td><span class="code">${escapeHtml(a.action)}</span></td>
      <td>${escapeHtml(a.school_name || '—')}</td>
      <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(typeof a.details === 'string' ? a.details : JSON.stringify(a.details || ''))}</td>
    </tr>`).join('');
  }
  document.getElementById('activity-pager').innerHTML = `<span>${rows.length} entrée(s)</span>`;
}

/* -- Support ------------------------------------------------------------ */
let supportCache = [];
async function loadSupport() {
  const status = document.getElementById('support-status').value;
  const qs = new URLSearchParams({ limit: String(PAGE) });
  if (status) qs.set('status', status);
  let s;
  try { s = await api(`/api/platform/support?${qs}`); } catch (err) { toast(err.message, true); return; }
  supportCache = s.requests;
  const body = document.getElementById('support-body');
  if (!s.requests.length) {
    body.innerHTML = '<tr><td colspan="6" class="empty">Aucune demande.</td></tr>';
  } else {
    body.innerHTML = s.requests.map(r => `<tr>
      <td>${escapeHtml(r.school_name)}</td>
      <td>${escapeHtml(r.subject)}${!r.is_read ? ' <span class="badge b-new">Non lue</span>' : ''}</td>
      <td>${fmtDate(r.created_at)}</td>
      <td>${escapeHtml(r.priority)}</td>
      <td>${badge(r.status, SUPPORT_BADGE)}</td>
      <td class="actions"><button class="primary" data-ract="open" data-rid="${r.id}">Ouvrir</button></td>
    </tr>`).join('');
  }
  updateSupportBadge(s.requests.filter(r => !r.is_read).length);
}
function updateSupportBadge(n) {
  const el = document.getElementById('support-badge');
  el.textContent = n;
  el.style.display = n > 0 ? '' : 'none';
}
async function loadSupportBadge() {
  try {
    const s = await api('/api/platform/support?limit=100');
    updateSupportBadge(s.requests.filter(r => !r.is_read).length);
  } catch (_) { /* silencieux */ }
}
document.getElementById('support-btn').addEventListener('click', loadSupport);
document.getElementById('support-body').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-ract]');
  if (!btn) return;
  const req = supportCache.find(r => String(r.id) === btn.dataset.rid);
  if (!req) return;
  document.getElementById('support-title').textContent = `Support — ${req.school_name}`;
  document.getElementById('support-content').innerHTML = `
    <div class="row"><span class="k">Sujet</span><span>${escapeHtml(req.subject)}</span></div>
    <div class="row"><span class="k">Reçu le</span><span>${fmtDate(req.created_at)}</span></div>
    <div class="row"><span class="k">Téléphone</span><span>${escapeHtml(req.phone || '—')}</span></div>
    <p style="font-size:14px;background:var(--surface-soft);padding:12px;border-radius:var(--radius-sm);">${escapeHtml(req.message)}</p>
    ${req.response ? `<p style="font-size:14px;"><strong>Réponse :</strong> ${escapeHtml(req.response)}</p>` : ''}`;
  document.getElementById('support-response').value = req.response || '';
  document.getElementById('support-new-status').value = req.status;
  document.getElementById('support-modal').classList.add('open');
  document.getElementById('support-save').onclick = async () => {
    try {
      await api(`/api/platform/support/${req.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          response: document.getElementById('support-response').value.trim() || null,
          status: document.getElementById('support-new-status').value,
          is_read: true,
        }),
      });
      toast('Demande mise à jour.');
      document.getElementById('support-modal').classList.remove('open');
      loadSupport();
    } catch (err) { toast(err.message, true); }
  };
});
document.getElementById('support-close').addEventListener('click', () => document.getElementById('support-modal').classList.remove('open'));
document.getElementById('support-close2').addEventListener('click', () => document.getElementById('support-modal').classList.remove('open'));

/* -- Notifications ------------------------------------------------------- */
async function loadNotifications() {
  let s;
  try { s = await api('/api/platform/notifications'); } catch (err) { toast(err.message, true); return; }
  const list = document.getElementById('notif-list');
  if (!s.notifications.length) {
    list.innerHTML = '<p class="empty">Aucune notification.</p>';
    return;
  }
  list.innerHTML = s.notifications.map(n => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border);font-size:14px;${n.is_read ? 'color:var(--texte-secondaire);' : 'font-weight:600;'}">
      <span>${n.is_read ? '' : '🔵 '}${escapeHtml(n.title)}</span>
      <span style="font-size:12px;color:var(--texte-secondaire);">${fmtDate(n.created_at)}</span>
    </div>`).join('');
}
document.getElementById('notif-read-all').addEventListener('click', async () => {
  try {
    await api('/api/platform/notifications/mark-read', { method: 'POST' });
    toast('Notifications marquées comme lues.');
    loadNotifications();
  } catch (err) { toast(err.message, true); }
});

/* -- Paramètres ------------------------------------------------------------ */
async function loadSettings() {
  let s;
  try { s = await api('/api/platform/settings'); } catch (err) { toast(err.message, true); return; }
  document.getElementById('set-name').value = s.platform_name || 'YIRIBA';
  document.getElementById('set-email').value = s.contact_email || '';
  document.getElementById('set-maintenance').checked = !!s.maintenance_mode;
}
document.getElementById('set-maintenance').addEventListener('change', (e) => {
  if (e.target.checked) {
    e.target.checked = false; // on n'active que via la confirmation
    confirmAction(
      'Activer le mode maintenance ?',
      'Tous les utilisateurs classiques verront une page de maintenance. Votre accès Super Admin reste actif. Aucune donnée n\'est affectée.',
      async () => {
        await api('/api/platform/settings', { method: 'PATCH', body: JSON.stringify({ maintenance_mode: true }) });
        e.target.checked = true;
        toast('Mode maintenance activé.');
      },
    );
  }
});
document.getElementById('set-save').addEventListener('click', async () => {
  try {
    const r = await api('/api/platform/settings', {
      method: 'PATCH',
      body: JSON.stringify({
        platform_name: document.getElementById('set-name').value.trim(),
        contact_email: document.getElementById('set-email').value.trim(),
      }),
    });
    toast('Paramètres enregistrés.');
  } catch (err) { toast(err.message, true); }
});

/* -- Init -------------------------------------------------------------------- */
if (token) { showApp('—'); } else { showAuth(); }
