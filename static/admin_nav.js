// Yiriba SaaS — Sidebar Admin à catégories dépliables
// Regroupe les modules existants en 6 catégories + Tableau de bord.
// Aucun module supprimé : les pages sont identiques, seule la structure change.
// Plusieurs catégories peuvent être ouvertes simultanément (état persistant en sessionStorage).

const ADMIN_NAV_GROUPS = [
  {
    id: 'scolarite', label: 'Scolarité', icon: 'fa-graduation-cap',
    pages: ['students', 'classes', 'teachers', 'grades', 'attendance', 'attendance-justify', 'bulletins', 'promotion', 'next-year'],
    items: [
      { page: 'students',            label: 'Élèves',                  icon: 'fa-user-graduate' },
      { page: 'classes',             label: 'Classes',                 icon: 'fa-chalkboard' },
      { page: 'teachers',            label: 'Enseignants',             icon: 'fa-person-chalkboard' },
      { page: 'grades',              label: 'Notes',                   icon: 'fa-pen-fancy' },
      { page: 'attendance',          label: 'Présences',               icon: 'fa-clipboard-check' },
      { page: 'attendance-justify',  label: 'Absences à justifier',    icon: 'fa-file-signature' },
      { page: 'bulletins',           label: 'Bulletins',               icon: 'fa-file-lines' },
      { page: 'promotion',           label: 'Passage de classe',       icon: 'fa-graduation-cap' },
      { page: 'next-year',           label: "Préparer l'année suivante", icon: 'fa-forward' },
    ],
  },
  {
    id: 'finance', label: 'Finance', icon: 'fa-money-bill-wave',
    pages: ['payments', 'debtors', 'fee-structure'],
    items: [
      { page: 'payments',      label: 'Paiements',           icon: 'fa-money-bill-wave' },
      { page: 'debtors',       label: 'Impayés & relances',  icon: 'fa-hand-holding-dollar' },
      { page: 'fee-structure', label: 'Structure des frais', icon: 'fa-file-invoice-dollar' },
    ],
  },
  {
    id: 'planning', label: 'Planning', icon: 'fa-calendar-days',
    pages: ['timetable'],
    items: [
      { page: 'timetable', label: 'Emploi du temps', icon: 'fa-calendar-days' },
    ],
  },
  {
    id: 'communication', label: 'Communication', icon: 'fa-bullhorn',
    pages: ['parents', 'communication'],
    items: [
      { page: 'parents',       label: 'Parents / Tuteurs', icon: 'fa-people-roof' },
      { page: 'communication', label: 'Communication',     icon: 'fa-bullhorn' },
    ],
  },
  {
    id: 'configuration', label: 'Configuration', icon: 'fa-sliders',
    adminOnly: true,
    pages: ['academic-years', 'academic-config', 'cycles', 'notif-preferences', 'class-subjects'],
    items: [
      { page: 'academic-years',    label: 'Années scolaires',           icon: 'fa-calendar-days' },
      { page: 'academic-config',   label: 'Configuration académique',   icon: 'fa-cog' },
      { page: 'cycles',            label: 'Cycles & Niveaux',           icon: 'fa-layer-group' },
      { page: 'notif-preferences', label: 'Préférences notifications',  icon: 'fa-sliders' },
      { page: 'class-subjects',    label: 'Matières par classe',        icon: 'fa-book-open' },
    ],
  },
  {
    id: 'administration', label: 'Administration', icon: 'fa-users-gear',
    adminOnly: true,
    pages: ['users', 'roles', 'subscription', 'audit', 'settings'],
    items: [
      { page: 'users',        label: 'Utilisateurs',          icon: 'fa-users-gear' },
      { page: 'roles',        label: 'Rôles & Permissions',   icon: 'fa-shield-halved' },
      { page: 'subscription', label: 'Abonnement',            icon: 'fa-crown' },
      { page: 'audit',        label: 'Audit',                 icon: 'fa-clock-rotate-left' },
      { page: 'settings',     label: 'Paramètres',            icon: 'fa-gear' },
    ],
  },
];

function _adminNavOpenState() {
  try { return JSON.parse(sessionStorage.getItem('adminNavOpen') || '{}'); }
  catch { return {}; }
}

function _adminNavSaveState(state) {
  try { sessionStorage.setItem('adminNavOpen', JSON.stringify(state)); } catch {}
}

function isAdminNavPageAdminOnly() {
  const roleType = (state.user?.role_type || '').toLowerCase();
  return roleType === 'admin' || (state.user?.id || '').startsWith('school:');
}

function toggleNavGroup(groupId) {
  const st = _adminNavOpenState();
  st[groupId] = !st[groupId];
  _adminNavSaveState(st);
  const btn = document.querySelector(`[data-nav-group="${groupId}"]`);
  const list = document.getElementById(`nav-group-${groupId}`);
  if (btn) btn.setAttribute('aria-expanded', st[groupId] ? 'true' : 'false');
  if (list) list.classList.toggle('open', !!st[groupId]);
  const chev = btn?.querySelector('.nav-chev i');
  if (chev) chev.className = st[groupId] ? 'fas fa-chevron-down' : 'fas fa-chevron-right';
}

function renderAdminNav() {
  const nav = document.getElementById('nav-main');
  const navAdmin = document.getElementById('nav-admin');
  if (!nav) return;
  const isAdmin = isAdminNavPageAdminOnly();
  const openState = _adminNavOpenState();

  const groups = ADMIN_NAV_GROUPS.filter(g => !g.adminOnly || isAdmin);

  const platformLink = window._isPlatformAdmin ? `
    <a class="nav-link" data-page="platform" onclick="loadPage('platform')" href="javascript:void(0)" title="Administration plateforme YIRIBA">
      <span class="nav-icon"><i class="fas fa-globe"></i></span><span>Écoles YIRIBA</span>
    </a>
  ` : '';

  nav.innerHTML = `
    <a class="nav-link" data-page="dashboard" onclick="loadPage('dashboard')" href="javascript:void(0)">
      <span class="nav-icon"><i class="fas fa-house"></i></span><span>Tableau de bord</span>
    </a>
    ${platformLink}
  `;

  if (navAdmin) {
    navAdmin.innerHTML = groups.map(g => {
      const open = !!openState[g.id];
      return `
      <div class="nav-group ${open ? 'open' : ''}">
        <button type="button" class="nav-group-btn" data-nav-group="${g.id}"
                aria-expanded="${open ? 'true' : 'false'}" aria-controls="nav-group-${g.id}"
                onclick="toggleNavGroup('${g.id}')">
          <span class="nav-icon"><i class="fas ${g.icon}"></i></span>
          <span class="nav-group-label">${g.label}</span>
          <span class="nav-chev"><i class="fas ${open ? 'fa-chevron-down' : 'fa-chevron-right'}"></i></span>
        </button>
        <div class="nav-group-list" id="nav-group-${g.id}" role="list">
          ${g.items.map(it => `
            <a class="nav-link nav-sublink" data-page="${it.page}" role="listitem"
               href="javascript:void(0)" onclick="loadPage('${it.page}')">
              <span class="nav-icon"><i class="fas ${it.icon}"></i></span><span>${it.label}</span>
            </a>`).join('')}
        </div>
      </div>`;
    }).join('');
  }
}

// Ouvre automatiquement la catégorie contenant la page active
function ensureNavGroupOpenForPage(page) {
  const group = ADMIN_NAV_GROUPS.find(g => g.pages.includes(page));
  if (!group) return;
  const st = _adminNavOpenState();
  if (!st[group.id]) {
    st[group.id] = true;
    _adminNavSaveState(st);
    const btn = document.querySelector(`[data-nav-group="${group.id}"]`);
    const list = document.getElementById(`nav-group-${group.id}`);
    if (btn) btn.setAttribute('aria-expanded', 'true');
    if (list) list.classList.add('open');
    const chev = btn?.querySelector('.nav-chev i');
    if (chev) chev.className = 'fas fa-chevron-down';
  }
}
