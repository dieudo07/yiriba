/* ===================================================================
   YIRIBA SAAS — Dashboard — Reproduction fidèle de la maquette
   =================================================================== */
const API = window.location.origin;
let state = { token: localStorage.getItem('yiriba_token') || sessionStorage.getItem('yiriba_token'), refreshToken: localStorage.getItem('yiriba_refresh') || sessionStorage.getItem('yiriba_refresh'), user: null, schoolId: null, schoolName: '', subscription: null };

/* -- Error parsing helper ------------------------------------ */
function parseError(d) {
  if (!d) return 'Erreur inconnue';
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map(e => e.msg || e.message || String(e)).join('\n');
  if (d.detail) return typeof d.detail === 'string' ? d.detail : parseError(d.detail);
  if (d.error) return typeof d.error === 'string' ? d.error : JSON.stringify(d.error);
  return JSON.stringify(d);
}

/* -- HTML escaping (anti-XSS) --------------------------------- */
function escapeHtml(v) {
  return String(v == null ? '' : v)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* -- YIRIBA Shared UI Helpers ---------------------------------- */
function yiribaLoading(msg = 'Chargement...') {
  return `<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>${msg}</p></div>`;
}
function yiribaEmpty(icon, title, desc, actionLabel, actionFn) {
  const btn = actionLabel && actionFn ? `<button class="btn-action" onclick="${actionFn}"><i class="fas fa-plus"></i> ${actionLabel}</button>` : '';
  return `<div class="yiriba-empty"><div class="empty-tree"><i class="fas ${icon}"></i></div><h4>${title}</h4><p>${desc}</p>${btn}</div>`;
}
function updateNotifBadge(count) {
  const badge = document.getElementById('notif-badge');
  if (badge) badge.style.display = count > 0 ? 'block' : 'none';
}

/* -- Auth UI Helpers ------------------------------------- */
function togglePassword(btn) {
  const input = btn.closest('.auth-input-wrap').querySelector('input');
  const icon = btn.querySelector('i');
  if (input.type === 'password') {
    input.type = 'text';
    icon.classList.remove('fa-eye-slash');
    icon.classList.add('fa-eye');
  } else {
    input.type = 'password';
    icon.classList.remove('fa-eye');
    icon.classList.add('fa-eye-slash');
  }
}

/* -- API Client ----------------------------------------------- */
async function api(path, opts = {}) {
  const h = { ...opts.headers };
  // Ne pas forcer Content-Type sur un FormData : le navigateur doit poser
  // lui-même le multipart boundary.
  if (!(opts.body instanceof FormData)) h['Content-Type'] = 'application/json';
  if (state.token) h['Authorization'] = `Bearer ${state.token}`;
  try {
    let r = await fetch(`${API}${path}`, { ...opts, headers: h });
    if (r.status === 401 && state.refreshToken) {
      const ok = await tryRefresh();
      if (ok) { h['Authorization'] = `Bearer ${state.token}`; r = await fetch(`${API}${path}`, { ...opts, headers: h }); return r; }
    }
    return r;
  } catch (e) { throw e; }
}
async function tryRefresh() {
  try { const r = await fetch(`${API}/api/auth/refresh`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: state.refreshToken }) }); if (r.ok) { const d = await r.json(); state.token = d.access_token; state.refreshToken = d.refresh_token || state.refreshToken; localStorage.setItem('yiriba_token', state.token); localStorage.setItem('yiriba_refresh', state.refreshToken); return true; } } catch {} return false;
}

/* -- Auth ----------------------------------------------------- */
var _loginInProgress = false;
function showAuthTab(t) {
  document.querySelectorAll('.auth-tab').forEach(function(b, i) {
    b.classList.toggle('active', (t === 'login' && i === 0) || (t === 'register' && i === 1));
  });
  document.getElementById('login-form').style.display = t === 'login' ? 'block' : 'none';
  document.getElementById('register-form').style.display = t === 'register' ? 'block' : 'none';
  if (t === 'register') { regNextStep(1); document.getElementById('register-error').textContent = ''; }
  document.getElementById('forgot-form').style.display = t === 'forgot' ? 'block' : 'none';
  document.getElementById('reset-form').style.display = t === 'reset' ? 'block' : 'none';
  // Hide separator and social when on forgot/reset
  var sep = document.querySelector('.auth-separator');
  var social = document.querySelector('.auth-social-row');
  var tabs = document.querySelector('.auth-tabs');
  if (t === 'forgot' || t === 'reset') {
    if (sep) sep.style.display = 'none';
    if (social) social.style.display = 'none';
    if (tabs) tabs.style.display = 'none';
  } else {
    if (sep) sep.style.display = '';
    if (social) social.style.display = '';
    if (tabs) tabs.style.display = '';
  }
}

/* -- Language switching (retiré : interface 100% française) ----- */
// Les fonctions toggleLangMenu/switchLang ont été supprimées avec le
// sélecteur de langue de l'écran de connexion.

/* -- Login with loading state ---------------------------------- */
async function handleLogin(e) {
  e.preventDefault();
  if (_loginInProgress) return;
  _loginInProgress = true;
  var el = document.getElementById('login-error');
  var btn = document.getElementById('login-submit-btn');
  el.textContent = '';
  // Show loading
  var origHTML = btn.innerHTML;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> <span data-i18n="login.loading">' + YIRIBA_I18N.t('login.loading') + '</span>';
  btn.disabled = true;
  try {
    var schoolSlug = document.getElementById('login-school-slug')?.value?.trim() || null;
    var rememberMe = document.querySelector('.auth-checkbox')?.checked || false;
    var email = document.getElementById('login-email').value.trim();
    var password = document.getElementById('login-password').value;
    if (!email) { el.textContent = YIRIBA_I18N.t('error.email_required'); return; }
    if (!password) { el.textContent = YIRIBA_I18N.t('error.password_required'); return; }
    var r = await fetch(API + '/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email, password: password, school_slug: schoolSlug })
    });
    var d = await r.json();
    if (!r.ok) {
      var msg = YIRIBA_I18N.t('login.error.default');
      if (r.status === 423) msg = YIRIBA_I18N.t('login.error.locked');
      else if (r.status === 403) msg = YIRIBA_I18N.t('login.error.disabled');
      else if (Array.isArray(d.detail)) msg = d.detail.map(function(e) { return e.msg || e.message || String(e); }).join('\n');
      else if (d.detail) msg = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail);
      else if (d.error) msg = d.error;
      throw new Error(msg);
    }
    state.token = d.access_token;
    state.refreshToken = d.refresh_token;
    state.user = d.user;
    state.schoolId = d.user?.school_id || d.school_id;
    if (rememberMe) {
      localStorage.setItem('yiriba_token', state.token);
      localStorage.setItem('yiriba_refresh', state.refreshToken || '');
    } else {
      sessionStorage.setItem('yiriba_token', state.token);
      sessionStorage.setItem('yiriba_refresh', state.refreshToken || '');
    }
    await enterApp();
  } catch (err) {
    el.textContent = err.message || YIRIBA_I18N.t('login.error.network');
  } finally {
    btn.innerHTML = origHTML;
    btn.disabled = false;
    _loginInProgress = false;
  }
}

/* -- Forgot password ------------------------------------------- */
async function handleForgotPassword(e) {
  e.preventDefault();
  var el = document.getElementById('forgot-error');
  var success = document.getElementById('forgot-success');
  var btn = document.getElementById('forgot-submit-btn');
  el.textContent = '';
  success.style.display = 'none';
  var email = document.getElementById('forgot-email').value.trim();
  if (!email) { el.textContent = YIRIBA_I18N.t('error.email_required'); return; }
  var origHTML = btn.innerHTML;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> <span>' + YIRIBA_I18N.t('reset.loading') + '</span>';
  btn.disabled = true;
  try {
    var r = await fetch(API + '/api/auth/forgot-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email })
    });
    var d = await r.json();
    if (r.ok && d.reset_token) {
      // Dev mode: auto-redirect to reset form with token
      window._resetToken = d.reset_token;
      showAuthTab('reset');
    } else {
      success.style.display = 'block';
    }
  } catch (err) {
    el.textContent = err.message || YIRIBA_I18N.t('login.error.network');
  } finally {
    btn.innerHTML = origHTML;
    btn.disabled = false;
  }
}

/* -- Reset password -------------------------------------------- */
async function handleResetPassword(e) {
  e.preventDefault();
  var el = document.getElementById('reset-error');
  var success = document.getElementById('reset-success');
  var btn = document.getElementById('reset-submit-btn');
  el.textContent = '';
  success.style.display = 'none';
  var pw = document.getElementById('reset-password').value;
  var pw2 = document.getElementById('reset-password-confirm').value;
  if (pw !== pw2) { el.textContent = YIRIBA_I18N.t('reset.error.mismatch'); return; }
  if (pw.length < 8) { el.textContent = YIRIBA_I18N.t('reset.error.mismatch'); return; }
  var token = window._resetToken;
  if (!token) { el.textContent = YIRIBA_I18N.t('reset.error.invalid'); return; }
  var origHTML = btn.innerHTML;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> <span>' + YIRIBA_I18N.t('reset.confirm_loading') + '</span>';
  btn.disabled = true;
  try {
    var r = await fetch(API + '/api/auth/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token, new_password: pw })
    });
    var d = await r.json();
    if (r.ok) {
      success.style.display = 'block';
      window._resetToken = null;
      setTimeout(function() { showAuthTab('login'); }, 3000);
    } else {
      var msg = YIRIBA_I18N.t('reset.error.invalid');
      if (d.detail) msg = typeof d.detail === 'string' ? d.detail : msg;
      throw new Error(msg);
    }
  } catch (err) {
    el.textContent = err.message;
  } finally {
    btn.innerHTML = origHTML;
    btn.disabled = false;
  }
}
/* ── Register School: Multi-step Wizard ──────────────────── */
let _selectedPlan = null;
let _regConfig = null;
let _turnstileToken = null;
let _turnstileWidgetId = null;

async function _loadRegConfig() {
  if (_regConfig) return _regConfig;
  try {
    const r = await fetch(API + '/api/auth/registration-config');
    _regConfig = await r.json();
  } catch (e) {
    _regConfig = { require_email_confirmation: false, turnstile_site_key: '' };
  }
  return _regConfig;
}

async function _loadRegCaptcha() {
  const cfg = await _loadRegConfig();
  const container = document.getElementById('reg-captcha-container');
  if (!container) return;
  if (!cfg.turnstile_site_key) { container.style.display = 'none'; return; }
  if (!window.turnstile) {
    window.addEventListener('load', () => _renderTurnstile(container, cfg.turnstile_site_key));
    return;
  }
  _renderTurnstile(container, cfg.turnstile_site_key);
}

function _renderTurnstile(container, siteKey) {
  if (_turnstileWidgetId !== null) { window.turnstile.reset(_turnstileWidgetId); return; }
  try {
    container.style.display = 'flex';
    container.innerHTML = '';
    _turnstileWidgetId = window.turnstile.render(container, {
      sitekey: siteKey,
      theme: 'light',
      callback: (token) => { _turnstileToken = token; const btn = document.getElementById('reg-plan-next'); if (btn) btn.disabled = false; },
      'error-callback': () => {
        _turnstileToken = null;
        _showTurnstileError('La vérification anti-robot a échoué. Vérifiez que le domaine autorisé est bien actif dans Cloudflare, puis réessayez.');
      },
      'expired-callback': () => { _turnstileToken = null; },
    });
  } catch (e) {
    _showTurnstileError('Widget anti-robot non chargé. Vérifiez votre connexion internet et rechargiez la page.');
  }
}

function _showTurnstileError(msg) {
  const container = document.getElementById('reg-captcha-container');
  if (!container) return;
  container.style.display = 'flex';
  container.innerHTML = '<div style="font-size:12.5px;color:#c62828;background:#fdecea;padding:10px 14px;border-radius:8px"><i class="fas fa-exclamation-triangle"></i> ' + msg + '</div>';
  _turnstileWidgetId = null;
}

function showCgvModal() {
  showModal('Conditions d\'utilisation et confidentialité', `
    <div style="font-size:13px;color:var(--texte-secondaire);line-height:1.7;max-height:60vh;overflow-y:auto">
      <h4 style="color:var(--yiriba-vert-profond);margin:0 0 8px">1. Objet</h4>
      <p>YIRIBA est une plateforme de gestion scolaire (élèves, notes, bulletins, paiements, communication école-famille) accessible via Internet. Les présentes conditions régissent l'accès et l'utilisation du service par tout établissement scolaire et ses utilisateurs.</p>

      <h4 style="color:var(--yiriba-vert-profond);margin:14px 0 8px">2. Compte et identifiants</h4>
      <p>L'inscription crée un établissement et un compte administrateur. Vous recevez un identifiant unique et un mot de passe temporaire que vous modifiez à la première connexion. Vous êtes seul responsable de la confidentialité de vos identifiants et de toute activité réalisée depuis votre compte. Signalez immédiatement toute utilisation non autorisée.</p>

      <h4 style="color:var(--yiriba-vert-profond);margin:14px 0 8px">3. Souscription, paiement et résiliation</h4>
      <p>Le service est proposé sous la forme de forfaits (essai gratuit, forfaits annuels payants). Les tarifs en vigueur sont ceux affichés lors de la souscription. L'essai gratuit est sans engagement et peut être interrompu à tout moment. En cas d'abonnement payant, la facturation est effectuée selon les modalités indiquées au moment de la souscription ; l'établissement peut résilier son abonnement à l'issue de la période en cours. En cas de non-paiement, l'accès au service peut être suspendu après notification.</p>

      <h4 style="color:var(--yiriba-vert-profond);margin:14px 0 8px">4. Données personnelles et confidentialité</h4>
      <p>YIRIBA collecte et traite les données nécessaires au fonctionnement du service (identification de l'établissement, des personnels, des élèves et des parents, données de scolarité, de paiement et d'absentéisme). Le traitement respecte la loi n° 001-2021/AN du 30 mars 2021 portant protection des données à caractère personnel au Burkina Faso. Les données sont utilisées uniquement dans le cadre du service, ne sont jamais revendues à des tiers et ne sont transmises que lorsque cela est strictement nécessaire au fonctionnement (hébergement sécurisé, encaissement des paiements en ligne). Vous pouvez demander l'accès, la rectification ou la suppression de vos données en écrivant à support@yiriba.app.</p>

      <h4 style="color:var(--yiriba-vert-profond);margin:14px 0 8px">5. Obligations de l'utilisateur</h4>
      <p>L'utilisateur s'engage à fournir des informations exactes, à utiliser le service de manière licite et conforme à sa destination, à ne pas tenter d'accéder aux comptes de tiers ni de perturber le fonctionnement de la plateforme, et à ne pas reproduire, modifier ou revendre le service sans autorisation.</p>

      <h4 style="color:var(--yiriba-vert-profond);margin:14px 0 8px">6. Disponibilité et responsabilité</h4>
      <p>YIRIBA met en œuvre les moyens raisonnables pour assurer la disponibilité du service et la sauvegarde des données, sans garantie d'absence totale d'interruption (maintenance, incidents techniques, obligations légales). La responsabilité de YIRIBA est limitée aux dommages directs et prouvés résultant d'un manquement à ses obligations. L'établissement conserve l'obligation de conserver ses propres archives scolaires et comptables.</p>

      <h4 style="color:var(--yiriba-vert-profond);margin:14px 0 8px">7. Propriété intellectuelle</h4>
      <p>La plateforme, ses marques, logos et contenus sont la propriété de YIRIBA. L'utilisation du service ne confère aucun droit de propriété sur ces éléments.</p>

      <h4 style="color:var(--yiriba-vert-profond);margin:14px 0 8px">8. Modifications des conditions</h4>
      <p>YIRIBA peut faire évoluer le service et les présentes conditions, notamment pour s'adapter aux exigences légales, réglementaires ou techniques. Les conditions applicables sont celles en vigueur lors de l'utilisation du service ; la poursuite de l'utilisation vaut acceptation.</p>

      <h4 style="color:var(--yiriba-vert-profond);margin:14px 0 8px">9. Droit applicable et contact</h4>
      <p>Les présentes conditions sont soumises au droit burkinabè. Tout litige sera, à défaut de solution amiable, porté devant les juridictions compétentes. Pour toute question : support@yiriba.app.</p>
    </div>
    <div style="margin-top:14px;text-align:right"><button onclick="closeModal()" style="background:var(--yiriba-vert);color:white;border:none;border-radius:8px;padding:10px 20px;font-weight:600;cursor:pointer">J'ai compris</button></div>
  `);
}

async function _loadRegPlans() {
  try {
    const r = await fetch(API + '/api/auth/subscription-plans');
    const d = await r.json();
    const plans = d.plans || [];
    const el = document.getElementById('reg-plans-container');
    if (!plans.length) { el.innerHTML = '<p style="text-align:center;color:var(--texte-secondaire)">Aucun forfait disponible</p>'; return; }
    const icons = { graine: '🌱', racine: '🌿', baobab: '🌳' };
    const colors = { graine: '#4caf50', racine: '#ff9800', baobab: '#795548' };
    el.innerHTML = plans.map(p => {
      const price = p.price_per_student_year > 0 ? p.price_per_student_year + ' XOF / élève / an' : (p.trial_days > 0 ? 'Gratuit pendant ' + p.trial_days + ' jours' : 'Sur devis');
      const maxLabel = p.max_students ? 'Jusqu\'à ' + p.max_students + ' élèves' : 'Illimité';
      const trialLabel = p.trial_days > 0 ? '✅ Essai gratuit : ' + p.trial_days + ' jours' : (p.code === 'baobab' ? '📞 Tarif personnalisé' : 'Pas d\'essai');
      return `<div onclick="selectRegPlan('${p.code}')" id="reg-plan-${p.code}" style="border:2px solid var(--border);border-radius:12px;padding:16px;cursor:pointer;transition:all 0.2s;display:flex;gap:14px;align-items:flex-start;background:white" onmouseover="this.style.borderColor='var(--yiriba-vert)';this.style.background='#f0faf4'" onmouseout="if(_selectedPlan!=='${p.code}'){this.style.borderColor='var(--border)';this.style.background='white'}">
        <div style="font-size:32px;line-height:1">${icons[p.code] || '📦'}</div>
        <div style="flex:1">
          <div style="font-weight:700;font-size:16px;color:var(--yiriba-vert-profond);margin-bottom:2px">${p.name}</div>
          <div style="font-size:13px;color:var(--texte-secondaire);margin-bottom:6px">${maxLabel} · ${trialLabel}</div>
          <div style="font-size:14px;font-weight:600;color:${colors[p.code] || 'var(--texte-primaire)'}">${price}</div>
          ${p.code === 'baobab' ? '<div style="margin-top:8px"><span style="background:#fff3e0;color:#e65100;padding:4px 10px;border-radius:6px;font-size:12px;font-weight:600">Demander une offre</span></div>' : ''}
        </div>
        <div style="width:22px;height:22px;border-radius:50%;border:2px solid var(--border);display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:4px;transition:all 0.2s" id="reg-plan-check-${p.code}"></div>
      </div>`;
    }).join('');
  } catch(e) {
    document.getElementById('reg-plans-container').innerHTML = '<p style="text-align:center;color:#c62828">Erreur de chargement des forfaits</p>';
  }
}

function selectRegPlan(code) {
  _selectedPlan = code;
  // Reset all plans
  ['graine', 'racine', 'baobab'].forEach(c => {
    const el = document.getElementById('reg-plan-' + c);
    const check = document.getElementById('reg-plan-check-' + c);
    if (el) { el.style.borderColor = 'var(--border)'; el.style.background = 'white'; }
    if (check) { check.style.borderColor = 'var(--border)'; check.style.background = 'white'; check.innerHTML = ''; }
  });
  // Highlight selected
  const sel = document.getElementById('reg-plan-' + code);
  const selCheck = document.getElementById('reg-plan-check-' + code);
  if (sel) { sel.style.borderColor = 'var(--yiriba-vert)'; sel.style.background = '#f0faf4'; }
  if (selCheck) { selCheck.style.borderColor = 'var(--yiriba-vert)'; selCheck.style.background = 'var(--yiriba-vert)'; selCheck.innerHTML = '<i class="fas fa-check" style="color:white;font-size:11px"></i>'; }
  // Enable next button
  const btn = document.getElementById('reg-plan-next');
  if (btn) btn.disabled = false;
}

function regNextStep(step) {
  const el = document.getElementById('register-error'); el.textContent = '';
  if (step === 2) {
    const name = document.getElementById('reg-school-name').value.trim();
    if (!name) { el.textContent = 'Le nom de l\'école est requis'; return; }
    if (name.length < 2) { el.textContent = 'Le nom doit contenir au moins 2 caractères'; return; }
  }
  if (step === 3) {
    const cgv = document.getElementById('reg-cgv')?.checked;
    if (!cgv) {
      el.textContent = 'Veuillez lire et accepter les conditions d\'utilisation avant de continuer.';
      showCgvModal();
      return;
    }
    _loadRegPlans();
    _loadRegCaptcha();
  }
  // Hide all steps, show the target
  ['reg-step1', 'reg-step2', 'reg-step3', 'reg-step4'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
  const stepEl = document.getElementById('reg-step' + step);
  if (stepEl) stepEl.style.display = 'block';
  // Update progress dots
  const dots = ['reg-step1-dot', 'reg-step2-dot', 'reg-step3-dot', 'reg-step4-dot'];
  dots.forEach((id, i) => { const d = document.getElementById(id); if (d) d.style.background = i < step ? 'var(--yiriba-vert)' : 'var(--border)'; });
  const labels = ['Étape 1 sur 4 — Votre établissement', 'Étape 2 sur 4 — Informations du directeur', 'Étape 3 sur 4 — Votre forfait', 'Étape 4 sur 4 — Confirmation'];
  document.getElementById('reg-step-label').textContent = labels[step - 1] || '';
}
async function regSubmit() {
  const el = document.getElementById('register-error'); el.textContent = '';
  const firstName = document.getElementById('reg-first-name').value.trim();
  const lastName = document.getElementById('reg-last-name').value.trim();
  const email = document.getElementById('reg-email').value.trim();
  if (!firstName) { el.textContent = 'Le prénom du directeur est requis'; return; }
  if (!lastName) { el.textContent = 'Le nom du directeur est requis'; return; }
  if (!email) { el.textContent = 'L\'email du directeur est requis'; return; }
  if (!email.includes('@')) { el.textContent = 'L\'email n\'est pas valide'; return; }
  if (!_selectedPlan) { el.textContent = 'Veuillez choisir un forfait'; return; }
  const cgvChecked = document.getElementById('reg-cgv')?.checked;
  if (!cgvChecked) { el.textContent = 'Vous devez accepter les conditions d\'utilisation pour créer un compte'; return; }
  const cfg = await _loadRegConfig();
  if (cfg.turnstile_site_key && !_turnstileToken) { el.textContent = 'Veuillez valider la vérification anti-robot'; return; }
  try {
    const btn = document.getElementById('reg-plan-next');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Création...'; }
    const r = await fetch(`${API}/api/auth/register-school`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        school_name: document.getElementById('reg-school-name').value.trim(),
        school_type: document.getElementById('reg-school-type').value,
        school_city: document.getElementById('reg-school-city').value.trim() || null,
        admin_first_name: firstName,
        admin_last_name: lastName,
        admin_email: email,
        admin_phone: document.getElementById('reg-phone').value.trim() || null,
        plan_code: _selectedPlan,
        cgv_accepted: true,
        turnstile_token: _turnstileToken || null,
      })
    });
    const d = await r.json();
    if (!r.ok) {
      let msg = 'Erreur';
      if (Array.isArray(d.detail)) msg = d.detail.map(e => e.msg || e.message || String(e)).join('\n');
      else if (d.detail) msg = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail);
      else if (d.error) msg = d.error;
      throw new Error(msg);
    }
    // Show confirmation step
    document.getElementById('reg-yiriba-id').textContent = d.admin?.yiriba_id || '—';
    const tempPwd = d.admin?.temp_password;
    document.getElementById('reg-temp-pwd').textContent = tempPwd || '—';
    const confirmMode = !!d.confirmation_required;
    document.getElementById('reg-confirm-email-box').style.display = confirmMode ? 'block' : 'none';
    document.getElementById('reg-temp-pwd-box').style.display = (tempPwd && !confirmMode) ? 'block' : 'none';
    const urlBtn = document.getElementById('reg-confirm-url-btn');
    if (confirmMode && d.confirmation_url) {
      urlBtn.style.display = 'inline-block';
      urlBtn.onclick = () => window.open(d.confirmation_url, '_blank');
    } else if (urlBtn) {
      urlBtn.style.display = 'none';
    }
    // Show subscription info if available
    const subEl = document.getElementById('reg-sub-info');
    if (subEl && d.subscription) {
      const s = d.subscription;
      subEl.style.display = 'block';
      if (s.trial_days > 0) {
        subEl.innerHTML = '<div style="background:#e8f5e9;border-radius:10px;padding:12px;text-align:left;margin-bottom:12px"><div style="font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:#2e7d32;margin-bottom:4px">Forfait ' + s.name + ' — Essai gratuit</div><div style="font-size:13px;color:#1b5e20">Votre essai de ' + s.trial_days + ' jours est actif. Aucun paiement requis pour le moment.</div></div>';
      } else if (s.code === 'racine') {
        subEl.innerHTML = '<div style="background:#fff3e0;border-radius:10px;padding:12px;text-align:left;margin-bottom:12px"><div style="font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:#e65100;margin-bottom:4px">Forfait ' + s.name + '</div><div style="font-size:13px;color:#bf360c">Contactez notre équipe pour finaliser votre abonnement.</div></div>';
      } else {
        subEl.innerHTML = '<div style="background:#e3f2fd;border-radius:10px;padding:12px;text-align:left;margin-bottom:12px"><div style="font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:#1565c0;margin-bottom:4px">Forfait ' + s.name + '</div><div style="font-size:13px;color:#0d47a1">Notre équipe vous contactera pour établir un devis personnalisé.</div></div>';
      }
    }
    regNextStep(4);
  } catch (err) { el.textContent = err.message; if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-check"></i> Créer l\'école'; } }
}
function copyYiribaId() {
  const id = document.getElementById('reg-yiriba-id').textContent;
  if (id && id !== '—') {
    navigator.clipboard.writeText(id).then(() => {
      const msg = document.getElementById('reg-copy-msg'); msg.style.display = 'block';
      setTimeout(() => msg.style.display = 'none', 2000);
    });
  }
}

function copyTempPwd() {
  const pwd = document.getElementById('reg-temp-pwd').textContent;
  if (pwd && pwd !== '—') {
    navigator.clipboard.writeText(pwd).then(() => {
      const msg = document.getElementById('reg-copy-pwd-msg'); if (msg) { msg.style.display = 'block'; setTimeout(() => msg.style.display = 'none', 2000); }
    });
  }
}
function regGoToLogin() {
  document.getElementById('register-form').style.display = 'none';
  document.getElementById('login-form').style.display = 'block';
  document.getElementById('auth-subtitle').textContent = 'Connectez-vous à votre espace';
}

async function handleRegister(e) {
  e.preventDefault();
  // Legacy — now handled by regNextStep/regSubmit
}
function logout() { try { fetch(`${API}/api/auth/logout`, { method: 'POST', keepalive: true }).catch(() => {}); } catch {} document.cookie = 'yiriba_access=; Max-Age=0; path=/'; state.token = null; state.refreshToken = null; state.user = null; localStorage.removeItem('yiriba_token'); localStorage.removeItem('yiriba_refresh'); sessionStorage.removeItem('yiriba_token'); sessionStorage.removeItem('yiriba_refresh'); closeProfileMenu(); document.getElementById('app-screen').style.display = 'none'; document.getElementById('auth-screen').style.display = 'flex'; }

function toggleProfileMenu(ev) {
  if (ev) ev.stopPropagation();
  const dd = document.getElementById('profile-dropdown');
  const wrap = document.getElementById('profile-menu');
  if (!dd || !wrap) return;
  const open = dd.classList.toggle('open');
  wrap.setAttribute('aria-expanded', open ? 'true' : 'false');
}
function closeProfileMenu() {
  const dd = document.getElementById('profile-dropdown');
  const wrap = document.getElementById('profile-menu');
  if (dd) dd.classList.remove('open');
  if (wrap) wrap.setAttribute('aria-expanded', 'false');
}
document.addEventListener('click', (ev) => {
  const wrap = document.getElementById('profile-menu');
  if (wrap && !wrap.contains(ev.target)) closeProfileMenu();
});
document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') closeProfileMenu(); });

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  if (!sidebar) return;
  const isOpen = sidebar.classList.toggle('open');
  if (overlay) overlay.classList.toggle('show', isOpen);
}

// Ferme le menu mobile quand un lien de navigation est cliqué
document.addEventListener('click', function (e) {
  if (window.innerWidth <= 560 && e.target.closest('.nav-link')) {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    if (sidebar) sidebar.classList.remove('open');
    if (overlay) overlay.classList.remove('show');
  }
});

/* -- Change Password Modal (first login) ------------------------- */
function showChangePasswordModal() {
  showModal('Changer votre mot de passe', `
    <div style="text-align:center;margin-bottom:20px">
      <div style="width:60px;height:60px;border-radius:50%;background:var(--yiriba-ivoire);display:flex;align-items:center;justify-content:center;margin:0 auto 12px"><i class="fas fa-shield-halved" style="font-size:24px;color:var(--yiriba-vert)"></i></div>
      <h3 style="font-family:'Sora',sans-serif;font-size:16px;margin-bottom:4px">Bienvenue sur YIRIBA</h3>
      <p style="font-size:13px;color:var(--texte-secondaire)">Pour sécuriser votre compte, veuillez définir votre nouveau mot de passe.</p>
    </div>
    <div style="display:flex;flex-direction:column;gap:14px">
      <div><label style="font-size:12px;font-weight:600;color:var(--texte-primaire);margin-bottom:4px;display:block">Nouveau mot de passe</label>
        <div class="auth-input-wrap"><input type="password" id="new-pwd" placeholder="Minimum 8 caractères" style="width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:8px;font-size:14px"></div></div>
      <div><label style="font-size:12px;font-weight:600;color:var(--texte-primaire);margin-bottom:4px;display:block">Confirmer le mot de passe</label>
        <div class="auth-input-wrap"><input type="password" id="confirm-pwd" placeholder="Retapez le mot de passe" style="width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:8px;font-size:14px"></div></div>
      <button class="btn-action" id="btn-change-pwd" onclick="submitChangePassword()" style="width:100%;padding:12px;background:var(--yiriba-vert);color:white;border:none;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer">Définir le mot de passe</button>
    </div>
  `);
}
async function submitChangePassword() {
  const pwd = document.getElementById('new-pwd').value;
  const confirm = document.getElementById('confirm-pwd').value;
  if (!pwd || pwd.length < 8) { showToast('Le mot de passe doit contenir au moins 8 caractères', 'error'); return; }
  if (pwd !== confirm) { showToast('Les mots de passe ne correspondent pas', 'error'); return; }
  const btn = document.getElementById('btn-change-pwd');
  btn.disabled = true; btn.textContent = 'Enregistrement...';
  try {
    const r = await api('/api/auth/change-password', { method: 'POST', body: JSON.stringify({ new_password: pwd }) });
    if (r?.ok) {
      const data = await r.json().catch(() => ({}));
      showToast('Mot de passe changé avec succès !');
      closeModal();
      // Use new tokens from backend (with must_change_password: false)
      if (data.access_token) {
        state.token = data.access_token;
        state.refreshToken = data.refresh_token;
        localStorage.setItem('yiriba_token', data.access_token);
        localStorage.setItem('yiriba_refresh', data.refresh_token || '');
        // Decode updated user info
        const payload = decodeJwtPayload(data.access_token);
        if (payload) {
          state.user = { ...state.user, must_change_password: false };
        }
      }
      await enterApp();
    } else {
      const d = await r.json().catch(() => ({}));
      showToast(d.detail || 'Erreur', 'error');
      btn.disabled = false; btn.textContent = 'Définir le mot de passe';
    }
  } catch { showToast('Erreur réseau', 'error'); btn.disabled = false; btn.textContent = 'Définir le mot de passe'; }
}

/* -- Google OAuth ------------------------------------------------ */
function loginWithGoogle() {
  const slugInput = document.getElementById('login-school-slug');
  const slug = slugInput ? slugInput.value.trim() : '';
  const params = slug ? '?school_slug=' + encodeURIComponent(slug) : '';
  window.location.href = API + '/api/auth/google' + params;
}
function handleGoogleAuthFragment() {
  const hash = window.location.hash;
  if (!hash || !hash.includes('google-auth=')) return false;
  try {
    const fragment = hash.split('google-auth=')[1];
    const params = new URLSearchParams(fragment);
    const token = params.get('token');
    const refresh = params.get('refresh');
    if (token) {
      state.token = token;
      state.refreshToken = refresh || '';
      localStorage.setItem('yiriba_token', token);
      if (refresh) localStorage.setItem('yiriba_refresh', refresh);
      // Decode user from JWT
      const payload = decodeJwtPayload(token);
      if (payload) {
        state.user = { id: payload.sub, school_id: payload.school_id, role_type: payload.role, email: payload.email };
        state.schoolId = payload.school_id;
      }
      // Clear the hash to avoid re-processing
      history.replaceState(null, '', window.location.pathname);
      enterApp();
      return true;
    }
  } catch (err) { console.error('Google auth fragment error:', err); }
  return false;
}

function decodeJwtPayload(token) {
  try {
    const payload = token.split('.')[1];
    const decoded = payload.replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeURIComponent(atob(decoded).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join(''));
    return JSON.parse(json);
  } catch { return null; }
}
async function enterApp() {
  document.getElementById('auth-screen').style.display = 'none';
  document.getElementById('app-screen').style.display = 'flex';
  // Decode user from JWT if state.user is missing (page reload)
  if (!state.user && state.token) {
    const payload = decodeJwtPayload(state.token);
    if (payload) {
      state.user = { id: payload.sub, school_id: payload.school_id, role_type: payload.role, email: payload.email, username: payload.username };
      state.schoolId = payload.school_id;
      state.roleType = payload.role;
    }
  }
  // Check must_change_password from JWT (first login)
  const payload = state.token ? decodeJwtPayload(state.token) : null;
  if (payload && payload.must_change_pwd) {
    document.getElementById('app-screen').style.display = 'none';
    document.getElementById('auth-screen').style.display = 'flex';
    showChangePasswordModal();
    return;
  }
  const fn = state.user?.first_name || state.user?.email || 'Utilisateur', ln = state.user?.last_name || '';
  document.getElementById('user-avatar').textContent = (fn.charAt(0) + ln.charAt(0)).toUpperCase();
  document.getElementById('user-name-display').textContent = `${fn} ${ln}`.trim();
  // Store role_type for portal routing
  state.roleType = state.user?.role_type || 'admin';
  // Load portal-specific sidebar and dashboard
  loadPortal(state.roleType);
}

/* ==============================================================
   PORTAL ROUTING — Redirige selon le rôle de l'utilisateur
   ============================================================== */
function loadPortal(roleType) {
  state.portal = roleType || 'admin';
  // Load portal-specific sidebar
  loadPortalSidebar(state.portal);
  // Load portal-specific dashboard

  // Charger la page d'accueil via loadPage pour mettre à jour titre + contenu
  if (state.portal === 'teacher') loadPage('t-dashboard');
  else if (state.portal === 'parent') loadPage('p-dashboard');
  else if (state.portal === 'student') loadPage('s-dashboard');
  else if (state.portal === 'comptable') loadPage('c-dashboard');
  else loadPage('dashboard'); // admin
}

function loadPortalSidebar(portal) {
  const nav = document.getElementById('nav-main');
  const navAdmin = document.getElementById('nav-admin');
  const schoolCtx = document.querySelector('.school-context');
  const sub = document.getElementById('sub-badge');

  if (portal === 'teacher') {
    nav.innerHTML = `
      <a class="nav-link active" onclick="loadPage('t-dashboard')"><span class="nav-icon"><i class="fas fa-house"></i></span><span>Accueil</span></a>
      <a class="nav-link" onclick="loadPage('t-classes')"><span class="nav-icon"><i class="fas fa-chalkboard"></i></span><span>Mes classes</span></a>
      <a class="nav-link" onclick="loadPage('t-grades')"><span class="nav-icon"><i class="fas fa-pen-fancy"></i></span><span>Notes</span></a>
      <a class="nav-link" onclick="loadPage('t-attendance')"><span class="nav-icon"><i class="fas fa-clipboard-check"></i></span><span>Présences</span></a>
      <a class="nav-link" onclick="loadPage('t-bulletins')"><span class="nav-icon"><i class="fas fa-file-lines"></i></span><span>Bulletins</span></a>
      <a class="nav-link" onclick="loadPage('t-timetable')"><span class="nav-icon"><i class="fas fa-calendar-days"></i></span><span>Emploi du temps</span></a>
      <a class="nav-link" onclick="loadPage('t-notifications')"><span class="nav-icon"><i class="fas fa-bell"></i></span><span>Notifications</span></a>
    `;
    if (navAdmin) navAdmin.innerHTML = '';
    if (schoolCtx) schoolCtx.textContent = 'Portail Enseignant';
  } else if (portal === 'parent') {
    nav.innerHTML = `
      <a class="nav-link active" onclick="loadPage('p-dashboard')"><span class="nav-icon"><i class="fas fa-house"></i></span><span>Accueil</span></a>
      <a class="nav-link" onclick="loadPage('p-children')"><span class="nav-icon"><i class="fas fa-children"></i></span><span>Mes enfants</span></a>
      <a class="nav-link" onclick="loadPage('p-scolarite')"><span class="nav-icon"><i class="fas fa-school"></i></span><span>Scolarité</span></a>
      <a class="nav-link" onclick="loadPage('p-grades')"><span class="nav-icon"><i class="fas fa-pen-fancy"></i></span><span>Résultats</span></a>
      <a class="nav-link" onclick="loadPage('p-attendance')"><span class="nav-icon"><i class="fas fa-clipboard-check"></i></span><span>Présences</span></a>
      <a class="nav-link" onclick="loadPage('p-bulletins')"><span class="nav-icon"><i class="fas fa-file-lines"></i></span><span>Bulletins</span></a>
      <a class="nav-link" onclick="loadPage('p-evaluations')"><span class="nav-icon"><i class="fas fa-calendar-plus"></i></span><span>Devoirs & évaluations</span></a>
      <a class="nav-link" onclick="loadPage('p-timetable')"><span class="nav-icon"><i class="fas fa-calendar-days"></i></span><span>Emploi du temps</span></a>
      <a class="nav-link" onclick="loadPage('p-payments')"><span class="nav-icon"><i class="fas fa-money-bill-wave"></i></span><span>Paiements</span></a>
      <a class="nav-link" onclick="loadPage('p-documents')"><span class="nav-icon"><i class="fas fa-folder-open"></i></span><span>Documents</span></a>
      <a class="nav-link" onclick="loadPage('p-messages')"><span class="nav-icon"><i class="fas fa-comments"></i></span><span>Échanges</span></a>
      <a class="nav-link" onclick="loadPage('p-notifications')"><span class="nav-icon"><i class="fas fa-bell"></i></span><span>Notifications</span></a>
      <a class="nav-link" onclick="loadPage('p-rappels')"><span class="nav-icon"><i class="fas fa-clipboard-list"></i></span><span>Rappels</span></a>
      <a class="nav-link" onclick="loadPage('p-settings')"><span class="nav-icon"><i class="fas fa-gear"></i></span><span>Paramètres</span></a>
    `;
    if (navAdmin) navAdmin.innerHTML = '';
    if (schoolCtx) schoolCtx.textContent = 'Portail Parent';
  } else if (portal === 'student') {
    nav.innerHTML = `
      <a class="nav-link active" onclick="loadPage('s-dashboard')"><span class="nav-icon"><i class="fas fa-house"></i></span><span>Accueil</span></a>
      <a class="nav-link" onclick="loadPage('s-grades')"><span class="nav-icon"><i class="fas fa-pen-fancy"></i></span><span>Mes notes</span></a>
      <a class="nav-link" onclick="loadPage('s-subjects')"><span class="nav-icon"><i class="fas fa-book-open"></i></span><span>Mes matières</span></a>
      <a class="nav-link" onclick="loadPage('s-attendance')"><span class="nav-icon"><i class="fas fa-clipboard-check"></i></span><span>Mes présences</span></a>
      <a class="nav-link" onclick="loadPage('s-bulletins')"><span class="nav-icon"><i class="fas fa-file-lines"></i></span><span>Mes bulletins</span></a>
      <a class="nav-link" onclick="loadPage('s-timetable')"><span class="nav-icon"><i class="fas fa-calendar-days"></i></span><span>Emploi du temps</span></a>
      <a class="nav-link" onclick="loadPage('s-homework')"><span class="nav-icon"><i class="fas fa-book-bookmark"></i></span><span>Mes devoirs</span></a>
      <a class="nav-link" onclick="loadPage('s-notifications')"><span class="nav-icon"><i class="fas fa-bell"></i></span><span>Notifications</span></a>
    `;
    if (navAdmin) navAdmin.innerHTML = '';
    if (schoolCtx) schoolCtx.textContent = 'Portail Élève';
  } else if (portal === 'comptable') {
    nav.innerHTML = `
      <a class="nav-link active" onclick="loadPage('c-dashboard')"><span class="nav-icon"><i class="fas fa-house"></i></span><span>Accueil</span></a>
      <a class="nav-link" onclick="loadPage('payments')"><span class="nav-icon"><i class="fas fa-money-bill-wave"></i></span><span>Paiements</span></a>
      <a class="nav-link" onclick="loadPage('debtors')"><span class="nav-icon"><i class="fas fa-hand-holding-dollar"></i></span><span>Impayés & relances</span></a>
      <a class="nav-link" onclick="loadPage('fee-structure')"><span class="nav-icon"><i class="fas fa-file-invoice-dollar"></i></span><span>Structure des frais</span></a>
      <a class="nav-link" onclick="loadPage('students')"><span class="nav-icon"><i class="fas fa-user-graduate"></i></span><span>Élèves</span></a>
      <a class="nav-link" onclick="loadPage('parents')"><span class="nav-icon"><i class="fas fa-people-roof"></i></span><span>Parents</span></a>
    `;
    if (navAdmin) navAdmin.innerHTML = '';
    if (schoolCtx) schoolCtx.textContent = 'Portail Comptabilité';
  } else {
    // Admin — sidebar à catégories dépliables (admin_nav.js)
    renderAdminNav();
    if (schoolCtx) schoolCtx.textContent = 'Vos Racines Digitalisées';
  }
  if (sub) sub.remove();
}

/* -- Navigation ----------------------------------------------- */
function setActiveNav(id) {
  document.querySelectorAll('.nav-link').forEach(l => {
    l.classList.remove('active');
    l.removeAttribute('aria-current');
  });
  const link = document.querySelector(`.nav-link[data-page="${id}"]`);
  if (link) {
    link.classList.add('active');
    link.setAttribute('aria-current', 'page');
    if (typeof ensureNavGroupOpenForPage === 'function') ensureNavGroupOpenForPage(id);
  }
}
function loadPage(page) {
  setActiveNav(page);
  // Portal-specific pages
  const portalPages = {
    // Teacher portal
    't-dashboard': ['Accueil', 'Portail Enseignant'],
    't-classes': ['Mes classes', 'Enseignement'],
    't-grades': ['Notes', 'Saisie rapide'],
    't-attendance': ['Présences', 'Appel'],
    't-bulletins': ['Bulletins', 'Consultation'],
    't-timetable': ['Emploi du temps', 'Planning'],
    't-notifications': ['Notifications', 'Alertes'],
    // Parent portal
    'p-dashboard': ['Accueil', 'Portail Parent'],
    'p-children': ['Mes enfants', 'Suivi'],
    'p-scolarite': ['Scolarité', 'Situation'],
    'p-grades': ['Résultats', 'Notes'],
    'p-attendance': ['Présences', 'Suivi'],
    'p-bulletins': ['Bulletins', 'Consultation'],
    'p-evaluations': ['Devoirs & évaluations', 'Suivi'],
    'p-payments': ['Paiements', 'Frais scolaires'],
    'p-timetable': ['Emploi du temps', 'Planning'],
    'p-documents': ['Documents', 'Consultation'],
    'p-notifications': ['Notifications', 'Alertes'],
      'p-rappels': ['Rappels', 'Suivi'],
      'p-messages': ['Échanges', 'Messagerie'],
      'p-settings': ['Paramètres', 'Compte'],
    // Student portal
    's-dashboard': ['Accueil', 'Portail Élève'],
    's-grades': ['Mes notes', 'Résultats'],
    's-bulletins': ['Mes bulletins', 'Consultation'],
    's-attendance': ['Mes présences', 'Suivi'],
    's-subjects': ['Mes matières', 'Matières'],
    's-timetable': ['Emploi du temps', 'Planning'],
    's-homework': ['Mes devoirs', 'Évaluations'],
    's-notifications': ['Notifications', 'Alertes'],
    // Admin portal
    'dashboard': ['Tableau de bord', "Vue d'ensemble"],
    'students': ['Élèves', 'Gestion'],
    'classes': ['Classes', 'Gestion'],
    'teachers': ['Enseignants', 'Gestion'],
    'grades': ['Notes', 'Saisie'],
    'attendance': ['Présences', 'Suivi'],
    'attendance-justify': ['Présences', 'Justifications'],
    'bulletins': ['Bulletins', 'Génération'],
    'payments': ['Paiements', 'Suivi'],
    'timetable': ['Emploi du temps', 'Planning'],
    'messaging': ['Messagerie', 'Conversations'],
    'fee-structure': ['Structure des frais', 'Configuration'],
    'debtors': ['Impayés & relances', 'Finance'],
    'parents': ['Parents', 'Gestion'],
    'users': ['Utilisateurs', 'Comptes'],
    'communication': ['Communication', 'Annonces'],
    'notif-preferences': ['Préférences notifications', 'Configuration'],
    'roles': ['Rôles & Permissions', 'Configuration'],
    'audit': ['Audit', 'Journal'],
    'settings': ['Paramètres', 'Config'],
    'academic-years': ['Années scolaires', 'Configuration'],
    'academic-config': ['Configuration académique', 'Périodes'],
    'cycles': ['Cycles & Niveaux', 'Configuration'],
    'class-subjects': ['Matières par classe', 'Configuration'],
    'promotion': ['Passage de classe', 'Fin d\'année'],
    'next-year': ['Préparer l\'année suivante', 'Inscriptions'],
    'c-dashboard': ['Accueil', 'Portail Comptabilité'],
    'subscription': ['Abonnement', 'Forfait'],
  };
  const [ti, su] = portalPages[page] || ['Yiriba', ''];
  document.querySelector('.topbar-title').textContent = ti;
  document.querySelector('.topbar-subtitle').textContent = su;
  // Admin pages
  if (page === 'dashboard') loadDashboard();
  else if (page === 'students') loadStudents();
  else if (page === 'classes') loadClasses();
  else if (page === 'grades') loadGrades();
  else if (page === 'attendance') loadAttendance();
  else if (page === 'attendance-justify') loadAttendanceJustify();
  else if (page === 'bulletins') loadBulletins();
  else if (page === 'payments') loadPayments();
  else if (page === 'debtors') loadDebtors();
  else if (page === 'fee-structure') loadFeeStructure();
  else if (page === 'timetable') loadTimetable();
  else if (page === 'teachers') loadTeachers();
  else if (page === 'parents') loadParents();
  else if (page === 'users') loadUsers();
  else if (page === 'roles') loadRoles();
  else if (page === 'subscription') loadSubscription();
  else if (page === 'audit') loadAudit();
  else if (page === 'communication') loadCommunication();
  else if (page === 'notif-preferences') loadNotifPreferences();
  else if (page === 'settings') loadSettings();
  else if (page === 'academic-years') loadAcademicYears();
  else if (page === 'academic-config') loadAcademicConfig();
  else if (page === 'cycles') loadCycles();
  else if (page === 'class-subjects') loadClassSubjectsConfig();
  else if (page === 'promotion') loadPromotion();
  else if (page === 'next-year') loadNextYearPrep();
  // Teacher portal pages
  else if (page === 't-dashboard') loadTeacherDashboard();
  else if (page === 't-classes') loadTeacherClasses();
  else if (page === 't-grades') loadTeacherGrades();
  else if (page === 't-attendance') loadTeacherAttendance();
  else if (page === 't-bulletins') loadBulletins();
  else if (page === 't-timetable') loadTeacherTimetable();
  else if (page === 'notifications') loadNotifications();
  else if (page === 't-notifications') loadNotifications();
  // Parent portal pages
  else if (page === 'p-dashboard') loadParentDashboard();
  else if (page === 'p-children') loadParentChildren();
  else if (page === 'p-scolarite') loadParentScolarite();
  else if (page === 'p-grades') loadParentGrades();
  else if (page === 'p-attendance') loadParentAttendance();
  else if (page === 'p-bulletins') loadParentBulletins();
  else if (page === 'p-evaluations') loadParentEvaluations();
  else if (page === 'p-payments') loadParentPayments();
  else if (page === 'p-timetable') loadParentTimetable();
  else if (page === 'p-documents') loadParentDocuments();
  else if (page === 'p-notifications') loadParentNotifications();
  else if (page === 'p-rappels') loadParentRappels();
  else if (page === 'p-messages') loadParentMessages();
  else if (page === 'p-settings') loadParentSettings();
  // Student portal pages
  else if (page === 's-dashboard') loadStudentDashboard();
  else if (page === 's-grades') loadStudentGrades();
  else if (page === 's-subjects') loadStudentSubjects();
  else if (page === 's-bulletins') loadStudentBulletins();
  else if (page === 's-attendance') loadStudentAttendance();
  else if (page === 's-timetable') loadStudentTimetable();
  else if (page === 's-homework') loadStudentHomework();
  else if (page === 's-notifications') loadNotifications();
  // Comptable portal pages
  else if (page === 'c-dashboard') loadComptableDashboard();
  else if (page === 'messaging') loadMessaging();
  else loadPlaceholder(page);
}

/* ==============================================================
   DASHBOARD — Reproduction exacte de la maquette
   ============================================================== */
async function loadDashboard() {
  const c = document.getElementById('main-content');
  let d = { students: 0, classes: 0, teachers: 0, attendance: 0, payments: 0, pendingPayments: 0, absences: 0, bulletins: 0, auditLog: [], studentsByLevel: {}, paymentsByStatus: {} };
  try {
    const [s, cl, t, p, a, pay, audit, sub] = await Promise.all([
      api('/api/students?per_page=1').catch(()=>null),
      api('/api/classes?per_page=1').catch(()=>null),
      api('/api/admin/users?per_page=1').catch(()=>null),
      api('/api/attendance?per_page=1').catch(()=>null),
      api('/api/attendance?status=absent&per_page=1').catch(()=>null),
      api('/api/payments?per_page=1').catch(()=>null),
      api('/api/admin/audit-log?per_page=4').catch(()=>null),
      api('/api/subscriptions/my-summary').catch(()=>null)
    ]);
    if (s?.ok) { const j = await s.json(); d.students = j.total || j.count || 0; }
    if (cl?.ok) { const j = await cl.json(); d.classes = j.total || j.count || 0; }
    if (t?.ok) { const j = await t.json(); d.teachers = j.total || j.count || 0; }
    if (a?.ok) { const j = await a.json(); d.absences = j.total || j.count || 0; }
    if (pay?.ok) { const j = await pay.json(); d.payments = j.total || j.count || 0; }
    if (audit?.ok) { const j = await audit.json(); d.auditLog = j.logs || j.items || []; }
    if (sub?.ok) { d.subscription = await sub.json(); state.subscription = d.subscription; }
  } catch {}
  const fn = state.user?.first_name || 'Directeur';
  const delta = Math.max(1, Math.floor(d.students * 0.025));

  const sub = d.subscription || {};
  const subAlert = sub.subscription_status === 'expired' ? `
    <div class="alert-banner alert-expired">
      <div class="alert-icon"><i class="fas fa-exclamation-triangle"></i></div>
      <div class="alert-content">
        <div class="alert-title">Votre abonnement a expiré</div>
        <div class="alert-text">Vos données sont accessibles en lecture seule. Choisissez un forfait pour réactiver la gestion complète.</div>
      </div>
      <button class="alert-btn" onclick="loadPage('subscriptions')">Choisir un forfait →</button>
    </div>
  ` : sub.subscription_status === 'trial' && sub.trial_ends_at ? `
    <div class="alert-banner alert-trial">
      <div class="alert-icon"><i class="fas fa-seedling"></i></div>
      <div class="alert-content">
        <div class="alert-title">Essai Graine actif</div>
        <div class="alert-text">Votre essai se termine le ${new Date(sub.trial_ends_at).toLocaleDateString('fr-FR', {day:'numeric',month:'long',year:'numeric'})}. Passez à un forfait payant pour continuer.</div>
      </div>
    </div>
  ` : '';

  // Student limit bar
  const limitBar = sub.plan?.max_students ? `
    <div class="limit-bar">
      <div class="limit-info">
        <span class="limit-plan"><i class="fas fa-${sub.plan?.code === 'graine' ? 'seedling' : sub.plan?.code === 'racine' ? 'leaf' : 'tree'}" style="margin-right:6px"></i>${sub.plan?.name || 'Graine'}</span>
        <span class="limit-count">${sub.student_count || 0} / ${sub.plan?.max_students} élèves</span>
      </div>
      <div class="limit-progress">
        <div class="limit-fill ${sub.usage_pct >= 80 ? 'limit-warning' : sub.usage_pct >= 100 ? 'limit-danger' : ''}" style="width:${Math.min(sub.usage_pct || 0, 100)}%"></div>
      </div>
      ${sub.usage_pct >= 80 ? `<div class="limit-alert"><i class="fas fa-exclamation-circle"></i> ${sub.usage_pct >= 100 ? 'Limite atteinte !' : 'Proche de la limite'}</div>` : ''}
    </div>
  ` : sub.plan?.code === 'baobab' ? `
    <div class="limit-bar">
      <div class="limit-info">
        <span class="limit-plan"><i class="fas fa-tree" style="margin-right:6px"></i>Baobab</span>
        <span class="limit-count">${sub.student_count || 0} élèves — Aucune limite</span>
      </div>
    </div>
  ` : '';

  c.innerHTML = `
    <!-- ALERTES ABONNEMENT -->
    ${subAlert}

    <!-- WELCOME -->
    <div class="welcome">
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div>
          <h1>Bonjour, ${fn} 👋</h1>
          <p>Voici un aperçu de la situation de votre école aujourd'hui.</p>
        </div>
        ${limitBar ? `<div style="min-width:280px">${limitBar}</div>` : ''}
      </div>
    </div>

    <!-- ZONE 1: STATISTIQUES -->
    <section class="stats-grid">
      <article class="card main-stat">
        <div class="stat-label"><i class="fas fa-graduation-cap" style="margin-right:6px;opacity:.7"></i>Élèves inscrits</div>
        <div class="stat-number">${d.students.toLocaleString('fr-FR')}</div>
        <div class="stat-change">+${delta} depuis le mois dernier ↗</div>
        <div class="stat-see" onclick="loadPage('students')">Voir les élèves <i class="fas fa-arrow-right" style="font-size:11px"></i></div>
      </article>
      <article class="card secondary-stat">
        <div class="stat-icon"><i class="fas fa-chalkboard"></i></div>
        <div class="stat-label">CLASSES</div>
        <div class="stat-number">${d.classes}</div>
        <div class="stat-change">+${Math.max(1,Math.floor(d.classes*0.06))} ce mois</div>
      </article>
      <article class="card secondary-stat">
        <div class="stat-icon"><i class="fas fa-person-chalkboard"></i></div>
        <div class="stat-label">ENSEIGNANTS</div>
        <div class="stat-number">${d.teachers}</div>
        <div class="stat-change">${Math.max(1,Math.floor(d.teachers*0.06))} nouveaux</div>
      </article>
    </section>

    <!-- ZONE 2: GRAPHIQUE + NOTIFICATIONS -->
    <section class="dashboard-grid">
      <article class="card section-card">
        <div class="section-header">
          <div>
            <div class="section-title">Évolution globale</div>
            <div class="section-description">Cette année scolaire</div>
          </div>
        </div>
        <div class="chart-legend">
          <div class="chart-legend-item"><span class="chart-legend-dot" style="background:var(--yiriba-vert)"></span><span id="leg-insc">Inscriptions</span></div>
          <div class="chart-legend-item"><span class="chart-legend-dot" style="background:var(--yiriba-jaune)"></span><span id="leg-pres">Présences moyennes (%)</span></div>
          <div class="chart-legend-item"><span class="chart-legend-dot" style="background:var(--yiriba-vert-feuille)"></span><span id="leg-pay">Paiements (FCFA)</span></div>
        </div>
        <div class="card-body"><div id="chart-area" style="height:240px"></div></div>
      </article>
      <article class="card section-card">
        <div class="section-header">
          <div class="section-title">Notifications récentes</div>
          <span class="section-link">Voir toutes</span>
        </div>
        <div style="display:flex;flex-direction:column;gap:0">
          ${d.pendingPayments > 0 ? `<div class="notif-item"><div class="notif-icon" style="background:rgba(201,74,53,0.1);color:var(--yiriba-rouge)"><i class="fas fa-file-invoice-dollar"></i></div><div style="flex:1"><div style="font-size:14px;font-weight:600">Paiements en attente</div><div style="font-size:12px;color:var(--texte-secondaire);margin-top:2px">${d.pendingPayments} paiements en attente</div></div></div>` : ''}
          ${d.absences > 0 ? `<div class="notif-item"><div class="notif-icon" style="background:rgba(242,183,5,0.12);color:#B38A00"><i class="fas fa-user-slash"></i></div><div style="flex:1"><div style="font-size:14px;font-weight:600">Absences aujourd'hui</div><div style="font-size:12px;color:var(--texte-secondaire);margin-top:2px">${d.absences} élèves absents</div></div></div>` : ''}
          ${d.bulletins > 0 ? `<div class="notif-item"><div class="notif-icon" style="background:rgba(47,143,91,0.08);color:var(--yiriba-vert-feuille)"><i class="fas fa-file-lines"></i></div><div style="flex:1"><div style="font-size:14px;font-weight:600">Bulletins prêts</div><div style="font-size:12px;color:var(--texte-secondaire);margin-top:2px">${d.bulletins} bulletins prêts</div></div></div>` : ''}
          ${d.students > 0 ? `<div class="notif-item"><div class="notif-icon" style="background:rgba(14,92,63,0.06);color:var(--yiriba-vert)"><i class="fas fa-user-plus"></i></div><div style="flex:1"><div style="font-size:14px;font-weight:600">Élèves inscrits</div><div style="font-size:12px;color:var(--texte-secondaire);margin-top:2px">${d.students} élèves au total</div></div></div>` : ''}
        </div>
      </article>
    </section>

    <!-- ZONE 3: NOTES / PAIEMENTS / RÉPARTITION / STATUT -->
    <section style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:16px">
      <article class="card section-card">
        <div class="section-title" style="font-size:14px;margin-bottom:16px">Notes ce mois</div>
        <div class="empty"><div class="empty-icon"><i class="fas fa-pen-fancy"></i></div><h4>Aucune note ce mois</h4><p>Les notes de cette période n'ont pas encore été saisies.</p><span class="link" onclick="loadPage('grades')">Commencer la saisie →</span></div>
      </article>
      <article class="card section-card">
        <div class="section-title" style="font-size:14px;margin-bottom:16px">Paiements ce mois</div>
        <div class="empty"><div class="empty-icon"><i class="fas fa-money-bill-wave"></i></div><h4>Aucun paiement enregistré</h4><p>Enregistrez le premier paiement pour commencer le suivi.</p><span class="link" onclick="loadPage('payments')">Enregistrer un paiement →</span></div>
      </article>
      <article class="card section-card">
        <div class="section-title" style="font-size:14px;margin-bottom:12px">Répartition des élèves</div>
        <div id="student-donut" style="display:flex;align-items:center;gap:16px"></div>
      </article>
      <article class="card section-card">
        <div class="section-title" style="font-size:14px;margin-bottom:12px">Statut des paiements</div>
        <div id="payment-donut" style="display:flex;align-items:center;gap:16px"></div>
      </article>
    </section>

    <!-- ZONE 4: ACTIONS RAPIDES + ACTIVITÉS -->
    <section class="dashboard-grid" style="margin-top:16px">
      <article class="card section-card">
        <div class="section-title" style="font-size:14px;margin-bottom:16px">Actions rapides</div>
        <div class="actions">
          <button class="primary-action" onclick="loadPage('students')"><strong>+ Ajouter un élève</strong><span>Créer rapidement un nouveau dossier élève.</span></button>
          <button class="action-button" onclick="loadPage('grades')"><i class="fas fa-pen-fancy" style="font-size:20px;color:var(--yiriba-vert);margin-bottom:8px"></i><strong>Saisir les notes</strong><span>Accéder à la saisie.</span></button>
          <button class="action-button" onclick="loadPage('attendance')"><i class="fas fa-clipboard-check" style="font-size:20px;color:var(--yiriba-vert);margin-bottom:8px"></i><strong>Faire l'appel</strong><span>Enregistrer les présences.</span></button>
          <button class="action-button" onclick="loadPage('payments')"><i class="fas fa-money-bill-wave" style="font-size:20px;color:var(--yiriba-jaune);margin-bottom:8px"></i><strong>Enregistrer un paiement</strong><span>Ajouter une opération.</span></button>
          <button class="action-button" onclick="loadPage('bulletins')"><i class="fas fa-file-lines" style="font-size:20px;color:var(--yiriba-vert-feuille);margin-bottom:8px"></i><strong>Générer un bulletin</strong><span>Créer ou publier.</span></button>
        </div>
      </article>
      <article class="card section-card">
        <div class="section-header"><div class="section-title">Activités récentes</div><span class="section-link">Voir toutes</span></div>
        <div style="display:flex;flex-direction:column;gap:12px">
          ${d.auditLog.length > 0 ? d.auditLog.map(log => {
            const colors = {'create':'var(--yiriba-vert)','update':'var(--yiriba-jaune)','delete':'var(--yiriba-rouge)','read':'var(--yiriba-vert-feuille)'};
            const color = colors[log.action?.toLowerCase()] || 'var(--yiriba-vert)';
            return `<div style="display:flex;align-items:flex-start;gap:10px"><div style="width:8px;height:8px;border-radius:50%;background:${color};margin-top:6px;flex-shrink:0"></div><div style="flex:1;font-size:13px;color:var(--texte-secondaire)">${log.description || log.action || 'Action inconnue'}</div><div style="font-size:11px;color:var(--texte-secondaire);white-space:nowrap">${log.created_at ? timeAgo(log.created_at) : ''}</div></div>`;
          }).join('') : '<div style="font-size:13px;color:var(--texte-secondaire);text-align:center;padding:20px">Aucune activité récente</div>'}
        </div>
      </article>
    </section>`;

  // Load chart data and donuts from API
  setTimeout(async () => {
    try {
      // Fetch students by month for chart
      const studentsRes = await api('/api/students?per_page=100');
      if (studentsRes?.ok) {
        const studentsData = await studentsRes.json();
        const students = studentsData.students || [];
        // Group by month for evolution chart
        const monthCounts = {};
        months.forEach((m, i) => monthCounts[m] = 0);
        students.forEach(s => {
          if (s.created_at) {
            const d = new Date(s.created_at);
            const mIdx = (d.getMonth() + 4) % 12;
            const m = months[mIdx];
            if (m && monthCounts[m] !== undefined) monthCounts[m]++;
          }
        });
        chartData.insc = months.map(m => monthCounts[m] || 0);
      }
      // Fetch attendance for chart
      const attRes = await api('/api/attendance?per_page=500');
      if (attRes?.ok) {
        const attData = await attRes.json();
        const atts = attData.attendance || attData.attendances || [];
        const monthPres = {};
        months.forEach((m, i) => monthPres[m] = {present: 0, total: 0});
        atts.forEach(a => {
          if (a.date) {
            const d = new Date(a.date);
            const mIdx = (d.getMonth() + 4) % 12;
            const m = months[mIdx];
            if (m && monthPres[m] !== undefined) {
              monthPres[m].total++;
              if (a.status === 'present') monthPres[m].present++;
            }
          }
        });
        chartData.pres = months.map(m => {
          const mp = monthPres[m];
          return mp.total > 0 ? Math.round((mp.present / mp.total) * 100) : 0;
        });
      }
      // Fetch payments for chart
      const payRes = await api('/api/payments?per_page=100');
      if (payRes?.ok) {
        const payData = await payRes.json();
        const pays = payData.payments || [];
        const monthPay = {};
        months.forEach((m, i) => monthPay[m] = 0);
        pays.forEach(p => {
          const dateField = p.paid_at || p.created_at;
          if (dateField && p.status === 'confirmed') {
            const d = new Date(dateField);
            const mIdx = (d.getMonth() + 4) % 12;
            const m = months[mIdx];
            if (m && monthPay[m] !== undefined) monthPay[m] += (p.amount || 0);
          }
        });
        chartData.pay = months.map(m => Math.round(monthPay[m] / 1000)); // In thousands FCFA
      }
    } catch (e) { console.log('Chart data error:', e); }
    renderChart();
    // Update legend with actual values
    const maxI = Math.max(...(chartData.insc.length ? chartData.insc : [0]));
    const presNonZero = chartData.pres.filter(v => v > 0);
    const maxP = presNonZero.length > 0 ? Math.max(...presNonZero) : 0;
    const payNonZero = chartData.pay.filter(v => v > 0);
    const maxPay = payNonZero.length > 0 ? Math.max(...payNonZero) : 0;
    const legInsc = document.getElementById('leg-insc');
    const legPres = document.getElementById('leg-pres');
    const legPay = document.getElementById('leg-pay');
    if (legInsc) legInsc.textContent = `Inscriptions (${maxI})`;
    if (legPres) legPres.textContent = `Présences moyennes (${maxP}%)`;
    if (legPay) legPay.textContent = `Paiements (${(maxPay * 1000).toLocaleString('fr-FR')} FCFA)`;
    // Fetch donut data from dashboard endpoint (single call, no N+1)
    try {
      const dRes = await api('/api/admin/dashboard');
      if (dRes?.ok) {
        const dash = await dRes.json();
        // Student donut by class (from dashboard class_distribution)
        const classDist = dash.class_distribution || {};
        const enrolledTotal = Object.values(classDist).reduce((a,b) => a+b, 0);
        const activeStudents = dash.active_students || 0;
        const classLabels = Object.keys(classDist);
        const classValues = Object.values(classDist);
        // Add non-enrolled students as separate category if any
        if (activeStudents > enrolledTotal) {
          classLabels.push('Non inscrits');
          classValues.push(activeStudents - enrolledTotal);
        }
        const classColors = ['#0E5C3F','#2F8F5B','#F2B705','#083D2B','#C94A35','#68766F','#3A7BBF','#8B5CF6','#B0B0B0'];
        if (classLabels.length > 0) {
          renderDonut('student-donut', classValues, classLabels, classColors);
        }
        // Payment status donut (from dashboard payment_status)
        const payStatus = dash.payment_status || {};
        const payLabels = Object.keys(payStatus);
        const payValues = Object.values(payStatus);
        const payColors = payLabels.map(l => l === 'Payés' ? '#0E5C3F' : l === 'En attente' ? '#F2B705' : l === 'En retard' ? '#C94A35' : '#2F8F5B');
        if (payValues.length > 0) renderDonut('payment-donut', payValues, payLabels, payColors);
      }
    } catch (e) { console.log('Donut data error:', e); }
  }, 50);
}

/* -- Notif Item CSS ------------------------------------------- */
const notifStyle = document.createElement('style');
notifStyle.textContent = `.notif-item{display:flex;align-items:flex-start;gap:12px;padding:13px 0;border-bottom:1px solid var(--border)}.notif-item:last-child{border-bottom:none}.notif-icon{width:36px;height:36px;display:grid;place-items:center;border-radius:10px;font-size:14px;flex-shrink:0}`;
document.head.appendChild(notifStyle);

/* ==============================================================
   MODULE ÉLÈVES — Tableau CRUD Yiriba
   ============================================================== */
let studentsPage = 1, studentsSearch = '', studentsFilter = { status: 'all', level: '', academic_year: '' };

async function loadStudents() {
  const c = document.getElementById('main-content');
  // Fetch students + classes for indicators
  let students = [], total = 0, classes = [];
  try {
    const params = new URLSearchParams({ page: studentsPage, per_page: 15 });
    if (studentsSearch) params.set('search', studentsSearch);
    if (studentsFilter.status) params.set('status', studentsFilter.status);
    if (studentsFilter.gender) params.set('gender', studentsFilter.gender);
    if (studentsFilter.class_id) params.set('class_id', studentsFilter.class_id);
    if (studentsFilter.level) params.set('level', studentsFilter.level);
    if (studentsFilter.academic_year) params.set('academic_year', studentsFilter.academic_year);
    const res = await api(`/api/students?${params}`);
    if (res?.ok) { const j = await res.json(); students = j.students || []; total = j.total || 0; }
    const cRes = await api('/api/classes?per_page=200');
    if (cRes?.ok) { const j = await cRes.json(); classes = j.classes || []; }
  } catch {}

  const activeCount = students.filter(s => (s.status || '').toUpperCase() === 'ACTIVE').length;
  const totalPages = Math.ceil(total / 15) || 1;

  c.innerHTML = `
    <!-- WELCOME -->
    <div class="welcome">
      <h1>Élèves</h1>
      <p>Gérez les élèves inscrits dans votre établissement.</p>
    </div>

    <!-- INDICATORS -->
    <div class="indicator-row">
      <div class="indicator-card hero">
        <div class="indicator-icon"><i class="fas fa-users"></i></div>
        <div class="indicator-info">
          <h4>Total élèves</h4>
          <div class="indicator-val">${total}</div>
          <div class="indicator-sub">Inscrits au total</div>
        </div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon"><i class="fas fa-user-check"></i></div>
        <div class="indicator-info">
          <h4>Actifs</h4>
          <div class="indicator-val">${activeCount}</div>
          <div class="indicator-sub">Élèves en cours</div>
        </div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon" style="color:var(--yiriba-jaune)"><i class="fas fa-user-plus"></i></div>
        <div class="indicator-info">
          <h4>Ce mois</h4>
          <div class="indicator-val">${students.filter(s => {
            if (!s.created_at) return false;
            const d = new Date(s.created_at); const now = new Date();
            return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
          }).length}</div>
          <div class="indicator-sub">Nouvelles inscriptions</div>
        </div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon" style="color:var(--yiriba-rouge)"><i class="fas fa-arrow-right-arrow-left"></i></div>
        <div class="indicator-info">
          <h4>Transférés</h4>
          <div class="indicator-val">          ${students.filter(s => (s.status || '').toUpperCase() === 'TRANSFERRED').length}</div>
          <div class="indicator-sub">Ce trimestre</div>
        </div>
      </div>
    </div>

    <!-- TOOLBAR + FILTERS -->
    <div class="page-toolbar">
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <div class="filter-search-wrap">
          <i class="fas fa-search"></i>
          <input class="filter-search" id="student-search" placeholder="Rechercher un élève..." value="${studentsSearch}">
        </div>
        <select class="filter-select" id="filter-class">
          <option value="">Toutes les classes</option>
          ${classes.map(cl => `<option value="${cl.id}" ${studentsFilter.class_id == cl.id ? 'selected' : ''}>${escapeHtml(cl.name)}</option>`).join('')}
        </select>
        <select class="filter-select" id="filter-status">
          <option value="all" ${studentsFilter.status === 'all' || !studentsFilter.status ? 'selected' : ''}>Tous les statuts</option>
          <option value="active" ${studentsFilter.status === 'active' ? 'selected' : ''}>Actif</option>
          <option value="inactive" ${studentsFilter.status === 'inactive' ? 'selected' : ''}>Inactif</option>
          <option value="graduated" ${studentsFilter.status === 'graduated' ? 'selected' : ''}>Diplômé</option>
          <option value="transferred" ${studentsFilter.status === 'transferred' ? 'selected' : ''}>Transféré</option>
          <option value="withdrawn" ${studentsFilter.status === 'withdrawn' ? 'selected' : ''}>Retiré</option>
        </select>
        <select class="filter-select" id="filter-gender">
          <option value="" ${!studentsFilter.gender ? 'selected' : ''}>Tous</option>
          <option value="M" ${studentsFilter.gender === 'M' ? 'selected' : ''}>Masculin</option>
          <option value="F" ${studentsFilter.gender === 'F' ? 'selected' : ''}>Féminin</option>
        </select>
        <select class="filter-select" id="filter-level">
          <option value="">Tous les niveaux</option>
          ${[...new Set(classes.map(cl => cl.level).filter(Boolean))].map(lv => `<option value="${lv}" ${studentsFilter.level === lv ? 'selected' : ''}>${lv}</option>`).join('')}
        </select>
        <select class="filter-select" id="filter-year">
          <option value="">Toutes les années</option>
          ${[...new Set(classes.map(cl => cl.academic_year).filter(Boolean))].map(y => `<option value="${y}" ${studentsFilter.academic_year === y ? 'selected' : ''}>${y}</option>`).join('')}
        </select>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn-secondary" onclick="exportStudents()" style="padding:10px 16px;border-radius:8px;cursor:pointer"><i class="fas fa-file-export"></i> Exporter</button>
        <button class="btn-add" style="background:var(--yiriba-jaune);color:#333" onclick="showImportModal()"><i class="fas fa-file-import"></i> Importer</button>
        <button class="btn-add" onclick="showAddStudentModal()"><i class="fas fa-plus"></i> Ajouter un élève</button>
      </div>
    </div>

    <!-- TABLE -->
    ${students.length > 0 ? `
    <div class="yiriba-table-wrap">
      <table class="yiriba-table">
        <thead>
          <tr>
            <th>Élève</th>
            <th>Matricule</th>
            <th>Classe</th>
            <th>Naissance</th>
            <th>Parent</th>
            <th>Statut</th>
            <th style="text-align:right">Actions</th>
          </tr>
        </thead>
        <tbody>
          ${students.map(s => {
            const initials = (s.first_name?.[0] || '') + (s.last_name?.[0] || '');
            const st = (s.status || '').toUpperCase();
            const statusMap = { ACTIVE: ['Actif', 'badge-active'], INACTIVE: ['Inactif', 'badge-inactive'], GRADUATED: ['Diplômé', 'badge-info'], TRANSFERRED: ['Transféré', 'badge-warning'], WITHDRAWN: ['Retiré', 'badge-danger'] };
            const [statusLabel, statusClass] = statusMap[st] || ['—', 'badge-inactive'];
            const birthDate = s.birth_date ? new Date(s.birth_date).toLocaleDateString('fr-FR', {day:'2-digit',month:'short',year:'numeric'}) : '—';
            const parents = s.parents || [];
            const parentName = parents.length > 0 ? parents[0].parent_name : '—';
            const clsName = s.current_class || '—';
            const photo = s.photo_url;
            return `<tr style="cursor:pointer" onclick="viewStudent(${s.id})">
              <td><div class="avatar-cell">
                <div class="avatar-sm">${photo ? `<img src="${photo}" alt="">` : initials.toUpperCase()}</div>
                <div class="name-cell">${s.last_name} ${s.first_name}<small>${s.gender === 'F' ? 'Féminin' : 'Masculin'}</small></div>
              </div></td>
              <td><span class="matricule">${s.matricule || '—'}</span></td>
              <td>${clsName}${s.current_year ? `<small style="display:block;font-size:11px;color:var(--texte-secondaire)">${s.current_year}</small>` : ''}</td>
              <td>${birthDate}</td>
              <td>${parentName}</td>
              <td><span class="badge ${statusClass}"><span class="badge-dot"></span>${statusLabel}</span></td>
              <td><div class="table-actions" style="justify-content:flex-end">
                <button title="Voir" onclick="event.stopPropagation();viewStudent(${s.id})"><i class="fas fa-eye"></i></button>
                <button title="Modifier" onclick="event.stopPropagation();editStudent(${s.id})"><i class="fas fa-pen"></i></button>
                ${st === 'ACTIVE' ? `<button title="Suspendre / désactiver" style="color:#b45309" onclick="event.stopPropagation();suspendStudent(${s.id}, '${s.first_name} ${s.last_name}')"><i class="fas fa-user-slash"></i></button>` : (st === 'INACTIVE' ? `<button title="Réactiver" style="color:var(--yiriba-vert)" onclick="event.stopPropagation();reactivateStudent(${s.id}, '${s.first_name} ${s.last_name}')"><i class="fas fa-user-check"></i></button>` : '')}
                <button title="Signaler un incident" style="color:var(--yiriba-rouge)" onclick="event.stopPropagation();showDisciplineModal(${s.id}, '${(s.first_name + ' ' + s.last_name).replace(/'/g, "\\'")}')"><i class="fas fa-exclamation-triangle"></i></button>
                <button title="Supprimer / retirer" class="danger" onclick="event.stopPropagation();deleteStudent(${s.id}, '${s.first_name} ${s.last_name}')"><i class="fas fa-trash"></i></button>
              </div></td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
      <div class="pagination">
        <span>Page ${studentsPage} sur ${totalPages} — ${total} élève${total > 1 ? 's' : ''}</span>
        <div class="pagination-btns">
          <button ${studentsPage <= 1 ? 'disabled' : ''} onclick="studentsPage--;loadStudents()"><i class="fas fa-chevron-left"></i></button>
          ${Array.from({length: Math.min(totalPages, 5)}, (_, i) => i + 1).map(p => `<button class="${p === studentsPage ? 'current' : ''}" onclick="studentsPage=${p};loadStudents()">${p}</button>`).join('')}
          <button ${studentsPage >= totalPages ? 'disabled' : ''} onclick="studentsPage++;loadStudents()"><i class="fas fa-chevron-right"></i></button>
        </div>
      </div>
    </div>`
    : `
    <!-- EMPTY STATE -->
    <div class="card section-card">
      <div class="empty">
        <div class="empty-icon"><i class="fas fa-user-graduate"></i></div>
        <h4>Aucun élève enregistré</h4>
        <p>Commencez par ajouter votre premier élève pour construire votre effectif scolaire.</p>
        <span class="link" onclick="showAddStudentModal()"><i class="fas fa-plus"></i> Ajouter un élève →</span>
      </div>
    </div>`}
  `;

  // Event listeners for filters
  const searchEl = document.getElementById('student-search');
  if (searchEl) {
    let debounce;
    searchEl.addEventListener('input', e => {
      clearTimeout(debounce);
      debounce = setTimeout(() => { studentsSearch = e.target.value; studentsPage = 1; loadStudents(); }, 350);
    });
  }
  ['filter-class', 'filter-status', 'filter-gender', 'filter-level', 'filter-year'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', () => {
      studentsFilter.class_id = document.getElementById('filter-class').value;
      studentsFilter.status = document.getElementById('filter-status').value;
      studentsFilter.gender = document.getElementById('filter-gender').value;
      studentsFilter.level = document.getElementById('filter-level').value;
      studentsFilter.academic_year = document.getElementById('filter-year').value;
      studentsPage = 1; loadStudents();
    });
  });
}

// Export CSV des élèves (respecte les filtres actifs)
function exportStudents() {
  const params = new URLSearchParams();
  if (studentsSearch) params.set('search', studentsSearch);
  if (studentsFilter.status) params.set('status', studentsFilter.status);
  if (studentsFilter.gender) params.set('gender', studentsFilter.gender);
  if (studentsFilter.class_id) params.set('class_id', studentsFilter.class_id);
  if (studentsFilter.level) params.set('level', studentsFilter.level);
  if (studentsFilter.academic_year) params.set('academic_year', studentsFilter.academic_year);
  const url = '/api/students/export' + (params.toString() ? '?' + params.toString() : '');
  const token = state.token || localStorage.getItem('yiriba_token') || '';
  fetch(url, { headers: { 'Authorization': 'Bearer ' + token } })
    .then(r => { if (!r.ok) throw new Error('Erreur export'); return r.blob(); })
    .then(blob => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'eleves_' + new Date().toISOString().slice(0, 10) + '.csv';
      document.body.appendChild(a); a.click(); a.remove();
      showToast('Export CSV téléchargé');
    })
    .catch(() => showToast('Erreur lors de l\'export', 'error'));
}

/* -- Student CRUD Modals ----------------------------------- */

async function showAddStudentModal() {
  const [cRes, pRes] = await Promise.all([api('/api/classes?per_page=200'), api('/api/admin/users?per_page=200')]);
  let classes = [];
  if (cRes?.ok) { const j = await cRes.json(); classes = j.classes || []; }
  let parents = [];
  if (pRes?.ok) { const j = await pRes.json(); parents = (j.users || []).filter(u => (u.role_type || '').toLowerCase() === 'parent'); }
  showModal('Ajouter un élève', `
    <div class="modal-form">
      <div class="form-row">
        <div class="form-group"><label>Prénom *</label><input id="s-first" placeholder="Ex: Ibrahim"></div>
        <div class="form-group"><label>Nom *</label><input id="s-last" placeholder="Ex: Ouédraogo"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Genre</label><select id="s-gender"><option value="M">Masculin</option><option value="F">Féminin</option></select></div>
        <div class="form-group"><label>Date de naissance</label><input id="s-birth" type="date"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Lieu de naissance</label><input id="s-birthplace" placeholder="Ex: Ouagadougou"></div>
        <div class="form-group"><label>Nationalité</label><input id="s-nationality" value="Burkinabè"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Matricule</label><input id="s-matricule" placeholder="Auto : ELV-2026-0001"></div>
        <div class="form-group"><label>Téléphone</label><input id="s-phone" placeholder="Optionnel"></div>
      </div>
      <div class="form-group"><label>Adresse</label><input id="s-address" placeholder="Optionnel"></div>
      <div class="form-group"><label>École précédente</label><input id="s-prev" placeholder="Optionnel"></div>
      <div class="form-group" style="display:flex;align-items:center;gap:8px;margin-top:4px">
        <input type="checkbox" id="s-repeater" style="width:auto">
        <label for="s-repeater" style="margin:0;font-size:13px">Redoublant</label>
      </div>

      <!-- INSCRIPTION -->
      <div style="border-top:1px solid var(--border);margin-top:12px;padding-top:12px">
        <div style="font-weight:700;font-size:13px;color:var(--yiriba-primary);margin-bottom:8px"><i class="fas fa-chalkboard" style="margin-right:6px"></i>Inscription dans une classe</div>
        <div class="form-group">
          <label>Classe</label>
          <select id="s-class">
            <option value="">— Sélectionner une classe —</option>
            ${classes.map(cl => `<option value="${cl.id}">${escapeHtml(cl.name)} (${cl.academic_year || ''}) — ${cl.capacity || 50} places</option>`).join('')}
          </select>
        </div>
      </div>

      <!-- PHOTO -->
      <div style="border-top:1px solid var(--border);margin-top:12px;padding-top:12px">
        <div style="font-weight:700;font-size:13px;color:var(--yiriba-primary);margin-bottom:8px"><i class="fas fa-camera" style="margin-right:6px"></i>Photo de l'élève</div>
        <div class="form-group">
          <input type="file" id="s-photo" accept="image/jpeg,image/png,image/webp" style="font-size:13px">
          <div style="font-size:11px;color:var(--texte-secondaire);margin-top:4px">JPG, PNG ou WebP — max 5 Mo</div>
        </div>
      </div>

      <!-- PARENT -->
      <div style="border-top:1px solid var(--border);margin-top:12px;padding-top:12px">
        <div style="font-weight:700;font-size:13px;color:var(--yiriba-primary);margin-bottom:8px"><i class="fas fa-user-group" style="margin-right:6px"></i>Responsable (optionnel)</div>
        <div class="form-group">
          <label>Choisir un responsable existant (recommandé)</label>
          <select id="s-parent-existing" onchange="toggleParentMode()">
            <option value="">— Aucun / créer un nouveau —</option>
            ${parents.map(p => `<option value="${p.id}">${p.first_name} ${p.last_name}${p.email && p.email.includes('@') ? ' (' + p.email + ')' : ''}</option>`).join('')}
          </select>
        </div>
        <div id="new-parent-fields">
          <div style="font-size:12px;color:var(--texte-secondaire);margin-bottom:8px">Ou créez un nouveau compte parent :</div>
          <div class="form-row">
            <div class="form-group"><label>Prénom du parent</label><input id="s-pfirst" placeholder="Ex: Awa"></div>
            <div class="form-group"><label>Nom du parent</label><input id="s-plast" placeholder="Ex: Ouédraogo"></div>
          </div>
          <div class="form-row">
            <div class="form-group"><label>Téléphone parent</label><input id="s-pphone" placeholder="Ex: 70 12 34 56"></div>
            <div class="form-group"><label>Lien</label><select id="s-prole"><option value="father">Père</option><option value="mother">Mère</option><option value="guardian">Tuteur</option><option value="other">Autre</option></select></div>
          </div>
        </div>
      </div>

      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="submitAddStudent()"><i class="fas fa-plus"></i> Inscrire l'élève</button>
      </div>
    </div>
  `);
}

function toggleParentMode() {
  const sel = document.getElementById('s-parent-existing');
  const isExisting = sel && sel.value;
  const newFields = document.getElementById('new-parent-fields');
  if (newFields) newFields.style.display = isExisting ? 'none' : 'block';
}

async function submitAddStudent() {
  const parentExisting = document.getElementById('s-parent-existing')?.value || '';
  const data = {
    first_name: document.getElementById('s-first').value.trim(),
    last_name: document.getElementById('s-last').value.trim(),
    gender: document.getElementById('s-gender').value,
    birth_date: document.getElementById('s-birth').value || null,
    birth_place: document.getElementById('s-birthplace').value.trim() || null,
    nationality: document.getElementById('s-nationality').value.trim() || 'Burkinabè',
    matricule: document.getElementById('s-matricule').value.trim() || '',
    phone: document.getElementById('s-phone').value.trim() || null,
    address: document.getElementById('s-address').value.trim() || null,
    previous_school: document.getElementById('s-prev').value.trim() || null,
    is_repeater: document.getElementById('s-repeater').checked,
    // Parent (seulement si on crée un NOUVEAU parent)
    parent_first_name: parentExisting ? null : (document.getElementById('s-pfirst')?.value.trim() || null),
    parent_last_name: parentExisting ? null : (document.getElementById('s-plast')?.value.trim() || null),
    parent_phone: parentExisting ? null : (document.getElementById('s-pphone')?.value.trim() || null),
    parent_role: parentExisting ? null : (document.getElementById('s-prole')?.value || null),
  };
  if (!data.first_name || !data.last_name) { showToast('Prénom et nom sont requis', 'error'); return; }
  try {
    const res = await api('/api/students', { method: 'POST', body: JSON.stringify(data) });
    if (!res?.ok) { const j = await res.json(); showToast(parseError(j) || 'Erreur lors de la création', 'error'); return; }
    const student = await res.json();
    // Lier un parent EXISTANT si choisi
    if (parentExisting) {
      const linkRes = await api(`/api/students/${student.id}/parents`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ parent_id: parseInt(parentExisting), role: 'other', is_primary: false }) });
      if (!linkRes?.ok) {
        const linkErr = await linkRes?.json().catch(() => ({}));
        showToast('Élève créé mais association parent échouée: ' + (linkErr.detail || 'erreur'), 'error');
      }
    }

    // Inscription dans la classe si sélectionnée
    const classId = document.getElementById('s-class')?.value;
    if (classId) {
      const enrollRes = await api('/api/enrollments', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ student_id: student.id, class_id: parseInt(classId), is_repeater: data.is_repeater }) });
      if (!enrollRes?.ok) {
        const enrollErr = await enrollRes?.json().catch(()=>({}));
        showToast('Élève créé mais inscription échouée: ' + (enrollErr.detail || 'erreur'), 'error');
      }
    }

    // Upload photo si sélectionnée
    const photoInput = document.getElementById('s-photo');
    if (photoInput?.files?.length > 0) {
      const file = photoInput.files[0];
      if (file.size > 5 * 1024 * 1024) { showToast('Photo trop volumineuse (max 5 Mo)', 'error'); }
      else {
        const fd = new FormData();
        fd.append('file', file);
        await api(`/api/students/${student.id}/photo`, { method: 'POST', body: fd });
      }
    }

    closeModal(); showToast(classId ? 'Élève inscrit avec succès' : 'Élève ajouté (pas encore inscrit)'); loadStudents();
  } catch { showToast('Erreur réseau', 'error'); }
}

/* -- Mass Import ------------------------------------------------ */

let _importFile = null;
let _importMapping = null;
let _importSessionId = null;

function showImportModal() {
  _importFile = null;
  _importMapping = null;
  _importSessionId = null;
  showModal('Importer des élèves', `
    <div style="text-align:center;padding:30px 0">
      <div id="import-dropzone" style="border:2px dashed var(--border);border-radius:12px;padding:40px 20px;cursor:pointer;transition:all 0.2s" onmouseover="this.style.borderColor='var(--yiriba-vert)'" onmouseout="this.style.borderColor='var(--border)'" onclick="document.getElementById('import-file-input').click()" ondragover="event.preventDefault();this.style.borderColor='var(--yiriba-vert)';this.style.background='#f0faf4'" ondragleave="this.style.borderColor='var(--border)';this.style.background=''" ondrop="event.preventDefault();handleImportFileDrop(event)">
        <i class="fas fa-cloud-arrow-up" style="font-size:40px;color:var(--yiriba-vert);margin-bottom:12px;display:block"></i>
        <p style="font-size:16px;font-weight:600;margin-bottom:6px">Glissez votre fichier ici</p>
        <p style="font-size:13px;color:var(--texte-secondaire)">ou cliquez pour sélectionner</p>
        <p style="font-size:12px;color:var(--texte-secondaire);margin-top:12px">Formats acceptés : CSV, XLSX, XLS — Max 10 Mo</p>
      </div>
      <input type="file" id="import-file-input" accept=".csv,.xlsx,.xls" style="display:none" onchange="handleImportFileSelect(this)">
      <div id="import-file-info" style="display:none;margin-top:16px;text-align:left"></div>
      <div id="import-step2" style="display:none"></div>
      <div id="import-step3" style="display:none"></div>
    </div>
  `);
}

function handleImportFileDrop(e) {
  const file = e.dataTransfer.files[0];
  if (file) processImportFile(file);
}

function handleImportFileSelect(input) {
  const file = input.files[0];
  if (file) processImportFile(file);
}

async function processImportFile(file) {
  const allowed = ['.csv', '.xlsx', '.xls'];
  const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
  if (!allowed.includes(ext)) { showToast('Format non supporté', 'error'); return; }
  if (file.size > 10 * 1024 * 1024) { showToast('Fichier trop volumineux (max 10 Mo)', 'error'); return; }

  _importFile = file;
  const info = document.getElementById('import-file-info');
  info.style.display = 'block';
  info.innerHTML = '<div style="display:flex;align-items:center;gap:10px;padding:10px;background:#f0faf4;border-radius:8px"><i class="fas fa-file" style="color:var(--yiriba-vert)"></i><span style="font-weight:600">' + escapeHtml(file.name) + '</span><span style="color:var(--texte-secondaire);font-size:13px">(' + (file.size / 1024).toFixed(1) + ' Ko)</span></div>';

  // Step 1: Detect columns
  showToast('Analyse du fichier...', 'info');
  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await api('/api/students/import/detect', { method: 'POST', body: formData, headers: {} });
    if (!res?.ok) { const e = await res.json().catch(() => ({})); showToast(e.detail || 'Erreur de détection', 'error'); return; }
    const data = await res.json();
    _importMapping = data.mapping;
    showImportStep2(data);
  } catch { showToast('Erreur réseau', 'error'); }
}

function showImportStep2(data) {
  const step2 = document.getElementById('import-step2');
  step2.style.display = 'block';

  const fields = [
    { key: 'first_name', label: 'Prénom', required: true },
    { key: 'last_name', label: 'Nom', required: true },
    { key: 'birth_date', label: 'Date de naissance', required: false },
    { key: 'gender', label: 'Sexe (M/F)', required: false },
    { key: 'class_name', label: 'Classe', required: true },
    { key: 'parent_name', label: 'Nom du parent', required: false },
    { key: 'parent_phone', label: 'Téléphone parent', required: false },
    { key: 'parent_email', label: 'Email parent', required: false },
    { key: 'matricule', label: 'Matricule', required: false },
  ];

  const headers = data.headers || [];
  const mapping = data.mapping || {};

  let html = '<div style="margin-top:20px"><h3 style="font-size:15px;margin-bottom:12px"><i class="fas fa-link" style="color:var(--yiriba-vert);margin-right:6px"></i>Correspondance des colonnes</h3>';
  html += '<p style="font-size:13px;color:var(--texte-secondaire);margin-bottom:16px">' + data.total_rows + ' lignes détectées. Vérifiez le mapping :</p>';

  html += '<div style="display:flex;flex-direction:column;gap:8px">';
  fields.forEach(f => {
    const detected = mapping[f.key];
    const col = detected?.column || '';
    const conf = detected?.confidence || 0;
    const confColor = conf >= 0.85 ? 'var(--yiriba-vert)' : conf >= 0.6 ? 'var(--yiriba-jaune)' : 'var(--yiriba-rouge)';
    const missing = f.required && !col;

    html += '<div style="display:flex;align-items:center;gap:8px;padding:8px 10px;background:' + (missing ? '#fff5f5' : '#f8faf8') + ';border-radius:8px;border:1px solid ' + (missing ? 'var(--yiriba-rouge)' : 'var(--border)') + '">';
    html += '<label style="min-width:140px;font-size:13px;font-weight:600">' + f.label + (f.required ? ' <span style="color:var(--yiriba-rouge)">*</span>' : '') + '</label>';
    html += '<select id="import-map-' + f.key + '" style="flex:1;padding:6px 8px;border:1px solid var(--border);border-radius:6px;font-size:13px" onchange="_importMapping[\'' + f.key + '\'].column = this.value || null">';
    html += '<option value="">-- Aucune colonne --</option>';
    headers.forEach(h => {
      const sel = col === h ? 'selected' : '';
      html += '<option value="' + h + '" ' + sel + '>' + h + '</option>';
    });
    html += '</select>';
    if (col && conf > 0) {
      html += '<span style="font-size:11px;color:' + confColor + ';white-space:nowrap">' + Math.round(conf * 100) + '%</span>';
    }
    html += '</div>';
  });
  html += '</div>';

  // Sample data preview
  if (data.sample_rows && data.sample_rows.length > 0) {
    html += '<details style="margin-top:12px"><summary style="font-size:13px;cursor:pointer;color:var(--texte-secondaire)">Aperçu des données (' + Math.min(5, data.sample_rows.length) + ' lignes)</summary>';
    html += '<div style="overflow-x:auto;margin-top:8px"><table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr style="background:#f0faf4">';
    headers.forEach(h => { html += '<th style="padding:6px 8px;text-align:left;border-bottom:1px solid var(--border)">' + h + '</th>'; });
    html += '</tr></thead><tbody>';
    data.sample_rows.forEach(row => {
      html += '<tr>';
      headers.forEach(h => { html += '<td style="padding:4px 8px;border-bottom:1px solid var(--border)">' + (row[h] || '') + '</td>'; });
      html += '</tr>';
    });
    html += '</tbody></table></div></details>';
  }

  html += '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:16px">';
  html += '<button class="btn-secondary" onclick="showImportModal()"><i class="fas fa-arrow-left"></i> Retour</button>';
  html += '<button class="btn-add" onclick="submitImportValidate()"><i class="fas fa-check"></i> Valider le mapping</button>';
  html += '</div></div>';

  step2.innerHTML = html;
}

async function submitImportValidate() {
  if (!_importFile || !_importMapping) { showToast('Données manquantes', 'error'); return; }

  // Build mapping dict: field -> column name
  const mappingDict = {};
  for (const [key, val] of Object.entries(_importMapping)) {
    mappingDict[key] = val.column || null;
  }

  showToast('Validation en cours...', 'info');
  const formData = new FormData();
  formData.append('file', _importFile);
  formData.append('mapping', JSON.stringify(mappingDict));

  try {
    const res = await api('/api/students/import/validate', { method: 'POST', body: formData, headers: {} });
    if (!res?.ok) { const e = await res.json().catch(() => ({})); showToast(e.detail || 'Erreur de validation', 'error'); return; }
    const data = await res.json();
    _importSessionId = data.session_id;
    showImportStep3(data);
  } catch { showToast('Erreur réseau', 'error'); }
}

function showImportStep3(data) {
  const step3 = document.getElementById('import-step3');
  step3.style.display = 'block';
  document.getElementById('import-step2').style.display = 'none';

  let html = '<div style="margin-top:20px">';

  // Summary cards
  html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px">';
  html += '<div style="padding:16px;background:#f0faf4;border-radius:8px;text-align:center"><div style="font-size:24px;font-weight:800;color:var(--yiriba-vert)">' + data.valid_count + '</div><div style="font-size:12px;color:var(--texte-secondaire)">À importer</div></div>';
  html += '<div style="padding:16px;background:#fff5f0;border-radius:8px;text-align:center"><div style="font-size:24px;font-weight:800;color:var(--yiriba-rouge)">' + data.error_count + '</div><div style="font-size:12px;color:var(--texte-secondaire)">Erreurs</div></div>';
  html += '<div style="padding:16px;background:#fffbe6;border-radius:8px;text-align:center"><div style="font-size:24px;font-weight:800;color:var(--yiriba-jaune)">' + data.duplicates_skipped + '</div><div style="font-size:12px;color:var(--texte-secondaire)">Doublons</div></div>';
  html += '</div>';

  // Errors list
  if (data.errors && data.errors.length > 0) {
    html += '<details style="margin-bottom:16px"><summary style="font-size:13px;cursor:pointer;color:var(--yiriba-rouge);font-weight:600">Voir les erreurs (' + data.errors.length + ')</summary>';
    html += '<div style="max-height:200px;overflow-y:auto;margin-top:8px">';
    data.errors.forEach(e => {
      html += '<div style="padding:6px 10px;border-left:3px solid var(--yiriba-rouge);background:#fff5f5;margin-bottom:4px;border-radius:0 4px 4px 0;font-size:12px">Ligne ' + e.row + ' : ' + e.message + '</div>';
    });
    html += '</div></details>';
  }

  // Preview table
  if (data.preview && data.preview.length > 0) {
    html += '<h4 style="font-size:13px;margin-bottom:8px">Aperçu des élèves à importer</h4>';
    html += '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr style="background:var(--yiriba-vert);color:white">';
    html += '<th style="padding:6px 8px;text-align:left">Nom</th><th>Prénom</th><th>Classe</th><th>Matricule</th><th>Parent</th>';
    html += '</tr></thead><tbody>';
    data.preview.forEach(r => {
      html += '<tr style="border-bottom:1px solid var(--border)">';
      html += '<td style="padding:6px 8px">' + r.last_name + '</td><td>' + r.first_name + '</td><td>' + (r.class_name || '—') + '</td><td>' + r.matricule + '</td><td>' + (r.parent_name || '—') + '</td>';
      html += '</tr>';
    });
    html += '</tbody></table></div>';
  }

  // Option: create student accounts
  html += '<div style="margin-top:14px;padding:12px 14px;background:#f0faf4;border:1px solid var(--border);border-radius:8px;display:flex;align-items:center;gap:10px">';
  html += '<input type="checkbox" id="import-create-accounts" style="width:auto" ' + (data.valid_count > 0 ? '' : 'disabled') + '>';
  html += '<label for="import-create-accounts" style="margin:0;font-size:13px;cursor:pointer"><strong>Créer automatiquement les comptes élèves</strong><br><span style="font-size:12px;color:var(--texte-secondaire)">Identifiant YRB-XXXXXX + mot de passe temporaire pour chaque élève importé (modifiable ensuite dans la fiche élève).</span></label>';
  html += '</div>';

  // Action buttons
  html += '<div id="import-actions" style="display:flex;justify-content:flex-end;gap:8px;margin-top:16px">';
  html += '<button class="btn-secondary" onclick="showImportModal()"><i class="fas fa-times"></i> Annuler</button>';
  if (data.valid_count > 0) {
    html += '<button class="btn-add" onclick="submitImportConfirm()"><i class="fas fa-file-import"></i> Importer ' + data.valid_count + ' élèves</button>';
  }
  html += '</div>';

  html += '</div>';
  step3.innerHTML = html;
}

async function submitImportConfirm() {
  if (!_importSessionId) { showToast('Session introuvable', 'error'); return; }

  const actionsDiv = document.getElementById('import-actions');
  if (actionsDiv) actionsDiv.innerHTML = '<div style="display:flex;align-items:center;gap:8px;color:var(--yiriba-vert)"><i class="fas fa-spinner fa-spin"></i> Import en cours...</div>';

  try {
    const createAccounts = document.getElementById('import-create-accounts')?.checked || false;
    const res = await api('/api/students/import/confirm?session_id=' + _importSessionId + '&create_accounts=' + createAccounts, { method: 'POST' });
    if (!res?.ok) { const e = await res.json().catch(() => ({})); showToast(e.detail || 'Erreur lors de l\'import', 'error'); if (actionsDiv) actionsDiv.innerHTML = '<button class="btn-add" onclick="submitImportConfirm()"><i class="fas fa-file-import"></i> Réessayer</button>'; return; }
    const data = await res.json();
    closeModal();
    showToast(data.imported + ' élèves importés avec succès !', 'success');
    loadStudents();
  } catch { showToast('Erreur réseau', 'error'); }
}

async function viewStudent(id) {
  try {
    const res = await api(`/api/students/${id}`);
    if (!res?.ok) { showToast('Élève introuvable', 'error'); return; }
    const s = await res.json();
    // Charger les parents disponibles de l'école (pour associer un parent existant)
    let schoolParents = [];
    try {
      const pRes = await api('/api/admin/users?per_page=200');
      if (pRes?.ok) { const pj = await pRes.json(); schoolParents = (pj.users || []).filter(u => (u.role_type || '').toLowerCase() === 'parent'); }
    } catch {}
    const linkedParentIds = new Set((s.parents || []).map(p => p.parent_id));
    const availableParents = schoolParents.filter(p => !linkedParentIds.has(p.id));
    const roleLabel = { father: 'Père', mother: 'Mère', guardian: 'Tuteur', other: 'Autre' };
    const parentLinksHTML = (s.parents || []).map(p => `
      <div style="display:flex;align-items:center;gap:8px;padding:6px 10px;background:var(--surface-soft);border-radius:8px;font-size:13px">
        <i class="fas fa-user" style="color:var(--yiriba-vert)"></i>
        <span style="font-weight:600">${p.parent_name}</span>
        <span class="badge badge-info">${roleLabel[p.role] || p.role}</span>
        <button title="Retirer ce responsable" style="margin-left:auto;background:none;border:none;cursor:pointer;color:var(--yiriba-rouge)" onclick="removeParentFromStudent(${id}, ${p.parent_id}, '${p.parent_name.replace(/'/g, "\\'")}')"><i class="fas fa-user-minus"></i></button>
      </div>`).join('') || '<div style="font-size:13px;color:var(--texte-secondaire)">Aucun responsable lié pour le moment.</div>';
    const statusMap = { ACTIVE: ['Actif', 'badge-active'], INACTIVE: ['Inactif', 'badge-inactive'], GRADUATED: ['Diplômé', 'badge-info'], TRANSFERRED: ['Transféré', 'badge-warning'], WITHDRAWN: ['Retiré', 'badge-danger'] };
    const st = (s.status || '').toUpperCase();
    const [sl, sc] = statusMap[st] || ['—', 'badge-inactive'];

    // Fetch discipline history
    let disciplineHTML = '';
    try {
      const period = 'T1'; // default to current period
      const year = '2025-2026';
      const dRes = await api(`/api/discipline/student/${id}/summary?period=${period}&academic_year=${year}`);
      if (dRes?.ok) {
        const d = await dRes.json();
        const records = (d.records || []).filter(r => r.status === 'active');
        if (records.length > 0) {
          disciplineHTML = `
            <div style="border-top:1px solid var(--border);padding-top:12px">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                <strong style="font-size:12px;text-transform:uppercase;letter-spacing:0.05em;color:var(--yiriba-rouge)"><i class="fas fa-exclamation-triangle" style="margin-right:4px"></i>Incidents disciplinaires — ${period}</strong>
                <span style="color:var(--yiriba-rouge);font-weight:700;font-size:14px">-${d.total_deductions} pts</span>
              </div>
              <div style="display:flex;flex-direction:column;gap:6px">
                ${records.map(r => `
                  <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 8px;background:${r.source === 'auto' ? '#fff3e0' : '#fce4ec'};border-radius:6px;font-size:12px">
                    <div>
                      <span style="font-weight:600">${r.incident_type.replace(/_/g, ' ')}</span>
                      <span style="color:var(--texte-secondaire);margin-left:6px">${r.date ? new Date(r.date).toLocaleDateString('fr-FR') : ''}</span>
                      ${r.note ? `<span style="color:var(--texte-secondaire);margin-left:6px">· ${r.note}</span>` : ''}
                    </div>
                    <span style="color:var(--yiriba-rouge);font-weight:700">-${r.points_deducted}</span>
                  </div>
                `).join('')}
              </div>
            </div>`;
        } else {
          disciplineHTML = `
            <div style="border-top:1px solid var(--border);padding-top:12px">
              <div style="font-size:12px;text-transform:uppercase;letter-spacing:0.05em;color:var(--yiriba-vert);font-weight:600;margin-bottom:4px"><i class="fas fa-check-circle" style="margin-right:4px"></i>Aucun incident disciplinaire — ${period}</div>
              <div style="font-size:12px;color:var(--texte-secondaire)">Aucun point déduit cette période.</div>
            </div>`;
        }
      }
    } catch {}

    showModal(`${s.first_name} ${s.last_name}`, `
      <div style="display:flex;flex-direction:column;gap:14px;font-size:14px">
        <div style="display:flex;align-items:center;gap:14px;margin-bottom:8px">
          <div class="avatar-sm" style="width:48px;height:48px;font-size:16px">${s.photo_url ? `<img src="${s.photo_url}" alt="">` : (s.first_name[0] + s.last_name[0]).toUpperCase()}</div>
          <div><div style="font-weight:700;font-size:16px">${s.first_name} ${s.last_name}</div><div style="font-size:13px;color:var(--texte-secondaire)">${s.gender === 'F' ? 'Féminin' : 'Masculin'} · Matricule: ${s.matricule || '—'}</div></div>
          <span class="badge ${sc}" style="margin-left:auto"><span class="badge-dot"></span>${sl}</span>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div><strong style="font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--texte-secondaire)">Classe</strong><div>${s.current_class || '—'}</div></div>
          <div><strong style="font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--texte-secondaire)">Naissance</strong><div>${s.birth_date ? new Date(s.birth_date).toLocaleDateString('fr-FR') : '—'} ${s.birth_place ? '· ' + s.birth_place : ''}</div></div>
          <div><strong style="font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--texte-secondaire)">Nationalité</strong><div>${s.nationality || '—'}</div></div>
          <div><strong style="font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--texte-secondaire)">Téléphone</strong><div>${s.phone || '—'}</div></div>
          <div><strong style="font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--texte-secondaire)">Adresse</strong><div>${s.address || '—'}</div></div>
          <div><strong style="font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--texte-secondaire)">École précédente</strong><div>${s.previous_school || '—'}</div></div>
          <div><strong style="font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:var(--texte-secondaire)">Redoublant</strong><div>${s.is_repeater ? 'Oui' : 'Non'}</div></div>
        </div>
        <div style="border-top:1px solid var(--border);padding-top:12px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <strong style="font-size:12px;text-transform:uppercase;letter-spacing:0.05em;color:var(--yiriba-vert)"><i class="fas fa-user-group" style="margin-right:4px"></i>Responsables (parents / tuteurs)</strong>
          </div>
          <div style="display:flex;flex-direction:column;gap:6px;margin-bottom:10px">${parentLinksHTML}</div>
          ${availableParents.length > 0 ? `<div style="display:flex;gap:8px;align-items:center">
            <select id="link-parent-select" style="flex:1;padding:8px;border:1px solid var(--border);border-radius:8px;font-size:13px">
              <option value="">— Associer un parent existant —</option>
              ${availableParents.map(p => `<option value="${p.id}">${p.first_name} ${p.last_name}${p.email && p.email.includes('@') ? ' · ' + p.email : ''}</option>`).join('')}
            </select>
            <button class="btn-add" style="white-space:nowrap" onclick="linkExistingParentToStudent(${id})"><i class="fas fa-link"></i> Associer</button>
          </div>` : '<div style="font-size:12px;color:var(--texte-secondaire)">Tous les parents de l\'école sont déjà associés (ou aucun parent enregistré).</div>'}
        </div>
        <div style="border-top:1px solid var(--border);padding-top:12px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <strong style="font-size:12px;text-transform:uppercase;letter-spacing:0.05em;color:var(--yiriba-vert)"><i class="fas fa-key" style="margin-right:4px"></i>Accès élève (portail)</strong>
            <span class="badge ${s.account_exists ? 'badge-active' : 'badge-inactive'}"><span class="badge-dot"></span>${s.account_exists ? 'Compte actif' : 'Aucun compte'}</span>
          </div>
          ${s.account_exists
            ? `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;padding:8px 10px;background:var(--surface-soft);border-radius:8px;font-size:13px"><span style="color:var(--texte-secondaire)">Identifiant :</span><span style="font-weight:700;font-family:monospace">${s.account_username}</span></div>
               <div style="font-size:12px;color:var(--texte-secondaire);margin-bottom:8px">Le mot de passe temporaire est transmis une seule fois. Réinitialisez pour en générer un nouveau.</div>
               <button class="btn-secondary" onclick="createOrResetStudentAccess(${s.id}, false)"><i class="fas fa-rotate-right"></i> Réinitialiser le mot de passe</button>`
            : `<div style="font-size:12px;color:var(--texte-secondaire);margin-bottom:8px">Créez le compte de connexion de l'élève : identifiant YIRIBA (YRB-XXXXXX) généré automatiquement + mot de passe temporaire.</div>
               <button class="btn-add" onclick="createOrResetStudentAccess(${s.id}, true)"><i class="fas fa-user-plus"></i> Créer l'accès élève</button>`}
        </div>
        <div style="border-top:1px solid var(--border);padding-top:12px">
          <strong style="font-size:12px;text-transform:uppercase;letter-spacing:0.05em;color:var(--yiriba-vert)"><i class="fas fa-clock-rotate-left" style="margin-right:4px"></i>Historique scolaire</strong>
          <div id="student-history-${id}" style="margin-top:8px;font-size:13px">Chargement…</div>
        </div>
        ${disciplineHTML}
        ${st === 'ACTIVE' ? `<div style="border-top:1px solid var(--border);padding-top:12px;display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn-secondary" onclick="closeModal();showTransferModal(${s.id})"><i class="fas fa-arrow-right-arrow-left"></i> Transférer</button>
          <button style="background:#fce4ec;color:var(--yiriba-rouge);border:1px solid var(--yiriba-rouge);border-radius:8px;padding:8px 14px;cursor:pointer;font-size:13px;font-weight:600" onclick="closeModal();showDisciplineModal(${s.id}, '${s.first_name} ${s.last_name}')"><i class="fas fa-exclamation-triangle" style="margin-right:4px"></i> Signaler un incident</button>
        </div>` : ''}
      </div>
    `);
    loadStudentHistory(id);
  } catch { showToast('Erreur lors du chargement', 'error'); }
}

async function loadStudentHistory(id) {
  try {
    const r = await api(`/api/students/${id}/history`);
    if (!r?.ok) return;
    const d = await r.json();
    const el = document.getElementById('student-history-' + id);
    if (!el) return;
    const enr = d.enrollments || [];
    if (enr.length === 0) { el.innerHTML = '<div style="color:var(--texte-secondaire)">Aucun parcours enregistré (élève sans inscription passée ou actuelle).</div>'; return; }
    el.innerHTML = enr.map(e => `
      <div style="display:flex;align-items:center;gap:8px;padding:6px 10px;background:var(--surface-soft);border-radius:8px;margin-bottom:6px;font-size:13px">
        <i class="fas fa-chalkboard" style="color:var(--yiriba-vert)"></i>
        <span style="font-weight:600">${e.class_name}</span>
        <span style="color:var(--texte-secondaire)">· ${e.academic_year || '—'}</span>
        ${e.is_repeater ? '<span class="badge badge-warning">Redoublant</span>' : ''}
        <span style="margin-left:auto;font-size:12px;color:var(--texte-secondaire)">${e.enrolled_at ? new Date(e.enrolled_at).toLocaleDateString('fr-FR') : ''}</span>
        <span class="badge ${e.status === 'active' ? 'badge-active' : 'badge-inactive'}">${e.status === 'active' ? 'Actuel' : ({passed:'Passé', repeated:'Redoublé', to_review:'À revoir', not_reenrolled:'Non réinscrit', withdrawn:'Sorti', transferred:'Transféré'}[e.status] || e.status)}</span>
      </div>`).join('');
  } catch {}
}

async function linkExistingParentToStudent(studentId) {
  const sel = document.getElementById('link-parent-select');
  const parentId = sel?.value;
  if (!parentId) { showToast('Sélectionnez un parent à associer', 'error'); return; }
  try {
    const res = await api(`/api/students/${studentId}/parents`, { method: 'POST', body: JSON.stringify({ parent_id: parseInt(parentId), role: 'other', is_primary: false }) });
    if (res?.ok) { showToast('Parent associé à l\'élève'); viewStudent(studentId); }
    else { const d = await res.json().catch(() => ({})); showToast(d.detail || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

async function removeParentFromStudent(studentId, parentUserId, parentName) {
  if (!confirm(`Retirer ${parentName} de cet élève ?`)) return;
  try {
    const res = await api(`/api/students/${studentId}/parents/${parentUserId}`, { method: 'DELETE' });
    if (res?.ok || res?.status === 204) { showToast('Responsable retiré'); viewStudent(studentId); }
    else { const d = await res.json().catch(() => ({})); showToast(d.detail || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

async function showTransferModal(studentId) {
  const cRes = await api('/api/classes?per_page=200');
  const classes = cRes?.ok ? (await cRes.json()).classes || [] : [];
  showModal('Transférer l\'élève', `
    <div class="modal-form">
      <div class="form-group"><label>Nouvelle classe</label><select id="tr-class">
        ${classes.map(cl => `<option value="${cl.id}">${escapeHtml(cl.name)}</option>`).join('')}
      </select></div>
      <div class="form-group"><label>Raison (optionnel)</label><input id="tr-reason" placeholder="Ex: Familiale"></div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="submitTransfer(${studentId})"><i class="fas fa-arrow-right"></i> Transférer</button>
      </div>
    </div>
  `);
}

async function submitTransfer(studentId) {
  const data = {
    new_class_id: parseInt(document.getElementById('tr-class').value),
    reason: document.getElementById('tr-reason').value.trim() || null,
  };
  try {
    const res = await api(`/api/students/${studentId}/transfer`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
    if (res?.ok) { closeModal(); showToast('Élève transféré'); loadStudents(); }
    else { const d = await res.json().catch(()=>({})); showToast(d.detail || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

/* -- Discipline Modal ----------------------------------- */

async function showDisciplineModal(studentId, studentName) {
  // Fetch active rules for this school
  let rules = [];
  try {
    const rRes = await api('/api/discipline/rules');
    if (rRes?.ok) rules = (await rRes.json()).rules || [];
  } catch {}
  const activeRules = rules.filter(r => r.is_active);
  const today = new Date().toISOString().split('T')[0];

  showModal('Signaler un incident — ' + studentName, `
    <div class="modal-form">
      <div class="form-group">
        <label>Type d'incident *</label>
        <select id="disc-incident-type">
          <option value="">Choisir un type</option>
          ${activeRules.map(r => `<option value="${r.incident_type}">${r.incident_type.replace(/_/g, ' ')} (-${r.points_deducted} pts)</option>`).join('')}
        </select>
        <div id="disc-points-preview" style="font-size:12px;color:var(--yiriba-rouge);margin-top:4px;font-weight:600"></div>
      </div>
      <div class="form-group">
        <label>Date</label>
        <input id="disc-date" type="date" value="${today}">
      </div>
      <div class="form-group">
        <label>Note (optionnelle)</label>
        <textarea id="disc-note" rows="2" placeholder="Détails de l'incident..." style="width:100%;padding:8px;border:1px solid var(--border);border-radius:8px;font-size:13px;resize:vertical"></textarea>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" style="background:var(--yiriba-rouge)" onclick="submitDisciplineRecord(${studentId})"><i class="fas fa-exclamation-triangle"></i> Signaler</button>
      </div>
    </div>
  `);

  // Show points preview on type change
  document.getElementById('disc-incident-type').addEventListener('change', function() {
    const pts = activeRules.find(r => r.incident_type === this.value);
    document.getElementById('disc-points-preview').textContent = pts ? `→ ${pts.points_deducted} point(s) déduit(s)` : '';
  });
}

async function submitDisciplineRecord(studentId) {
  const incidentType = document.getElementById('disc-incident-type').value;
  const date = document.getElementById('disc-date').value;
  const note = document.getElementById('disc-note').value.trim() || null;
  if (!incidentType) { showToast('Choisissez un type d\'incident', 'error'); return; }
  if (!date) { showToast('Choisissez une date', 'error'); return; }
  try {
    const r = await api('/api/discipline/records', {
      method: 'POST',
      body: JSON.stringify({
        student_id: studentId,
        incident_type: incidentType,
        date: date,
        period: 'T1',
        academic_year: '2025-2026',
        note: note,
      })
    });
    if (r?.ok) {
      const j = await r.json();
      showToast(`Incident signalé — ${j.message || j.points_deducted + ' point(s) déduit(s)'}`, 'success');
      closeModal();
    } else {
      const e = await r.json().catch(() => ({}));
      showToast(e.detail || 'Erreur lors de la signalisation', 'error');
    }
  } catch (err) { showToast('Erreur: ' + err.message, 'error'); }
}

/* -- Accès élève (création / réinitialisation) ---------- */

async function createOrResetStudentAccess(studentId, isCreate) {
  const label = isCreate ? 'Créer l\'accès' : 'Réinitialiser le mot de passe';
  try {
    const res = await api(`/api/students/${studentId}/access`, { method: 'POST' });
    if (!res?.ok) {
      const e = await res.json().catch(() => ({}));
      showToast(e.detail || 'Erreur', 'error');
      return;
    }
    const data = await res.json();
    // Afficher l'identifiant + le mot de passe temporaire (une seule fois)
    showModal(label + ' — élève', `
      <div style="padding:8px 0">
        <div style="padding:14px;background:#f0faf4;border-radius:10px;margin-bottom:14px;border-left:4px solid var(--yiriba-vert)">
          <div style="font-size:12px;color:var(--texte-secondaire);margin-bottom:2px">Identifiant de connexion</div>
          <div style="font-family:monospace;font-size:18px;font-weight:700;color:var(--yiriba-vert)">${data.username}</div>
        </div>
        <div style="padding:14px;background:#fffbe6;border-radius:10px;border-left:4px solid var(--yiriba-jaune)">
          <div style="font-size:12px;color:var(--texte-secondaire);margin-bottom:2px">Mot de passe temporaire (à transmettre en sécurité)</div>
          <div style="font-family:monospace;font-size:18px;font-weight:700;color:#8a6d00">${data.temp_password}</div>
        </div>
        <div style="font-size:12px;color:var(--texte-secondaire);margin-top:14px"><i class="fas fa-circle-info"></i> L'élève devra changer ce mot de passe lors de sa première connexion. Ces informations ne seront plus affichées.</div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
          <button class="btn-secondary" onclick="navigator.clipboard.writeText('${data.username} / ${data.temp_password}');showToast('Copié !')">Copier</button>
          <button class="btn-add" onclick="closeModal()">OK</button>
        </div>
      </div>
    `);
    showToast(data.message || (isCreate ? 'Accès créé' : 'Mot de passe réinitialisé'), 'success');
  } catch { showToast('Erreur réseau', 'error'); }
}

async function editStudent(id) {
  try {
    const [sRes, cRes] = await Promise.all([api(`/api/students/${id}`), api('/api/classes?per_page=200')]);
    if (!sRes?.ok) { showToast('Élève introuvable', 'error'); return; }
    const s = await sRes.json();
    let classes = [];
    if (cRes?.ok) { const j = await cRes.json(); classes = j.classes || []; }
    showModal('Modifier — ' + s.first_name + ' ' + s.last_name, `
      <div class="modal-form">
        <!-- PHOTO -->
        <div class="form-group">
          <label>Photo de l'élève</label>
          <div style="display:flex;align-items:center;gap:14px">
            <div id="e-photo-preview" style="width:64px;height:64px;font-size:22px;border-radius:50%;overflow:hidden;background:var(--surface-soft,#f0ede4);display:grid;place-items:center;flex-shrink:0;font-weight:700;color:var(--yiriba-vert-profond,#145c3f)">
              ${s.photo_url ? `<img src="${s.photo_url}?t=${Date.now()}" alt="" style="width:100%;height:100%;object-fit:cover">` : (s.first_name?.[0] || '?').toUpperCase()}
            </div>
            <div style="flex:1">
              <input type="file" id="e-photo" accept="image/jpeg,image/png,image/webp" onchange="_previewEditPhoto(this)" style="font-size:13px">
              <div style="font-size:11px;color:var(--texte-secondaire);margin-top:4px">JPG, PNG ou WebP — max 5 Mo</div>
            </div>
          </div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>Prénom</label><input id="e-first" value="${s.first_name || ''}"></div>
          <div class="form-group"><label>Nom</label><input id="e-last" value="${s.last_name || ''}"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>Genre</label><select id="e-gender"><option value="M" ${s.gender==='M'?'selected':''}>Masculin</option><option value="F" ${s.gender==='F'?'selected':''}>Féminin</option></select></div>
          <div class="form-group"><label>Date de naissance</label><input id="e-birth" type="date" value="${s.birth_date ? s.birth_date.split('T')[0] : ''}"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>Lieu de naissance</label><input id="e-birthplace" value="${s.birth_place || ''}"></div>
          <div class="form-group"><label>Nationalité</label><input id="e-nationality" value="${s.nationality || ''}"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>Matricule</label><input id="e-matricule" value="${s.matricule || ''}"></div>
          <div class="form-group"><label>Téléphone</label><input id="e-phone" value="${s.phone || ''}"></div>
        </div>
        <div class="form-group"><label>Adresse</label><input id="e-address" value="${s.address || ''}"></div>
        <div class="form-group"><label>École précédente</label><input id="e-prev" value="${s.previous_school || ''}"></div>
        <div class="form-group" style="display:flex;align-items:center;gap:8px;margin-top:4px">
          <input type="checkbox" id="e-repeater" style="width:auto" ${s.is_repeater ? 'checked' : ''}>
          <label for="e-repeater" style="margin:0;font-size:13px">Redoublant</label>
        </div>
        <div class="form-group">
          <label>Statut</label>
          <select id="e-status">
            <option value="ACTIVE" ${s.status==='ACTIVE'?'selected':''}>Actif</option>
            <option value="INACTIVE" ${s.status==='INACTIVE'?'selected':''}>Inactif</option>
            <option value="GRADUATED" ${s.status==='GRADUATED'?'selected':''}>Diplômé</option>
            <option value="TRANSFERRED" ${s.status==='TRANSFERRED'?'selected':''}>Transféré</option>
            <option value="WITHDRAWN" ${s.status==='WITHDRAWN'?'selected':''}>Retiré</option>
          </select>
        </div>
        <div class="modal-footer">
          <button class="btn-secondary" onclick="closeModal()">Annuler</button>
          <button class="btn-add" onclick="submitEditStudent(${id})"><i class="fas fa-check"></i> Enregistrer</button>
        </div>
      </div>
    `);
  } catch { showToast('Erreur lors du chargement', 'error'); }
}

function _previewEditPhoto(input) {
  if (!input.files || !input.files[0]) return;
  const file = input.files[0];
  if (file.size > 5 * 1024 * 1024) { showToast('Photo trop volumineuse (max 5 Mo)', 'error'); input.value = ''; return; }
  const reader = new FileReader();
  reader.onload = (e) => {
    const prev = document.getElementById('e-photo-preview');
    if (prev) prev.innerHTML = `<img src="${e.target.result}" alt="" style="width:100%;height:100%;object-fit:cover">`;
  };
  reader.readAsDataURL(file);
}

async function submitEditStudent(id) {
  const data = {
    first_name: document.getElementById('e-first').value.trim(),
    last_name: document.getElementById('e-last').value.trim(),
    gender: document.getElementById('e-gender').value,
    birth_date: document.getElementById('e-birth').value || null,
    birth_place: document.getElementById('e-birthplace').value.trim() || null,
    nationality: document.getElementById('e-nationality').value.trim() || null,
    matricule: document.getElementById('e-matricule').value.trim() || '',
    phone: document.getElementById('e-phone').value.trim() || null,
    address: document.getElementById('e-address').value.trim() || null,
    previous_school: document.getElementById('e-prev').value.trim() || null,
    is_repeater: document.getElementById('e-repeater').checked,
  };
  if (!data.first_name || !data.last_name) { showToast('Prénom et nom sont requis', 'error'); return; }
  try {
    const res = await api(`/api/students/${id}`, { method: 'PUT', body: JSON.stringify(data) });
    if (res?.ok) {
      // Upload de la photo si une nouvelle a été choisie
      const photoInput = document.getElementById('e-photo');
      if (photoInput?.files?.length > 0) {
        const file = photoInput.files[0];
        if (file.size > 5 * 1024 * 1024) { showToast('Photo trop volumineuse (max 5 Mo)', 'error'); }
        else {
          const fd = new FormData();
          fd.append('file', file);
          const phRes = await api(`/api/students/${id}/photo`, { method: 'POST', body: fd });
          if (!phRes?.ok) { const j = await phRes?.json().catch(() => ({})); showToast('Profil enregistré mais photo refusée : ' + (j.detail || 'erreur'), 'error'); }
        }
      }
      closeModal(); showToast('Élève modifié avec succès'); loadStudents();
    }
    else { const j = await res.json(); showToast(parseError(j) || 'Erreur lors de la modification', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

async function deleteStudent(id, name) {
  if (!confirm(`Voulez-vous vraiment retirer ${name} ?\nLe statut sera changé en \"Retiré\".`)) return;
  try {
    const res = await api(`/api/students/${id}`, { method: 'DELETE' });
    if (res?.ok || res?.status === 204) { showToast(name + ' a été retiré'); loadStudents(); }
    else { showToast('Erreur lors de la suppression', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

async function suspendStudent(id, name) {
  if (!confirm(`Suspendre / désactiver ${name} ?\nIl n'apparaîtra plus dans les listes actives et ne pourra plus être noté.`)) return;
  try {
    const res = await api(`/api/students/${id}/status`, { method: 'PUT', body: JSON.stringify({ status: 'inactive', reason: 'Désactivé par l\'administrateur' }) });
    if (res?.ok) { showToast(name + ' a été désactivé'); loadStudents(); }
    else { const d = await res.json().catch(() => ({})); showToast(d.detail || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

async function reactivateStudent(id, name) {
  if (!confirm(`Réactiver ${name} ?`)) return;
  try {
    const res = await api(`/api/students/${id}/status`, { method: 'PUT', body: JSON.stringify({ status: 'active', reason: 'Réactivé par l\'administrateur' }) });
    if (res?.ok) { showToast(name + ' a été réactivé'); loadStudents(); }
    else { const d = await res.json().catch(() => ({})); showToast(d.detail || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

/* ==============================================================
   MODULE CLASSES — Grille Yiriba
   ============================================================== */
async function loadClasses() {
  const c = document.getElementById('main-content');
  let classes = [], totalStudents = 0, teachers = 0;
  try {
    const [clRes, sRes, tRes] = await Promise.all([
      api('/api/classes?per_page=200'),
      api('/api/students?per_page=1'),
      api('/api/admin/users?per_page=200'),
    ]);
    if (clRes?.ok) { const j = await clRes.json(); classes = j.classes || []; }
    if (sRes?.ok) { totalStudents = (await sRes.json()).total || 0; }
    if (tRes?.ok) { teachers = (await tRes.json()).total || 0; }
  } catch {}

  c.innerHTML = `
    <div class="welcome"><h1>Classes</h1><p>Organisez les classes et les matières de votre établissement.</p></div>

    <div class="indicator-row">
      <div class="indicator-card hero">
        <div class="indicator-icon"><i class="fas fa-chalkboard"></i></div>
        <div class="indicator-info"><h4>Total classes</h4><div class="indicator-val">${classes.length}</div><div class="indicator-sub">Classes actives</div></div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon"><i class="fas fa-users"></i></div>
        <div class="indicator-info"><h4>Élèves</h4><div class="indicator-val">${totalStudents}</div><div class="indicator-sub">Inscrits</div></div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon" style="color:var(--yiriba-jaune)"><i class="fas fa-person-chalkboard"></i></div>
        <div class="indicator-info"><h4>Enseignants</h4><div class="indicator-val">${teachers}</div><div class="indicator-sub">Assignés</div></div>
      </div>
    </div>

    <div class="page-toolbar">
      <div></div>
      <button class="btn-add" onclick="showAddClassModal()"><i class="fas fa-plus"></i> Nouvelle classe</button>
    </div>

    ${classes.length > 0 ? `
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px">
      ${classes.map(cl => `
        <article class="card section-card" style="cursor:default">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:14px">
            <div class="stat-icon"><i class="fas fa-chalkboard"></i></div>
            <div class="table-actions">
              <button title="Modifier" onclick="editClass(${cl.id})"><i class="fas fa-pen"></i></button>
              <button title="Supprimer" class="danger" onclick="deleteClass(${cl.id},'${escapeHtml(cl.name)}')"><i class="fas fa-trash"></i></button>
            </div>
          </div>
          <h3 style="font-family:'Sora',sans-serif;font-size:17px;font-weight:650;margin-bottom:4px">${escapeHtml(cl.name)}</h3>
          <div style="font-size:13px;color:var(--texte-secondaire);margin-bottom:12px">${cl.level || 'Niveau non défini'} · Année ${cl.academic_year}</div>
          <div style="display:flex;gap:16px;font-size:13px">
            <div><span style="font-weight:600">${cl.capacity}</span> places</div>
            <div><span style="font-weight:600;color:var(--yiriba-vert)">${cl.period_type || 'trimestre'}</span></div>
          </div>
          ${(cl.enrollment_fee || cl.annual_tuition) ? `<div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border);font-size:12px;display:flex;gap:14px">
            ${cl.enrollment_fee ? `<span><i class="fas fa-file-invoice" style="margin-right:4px;color:var(--yiriba-jaune)"></i>Inscription: <b>${Number(cl.enrollment_fee).toLocaleString('fr-FR')} FCFA</b></span>` : ''}
            ${cl.annual_tuition ? `<span><i class="fas fa-calendar-check" style="margin-right:4px;color:var(--yiriba-vert)"></i>Scolarité: <b>${Number(cl.annual_tuition).toLocaleString('fr-FR')} FCFA</b></span>` : ''}
          </div>` : ''}
          <div style="margin-top:12px;height:4px;background:var(--surface-soft);border-radius:2px;overflow:hidden">
            <div style="height:100%;width:${Math.min(100, Math.round(0 / cl.capacity * 100))}%;background:var(--yiriba-vert);border-radius:2px"></div>
          </div>
        </article>
      `).join('')}
    </div>`
    : `
    <div class="card section-card">
      <div class="empty">
        <div class="empty-icon"><i class="fas fa-chalkboard"></i></div>
        <h4>Aucune classe créée</h4>
        <p>Créez votre première classe pour organiser vos élèves et vos enseignements.</p>
        <span class="link" onclick="showAddClassModal()"><i class="fas fa-plus"></i> Nouvelle classe →</span>
      </div>
    </div>`}
  `;
}

function showAddClassModal() {
  showModal('Nouvelle classe', `
    <div class="modal-form">
      <div class="form-group"><label>Nom de la classe</label><input id="cl-name" placeholder="Ex: 6ème A"></div>
      <div class="form-row">
        <div class="form-group"><label>Niveau</label><input id="cl-level" placeholder="Ex: 6ème"></div>
        <div class="form-group"><label>Capacité</label><input id="cl-capacity" type="number" value="50" min="1" max="200"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Année scolaire</label><input id="cl-year" value="2025-2026"></div>
        <div class="form-group"><label>Période</label><select id="cl-period"><option value="trimestre">Trimestre</option><option value="semestre">Semestre</option></select><div style="font-size:11px;color:var(--yiriba-rouge);margin-top:4px"><i class="fas fa-exclamation-triangle" style="margin-right:4px"></i>Ce choix est définitif. Il ne pourra pas être modifié après la création.</div></div>
      </div>
      <div style="border-top:1px solid var(--border);margin-top:12px;padding-top:12px">
        <div style="font-weight:700;font-size:13px;color:var(--yiriba-primary);margin-bottom:8px"><i class="fas fa-coins" style="margin-right:6px"></i>Frais de scolarité</div>
        <div class="form-row">
          <div class="form-group"><label>Frais d'inscription (FCFA)</label><input id="cl-enroll-fee" type="number" min="0" placeholder="Ex: 15000"></div>
          <div class="form-group"><label>Scolarité annuelle (FCFA)</label><input id="cl-annual-fee" type="number" min="0" placeholder="Ex: 75000"></div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="submitClass()"><i class="fas fa-plus"></i> Créer</button>
      </div>
    </div>
  `);
}

async function submitClass() {
  const data = {
    name: document.getElementById('cl-name').value.trim(),
    level: document.getElementById('cl-level').value.trim() || null,
    capacity: parseInt(document.getElementById('cl-capacity').value) || 50,
    academic_year: document.getElementById('cl-year').value.trim() || '2025-2026',
    period_type: document.getElementById('cl-period').value,
    enrollment_fee: document.getElementById('cl-enroll-fee')?.value ? parseFloat(document.getElementById('cl-enroll-fee').value) : null,
    annual_tuition: document.getElementById('cl-annual-fee')?.value ? parseFloat(document.getElementById('cl-annual-fee').value) : null,
  };
  if (!data.name) { showToast('Le nom est requis', 'error'); return; }
  try {
    const res = await api('/api/classes', { method: 'POST', body: JSON.stringify(data) });
    if (res?.ok) { closeModal(); showToast('Classe créée'); loadClasses(); }
    else { const j = await res.json(); showToast(parseError(j) || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

async function editClass(id) {
  try {
    const res = await api('/api/classes?per_page=200');
    if (!res?.ok) return;
    const cl = (await res.json()).classes.find(c => c.id === id);
    if (!cl) { showToast('Classe introuvable', 'error'); return; }
    showModal('Modifier — ' + cl.name, `
      <div class="modal-form">
        <div class="form-group"><label>Nom</label><input id="cl-name" value="${escapeHtml(cl.name)}"></div>
        <div class="form-row">
          <div class="form-group"><label>Niveau</label><input id="cl-level" value="${cl.level || ''}"></div>
          <div class="form-group"><label>Capacité</label><input id="cl-capacity" type="number" value="${cl.capacity}" min="1" max="200"></div>
        </div>
        <div class="form-group"><label>Période</label><select id="cl-period"><option value="trimestre" ${cl.period_type==='trimestre'?'selected':''}>Trimestre</option><option value="semestre" ${cl.period_type==='semestre'?'selected':''}>Semestre</option></select></div>
        <div style="border-top:1px solid var(--border);margin-top:12px;padding-top:12px">
          <div style="font-weight:700;font-size:13px;color:var(--yiriba-primary);margin-bottom:8px"><i class="fas fa-file-invoice-dollar" style="margin-right:6px"></i>Frais de scolarité</div>
          <div class="form-row">
            <div class="form-group"><label>Frais d'inscription (FCFA)</label><input id="cl-enroll-fee" type="number" min="0" value="${cl.enrollment_fee || ''}" placeholder="Ex: 15000"></div>
            <div class="form-group"><label>Scolarité annuelle (FCFA)</label><input id="cl-annual-fee" type="number" min="0" value="${cl.annual_tuition || ''}" placeholder="Ex: 75000"></div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-secondary" onclick="closeModal()">Annuler</button>
          <button class="btn-add" onclick="submitEditClass(${id})"><i class="fas fa-check"></i> Enregistrer</button>
        </div>
      </div>
    `);
  } catch { showToast('Erreur', 'error'); }
}

async function submitEditClass(id) {
  const data = {
    name: document.getElementById('cl-name').value.trim(),
    level: document.getElementById('cl-level').value.trim() || null,
    capacity: parseInt(document.getElementById('cl-capacity').value) || 50,
    period_type: document.getElementById('cl-period').value,
    enrollment_fee: document.getElementById('cl-enroll-fee')?.value ? parseFloat(document.getElementById('cl-enroll-fee').value) : null,
    annual_tuition: document.getElementById('cl-annual-fee')?.value ? parseFloat(document.getElementById('cl-annual-fee').value) : null,
  };
  if (!data.name) { showToast('Le nom est requis', 'error'); return; }
  try {
    const res = await api(`/api/classes/${id}`, { method: 'PUT', body: JSON.stringify(data) });
    if (res?.ok) { closeModal(); showToast('Classe modifiée'); loadClasses(); }
    else { showToast('Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

async function deleteClass(id, name) {
  if (!confirm(`Supprimer la classe « ${name} » ?`)) return;
  try {
    const res = await api(`/api/classes/${id}`, { method: 'DELETE' });
    if (res?.ok || res?.status === 204) { showToast('Classe supprimée'); loadClasses(); }
    else { showToast('Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

/* ==============================================================
   PORTAIL ENSEIGNANT — Dashboard & fonctions
   ============================================================== */
async function loadTeacherDashboard() {
  const c = document.getElementById('main-content');
  const fn = state.user?.first_name || 'Enseignant';
  c.innerHTML = `yiribaLoading("Chargement...")`;
  try {
    const [clsRes, evRes] = await Promise.all([
      api('/api/teacher/my-classes'),
      api('/api/teacher/my-evaluations'),
    ]);
    const classes = clsRes?.ok ? (await clsRes.json()).classes || [] : [];
    const evals = evRes?.ok ? (await evRes.json()).evaluations || [] : [];
    c.innerHTML = `
      <div class="welcome"><h1>Bonjour, ${fn} 👋</h1><p>Voici votre tableau de bord enseignant.</p></div>
      <div class="indicator-row">
        <div class="indicator-card hero">
          <div class="indicator-icon"><i class="fas fa-chalkboard"></i></div>
          <div class="indicator-info"><h4>Mes classes</h4><div class="indicator-val">${classes.length}</div><div class="indicator-sub">Affectées</div></div>
        </div>
        <div class="indicator-card">
          <div class="indicator-icon" style="color:var(--yiriba-jaune)"><i class="fas fa-file-lines"></i></div>
          <div class="indicator-info"><h4>Évaluations</h4><div class="indicator-val">${evals.length}</div><div class="indicator-sub">Créées</div></div>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px">
        <div class="card section-card" style="cursor:pointer" onclick="loadPage('t-grades')">
          <div style="display:flex;align-items:center;gap:12px;padding:16px">
            <div style="width:48px;height:48px;border-radius:12px;background:var(--yiriba-ivoire);display:flex;align-items:center;justify-content:center;font-size:20px;color:var(--yiriba-vert-profond)"><i class="fas fa-pen-fancy"></i></div>
            <div><h3 style="margin:0;font-size:15px">Saisir des notes</h3><p style="margin:2px 0 0;font-size:12px;color:var(--yiriba-text-secondaire)">Accéder à la grille de saisie rapide</p></div>
          </div>
        </div>
        <div class="card section-card" style="cursor:pointer" onclick="loadPage('t-attendance')">
          <div style="display:flex;align-items:center;gap:12px;padding:16px">
            <div style="width:48px;height:48px;border-radius:12px;background:var(--yiriba-ivoire);display:flex;align-items:center;justify-content:center;font-size:20px;color:var(--yiriba-vert-profond)"><i class="fas fa-clipboard-check"></i></div>
            <div><h3 style="margin:0;font-size:15px">Faire l'appel</h3><p style="margin:2px 0 0;font-size:12px;color:var(--yiriba-text-secondaire)">Pointer les présences de vos classes</p></div>
          </div>
        </div>
      </div>
      <div class="card section-card" style="margin-top:16px">
        <div style="padding:16px;border-bottom:1px solid var(--border)"><h3 style="margin:0;font-size:15px">Mes classes</h3></div>
        <div style="padding:8px">${classes.length > 0 ? classes.map(cls => `
          <div style="display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:8px;transition:background 0.15s" onmouseover="this.style.background='var(--yiriba-ivoire)'" onmouseout="this.style.background='transparent'">
            <div style="width:36px;height:36px;border-radius:8px;background:var(--yiriba-vert-profond);color:white;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700">${cls.name ? cls.name.charAt(0) : '?'}</div>
            <div><div style="font-weight:600;font-size:14px">${cls.name || 'Classe'}</div><div style="font-size:12px;color:var(--yiriba-text-secondaire)">${cls.student_count || 0} élèves</div></div>
          </div>
        `).join('') : '<p style="padding:16px;color:var(--yiriba-text-secondaire)">Aucune classe assignée</p>'}</div>
      </div>
    `;
  } catch {
    c.innerHTML = `<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur de chargement</h4></div></div>`;
  }
}

async function loadTeacherClasses() {
  const c = document.getElementById('main-content');
  c.innerHTML = `yiribaLoading()`;
  try {
    const res = await api('/api/teacher/my-classes');
    const classes = res?.ok ? (await res.json()).classes || [] : [];
    c.innerHTML = `
      <div class="welcome"><h1>Mes classes</h1><p>Les classes qui vous sont assignées.</p></div>
      ${classes.length > 0 ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px">
        ${classes.map(cls => `<div class="card section-card" style="padding:20px">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
            <div style="width:48px;height:48px;border-radius:12px;background:var(--yiriba-vert-profond);color:white;display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700">${cls.name ? cls.name.charAt(0) : '?'}</div>
            <div><h3 style="margin:0;font-size:16px">${cls.name}</h3><p style="margin:2px 0 0;font-size:12px;color:var(--yiriba-text-secondaire)">${cls.level || ''}</p></div>
          </div>
          <div style="display:flex;gap:16px;font-size:13px;color:var(--yiriba-text-secondaire)">
            <span><i class="fas fa-user-graduate"></i> ${cls.student_count || 0} élèves</span>
          </div>
        </div>`).join('')}
      </div>` : `<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-chalkboard"></i></div><h4>Aucune classe</h4><p>Contactez l'administration pour être affecté à des classes.</p></div></div>`}
    `;
  } catch {
    c.innerHTML = `<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>`;
  }
}

async function loadComptableDashboard() {
  const c = document.getElementById('main-content');
  const fn = state.user?.first_name || 'Comptable';
  c.innerHTML = 'yiribaLoading()';

  let payments = [], students = [], obligations = [];
  try {
    const [payRes, stRes, obRes] = await Promise.all([
      api('/api/payments?per_page=500'),
      api('/api/students?per_page=1'),
      api('/api/payments/obligations?per_page=500'),
    ]);
    if (payRes?.ok) payments = (await payRes.json()).payments || [];
    if (stRes?.ok) students = (await stRes.json()).students || [];
    if (obRes?.ok) obligations = (await obRes.json()).obligations || [];
  } catch {}

  const confirmed = payments.filter(p => (p.status||'').toLowerCase() === 'confirmed');
  const totalCollected = confirmed.reduce((s, p) => s + (p.amount || 0), 0);
  const pending = payments.filter(p => (p.status||'').toLowerCase() === 'pending');
  const totalPending = pending.reduce((s, p) => s + (p.amount || 0), 0);
  const totalOwed = obligations.reduce((s, o) => s + (o.amount || 0), 0);
  const unpaid = totalOwed - totalCollected;

  // Group payments by method
  const byMethod = {};
  confirmed.forEach(p => {
    const m = p.payment_method || 'other';
    if (!byMethod[m]) byMethod[m] = { count: 0, total: 0 };
    byMethod[m].count++;
    byMethod[m].total += p.amount || 0;
  });

  c.innerHTML = `
    <div class="welcome"><h1>Bonjour, ${fn} 👋</h1><p>Vue d'ensemble des finances de l'établissement.</p></div>
    <div class="indicator-row">
      <div class="indicator-card hero">
        <div class="indicator-icon"><i class="fas fa-coins"></i></div>
        <div class="indicator-info"><h4>Total encaissé</h4><div class="indicator-val">${totalCollected.toLocaleString('fr-FR')} FCFA</div><div class="indicator-sub">${confirmed.length} paiements confirmés</div></div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon" style="color:var(--yiriba-jaune)"><i class="fas fa-clock"></i></div>
        <div class="indicator-info"><h4>En attente</h4><div class="indicator-val">${totalPending.toLocaleString('fr-FR')} FCFA</div><div class="indicator-sub">${pending.length} paiements</div></div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon" style="color:var(--yiriba-rouge)"><i class="fas fa-exclamation-triangle"></i></div>
        <div class="indicator-info"><h4>Impayés</h4><div class="indicator-val">${unpaid.toLocaleString('fr-FR')} FCFA</div><div class="indicator-sub">Reste à encaisser</div></div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px">
      <div class="card section-card" style="padding:20px">
        <div style="font-weight:700;font-size:14px;margin-bottom:16px"><i class="fas fa-chart-pie" style="color:var(--yiriba-vert);margin-right:8px"></i>Répartition par méthode</div>
        ${Object.entries(byMethod).map(([m, data]) => {
          const labels = { cash: 'Espèces', mobile_money: 'Mobile Money', bank: 'Virement', other: 'Autre' };
          return `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border)"><span style="font-size:13px">${labels[m] || m}</span><div style="display:flex;gap:12px;font-size:13px"><span style="color:var(--texte-secondaire)">${data.count} opérations</span><strong>${data.total.toLocaleString('fr-FR')} FCFA</strong></div></div>`;
        }).join('') || '<div style="font-size:13px;color:var(--texte-secondaire);text-align:center;padding:16px">Aucun paiement</div>'}
      </div>
      <div class="card section-card" style="padding:20px">
        <div style="font-weight:700;font-size:14px;margin-bottom:16px"><i class="fas fa-history" style="color:var(--yiriba-vert);margin-right:8px"></i>Derniers paiements</div>
        ${payments.slice(0, 5).map(p => `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px"><div><strong>${(p.amount || 0).toLocaleString('fr-FR')} FCFA</strong><div style="font-size:11px;color:var(--texte-secondaire)">Élève #${p.student_id} · ${p.payment_method || ''}</div></div><span class="badge ${(p.status||'').toLowerCase() === 'confirmed' ? 'badge-active' : 'badge-warning'}"><span class="badge-dot"></span>${(p.status||'').toLowerCase() === 'confirmed' ? 'Confirmé' : 'En attente'}</span></div>`).join('') || '<div style="font-size:13px;color:var(--texte-secondaire);text-align:center;padding:16px">Aucun paiement</div>'}
      </div>
    </div>
    <div class="card section-card" style="margin-top:16px;padding:20px">
      <div class="section-title" style="font-size:14px;margin-bottom:16px"><i class="fas fa-lightbulb" style="color:var(--yiriba-jaune);margin-right:8px"></i>Actions rapides</div>
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <button class="btn-add" onclick="loadPage('payments')"><i class="fas fa-money-bill-wave"></i> Voir les paiements</button>
        <button class="btn-secondary" onclick="loadPage('fee-structure')"><i class="fas fa-file-invoice-dollar"></i> Structure des frais</button>
        <button class="btn-secondary" onclick="showPaymentModal()"><i class="fas fa-plus"></i> Enregistrer un paiement</button>
      </div>
    </div>
  `;
}
/* ==============================================================
   NOTIFICATIONS — Portails
   ============================================================== */
let _notifState = { filter: 'all', type: '', search: '', page: 1 };

async function loadNotifications() {
  const c = document.getElementById('main-content');
  _notifState = { filter: 'all', type: '', search: '', page: 1 };
  c.innerHTML = `
    <div class="welcome"><h1>Notifications</h1><p>Vos alertes et informations.</p></div>
    <div class="card section-card" style="margin-bottom:14px">
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <div style="display:flex;gap:0;border:1px solid var(--border);border-radius:10px;overflow:hidden">
          <button class="btn-secondary" id="nf-all" style="border:none;border-radius:0" onclick="notifFilter('all')">Toutes</button>
          <button class="btn-secondary" id="nf-unread" style="border:none;border-radius:0" onclick="notifFilter('unread')">Non lues</button>
          <button class="btn-secondary" id="nf-read" style="border:none;border-radius:0" onclick="notifFilter('read')">Lues</button>
        </div>
        <select id="nf-type" onchange="notifLoad()" style="padding:8px;border:1px solid var(--border);border-radius:8px;font-size:13px">
          <option value="">Tous les types</option>
          <option value="announcement">Annonces</option>
          <option value="absence">Absences</option>
          <option value="payment_reminder">Paiements</option>
          <option value="grade_published">Notes</option>
          <option value="other">Autres</option>
        </select>
        <input id="nf-search" placeholder="Rechercher…" style="padding:8px;border:1px solid var(--border);border-radius:8px;font-size:13px;width:180px" onkeydown="if(event.key==='Enter')notifLoad()">
        <div style="flex:1"></div>
        <button class="btn-secondary" onclick="notifMarkAllRead()"><i class="fas fa-check-double"></i> Tout marquer comme lu</button>
      </div>
    </div>
    <div id="notif-list"><div class="empty"><i class="fas fa-spinner fa-spin"></i><p>Chargement…</p></div></div>
  `;
  notifLoad();
}

function notifFilter(f) {
  _notifState.filter = f;
  ['all','unread','read'].forEach(x => {
    const btn = document.getElementById('nf-' + x);
    if (btn) btn.style.background = x === f ? 'var(--yiriba-vert)' : '';
    if (btn) btn.style.color = x === f ? 'white' : '';
  });
  notifLoad();
}

async function notifLoad() {
  const zone = document.getElementById('notif-list');
  if (!zone) return;
  _notifState.type = document.getElementById('nf-type')?.value || '';
  _notifState.search = document.getElementById('nf-search')?.value || '';
  zone.innerHTML = '<div class="empty"><i class="fas fa-spinner fa-spin"></i><p>Chargement…</p></div>';
  const params = new URLSearchParams({ page: _notifState.page, per_page: '30' });
  if (_notifState.filter === 'unread') params.set('read', 'false');
  if (_notifState.filter === 'read') params.set('read', 'true');
  if (_notifState.type) params.set('type', _notifState.type);
  if (_notifState.search) params.set('q', _notifState.search);
  let data = {};
  try {
    const res = await api('/api/notifications/search?' + params.toString());
    if (res?.ok) data = await res.json();
  } catch {}
  const notifs = data.notifications || [];
  const unread = data.unread_total || 0;
  const typeIcons = { announcement: 'fa-bullhorn', absence: 'fa-user-xmark', payment_reminder: 'fa-money-bill-wave', grade_published: 'fa-pen-fancy', other: 'fa-bell' };
  const typeLabels = { announcement: 'Annonce', absence: 'Absence', payment_reminder: 'Paiement', grade_published: 'Note', other: 'Info' };
  if (!notifs.length) {
    zone.innerHTML = `<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-bell"></i></div><h4>Aucune notification</h4><p>Vous êtes à jour !</p></div></div>`;
    return;
  }
  zone.innerHTML = `
    ${unread > 0 ? `<div style="font-size:12px;color:var(--texte-secondaire);margin-bottom:8px">${unread} notification(s) non lue(s)</div>` : ''}
    <div class="card section-card" style="padding:4px">
    ${notifs.map(n => `
      <div style="display:flex;gap:12px;padding:14px 12px;border-bottom:1px solid var(--border);cursor:${n.related_entity_type ? 'pointer' : 'default'};${n.is_read ? 'opacity:0.65' : ''}" ${n.related_entity_type ? `onclick="notifOpen(${n.id},'${n.related_entity_type}',${n.related_entity_id || 'null'})"` : ''}>
        <div style="width:38px;height:38px;border-radius:10px;background:var(--yiriba-ivoire);display:flex;align-items:center;justify-content:center;flex-shrink:0">
          <i class="fas ${typeIcons[n.type] || 'fa-bell'}" style="color:var(--yiriba-vert);font-size:14px"></i>
        </div>
        <div style="flex:1;min-width:0">
          <div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline">
            <div style="font-weight:${n.is_read ? '500' : '700'};font-size:13px">${escapeHtml(n.title || 'Notification')}</div>
            <div style="font-size:11px;color:var(--texte-secondaire);white-space:nowrap">${n.created_at ? new Date(n.created_at).toLocaleDateString('fr-FR', {day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : ''}</div>
          </div>
          <div style="font-size:12px;color:var(--texte-secondaire);margin-top:2px">${escapeHtml(n.body || '')}</div>
          <div style="display:flex;gap:6px;margin-top:6px;align-items:center">
            <span class="badge badge-inactive" style="font-size:10px">${typeLabels[n.type] || n.type}</span>
            ${!n.is_read ? '<span class="badge badge-active" style="font-size:10px">Non lue</span>' : ''}
            ${n.related_entity_type === 'bulletin' ? '<span style="font-size:11px;color:var(--yiriba-vert)"><i class="fas fa-arrow-right"></i> Voir le bulletin</span>' : ''}
          </div>
        </div>
      </div>`).join('')}
    </div>`;
}

async function notifMarkAllRead() {
  try {
    const res = await api('/api/notifications/mark-read', { method: 'POST', body: JSON.stringify({}) });
    if (res?.ok) { showToast('Toutes les notifications sont lues'); notifLoad(); refreshNotifBadge(); }
    else showToast('Erreur', 'error');
  } catch { showToast('Erreur réseau', 'error'); }
}

async function notifOpen(id, type, relatedId) {
  // Marquer comme lue puis naviguer
  try { await api('/api/notifications/mark-read', { method: 'POST', body: JSON.stringify({ notification_ids: [id] }) }); } catch {}
  refreshNotifBadge();
  if (type === 'bulletin') loadPage('bulletins');
  else if (type === 'payment') loadPage('payments');
  else if (type === 'attendance') loadPage('attendance');
  else if (type === 'message') loadPage('p-messages') || loadPage('messages');
  else notifLoad();
}

/* ==============================================================
   COMMUNICATION (ADMIN) — Annonces
   ============================================================== */
async function loadCommunication() {
  const c = document.getElementById('main-content');
  let classes = [];
  try { const r = await api('/api/classes?per_page=200'); if (r?.ok) classes = (await r.json()).classes || []; } catch {}
  c.innerHTML = `
    <div class="welcome"><h1>Communication</h1><p>Envoyez des annonces aux parents, élèves et enseignants de votre établissement.</p></div>
    <div class="card section-card" style="max-width:760px">
      <h3 style="font-size:15px;margin-bottom:14px"><i class="fas fa-bullhorn" style="color:var(--yiriba-vert);margin-right:6px"></i>Nouvelle annonce</h3>
      <div class="form-group"><label>Titre *</label><input id="ann-title" placeholder="Ex : Réunion parents-professeurs" style="width:100%"></div>
      <div class="form-group"><label>Contenu *</label><textarea id="ann-content" rows="5" placeholder="Message destiné aux destinataires…" style="width:100%"></textarea></div>
      <div class="form-group"><label>Destinataires *</label>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px">
          <label style="display:flex;gap:8px;align-items:center;font-size:13px;font-weight:400"><input type="checkbox" class="ann-target" value="all_parents" style="width:auto"> Tous les parents</label>
          <label style="display:flex;gap:8px;align-items:center;font-size:13px;font-weight:400"><input type="checkbox" class="ann-target" value="all_students" style="width:auto"> Tous les élèves</label>
          <label style="display:flex;gap:8px;align-items:center;font-size:13px;font-weight:400"><input type="checkbox" class="ann-target" value="all_teachers" style="width:auto"> Tous les enseignants</label>
          <label style="display:flex;gap:8px;align-items:center;font-size:13px;font-weight:400"><input type="checkbox" class="ann-target" value="everyone" style="width:auto"> Toute l'école</label>
        </div>
        <div style="margin-top:10px;font-size:13px;font-weight:600;color:var(--texte-secondaire)">Ou cibler des classes précises :</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:6px;margin-top:6px">
          ${classes.map(cl => `<label style="display:flex;gap:6px;align-items:center;font-size:12px;font-weight:400"><input type="checkbox" class="ann-class" value="${cl.id}" style="width:auto"> ${escapeHtml(cl.name)}</label>`).join('')}
        </div>
      </div>
      <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px">
        <button class="btn-add" onclick="sendAnnouncement()"><i class="fas fa-paper-plane"></i> Envoyer l'annonce</button>
      </div>
    </div>`;
}

async function sendAnnouncement() {
  const title = document.getElementById('ann-title')?.value.trim();
  const content = document.getElementById('ann-content')?.value.trim();
  if (!title || !content) { showToast('Titre et contenu obligatoires', 'error'); return; }
  const targets = [...document.querySelectorAll('.ann-target:checked')].map(cb => cb.value);
  document.querySelectorAll('.ann-class:checked').forEach(cb => {
    targets.push('class_parents:' + cb.value);
    targets.push('class_students:' + cb.value);
  });
  if (!targets.length) { showToast('Choisissez au moins un destinataire', 'error'); return; }
  try {
    const res = await api('/api/notifications/announcements', { method: 'POST', body: JSON.stringify({ title, content, targets }) });
    if (!res?.ok) { const e = await res.json().catch(()=>({})); showToast(parseError(e) || 'Erreur', 'error'); return; }
    const j = await res.json();
    showToast(`Annonce envoyée à ${j.recipients} destinataire(s)`, 'success');
    document.getElementById('ann-title').value = '';
    document.getElementById('ann-content').value = '';
    document.querySelectorAll('.ann-target:checked,.ann-class:checked').forEach(cb => cb.checked = false);
  } catch { showToast('Erreur réseau', 'error'); }
}

/* ==============================================================
   PRÉFÉRENCES DE NOTIFICATIONS (ADMIN)
   ============================================================== */
async function loadNotifPreferences() {
  const c = document.getElementById('main-content');
  c.innerHTML = '<div class="empty"><i class="fas fa-spinner fa-spin"></i><p>Chargement…</p></div>';
  let events = [];
  try {
    const res = await api('/api/notifications/preferences');
    if (res?.ok) events = (await res.json()).events || [];
  } catch {}
  c.innerHTML = `
    <div class="welcome"><h1>Préférences de notifications</h1><p>Choisissez les événements qui déclenchent une notification dans l'application (et par email si configuré).</p></div>
    <div class="card section-card" style="max-width:700px">
      ${events.length ? events.map(e => `
        <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid var(--border)">
          <div><div style="font-weight:600;font-size:13px">${escapeHtml(e.label)}</div>
          <div style="font-size:11px;color:var(--texte-secondaire)">Notification in-app${e.exists ? '' : ' (réglage par défaut)'}</div></div>
          <div style="display:flex;gap:14px;align-items:center">
            <label style="display:flex;gap:6px;align-items:center;font-size:12px;font-weight:400"><input type="checkbox" id="pref-inapp-${e.key}" ${e.in_app ? 'checked' : ''} onchange="updateNotifPref('${e.key}')" style="width:auto"> In-app</label>
            <label style="display:flex;gap:6px;align-items:center;font-size:12px;font-weight:400"><input type="checkbox" id="pref-email-${e.key}" ${e.email ? 'checked' : ''} onchange="updateNotifPref('${e.key}')" style="width:auto"> Email</label>
          </div>
        </div>`).join('') : '<div class="empty"><i class="fas fa-sliders"></i><p>Aucun événement configurable.</p></div>'}
    </div>`;
}

async function updateNotifPref(eventKey) {
  const inApp = document.getElementById('pref-inapp-' + eventKey)?.checked ?? true;
  const email = document.getElementById('pref-email-' + eventKey)?.checked ?? false;
  try {
    const res = await api('/api/notifications/preferences', { method: 'PUT', body: JSON.stringify({ event_key: eventKey, in_app: inApp, email, is_active: true }) });
    if (res?.ok) showToast('Préférence enregistrée');
    else { const e = await res.json().catch(()=>({})); showToast(parseError(e) || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

/* ==============================================================
   MODULE NOTES — Saisie rapide Yiriba
   ============================================================== */
let _gradeEntry = { data: null, filter: 'all', search: '' };
let _gradeAutoSaveTimers = {};

async function loadGrades() {
  const c = document.getElementById('main-content');
  let evaluations = [], classes = [], subjects = [], periods = [];
  try {
    const [eRes, clRes, sRes, pRes] = await Promise.all([
      api('/api/grades/evaluations?per_page=200'),
      api('/api/classes?per_page=200'),
      api('/api/subjects'),
      api('/api/academic-periods'),
    ]);
    if (eRes?.ok) evaluations = (await eRes.json()).evaluations || [];
    if (clRes?.ok) classes = (await clRes.json()).classes || [];
    if (sRes?.ok) subjects = (await sRes.json()).subjects || [];
    if (pRes?.ok) periods = (await pRes.json()).periods || [];
  } catch {}

  // Store data globally for filtering
  window._gradesData = { evaluations, classes, subjects, periods };
  window._gradesFilter = { classId: '', period: '' };

  // Build dynamic period options from academic periods
  const periodOptions = periods.length
    ? periods.map(p => `<option value="${p.id}" data-short="${p.name.substring(0,2).toUpperCase()}">${p.name}</option>`).join('')
    : '<option value="T1">Trimestre 1</option><option value="T2">Trimestre 2</option><option value="T3">Trimestre 3</option>';

  c.innerHTML = `
    <div class="welcome"><h1>Notes</h1><p>Saisissez et consultez les résultats scolaires.</p></div>
    <div class="indicator-row">
      <div class="indicator-card hero">
        <div class="indicator-icon"><i class="fas fa-pen-fancy"></i></div>
        <div class="indicator-info"><h4>Évaluations</h4><div class="indicator-val" id="grade-eval-count">${evaluations.length}</div><div class="indicator-sub">Créées</div></div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon" style="color:var(--yiriba-jaune)"><i class="fas fa-book"></i></div>
        <div class="indicator-info"><h4>Matières</h4><div class="indicator-val">${subjects.length}</div><div class="indicator-sub">Enseignées</div></div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon" style="color:var(--yiriba-vert-feuille)"><i class="fas fa-chalkboard"></i></div>
        <div class="indicator-info"><h4>Classes</h4><div class="indicator-val">${classes.length}</div><div class="indicator-sub">Actives</div></div>
      </div>
    </div>
    <div class="page-toolbar" style="flex-wrap:wrap;gap:8px">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <label style="font-size:13px;color:var(--texte-secondaire)">Filtrer :</label>
        <select id="grade-filter-class" onchange="filterGrades()" style="padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:white"><option value="">Toutes les classes</option>${classes.map(cl => `<option value="${cl.id}">${escapeHtml(cl.name)}</option>`).join('')}</select>
        <select id="grade-filter-period" onchange="filterGrades()" style="padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:white"><option value="">Toutes périodes</option>${periodOptions}</select>
        <span style="font-size:13px;color:var(--texte-secondaire)" id="grade-filter-count">${evaluations.length} évaluation(s)</span>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn-add" onclick="showCreateEvalModal()"><i class="fas fa-plus"></i> Créer une évaluation</button>
        <button class="btn-add" onclick="showGradeEntryModal()" style="background:var(--yiriba-vert-feuille)"><i class="fas fa-pen"></i> Saisir des notes</button>
      </div>
    </div>
    ${evaluations.length > 0 ? `
    <div class="yiriba-table-wrap">
      <table class="yiriba-table" id="grade-eval-table">
        <thead><tr><th>Évaluation</th><th>Classe</th><th>Matière</th><th>Type</th><th>Période</th><th>Barème</th><th>Coef.</th><th style="text-align:right">Actions</th></tr></thead>
        <tbody>${evaluations.map(e => {
          const cls = classes.find(cl => cl.id === e.class_id) || {};
          const sub = subjects.find(s => s.id === e.subject_id) || {};
          const typeMap = {devoir:'Devoir',devoir1:'Devoir 1',devoir2:'Devoir 2',composition:'Composition',controle:'Contrôle',examen:'Examen'};
          const typeLabel = typeMap[e.assessment_type] || e.assessment_type || '—';
          return `<tr>
            <td style="font-weight:600">${e.name}</td>
            <td>${cls.name || e.class_id}</td>
            <td>${sub.name || e.subject_id}</td>
            <td><span class="badge badge-info">${typeLabel}</span></td>
            <td>${e.period}</td>
            <td>/${e.max_grade || 20}</td>
            <td style="font-weight:600">x${e.coefficient || 1}</td>
            <td><div class="table-actions" style="justify-content:flex-end">
              <button class="btn-sm-green" onclick="openGradeGrid(${e.id})"><i class="fas fa-pen"></i> Saisir</button>
            </div></td>
          </tr>`;
        }).join('')}</tbody>
      </table>
    </div>`
    : `<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-pen-fancy"></i></div><h4>Aucune évaluation</h4><p>Créez d'abord une évaluation pour saisir des notes.</p></div></div>`}
  `;
}

function filterGrades() {
  const d = window._gradesData; if (!d) return;
  const classId = document.getElementById('grade-filter-class')?.value || '';
  const periodVal = document.getElementById('grade-filter-period')?.value || '';
  let filtered = d.evaluations;
  if (classId) filtered = filtered.filter(e => String(e.class_id) === classId);
  if (periodVal) {
    // periodVal is now an academic_period_id (integer)
    const periodId = parseInt(periodVal);
    if (!isNaN(periodId)) {
      filtered = filtered.filter(e => e.academic_period_id === periodId);
    } else {
      filtered = filtered.filter(e => e.period === periodVal);
    }
  }
  const cnt = document.getElementById('grade-filter-count');
  if (cnt) cnt.textContent = `${filtered.length} évaluation(s)`;
  const cc = document.getElementById('grade-eval-count');
  if (cc) cc.textContent = filtered.length;
  // Re-render the evaluations table
  const tableBody = document.querySelector('#grade-eval-table tbody');
  if (!tableBody) return;
  tableBody.innerHTML = filtered.map(e => {
    const cls = d.classes.find(c => c.id === e.class_id);
    const sub = d.subjects.find(s => s.id === e.subject_id);
    const per = d.periods ? d.periods.find(p => p.id === e.academic_period_id) : null;
    const periodLabel = per ? per.name : (e.period || '—');
    const typeMap = {devoir:'Devoir',devoir1:'Devoir 1',devoir2:'Devoir 2',composition:'Composition',controle:'Contrôle',examen:'Examen'};
    const typeLabel = typeMap[e.assessment_type] || escapeHtml(e.assessment_type);
    return `<tr><td style="font-weight:600">${escapeHtml(e.name)}</td><td>${escapeHtml(cls?.name) || '—'}</td><td>${escapeHtml(sub?.name) || '—'}</td><td><span class="badge badge-info">${escapeHtml(typeLabel)}</span></td><td><span style="font-size:12px">${escapeHtml(periodLabel)}</span></td><td>/<span>${e.max_grade || 20}</span></td><td style="font-weight:600">x${e.coefficient || 1}</td><td><div class="table-actions" style="justify-content:flex-end"><button title="Saisir" onclick="startGradeEntry(${e.id})"><i class="fas fa-pen"></i></button></div></td></tr>`;
  }).join('');
}

function showCreateEvalModal() {
  showModal('Créer une évaluation', `
    <div class="modal-form">
      <div class="form-group"><label>Nom</label><input id="ev-name" placeholder="Ex: Devoir 1"></div>
      <div class="form-row">
        <div class="form-group"><label>Classe</label><select id="ev-class"></select></div>
        <div class="form-group"><label>Matière</label><select id="ev-subject"></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Type</label><select id="ev-type"><option value="devoir">Devoir</option><option value="composition">Composition</option><option value="controle">Contrôle</option><option value="examen">Examen</option></select></div>
        <div class="form-group"><label>Période</label><select id="ev-period"></select></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Barème</label><input id="ev-max" type="number" value="20" min="1"></div>
        <div class="form-group"><label>Date</label><input id="ev-date" type="date"></div>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="submitCreateEval()"><i class="fas fa-plus"></i> Créer</button>
      </div>
    </div>
  `);
  // Load classes, subjects and periods dynamically
  api('/api/classes?per_page=200').then(r => r?.ok ? r.json() : null).then(j => { if (!j) return; const cls = j.classes || []; const sel = document.getElementById('ev-class'); if (sel) cls.forEach(c => { const o = document.createElement('option'); o.value = c.id; o.textContent = c.name; sel.appendChild(o); }); });
  api('/api/subjects').then(r => r?.ok ? r.json() : null).then(j => { if (!j) return; const subs = j.subjects || []; const sel = document.getElementById('ev-subject'); if (sel) subs.forEach(s => { const o = document.createElement('option'); o.value = s.id; o.textContent = s.name; sel.appendChild(o); }); });
  // Load academic periods dynamically
  api('/api/academic-periods').then(r => r?.ok ? r.json() : null).then(j => {
    if (!j) return;
    const periods = j.periods || [];
    const sel = document.getElementById('ev-period');
    if (!sel) return;
    periods.forEach(p => {
      const o = document.createElement('option');
      o.value = p.id;
      o.textContent = p.name + (p.status === 'active' ? ' (en cours)' : '');
      o.dataset.short = p.name.substring(0,2).toUpperCase();
      sel.appendChild(o);
    });
    // Auto-select active period
    const active = periods.find(p => p.status === 'active');
    if (active) sel.value = active.id;
  });
}

async function submitCreateEval() {
  const periodSel = document.getElementById('ev-period');
  const periodId = periodSel ? parseInt(periodSel.value) : null;
  const periodOpt = periodSel?.selectedOptions?.[0];
  const periodShort = periodOpt?.dataset?.short || 'T1'; // Derive T1/T2/T3/S1/S2 from name
  const data = {
    name: document.getElementById('ev-name').value.trim(),
    class_id: parseInt(document.getElementById('ev-class').value),
    subject_id: parseInt(document.getElementById('ev-subject').value),
    assessment_type: document.getElementById('ev-type').value,
    period: periodShort,
    academic_period_id: periodId,
    max_score: parseFloat(document.getElementById('ev-max').value) || 20,
    date: document.getElementById('ev-date').value || null,
  };
  if (!data.name || !data.class_id || !data.subject_id) { showToast('Remplissez tous les champs', 'error'); return; }
  try {
    const res = await api('/api/grades/evaluations', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
    if (res?.ok) { closeModal(); showToast('Évaluation créée'); loadGrades(); }
    else { const d = await res.json().catch(()=>({})); showToast(d.detail || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

function showGradeEntryModal() {
  showModal('Saisir des notes', `
    <div class="modal-form">
      <div class="form-group"><label>Évaluation</label><select id="gr-eval"><option value="">Choisir une évaluation</option></select></div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="openGradeGridFromModal()"><i class="fas fa-pen"></i> Ouvrir la grille</button>
      </div>
    </div>
  `);
  loadEvalsForSelect('gr-eval');
}

async function loadEvalsForSelect(selectId) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  try {
    const res = await api('/api/grades/evaluations?per_page=200');
    if (res?.ok) {
      const evals = (await res.json()).evaluations || [];
      evals.forEach(e => {
        const opt = document.createElement('option');
        opt.value = e.id;
        opt.textContent = `${e.name} (${e.period})`;
        sel.appendChild(opt);
      });
    }
  } catch {}
}

function openGradeGridFromModal() {
  const evalId = parseInt(document.getElementById('gr-eval').value);
  if (!evalId) { showToast('Choisissez une évaluation', 'error'); return; }
  closeModal();
  openGradeGrid(evalId);
}

async function openGradeGrid(evaluationId) {
  const c = document.getElementById('main-content');
  c.innerHTML = `<div style="text-align:center;padding:40px;color:var(--yiriba-text-secondaire)"><i class="fas fa-spinner fa-spin" style="font-size:24px"></i><p style="margin-top:10px">Chargement de la grille...</p></div>`;
  try {
    const res = await api(`/api/grades/entry/${evaluationId}`);
    if (!res?.ok) throw new Error('Erreur API');
    _gradeEntry.data = await res.json();
    _gradeEntry.filter = 'all';
    _gradeEntry.search = '';
    _gradeEntry.evalId = evaluationId;
    renderGradeGrid();
  } catch {
    c.innerHTML = `<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur de chargement</h4><p>Impossible de charger les données de cette évaluation.</p><span class="link" onclick="loadGrades()">← Retour aux notes</span></div></div>`;
  }
}

function renderGradeGrid() {
  const c = document.getElementById('main-content');
  const d = _gradeEntry.data;
  if (!d) return;
  const ev = d.evaluation;
  const students = d.students;
  const stats = d.stats;
  const pct = stats.total > 0 ? Math.round((stats.entered / stats.total) * 100) : 0;
  const isComplete = stats.entered === stats.total && stats.total > 0;
  const progressColor = isComplete ? '#2E7D32' : pct >= 80 ? 'var(--yiriba-vert-feuille)' : 'var(--yiriba-vert-profond)';

  // Apply filters
  let filtered = [...students];
  if (_gradeEntry.filter === 'entered') filtered = filtered.filter(s => s.status === 'graded' && s.grade !== null);
  else if (_gradeEntry.filter === 'missing') filtered = filtered.filter(s => s.status === 'empty');
  else if (_gradeEntry.filter === 'absent') filtered = filtered.filter(s => s.status === 'absent' || s.status === 'excused');
  if (_gradeEntry.search) {
    const q = _gradeEntry.search.toLowerCase();
    filtered = filtered.filter(s => s.name.toLowerCase().includes(q) || s.matricule.toLowerCase().includes(q));
  }

  c.innerHTML = `
    <div class="grade-grid-header">
      <div class="grade-grid-title">
        <button class="btn-back" onclick="loadGrades()"><i class="fas fa-arrow-left"></i></button>
        <div>
          <h2>${ev.name}</h2>
          <p>${ev.subject_name || ''} • ${ev.period} • /${ev.max_grade} (x${ev.coefficient}) • ${ev.date}</p>
        </div>
      </div>
      ${ev.is_finalized ? '<span class="badge badge-finalized"><i class="fas fa-lock"></i> Finalisée</span>' : ''}
    </div>
    <div class="grade-progress-bar">
      <div class="grade-progress-info">
        <span><strong>${stats.entered}</strong> / ${stats.total} notes saisies</span>
        <span>${pct}%</span>
      </div>
      <div class="grade-progress-track">
        <div class="grade-progress-fill" style="width:${pct}%;background:${progressColor}"></div>
      </div>
      ${isComplete ? '<div class="grade-complete-msg"><i class="fas fa-check-circle"></i> Saisie terminée !</div>' : ''}
    </div>
    <div class="grade-toolbar">
      <div class="grade-filters">
        <button class="gf ${_gradeEntry.filter === 'all' ? 'active' : ''}" onclick="setGradeFilter('all')">Tous (${stats.total})</button>
        <button class="gf ${_gradeEntry.filter === 'entered' ? 'active' : ''}" onclick="setGradeFilter('entered')">Saisies (${stats.entered})</button>
        <button class="gf ${_gradeEntry.filter === 'missing' ? 'active' : ''}" onclick="setGradeFilter('missing')">Manquantes (${stats.missing})</button>
        <button class="gf ${_gradeEntry.filter === 'absent' ? 'active' : ''}" onclick="setGradeFilter('absent')">Absents (${stats.absent + stats.excused})</button>
      </div>
      <div class="grade-toolbar-right">
        <input type="text" class="grade-search" placeholder="Rechercher..." value="${_gradeEntry.search}" oninput="_gradeEntry.search=this.value;renderGradeGrid()">
        <button class="btn-mark-all-present" onclick="openExcelImport()"><i class="fas fa-paste"></i> Coller Excel</button>
      </div>
    </div>
    <div class="grade-table-wrap">
      <table class="grade-table">
        <thead><tr>
          <th style="width:40px">#</th>
          <th>Élève</th>
          <th style="width:140px">Note /${ev.max_grade}</th>
          <th style="width:80px">État</th>
          <th style="width:200px">Actions</th>
        </tr></thead>
        <tbody>${filtered.map((s, i) => {
          const origIdx = students.indexOf(s);
          let stateIcon = '';
          if (s.status === 'absent') stateIcon = '<span class="badge-absent">ABS</span>';
          else if (s.status === 'excused') stateIcon = '<span class="badge-excused">DISP</span>';
          else if (s.grade !== null) stateIcon = '<span class="badge-saved">✓</span>';
          else stateIcon = '<span class="badge-missing">⚠</span>';
          const gradeVal = s.status === 'graded' && s.grade !== null ? s.grade : '';
          return `<tr data-idx="${origIdx}" data-student-id="${s.id}">
            <td style="color:var(--yiriba-text-secondaire);font-size:12px">${origIdx + 1}</td>
            <td>
              <div class="grade-student-cell">
                <div class="grade-student-avatar" style="background:${s.gender === 'F' ? '#C94A35' : 'var(--yiriba-vert-feuille)'}">${(s.last_name || '')[0] || ''}${(s.first_name || '')[0] || ''}</div>
                <div><div class="grade-student-name">${s.name}</div><div class="grade-student-mat">${s.matricule || ''}</div></div>
              </div>
            </td>
            <td><input type="number" class="grade-input ${s.status === 'graded' && s.grade !== null ? 'filled' : ''} ${ev.is_finalized ? 'finalized' : ''}" 
              value="${gradeVal}" 
              min="0" max="${ev.max_grade}" step="0.5"
              data-idx="${origIdx}" data-student-id="${s.id}"
              ${ev.is_finalized ? 'disabled' : ''}
              onfocus="this.select()"
              oninput="onGradeInput(this)"
              onkeydown="onGradeKeydown(event, this)">
            </td>
            <td>${stateIcon}</td>
            <td>
              <div class="grade-actions">
                <button class="ga-btn" title="ABS" onclick="setGradeStatus(${origIdx},'absent')" ${ev.is_finalized ? 'disabled' : ''}><i class="fas fa-user-xmark"></i></button>
                <button class="ga-btn" title="Mettre 0" onclick="setGradeValue(${origIdx},0)" ${ev.is_finalized ? 'disabled' : ''}><i class="fas fa-zero"></i></button>
                <button class="ga-btn" title="Effacer" onclick="clearGrade(${origIdx})" ${ev.is_finalized ? 'disabled' : ''}><i class="fas fa-eraser"></i></button>
              </div>
            </td>
          </tr>`;
        }).join('')}</tbody>
      </table>
    </div>
    ${!ev.is_finalized ? `<div class="grade-finalize-bar">
      <button class="btn-finalize" onclick="finalizeEval(${ev.id})"><i class="fas fa-lock"></i> Finaliser la saisie</button>
    </div>` : `<div class="grade-finalize-bar">
      <button class="btn-reopen" onclick="reopenEval(${ev.id})"><i class="fas fa-lock-open"></i> Rouvrir la saisie</button>
    </div>`}
  `;
  // Auto-focus first empty grade input
  setTimeout(() => {
    const firstEmpty = c.querySelector('.grade-input:not(.filled):not(.finalized)');
    if (firstEmpty) firstEmpty.focus();
  }, 100);
}

function setGradeFilter(f) { _gradeEntry.filter = f; renderGradeGrid(); }

function onGradeInput(el) {
  const idx = parseInt(el.dataset.idx);
  const val = el.value.trim();
  if (_gradeAutoSaveTimers[idx]) clearTimeout(_gradeAutoSaveTimers[idx]);
  if (val === '') {
    el.classList.remove('filled');
    return;
  }
  const ev = _gradeEntry.data.evaluation;
  const num = parseFloat(val.replace(',', '.'));
  if (isNaN(num) || num < 0 || num > ev.max_grade) {
    el.classList.add('grade-error');
    el.title = `Doit être entre 0 et ${ev.max_grade}`;
    return;
  }
  el.classList.remove('grade-error');
  el.title = '';
  _gradeAutoSaveTimers[idx] = setTimeout(() => saveSingleGrade(idx, num), 500);
}

function onGradeKeydown(e, el) {
  const idx = parseInt(el.dataset.idx);
  const students = _gradeEntry.data.students;
  if (e.key === 'Enter') {
    e.preventDefault();
    if (e.shiftKey) moveGradeFocus(idx, -1);
    else moveGradeFocus(idx, 1);
  } else if (e.key === 'ArrowDown') {
    e.preventDefault(); moveGradeFocus(idx, 1);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault(); moveGradeFocus(idx, -1);
  } else if (e.key === 'Home') {
    e.preventDefault(); moveGradeFocus(-1, 0);
  } else if (e.key === 'End') {
    e.preventDefault(); moveGradeFocus(students.length, 0);
  }
}

function moveGradeFocus(currentIdx, delta) {
  const students = _gradeEntry.data.students;
  let nextIdx;
  if (delta === 0) nextIdx = currentIdx < 0 ? 0 : students.length - 1;
  else nextIdx = currentIdx + delta;
  if (nextIdx < 0 || nextIdx >= students.length) return;
  const input = document.querySelector(`.grade-input[data-idx="${nextIdx}"]`);
  if (input && !input.disabled) { input.focus(); input.select(); }
}

async function saveSingleGrade(idx, gradeValue) {
  const s = _gradeEntry.data.students[idx];
  const evalId = _gradeEntry.data.evaluation.id;
  s.grade = gradeValue;
  s.status = 'graded';
  const input = document.querySelector(`.grade-input[data-idx="${idx}"]`);
  if (input) { input.classList.add('filled'); input.classList.add('saving'); }
  try {
    const res = await api(`/api/grades/entry?evaluation_id=${evalId}`, {
      method: 'PATCH',
      body: JSON.stringify({ student_id: s.id, grade: gradeValue, status: 'graded' }),
    });
    if (res?.ok) {
      if (input) { input.classList.remove('saving'); input.classList.add('saved'); setTimeout(() => input.classList.remove('saved'), 1000); }
      _gradeEntry.data.stats.entered = _gradeEntry.data.students.filter(st => st.status === 'graded' && st.grade !== null).length;
      _gradeEntry.data.stats.missing = _gradeEntry.data.students.filter(st => st.status === 'empty').length;
    } else {
      if (input) { input.classList.remove('saving'); input.classList.add('save-error'); }
    }
  } catch {
    if (input) { input.classList.remove('saving'); input.classList.add('save-error'); }
  }
}

async function setGradeStatus(idx, status) {
  const s = _gradeEntry.data.students[idx];
  const evalId = _gradeEntry.data.evaluation.id;
  s.status = status;
  s.grade = null;
  try {
    await api(`/api/grades/entry?evaluation_id=${evalId}`, {
      method: 'PATCH',
      body: JSON.stringify({ student_id: s.id, grade: null, status }),
    });
    recalcStats(); renderGradeGrid();
  } catch {}
}

async function setGradeValue(idx, val) {
  const s = _gradeEntry.data.students[idx];
  s.grade = val; s.status = 'graded';
  await saveSingleGrade(idx, val);
  recalcStats();
}

async function clearGrade(idx) {
  const s = _gradeEntry.data.students[idx];
  const evalId = _gradeEntry.data.evaluation.id;
  s.grade = null; s.status = 'empty';
  try {
    await api(`/api/grades/entry?evaluation_id=${evalId}`, {
      method: 'PATCH',
      body: JSON.stringify({ student_id: s.id, grade: null, status: 'empty' }),
    });
    recalcStats(); renderGradeGrid();
  } catch {}
}

function recalcStats() {
  const students = _gradeEntry.data.students;
  _gradeEntry.data.stats.entered = students.filter(s => s.status === 'graded' && s.grade !== null).length;
  _gradeEntry.data.stats.missing = students.filter(s => s.status === 'empty').length;
  _gradeEntry.data.stats.absent = students.filter(s => s.status === 'absent' || s.status === 'excused').length;
}

function openExcelImport() {
  showModal('Coller depuis Excel', `
    <div class="modal-form">
      <p style="font-size:13px;color:var(--yiriba-text-secondaire);margin-bottom:12px">Copiez une colonne de notes depuis Excel/LibreOffice puis collez-la ici :</p>
      <textarea id="excel-paste" rows="10" style="width:100%;font-family:monospace;font-size:13px;padding:10px;border:1px solid var(--border);border-radius:8px;resize:vertical" placeholder="14\n12\nABS\n16\n15"></textarea>
      <div id="excel-preview" style="margin-top:10px"></div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" id="btn-excel-confirm" onclick="confirmExcelImport()" disabled><i class="fas fa-check"></i> Appliquer</button>
      </div>
    </div>
  `);
  document.getElementById('excel-paste').addEventListener('input', previewExcelImport);
}

function previewExcelImport() {
  const raw = document.getElementById('excel-paste').value;
  const lines = raw.split('\n').map(l => l.trim()).filter(l => l);
  let valid = 0, abs = 0, disp = 0, invalid = 0;
  lines.forEach(l => {
    const u = l.toUpperCase().replace(/\s/g, '');
    if (u === 'ABS' || u === 'ABSENT') abs++;
    else if (u === 'DISP' || u === 'DISPENSE') disp++;
    else { const n = parseFloat(l.replace(',', '.')); if (!isNaN(n) && n >= 0 && n <= _gradeEntry.data.evaluation.max_grade) valid++; else invalid++; }
  });
  document.getElementById('excel-preview').innerHTML = `<div style="font-size:12px;color:var(--yiriba-text-secondaire)">${lines.length} valeur(s) détectée(s) : <span style="color:#2E7D32">${valid} valides</span> | <span style="color:var(--yiriba-jaune)">${abs} abs</span> | <span style="color:#1565C0">${disp} disp</span> ${invalid > 0 ? `| <span style="color:var(--yiriba-rouge)">${invalid} invalide(s)</span>` : ''}</div>`;
  document.getElementById('btn-excel-confirm').disabled = invalid > 0 || lines.length === 0;
}

async function confirmExcelImport() {
  const raw = document.getElementById('excel-paste').value;
  const lines = raw.split('\n').map(l => l.trim()).filter(l => l);
  const evalId = _gradeEntry.data.evaluation.id;
  const students = _gradeEntry.data.students;
  const entries = [];
  lines.forEach((l, i) => {
    if (i >= students.length) return;
    const u = l.toUpperCase().replace(/\s/g, '');
    if (u === 'ABS' || u === 'ABSENT') entries.push({ student_id: students[i].id, grade: null, status: 'absent' });
    else if (u === 'DISP' || u === 'DISPENSE') entries.push({ student_id: students[i].id, grade: null, status: 'excused' });
    else entries.push({ student_id: students[i].id, grade: parseFloat(l.replace(',', '.')), status: 'graded' });
  });
  try {
    const res = await api(`/api/grades/import/confirm?evaluation_id=${evalId}`, {
      method: 'POST',
      body: JSON.stringify(entries),
    });
    if (res?.ok) {
      closeModal();
      showToast(`${entries.length} notes importées`);
      openGradeGrid(evalId);
    } else { showToast('Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

async function finalizeEval(evalId) {
  if (!confirm('Finaliser cette évaluation ? Les notes seront bloquées.')) return;
  try {
    const res = await api(`/api/grades/evaluations/${evalId}/finalize`, { method: 'POST' });
    if (res?.ok) { showToast('Évaluation finalisée'); openGradeGrid(evalId); }
    else { showToast('Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

async function reopenEval(evalId) {
  if (!confirm('Rouvrir cette évaluation ?')) return;
  try {
    const res = await api(`/api/grades/evaluations/${evalId}/reopen`, { method: 'POST' });
    if (res?.ok) { showToast('Évaluation rouverte'); openGradeGrid(evalId); }
    else { showToast('Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

async function deleteGrade(id) {
  if (!confirm('Supprimer cette note ?')) return;
  try {
    const res = await api(`/api/grades/${id}`, { method: 'DELETE' });
    if (res?.ok || res?.status === 204) { showToast('Note supprimée'); loadGrades(); }
    else { showToast('Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}


/* ==============================================================
   MODULE PRÉSENCES — Grille Yiriba
   ============================================================== */
async function loadAttendance() {
  const c = document.getElementById('main-content');
  let attendances = [], total = 0, classes = [], students = [];
  try {
    const [aRes, clRes, sRes] = await Promise.all([
      api('/api/attendance?per_page=50'),
      api('/api/classes?per_page=200'),
      api('/api/students?per_page=200'),
    ]);
    if (aRes?.ok) { const j = await aRes.json(); attendances = j.attendance || j.attendances || []; total = j.total || 0; }
    if (clRes?.ok) { classes = (await clRes.json()).classes || []; }
    if (sRes?.ok) { students = (await sRes.json()).students || []; }
  } catch {}

  const presentCount = attendances.filter(a => (a.status||'').toLowerCase() === 'present').length;
  const absentCount = attendances.filter(a => (a.status||'').toLowerCase() === 'absent').length;
  const lateCount = attendances.filter(a => (a.status||'').toLowerCase() === 'late').length;
  const rate = total > 0 ? Math.round(presentCount / total * 100) : 0;

  c.innerHTML = `
    <div class="welcome"><h1>Présences</h1><p>Suivez les présences et absences des élèves.</p></div>

    <div class="indicator-row">
      <div class="indicator-card hero">
        <div class="indicator-icon"><i class="fas fa-clipboard-check"></i></div>
        <div class="indicator-info"><h4>Total présences</h4><div class="indicator-val">${total}</div><div class="indicator-sub">Pointages</div></div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon"><i class="fas fa-check-circle"></i></div>
        <div class="indicator-info"><h4>Présents</h4><div class="indicator-val">${presentCount}</div><div class="indicator-sub">Aujourd'hui</div></div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon" style="color:var(--yiriba-rouge)"><i class="fas fa-times-circle"></i></div>
        <div class="indicator-info"><h4>Absents</h4><div class="indicator-val">${absentCount}</div><div class="indicator-sub">Sans excuse</div></div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon" style="color:var(--yiriba-jaune)"><i class="fas fa-clock"></i></div>
        <div class="indicator-info"><h4>Retards</h4><div class="indicator-val">${lateCount}</div><div class="indicator-sub">Enregistrés</div></div>
      </div>
    </div>

    <div class="page-toolbar">
      <div></div>
      <button class="btn-add" onclick="showAttendanceModal()"><i class="fas fa-clipboard-check"></i> Faire l'appel</button>
    </div>

    ${attendances.length > 0 ? `
    <div class="yiriba-table-wrap">
      <table class="yiriba-table">
        <thead><tr><th>Élève</th><th>Classe</th><th>Date</th><th>Période</th><th>Statut</th><th>Retard</th><th>Justifié</th><th style="text-align:right">Actions</th></tr></thead>
        <tbody>${attendances.map(a => {
          const st = (a.status||'').toLowerCase();
          const statusMap = { present: ['Présent', 'badge-active'], absent: ['Absent', 'badge-danger'], late: ['Retard', 'badge-warning'], excused: ['Justifié', 'badge-info'] };
          const [sl, sc] = statusMap[st] || [a.status, 'badge-inactive'];
          const displayName = a.student_name || (students.find(s => s.id === a.student_id) ? (students.find(s => s.id === a.student_id).last_name + ' ' + students.find(s => s.id === a.student_id).first_name) : '#' + a.student_id);
          const displayClass = a.class_name || (classes.find(cl => cl.id === a.class_id)?.name) || '—';
          return `<tr>
            <td><span class="name-cell" style="font-weight:600">${displayName}</span></td>
            <td>${displayClass}</td>
            <td>${a.date ? new Date(a.date).toLocaleDateString('fr-FR') : '—'}</td>
            <td>${a.period || '—'}</td>
            <td><span class="badge ${sc}"><span class="badge-dot"></span>${sl}</span></td>
            <td>${a.minutes_late ? a.minutes_late + ' min' : '—'}</td>
            <td>${a.is_justified ? '<i class="fas fa-check" style="color:var(--yiriba-vert)"></i>' : '<i class="fas fa-minus" style="color:var(--texte-secondaire)"></i>'}</td>
            <td><div class="table-actions" style="justify-content:flex-end">
              <button title="Supprimer" class="danger" onclick="deleteAttendance(${a.id})"><i class="fas fa-trash"></i></button>
            </div></td>
          </tr>`;
        }).join('')}</tbody>
      </table>
    </div>`
    : `
    <div class="card section-card">
      <div class="empty">
        <div class="empty-icon"><i class="fas fa-clipboard-check"></i></div>
        <h4>Aucune présence enregistrée</h4>
        <p>Commencez par faire l'appel pour suivre les présences de vos élèves.</p>
        <span class="link" onclick="showAttendanceModal()"><i class="fas fa-clipboard-check"></i> Faire l'appel →</span>
      </div>
    </div>`}
  `;
}

async function showAttendanceModal() {
  let classes = [];
  try {
    const res = await api('/api/classes?per_page=200');
    if (res?.ok) { const j = await res.json(); classes = j.classes || []; }
  } catch {}

  const today = new Date().toISOString().split('T')[0];

  showModal('Faire l\'appel', `
    <div class="modal-form">
      <div class="form-row">
        <div class="form-group"><label>Classe</label><select id="att-class" onchange="loadRollCallStudents()"><option value="">Choisir une classe</option>${classes.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('')}</select></div>
        <div class="form-group"><label>Date</label><input id="att-date" type="date" value="${today}"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Période</label><select id="att-period"><option value="T1">T1</option><option value="T2">T2</option><option value="T3">T3</option><option value="S1">S1</option><option value="S2">S2</option></select></div>
      </div>
      <div id="roll-call-area">
        <div class="roll-call-empty">
          <i class="fas fa-clipboard-list"></i>
          <p>Sélectionnez une classe pour afficher les élèves</p>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" id="btn-save-attendance" onclick="submitAttendance()" disabled><i class="fas fa-check"></i> Enregistrer l'appel</button>
      </div>
    </div>
  `);
}

async function loadRollCallStudents() {
  const classId = document.getElementById('att-class').value;
  const area = document.getElementById('roll-call-area');
  if (!classId) {
    area.innerHTML = `<div class="roll-call-empty"><i class="fas fa-clipboard-list"></i><p>Sélectionnez une classe pour afficher les élèves</p></div>`;
    document.getElementById('btn-save-attendance').disabled = true;
    return;
  }
  area.innerHTML = `<div class="roll-call-loading"><i class="fas fa-spinner fa-spin"></i> Chargement des élèves...</div>`;
  try {
    const res = await api(`/api/students?class_id=${classId}&per_page=100`);
    if (!res?.ok) throw new Error('Erreur API');
    const j = await res.json();
    const students = j.students || [];
    if (!students.length) {
      area.innerHTML = `<div class="roll-call-empty"><i class="fas fa-user-slash"></i><p>Aucun élève inscrit dans cette classe</p></div>`;
      return;
    }
    let html = `<div class="roll-call-toolbar"><span class="roll-call-count">${students.length} élèves inscrits</span><button class="btn-mark-all-present" onclick="markAllPresent()"><i class="fas fa-check-double"></i> Tous présents</button></div><div class="roll-call-grid">`;
    students.forEach(s => {
      const initials = ((s.first_name||'')[0] || '') + ((s.last_name||'')[0] || '');
      const fullName = `${s.first_name || ''} ${s.last_name || ''}`.trim();
      html += `
        <div class="roll-call-row" data-student-id="${s.id}">
          <div class="roll-call-student">
            <div class="roll-call-avatar">${initials.toUpperCase()}</div>
            <div class="roll-call-info">
              <span class="roll-call-name">${fullName}</span>
              <span class="roll-call-matricule">${s.matricule || ''}</span>
            </div>
          </div>
          <div class="roll-call-actions">
            <button type="button" class="roll-btn roll-present" onclick="setRollStatus(this,'present')" title="Présent"><i class="fas fa-check"></i></button>
            <button type="button" class="roll-btn roll-absent" onclick="setRollStatus(this,'absent')" title="Absent"><i class="fas fa-times"></i></button>
            <button type="button" class="roll-btn roll-late" onclick="setRollStatus(this,'late')" title="Retard"><i class="fas fa-clock"></i></button>
            <button type="button" class="roll-btn roll-excused" onclick="setRollStatus(this,'excused')" title="Justifié"><i class="fas fa-shield-alt"></i></button>
            <button type="button" class="roll-btn" style="background:#fce4ec;color:var(--yiriba-rouge);border:1px solid var(--yiriba-rouge);margin-left:4px" onclick="closeModal();showDisciplineModal(${s.id}, '${(s.first_name + ' ' + s.last_name).replace(/'/g, "\\'")}');" title="Signaler un incident"><i class="fas fa-exclamation-triangle"></i></button>
          </div>
        </div>`;
    });
    html += '</div>';
    area.innerHTML = html;
    document.getElementById('btn-save-attendance').disabled = false;
  } catch (e) {
    area.innerHTML = `<div class="roll-call-empty"><i class="fas fa-exclamation-triangle"></i><p>Erreur lors du chargement</p></div>`;
  }
}

function markAllPresent() {
  document.querySelectorAll('.roll-call-row[data-student-id]').forEach(row => {
    const presentBtn = row.querySelector('.roll-present');
    if (presentBtn) setRollStatus(presentBtn, 'present');
  });
  showToast('Tous les élèves marqués présents', 'success');
}

function setRollStatus(btn, status) {
  const row = btn.closest('.roll-call-row');
  row.querySelectorAll('.roll-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  row.dataset.status = status;
}

async function submitAttendance() {
  const classId = parseInt(document.getElementById('att-class').value);
  const dateVal = document.getElementById('att-date').value;
  const period = document.getElementById('att-period').value;
  if (!classId || !dateVal) { showToast('Remplissez la classe et la date', 'error'); return; }
  const rows = document.querySelectorAll('.roll-call-row[data-student-id]');
  const entries = [];
  let missing = 0;
  rows.forEach(r => {
    const sid = parseInt(r.dataset.studentId);
    const st = r.dataset.status;
    if (st) {
      entries.push({ student_id: sid, status: st, minutes_late: st === 'late' ? 5 : 0 });
    } else {
      missing++;
    }
  });
  if (entries.length === 0) { showToast('Aucun statut défini', 'error'); return; }
  if (missing > 0 && !confirm(`${missing} élève(s) sans statut seront ignorés. Continuer ?`)) return;
  const payload = { class_id: classId, date: dateVal, period, entries };
  const result = await OfflineSync.submitAttendanceOrOffline(payload);
  if (result.ok) {
    closeModal();
    if (result.offline) {
      showToast(`Appel sauvegardé localement (${result.pending} en attente)`, 'warning');
    } else {
      showToast(`${entries.length} présences enregistrées`);
    }
    loadAttendance();
  } else {
    showToast(result.error || 'Erreur', 'error');
  }
}

async function deleteAttendance(id) {
  if (!confirm('Supprimer ce pointage ?')) return;
  try {
    const res = await api(`/api/attendance/${id}`, { method: 'DELETE' });
    if (res?.ok || res?.status === 204) { showToast('Pointage supprimé'); loadAttendance(); }
    else { showToast('Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

/* ==============================================================
   MODULE BULLETINS
   ============================================================== */
let _bState = { classId: '', period: '', status: '', search: '', year: '', classes: [], periods: [] };

async function loadBulletins() {
  const c = document.getElementById('main-content');
  let classes = [], years = [];
  try {
    const [clRes, yRes] = await Promise.all([api('/api/classes?per_page=200'), api('/api/academic-years')]);
    if (clRes?.ok) classes = (await clRes.json()).classes || [];
    if (yRes?.ok) years = (await yRes.json()).academic_years || [];
  } catch {}
  const currentYear = (years.find(y => y.is_current) || {}).name || '';
  _bState = { ..._bState, classId: _bState.classId || '', period: _bState.period || '', status: _bState.status || '', search: _bState.search || '', year: _bState.year || currentYear, classes, periods: [] };

  c.innerHTML = `
    <div class="welcome"><h1>Gestion des bulletins</h1><p>Générez, contrôlez et publiez les bulletins scolaires. Les périodes dépendent de la configuration de chaque classe (trimestres ou semestres).</p></div>
    <div class="card section-card" style="margin-bottom:16px">
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px">
        <div class="form-group"><label>Classe</label>
          <select id="b2-class" onchange="b2OnClassChange()">
            <option value="">Toutes les classes</option>
            ${classes.map(cl => `<option value="${cl.id}" ${_bState.classId == cl.id ? 'selected' : ''}>${escapeHtml(cl.name)} (${escapeHtml(cl.academic_year || '')})</option>`).join('')}
          </select></div>
        <div class="form-group"><label>Période</label>
          <select id="b2-period" onchange="b2Load()" ${_bState.classId ? '' : 'disabled'}>
            <option value="">Toutes</option>
          </select></div>
        <div class="form-group"><label>Statut</label>
          <select id="b2-status" onchange="b2Load()">
            <option value="">Tous</option>
            <option value="draft">Brouillon</option>
            <option value="teacher_review">Révision enseignant</option>
            <option value="teacher_validated">Validé enseignant</option>
            <option value="admin_validated">Validé admin</option>
            <option value="published">Publié</option>
            <option value="rejected">Renvoyé</option>
          </select></div>
        <div class="form-group"><label>Recherche élève</label>
          <input id="b2-search" placeholder="Nom ou matricule…" onkeydown="if(event.key==='Enter')b2Load()"></div>
        <div style="display:flex;align-items:flex-end;gap:8px">
          <button class="btn-secondary" onclick="b2Load()"><i class="fas fa-filter"></i> Filtrer</button>
          <button class="btn-add" onclick="showBulletinGenModal()"><i class="fas fa-bolt"></i> Générer</button>
        </div>
      </div>
    </div>
    <div id="b2-list"><div class="empty"><i class="fas fa-spinner fa-spin"></i><p>Chargement…</p></div></div>
  `;
  if (_bState.classId) await b2LoadPeriods();
  b2Load();
}

async function b2OnClassChange() {
  _bState.classId = document.getElementById('b2-class').value;
  _bState.period = '';
  await b2LoadPeriods();
  b2Load();
}

async function b2LoadPeriods() {
  _bState.periods = [];
  const sel = document.getElementById('b2-period');
  if (!sel) return;
  if (!_bState.classId) { sel.disabled = true; sel.innerHTML = '<option value="">Toutes</option>'; return; }
  sel.disabled = false;
  sel.innerHTML = '<option value="">Chargement…</option>';
  try {
    const res = await api(`/api/report-cards/class/${_bState.classId}/periods?academic_year=${encodeURIComponent(_bState.year || '')}`);
    if (res?.ok) _bState.periods = (await res.json()).periods || [];
  } catch {}
  sel.innerHTML = '<option value="">Toutes</option>' + _bState.periods.map(p => `<option value="${p.code}" ${_bState.period === p.code ? 'selected' : ''}>${escapeHtml(p.label)}</option>`).join('');
}

async function b2Load() {
  const zone = document.getElementById('b2-list');
  if (!zone) return;
  _bState.status = document.getElementById('b2-status')?.value || '';
  _bState.search = document.getElementById('b2-search')?.value || '';
  _bState.period = document.getElementById('b2-period')?.value || '';
  zone.innerHTML = '<div class="empty"><i class="fas fa-spinner fa-spin"></i><p>Chargement…</p></div>';
  const params = new URLSearchParams({ per_page: '100' });
  if (_bState.classId) params.set('class_id', _bState.classId);
  if (_bState.period) params.set('period', _bState.period);
  if (_bState.status) params.set('status', _bState.status);
  if (_bState.search) params.set('search', _bState.search);
  let bulletins = [], total = 0;
  try {
    const res = await api('/api/report-cards?' + params.toString());
    if (res?.ok) { const j = await res.json(); bulletins = j.bulletins || []; total = j.total || 0; }
  } catch {}

  const sm = {draft:['Brouillon','badge-warning'], teacher_review:['Révision ens.','badge-info'], teacher_validated:['Validé ens.','badge-info'], admin_validated:['Validé admin','badge-active'], published:['Publié','badge-active'], rejected:['Renvoyé','badge-danger'], generated:['Généré','badge-info']};
  if (!bulletins.length) {
    zone.innerHTML = `<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-file-lines"></i></div><h4>Aucun bulletin</h4><p>Générez les bulletins pour une classe et une période.</p><span class="link" onclick="showBulletinGenModal()"><i class="fas fa-bolt"></i> Générer des bulletins →</span></div></div>`;
    return;
  }
  const counts = {};
  bulletins.forEach(b => { counts[b.status] = (counts[b.status]||0)+1; });
  let bulkHtml = '';
  if (_bState.classId && _bState.period) {
    const roleType = (state.user?.role_type || '').toLowerCase();
    const isAdmin = roleType === 'admin';
    if (counts.draft) bulkHtml += `<button class="btn-secondary" onclick="b2Bulk('draft','teacher_review')"><i class="fas fa-eye"></i> Passer les brouillons en révision (${counts.draft})</button>`;
    if (counts.teacher_validated && isAdmin) bulkHtml += `<button class="btn-add" onclick="b2Bulk('teacher_validated','admin_validated')"><i class="fas fa-check-double"></i> Valider (${counts.teacher_validated})</button>`;
    if (counts.admin_validated && isAdmin) bulkHtml += `<button class="btn-add" onclick="b2Bulk('admin_validated','published')"><i class="fas fa-bullhorn"></i> Publier (${counts.admin_validated})</button>`;
  }
  zone.innerHTML = `
    ${bulkHtml ? `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">${bulkHtml}</div>` : ''}
    <div class="yiriba-table-wrap"><table class="yiriba-table"><thead><tr><th>Élève</th><th>Classe</th><th>Période</th><th>Moyenne</th><th>Rang</th><th>Statut</th><th style="text-align:right">Actions</th></tr></thead><tbody>${bulletins.map(b => {
      const [sl,sc] = sm[b.status] || [b.status,'badge-inactive'];
      return `<tr><td style="font-weight:600">${escapeHtml(b.student_name)}<div style="font-size:11px;color:var(--texte-secondaire)">${escapeHtml(b.matricule || '')}</div></td>
      <td>${escapeHtml(b.class_name)}</td><td>${escapeHtml(b.period_label || b.period)}</td>
      <td><span class="badge ${b.overall_average>=10?'badge-active':'badge-danger'}">${b.overall_average != null ? b.overall_average.toFixed(2) : '—'}/20</span></td>
      <td>${b.rank ? b.rank + (b.total_students ? '/' + b.total_students : '') : '—'}</td>
      <td><span class="badge ${sc}"><span class="badge-dot"></span>${sl}</span></td>
      <td><div class="table-actions" style="justify-content:flex-end">
        <button title="Détail" onclick="b2View(${b.id})"><i class="fas fa-eye"></i></button>
        <button title="PDF" onclick="window.open('/api/report-cards/${b.id}/pdf?token='+state.token)"><i class="fas fa-file-pdf"></i></button>
      </div></td></tr>`;
    }).join('')}</tbody></table></div>`;
}

async function b2Bulk(fromStatus, toStatus) {
  if (!confirm('Appliquer cette transition à tous les bulletins correspondants de la classe/période sélectionnée ?')) return;
  try {
    const res = await api('/api/report-cards/bulk-transition', { method: 'POST', body: JSON.stringify({
      class_id: parseInt(_bState.classId), period: _bState.period,
      academic_year: _bState.year || '2025-2026', from_status: fromStatus, to_status: toStatus,
    }) });
    if (!res?.ok) { const e = await res.json().catch(()=>({})); showToast(parseError(e) || 'Erreur', 'error'); return; }
    const j = await res.json();
    let msg = `${j.transitioned} bulletin(s) mis à jour.`;
    if ((j.errors||[]).length) msg += ` ${j.errors.length} erreur(s).`;
    showToast(msg, (j.errors||[]).length ? 'info' : 'success');
    b2Load();
  } catch { showToast('Erreur réseau', 'error'); }
}

async function b2View(id) {
  try {
    const res = await api(`/api/report-cards/${id}`);
    if (!res?.ok) { showToast('Bulletin introuvable', 'error'); return; }
    const b = await res.json();
    const data = JSON.parse(b.data || '{}');
    const roleType = (state.user?.role_type || '').toLowerCase();
    const isAdmin = roleType === 'admin';
    const canEdit = isAdmin || roleType === 'teacher';
    const sm = {draft:'Brouillon', teacher_review:'Révision enseignant', teacher_validated:'Validé enseignant', admin_validated:'Validé admin', published:'Publié', rejected:'Renvoyé'};
    const nextActions = [];
    if (canEdit && ['draft','rejected'].includes(b.status)) nextActions.push(`<button class="btn-secondary" onclick="b2Transition(${b.id},'teacher_review')">Passer en révision</button>`);
    if (canEdit && b.status === 'teacher_review') nextActions.push(`<button class="btn-add" onclick="b2Transition(${b.id},'teacher_validated')">Valider (enseignant)</button>`);
    if (isAdmin && b.status === 'teacher_validated') nextActions.push(`<button class="btn-add" onclick="b2Transition(${b.id},'admin_validated')">Valider (admin)</button>`);
    if (isAdmin && b.status === 'admin_validated') nextActions.push(`<button class="btn-add" onclick="b2Transition(${b.id},'published')">Publier</button>`);
    if (isAdmin && ['teacher_validated','admin_validated'].includes(b.status)) nextActions.push(`<button class="btn-secondary" style="background:#b45309" onclick="b2Reject(${b.id})">Renvoyer</button>`);
    showModal(`Bulletin — ${b.student.name} (${b.period_label})`, `
      <div style="max-height:60vh;overflow-y:auto">
        <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px;font-size:13px">
          <div><b>Classe :</b> ${escapeHtml(b.class.name)}</div>
          <div><b>Année :</b> ${escapeHtml(b.academic_year)}</div>
          <div><b>Statut :</b> ${sm[b.status] || b.status}</div>
          <div><b>Moyenne :</b> ${b.overall_average != null ? b.overall_average.toFixed(2) : '—'}/20</div>
          <div><b>Rang :</b> ${b.rank ? b.rank + '/' + b.total_students : '—'}</div>
        </div>
        ${data.anomalies && data.anomalies.length ? `<div style="background:#fffbe6;color:#b45309;padding:8px 12px;border-radius:8px;font-size:12px;margin-bottom:10px"><i class="fas fa-triangle-exclamation"></i> ${data.anomalies.map(escapeHtml).join('<br>')}</div>` : ''}
        <table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:12px">
          <thead><tr style="border-bottom:2px solid var(--border);text-align:left">
            <th style="padding:6px 8px">Matière</th><th style="padding:6px 8px">Coef</th><th style="padding:6px 8px">Moyenne</th><th style="padding:6px 8px">Appréciation</th>
          </tr></thead><tbody>
          ${(data.subjects||[]).map(s => `<tr style="border-bottom:1px solid var(--border)">
            <td style="padding:6px 8px">${escapeHtml(s.name)}</td>
            <td style="padding:6px 8px">${s.coefficient}</td>
            <td style="padding:6px 8px">${s.average != null ? s.average.toFixed(2) : '—'}</td>
            <td style="padding:6px 8px">${escapeHtml(s.appreciation || '—')}</td>
          </tr>`).join('')}
        </tbody></table>
        ${data.general_appreciation ? `<div style="font-size:13px;margin-bottom:10px"><b>Appréciation générale :</b> ${escapeHtml(data.general_appreciation)}</div>` : ''}
        ${data.rejection_reason ? `<div style="background:#fde8e8;color:#b91c1c;padding:8px 12px;border-radius:8px;font-size:12px;margin-bottom:10px"><b>Motif du renvoi :</b> ${escapeHtml(data.rejection_reason)}</div>` : ''}
        <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end">
          ${nextActions.join('')}
          <button class="btn-secondary" onclick="window.open('/api/report-cards/${b.id}/pdf?token='+state.token)"><i class="fas fa-file-pdf"></i> PDF</button>
        </div>
      </div>`);
  } catch { showToast('Erreur réseau', 'error'); }
}

async function b2Transition(id, status) {
  try {
    const res = await api(`/api/report-cards/${id}/transition`, { method: 'POST', body: JSON.stringify({ status }) });
    if (!res?.ok) { const e = await res.json().catch(()=>({})); showToast(parseError(e) || 'Erreur', 'error'); return; }
    closeModal(); showToast('Statut mis à jour : ' + status); b2Load();
  } catch { showToast('Erreur réseau', 'error'); }
}

async function b2Reject(id) {
  const reason = prompt("Motif du renvoi à l'enseignant (optionnel) :");
  if (reason === null) return;
  try {
    const res = await api(`/api/report-cards/${id}/transition`, { method: 'POST', body: JSON.stringify({ status: 'rejected', reason }) });
    if (!res?.ok) { const e = await res.json().catch(()=>({})); showToast(parseError(e) || 'Erreur', 'error'); return; }
    closeModal(); showToast("Bulletin renvoyé à l'enseignant"); b2Load();
  } catch { showToast('Erreur réseau', 'error'); }
}

function showBulletinGenModal() {
  showModal('Générer les bulletins', `
    <div class="modal-form">
      <div class="form-group"><label>Classe *</label><select id="bg-class" onchange="bgOnClass()"><option value="">Choisir…</option></select></div>
      <div class="form-group"><label>Période *</label><select id="bg-period" disabled><option value="">Choisir d\\'abord une classe</option></select></div>
      <div id="bg-anomalies" style="font-size:12px;color:var(--texte-secondaire)"></div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="generateBulletinsV2()"><i class="fas fa-bolt"></i> Générer</button>
      </div>
    </div>`);
  api('/api/classes?per_page=200').then(r => r?.ok ? r.json() : null).then(j => {
    const sel = document.getElementById('bg-class');
    if (sel && j) ((j.classes)||[]).forEach(cl => sel.insertAdjacentHTML('beforeend', `<option value="${cl.id}">${escapeHtml(cl.name)} (${escapeHtml(cl.academic_year || '')})</option>`));
  });
}

async function bgOnClass() {
  const classId = document.getElementById('bg-class').value;
  const sel = document.getElementById('bg-period');
  const zone = document.getElementById('bg-anomalies');
  sel.innerHTML = '<option value="">—</option>'; sel.disabled = true;
  zone.innerHTML = '';
  if (!classId) return;
  const res = await api(`/api/report-cards/class/${classId}/periods`);
  if (!res?.ok) return;
  const j = await res.json();
  sel.disabled = false;
  sel.innerHTML = '<option value="">Choisir…</option>' + j.periods.map(p => `<option value="${p.code}">${escapeHtml(p.label)}</option>`).join('');
  zone.innerHTML = `<i class="fas fa-circle-info"></i> Cette classe est configurée en <b>${escapeHtml(j.class.period_type)}</b>.`;
}

async function generateBulletinsV2() {
  const classId = document.getElementById('bg-class').value;
  const period = document.getElementById('bg-period').value;
  if (!classId || !period) { showToast('Choisissez une classe et une période', 'error'); return; }
  try {
    const res = await api('/api/report-cards/generate', { method: 'POST', body: JSON.stringify({ class_id: parseInt(classId), period, academic_year: _bState.year || '2025-2026' }) });
    if (!res?.ok) { const e = await res.json().catch(()=>({})); showToast(parseError(e) || 'Erreur', 'error'); return; }
    const j = await res.json();
    let msg = `${j.created} créé(s), ${j.updated} mis à jour.`;
    if (j.incomplete) msg += ` ${j.incomplete} élève(s) incomplet(s).`;
    if ((j.anomalies||[]).length) msg += ` Anomalies : ${j.anomalies.join(' ; ')}`;
    closeModal();
    showToast(msg, (j.anomalies||[]).length || j.incomplete ? 'info' : 'success');
    _bState.classId = classId; _bState.period = period;
    loadBulletins();
  } catch { showToast('Erreur réseau', 'error'); }
}

/* ==============================================================
   MODULE PAIEMENTS
   ============================================================== */
let _payFilter = { q: '', status: '', method: '' };
async function loadPayments() {
  const c = document.getElementById('main-content');
  let payments = [], total = 0, students = [];
  try {
    const [pRes, sRes] = await Promise.all([api('/api/payments?per_page=100'), api('/api/students?per_page=200')]);
    if (pRes?.ok) { const j = await pRes.json(); payments = j.payments || []; total = j.total || 0; }
    if (sRes?.ok) { students = (await sRes.json()).students || []; }
  } catch {}
  const confirmed = payments.filter(p => (p.status||'').toLowerCase() === 'confirmed');
  const pending = payments.filter(p => (p.status||'').toLowerCase() === 'pending').length;
  const totalAmount = confirmed.reduce((s,p) => s + (p.amount||0), 0);
  // Application des filtres locaux
  let rows = payments;
  if (_payFilter.status) rows = rows.filter(p => (p.status||'').toLowerCase() === _payFilter.status);
  if (_payFilter.method) rows = rows.filter(p => (p.payment_method||'') === _payFilter.method);
  if (_payFilter.q) {
    const q = _payFilter.q.toLowerCase();
    rows = rows.filter(p => (p.student_name||'').toLowerCase().includes(q) || String(p.student_id).includes(q));
  }
  const methodLabels = { cash:'Espèces', mobile_money:'Mobile Money', bank:'Virement', cheque:'Chèque', other:'Autre' };
  c.innerHTML = `
    <div class="welcome"><h1>Paiements</h1><p>Suivez les frais scolaires et les règlements.</p></div>
    <div class="indicator-row">
      <div class="indicator-card hero"><div class="indicator-icon"><i class="fas fa-money-bill-wave"></i></div><div class="indicator-info"><h4>Total encaissé</h4><div class="indicator-val">${totalAmount.toLocaleString('fr-FR')} FCFA</div><div class="indicator-sub">Confirmés</div></div></div>
      <div class="indicator-card"><div class="indicator-icon"><i class="fas fa-check-circle"></i></div><div class="indicator-info"><h4>Confirmés</h4><div class="indicator-val">${confirmed.length}</div><div class="indicator-sub">Paiements</div></div></div>
      <div class="indicator-card"><div class="indicator-icon" style="color:var(--yiriba-jaune)"><i class="fas fa-clock"></i></div><div class="indicator-info"><h4>En attente</h4><div class="indicator-val">${pending}</div><div class="indicator-sub">À confirmer</div></div></div>
      <div class="indicator-card"><div class="indicator-icon" style="color:var(--yiriba-vert-feuille)"><i class="fas fa-receipt"></i></div><div class="indicator-info"><h4>Total opérations</h4><div class="indicator-val">${total}</div><div class="indicator-sub">Enregistrées</div></div></div>
    </div>
    <div class="card section-card" style="margin:14px 0;padding:14px 20px">
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <input id="pay-q" placeholder="Rechercher un élève / matricule…" value="${_payFilter.q}" style="padding:8px;border:1px solid var(--border);border-radius:8px;font-size:13px;width:220px" oninput="_payFilter.q=this.value;clearTimeout(window._payT);window._payT=setTimeout(renderPayTable,300)">
        <select onchange="_payFilter.status=this.value;renderPayTable()" style="padding:8px;border:1px solid var(--border);border-radius:8px;font-size:13px">
          <option value="">Tous statuts</option>
          <option value="confirmed" ${_payFilter.status==='confirmed'?'selected':''}>Confirmés</option>
          <option value="pending" ${_payFilter.status==='pending'?'selected':''}>En attente</option>
          <option value="cancelled" ${_payFilter.status==='cancelled'?'selected':''}>Annulés</option>
        </select>
        <select onchange="_payFilter.method=this.value;renderPayTable()" style="padding:8px;border:1px solid var(--border);border-radius:8px;font-size:13px">
          <option value="">Tous moyens</option>
          ${Object.entries(methodLabels).map(([v,l]) => `<option value="${v}" ${_payFilter.method===v?'selected':''}>${l}</option>`).join('')}
        </select>
        <div style="flex:1"></div>
        <div style="display:flex;align-items:center;gap:6px">
          <select id="pay-export-type" onchange="document.getElementById('pay-export-btn').href='/api/payments/export/csv?export_type='+this.value" style="padding:8px;border:1px solid var(--border);border-radius:8px;font-size:13px">
            <option value="payments">Paiements (CSV)</option>
            <option value="debtors">Débiteurs (CSV)</option>
            <option value="obligations">Obligations (CSV)</option>
          </select>
          <a id="pay-export-btn" class="btn-secondary" href="/api/payments/export/csv?export_type=payments" style="text-decoration:none"><i class="fas fa-file-csv"></i> Exporter</a>
        </div>
        <button class="btn-add" onclick="showPaymentModal()"><i class="fas fa-plus"></i> Enregistrer</button>
      </div>
    </div>
    <div id="pay-table-zone"></div>
  `;
  window._payRows = rows; window._payMethodLabels = methodLabels;
  renderPayTable();
}
function renderPayTable() {
  const zone = document.getElementById('pay-table-zone'); if (!zone) return;
  const rows = window._payRows || [];
  const ml = window._payMethodLabels || {};
  if (_payFilter.q) {
    const q = _payFilter.q.toLowerCase();
    rows = rows.filter(p => (p.student_name||'').toLowerCase().includes(q) || String(p.student_id).includes(q));
  }
  if (!rows.length) {
    zone.innerHTML = `<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-money-bill-wave"></i></div><h4>Aucun paiement</h4><p>Aucune opération ne correspond aux filtres.</p></div></div>`;
    return;
  }
  zone.innerHTML = `<div class="yiriba-table-wrap"><table class="yiriba-table"><thead><tr><th>Élève</th><th>Montant</th><th>Motif / Moyen</th><th>Date</th><th>Statut</th><th style="text-align:right">Actions</th></tr></thead><tbody>${rows.map(p => {
    const st = (p.status||'').toLowerCase();
    const sm = {confirmed:['Confirmé','badge-active'], pending:['En attente','badge-warning'], failed:['Échoué','badge-danger'], refunded:['Remboursé','badge-info'], cancelled:['Annulé','badge-danger']};
    const [sl,sc] = sm[st] || [p.status,'badge-inactive'];
    return `<tr><td style="font-weight:600">${p.student_name || '#' + p.student_id}</td><td style="font-family:'Sora',sans-serif;font-weight:600">${(p.amount||0).toLocaleString('fr-FR')} FCFA</td><td>${ml[p.payment_method] || p.payment_method || '—'}</td><td>${p.paid_at ? new Date(p.paid_at).toLocaleDateString('fr-FR') : '—'}</td><td><span class="badge ${sc}"><span class="badge-dot"></span>${sl}</span></td><td><div class="table-actions" style="justify-content:flex-end"><button title="Voir" onclick="viewPayment(${p.id})"><i class="fas fa-eye"></i></button>${st === 'confirmed' ? `<button title="Reçu PDF" onclick="window.open('/api/payments/${p.id}/receipt?token='+state.token,'_blank')" style="color:var(--yiriba-vert)"><i class="fas fa-file-pdf"></i></button><button title="Aperçu Reçu" onclick="window.open('/api/payments/${p.id}/receipt/html?token='+state.token,'_blank')" style="color:var(--yiriba-vert-profond)"><i class="fas fa-print"></i></button><button title="Corriger" onclick="showCorrectPaymentModal(${p.id}, ${p.amount}, '${p.payment_method||'cash'}')" style="color:var(--yiriba-jaune)"><i class="fas fa-pen"></i></button>` : ''}${st === 'pending' ? `<button title="Confirmer" onclick="confirmPayment(${p.id})" style="color:var(--yiriba-vert)"><i class="fas fa-check-circle"></i></button><button title="Refuser" onclick="rejectPayment(${p.id})" style="color:var(--yiriba-rouge)"><i class="fas fa-times-circle"></i></button>` : ''}</div></td></tr>`;
  }).join('')}</tbody></table></div>`;
}
async function loadDebtors() {
  const c = document.getElementById('main-content');
  let debtors = [];
  try {
    const r = await api('/api/payments/debtors');
    if (r?.ok) debtors = (await r.json()).debtors || [];
  } catch {}
  const totalDebt = debtors.reduce((s,d) => s + (d.balance||0), 0);
  const withOverdue = debtors.filter(d => d.overdue_count > 0);
  c.innerHTML = `
    <div class="welcome"><h1>Impayés & relances</h1><p>Élèves débiteurs et relances aux parents.</p></div>
    <div class="indicator-row">
      <div class="indicator-card hero"><div class="indicator-icon" style="color:var(--yiriba-rouge)"><i class="fas fa-exclamation-circle"></i></div><div class="indicator-info"><h4>Créances totales</h4><div class="indicator-val">${totalDebt.toLocaleString('fr-FR')} FCFA</div><div class="indicator-sub">${debtors.length} élève(s) débiteur(s)</div></div></div>
      <div class="indicator-card"><div class="indicator-icon" style="color:var(--yiriba-jaune)"><i class="fas fa-hourglass-half"></i></div><div class="indicator-info"><h4>Échéances dépassées</h4><div class="indicator-val">${withOverdue.length}</div><div class="indicator-sub">Élèves concernés</div></div></div>
    </div>
    <div class="page-toolbar"><div></div><button class="btn-add" ${!debtors.length ? 'disabled style=opacity:.5' : ''} onclick="remindSelected()"><i class="fas fa-bell"></i> Relancer les parents sélectionnés</button></div>
    ${debtors.length ? `<div class="yiriba-table-wrap"><table class="yiriba-table"><thead><tr><th><input type="checkbox" onchange="document.querySelectorAll('.debtor-check').forEach(c=>c.checked=this.checked)" style="width:auto"></th><th>Élève</th><th>Matricule</th><th>Solde</th><th>Retards</th><th style="text-align:right">Actions</th></tr></thead><tbody>${debtors.map(d => `<tr>
      <td><input type="checkbox" class="debtor-check" value="${d.student_id}" style="width:auto"></td>
      <td style="font-weight:600">${d.name}</td><td>${d.matricule || '—'}</td>
      <td style="font-family:'Sora',sans-serif;font-weight:600;color:${d.overdue_count>0?'var(--yiriba-rouge)':'inherit'}">${(d.balance||0).toLocaleString('fr-FR')} FCFA</td>
      <td>${d.overdue_count > 0 ? `<span class="badge badge-danger"><span class="badge-dot"></span>${d.overdue_count} échéance(s) — ${(d.overdue_amount||0).toLocaleString('fr-FR')} F</span>` : '<span style="color:var(--texte-secondaire);font-size:12px">—</span>'}</td>
      <td><div class="table-actions" style="justify-content:flex-end"><button title="Relancer" onclick="remindSelected([${d.student_id}])" style="color:var(--yiriba-jaune)"><i class="fas fa-bell"></i></button></div></td></tr>`).join('')}</tbody></table></div>`
    : `<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-check-double"></i></div><h4>Aucun impayé</h4><p>Tous les élèves sont à jour.</p></div></div>`}
  `;
}
async function remindSelected(ids) {
  if (!ids) {
    ids = [...document.querySelectorAll('.debtor-check:checked')].map(c => parseInt(c.value));
    if (!ids.length) { showToast('Sélectionnez au moins un élève', 'error'); return; }
  }
  if (!confirm(`Envoyer une relance de paiement aux parents de ${ids.length} élève(s) ?`)) return;
  try {
    const res = await api('/api/payments/reminders', { method: 'POST', body: JSON.stringify({ student_ids: ids }) });
    if (res?.ok) { const j = await res.json(); showToast(`${j.sent} relance(s) envoyée(s)`); }
    else { const j = await res.json(); showToast(parseError(j) || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}
function showPaymentModal() {
  showModal('Enregistrer un paiement', `<div class="modal-form"><div class="form-group"><label>Élève (ID)</label><input id="pay-student" type="number" min="1"></div><div class="form-row"><div class="form-group"><label>Montant (FCFA)</label><input id="pay-amount" type="number" min="1"></div><div class="form-group"><label>Méthode</label><select id="pay-method"><option value="cash">Espèces</option><option value="mobile_money">Mobile Money</option><option value="bank">Virement bancaire</option><option value="cheque">Chèque</option><option value="other">Autre</option></select></div></div><div class="form-group"><label>Notes / N° Chèque / Réf</label><input id="pay-notes" placeholder="Optionnel"></div><div class="modal-footer"><button class="btn-secondary" onclick="closeModal()">Annuler</button><button class="btn-add" onclick="submitPayment()"><i class="fas fa-check"></i> Enregistrer</button></div></div>`);
}
async function submitPayment() {
  const data = {
    student_id: parseInt(document.getElementById('pay-student').value),
    amount: parseFloat(document.getElementById('pay-amount').value),
    payment_method: document.getElementById('pay-method').value,
    notes: document.getElementById('pay-notes').value.trim() || null,
  };
  if (!data.student_id || !data.amount) { showToast('Remplissez les champs requis', 'error'); return; }
  try {
    const res = await api('/api/payments', { method: 'POST', body: JSON.stringify(data) });
    if (res?.ok) { closeModal(); showToast('Paiement enregistré — en attente de confirmation'); loadPayments(); }
    else { const j = await res.json(); showToast(parseError(j) || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}
async function viewPayment(id) {
  try {
    const res = await api(`/api/payments/${id}`);
    if (!res?.ok) { showToast('Paiement introuvable', 'error'); return; }
    const p = await res.json();
    const st = (p.status||'').toLowerCase();
    const sm = {confirmed:'Confirmé', pending:'En attente', failed:'Échoué', refunded:'Remboursé', cancelled:'Annulé'};
    showModal('Détails du paiement', `
      <div style="display:flex;flex-direction:column;gap:14px;font-size:14px">
        <div style="display:flex;justify-content:space-between"><span style="color:var(--texte-secondaire)">Référence</span><strong>#${p.id}</strong></div>
        <div style="display:flex;justify-content:space-between"><span style="color:var(--texte-secondaire)">Montant</span><strong style="font-family:'Sora',sans-serif;font-size:18px">${(p.amount||0).toLocaleString('fr-FR')} FCFA</strong></div>
        <div style="display:flex;justify-content:space-between"><span style="color:var(--texte-secondaire)">Élève</span><span>${p.student_id ? '#' + p.student_id : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span style="color:var(--texte-secondaire)">Méthode</span><span>${p.payment_method || '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span style="color:var(--texte-secondaire)">Date</span><span>${p.paid_at ? new Date(p.paid_at).toLocaleDateString('fr-FR') : '—'}</span></div>
        <div style="display:flex;justify-content:space-between"><span style="color:var(--texte-secondaire)">Statut</span><span class="badge ${st === 'confirmed' ? 'badge-active' : (st === 'cancelled' ? 'badge-danger' : 'badge-warning')}"><span class="badge-dot"></span>${sm[st] || p.status}</span></div>
        ${p.notes ? `<div><span style="color:var(--texte-secondaire)">Notes</span><div style="margin-top:4px">${p.notes}</div></div>` : ''}
        ${p.correction_reason ? `<div style="background:var(--yiriba-ivoire);border-radius:8px;padding:8px 12px;font-size:12px;color:var(--texte-secondaire)"><i class="fas fa-pen" style="margin-right:6px"></i>Rectifié : ${p.correction_reason}</div>` : ''}
      </div>
      <div class="modal-footer" style="margin-top:20px">
        <button class="btn-secondary" onclick="closeModal()">Fermer</button>
        ${st === 'confirmed' ? `<a class="btn-secondary" href="/api/payments/${p.id}/receipt?token=${state.token}" target="_blank" style="text-decoration:none"><i class="fas fa-file-pdf"></i> PDF</a><a class="btn-secondary" href="/api/payments/${p.id}/receipt/html?token=${state.token}" target="_blank" style="text-decoration:none"><i class="fas fa-print"></i> Aperçu</a><button class="btn-secondary" onclick="showCorrectPaymentModal(${p.id}, ${p.amount}, '${p.payment_method||'cash'}')" style="color:var(--yiriba-jaune)"><i class="fas fa-pen"></i> Corriger</button><button class="btn-secondary" onclick="cancelPayment(${p.id})" style="color:var(--yiriba-rouge)"><i class="fas fa-ban"></i> Annuler</button>` : ''}
        ${st === 'pending' ? `<button class="btn-add" onclick="confirmPayment(${p.id})"><i class="fas fa-check"></i> Confirmer</button><button class="btn-secondary" onclick="rejectPayment(${p.id})" style="color:var(--yiriba-rouge)"><i class="fas fa-times"></i> Refuser</button>` : ''}
      </div>`);
  } catch { showToast('Erreur réseau', 'error'); }
}
function showCorrectPaymentModal(id, currentAmount, currentMethod) {
  showModal('Corriger le paiement #' + id, `
    <div class="modal-form">
      <p style="font-size:13px;color:var(--texte-secondaire);margin-bottom:12px">Toute modification d'un paiement requiert un motif explicite et sera consignée dans l'audit.</p>
      <div class="form-row">
        <div class="form-group"><label>Montant (FCFA)</label><input id="corr-amount" type="number" min="1" value="${currentAmount || ''}"></div>
        <div class="form-group"><label>Moyen</label><select id="corr-method"><option value="cash" ${currentMethod==='cash'?'selected':''}>Espèces</option><option value="mobile_money" ${currentMethod==='mobile_money'?'selected':''}>Mobile Money</option><option value="bank" ${currentMethod==='bank'?'selected':''}>Virement bancaire</option><option value="cheque" ${currentMethod==='cheque'?'selected':''}>Chèque</option><option value="other" ${currentMethod==='other'?'selected':''}>Autre</option></select></div>
      </div>
      <div class="form-group"><label>Motif de la rectification (obligatoire, min 3 car.)</label><textarea id="corr-reason" rows="3" placeholder="Ex : Erreur de montant sur reçu initial, chèque régularisé..."></textarea></div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="submitCorrectPayment(${id})"><i class="fas fa-check"></i> Enregistrer la correction</button>
      </div>
    </div>
  `);
}
async function submitCorrectPayment(id) {
  const amount = parseFloat(document.getElementById('corr-amount').value);
  const payment_method = document.getElementById('corr-method').value;
  const reason = document.getElementById('corr-reason').value.trim();
  if (!amount || reason.length < 3) { showToast('Montant et motif obligatoire (min. 3 car.)', 'error'); return; }
  try {
    const res = await api(`/api/payments/${id}/correct`, {
      method: 'PATCH',
      body: JSON.stringify({ amount, payment_method, reason }),
    });
    if (res?.ok) { closeModal(); showToast('Paiement rectifié avec succès'); loadPayments(); }
    else { const j = await res.json(); showToast(parseError(j) || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}
async function cancelPayment(id) {
  showModal('Annuler le paiement', `
    <div class="modal-form">
      <p style="font-size:13px;color:var(--texte-secondaire);margin-bottom:12px">Le paiement sera marqué « annulé ». Cette opération est enregistrée dans l'audit et ne peut pas être supprimée.</p>
      <div class="form-group"><label>Motif (obligatoire)</label><textarea id="cancel-reason" rows="3" placeholder="Ex : erreur de saisie, chèque sans provision…"></textarea></div>
      <div class="modal-footer"><button class="btn-secondary" onclick="closeModal()">Retour</button><button class="btn-add" style="background:var(--yiriba-rouge)" onclick="submitCancelPayment(${id})"><i class="fas fa-ban"></i> Confirmer l'annulation</button></div>
    </div>`);
}
async function submitCancelPayment(id) {
  const reason = document.getElementById('cancel-reason').value.trim();
  if (reason.length < 3) { showToast('Motif obligatoire (3 caractères min.)', 'error'); return; }
  try {
    const res = await api(`/api/payments/${id}/cancel`, { method: 'PATCH', body: JSON.stringify({ reason }) });
    if (res?.ok) { closeModal(); showToast('Paiement annulé'); loadPayments(); }
    else { const j = await res.json(); showToast(parseError(j) || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}
async function confirmPayment(id) {
  try {
    const res = await api(`/api/payments/${id}/confirm`, { method: 'PATCH' });
    if (res?.ok) { closeModal(); showToast('Paiement confirmé'); loadPayments(); }
    else { showToast('Impossible de confirmer ce paiement', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}
async function rejectPayment(id) {
  if (!confirm('Refuser ce paiement ?')) return;
  try {
    const res = await api(`/api/payments/${id}/reject`, { method: 'PATCH' });
    if (res?.ok) { showToast('Paiement refusé'); loadPayments(); }
    else { showToast('Impossible de refuser ce paiement', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

/* ==============================================================
   MODULE ENSEIGNANTS
   ============================================================== */
async function loadTeachers() {
  const c = document.getElementById('main-content');
  let users = [], total = 0, specialtiesMap = {};
  try {
    const r = await api('/api/admin/users?per_page=100');
    if (r?.ok) { const j = await r.json(); users = j.users || []; total = j.total || 0; }
  } catch {}
  const teachers = users.filter(u => (u.role_type||'').toLowerCase() === 'teacher');
  const activeCount = teachers.filter(t => (t.status||'').toLowerCase() === 'active').length;
  // Fetch specialties for each teacher
  for (const t of teachers) {
    try {
      const sr = await api(`/api/admin/teachers/${t.id}/specialties`);
      if (sr?.ok) { const sj = await sr.json(); specialtiesMap[t.id] = sj.specialties || []; }
    } catch {}
  }
  c.innerHTML = `
    <div class="welcome"><h1>Enseignants</h1><p>Gérez votre équipe pédagogique.</p></div>
    <div class="indicator-row">
      <div class="indicator-card hero"><div class="indicator-icon"><i class="fas fa-person-chalkboard"></i></div><div class="indicator-info"><h4>Total</h4><div class="indicator-val">${teachers.length}</div><div class="indicator-sub">Enseignants</div></div></div>
      <div class="indicator-card"><div class="indicator-icon"><i class="fas fa-user-check"></i></div><div class="indicator-info"><h4>Actifs</h4><div class="indicator-val">${activeCount}</div><div class="indicator-sub">En activité</div></div></div>
    </div>
    <div class="page-toolbar"><div></div><button class="btn-add" onclick="showAddTeacherModal()"><i class="fas fa-plus"></i> Ajouter un enseignant</button></div>
    ${teachers.length > 0 ? `<div class="yiriba-table-wrap"><table class="yiriba-table"><thead><tr><th>Nom</th><th>Email</th><th>Spécialités</th><th>Statut</th><th style="text-align:right">Actions</th></tr></thead><tbody>${teachers.map(t => {
      const st = (t.status||'').toLowerCase();
      const sm = {active:['Actif','badge-active'], pending:['En attente','badge-warning'], suspended:['Suspendu','badge-danger']};
      const [sl,sc] = sm[st] || [t.status,'badge-inactive'];
      const specs = specialtiesMap[t.id] || [];
      const specBadges = specs.map(s => `<span class="badge badge-info" style="margin:1px">${s.subject_name}</span>`).join('') || '<span style="color:var(--texte-secondaire);font-size:12px">—</span>';
      return `<tr><td style="font-weight:600">${t.first_name} ${t.last_name}</td><td>${t.email}</td><td>${specBadges}</td><td><span class="badge ${sc}"><span class="badge-dot"></span>${sl}</span></td><td><div class="table-actions" style="justify-content:flex-end"><button title="Modifier" onclick="editTeacher(${t.id}, '${t.first_name}', '${t.last_name}', '${t.email}')"><i class="fas fa-pen"></i></button></div></td></tr>`;
    }).join('')}</tbody></table></div>` : `<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-person-chalkboard"></i></div><h4>Aucun enseignant</h4><p>Ajoutez des enseignants pour couvrir vos classes.</p><span class="link" onclick="showAddTeacherModal()"><i class="fas fa-plus"></i> Ajouter un enseignant →</span></div></div>`}
  `;
}
async function showAddTeacherModal() {
  let subjects = [];
  try { const r = await api('/api/subjects?per_page=200'); if (r?.ok) subjects = (await r.json()).subjects || []; } catch {}
  let _tchSubjects = subjects;

  const body = [];
  body.push('<div style="max-height:85vh;overflow-y:auto">');

  // Section 1: Personal info
  body.push('<div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--texte-secondaire);margin-bottom:10px;display:flex;align-items:center;gap:6px">');
  body.push('<i class="fas fa-user" style="color:var(--yiriba-vert)"></i> Informations personnelles</div>');
  body.push('<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">');
  body.push('<div><label style="display:block;font-size:12px;font-weight:600;margin-bottom:4px">Prenom</label><input id="tch-first" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:13px;outline:none" placeholder="Ex: Amadou"><div id="err-tch-first" style="font-size:11px;color:var(--yiriba-rouge);margin-top:3px;display:none"></div></div>');
  body.push('<div><label style="display:block;font-size:12px;font-weight:600;margin-bottom:4px">Nom</label><input id="tch-last" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:13px;outline:none" placeholder="Ex: Diallo"><div id="err-tch-last" style="font-size:11px;color:var(--yiriba-rouge);margin-top:3px;display:none"></div></div>');
  body.push('</div>');
  body.push('<div style="margin-top:12px"><label style="display:block;font-size:12px;font-weight:600;margin-bottom:4px">Email professionnel</label><input id="tch-email" type="email" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:13px;outline:none" placeholder="prenom.nom@ecole.com"><div id="err-tch-email" style="font-size:11px;color:var(--yiriba-rouge);margin-top:3px;display:none"></div></div>');
  body.push('<div style="margin-top:12px"><label style="display:block;font-size:12px;font-weight:600;margin-bottom:4px">Mot de passe</label><div style="position:relative"><input id="tch-pass" type="password" style="width:100%;padding:8px 36px 8px 12px;border:1px solid var(--border);border-radius:6px;font-size:13px;outline:none" placeholder="Min. 8 caracteres" minlength="8"><button type="button" onclick="var p=document.getElementById(\'tch-pass\');var i=document.getElementById(\'tch-eye\');if(p.type===\'password\'){p.type=\'text\';i.className=\'fas fa-eye-slash\'}else{p.type=\'password\';i.className=\'fas fa-eye\'}" style="position:absolute;right:10px;top:50%;transform:translateY(-50%);background:none;border:none;cursor:pointer;color:var(--texte-secondaire);font-size:13px"><i id="tch-eye" class="fas fa-eye"></i></button></div><div id="err-tch-pass" style="font-size:11px;color:var(--yiriba-rouge);margin-top:3px;display:none"></div></div>');

  // Section 2: Subjects
  body.push('<div style="margin-top:20px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--texte-secondaire);margin-bottom:10px;display:flex;align-items:center;gap:6px">');
  body.push('<i class="fas fa-book" style="color:var(--yiriba-vert)"></i> Specialites / matieres</div>');
  body.push('<p style="font-size:12px;color:var(--texte-secondaire);margin:0 0 8px">Selectionnez les matieres que cet enseignant peut enseigner.</p>');
  body.push('<div style="position:relative;margin-bottom:8px"><i class="fas fa-search" style="position:absolute;left:10px;top:50%;transform:translateY(-50%);color:var(--texte-secondaire);font-size:12px"></i><input id="tch-subj-search" oninput="filterTchSubjects()" placeholder="Rechercher une matiere..." style="width:100%;padding:7px 10px 7px 30px;border:1px solid var(--border);border-radius:6px;font-size:12px;outline:none;box-sizing:border-box"></div>');
  body.push('<div id="tch-subj-count" style="font-size:11px;color:var(--yiriba-vert);font-weight:600;margin-bottom:6px"></div>');
  body.push('<div id="tch-subj-list" style="border:1px solid var(--border);border-radius:8px;overflow:hidden;max-height:200px;overflow-y:auto"></div>');
  body.push('<div id="err-tch-subj" style="font-size:11px;color:var(--yiriba-rouge);margin-top:3px;display:none"></div>');

  // Buttons
  body.push('<div style="padding:16px 0 0;display:flex;justify-content:flex-end;gap:8px;margin-top:16px;border-top:1px solid var(--border)">');
  body.push('<button class="btn-secondary" onclick="closeModal()" style="padding:8px 20px;font-size:13px">Annuler</button>');
  body.push('<button id="tch-submit-btn" class="btn-add" onclick="submitAddTeacher()" style="padding:8px 20px;font-size:13px"><i class="fas fa-plus"></i> Ajouter l\'enseignant</button>');
  body.push('</div></div>');

  showModal('Ajouter un enseignant', body.join(''));

  // Render subject list
  function renderSubjList(filter) {
    var list = document.getElementById('tch-subj-list');
    if (!list) return;
    var q = (filter || '').toLowerCase();
    var filtered = _tchSubjects.filter(function(s) { return !q || s.name.toLowerCase().includes(q); });
    if (filtered.length === 0) { list.innerHTML = '<div style="padding:12px;text-align:center;color:var(--texte-secondaire);font-size:12px">Aucune matiere trouvee</div>'; return; }
    list.innerHTML = filtered.map(function(s) {
      return '<div class="tch-subj-row" data-id="' + s.id + '" data-checked="0" onclick="toggleTchSubject(' + s.id + ',this)" style="display:flex;align-items:center;gap:8px;padding:7px 10px;cursor:pointer;transition:background 0.15s;border-bottom:1px solid var(--border)">' +
        '<div style="width:18px;height:18px;border:2px solid var(--border);border-radius:4px;display:flex;align-items:center;justify-content:center;transition:all 0.15s;flex-shrink:0" class="tch-subj-check"></div>' +
        '<span style="font-size:13px;flex:1">' + escapeHtml(s.name) + '</span></div>';
    }).join('');
    updateSubjCount();
  }
  renderSubjList('');
  window.filterTchSubjects = function() { renderSubjList(document.getElementById('tch-subj-search').value); };
  window.toggleTchSubject = function(id, el) {
    var check = el.querySelector('.tch-subj-check');
    var checked = el.dataset.checked === '1';
    if (checked) { el.dataset.checked = '0'; check.style.background = 'transparent'; check.style.borderColor = 'var(--border)'; check.innerHTML = ''; el.style.background = ''; }
    else { el.dataset.checked = '1'; check.style.background = 'var(--yiriba-vert)'; check.style.borderColor = 'var(--yiriba-vert)'; check.innerHTML = '<i class="fas fa-check" style="font-size:10px;color:white"></i>'; el.style.background = '#f0fdf4'; }
    updateSubjCount();
  };
  function updateSubjCount() {
    var count = document.querySelectorAll('.tch-subj-row[data-checked="1"]').length;
    var el = document.getElementById('tch-subj-count');
    if (el) el.textContent = count > 0 ? count + ' matiere' + (count > 1 ? 's' : '') + ' selectionnee' + (count > 1 ? 's' : '') : '';
  }
}

function _clearTchErrors() {
  ['tch-first','tch-last','tch-email','tch-pass','tch-subj'].forEach(id => {
    const el = document.getElementById('err-' + id);
    if (el) el.style.display = 'none';
  });
}
function _showTchError(field, msg) {
  const el = document.getElementById('err-' + field);
  if (el) { el.textContent = msg; el.style.display = 'block'; }
}

async function submitAddTeacher() {
  _clearTchErrors();
  const first = document.getElementById('tch-first').value.trim();
  const last = document.getElementById('tch-last').value.trim();
  const email = document.getElementById('tch-email').value.trim();
  const pass = document.getElementById('tch-pass').value;
  let valid = true;
  if (!first) { _showTchError('tch-first', 'Le prenom est requis'); valid = false; }
  if (!last) { _showTchError('tch-last', 'Le nom est requis'); valid = false; }
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { _showTchError('tch-email', 'Adresse email invalide'); valid = false; }
  if (!pass || pass.length < 8) { _showTchError('tch-pass', 'Le mot de passe doit contenir au moins 8 caracteres'); valid = false; }
  if (!valid) return;

  const btn = document.getElementById('tch-submit-btn');
  const origHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Enregistrement...';

  try {
    const data = { first_name: first, last_name: last, email: email, password: pass, role_type: 'teacher' };
    const res = await api('/api/admin/users', { method: 'POST', body: JSON.stringify(data) });
    if (res?.ok) {
      const j = await res.json(); const teacherId = j.id || j.user_id;
      const subjectIds = [...document.querySelectorAll('.tch-subj-row[data-checked="1"]')].map(el => parseInt(el.dataset.id));
      if (teacherId && subjectIds.length > 0) {
        await api('/api/admin/teachers/' + teacherId + '/specialties', { method: 'PUT', body: JSON.stringify({ subject_ids: subjectIds }) });
      }
      closeModal(); showToast('Enseignant ajoute avec succes'); loadTeachers();
    } else {
      const j = await res.json();
      const msg = j.detail || j.message || 'Erreur lors de l\'ajout';
      if (msg.toLowerCase().includes('email')) _showTchError('tch-email', msg);
      else showToast(msg, 'error');
    }
  } catch { showToast('Erreur reseau', 'error'); }
  finally { btn.disabled = false; btn.innerHTML = origHtml; }
}
/* Fee structure module-level classes cache */
let _feeStructureClasses = [];

/* =============================================================
   MODULE STRUCTURE DES FRAIS — Configuration et suivi
   ============================================================== */
async function loadFeeStructure() {
  const c = document.getElementById('main-content');
  c.innerHTML = `yiribaLoading()`;

  let classes = [], obligations = [], payments = [], students = [];
  try {
    const [clRes, obRes, payRes, stRes] = await Promise.all([
      api('/api/classes?per_page=200'),
      api('/api/payments/obligations?per_page=500'),
      api('/api/payments?per_page=500'),
      api('/api/students?per_page=500'),
    ]);
    if (clRes?.ok) { classes = (await clRes.json()).classes || []; _feeStructureClasses = classes; }
    if (obRes?.ok) obligations = (await obRes.json()).obligations || [];
    if (payRes?.ok) payments = (await payRes.json()).payments || [];
    if (stRes?.ok) students = (await stRes.json()).students || [];
  } catch {}

  // Calculate stats
  const totalObligations = obligations.reduce((s, o) => s + (o.amount || 0), 0);
  const totalPaid = payments.filter(p => (p.status||'').toLowerCase() === 'confirmed').reduce((s, p) => s + (p.amount || 0), 0);
  const pendingAmount = totalObligations - totalPaid;
  const pendingPayments = payments.filter(p => (p.status||'').toLowerCase() === 'pending').length;

  // Group obligations by class
  const obligationsByClass = {};
  obligations.forEach(o => {
    if (!obligationsByClass[o.class_id]) obligationsByClass[o.class_id] = [];
    obligationsByClass[o.class_id].push(o);
  });

  c.innerHTML = `
    <div class="welcome"><h1>Structure des frais</h1><p>Configurez les frais d'inscription, de scolarité et suivez les paiements.</p></div>

    <!-- STATISTIQUES -->
    <div class="indicator-row">
      <div class="indicator-card hero">
        <div class="indicator-icon"><i class="fas fa-file-invoice-dollar"></i></div>
        <div class="indicator-info">
          <h4>Total dû</h4>
          <div class="indicator-val">${totalObligations.toLocaleString('fr-FR')} FCFA</div>
          <div class="indicator-sub">Obligations</div>
        </div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon" style="color:var(--yiriba-vert)"><i class="fas fa-check-circle"></i></div>
        <div class="indicator-info">
          <h4>Encaissé</h4>
          <div class="indicator-val">${totalPaid.toLocaleString('fr-FR')} FCFA</div>
          <div class="indicator-sub">Paiements confirmés</div>
        </div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon" style="color:var(--yiriba-rouge)"><i class="fas fa-exclamation-circle"></i></div>
        <div class="indicator-info">
          <h4>Reste à payer</h4>
          <div class="indicator-val">${pendingAmount.toLocaleString('fr-FR')} FCFA</div>
          <div class="indicator-sub">Impayés</div>
        </div>
      </div>
      <div class="indicator-card">
        <div class="indicator-icon" style="color:var(--yiriba-jaune)"><i class="fas fa-clock"></i></div>
        <div class="indicator-info">
          <h4>En attente</h4>
          <div class="indicator-val">${pendingPayments}</div>
          <div class="indicator-sub">À confirmer</div>
        </div>
      </div>
    </div>

    <!-- TOOLBAR -->
    <div class="page-toolbar">
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <select class="filter-select" id="fs-class-filter">
          <option value="">Toutes les classes</option>
          ${classes.map(cl => `<option value="${cl.id}">${escapeHtml(cl.name)}</option>`).join('')}
        </select>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn-add" onclick="showAutoGenerateObligations()"><i class="fas fa-magic"></i> Générer automatiquement</button>
        <button class="btn-add" onclick="showAddObligationModal()"><i class="fas fa-plus"></i> Ajouter une obligation</button>
      </div>
    </div>

    <!-- OBLIGATIONS BY CLASS -->
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:16px;margin-top:16px">
      ${classes.map(cl => {
        const classObs = obligationsByClass[cl.id] || [];
        const classTotal = classObs.reduce((s, o) => s + (o.amount || 0), 0);
        const classPayments = payments.filter(p => {
          const student = students.find(s => s.id === p.student_id);
          return student && student.current_class_id === cl.id && (p.status||'').toLowerCase() === 'confirmed';
        });
        const classPaid = classPayments.reduce((s, p) => s + (p.amount || 0), 0);
        const classPending = classTotal - classPaid;
        const enrollmentFee = cl.enrollment_fee || 0;
        const annualTuition = cl.annual_tuition || 0;

        return `<div class="card section-card" style="overflow:hidden">
          <div style="background:linear-gradient(135deg,var(--yiriba-vert),var(--yiriba-vert-fonce));color:white;padding:16px 20px;display:flex;justify-content:space-between;align-items:center">
            <div>
              <div style="font-weight:700;font-size:16px">${escapeHtml(cl.name)}</div>
              <div style="font-size:12px;opacity:0.8;margin-top:4px">${cl.level || '—'} · ${cl.academic_year || '—'}</div>
            </div>
            <div style="text-align:right">
              <div style="font-size:24px;font-weight:700;font-family:'Sora',sans-serif">${classTotal.toLocaleString('fr-FR')} FCFA</div>
              <div style="font-size:11px;opacity:0.8">Total dû</div>
            </div>
          </div>
          <div style="padding:16px 20px">
            <!-- FRAIS DE BASE -->
            <div style="display:flex;gap:16px;margin-bottom:16px">
              <div style="flex:1;background:var(--yiriba-ivoire);border-radius:8px;padding:12px;text-align:center">
                <div style="font-size:11px;color:var(--texte-secondaire);text-transform:uppercase;letter-spacing:0.5px">Inscription</div>
                <div style="font-size:18px;font-weight:700;font-family:'Sora',sans-serif;color:var(--yiriba-vert);margin-top:4px">${enrollmentFee.toLocaleString('fr-FR')} FCFA</div>
              </div>
              <div style="flex:1;background:var(--yiriba-ivoire);border-radius:8px;padding:12px;text-align:center">
                <div style="font-size:11px;color:var(--texte-secondaire);text-transform:uppercase;letter-spacing:0.5px">Scolarité/An</div>
                <div style="font-size:18px;font-weight:700;font-family:'Sora',sans-serif;color:var(--yiriba-vert);margin-top:4px">${annualTuition.toLocaleString('fr-FR')} FCFA</div>
              </div>
            </div>

            <!-- PROGRESSION PAIEMENTS -->
            <div style="margin-bottom:16px">
              <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:6px">
                <span style="color:var(--texte-secondaire)">Encaissé</span>
                <span style="font-weight:600">${classPaid.toLocaleString('fr-FR')} / ${classTotal.toLocaleString('fr-FR')} FCFA</span>
              </div>
              <div style="height:8px;background:var(--border);border-radius:4px;overflow:hidden">
                <div style="height:100%;background:${classPending <= 0 ? 'var(--yiriba-vert)' : classPaid / classTotal > 0.5 ? 'var(--yiriba-jaune)' : 'var(--yiriba-rouge)'};width:${classTotal > 0 ? Math.min((classPaid / classTotal) * 100, 100) : 0}%;transition:width 0.3s"></div>
              </div>
            </div>

            <!-- OBLIGATIONS LIST -->
            <div style="font-weight:600;font-size:13px;margin-bottom:8px;color:var(--yiriba-text-secondaire)"><i class="fas fa-list" style="margin-right:6px"></i>Obligations (${classObs.length})</div>
            ${classObs.length > 0 ? classObs.map(o => `
              <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px">
                <div>
                  <div style="font-weight:600">${o.name}</div>
                  <div style="font-size:11px;color:var(--texte-secondaire)">${o.period || '—'} ${o.due_date ? '· Échéance: ' + new Date(o.due_date).toLocaleDateString('fr-FR') : ''}</div>
                </div>
                <div style="display:flex;align-items:center;gap:8px">
                  <span style="font-family:'Sora',sans-serif;font-weight:600">${(o.amount || 0).toLocaleString('fr-FR')} FCFA</span>
                  <button title="Supprimer" class="danger" onclick="deleteObligation(${o.id})" style="padding:4px 8px;font-size:11px"><i class="fas fa-trash"></i></button>
                </div>
              </div>
            `).join('') : '<div style="font-size:12px;color:var(--texte-secondaire);text-align:center;padding:12px">Aucune obligation configurée</div>'}

            <!-- ACTIONS -->
            <div style="margin-top:12px;display:flex;gap:8px">
              <button class="btn-secondary" style="flex:1;font-size:12px" onclick="showAddObligationModal(${cl.id})"><i class="fas fa-plus"></i> Ajouter</button>
              <button class="btn-secondary" style="flex:1;font-size:12px" onclick="showAutoGenerateForClass(${cl.id}, '${escapeHtml(cl.name)}', ${enrollmentFee}, ${annualTuition})"><i class="fas fa-magic"></i> Auto-générer</button>
            </div>
          </div>
        </div>`;
      }).join('')}
    </div>
  `;

  // Filter by class
  const filterEl = document.getElementById('fs-class-filter');
  if (filterEl) {
    filterEl.addEventListener('change', () => {
      const classId = filterEl.value;
      document.querySelectorAll('.section-card').forEach(card => {
        if (!classId) { card.style.display = ''; return; }
        // Simple filter - hide cards not matching
        const title = card.querySelector('div[style*="font-weight:700"]');
        const matchingClass = classes.find(cl => cl.id == classId);
        if (title && matchingClass) {
          card.style.display = title.textContent.includes(matchingClass.name) ? '' : 'none';
        }
      });
    });
  }
}

function showAddObligationModal(classId) {
  const cls = _feeStructureClasses;
  const selected = classId ? [String(classId)] : [];
  const classCheckboxes = cls.map(c => {
    const checked = selected.includes(String(c.id)) ? 'checked' : '';
    return `<label class="ob-class-item" style="display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid var(--border);border-radius:8px;cursor:pointer;background:white;transition:all .15s" onmouseover="this.style.borderColor='var(--yiriba-vert)'" onmouseout="this.style.borderColor='var(--border)'"><input type="checkbox" value="${c.id}" class="ob-class-check" ${checked} style="width:16px;height:16px;accent-color:var(--yiriba-vert)"><span style="font-size:13px;font-weight:500;color:var(--texte-primaire)">${escapeHtml(c.name)}</span></label>`;
  }).join('');
  showModal('Ajouter une obligation', `
    <div class="modal-form">
      <div class="form-group">
        <label style="font-weight:600;margin-bottom:6px;display:block">Classes <span style="font-weight:400;color:var(--texte-secondaire);font-size:12px">(cochez une ou plusieurs)</span></label>
        <div id="ob-classes-list" style="display:flex;flex-direction:column;gap:6px;max-height:160px;overflow-y:auto;padding:4px 0">
          ${classCheckboxes || '<div style="font-size:13px;color:var(--texte-secondaire)">Aucune classe disponible</div>'}
        </div>
        <div style="margin-top:6px;display:flex;gap:8px">
          <button type="button" class="btn-secondary" style="font-size:11px;padding:4px 10px;border-radius:6px" onclick="document.querySelectorAll('.ob-class-check').forEach(c=>c.checked=true)">Tout cocher</button>
          <button type="button" class="btn-secondary" style="font-size:11px;padding:4px 10px;border-radius:6px" onclick="document.querySelectorAll('.ob-class-check').forEach(c=>c.checked=false)">Tout décocher</button>
          <span id="ob-class-count" style="font-size:12px;color:var(--yiriba-vert);font-weight:600;align-self:center">${selected.length || cls.length} sélectionnée(s)</span>
        </div>
      </div>
      <div class="form-group"><label>Nom</label><input id="ob-name" placeholder="Ex: Frais d'inscription T1"></div>
      <div class="form-row">
        <div class="form-group"><label>Montant (FCFA)</label><input id="ob-amount" type="number" min="1"></div>
        <div class="form-group"><label>Période</label><select id="ob-period"><option value="T1">Trimestre 1</option><option value="T2">Trimestre 2</option><option value="T3">Trimestre 3</option><option value="annuel">Annuel</option><option value="inscription">Inscription</option></select></div>
      </div>
      <div class="form-group"><label>Échéance</label><input id="ob-due" type="date"></div>
      <div class="form-group"><label>Description</label><input id="ob-desc" placeholder="Optionnel"></div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="submitObligation()"><i class="fas fa-plus"></i> Ajouter</button>
      </div>
    </div>
  `);
  // Update counter on checkbox change
  document.querySelectorAll('.ob-class-check').forEach(cb => {
    cb.addEventListener('change', () => {
      const count = document.querySelectorAll('.ob-class-check:checked').length;
      document.getElementById('ob-class-count').textContent = count + ' sélectionnée(s)';
    });
  });
}

async function submitObligation() {
  const checked = document.querySelectorAll('.ob-class-check:checked');
  const classIds = Array.from(checked).map(cb => parseInt(cb.value));
  const name = document.getElementById('ob-name').value.trim();
  const amount = parseFloat(document.getElementById('ob-amount').value);
  const period = document.getElementById('ob-period').value;
  const due_date = document.getElementById('ob-due').value || null;
  const description = document.getElementById('ob-desc').value.trim() || null;
  if (!classIds.length || !name || !amount) { showToast('Remplissez les champs requis et sélectionnez au moins une classe', 'error'); return; }
  let success = 0, failed = 0;
  for (const classId of classIds) {
    try {
      const data = { class_id: classId, name, amount, period, due_date, description };
      const res = await api('/api/payments/obligations', { method: 'POST', body: JSON.stringify(data) });
      if (res?.ok) success++; else failed++;
    } catch { failed++; }
  }
  closeModal();
  if (failed === 0) { showToast(classIds.length > 1 ? `${success} obligations ajoutées` : 'Obligation ajoutée'); loadFeeStructure(); }
  else if (success === 0) { showToast('Erreur lors de l\'ajout', 'error'); }
  else { showToast(`${success} ajoutée(s), ${failed} échouée(s)`, 'error'); loadFeeStructure(); }
}

async function deleteObligation(id) {
  if (!confirm('Supprimer cette obligation ?')) return;
  try {
    const res = await api(`/api/payments/obligations/${id}`, { method: 'DELETE' });
    if (res?.ok) { showToast('Obligation supprimée'); loadFeeStructure(); }
    else { showToast('Impossible de supprimer', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

function showAutoGenerateObligations() {
  showModal('Génération automatique des obligations', `
    <div class="modal-form">
      <div style="background:var(--yiriba-ivoire);border-radius:8px;padding:16px;margin-bottom:16px">
        <div style="font-size:13px;color:var(--yiriba-text-secondaire);margin-bottom:8px"><i class="fas fa-info-circle" style="margin-right:6px"></i>Cette fonction génère automatiquement des obligations à partir des frais configurés dans chaque classe.</div>
        <div style="font-size:12px;color:var(--yiriba-text-secondaire)">• Inscription si non encore facturée<br>• Scolarité annuelle divisée par trimestres</div>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="autoGenerateAllObligations()"><i class="fas fa-magic"></i> Générer</button>
      </div>
    </div>
  `);
}

function showAutoGenerateForClass(classId, className, enrollmentFee, annualTuition) {
  showModal(`Auto-générer pour ${className}`, `
    <div class="modal-form">
      <div style="background:var(--yiriba-ivoire);border-radius:8px;padding:16px;margin-bottom:16px">
        <div style="font-size:13px;color:var(--yiriba-text-secondaire);margin-bottom:8px"><i class="fas fa-info-circle" style="margin-right:6px"></i>Générer des obligations pour <strong>${className}</strong></div>
        <div style="font-size:12px;color:var(--yiriba-text-secondaire)">• Inscription: ${enrollmentFee.toLocaleString('fr-FR')} FCFA<br>• Scolarité annuelle: ${annualTuition.toLocaleString('fr-FR')} FCFA → ${Math.round(annualTuition/3).toLocaleString('fr-FR')} FCFA/trimestre</div>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="autoGenerateForClass(${classId}, ${enrollmentFee}, ${annualTuition})"><i class="fas fa-magic"></i> Générer</button>
      </div>
    </div>
  `);
}

async function autoGenerateAllObligations() {
  try {
    const clRes = await api('/api/classes?per_page=200');
    if (!clRes?.ok) { showToast('Erreur chargement classes', 'error'); return; }
    const classes = (await clRes.json()).classes || [];
    let created = 0;
    for (const cl of classes) {
      const ef = cl.enrollment_fee || 0;
      const at = cl.annual_tuition || 0;
      if (ef > 0) {
        await api('/api/payments/obligations', { method: 'POST', body: JSON.stringify({
          class_id: cl.id, name: `Frais d'inscription - ${escapeHtml(cl.name)}`, amount: ef, period: 'inscription'
        })});
        created++;
      }
      if (at > 0) {
        const trimester = Math.round(at / 3);
        for (let t = 1; t <= 3; t++) {
          await api('/api/payments/obligations', { method: 'POST', body: JSON.stringify({
            class_id: cl.id, name: `Scolarité T${t} - ${escapeHtml(cl.name)}`, amount: t === 3 ? at - (trimester * 2) : trimester, period: `T${t}`
          })});
          created++;
        }
      }
    }
    closeModal();
    showToast(`${created} obligation(s) générée(s)`);
    loadFeeStructure();
  } catch { showToast('Erreur génération', 'error'); }
}

async function autoGenerateForClass(classId, enrollmentFee, annualTuition) {
  try {
    let created = 0;
    if (enrollmentFee > 0) {
      await api('/api/payments/obligations', { method: 'POST', body: JSON.stringify({
        class_id: classId, name: 'Frais d\'inscription', amount: enrollmentFee, period: 'inscription'
      })});
      created++;
    }
    if (annualTuition > 0) {
      const trimester = Math.round(annualTuition / 3);
      for (let t = 1; t <= 3; t++) {
        await api('/api/payments/obligations', { method: 'POST', body: JSON.stringify({
          class_id: classId, name: `Scolarité T${t}`, amount: t === 3 ? annualTuition - (trimester * 2) : trimester, period: `T${t}`
        })});
        created++;
      }
    }
    closeModal();
    showToast(`${created} obligation(s) générée(s)`);
    loadFeeStructure();
  } catch { showToast('Erreur génération', 'error'); }
}
function editTeacher(id, first, last, email) {
  showModal('Modifier l\'enseignant', `<div class="modal-form"><div class="form-row"><div class="form-group"><label>Prénom</label><input id="tch-first" value="${first}" required></div><div class="form-group"><label>Nom</label><input id="tch-last" value="${last}" required></div></div><div class="form-group"><label>Email</label><input id="tch-email" type="email" value="${email}" required></div><div class="modal-footer"><button class="btn-secondary" onclick="closeModal()">Annuler</button><button class="btn-add" onclick="submitEditTeacher(${id})"><i class="fas fa-check"></i> Enregistrer</button></div></div>`);
}
async function submitEditTeacher(id) {
  const data = {
    first_name: document.getElementById('tch-first').value.trim(),
    last_name: document.getElementById('tch-last').value.trim(),
    email: document.getElementById('tch-email').value.trim(),
  };
  try {
    const res = await api(`/api/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
    if (res?.ok) { closeModal(); showToast('Enseignant mis à jour'); loadTeachers(); }
    else { showToast('Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

/* ==============================================================
   MODULE PARENTS
   ============================================================== */
async function loadParents() {
  const c = document.getElementById('main-content');
  let users = [];
  try { const r = await api('/api/admin/users?per_page=100'); if (r?.ok) users = (await r.json()).users || []; } catch {}
  const parents = users.filter(u => (u.role_type||'').toLowerCase() === 'parent');
  c.innerHTML = `
    <div class="welcome"><h1>Parents / Tuteurs</h1><p>Gérez les responsables légaux associés aux élèves.</p></div>
    <div class="indicator-row"><div class="indicator-card hero"><div class="indicator-icon"><i class="fas fa-users"></i></div><div class="indicator-info"><h4>Total</h4><div class="indicator-val">${parents.length}</div><div class="indicator-sub">Parents enregistrés</div></div></div></div>
    ${parents.length > 0 ? `<div class="yiriba-table-wrap"><table class="yiriba-table"><thead><tr><th>Nom</th><th>Email</th><th>Statut</th></tr></thead><tbody>${parents.map(p => `<tr><td style="font-weight:600">${p.first_name} ${p.last_name}</td><td>${p.email}</td><td><span class="badge badge-active"><span class="badge-dot"></span>${p.status}</span></td></tr>`).join('')}</tbody></table></div>` : `<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-users"></i></div><h4>Aucun parent enregistré</h4><p>Les parents seront ajoutés lors de l'inscription des élèves.</p></div></div>`}
  `;
}

/* ==============================================================
   MODULE PASSAGE DE CLASSE
   ============================================================== */

let _promoState = { sourceClass: '', sourceYear: '', targetYear: '', students: [], decisions: {}, avgThreshold: 10 };

async function loadPromotion() {
  const c = document.getElementById('main-content');
  let classes = [], years = [];
  try {
    const [clRes, yRes] = await Promise.all([api('/api/classes?per_page=200'), api('/api/academic-years')]);
    if (clRes?.ok) classes = (await clRes.json()).classes || [];
    if (yRes?.ok) years = (await yRes.json()).academic_years || [];
  } catch {}
  const yearNames = [...new Set(classes.map(cl => cl.academic_year).filter(Boolean))]
    .concat(years.map(y => y.name || y))
    .filter((v, i, a) => a.indexOf(v) === i);
  _promoState = { sourceClass: '', sourceYear: '', targetYear: '', students: [], decisions: {}, avgThreshold: 10 };

  c.innerHTML = `
    <div class="welcome"><h1>Passage de classe</h1><p>Faites passer vos élèves vers l'année scolaire suivante en conservant tout leur historique.</p></div>
    <div class="card section-card" style="margin-bottom:16px">
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px">
        <div class="form-group"><label>Année scolaire actuelle *</label>
          <select id="promo-year" onchange="promoOnYearChange()">
            <option value="">— Choisir —</option>
            ${yearNames.map(y => `<option value="${y}">${y}</option>`).join('')}
          </select></div>
        <div class="form-group"><label>Classe d'origine *</label>
          <select id="promo-class" onchange="promoOnClassChange()" disabled>
            <option value="">— Choisir d'abord l'année —</option>
          </select></div>
        <div class="form-group"><label>Année suivante</label>
          <input id="promo-next-year" readonly placeholder="Auto"></div>
        <div class="form-group"><label>Seuil de moyenne (proposition)</label>
          <input id="promo-threshold" type="number" value="10" min="0" max="20" step="0.5" onchange="promoApplyAutoRules()">
          <div style="font-size:11px;color:var(--texte-secondaire);margin-top:2px">≥ seuil → « Passe » (proposition modifiable)</div></div>
      </div>
    </div>
    <div id="promo-students-zone"></div>
    <div id="promo-summary-zone"></div>
  `;
}

function promoOnYearChange() {
  const year = document.getElementById('promo-year').value;
  const classSel = document.getElementById('promo-class');
  const nextInput = document.getElementById('promo-next-year');
  if (!year) { classSel.disabled = true; classSel.innerHTML = '<option value="">— Choisir d\'abord l\'année —</option>'; nextInput.value = ''; return; }
  const start = parseInt(year.split('-')[0]);
  nextInput.value = `${start + 1}-${start + 2}`;
  _promoState.sourceYear = year;
  _promoState.targetYear = nextInput.value;
  classSel.disabled = false;
  classSel.innerHTML = '<option value="">— Choisir une classe —</option>';
  _promoState._classes = null;
  api('/api/classes?per_page=200').then(r => r?.ok ? r.json() : null).then(j => {
    const classes = ((j || {}).classes || []).filter(cl => cl.academic_year === year);
    _promoState._classes = classes;
    classes.forEach(cl => { classSel.insertAdjacentHTML('beforeend', `<option value="${cl.id}">${escapeHtml(cl.name)} (${cl.academic_year})</option>`); });
  });
}

async function promoOnClassChange() {
  const classId = document.getElementById('promo-class').value;
  _promoState.sourceClass = classId;
  _promoState.students = [];
  _promoState.decisions = {};
  document.getElementById('promo-students-zone').innerHTML = '';
  document.getElementById('promo-summary-zone').innerHTML = '';
  if (!classId) return;
  const zone = document.getElementById('promo-students-zone');
  zone.innerHTML = '<div class="empty"><i class="fas fa-spinner fa-spin"></i><p>Chargement des élèves…</p></div>';
  const res = await api(`/api/promotion/students?class_id=${classId}&academic_year=${encodeURIComponent(_promoState.sourceYear)}`);
  if (!res?.ok) { const e = await res.json().catch(() => ({})); zone.innerHTML = `<div class="empty"><i class="fas fa-circle-exclamation"></i><p>${parseError(e) || 'Erreur'}</p></div>`; return; }
  const data = await res.json();
  _promoState.students = data.students || [];
  promoRenderStudents();
}

function promoSuggestedFor(s) {
  if (s.suggested_decision) return s.suggested_decision;
  return 'review';
}

function promoApplyAutoRules() {
  const threshold = parseFloat(document.getElementById('promo-threshold')?.value || '10');
  _promoState.avgThreshold = threshold;
  _promoState.students.forEach(s => {
    if (s.annual_average != null) {
      _promoState.decisions[s.student_id] = s.annual_average >= threshold ? 'pass' : 'repeat';
    }
  });
  promoRenderStudents();
}

function promoRenderStudents() {
  const zone = document.getElementById('promo-students-zone');
  const students = _promoState.students;
  if (!students.length) { zone.innerHTML = '<div class="empty"><i class="fas fa-user-graduate"></i><h4>Aucun élève</h4><p>Cette classe ne contient aucun élève éligible au passage.</p></div>'; return; }

  const decLabel = { pass: ['Passe', 'badge-active'], repeat: ['Redouble', 'badge-warning'], review: ['À revoir', 'badge-info'] };
  const decColor = { pass: 'var(--yiriba-vert)', repeat: '#b45309', review: 'var(--yiriba-info, #2563eb)' };

  let html = `<div class="card section-card">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px">
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn-secondary" onclick="promoSelectAll()">Sélectionner tous</button>
        <button class="btn-secondary" onclick="promoDeselectAll()">Désélectionner tous</button>
        <button class="btn-secondary" onclick="promoApplyAutoRules()"><i class="fas fa-wand-magic-sparkles"></i> Proposer selon la moyenne</button>
      </div>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <select id="promo-filter-decision" onchange="promoApplyBulk('decision')" style="padding:8px;border:1px solid var(--border);border-radius:8px;font-size:13px">
          <option value="">— Décision en masse —</option>
          <option value="pass">Faire passer la sélection</option>
          <option value="repeat">Faire redoubler la sélection</option>
          <option value="review">À revoir (sélection)</option>
        </select>
      </div>
    </div>
    <div style="overflow-x:auto">
    <table class="yiriba-table">
      <thead><tr>
        <th><input type="checkbox" id="promo-check-all" onchange="promoToggleAll(this.checked)" style="width:auto"></th>
        <th>Matricule</th><th>Élève</th><th>Sexe</th><th>Moyenne annuelle</th><th>Décision</th><th>Classe de destination</th>
      </tr></thead><tbody>`;

  students.forEach(s => {
    const dec = _promoState.decisions[s.student_id] || 'review';
    const avgBadge = s.annual_average != null
      ? `<span class="badge ${s.annual_average >= 10 ? 'badge-active' : 'badge-warning'}">${s.annual_average.toFixed(2)}/20</span>`
      : '<span style="color:var(--texte-secondaire);font-size:12px">Pas de notes</span>';
    const needsTarget = dec !== 'review';
    html += `<tr>
      <td><input type="checkbox" class="promo-check" data-sid="${s.student_id}" ${dec !== 'review' ? 'checked' : ''} onchange="promoToggleStudent(${s.student_id}, this.checked)" style="width:auto"></td>
      <td><span class="matricule">${s.matricule || '—'}</span></td>
      <td style="font-weight:600">${s.last_name} ${s.first_name}</td>
      <td>${s.gender === 'F' ? 'F' : 'M'}</td>
      <td>${avgBadge}</td>
      <td><select onchange="promoSetDecision(${s.student_id}, this.value)" style="padding:6px;border:1px solid var(--border);border-radius:6px;font-size:13px;color:${decColor[dec]}">
        ${Object.entries(decLabel).map(([k, [lbl]]) => `<option value="${k}" ${dec === k ? 'selected' : ''}>${lbl}</option>`).join('')}
      </select></td>
      <td><select id="promo-target-${s.student_id}" ${needsTarget ? '' : 'disabled'} onchange="promoMaybeRefreshSummary()" style="padding:6px;border:1px solid var(--border);border-radius:6px;font-size:13px">
        <option value="">— Choisir —</option>
        ${(_promoState._destClasses || []).map(cl => `<option value="${cl.id}">${escapeHtml(cl.name)}</option>`).join('')}
      </select></td>
    </tr>`;
  });

  html += `</tbody></table></div></div>`;
  zone.innerHTML = html;
  promoLoadDestClasses();
  promoMaybeRefreshSummary();
}

async function promoLoadDestClasses() {
  if (_promoState._destClasses) return;
  const res = await api(`/api/promotion/destination-classes?next_year=${encodeURIComponent(_promoState.targetYear)}`);
  _promoState._destClasses = res?.ok ? (await res.json()).classes || [] : [];
  if (!_promoState._destClasses.length) {
    const warn = document.createElement('div');
    warn.className = 'card section-card'; warn.style.marginTop = '10px';
    warn.innerHTML = '<div style="display:flex;gap:10px;align-items:center;color:#b45309"><i class="fas fa-triangle-exclamation"></i><span>Aucune classe n&rsquo;existe encore pour ' + escapeHtml(_promoState.targetYear) + '. <a href="#" onclick="loadPage(\'classes\');return false" style="color:var(--yiriba-vert);font-weight:600">Créer les classes de la nouvelle année</a> puis revenir ici.</span></div>';
    document.getElementById('promo-students-zone').after(warn);
  }
  // re-render target selects
  document.querySelectorAll('[id^="promo-target-"]').forEach(sel => {
    const sid = sel.id.replace('promo-target-', '');
    sel.innerHTML = '<option value="">— Choisir —</option>' + _promoState._destClasses.map(cl => `<option value="${cl.id}">${escapeHtml(cl.name)}</option>`).join('');
  });
}

function promoToggleStudent(sid, checked) {
  if (checked) {
    if (!_promoState.decisions[sid]) _promoState.decisions[sid] = 'review';
  } else {
    delete _promoState.decisions[sid];
  }
  promoMaybeRefreshSummary();
}

function promoToggleAll(checked) {
  _promoState.students.forEach(s => {
    if (checked) { if (!_promoState.decisions[s.student_id]) _promoState.decisions[s.student_id] = 'review'; }
    else delete _promoState.decisions[s.student_id];
  });
  document.querySelectorAll('.promo-check').forEach(cb => { cb.checked = checked; });
  promoMaybeRefreshSummary();
}

function promoSelectAll() { const cb = document.getElementById('promo-check-all'); cb.checked = true; promoToggleAll(true); }
function promoDeselectAll() { const cb = document.getElementById('promo-check-all'); cb.checked = false; promoToggleAll(false); }

function promoSetDecision(sid, decision) {
  _promoState.decisions[sid] = decision;
  const targetSel = document.getElementById('promo-target-' + sid);
  if (targetSel) targetSel.disabled = (decision === 'review');
  promoMaybeRefreshSummary();
}

function promoApplyBulk(mode) {
  const val = document.getElementById('promo-filter-decision').value;
  if (!val) return;
  document.querySelectorAll('.promo-check:checked').forEach(cb => {
    const sid = parseInt(cb.dataset.sid);
    _promoState.decisions[sid] = val;
    const sel = document.querySelector(`#promo-students-zone tr input[data-sid="${sid}"]`)?.closest('tr')?.querySelector('td:nth-child(6) select');
    if (sel) sel.value = val;
    const targetSel = document.getElementById('promo-target-' + sid);
    if (targetSel) targetSel.disabled = (val === 'review');
  });
  document.getElementById('promo-filter-decision').value = '';
  promoMaybeRefreshSummary();
}

function promoMaybeRefreshSummary() {
  const zone = document.getElementById('promo-summary-zone');
  const entries = Object.entries(_promoState.decisions);
  if (!entries.length) { zone.innerHTML = ''; return; }
  const counts = { pass: 0, repeat: 0, review: 0 };
  let missingTarget = 0;
  entries.forEach(([sid, dec]) => {
    counts[dec] = (counts[dec] || 0) + 1;
    if (dec !== 'review') {
      const t = document.getElementById('promo-target-' + sid);
      if (!t || !t.value) missingTarget++;
    }
  });
  zone.innerHTML = `
    <div class="card section-card" style="border:2px solid var(--yiriba-vert)">
      <h3 style="font-size:15px;margin-bottom:10px"><i class="fas fa-clipboard-check" style="color:var(--yiriba-vert);margin-right:6px"></i>Récapitulatif avant validation</h3>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:12px">
        <div style="padding:12px;background:#f0faf4;border-radius:8px;text-align:center"><div style="font-size:22px;font-weight:800;color:var(--yiriba-vert)">${counts.pass}</div><div style="font-size:12px;color:var(--texte-secondaire)">Passent</div></div>
        <div style="padding:12px;background:#fffbe6;border-radius:8px;text-align:center"><div style="font-size:22px;font-weight:800;color:#b45309">${counts.repeat}</div><div style="font-size:12px;color:var(--texte-secondaire)">Redoublent</div></div>
        <div style="padding:12px;background:#eef2ff;border-radius:8px;text-align:center"><div style="font-size:22px;font-weight:800;color:var(--yiriba-info, #2563eb)">${counts.review}</div><div style="font-size:12px;color:var(--texte-secondaire)">À revoir</div></div>
      </div>
      ${missingTarget > 0 ? `<div style="color:#b45309;font-size:13px;margin-bottom:10px"><i class="fas fa-triangle-exclamation"></i> ${missingTarget} élève(s) sélectionné(s) sans classe de destination.</div>` : ''}
      <div style="font-size:12px;color:var(--texte-secondaire);margin-bottom:12px">Année ${escapeHtml(_promoState.sourceYear)} → ${escapeHtml(_promoState.targetYear)} · Les anciennes affectations sont conservées dans l'historique.</div>
      <button class="btn-add" ${missingTarget > 0 ? 'disabled' : ''} onclick="promoValidate()"><i class="fas fa-check"></i> Valider le passage (${entries.length} élèves)</button>
    </div>`;
}

async function promoValidate() {
  const entries = Object.entries(_promoState.decisions);
  if (!entries.length) { showToast('Aucun élève sélectionné', 'error'); return; }
  if (!confirm(`Confirmer le passage de ${entries.length} élève(s) vers ${_promoState.targetYear} ?\nCette opération conserve tout l'historique scolaire.`)) return;
  const decisions = entries.map(([sid, dec]) => ({
    student_id: parseInt(sid),
    decision: dec,
    target_class_id: dec !== 'review' ? parseInt(document.getElementById('promo-target-' + sid)?.value || '') || null : null,
  })).filter(d => d.decision === 'review' || d.target_class_id);
  if (!decisions.length) { showToast('Aucune classe de destination renseignée pour les élèves passants/redoublants', 'error'); return; }
  try {
    const res = await api('/api/promotion/apply', { method: 'POST', body: JSON.stringify({
      source_class_id: parseInt(_promoState.sourceClass),
      source_year: _promoState.sourceYear,
      target_year: _promoState.targetYear,
      decisions,
    }) });
    if (!res?.ok) { const e = await res.json().catch(() => ({})); showToast(parseError(e) || 'Erreur', 'error'); return; }
    const d = await res.json();
    const s = d.summary || {};
    let msg = `Passage validé : ${s.passed || 0} passé(s), ${s.repeated || 0} redoublant(s), ${s.review || 0} à revoir.`;
    if ((s.errors || []).length) msg += ` ${s.errors.length} erreur(s) : ` + s.errors.map(e => `élève ${e.student_id} — ${e.detail}`).join('; ');
    showToast(msg, (s.errors || []).length ? 'info' : 'success');
    loadPromotion();
  } catch { showToast('Erreur réseau', 'error'); }
}

/* ==============================================================
   PRÉPARER L'ANNÉE SUIVANTE
   ============================================================== */
let _nyState = { year: '', data: null, selected: {}, decisions: {} };

async function loadNextYearPrep() {
  const c = document.getElementById('main-content');
  c.innerHTML = '<div style="text-align:center;padding:40px"><i class="fas fa-spinner fa-spin" style="font-size:24px;color:var(--yiriba-vert)"></i></div>';
  let years = [];
  try { const r = await api('/api/academic-years'); if (r?.ok) years = (await r.json()).academic_years || []; } catch {}
  const current = years.find(y => y.is_current) || years.find(y => y.status === 'active') || years[0];
  _nyState = { year: current?.name || '', data: null, selected: {}, decisions: {} };
  c.innerHTML = `
    <div class="welcome"><h1>Préparer l'année suivante</h1><p>Vue d'ensemble des décisions de passage de toutes les classes, puis affectation en masse des élèves réinscrits.</p></div>
    <div class="card section-card" style="margin-bottom:16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap">
      <div class="form-group" style="margin:0"><label>Année scolaire actuelle</label>
        <select id="ny-year" onchange="nyOnYearChange()" style="min-width:160px">
          ${years.map(y => `<option value="${y.name}" ${y.name === _nyState.year ? 'selected' : ''}>${y.name}${y.is_current ? ' (en cours)' : ''}</option>`).join('')}
        </select></div>
      <button class="btn-secondary" onclick="nyLoad()"><i class="fas fa-rotate"></i> Actualiser</button>
      <div style="flex:1"></div>
      <a class="btn-add" href="#" onclick="loadPage('promotion');return false"><i class="fas fa-graduation-cap"></i> Passage par classe</a>
    </div>
    <div id="ny-content"><div class="empty"><i class="fas fa-spinner fa-spin"></i><p>Chargement…</p></div></div>
  `;
  if (_nyState.year) nyLoad();
  else document.getElementById('ny-content').innerHTML = '<div class="empty"><i class="fas fa-calendar-xmark"></i><h4>Aucune année scolaire</h4><p>Créez d\'abord une année scolaire.</p></div>';
}

async function nyOnYearChange() { _nyState.year = document.getElementById('ny-year').value; nyLoad(); }

async function nyLoad() {
  const zone = document.getElementById('ny-content');
  zone.innerHTML = '<div class="empty"><i class="fas fa-spinner fa-spin"></i><p>Chargement…</p></div>';
  _nyState.selected = {}; _nyState.decisions = {}; _nyState.data = null;
  const res = await api(`/api/promotion/next-year-preparation?source_year=${encodeURIComponent(_nyState.year)}`);
  if (!res?.ok) { const e = await res.json().catch(() => ({})); zone.innerHTML = `<div class="empty"><i class="fas fa-circle-exclamation"></i><p>${parseError(e) || 'Erreur'}</p></div>`; return; }
  _nyState.data = await res.json();
  nyRender();
}

function nyRender() {
  const zone = document.getElementById('ny-content');
  const d = _nyState.data;
  if (!d) return;
  const s = d.stats || {};
  const hasDest = (d.dest_classes || []).length > 0;
  const statCard = (val, lbl, color, bg, icon) => `
    <div class="indicator-card" style="border-top:3px solid ${color}"><div class="indicator-icon" style="color:${color}"><i class="fas ${icon}"></i></div>
      <div class="indicator-info"><div class="indicator-val" style="font-size:22px">${val}</div><div class="indicator-sub">${lbl}</div></div></div>`;
  zone.innerHTML = `
    ${!d.next_year_registered ? `<div class="card section-card" style="margin-bottom:14px;display:flex;gap:10px;align-items:center;color:#b45309;background:#fffbe6">
      <i class="fas fa-triangle-exclamation"></i>
      <span>L'année scolaire <b>${escapeHtml(d.next_year)}</b> n'existe pas encore.</span>
      <button class="btn-sm-green" onclick="nyCreateNextYear()">Créer ${escapeHtml(d.next_year)}</button>
    </div>` : ''}
    ${!hasDest ? `<div class="card section-card" style="margin-bottom:14px;display:flex;gap:10px;align-items:center;color:#b45309;background:#fffbe6">
      <i class="fas fa-school"></i>
      <span>Aucune classe créée pour ${escapeHtml(d.next_year)}.</span>
      <a href="#" onclick="loadPage('classes');return false" style="color:var(--yiriba-vert);font-weight:600">Créer les classes</a>
    </div>` : ''}
    <div class="indicator-row" style="margin-bottom:16px">
      ${statCard(d.total, 'Élèves concernés', 'var(--yiriba-vert)', '', 'fa-user-graduate')}
      ${statCard(s.pass || 0, 'Passent', 'var(--yiriba-vert)', '', 'fa-circle-check')}
      ${statCard(s.repeat || 0, 'Redoublent', '#b45309', '', 'fa-rotate-left')}
      ${statCard(s.unenrolled || 0, 'Non réinscrits', 'var(--yiriba-danger, #dc2626)', '', 'fa-user-slash')}
      ${statCard(s.review || 0, 'À revoir', 'var(--yiriba-bleu, #2563eb)', '', 'fa-eye')}
      ${statCard(s.undecided || 0, 'Sans décision', 'var(--yiriba-text-secondaire, #6b7280)', '', 'fa-circle-question')}
    </div>
    <div id="ny-table-zone">${nyRenderStudentTable()}</div>
  `;
}

function nyRenderStudentTable() {
  const d = _nyState.data;
  if (!d.students || !d.students.length) {
    return '<div class="card section-card"><div class="empty"><i class="fas fa-user-graduate"></i><h4>Aucun élève inscrit</h4><p>Aucun élève n\'est inscrit pour ' + escapeHtml(d.source_year) + '.</p></div></div>';
  }
  const decLabel = { pass: ['Passe', 'badge-active'], repeat: ['Redouble', 'badge-warning'], review: ['À revoir', 'badge-info'], unenrolled: ['Non réinscrit', 'badge-danger'], undecided: ['—', 'badge-inactive'] };
  const classes = [...new Set(d.students.map(x => x.class_name).filter(Boolean))];
  let html = `<div class="card section-card">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px">
      <h3 style="font-size:15px;margin:0"><i class="fas fa-users" style="color:var(--yiriba-vert);margin-right:6px"></i>Élèves & décisions</h3>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <select id="ny-filter-class" onchange="nyRenderStudentTable()" style="padding:8px;border:1px solid var(--border);border-radius:8px;font-size:13px">
          <option value="">Toutes les classes</option>
          ${classes.map(cl => `<option>${escapeHtml(cl)}</option>`).join('')}
        </select>
        <select id="ny-filter-decision" onchange="nyRenderStudentTable()" style="padding:8px;border:1px solid var(--border);border-radius:8px;font-size:13px">
          <option value="">Toutes les décisions</option>
          ${Object.entries(decLabel).filter(([k]) => k !== 'undecided').map(([k, [lbl]]) => `<option value="${k}">${lbl}</option>`).join('')}
          <option value="undecided">Sans décision</option>
        </select>
        <input id="ny-search" placeholder="Rechercher…" oninput="nyRenderStudentTable()" style="padding:8px;border:1px solid var(--border);border-radius:8px;font-size:13px;width:150px">
      </div>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
      <button class="btn-secondary" onclick="nySelectVisible(true)">Sélectionner les filtrés</button>
      <button class="btn-secondary" onclick="nySelectVisible(false)">Désélectionner tous</button>
      <select id="ny-bulk-decision" onchange="nyApplyBulk()" style="padding:8px;border:1px solid var(--border);border-radius:8px;font-size:13px">
        <option value="">— Décision en masse —</option>
        <option value="pass">Faire passer</option>
        <option value="repeat">Faire redoubler</option>
        <option value="unenrolled">Non réinscrit</option>
      </select>
      <button class="btn-add" onclick="nyOpenAssign()"><i class="fas fa-user-plus"></i> Affecter les sélectionnés</button>
    </div>
    <div style="overflow-x:auto">
    <table class="yiriba-table">
      <thead><tr><th></th><th>Matricule</th><th>Élève</th><th>Classe ${escapeHtml(d.source_year)}</th><th>Décision</th></tr></thead>
      <tbody>`;
  const fc = document.getElementById('ny-filter-class')?.value || '';
  const fd = document.getElementById('ny-filter-decision')?.value || '';
  const q = (document.getElementById('ny-search')?.value || '').toLowerCase();
  const rows = d.students.filter(x =>
    (!fc || x.class_name === fc) &&
    (!fd || (x.decision || 'undecided') === fd) &&
    (!q || `${x.last_name} ${x.first_name} ${x.matricule || ''}`.toLowerCase().includes(q))
  );
  rows.forEach(x => {
    const dec = x.decision || 'undecided';
    const [lbl, badge] = decLabel[dec] || decLabel.undecided;
    const checked = _nyState.selected[x.student_id] ? 'checked' : '';
    html += `<tr style="border-bottom:1px solid var(--border)">
      <td style="padding:8px 12px"><input type="checkbox" class="ny-check" data-sid="${x.student_id}" ${checked} onchange="nyToggle(${x.student_id}, this.checked)" style="width:auto"></td>
      <td style="padding:8px 12px"><span class="matricule">${x.matricule || '—'}</span></td>
      <td style="padding:8px 12px;font-weight:600">${escapeHtml(x.last_name)} ${escapeHtml(x.first_name)}</td>
      <td style="padding:8px 12px">${escapeHtml(x.class_name || '—')}</td>
      <td style="padding:8px 12px"><span class="badge ${badge}">${lbl}</span></td>
    </tr>`;
  });
  if (!rows.length) html += '<tr><td colspan="5" style="padding:24px;text-align:center;color:var(--texte-secondaire)">Aucun élève ne correspond aux filtres.</td></tr>';
  html += '</tbody></table></div></div>';
  // Mettre à jour la zone du tableau si on est appelé depuis un filtre (re-render partiel)
  const tableZone = document.getElementById('ny-table-zone');
  if (tableZone) { tableZone.innerHTML = html; }
  return html;
}

function nyToggle(sid, checked) {
  if (checked) _nyState.selected[sid] = true;
  else delete _nyState.selected[sid];
}

function nySelectVisible(checked) {
  document.querySelectorAll('.ny-check').forEach(cb => {
    const sid = parseInt(cb.dataset.sid);
    cb.checked = !!checked;
    if (checked) _nyState.selected[sid] = true;
    else delete _nyState.selected[sid];
  });
}

function nyApplyBulk() {
  const val = document.getElementById('ny-bulk-decision').value;
  if (!val) return;
  const sids = document.querySelectorAll('.ny-check:checked');
  if (!sids.length) { showToast('Sélectionnez d\'abord des élèves', 'error'); document.getElementById('ny-bulk-decision').value = ''; return; }
  const statusMap = { pass: 'passed', repeat: 'repeated', unenrolled: 'not_reenrolled' };
  _nyState.pendingBulk = { decision: val, sids: [...sids].map(cb => parseInt(cb.dataset.sid)) };
  document.getElementById('ny-bulk-decision').value = '';
  nyShowBulkConfirm();
}

function nyShowBulkConfirm() {
  const pb = _nyState.pendingBulk;
  const students = _nyState.data.students.filter(x => pb.sids.includes(x.student_id));
  const labels = { pass: 'Passe', repeat: 'Redouble', unenrolled: 'Non réinscrit' };
  showModal('Confirmer la décision en masse', `
    <p style="font-size:14px;margin-bottom:10px">Appliquer <b>« ${labels[pb.decision]} »</b> à <b>${pb.sids.length} élève(s)</b> ?</p>
    <div style="max-height:200px;overflow-y:auto;border:1px solid var(--border);border-radius:8px;padding:8px;font-size:13px;margin-bottom:14px">
      ${students.map(x => `${escapeHtml(x.last_name)} ${escapeHtml(x.first_name)} — ${escapeHtml(x.class_name || '')}`).join('<br>')}
    </div>
    ${pb.decision !== 'unenrolled' ? '<div style="font-size:12px;color:var(--texte-secondaire);margin-bottom:12px">La classe de destination sera choisie à l\'étape « Affecter les sélectionnés ».</div>' : '<div style="font-size:12px;color:var(--texte-secondaire);margin-bottom:12px">Ces élèves ne seront pas réinscrits dans ' + escapeHtml(_nyState.data.next_year) + '. Leur historique est conservé.</div>'}
    <div style="display:flex;gap:8px;justify-content:flex-end">
      <button class="btn-secondary" onclick="closeModal()">Annuler</button>
      <button class="btn-add" onclick="nyConfirmBulk()">Confirmer</button>
    </div>`);
}

async function nyConfirmBulk() {
  const pb = _nyState.pendingBulk;
  closeModal();
  try {
    // Regrouper par classe source (l'API exige une classe source valide)
    const byClass = {};
    pb.sids.forEach(sid => {
      const x = _nyState.data.students.find(s => s.student_id === sid);
      if (x && x.class_id) (byClass[x.class_id] = byClass[x.class_id] || []).push({ student_id: sid, decision: pb.decision, target_class_id: null });
    });
    let allErrors = [];
    let done = 0;
    for (const [clsId, decisions] of Object.entries(byClass)) {
      const res = await api('/api/promotion/apply', { method: 'POST', body: JSON.stringify({
        source_class_id: parseInt(clsId),
        source_year: _nyState.data.source_year,
        target_year: _nyState.data.next_year,
        decisions,
      }) });
      if (!res?.ok) { const e = await res.json().catch(() => ({})); allErrors.push(parseError(e) || 'Erreur'); continue; }
      const j = await res.json();
      const s = j.summary || {};
      done += (s.passed || 0) + (s.repeated || 0) + (s.review || 0) + (s.unenrolled || 0);
      (s.errors || []).forEach(err => allErrors.push(`élève ${err.student_id} — ${err.detail}`));
    }
    let msg = `${done} décision(s) enregistrée(s).`;
    if (allErrors.length) msg += ` ${allErrors.length} erreur(s) : ` + allErrors.slice(0, 3).join('; ');
    showToast(msg, allErrors.length ? 'info' : 'success');
    _nyState.pendingBulk = null;
    nyLoad();
  } catch { showToast('Erreur réseau', 'error'); }
}

async function nyCreateNextYear() {
  const d = _nyState.data;
  const start = parseInt(d.next_year.split('-')[0]);
  const res = await api(`/api/academic-years?name=${encodeURIComponent(d.next_year)}&start_date=${start}-09-01&end_date=${start + 1}-06-30`, { method: 'POST' });
  if (res?.ok) { showToast(`Année ${d.next_year} créée`); nyLoad(); }
  else { const e = await res.json().catch(() => ({})); showToast(parseError(e) || 'Erreur', 'error'); }
}

function nyOpenAssign() {
  const d = _nyState.data;
  const sids = Object.keys(_nyState.selected).map(Number);
  if (!sids.length) { showToast('Sélectionnez d\'abord des élèves', 'error'); return; }
  if (!(d.dest_classes || []).length) { showToast('Créez d\'abord les classes de ' + d.next_year, 'error'); return; }
  const eligible = d.students.filter(x => sids.includes(x.student_id) && (x.decision === 'pass' || x.decision === 'repeat'));
  if (!eligible.length) { showToast('Les élèves sélectionnés n\'ont pas de décision « Passe » ou « Redouble »', 'error'); return; }
  showModal('Affecter les élèves sélectionnés', `
    <div style="display:flex;flex-direction:column;gap:12px">
      <div class="form-group"><label>Classe de destination (${escapeHtml(d.next_year)}) *</label>
        <select id="ny-target-class" style="width:100%">
          ${d.dest_classes.map(cl => `<option value="${cl.id}">${escapeHtml(cl.name)}</option>`).join('')}
        </select></div>
      <div style="font-size:12px;color:var(--texte-secondaire)">${eligible.length} élève(s) avec décision Passe/Redouble sur ${sids.length} sélectionné(s).</div>
      <div style="max-height:180px;overflow-y:auto;border:1px solid var(--border);border-radius:8px;padding:8px;font-size:13px">
        ${eligible.map(x => `${escapeHtml(x.last_name)} ${escapeHtml(x.first_name)} — ${escapeHtml(x.class_name || '')} (${x.decision === 'pass' ? 'Passe' : 'Redouble'})`).join('<br>')}
      </div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="btn-secondary" onclick="closeModal()">Retour</button>
        <button class="btn-add" onclick="nyConfirmAssign()">Confirmer les affectations</button>
      </div>
    </div>`);
}

async function nyConfirmAssign() {
  const targetClassId = parseInt(document.getElementById('ny-target-class')?.value || '');
  if (!targetClassId) { showToast('Choisissez une classe de destination', 'error'); return; }
  const d = _nyState.data;
  const sids = Object.keys(_nyState.selected).map(Number);
  const eligible = d.students.filter(x => sids.includes(x.student_id) && (x.decision === 'pass' || x.decision === 'repeat'));
  if (!confirm(`Confirmer l'affectation de ${eligible.length} élève(s) pour ${d.next_year} ?\nLes inscriptions actuelles sont conservées dans l'historique.`)) return;
  closeModal();
  try {
    // Affectation par classe source (l'API exige une classe source valide) : regrouper par classe
    const byClass = {};
    eligible.forEach(x => { (byClass[x.class_id] = byClass[x.class_id] || []).push(x); });
    let allErrors = [];
    let counts = { passed: 0, repeated: 0, review: 0, unenrolled: 0 };
    for (const [clsId, students] of Object.entries(byClass)) {
      const res = await api('/api/promotion/apply', { method: 'POST', body: JSON.stringify({
        source_class_id: parseInt(clsId),
        source_year: d.source_year,
        target_year: d.next_year,
        decisions: students.map(x => ({ student_id: x.student_id, decision: x.decision, target_class_id: targetClassId })),
      }) });
      if (!res?.ok) { const e = await res.json().catch(() => ({})); allErrors.push(parseError(e) || 'Erreur'); continue; }
      const j = await res.json();
      const s = j.summary || {};
      counts.passed += s.passed || 0; counts.repeated += s.repeated || 0; counts.review += s.review || 0; counts.unenrolled += s.unenrolled || 0;
      (s.errors || []).forEach(err => allErrors.push(`élève ${err.student_id} — ${err.detail}`));
    }
    let msg = `Affectations : ${counts.passed} passé(s), ${counts.repeated} redoublant(s).`;
    if (allErrors.length) msg += ` ${allErrors.length} erreur(s) : ` + allErrors.slice(0, 3).join('; ');
    showToast(msg, allErrors.length ? 'info' : 'success');
    nyLoad();
  } catch { showToast('Erreur réseau', 'error'); }
}

/* ==============================================================
   MODULE UTILISATEURS
   ============================================================== */
async function loadUsers() {
  const c = document.getElementById('main-content');
  let users = [], total = 0;
  try { const r = await api('/api/admin/users?per_page=200'); if (r?.ok) { const j = await r.json(); users = j.users || []; total = j.total || 0; } } catch {}
  const byRole = {};
  users.forEach(u => { const rt = u.role_type || 'other'; byRole[rt] = (byRole[rt]||0) + 1; });
  const rc = {admin:'badge-danger',teacher:'badge-info',educator:'badge-info',secretary:'badge-info',comptable:'badge-warning',parent:'badge-active',student:'badge-inactive'};
  const rn = {admin:'Admin',teacher:'Enseignant',educator:'Éducateur',secretary:'Secrétaire',comptable:'Comptable',parent:'Parent',student:'Élève'};
  const sm = {ACTIVE:['Actif','badge-active'], active:['Actif','badge-active'], PENDING:['En attente','badge-warning'], pending:['En attente','badge-warning'], SUSPENDED:['Suspendu','badge-danger'], suspended:['Suspendu','badge-danger'], INACTIVE:['Inactif','badge-inactive'], inactive:['Inactif','badge-inactive']};
  c.innerHTML = `
    <div class="welcome"><h1>Utilisateurs & Accès</h1><p>Gérez les comptes et les droits d'accès de votre établissement.</p></div>
    <div class="indicator-row"><div class="indicator-card hero"><div class="indicator-icon"><i class="fas fa-users-gear"></i></div><div class="indicator-info"><h4>Total</h4><div class="indicator-val">${total}</div><div class="indicator-sub">Utilisateurs</div></div></div>
    <div class="indicator-card"><div class="indicator-icon"><i class="fas fa-user-check"></i></div><div class="indicator-info"><h4>Actifs</h4><div class="indicator-val">${users.filter(u=>(u.status||'').toLowerCase()==='active').length}</div><div class="indicator-sub">En activité</div></div></div>
    <div class="indicator-card"><div class="indicator-icon" style="color:var(--yiriba-jaune)"><i class="fas fa-user-clock"></i></div><div class="indicator-info"><h4>En attente</h4><div class="indicator-val">${users.filter(u=>(u.status||'').toLowerCase()==='pending').length}</div><div class="indicator-sub">À valider</div></div></div>
    <div class="indicator-card"><div class="indicator-icon" style="color:var(--yiriba-rouge)"><i class="fas fa-user-xmark"></i></div><div class="indicator-info"><h4>Suspendus</h4><div class="indicator-val">${users.filter(u=>(u.status||'').toLowerCase()==='suspended').length}</div><div class="indicator-sub">Inactifs</div></div></div></div>
    <div class="page-toolbar"><div></div><button class="btn-add" onclick="showAddUserModal()"><i class="fas fa-plus"></i> Ajouter un utilisateur</button></div>
    ${users.length > 0 ? `<div class="yiriba-table-wrap"><table class="yiriba-table"><thead><tr><th>Nom</th><th>Email / Identifiant</th><th>Rôle</th><th>Statut</th><th style="text-align:right">Actions</th></tr></thead><tbody>${users.map(u => {
      const [sl,sc] = sm[u.status] || sm[(u.status||'').toLowerCase()] || [u.status,'badge-inactive'];
      const loginId = u.username || u.email || '—';
      return `<tr><td style="font-weight:600">${u.first_name} ${u.last_name}</td><td><div>${u.email || '—'}</div>${u.username ? '<div style="font-size:11px;color:var(--yiriba-vert);font-weight:600">'+u.username+'</div>' : ''}</td><td><span class="badge ${rc[u.role_type]||'badge-inactive'}">${rn[u.role_type]||u.role_type}</span></td><td><span class="badge ${sc}"><span class="badge-dot"></span>${sl}</span></td><td><div class="table-actions" style="justify-content:flex-end">${(u.status||'').toLowerCase()==='pending'?`<button title="Activer" onclick="activateUser(${u.id})"><i class="fas fa-check"></i></button>`:''}<button title="Voir" onclick="viewUser(${u.id})"><i class="fas fa-eye"></i></button><button title="Modifier" onclick="editUserRole(${u.id},'${u.first_name}','${u.last_name}')"><i class="fas fa-pen"></i></button>${(u.status||'').toLowerCase()!=='suspended'?`<button title="Suspendre" onclick="suspendUser(${u.id})"><i class="fas fa-ban"></i></button>`:''}</div></td></tr>`;
    }).join('')}</tbody></table></div>` : `<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-users-gear"></i></div><h4>Aucun utilisateur</h4><p>Commencez par ajouter des utilisateurs à votre établissement.</p><span class="link" onclick="showAddUserModal()"><i class="fas fa-plus"></i> Ajouter un utilisateur →</span></div></div>`}
  `;
}
async function activateUser(id) {
  try {
    const res = await api(`/api/admin/users/${id}/validate`, { method: 'POST' });
    if (res?.ok || res?.status === 200) { showToast('Compte activé'); loadUsers(); }
    else { showToast('Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}
async function suspendUser(id) {
  if (!confirm('Suspendre ce compte ? Il ne pourra plus se connecter.')) return;
  try {
    const res = await api(`/api/admin/users/${id}/suspend`, { method: 'POST' });
    if (res?.ok || res?.status === 200) { showToast('Compte suspendu'); loadUsers(); }
    else { showToast('Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}
async function viewUser(id) {
  showToast('Fiche utilisateur en cours de développement', 'info');
}
function editUserRole(id, first, last) {
  showModal('Modifier l\'utilisateur', `<div class="modal-form"><div class="form-row"><div class="form-group"><label>Prénom</label><input id="u-first" value="${first}" required></div><div class="form-group"><label>Nom</label><input id="u-last" value="${last}" required></div></div><div class="form-group"><label>Nouveau rôle</label><select id="u-role" class="yiriba-select"><option value="admin">Administrateur</option><option value="teacher">Enseignant</option><option value="educator">Éducateur</option><option value="secretary">Secrétaire</option><option value="comptable">Comptable</option><option value="parent">Parent</option><option value="student">Élève</option></select></div><div class="modal-footer"><button class="btn-secondary" onclick="closeModal()">Annuler</button><button class="btn-add" onclick="submitEditUserRole(${id})"><i class="fas fa-check"></i> Enregistrer</button></div></div>`);
}
async function submitEditUserRole(id) {
  const data = {
    first_name: document.getElementById('u-first').value.trim(),
    last_name: document.getElementById('u-last').value.trim(),
    role_type: document.getElementById('u-role').value,
  };
  try {
    const res = await api(`/api/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(data) });
    if (res?.ok) { closeModal(); showToast('Utilisateur mis à jour'); loadUsers(); }
    else { showToast('Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

/* -- Add User Modal ------------------------------------------- */
function showAddUserModal() {
  showModal('Ajouter un utilisateur', `
    <div class="modal-form">
      <div class="form-group"><label>Type d'utilisateur</label>
        <select id="au-role" class="yiriba-select" onchange="toggleUserFields()" style="width:100%">
          <option value="teacher">Enseignant</option>
          <option value="educator">Éducateur</option>
          <option value="secretary">Secrétaire</option>
          <option value="comptable">Comptable</option>
          <option value="parent">Parent / Tuteur</option>
          <option value="student">Élève</option>
          <option value="admin">Administrateur</option>
        </select></div>
      <div id="au-fields">
        <div class="form-row"><div class="form-group"><label>Prénom</label><input id="au-first" placeholder="Prénom" required></div><div class="form-group"><label>Nom</label><input id="au-last" placeholder="Nom" required></div></div>
        <div class="form-group"><label>Email <span style="font-weight:400;color:var(--texte-secondaire)" id="au-email-hint">(requis)</span></label><input id="au-email" type="email" placeholder="email@ecole.com"></div>
        <div class="form-group"><label>Téléphone</label><input id="au-phone" placeholder="(+226) XX XX XX XX"></div>
        <div id="au-pwd-section">
          <div class="form-group" style="display:flex;align-items:center;gap:8px">
            <label style="margin:0"><input type="checkbox" id="au-gen-pwd" checked> Générer un mot de passe temporaire</label></div>
          <div id="au-pwd-manual" style="display:none"><div class="form-group"><label>Mot de passe</label><input id="au-password" type="password" placeholder="Minimum 8 caractères"></div></div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" id="btn-create-user" onclick="submitCreateUser()"><i class="fas fa-plus"></i> Créer le compte</button>
      </div>
    </div>
  `);
  toggleUserFields();
}
function toggleUserFields() {
  const role = document.getElementById('au-role').value;
  const emailHint = document.getElementById('au-email-hint');
  const emailInput = document.getElementById('au-email');
  const pwdSection = document.getElementById('au-pwd-section');
  if (role === 'student') {
    emailHint.textContent = '(optionnel)';
    emailInput.placeholder = 'optionnel pour les élèves';
    pwdSection.style.display = 'none';
  } else {
    emailHint.textContent = '(requis)';
    emailInput.placeholder = 'email@ecole.com';
    pwdSection.style.display = 'block';
  }
}
async function submitCreateUser() {
  const btn = document.getElementById('btn-create-user');
  btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Création...';
  const role = document.getElementById('au-role').value;
  const genPwd = document.getElementById('au-gen-pwd')?.checked;
  const data = {
    first_name: document.getElementById('au-first').value.trim(),
    last_name: document.getElementById('au-last').value.trim(),
    email: document.getElementById('au-email').value.trim() || null,
    phone: document.getElementById('au-phone').value.trim() || null,
    role_type: role,
    generate_password: genPwd,
  };
  if (!genPwd) {
    data.password = document.getElementById('au-password')?.value;
    if (!data.password || data.password.length < 8) {
      showToast('Le mot de passe doit contenir au moins 8 caractères', 'error');
      btn.disabled = false; btn.innerHTML = '<i class="fas fa-plus"></i> Créer le compte';
      return;
    }
  }
  if (!data.first_name || !data.last_name) { showToast('Prénom et nom requis', 'error'); btn.disabled = false; btn.innerHTML = '<i class="fas fa-plus"></i> Créer le compte'; return; }
  if (role !== 'student' && !data.email) { showToast('Email requis pour ce rôle', 'error'); btn.disabled = false; btn.innerHTML = '<i class="fas fa-plus"></i> Créer le compte'; return; }
  try {
    const res = await api('/api/admin/users', { method: 'POST', body: JSON.stringify(data) });
    const d = await res.json().catch(() => ({}));
    if (res?.ok) {
      let msg = 'Compte créé avec succès';
      if (d.temp_password) msg += '\n\nMot de passe temporaire: ' + d.temp_password;
      if (d.username) msg += '\nIdentifiant YIRIBA: ' + d.username;
      alert(msg);
      closeModal(); loadUsers();
    } else {
      showToast(d.detail || 'Erreur lors de la création', 'error');
    }
  } catch { showToast('Erreur réseau', 'error'); }
  btn.disabled = false; btn.innerHTML = '<i class="fas fa-plus"></i> Créer le compte';
}

/* ==============================================================
   MODULE RÔLES & PERMISSIONS
   ============================================================== */
let _rolesData = { roles: [], permissions: [] };

async function loadRoles() {
  const c = document.getElementById('main-content');
  c.innerHTML = yiribaLoading('Chargement des rôles...');
  try {
    const r = await api('/api/admin/roles');
    if (!r?.ok) { showToast('Impossible de charger les rôles', 'error'); return; }
    _rolesData = await r.json();
  } catch { showToast('Erreur réseau', 'error'); return; }
  renderRolesPage();
}

function renderRolesPage() {
  const c = document.getElementById('main-content');
  const { roles, permissions } = _rolesData;

  // Regrouper les permissions par ressource
  const byResource = {};
  permissions.forEach(p => {
    (byResource[p.resource] = byResource[p.resource] || []).push(p);
  });

  const resourceLabels = {
    student: 'Élèves', class: 'Classes', teacher: 'Enseignants', grade: 'Notes',
    attendance: 'Présences', bulletin: 'Bulletins', payment: 'Paiements',
    user: 'Utilisateurs', role: 'Rôles', message: 'Messages', evaluation: 'Évaluations',
    discipline: 'Discipline', timetable: 'Emploi du temps', audit: 'Audit',
    report: 'Rapports', settings: 'Paramètres', notification: 'Notifications',
  };
  const actionLabels = { create: 'Créer', read: 'Consulter', update: 'Modifier', delete: 'Supprimer', manage: 'Gérer', import: 'Importer', justify: 'Justifier', send: 'Envoyer', generate: 'Générer', override: 'Forcer', refund: 'Rembourser', validate: 'Valider', audit: 'Superviser' };

  c.innerHTML = `
    <div class="welcome"><h1>Rôles & Permissions</h1><p>Contrôlez précisément ce que chaque rôle peut faire dans votre établissement.</p></div>
    <div class="indicator-row">
      <div class="indicator-card hero"><div class="indicator-icon"><i class="fas fa-shield-halved"></i></div><div class="indicator-info"><h4>Rôles</h4><div class="indicator-val">${roles.length}</div><div class="indicator-sub">Configurés</div></div></div>
      <div class="indicator-card"><div class="indicator-icon"><i class="fas fa-key"></i></div><div class="indicator-info"><h4>Permissions</h4><div class="indicator-val">${permissions.length}</div><div class="indicator-sub">Disponibles</div></div></div>
      <div class="indicator-card" style="display:flex;align-items:center;justify-content:center"><button class="btn-add" onclick="showCreateRoleModal()"><i class="fas fa-plus"></i> Nouveau rôle</button></div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px">
      ${roles.map(r => {
        const permCount = r.permission_count || (r.permission_ids || []).length;
        const users = r.user_count || 0;
        return `<article class="card section-card" style="display:flex;flex-direction:column;gap:10px">
          <div style="display:flex;align-items:center;gap:12px">
            <div class="stat-icon"><i class="fas fa-shield-halved"></i></div>
            <div style="flex:1">
              <h3 style="font-family:'Sora',sans-serif;font-size:16px;font-weight:650">${r.name}</h3>
              <div style="font-size:12px;color:var(--texte-secondaire)">${permCount} permission(s) · ${users} utilisateur(s)</div>
            </div>
            ${r.is_system ? '<span class="badge badge-active"><span class="badge-dot"></span>Système</span>' : '<span class="badge badge-warning"><span class="badge-dot"></span>Personnalisé</span>'}
          </div>
          <div style="display:flex;gap:8px;margin-top:auto">
            <button class="btn-secondary" style="flex:1" onclick="showEditRoleModal(${r.id})"><i class="fas fa-pen"></i> Configurer</button>
          </div>
        </article>`;
      }).join('')}
    </div>
    <div id="role-modal-slot"></div>
  `;
}

function _rolePermMatrix(selectedIds) {
  const { permissions } = _rolesData;
  const byResource = {};
  permissions.forEach(p => (byResource[p.resource] = byResource[p.resource] || []).push(p));
  const resourceLabels = { student: 'Élèves', class: 'Classes', teacher: 'Enseignants', grade: 'Notes', attendance: 'Présences', bulletin: 'Bulletins', payment: 'Paiements', user: 'Utilisateurs', role: 'Rôles', message: 'Messages', evaluation: 'Évaluations', discipline: 'Discipline', timetable: 'Emploi du temps', audit: 'Audit', report: 'Rapports', settings: 'Paramètres', notification: 'Notifications' };
  const actionLabels = { create: 'Créer', read: 'Consulter', update: 'Modifier', delete: 'Supprimer', manage: 'Gérer', import: 'Importer', justify: 'Justifier', send: 'Envoyer', generate: 'Générer', override: 'Forcer', refund: 'Rembourser', validate: 'Valider', audit: 'Superviser' };
  const sel = new Set(selectedIds);
  return Object.entries(byResource).map(([res, perms]) => `
    <div style="border:1px solid var(--border);border-radius:12px;padding:12px 14px;margin-bottom:10px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <div style="font-weight:700;font-size:13px;color:var(--yiriba-vert-profond,#145c3f)">${resourceLabels[res] || res}</div>
        <button type="button" class="btn-secondary" style="padding:3px 10px;font-size:11px" onclick="_toggleResourcePerms('${res}', this)">Tout / rien</button>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:6px">
        ${perms.map(p => `
          <label style="display:flex;align-items:center;gap:8px;font-size:12.5px;cursor:pointer;padding:4px 6px;border-radius:8px" onmouseover="this.style.background='var(--surface-soft,#f7f5ef)'" onmouseout="this.style.background=''">
            <input type="checkbox" class="role-perm-check" data-resource="${res}" value="${p.id}" ${sel.has(p.id) ? 'checked' : ''} style="accent-color:var(--yiriba-vert)">
            <span><b>${actionLabels[p.action] || p.action}</b>${p.description ? ' <span style="color:var(--texte-secondaire)">— ' + p.description + '</span>' : ''}</span>
          </label>`).join('')}
      </div>
    </div>`).join('');
}

function _toggleResourcePerms(resource, btn) {
  const checks = [...document.querySelectorAll(`.role-perm-check[data-resource="${resource}"]`)];
  const allChecked = checks.every(ch => ch.checked);
  checks.forEach(ch => ch.checked = !allChecked);
}

function _collectRolePerms() {
  return [...document.querySelectorAll('.role-perm-check:checked')].map(ch => parseInt(ch.value));
}

function showCreateRoleModal() {
  showModal('Nouveau rôle', `
    <div class="modal-form">
      <div class="form-group"><label>Nom du rôle *</label><input id="nr-name" placeholder="Ex: Surveillant général"></div>
      <div style="font-weight:700;font-size:13px;color:var(--yiriba-vert-profond,#145c3f);margin:10px 0 8px">Permissions accordées</div>
      <div style="max-height:380px;overflow-y:auto;padding-right:4px">${_rolePermMatrix([])}</div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="submitCreateRole()"><i class="fas fa-check"></i> Créer le rôle</button>
      </div>
    </div>
  `);
}

async function submitCreateRole() {
  const name = document.getElementById('nr-name').value.trim();
  if (!name) { showToast('Le nom du rôle est requis', 'error'); return; }
  try {
    const r = await api('/api/admin/roles', { method: 'POST', body: JSON.stringify({ name, permission_ids: _collectRolePerms() }) });
    if (r?.ok || r?.status === 201) { closeModal(); showToast(`Rôle « ${name} » créé`); loadRoles(); }
    else { const j = await r.json(); showToast(parseError(j) || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

function showEditRoleModal(roleId) {
  const role = _rolesData.roles.find(r => r.id === roleId);
  if (!role) return;
  showModal('Configurer — ' + role.name, `
    <div class="modal-form">
      <div class="form-group"><label>Nom du rôle</label><input id="er-name" value="${role.name}"></div>
      <div style="font-weight:700;font-size:13px;color:var(--yiriba-vert-profond,#145c3f);margin:10px 0 8px">Permissions du rôle</div>
      <div style="max-height:380px;overflow-y:auto;padding-right:4px">${_rolePermMatrix(role.permission_ids || [])}</div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="submitEditRole(${roleId})"><i class="fas fa-check"></i> Enregistrer</button>
      </div>
    </div>
  `);
}

async function submitEditRole(roleId) {
  const name = document.getElementById('er-name').value.trim();
  if (!name) { showToast('Le nom du rôle est requis', 'error'); return; }
  try {
    const r = await api(`/api/admin/roles/${roleId}`, { method: 'PUT', body: JSON.stringify({ name, permission_ids: _collectRolePerms() }) });
    if (r?.ok) { closeModal(); showToast('Rôle mis à jour'); loadRoles(); }
    else { const j = await r.json(); showToast(parseError(j) || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

/* ==============================================================
   CONTACT YIRIBA — demande d'abonnement / support
   ============================================================== */
function showSupportRequestModal() {
  showModal('Contacter YIRIBA', `
    <div class="modal-form">
      <div style="display:flex;align-items:center;gap:10px;background:var(--surface-soft,#f0ede4);border-radius:10px;padding:10px 14px;margin-bottom:14px;font-size:13px;color:var(--texte-secondaire)">
        <i class="fas fa-circle-info" style="color:var(--yiriba-vert)"></i>
        <span>Votre message sera envoyé directement à l'équipe YIRIBA. Nous vous répondrons dans vos <b>Échanges</b>.</span>
      </div>
      <div class="form-group"><label>Objet *</label>
        <select id="sr-subject">
          <option value="Demande d'abonnement">Activer / changer de forfait</option>
          <option value="Demande d'information">Demande d'information</option>
          <option value="Problème technique">Problème technique</option>
          <option value="Autre">Autre</option>
        </select>
      </div>
      <div class="form-group"><label>Téléphone (optionnel)</label><input id="sr-phone" placeholder="Ex: 70 12 34 56"></div>
      <div class="form-group"><label>Message *</label><textarea id="sr-message" rows="5" placeholder="Décrivez votre besoin..." style="width:100%;padding:11px 14px;border:1.5px solid var(--border);border-radius:12px;font-size:14px;font-family:inherit;resize:vertical"></textarea></div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" id="sr-send" onclick="submitSupportRequest()"><i class="fas fa-paper-plane"></i> Envoyer</button>
      </div>
    </div>
  `);
}

async function submitSupportRequest() {
  const subject = document.getElementById('sr-subject').value;
  const message = document.getElementById('sr-message').value.trim();
  const phone = document.getElementById('sr-phone').value.trim() || null;
  if (message.length < 10) { showToast('Le message doit contenir au moins 10 caractères', 'error'); return; }
  const btn = document.getElementById('sr-send');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Envoi...';
  try {
    const r = await api('/api/subscriptions/support-request', { method: 'POST', body: JSON.stringify({ subject, message, phone }) });
    if (r?.ok || r?.status === 201) {
      closeModal();
      showToast('Votre demande a été envoyée à l\'équipe YIRIBA ✔');
    } else {
      const j = await r.json().catch(() => ({}));
      showToast(parseError(j) || 'Erreur lors de l\'envoi', 'error');
      btn.disabled = false;
      btn.innerHTML = '<i class="fas fa-paper-plane"></i> Envoyer';
    }
  } catch { showToast('Erreur réseau', 'error'); btn.disabled = false; btn.innerHTML = '<i class="fas fa-paper-plane"></i> Envoyer'; }
}

/* ==============================================================
   MODULE SUBSCRIPTION (Abonnement)
   ============================================================== */
async function loadSubscription() {
  const c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    const [subRes, plansRes] = await Promise.all([
      api('/api/subscriptions/my-summary'),
      api('/api/auth/subscription-plans')
    ]);
    const sub = subRes?.ok ? await subRes.json() : {};
    const plans = plansRes?.ok ? (await plansRes.json()).plans || [] : [];
    const s = { status: sub.subscription_status, trial_ends_at: sub.trial_ends_at, student_count: sub.student_count || 0 };
    const p = sub.plan || {};
    const statusLabels = { trial: 'Essai gratuit', active: 'Actif', expired: 'Expiré', cancelled: 'Annulé' };
    const statusColors = { trial: '#ff9800', active: '#4caf50', expired: '#f44336', cancelled: '#9e9e9e' };
    const status = s.status || 'unknown';
    const statusLabel = statusLabels[status] || status;
    const statusColor = statusColors[status] || '#666';
    const trialEnds = s.trial_ends_at ? new Date(s.trial_ends_at).toLocaleDateString('fr-FR') : null;
    const daysLeft = trialEnds ? Math.max(0, Math.ceil((new Date(s.trial_ends_at) - new Date()) / 86400000)) : null;
    let trialInfo = '';
    if (status === 'trial' && daysLeft !== null) {
      const urgency = daysLeft < 30 ? '#f44336' : daysLeft < 60 ? '#ff9800' : '#4caf50';
      trialInfo = '<div style="background:#fff3e0;border-radius:10px;padding:16px;margin-top:16px"><div style="font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:#e65100;margin-bottom:6px">Essai gratuit</div><div style="font-size:28px;font-weight:700;color:' + urgency + '">' + daysLeft + ' jours restants</div><div style="font-size:13px;color:#bf360c;margin-top:4px">Expire le ' + trialEnds + '</div></div>';
    }
    const features = p.features || {};
    const featureLabels = { students: 'Gestion élèves', classes: 'Classes', subjects: 'Matières', grades: 'Notes', attendance: 'Présences', bulletins: 'Bulletins', payments: 'Paiements', parents: 'Portails parents', reports: 'Rapports', advanced_reports: 'Rapports avancés', multi_campus: 'Multi-campuses', priority_support: 'Support prioritaire' };
    const featuresListHtml = Object.entries(featureLabels).map(([k, label]) => {
      const included = features[k];
      return '<div style="display:flex;align-items:center;gap:8px;font-size:13px;color:' + (included ? 'var(--texte-primaire)' : 'var(--texte-secondaire)') + ';opacity:' + (included ? '1' : '0.5') + '"><i class="fas fa-' + (included ? 'check-circle' : 'times-circle') + '" style="color:' + (included ? '#4caf50' : '#ccc') + ';font-size:14px"></i>' + label + '</div>';
    }).join('\n');
    const trialBanner = status === 'trial' ? '<div style="margin-top:20px;padding:16px 20px;background:linear-gradient(135deg,#e8f5e9,#f0faf4);border-radius:12px;display:flex;align-items:center;gap:16px;max-width:900px"><i class="fas fa-gift" style="font-size:28px;color:var(--yiriba-vert)"></i><div><div style="font-weight:700;color:var(--yiriba-vert-profond);margin-bottom:2px">Passez au forfait payant</div><div style="font-size:13px;color:var(--texte-secondaire)">Votre essai gratuit se termine dans ' + (daysLeft || 0) + ' jours. Contactez-nous pour activer votre abonnement.</div></div><button onclick="showSupportRequestModal()" style="background:var(--yiriba-vert);color:white;border:none;border-radius:8px;padding:10px 20px;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap">Contacter YIRIBA</button></div>' : '';
    c.innerHTML = '<div class="welcome"><h1>Abonnement</h1><p>Gérez votre forfait YIRIBA et suivez votre consommation.</p></div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;max-width:900px">' +
      '<div class="card section-card" style="padding:24px">' +
      '<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">' +
      '<div style="width:48px;height:48px;border-radius:12px;background:' + statusColor + '22;display:flex;align-items:center;justify-content:center"><i class="fas fa-crown" style="font-size:22px;color:' + statusColor + '"></i></div>' +
      '<div><div style="font-size:22px;font-weight:700;color:var(--yiriba-vert-profond)">' + (p.name || 'Aucun forfait') + '</div><div style="font-size:13px;color:' + statusColor + ';font-weight:600">' + statusLabel + '</div></div>' +
      '</div>' +
      '<div style="display:flex;flex-direction:column;gap:10px">' +
      '<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)"><span style="color:var(--texte-secondaire);font-size:13px">Élèves max</span><span style="font-weight:600;font-size:13px">' + (p.max_students ? p.max_students + ' élèves' : 'Illimité') + '</span></div>' +
      '<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)"><span style="color:var(--texte-secondaire);font-size:13px">Tarif</span><span style="font-weight:600;font-size:13px">' + (p.price_per_student_year > 0 ? p.price_per_student_year + ' XOF / élève / an' : 'Sur devis') + '</span></div>' +
      '<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)"><span style="color:var(--texte-secondaire);font-size:13px">Élèves enregistrés</span><span style="font-weight:600;font-size:13px">' + (sub.student_count || 0) + '</span></div>' +
      '</div>' + trialInfo + '</div>' +
      '<div class="card section-card" style="padding:24px">' +
      '<div style="font-size:15px;font-weight:700;color:var(--yiriba-vert-profond);margin-bottom:16px">Fonctionnalités incluses</div>' +
      '<div style="display:flex;flex-direction:column;gap:8px">' + featuresListHtml + '</div>' +
      '</div></div>' + trialBanner;
  } catch(e) {
    c.innerHTML = '<div class="welcome"><h1>Abonnement</h1><p>Impossible de charger les informations d\'abonnement.</p></div>';
  }
}

/* ==============================================================
   MODULE AUDIT
   ============================================================== */
async function loadAudit() {
  const c = document.getElementById('main-content');
  let logs = [];
  try { const r = await api('/api/admin/audit-log?per_page=50'); if (r?.ok) logs = (await r.json()).logs || []; } catch {}
  c.innerHTML = `
    <div class="welcome"><h1>Audit</h1><p>Suivez les actions effectuées dans votre établissement.</p></div>
    ${logs.length > 0 ? `<div class="yiriba-table-wrap"><table class="yiriba-table"><thead><tr><th>Action</th><th>Description</th><th>Date</th></tr></thead><tbody>${logs.map(l => {
      const colors = {create:'var(--yiriba-vert)',update:'var(--yiriba-jaune)',delete:'var(--yiriba-rouge)',read:'var(--yiriba-vert-feuille)'};
      const color = colors[(l.action||'').toLowerCase()] || 'var(--yiriba-vert)';
      return `<tr><td><span style="display:inline-flex;align-items:center;gap:6px"><span style="width:8px;height:8px;border-radius:50%;background:${color}"></span>${l.action||'—'}</span></td><td>${l.description||'—'}</td><td>${l.created_at ? timeAgo(l.created_at) : '—'}</td></tr>`;
    }).join('')}</tbody></table></div>` : `<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-clock-rotate-left"></i></div><h4>Aucune activité enregistrée</h4><p>Les actions des utilisateurs apparaîtront ici.</p></div></div>`}
  `;
}

/* ==============================================================
   MODULE PARAMÈTRES
   ============================================================== */
async function loadSettings() {
  const c = document.getElementById('main-content');
  c.innerHTML = yiribaLoading('Chargement des paramètres...');
  let school = {};
  let notifSettings = [];
  let discMode = 'conduct';
  let discRules = [];
  try {
    const [schoolRes, notifRes, discModeRes, discRulesRes] = await Promise.all([
      api('/api/admin/school-profile'),
      api('/api/admin/notification-settings'),
      api('/api/discipline/mode'),
      api('/api/discipline/rules'),
    ]);
    if (schoolRes?.ok) school = (await schoolRes.json()).school || {};
    if (notifRes?.ok) notifSettings = (await notifRes.json()).settings || [];
    if (discModeRes?.ok) discMode = (await discModeRes.json()).mode || 'conduct';
    if (discRulesRes?.ok) discRules = (await discRulesRes.json()).rules || [];
  } catch {}
  const activeNotifs = notifSettings.filter(n => n.is_active).length;
  const totalNotifs = notifSettings.length || 8;
  const activeDiscRules = discRules.filter(r => r.is_active).length;
  c.innerHTML = `
    <div class="welcome"><h1>Paramètres</h1><p>Configurez votre établissement et votre compte.</p></div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px">
      <article class="card section-card" style="cursor:pointer" onclick="loadSettingsSection('profile')">
        <div class="section-title" style="font-size:15px;margin-bottom:16px"><i class="fas fa-school" style="margin-right:8px;color:var(--yiriba-vert)"></i>Établissement</div>
        <div style="display:flex;flex-direction:column;gap:10px;font-size:14px">
          <div><strong style="font-size:11px;text-transform:uppercase;color:var(--texte-secondaire);letter-spacing:0.05em">Nom</strong><div>${school.name || '—'}</div></div>
          <div><strong style="font-size:11px;text-transform:uppercase;color:var(--texte-secondaire);letter-spacing:0.05em">Slug</strong><div>${school.slug || '—'}</div></div>
          <div><strong style="font-size:11px;text-transform:uppercase;color:var(--texte-secondaire);letter-spacing:0.05em">Type</strong><div>${school.school_type || '—'}</div></div>
          <div><strong style="font-size:11px;text-transform:uppercase;color:var(--texte-secondaire);letter-spacing:0.05em">Email</strong><div>${school.email || '—'}</div></div>
        </div>
        <div style="margin-top:12px;font-size:12px;color:var(--yiriba-vert-profond);font-weight:500">Modifier →</div>
      </article>
      <article class="card section-card" style="cursor:pointer" onclick="loadSettingsSection('academic')">
        <div class="section-title" style="font-size:15px;margin-bottom:16px"><i class="fas fa-calendar-alt" style="margin-right:8px;color:var(--yiriba-jaune)"></i>Académique</div>
        <div style="font-size:14px;color:var(--texte-secondaire)">Barème et notes par défaut pour les nouvelles évaluations.</div>
        <div style="margin-top:12px;font-size:12px;color:var(--yiriba-vert-profond);font-weight:500">Configurer →</div>
      </article>
      <article class="card section-card" style="cursor:pointer" onclick="loadSettingsSection('notifications')">
        <div class="section-title" style="font-size:15px;margin-bottom:16px"><i class="fas fa-bell" style="margin-right:8px;color:var(--yiriba-vert-feuille)"></i>Notifications</div>
        <div style="font-size:14px"><div style="display:flex;justify-content:space-between;align-items:center"><span>Événements actifs</span><span class="badge badge-active">${activeNotifs}/${totalNotifs}</span></div></div>
        <div style="margin-top:12px;font-size:12px;color:var(--yiriba-vert-profond);font-weight:500">Configurer →</div>
      </article>
      <article class="card section-card" style="cursor:pointer" onclick="loadSettingsSection('discipline')">
        <div class="section-title" style="font-size:15px;margin-bottom:16px"><i class="fas fa-gavel" style="margin-right:8px;color:#f57f17"></i>Discipline</div>
        <div style="font-size:14px"><div style="display:flex;justify-content:space-between;align-items:center"><span>Mode</span><span class="badge badge-active">${discMode === 'conduct' ? 'Conduite séparée' : 'Impact sur moyenne'}</span></div></div>
        <div style="margin-top:8px;font-size:13px;color:var(--texte-secondaire)">${activeDiscRules} règles actives</div>
        <div style="margin-top:12px;font-size:12px;color:var(--yiriba-vert-profond);font-weight:500">Configurer →</div>
      </article>
      <article class="card section-card" style="cursor:pointer" onclick="loadSettingsSection('security')">
        <div class="section-title" style="font-size:15px;margin-bottom:16px"><i class="fas fa-shield-halved" style="margin-right:8px;color:var(--yiriba-rouge)"></i>Sécurité</div>
        <div style="font-size:14px"><div style="display:flex;justify-content:space-between;align-items:center"><span>Validation admin</span><span class="badge badge-active">Activée</span></div></div>
        <div style="margin-top:12px;font-size:12px;color:var(--yiriba-vert-profond);font-weight:500">Configurer →</div>
      </article>
    </div>
  `;
}

async function loadSettingsSection(section) {
  const c = document.getElementById('main-content');
  c.innerHTML = yiribaLoading();
  if (section === 'profile') await loadSettingsProfile(c);
  else if (section === 'notifications') await loadSettingsNotifications(c);
  else if (section === 'academic') await loadSettingsAcademic(c);
  else if (section === 'security') await loadSettingsSecurity(c);
  else if (section === 'discipline') await loadSettingsDiscipline(c);
}

async function loadSettingsProfile(c) {
  let school = {};
  try { const r = await api('/api/admin/school-profile'); if (r?.ok) school = (await r.json()).school || {}; } catch {}
  c.innerHTML = `
    <div class="welcome" style="display:flex;align-items:center;gap:12px">
      <a onclick="loadSettings()" style="cursor:pointer;color:var(--yiriba-vert-profond);font-size:18px"><i class="fas fa-arrow-left"></i></a>
      <div><h1>Profil de l'établissement</h1><p>Informations de votre école.</p></div>
    </div>
    <div class="card section-card" style="max-width:640px">
      <div class="section-title" style="font-size:15px;margin-bottom:16px"><i class="fas fa-school" style="margin-right:8px;color:var(--yiriba-vert)"></i>Établissement</div>
      <form onsubmit="saveSchoolProfile(event)" style="display:flex;flex-direction:column;gap:14px">
        <div style="display:flex;align-items:center;gap:16px;padding:12px;background:var(--yiriba-ivoire);border-radius:10px">
          <div id="logo-preview" style="width:64px;height:64px;border-radius:12px;background:white;border:2px dashed var(--border);display:flex;align-items:center;justify-content:center;overflow:hidden;flex-shrink:0">
            ${school.logo_url ? '<img src="' + school.logo_url + '" style="width:100%;height:100%;object-fit:contain">' : '<i class="fas fa-image" style="font-size:20px;color:var(--texte-secondaire)"></i>'}
          </div>
          <div style="flex:1"><strong style="font-size:13px">Logo de l'école</strong><div style="font-size:12px;color:var(--texte-secondaire);margin:2px 0">JPG, PNG, GIF ou WebP (max 5 Mo)</div>
            <input type="file" id="sp-logo" accept="image/*" onchange="uploadSchoolLogo(this)" style="margin-top:4px;font-size:12px">
          </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Nom</label><input id="sp-name" value="${school.name || ''}" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
          <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Sigle</label><input id="sp-short" value="${school.short_name || ''}" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
        </div>
        <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Email</label><input id="sp-email" type="email" value="${school.email || ''}" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Téléphone</label><input id="sp-phone" value="${school.phone || ''}" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
          <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Type</label><select id="sp-type" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"><option ${school.school_type==='college'?'selected':''}>college</option><option ${school.school_type==='lycee'?'selected':''}>lycee</option><option ${school.school_type==='primaire'?'selected':''}>primaire</option><option ${school.school_type==='complexe'?'selected':''}>complexe</option></select></div>
        </div>
        <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Adresse</label><input id="sp-address" value="${school.address || ''}" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px">
          <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Ville</label><input id="sp-city" value="${school.city || ''}" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
          <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Secteur</label><input id="sp-district" value="${school.district || ''}" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
          <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Région</label><input id="sp-region" value="${school.region || ''}" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
        </div>
        <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Devise</label><input id="sp-country" value="${school.country || 'Burkina Faso'}" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
        <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Site web</label><input id="sp-website" value="${school.website || ''}" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
        <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Motto</label><input id="sp-motto" value="${school.motto || ''}" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
        <div id="profile-msg" class="error-text"></div>
        <button type="submit" class="btn-add" style="align-self:flex-start"><i class="fas fa-check"></i> Enregistrer</button>
      </form>
    </div>
  `;
}

async function uploadSchoolLogo(input) {
  const file = input.files[0];
  if (!file) return;
  const preview = document.getElementById('logo-preview');
  if (!preview) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    preview.innerHTML = '<i class="fas fa-spinner fa-spin" style="font-size:16px;color:var(--yiriba-vert)"></i>';
    const r = await fetch(API + '/api/admin/school-profile/logo', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + state.token },
      body: fd,
    });
    const d = await r.json();
    if (r.ok && d.logo_url) {
      preview.innerHTML = '<img src="' + d.logo_url + '" style="width:100%;height:100%;object-fit:contain">';
      showToast('Logo mis a jour', 'success');
    } else {
      preview.innerHTML = '<i class="fas fa-image" style="font-size:20px;color:var(--texte-secondaire)"></i>';
      showToast(d.detail || 'Erreur lors de l upload', 'error');
    }
  } catch (err) {
    preview.innerHTML = '<i class="fas fa-image" style="font-size:20px;color:var(--texte-secondaire)"></i>';
    showToast(err.message, 'error');
  }
}

async function saveSchoolProfile(e) {
  e.preventDefault();
  const msg = document.getElementById('profile-msg'); msg.textContent = '';
  try {
    const r = await api('/api/onboarding/school-profile', {
      method: 'PUT',
      body: JSON.stringify({
        name: document.getElementById('sp-name').value,
        short_name: document.getElementById('sp-short').value,
        email: document.getElementById('sp-email').value,
        phone: document.getElementById('sp-phone').value,
        school_type: document.getElementById('sp-type').value,
        address: document.getElementById('sp-address').value,
        city: document.getElementById('sp-city').value,
        district: document.getElementById('sp-district').value,
        region: document.getElementById('sp-region').value,
        country: document.getElementById('sp-country').value,
        website: document.getElementById('sp-website').value,
        motto: document.getElementById('sp-motto').value,
      })
    });
    if (r?.ok) { showToast('Profil mis à jour', 'success'); loadSettings(); }
    else { const d = await r.json(); msg.textContent = d.detail || 'Erreur'; }
  } catch (err) { msg.textContent = err.message; }
}

async function loadSettingsNotifications(c) {
  let settings = [];
  try { const r = await api('/api/admin/notification-settings'); if (r?.ok) settings = (await r.json()).settings || []; } catch {}
  const eventLabels = {
    absence: { label: 'Absence', icon: 'fa-user-xmark', color: 'var(--yiriba-rouge)' },
    new_grade: { label: 'Nouvelle note', icon: 'fa-pen-fancy', color: 'var(--yiriba-vert)' },
    payment_due: { label: 'Échéance de paiement', icon: 'fa-money-bill-wave', color: 'var(--yiriba-jaune)' },
    payment_received: { label: 'Paiement reçu', icon: 'fa-check-circle', color: 'var(--yiriba-vert-feuille)' },
    bulletin_ready: { label: 'Bulletin disponible', icon: 'fa-file-lines', color: 'var(--yiriba-vert-profond)' },
    account_validation: { label: 'Validation de compte', icon: 'fa-user-check', color: 'var(--yiriba-vert)' },
    announcement: { label: 'Annonce générale', icon: 'fa-bullhorn', color: 'var(--yiriba-jaune)' },
    low_attendance: { label: 'Faible présence', icon: 'fa-triangle-exclamation', color: 'var(--yiriba-rouge)' },
  };
  c.innerHTML = `
    <div class="welcome" style="display:flex;align-items:center;gap:12px">
      <a onclick="loadSettings()" style="cursor:pointer;color:var(--yiriba-vert-profond);font-size:18px"><i class="fas fa-arrow-left"></i></a>
      <div><h1>Notifications</h1><p>Configurez les alertes par type d'événement.</p></div>
    </div>
    <div style="display:flex;flex-direction:column;gap:12px;max-width:800px">
      ${settings.map(s => {
        const ev = eventLabels[s.event_type] || { label: s.event_type, icon: 'fa-bell', color: '#666' };
        return `
        <article class="card section-card" style="padding:16px">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
            <div style="width:36px;height:36px;border-radius:8px;background:${ev.color}15;color:${ev.color};display:flex;align-items:center;justify-content:center;font-size:14px"><i class="fas ${ev.icon}"></i></div>
            <div style="flex:1"><strong style="font-size:14px">${ev.label}</strong></div>
            <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px">
              <input type="checkbox" ${s.sms_enabled ? 'checked' : ''} onchange="toggleNotifSetting(${s.id},'sms',this.checked)" style="accent-color:var(--yiriba-vert)"> SMS
            </label>
            <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:12px">
              <input type="checkbox" ${s.email_enabled ? 'checked' : ''} onchange="toggleNotifSetting(${s.id},'email',this.checked)" style="accent-color:var(--yiriba-vert)"> Email
            </label>
          </div>
          <details style="font-size:13px">
            <summary style="cursor:pointer;color:var(--yiriba-vert-profond);font-weight:500">Modifier le message</summary>
            <div style="margin-top:8px">
              <textarea id="tmpl-${s.id}" style="width:100%;min-height:60px;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:12px;font-family:inherit;resize:vertical">${s.message_template || ''}</textarea>
              <div style="margin-top:4px;font-size:11px;color:var(--texte-secondaire)">Variables : ${s.template_variables.map(v => '<code style="background:#f0f0f0;padding:1px 4px;border-radius:3px;font-size:10px">' + v + '</code>').join(' ')}</div>
              <button onclick="saveNotifTemplate(${s.id})" style="margin-top:6px;padding:4px 12px;border:1px solid var(--border);border-radius:6px;font-size:12px;cursor:pointer;background:white">Enregistrer</button>
            </div>
          </details>
        </article>`;
      }).join('')}
    </div>
  `;
}

async function toggleNotifSetting(id, channel, enabled) {
  try {
    const data = channel === 'sms' ? { sms_enabled: enabled } : { email_enabled: enabled };
    await api('/api/admin/notification-settings/' + id, { method: 'PUT', body: JSON.stringify(data) });
  } catch {}
}

async function saveNotifTemplate(id) {
  const el = document.getElementById('tmpl-' + id);
  if (!el) return;
  try {
    const r = await api('/api/admin/notification-settings/' + id, { method: 'PUT', body: JSON.stringify({ message_template: el.value }) });
    if (r?.ok) showToast('Message enregistré', 'success');
    else { const d = await r.json(); showToast(d.detail || 'Erreur', 'error'); }
  } catch (err) { showToast(err.message, 'error'); }
}

async function loadSettingsAcademic(c) {
  let settings = {};
  try { const r = await api('/api/admin/settings'); if (r?.ok) settings = (await r.json()).settings || {}; } catch {}
  c.innerHTML = `
    <div class="welcome" style="display:flex;align-items:center;gap:12px">
      <a onclick="loadSettings()" style="cursor:pointer;color:var(--yiriba-vert-profond);font-size:18px"><i class="fas fa-arrow-left"></i></a>
      <div><h1>Paramètres académiques</h1><p>Valeurs par défaut pour les nouvelles évaluations.</p></div>
    </div>
    <div class="card section-card" style="max-width:640px">
      <div style="background:#fef9e7;border:1px solid #f2b70533;border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:12px;color:var(--yiriba-text-secondaire)"><i class="fas fa-info-circle" style="color:var(--yiriba-jaune);margin-right:6px"></i>Le choix Trimestre/Semestre est défini lors de la création de chaque classe et ne peut pas être modifié après.</div>
      <form onsubmit="saveAcademicSettings(event)" style="display:flex;flex-direction:column;gap:14px">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Barème par défaut (nouvelles évaluations)</label><input id="acad-scale" type="number" value="${settings.default_grading_scale || 20}" min="1" max="100" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
          <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Note minimale pour réussir</label><input id="acad-pass" type="number" value="${settings.default_passing_grade || 10}" min="0" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
        </div>
        <div id="acad-msg" class="error-text"></div>
        <button type="submit" class="btn-add" style="align-self:flex-start"><i class="fas fa-check"></i> Enregistrer</button>
      </form>
    </div>
  `;
}

async function saveAcademicSettings(e) {
  e.preventDefault();
  const msg = document.getElementById('acad-msg'); msg.textContent = '';
  try {
    const r = await api('/api/admin/settings', {
      method: 'PUT',
      body: JSON.stringify({ settings: {
        default_grading_scale: document.getElementById('acad-scale').value,
        default_passing_grade: document.getElementById('acad-pass').value,
      }})
    });
    if (r?.ok) { showToast('Paramètres enregistrés', 'success'); loadSettings(); }
    else { const d = await r.json(); msg.textContent = d.detail || 'Erreur'; }
  } catch (err) { msg.textContent = err.message; }
}

async function loadSettingsSecurity(c) {
  let settings = {};
  try { const r = await api('/api/admin/settings'); if (r?.ok) settings = (await r.json()).settings || {}; } catch {}
  c.innerHTML = `
    <div class="welcome" style="display:flex;align-items:center;gap:12px">
      <a onclick="loadSettings()" style="cursor:pointer;color:var(--yiriba-vert-profond);font-size:18px"><i class="fas fa-arrow-left"></i></a>
      <div><h1>Sécurité</h1><p>Règles de sécurité pour votre établissement.</p></div>
    </div>
    <div class="card section-card" style="max-width:640px">
      <form onsubmit="saveSecuritySettings(event)" style="display:flex;flex-direction:column;gap:14px">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 0;border-bottom:1px solid var(--border)">
          <div><strong style="font-size:14px">Validation admin</strong><div style="font-size:12px;color:var(--texte-secondaire)">Les nouveaux comptes doivent être validés par un admin</div></div>
          <input type="checkbox" id="sec-validate" ${settings.require_admin_validation !== 'false' ? 'checked' : ''} style="width:20px;height:20px;accent-color:var(--yiriba-vert)">
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px 0;border-bottom:1px solid var(--border)">
          <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Longueur min. mot de passe</label><input id="sec-pwlen" type="number" value="${settings.min_password_length || 8}" min="6" max="32" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
          <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Tentatives max avant verrouillage</label><input id="sec-maxlog" type="number" value="${settings.max_login_attempts || 5}" min="3" max="20" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
        </div>
        <div><label style="font-size:12px;font-weight:600;color:var(--texte-secondaire)">Durée de verrouillage (minutes)</label><input id="sec-lockdur" type="number" value="${settings.lock_duration_minutes || 30}" min="5" max="1440" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;margin-top:4px"></div>
        <div id="sec-msg" class="error-text"></div>
        <button type="submit" class="btn-add" style="align-self:flex-start"><i class="fas fa-check"></i> Enregistrer</button>
      </form>
    </div>
  `;
}

async function saveSecuritySettings(e) {
  e.preventDefault();
  const msg = document.getElementById('sec-msg'); msg.textContent = '';
  try {
    const r = await api('/api/admin/settings', {
      method: 'PUT',
      body: JSON.stringify({ settings: {
        require_admin_validation: document.getElementById('sec-validate').checked ? 'true' : 'false',
        min_password_length: document.getElementById('sec-pwlen').value,
        max_login_attempts: document.getElementById('sec-maxlog').value,
        lock_duration_minutes: document.getElementById('sec-lockdur').value,
      }})
    });
    if (r?.ok) { showToast('Paramètres de sécurité enregistrés', 'success'); loadSettings(); }
    else { const d = await r.json(); msg.textContent = d.detail || 'Erreur'; }
  } catch (err) { msg.textContent = err.message; }
}

async function loadSettingsDiscipline(c) {
  let mode = 'conduct';
  let rules = [];
  try {
    const [modeRes, rulesRes] = await Promise.all([
      api('/api/discipline/mode'),
      api('/api/discipline/rules'),
    ]);
    if (modeRes?.ok) mode = (await modeRes.json()).mode || 'conduct';
    if (rulesRes?.ok) rules = (await rulesRes.json()).rules || [];
  } catch {}

  const rulesRows = rules.map((r, i) => `
    <tr id="disc-rule-${i}" style="border-bottom:1px solid var(--border)">
      <td style="padding:10px 8px;font-weight:500">
        <span id="disc-type-${i}">${r.incident_type.replace(/_/g, ' ')}</span>
      </td>
      <td style="padding:10px 8px;text-align:center">
        <input id="disc-pts-${i}" type="number" value="${r.points_deducted}" min="0" max="10" step="0.25"
          style="width:70px;text-align:center;padding:6px;border:2px solid transparent;border-radius:6px;font-weight:700;color:var(--yiriba-rouge);font-size:15px;background:transparent;transition:all 0.2s"
          onfocus="this.style.borderColor='var(--yiriba-vert)';this.style.background='white'"
          onblur="this.style.borderColor='transparent';this.style.background='transparent'">
      </td>
      <td style="padding:10px 8px">
        <input id="disc-desc-${i}" type="text" value="${(r.description || '').replace(/"/g, '&quot;')}" 
          style="width:100%;padding:6px 8px;border:1px solid var(--border);border-radius:6px;font-size:13px;color:var(--texte-secondaire);background:transparent;transition:border-color 0.2s"
          onfocus="this.style.borderColor='var(--yiriba-vert)'" onblur="this.style.borderColor='var(--border)'">
      </td>
      <td style="padding:10px 8px;text-align:center;white-space:nowrap">
        <label style="position:relative;display:inline-block;width:44px;height:24px;cursor:pointer" title="${r.is_active ? 'Désactiver' : 'Activer'}">
          <input type="checkbox" id="disc-active-${i}" ${r.is_active ? 'checked' : ''} 
            onchange="toggleDisciplineRule(${i}, '${r.incident_type}', this.checked)"
            style="opacity:0;width:0;height:0">
          <span style="position:absolute;top:0;left:0;right:0;bottom:0;background:${r.is_active ? 'var(--yiriba-vert)' : '#ccc'};border-radius:24px;transition:0.3s;cursor:pointer"></span>
          <span style="position:absolute;left:${r.is_active ? '22px' : '3px'};top:3px;width:18px;height:18px;background:white;border-radius:50%;transition:0.3s;box-shadow:0 1px 3px rgba(0,0,0,0.2)"></span>
        </label>
        <span style="font-size:11px;color:var(--texte-secondaire);margin-left:6px">${r.is_active ? 'Oui' : 'Non'}</span>
      </td>
      <td style="padding:10px 8px;text-align:center">
        <button onclick="saveDisciplineRule(${i}, '${r.incident_type}')" 
          style="background:var(--yiriba-vert);color:white;border:none;border-radius:6px;padding:6px 14px;cursor:pointer;font-size:12px;font-weight:600" 
          title="Enregistrer">
          <i class="fas fa-check"></i>
        </button>
      </td>
    </tr>
  `).join('');

  c.innerHTML = `
    <div class="welcome" style="display:flex;align-items:center;gap:12px">
      <a onclick="loadSettings()" style="cursor:pointer;color:var(--yiriba-vert-profond);font-size:18px"><i class="fas fa-arrow-left"></i></a>
      <div><h1>Discipline</h1><p>Configurez les règles disciplinaires et le mode d'application.</p></div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;max-width:900px">
      <!-- Mode selection -->
      <div class="card section-card">
        <div style="font-size:15px;font-weight:700;margin-bottom:14px"><i class="fas fa-cog" style="margin-right:8px;color:var(--yiriba-vert)"></i>Mode disciplinaire</div>
        <div style="display:flex;flex-direction:column;gap:12px">
          <label style="display:flex;align-items:center;gap:12px;padding:12px;border:2px solid ${mode==='conduct'?'var(--yiriba-vert)':'var(--border)'};border-radius:10px;cursor:pointer;transition:all 0.2s" onclick="setDisciplineMode('conduct')">
            <input type="radio" name="disc-mode" value="conduct" ${mode==='conduct'?'checked':''} style="accent-color:var(--yiriba-vert)">
            <div><strong style="font-size:14px">Conduite séparée</strong><div style="font-size:12px;color:var(--texte-secondaire)">Note de conduite calculée séparément (20 − points déduits)</div></div>
          </label>
          <label style="display:flex;align-items:center;gap:12px;padding:12px;border:2px solid ${mode==='general_average'?'var(--yiriba-vert)':'var(--border)'};border-radius:10px;cursor:pointer;transition:all 0.2s" onclick="setDisciplineMode('general_average')">
            <input type="radio" name="disc-mode" value="general_average" ${mode==='general_average'?'checked':''} style="accent-color:var(--yiriba-vert)">
            <div><strong style="font-size:14px">Impact sur moyenne</strong><div style="font-size:12px;color:var(--texte-secondaire)">Points déduits directement de la moyenne générale</div></div>
          </label>
        </div>
        <div style="margin-top:16px;padding:12px;background:#f0faf4;border-radius:8px;border-left:3px solid var(--yiriba-vert)">
          <div style="font-size:12px;font-weight:600;color:var(--yiriba-vert);margin-bottom:4px"><i class="fas fa-info-circle"></i> Mode actuel</div>
          <div style="font-size:13px;color:var(--texte-secondaire)">${mode === 'conduct' ? 'Les points déduits impactent une note de Conduite séparée (max 20). La moyenne académique reste inchangée.' : 'Les points déduits sont retranchés directement de la moyenne générale (plancher à 0).'}</div>
        </div>
      </div>

      <!-- Rules table -->
      <div class="card section-card" style="grid-column:1/3">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
          <div style="font-size:15px;font-weight:700"><i class="fas fa-list-check" style="margin-right:8px;color:#f57f17"></i>Barème par type d'incident</div>
          <button onclick="showAddDisciplineRule()" 
            style="background:var(--yiriba-vert);color:white;border:none;border-radius:8px;padding:8px 16px;cursor:pointer;font-size:13px;font-weight:600">
            <i class="fas fa-plus" style="margin-right:6px"></i>Ajouter une règle
          </button>
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <thead>
            <tr style="background:var(--yiriba-vert);color:white">
              <th style="padding:10px 8px;text-align:left;border-radius:8px 0 0 0">Type d'incident</th>
              <th style="padding:10px 8px;text-align:center">Points déduits</th>
              <th style="padding:10px 8px;text-align:left">Description</th>
              <th style="padding:10px 8px;text-align:center">Activé</th>
              <th style="padding:10px 8px;text-align:center;border-radius:0 8px 0 0">Action</th>
            </tr>
          </thead>
          <tbody>
            ${rulesRows || '<tr><td colspan="5" style="padding:20px;text-align:center;color:var(--texte-secondaire)">Aucune règle configurée</td></tr>'}
          </tbody>
        </table>
        <div style="margin-top:12px;padding:10px;background:#fffde7;border-radius:8px;border-left:3px solid #f57f17">
          <div style="font-size:12px;color:#e65100"><i class="fas fa-lightbulb" style="margin-right:4px"></i> Modifiez les points, la description ou activez/désactivez chaque règle, puis cliquez sur <strong>✓</strong> pour enregistrer.</div>
        </div>
      </div>
    </div>
  `;
}

async function saveDisciplineRule(index, incidentType) {
  const pts = parseFloat(document.getElementById(`disc-pts-${index}`).value);
  const desc = document.getElementById(`disc-desc-${index}`).value.trim();
  const active = document.getElementById(`disc-active-${index}`).checked;
  if (isNaN(pts) || pts < 0) { showToast('Points invalides', 'error'); return; }
  try {
    const r = await api('/api/discipline/rules', {
      method: 'PUT',
      body: JSON.stringify({ incident_type: incidentType, points_deducted: pts, description: desc || null, is_active: active })
    });
    if (r?.ok) {
      showToast('Règle enregistrée', 'success');
      loadSettingsDiscipline(document.getElementById('main-content'));
    } else {
      const e = await r.json().catch(() => ({}));
      showToast(e.detail || 'Erreur', 'error');
    }
  } catch (err) { showToast('Erreur: ' + err.message, 'error'); }
}

async function toggleDisciplineRule(index, incidentType, isActive) {
  /* Optimistic: save immediately on toggle */
  const pts = parseFloat(document.getElementById(`disc-pts-${index}`).value);
  const desc = document.getElementById(`disc-desc-${index}`).value.trim();
  try {
    const r = await api('/api/discipline/rules', {
      method: 'PUT',
      body: JSON.stringify({ incident_type: incidentType, points_deducted: pts, description: desc || null, is_active: isActive })
    });
    if (r?.ok) {
      showToast(isActive ? 'Règle activée' : 'Règle désactivée', 'success');
      loadSettingsDiscipline(document.getElementById('main-content'));
    } else {
      showToast('Erreur lors de la mise à jour', 'error');
      loadSettingsDiscipline(document.getElementById('main-content'));
    }
  } catch (err) { showToast('Erreur: ' + err.message, 'error'); loadSettingsDiscipline(document.getElementById('main-content')); }
}

function showAddDisciplineRule() {
  showModal('Ajouter une r\u00e8gle disciplinaire', `
    <div class="modal-form">
      <div class="form-group">
        <label>Type d'incident (code)</label>
        <input id="new-disc-type" placeholder="ex: retards_recurrents" style="width:100%;padding:10px;border:1px solid var(--border);border-radius:8px;font-size:14px">
        <div style="font-size:11px;color:var(--texte-secondaire);margin-top:4px">Pas d'espaces ni caractères spéciaux. Sera affiché avec des underscores remplacés par des espaces.</div>
      </div>
      <div class="form-group">
        <label>Points déduits</label>
        <input id="new-disc-pts" type="number" value="0.5" min="0" max="10" step="0.25" style="width:100%;padding:10px;border:1px solid var(--border);border-radius:8px;font-size:14px">
      </div>
      <div class="form-group">
        <label>Description</label>
        <input id="new-disc-desc" placeholder="ex: Retards récurrents — 0.5 point déduit" style="width:100%;padding:10px;border:1px solid var(--border);border-radius:8px;font-size:14px">
      </div>
    </div>
  `, async () => {
    const type = document.getElementById('new-disc-type').value.trim().toLowerCase().replace(/\s+/g, '_');
    const pts = parseFloat(document.getElementById('new-disc-pts').value);
    const desc = document.getElementById('new-disc-desc').value.trim();
    if (!type) { showToast('Entrez un type d\'incident', 'error'); return; }
    if (isNaN(pts) || pts <= 0) { showToast('Points invalides', 'error'); return; }
    try {
      const r = await api('/api/discipline/rules', {
        method: 'PUT',
        body: JSON.stringify({ incident_type: type, points_deducted: pts, description: desc || null, is_active: true })
      });
      if (r?.ok) {
        showToast('R\u00e8gle cr\u00e9\u00e9e', 'success');
        closeModal();
        loadSettingsDiscipline(document.getElementById('main-content'));
      } else {
        const e = await r.json().catch(() => ({}));
        showToast(e.detail || 'Erreur', 'error');
      }
    } catch (err) { showToast('Erreur: ' + err.message, 'error'); }
  });
}

async function setDisciplineMode(mode) {
  try {
    const r = await api('/api/discipline/mode', {
      method: 'PUT',
      body: JSON.stringify({ mode })
    });
    if (r?.ok) {
      showToast(mode === 'conduct' ? 'Mode Conduite séparée activé' : 'Mode Impact sur moyenne activé', 'success');
      loadSettingsDiscipline(document.getElementById('main-content'));
    }
  } catch (err) { showToast('Erreur: ' + err.message, 'error'); }
}

/* -- Parent Portal ------------------------------------------- */

async function loadParentDashboard() {
  const c = document.getElementById('main-content');
  let children = [];
  try {
    const res = await api('/api/parent/my-children');
    if (res?.ok) children = (await res.json()).children || [];
  } catch {}

  const pName = state.user?.first_name || 'Parent';

  var cardsHtml = '';
  if (children.length > 0) {
    for (var ci = 0; ci < children.length; ci++) {
      var ch = children[ci];
      var initials = ((ch.first_name || '')[0] || '') + ((ch.last_name || '')[0] || '');
      cardsHtml += '<div class="card section-card" style="cursor:pointer" onclick="loadPage(\"p-children\");viewParentChild(' + ch.id + ')">';
      cardsHtml += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">';
      cardsHtml += '<div class="avatar-sm" style="width:40px;height:40px;font-size:14px;background:var(--yiriba-vert);color:white;border-radius:50%;display:flex;align-items:center;justify-content:center">' + initials.toUpperCase() + '</div>';
      cardsHtml += '<div><div style="font-weight:700;font-size:15px">' + (ch.first_name || '') + ' ' + (ch.last_name || '') + '</div>';
      cardsHtml += '<div style="font-size:12px;color:var(--texte-secondaire)">' + (ch.class_name || 'Non assign\u00e9') + '</div></div>';
      cardsHtml += '</div>';
      cardsHtml += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:13px">';
      cardsHtml += '<div><strong style="font-size:11px;color:var(--texte-secondaire)">Matricule</strong><div>' + (ch.matricule || '\u2014') + '</div></div>';
      cardsHtml += '<div><strong style="font-size:11px;color:var(--texte-secondaire)">Statut</strong><div><span class="badge badge-active"><span class="badge-dot"></span>' + (ch.status === 'ACTIVE' ? 'Actif' : ch.status) + '</span></div></div>';
      cardsHtml += '</div></div>';
    }
  }

  c.innerHTML = '<div class="welcome">' +
    '<h1>Bonjour, ' + pName + ' \ud83d\udc4b</h1>' +
    '<p>Voici le suivi de la scolarit\u00e9 de vos enfants.</p>' +
    '</div>' +
    '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px">' +
    cardsHtml +
    '<div class="card section-card" style="display:flex;align-items:center;justify-content:center;min-height:120px;color:var(--texte-secondaire)" onclick="loadPage(\"p-children\")">' +
    '<div style="text-align:center"><i class="fas fa-arrow-right" style="font-size:24px;margin-bottom:8px;display:block"></i>Voir tous mes enfants</div>' +
    '</div></div>';
}

let selectedParentChildId = null;

async function loadParentChildren() {
  const c = document.getElementById('main-content');
  let children = [];
  try {
    const res = await api('/api/parent/my-children');
    if (res?.ok) children = (await res.json()).children || [];
  } catch {}

  if (children.length === 0) {
    c.innerHTML = `
      <div class="welcome"><h1>Mes enfants</h1><p>Suivez la scolarité de vos enfants.</p></div>
      <div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-child"></i></div><h4>Aucun enfant rattaché</h4><p>Contacter l'administration pour rattacher vos enfants à votre compte.</p></div></div>`;
    return;
  }

  // Auto-select first child
  if (!selectedParentChildId || !children.find(ch => ch.id === selectedParentChildId)) {
    selectedParentChildId = children[0].id;
  }

  c.innerHTML = `
    <div class="welcome"><h1>Mes enfants</h1><p>Suivez la scolarité de vos enfants.</p></div>
    <div style="display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap">
      ${children.map(ch => `<button onclick="selectedParentChildId=${ch.id};loadParentChildren()" style="padding:8px 18px;border-radius:20px;border:2px solid ${ch.id === selectedParentChildId ? 'var(--yiriba-vert)' : 'var(--border)'};background:${ch.id === selectedParentChildId ? 'var(--yiriba-vert)' : 'white'};color:${ch.id === selectedParentChildId ? 'white' : 'var(--texte-primaire)'};cursor:pointer;font-weight:600;font-size:13px">
        ${ch.first_name} ${ch.last_name} <span style="font-weight:400;margin-left:4px">${ch.class_name || ''}</span>
      </button>`).join('')}
    </div>
    <div id="parent-child-detail"></div>
  `;

  viewParentChild(selectedParentChildId);
}

async function viewParentChild(studentId) {
  const area = document.getElementById('parent-child-detail');
  if (!area) return;
  selectedParentChildId = studentId;
  area.innerHTML = `<div style="text-align:center;padding:30px"><i class="fas fa-spinner fa-spin" style="font-size:20px"></i> Chargement...</div>`;

  const [discRes, gradesRes, attRes] = await Promise.all([
    api(`/api/parent/children/${studentId}/discipline?period=T1&academic_year=2025-2026`),
    api(`/api/parent/children/${studentId}/grades?period=T1`),
    api(`/api/parent/children/${studentId}/attendance?period=T1`),
  ]);

  let discipline = {}, grades = [], attendance = [];
  if (discRes?.ok) discipline = await discRes.json();
  if (gradesRes?.ok) { const j = await gradesRes.json(); grades = j.grades || []; }
  if (attRes?.ok) { const j = await attRes.json(); attendance = j.attendance || []; }

  const activeRecords = (discipline.records || []).filter(r => r.status === 'active');
  const presentCount = attendance.filter(a => a.status === 'present').length;
  const absentCount = attendance.filter(a => a.status === 'absent').length;
  const lateCount = attendance.filter(a => a.status === 'late').length;
  const totalAtt = attendance.length;
  const avg = grades.length > 0 ? (grades.reduce((s, g) => s + (g.grade || 0), 0) / grades.length).toFixed(2) : '—';

  area.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;margin-bottom:16px">
      <div class="card section-card" style="text-align:center;padding:16px">
        <div style="font-size:12px;text-transform:uppercase;color:var(--texte-secondaire);letter-spacing:0.05em;margin-bottom:4px">Moyenne</div>
        <div style="font-size:28px;font-weight:800;color:var(--yiriba-vert)">${avg}</div>
      </div>
      <div class="card section-card" style="text-align:center;padding:16px">
        <div style="font-size:12px;text-transform:uppercase;color:var(--texte-secondaire);letter-spacing:0.05em;margin-bottom:4px">Présences</div>
        <div style="font-size:28px;font-weight:800;color:var(--yiriba-vert)">${presentCount}</div>
        <div style="font-size:12px;color:var(--texte-secondaire)">sur ${totalAtt} jours</div>
      </div>
      <div class="card section-card" style="text-align:center;padding:16px">
        <div style="font-size:12px;text-transform:uppercase;color:var(--texte-secondaire);letter-spacing:0.05em;margin-bottom:4px">Absences</div>
        <div style="font-size:28px;font-weight:800;color:var(--yiriba-rouge)">${absentCount + lateCount}</div>
      </div>
      <div class="card section-card" style="text-align:center;padding:16px">
        <div style="font-size:12px;text-transform:uppercase;color:var(--texte-secondaire);letter-spacing:0.05em;margin-bottom:4px">Points discipline</div>
        <div style="font-size:28px;font-weight:800;color:${(discipline.total_deductions || 0) > 0 ? 'var(--yiriba-rouge)' : 'var(--yiriba-vert)'}">${discipline.total_deductions ? '-' + discipline.total_deductions : '0'}</div>
      </div>
    </div>

    ${activeRecords.length > 0 ? `
    <div class="card section-card" style="margin-bottom:16px">
      <div style="font-size:15px;font-weight:700;margin-bottom:10px;color:var(--yiriba-rouge)"><i class="fas fa-exclamation-triangle" style="margin-right:6px"></i>Incidents disciplinaires — T1</div>
      <div style="display:flex;flex-direction:column;gap:8px">
        ${activeRecords.map(r => `
          <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:#fff5f5;border-radius:8px;border-left:3px solid var(--yiriba-rouge)">
            <div>
              <div style="font-weight:600;font-size:14px">${r.incident_type.replace(/_/g, ' ')}</div>
              <div style="font-size:12px;color:var(--texte-secondaire)">${r.date ? new Date(r.date).toLocaleDateString('fr-FR') : ''} ${r.note ? '· ' + r.note : ''} ${r.source === 'auto' ? '· Généré automatiquement' : ''}</div>
            </div>
            <div style="color:var(--yiriba-rouge);font-weight:700;font-size:15px">-${r.points_deducted} pt${r.points_deducted > 1 ? 's' : ''}</div>
          </div>
        `).join('')}
      </div>
    </div>
    ` : `
    <div class="card section-card" style="margin-bottom:16px">
      <div style="display:flex;align-items:center;gap:8px;font-size:14px;color:var(--yiriba-vert)"><i class="fas fa-check-circle"></i><strong>Aucun incident disciplinaire</strong></div>
      <div style="font-size:13px;color:var(--texte-secondaire);margin-top:4px">Aucun point déduit pour cette période.</div>
    </div>
    `}

    ${grades.length > 0 ? `
    <div class="card section-card">
      <div style="font-size:15px;font-weight:700;margin-bottom:10px"><i class="fas fa-pen-fancy" style="margin-right:6px;color:var(--yiriba-vert)"></i>Dernières notes — T1</div>
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="background:var(--yiriba-vert);color:white">
          <th style="padding:8px;text-align:left;border-radius:8px 0 0 0">Évaluation</th>
          <th style="padding:8px;text-align:center">Type</th>
          <th style="padding:8px;text-align:center">Note</th>
          <th style="padding:8px;text-align:center;border-radius:0 8px 0 0">Coef.</th>
        </tr></thead>
        <tbody>${grades.slice(0, 10).map(g => `<tr style="border-bottom:1px solid var(--border)"><td style="padding:8px;font-weight:500">${g.evaluation_name}</td><td style="padding:8px;text-align:center"><span class="badge badge-info" style="font-size:11px">${g.assessment_type || 'DM'}</span></td><td style="padding:8px;text-align:center;font-weight:700">${g.grade}/${g.max_grade || 20}</td><td style="padding:8px;text-align:center">${g.coefficient || 1}</td></tr>`).join('')}</tbody>
      </table>
    </div>
    ` : ''}
  `;
}

/* -- Chart ---------------------------------------------------- */
let chartData = { insc: [], pres: [], pay: [] };
const months = ['Sept.','Oct.','Nov.','Déc.','Janv.','Févr.','Mars','Avr.','Mai','Juin','Juil.'];
function renderChart() {
  const el = document.getElementById('chart-area'); if (!el) return;
  // Use real data if available, otherwise empty arrays
  const rawInsc = chartData.insc.length > 0 ? chartData.insc : months.map(() => 0);
  const rawPres = chartData.pres.length > 0 ? chartData.pres : months.map(() => 0);
  const rawPay = chartData.pay.length > 0 ? chartData.pay : months.map(() => 0);
  // Normalize each to 0-100 for visual clarity
  const maxInsc = Math.max(...rawInsc) || 1;
  const maxPres = Math.max(...rawPres) || 1;
  const maxPay = Math.max(...rawPay) || 1;
  const insc = rawInsc.map(v => Math.round((v / maxInsc) * 100));
  const pres = rawPres.map(v => Math.round((v / maxPres) * 100));
  const pay = rawPay.map(v => Math.round((v / maxPay) * 100));
  const max = 100;
  const W=700,H=220,P={t:10,r:20,b:28,l:45};
  const pW=W-P.l-P.r, pH=H-P.t-P.b;

  let grid = '';
  for(let i=0;i<=4;i++){
    const y=P.t+(pH/4)*i, v=Math.round(max-(max/4)*i);
    grid+=`<line x1="${P.l}" y1="${y}" x2="${W-P.r}" y2="${y}" stroke="rgba(8,61,43,0.06)" stroke-width="0.8"/>`;
    grid+=`<text x="${P.l-8}" y="${y+4}" text-anchor="end" font-size="10" fill="#8A9690" font-family="Source Sans 3">${v}%</text>`;
  }
  let xl = '';
  months.forEach((m,i)=>{
    const x=P.l+(i/(months.length-1))*pW;
    xl+=`<text x="${x}" y="${H-6}" text-anchor="middle" font-size="9" fill="#8A9690" font-family="Source Sans 3">${m}</text>`;
  });

  function line(data,color,dashed){
    const pts=data.map((v,i)=>({x:P.l+(i/(data.length-1))*pW,y:P.t+pH-(v/max)*pH}));
    let d=`M${pts[0].x},${pts[0].y}`;
    for(let i=1;i<pts.length;i++){const c1x=pts[i-1].x+(pts[i].x-pts[i-1].x)*.4,c2x=pts[i].x-(pts[i].x-pts[i-1].x)*.4;d+=` C${c1x},${pts[i-1].y} ${c2x},${pts[i].y} ${pts[i].x},${pts[i].y}`;}
    const dash=dashed?'stroke-dasharray="6,4"':'';
    let s=`<path d="${d}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round" ${dash}/>`;
    pts.forEach(p=>{s+=`<circle cx="${p.x}" cy="${p.y}" r="3.5" fill="${color}" stroke="white" stroke-width="2"/>`;});
    return s;
  }

  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:100%" xmlns="http://www.w3.org/2000/svg">${grid}${xl}${line(insc,'#0E5C3F')}${line(pres,'#F2B705',true)}${line(pay,'#2F8F5B')}</svg>`;
}

/* -- Donut ---------------------------------------------------- */
function renderDonut(id, values, labels, colors) {
  const el = document.getElementById(id); if (!el) return;
  const total = values.reduce((a,b)=>a+b,0);
  const pct = values.map(v=>Math.round(v/total*100));
  let grad='', acc=0;
  values.forEach((v,i)=>{const s=(acc/total)*360;acc+=v;const e=(acc/total)*360;grad+=`${colors[i]} ${s}deg ${e}deg`;if(i<values.length-1)grad+=', ';});
  el.innerHTML=`
    <div style="width:100px;height:100px;border-radius:50%;background:conic-gradient(${grad});position:relative;flex-shrink:0">
      <div style="position:absolute;inset:28%;border-radius:50%;background:white;display:grid;place-items:center">
        <div style="text-align:center"><div style="font-family:'Sora',sans-serif;font-size:18px;font-weight:700;color:var(--texte)">${total.toLocaleString('fr-FR')}</div><div style="font-size:9px;color:var(--texte-secondaire);text-transform:uppercase">Total</div></div>
      </div>
    </div>
    <ul style="list-style:none;display:flex;flex-direction:column;gap:6px">
      ${labels.map((l,i)=>`<li style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--texte-secondaire)"><span style="width:8px;height:8px;border-radius:50%;background:${colors[i]};flex-shrink:0"></span>${l} <span style="margin-left:auto;font-weight:600;color:var(--texte);font-family:'Sora',sans-serif">${values[i].toLocaleString('fr-FR')}</span> <span style="font-size:10px;color:var(--texte-secondaire)">(${pct[i]}%)</span></li>`).join('')}
    </ul>`;
}

/* -- Placeholder ---------------------------------------------- */
function loadPlaceholder(p) {
  document.getElementById('main-content').innerHTML=`
    <div class="welcome"><h1>${document.querySelector('.topbar-title').textContent}</h1><p>${document.querySelector('.topbar-subtitle').textContent}</p></div>
    <div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-tools"></i></div><h4>Module en cours de développement</h4><p>L'API est prête et testée.</p><span class="link" onclick="loadPage('dashboard')">← Retour</span></div></div>`;
}

/* -- Time Ago -------------------------------------------------- */
function timeAgo(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "À l'instant";
  if (mins < 60) return `Il y a ${mins} min`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `Il y a ${hrs}h`;
  const days = Math.floor(hrs / 24);
  return `Il y a ${days}j`;
}

/* -- Utils ---------------------------------------------------- */
function showModal(t,h){document.getElementById('modal-title').textContent=t;document.getElementById('modal-body').innerHTML=h;document.getElementById('modal-overlay').style.display='flex'}
/* ==============================================================
   CONFIGURATION ACADEMIQUE
   ============================================================== */
async function loadAcademicYears() {
  const c = document.getElementById('main-content');
  c.innerHTML = '<div style="text-align:center;padding:40px"><i class="fas fa-spinner fa-spin" style="font-size:24px;color:var(--yiriba-vert)"></i></div>';
  try {
    const res = await api('/api/academic-years');
    const years = res?.ok ? (await res.json()).academic_years || [] : [];
    c.innerHTML = `
      <div class="welcome"><h1>Années scolaires</h1><p>Gérez les périodes académiques de votre établissement.</p></div>
      <div style="display:flex;justify-content:flex-end;margin-bottom:16px">
        <button class="btn-add" onclick="showCreateYearModal()"><i class="fas fa-plus"></i> Nouvelle année</button>
      </div>
      <div class="card section-card" style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead><tr style="border-bottom:2px solid var(--border);text-align:left">
            <th style="padding:10px 12px;color:var(--texte-secondaire);font-size:11px;text-transform:uppercase">Année</th>
            <th style="padding:10px 12px;color:var(--texte-secondaire);font-size:11px;text-transform:uppercase">Période</th>
            <th style="padding:10px 12px;color:var(--texte-secondaire);font-size:11px;text-transform:uppercase">Statut</th>
            <th style="padding:10px 12px;color:var(--texte-secondaire);font-size:11px;text-transform:uppercase">Actions</th>
          </tr></thead>
          <tbody>
            ${years.map(ay => {
              const statusColors = { active: 'var(--yiriba-vert)', planned: 'var(--yiriba-jaune)', closed: 'var(--yiriba-text-secondaire)', archived: 'var(--yiriba-text-secondaire)' };
              const statusLabels = { active: 'Active', planned: 'Planifiée', closed: 'Clôturée', archived: 'Archivée' };
              return `<tr style="border-bottom:1px solid var(--border)">
                <td style="padding:10px 12px;font-weight:600">${ay.name}</td>
                <td style="padding:10px 12px;color:var(--texte-secondaire)">${ay.start_date} → ${ay.end_date}</td>
                <td style="padding:10px 12px"><span style="display:inline-block;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:600;background:${statusColors[ay.status] || 'var(--yiriba-text-secondaire)'}22;color:${statusColors[ay.status] || 'var(--yiriba-text-secondaire)'}">${statusLabels[ay.status] || ay.status}${ay.is_current ? ' (courante)' : ''}</span></td>
                <td style="padding:10px 12px">
                  ${ay.status !== 'active' ? `<button class="btn-sm-green" onclick="activateYear(${ay.id})">Activer</button> ` : ''}
                  ${ay.status === 'active' ? `<button style="background:var(--yiriba-jaune);color:#333;border:none;border-radius:6px;padding:5px 12px;font-size:12px;font-weight:600;cursor:pointer" onclick="closeYear(${ay.id})">Clôturer</button>` : ''}
                </td>
              </tr>`;
            }).join('')}
            ${years.length === 0 ? '<tr><td colspan="4" style="padding:30px;text-align:center;color:var(--texte-secondaire)">Aucune année scolaire configurée.</td></tr>' : ''}
          </tbody>
        </table>
      </div>`;
  } catch { c.innerHTML = '<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur de chargement</h4></div></div>'; }
}

function showCreateYearModal() {
  const today = new Date();
  const year = today.getFullYear();
  showModal('Nouvelle année scolaire', `
    <div style="display:flex;flex-direction:column;gap:12px">
      <label style="font-size:13px;font-weight:600">Nom</label>
      <input id="new-year-name" value="${year}-${year+1}" style="padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px">
      <div style="display:flex;gap:12px">
        <div style="flex:1"><label style="font-size:13px;font-weight:600">Début</label><input id="new-year-start" type="date" value="${year}-09-01" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px"></div>
        <div style="flex:1"><label style="font-size:13px;font-weight:600">Fin</label><input id="new-year-end" type="date" value="${year+1}-06-30" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px"></div>
      </div>
      <button class="btn-add" style="width:100%" onclick="createYear()">Créer l'année scolaire</button>
    </div>`);
}

async function createYear() {
  const name = document.getElementById('new-year-name').value;
  const start = document.getElementById('new-year-start').value;
  const end = document.getElementById('new-year-end').value;
  if (!name || !start || !end) return showToast('Remplissez tous les champs', 'error');
  const res = await api(`/api/academic-years?name=${encodeURIComponent(name)}&start_date=${start}&end_date=${end}`, { method: 'POST' });
  if (res?.ok) { closeModal(); showToast('Année créée'); loadAcademicYears(); }
  else { const d = await res.json().catch(()=>({})); showToast(d.detail || 'Erreur', 'error'); }
}

async function activateYear(id) {
  if (!confirm("Activer cette année scolaire ? L'année courante sera clôturée.")) return;
  const res = await api(`/api/academic-years/${id}/activate`, { method: 'POST' });
  if (res?.ok) { showToast('Année activée'); loadAcademicYears(); }
  else showToast('Erreur', 'error');
}

async function closeYear(id) {
  if (!confirm('Clôturer cette année scolaire ?')) return;
  const res = await api(`/api/academic-years/${id}/close`, { method: 'POST' });
  if (res?.ok) { showToast('Année clôturée'); loadAcademicYears(); }
  else showToast('Erreur', 'error');
}

/* -- CONFIGURATION ACADÉMIQUE --------------------------------------- */
async function loadAcademicConfig() {
  const c = document.getElementById('main-content');
  c.innerHTML = '<div style="text-align:center;padding:40px"><i class="fas fa-spinner fa-spin" style="font-size:24px;color:var(--yiriba-vert)"></i></div>';
  let years = [], periods = [];
  try {
    const [yRes, pRes] = await Promise.all([
      api('/api/academic-years'),
      api('/api/academic-periods'),
    ]);
    if (yRes?.ok) years = (await yRes.json()).academic_years || [];
    if (pRes?.ok) periods = (await pRes.json()).periods || [];
  } catch {}
  const currentYear = years.find(y => y.is_current) || years[0];
  const yearOptions = years.map(y => `<option value="${y.id}" ${y.id === currentYear?.id ? 'selected' : ''}>${y.name}${y.is_current ? ' (en cours)' : ''}</option>`).join('');
  const periodTypeLabels = {trimester: 'Trimestres', semester: 'Semestres', custom: 'Personnalisé'};
  const statusColors = {active: 'var(--yiriba-vert)', upcoming: 'var(--yiriba-bleu)', completed: 'var(--yiriba-orange)'};
  const statusLabels = {active: 'En cours', upcoming: 'À venir', completed: 'Terminée'};
  let periodsHtml = '';
  if (periods.length) {
    periodsHtml = periods.map(p => `
      <div style="display:flex;align-items:center;gap:12px;padding:12px 16px;background:white;border:1px solid var(--border);border-radius:10px;transition:all .15s" onmouseover="this.style.borderColor='var(--yiriba-vert)'" onmouseout="this.style.borderColor='var(--border)'">
        <div style="width:10px;height:10px;border-radius:50%;background:${statusColors[p.status] || '#ccc'};flex-shrink:0"></div>
        <div style="flex:1">
          <div style="font-weight:600;font-size:14px;color:var(--texte-primaire)">${p.name}</div>
          <div style="font-size:12px;color:var(--texte-secondaire);margin-top:2px">${p.start_date} → ${p.end_date} · ${periodTypeLabels[p.period_type] || p.period_type}</div>
        </div>
        <span style="font-size:11px;font-weight:600;padding:4px 10px;border-radius:20px;background:${statusColors[p.status] || '#eee'}22;color:${statusColors[p.status] || '#666'};text-transform:capitalize">${statusLabels[p.status] || p.status}</span>
        <button onclick="setPeriodActive(${p.id})" style="padding:4px 10px;border-radius:6px;border:1px solid var(--border);background:white;font-size:11px;cursor:pointer;color:var(--texte-primaire)" title="Définir comme active">● Activer</button>
        <button onclick="deletePeriod(${p.id})" style="padding:4px 10px;border-radius:6px;border:none;background:#fee2e2;color:var(--yiriba-rouge);font-size:11px;cursor:pointer" title="Supprimer">✕</button>
      </div>
    `).join('');
  } else {
    periodsHtml = '<div style="text-align:center;padding:30px;color:var(--texte-secondaire);font-size:13px">Aucune période configurée. Utilisez "Générer automatiquement" ou "Ajouter" ci-dessous.</div>';
  }
  c.innerHTML = `
    <div class="welcome"><h1>Configuration académique</h1><p>Gérez les périodes académiques (trimestres, semestres) de votre établissement.</p></div>
    <div style="display:flex;gap:16px;align-items:center;margin-bottom:20px;flex-wrap:wrap">
      <div style="flex:1;min-width:200px">
        <label style="font-size:12px;font-weight:600;color:var(--texte-secondaire);margin-bottom:4px;display:block">Année scolaire</label>
        <select id="ac-year" style="width:100%;padding:10px;border:1px solid var(--border);border-radius:8px;font-size:14px">${yearOptions}</select>
      </div>
      <button onclick="autoGeneratePeriods()" class="btn-action" style="white-space:nowrap"><i class="fas fa-magic"></i> Générer automatiquement</button>
      <button onclick="showAddPeriodModal()" class="btn-add"><i class="fas fa-plus"></i> Ajouter une période</button>
    </div>
    <div style="display:flex;flex-direction:column;gap:8px">
      ${periodsHtml}
    </div>
  `;
  // Reload when year changes
  document.getElementById('ac-year').addEventListener('change', () => loadAcademicConfig());
}

async function autoGeneratePeriods() {
  const yearId = document.getElementById('ac-year').value;
  showModal('Générer des périodes', `
    <div class="modal-form">
      <div class="form-group"><label>Type de période</label>
        <select id="ac-gen-type"><option value="trimester">Trimestres (3 périodes)</option><option value="semester">Semestres (2 périodes)</option><option value="custom">Personnalisé</option></select>
      </div>
      <div id="ac-gen-custom" style="display:none">
        <div class="form-group"><label>Nom de la période 1</label><input id="ac-gen-n1" value="Période 1"></div>
        <div class="form-group"><label>Nom de la période 2</label><input id="ac-gen-n2" value="Période 2"></div>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="submitAutoGenerate()"><i class="fas fa-magic"></i> Générer</button>
      </div>
    </div>
  `);
  document.getElementById('ac-gen-type').addEventListener('change', function() {
    document.getElementById('ac-gen-custom').style.display = this.value === 'custom' ? 'block' : 'none';
  });
}

async function submitAutoGenerate() {
  const yearId = parseInt(document.getElementById('ac-year').value);
  const type = document.getElementById('ac-gen-type').value;
  let periods = [];
  if (type === 'trimester') {
    periods = [
      {name:'Trimestre 1', period_type:'trimester', start_date:'2025-09-01', end_date:'2025-12-15', order_index:1, status:'active'},
      {name:'Trimestre 2', period_type:'trimester', start_date:'2026-01-05', end_date:'2026-03-31', order_index:2, status:'upcoming'},
      {name:'Trimestre 3', period_type:'trimester', start_date:'2026-04-01', end_date:'2026-06-30', order_index:3, status:'upcoming'},
    ];
  } else if (type === 'semester') {
    periods = [
      {name:'Semestre 1', period_type:'semester', start_date:'2025-09-01', end_date:'2026-01-31', order_index:1, status:'active'},
      {name:'Semestre 2', period_type:'semester', start_date:'2026-02-01', end_date:'2026-06-30', order_index:2, status:'upcoming'},
    ];
  } else {
    const n1 = document.getElementById('ac-gen-n1')?.value || 'Période 1';
    const n2 = document.getElementById('ac-gen-n2')?.value || 'Période 2';
    periods = [
      {name:n1, period_type:'custom', start_date:'2025-09-01', end_date:'2026-01-31', order_index:1, status:'active'},
      {name:n2, period_type:'custom', start_date:'2026-02-01', end_date:'2026-06-30', order_index:2, status:'upcoming'},
    ];
  }
  try {
    const res = await api('/api/academic-periods/bulk', { method: 'POST', body: JSON.stringify({ academic_year_id: yearId, period_type: type, periods }) });
    if (res?.ok) { const d = await res.json(); closeModal(); showToast(d.message || 'Périodes générées'); loadAcademicConfig(); }
    else { const d = await res.json().catch(()=>({})); showToast(d.detail || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

function showAddPeriodModal() {
  showModal('Ajouter une période', `
    <div class="modal-form">
      <div class="form-group"><label>Nom</label><input id="ac-p-name" placeholder="Ex: Trimestre 1"></div>
      <div class="form-group"><label>Type</label><select id="ac-p-type"><option value="trimester">Trimestre</option><option value="semester">Semestre</option><option value="custom">Personnalisé</option></select></div>
      <div class="form-row">
        <div class="form-group"><label>Date début</label><input id="ac-p-start" type="date"></div>
        <div class="form-group"><label>Date fin</label><input id="ac-p-end" type="date"></div>
      </div>
      <div class="form-group"><label>Ordre</label><input id="ac-p-order" type="number" value="1" min="1"></div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="submitAddPeriod()"><i class="fas fa-plus"></i> Ajouter</button>
      </div>
    </div>
  `);
}

async function submitAddPeriod() {
  const data = {
    name: document.getElementById('ac-p-name').value.trim(),
    period_type: document.getElementById('ac-p-type').value,
    start_date: document.getElementById('ac-p-start').value,
    end_date: document.getElementById('ac-p-end').value,
    order_index: parseInt(document.getElementById('ac-p-order').value) || 1,
  };
  if (!data.name || !data.start_date || !data.end_date) { showToast('Remplissez les champs requis', 'error'); return; }
  try {
    const res = await api('/api/academic-periods', { method: 'POST', body: JSON.stringify(data) });
    if (res?.ok) { closeModal(); showToast('Période ajoutée'); loadAcademicConfig(); }
    else { const d = await res.json().catch(()=>({})); showToast(d.detail || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

async function setPeriodActive(periodId) {
  // First get all periods to find the year_id
  try {
    const periods = [];
    const res = await api('/api/academic-periods');
    if (res?.ok) {
      const data = await res.json();
      const allPeriods = data.periods || [];
      // Set all to their default status, then activate this one
      for (const p of allPeriods) {
        const newStatus = p.id === periodId ? 'active' : (p.status === 'active' ? 'upcoming' : p.status);
        if (newStatus !== p.status) {
          await api(`/api/academic-periods/${p.id}`, { method: 'PUT', body: JSON.stringify({ status: newStatus }) });
        }
      }
      showToast('Période activée');
      loadAcademicConfig();
    }
  } catch { showToast('Erreur', 'error'); }
}

async function deletePeriod(id) {
  if (!confirm('Supprimer cette période ?')) return;
  try {
    const res = await api(`/api/academic-periods/${id}`, { method: 'DELETE' });
    if (res?.ok) { showToast('Période supprimée'); loadAcademicConfig(); }
    else { const d = await res.json().catch(()=>({})); showToast(d.detail || 'Impossible de supprimer', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

/* -- CYCLES & NIVEAUX --------------------------------------- */
async function loadCycles() {
  const c = document.getElementById('main-content');
  c.innerHTML = '<div style="text-align:center;padding:40px"><i class="fas fa-spinner fa-spin" style="font-size:24px;color:var(--yiriba-vert)"></i></div>';
  try {
    const res = await api('/api/cycles');
    const cycles = res?.ok ? (await res.json()).cycles || [] : [];
    c.innerHTML = `
      <div class="welcome"><h1>Cycles & Niveaux</h1><p>Organisez la hiérarchie pédagogique de votre établissement.</p></div>
      <div style="display:flex;gap:12px;margin-bottom:20px">
        <button class="btn-add" onclick="showCreateCycleModal()"><i class="fas fa-plus"></i> Nouveau cycle</button>
        <button class="btn-add" onclick="showCreateLevelModal()"><i class="fas fa-plus"></i> Nouveau niveau</button>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px">
        ${cycles.map(cy => `
          <div class="card section-card" style="padding:20px">
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
              <div style="width:40px;height:40px;border-radius:10px;background:var(--yiriba-vert-profond);color:white;display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700">${cy.name.charAt(0)}</div>
              <div><h3 style="margin:0;font-size:16px;font-weight:600">${cy.name}</h3><p style="margin:2px 0 0;font-size:12px;color:var(--texte-secondaire)">${cy.code} — ${cy.levels.length} niveau(x)</p></div>
            </div>
            ${cy.levels.length > 0 ? `<div style="display:flex;flex-wrap:wrap;gap:6px">
              ${cy.levels.map(l => `<span style="display:inline-block;padding:4px 10px;border-radius:6px;font-size:12px;font-weight:500;background:var(--yiriba-ivoire);color:var(--yiriba-vert-profond);border:1px solid var(--border)">${l.name}</span>`).join('')}
            </div>` : '<p style="font-size:12px;color:var(--texte-secondaire)">Aucun niveau</p>'}
          </div>
        `).join('')}
        ${cycles.length === 0 ? '<div class="card section-card" style="grid-column:1/-1"><div class="empty"><div class="empty-icon"><i class="fas fa-layer-group"></i></div><h4>Aucun cycle configuré</h4><p>Créez vos cycles (Primaire, Collège, Lycée) pour commencer.</p></div></div>' : ''}
      </div>`;
  } catch { c.innerHTML = '<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>'; }
}

function showCreateCycleModal() {
  showModal('Nouveau cycle', `
    <div style="display:flex;flex-direction:column;gap:12px">
      <label style="font-size:13px;font-weight:600">Nom</label>
      <input id="new-cycle-name" placeholder="Ex: Collège" style="padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px">
      <label style="font-size:13px;font-weight:600">Code</label>
      <input id="new-cycle-code" placeholder="Ex: college" style="padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px">
      <button class="btn-add" style="width:100%" onclick="createCycle()">Créer</button>
    </div>`);
}

async function createCycle() {
  const name = document.getElementById('new-cycle-name').value;
  const code = document.getElementById('new-cycle-code').value.toLowerCase().trim();
  if (!name || !code) return showToast('Remplissez tous les champs', 'error');
  const res = await api('/api/cycles', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({name, code}) });
  if (res?.ok) { closeModal(); showToast('Cycle créé'); loadCycles(); }
  else { const d = await res.json().catch(()=>({})); showToast(d.detail || 'Erreur', 'error'); }
}

function showCreateLevelModal() {
  showModal('Nouveau niveau', `
    <div style="display:flex;flex-direction:column;gap:12px">
      <label style="font-size:13px;font-weight:600">Cycle parent</label>
      <select id="new-level-cycle" style="padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px"><option value="">Chargement...</option></select>
      <label style="font-size:13px;font-weight:600">Nom</label>
      <input id="new-level-name" placeholder="Ex: 6ème" style="padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px">
      <label style="font-size:13px;font-weight:600">Code</label>
      <input id="new-level-code" placeholder="Ex: 6eme" style="padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px">
      <button class="btn-add" style="width:100%" onclick="createLevel()">Créer</button>
    </div>`);
  api('/api/cycles').then(async res => {
    if (res?.ok) {
      const cycles = (await res.json()).cycles || [];
      document.getElementById('new-level-cycle').innerHTML = cycles.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
    }
  });
}

async function createLevel() {
  const cycle_id = parseInt(document.getElementById('new-level-cycle').value);
  const name = document.getElementById('new-level-name').value;
  const code = document.getElementById('new-level-code').value.toLowerCase().trim();
  if (!cycle_id || !name || !code) return showToast('Remplissez tous les champs', 'error');
  const res = await api('/api/levels', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({cycle_id, name, code}) });
  if (res?.ok) { closeModal(); showToast('Niveau créé'); loadCycles(); }
  else { const d = await res.json().catch(()=>({})); showToast(d.detail || 'Erreur', 'error'); }
}

/* -- MATIÈRES PAR CLASSE ------------------------------------ */
async function loadClassSubjectsConfig() {
  const c = document.getElementById('main-content');
  c.innerHTML = '<div style="text-align:center;padding:40px"><i class="fas fa-spinner fa-spin" style="font-size:24px;color:var(--yiriba-vert)"></i></div>';
  try {
    const [clRes, sRes] = await Promise.all([api('/api/classes?per_page=200'), api('/api/subjects')]);
    const classes = clRes?.ok ? (await clRes.json()).classes || [] : [];
    const subjects = sRes?.ok ? (await sRes.json()).subjects || [] : [];
    if (classes.length === 0) { c.innerHTML = '<div class="welcome"><h1>Matières par classe</h1><p>Configurez les matières et coefficients de chaque classe.</p></div><div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-chalkboard"></i></div><h4>Aucune classe</h4><p>Créez des classes d\'abord dans la section Classes.</p></div></div>'; return; }
    c.innerHTML = `
      <div class="welcome"><h1>Matières par classe</h1><p>Configurez les matières et coefficients de chaque classe.</p></div>
      <div class="card section-card" style="padding:20px;margin-bottom:16px">
        <label style="font-size:13px;font-weight:600;color:var(--texte-secondaire)">Sélectionnez une classe</label>
        <select id="cs-class-select" style="margin-top:6px;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;width:300px" onchange="loadClassSubjectsForClass(this.value)">
          <option value="">-- Choisir une classe --</option>
          ${classes.map(cl => `<option value="${cl.id}">${escapeHtml(cl.name)} (${cl.academic_year || ''})</option>`).join('')}
        </select>
      </div>
      <div id="cs-detail"></div>`;
    window._subjectsList = subjects;
  } catch { c.innerHTML = '<div class="card section-card"><div class="empty"><div class="empty-icon"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>'; }
}

async function loadClassSubjectsForClass(classId) {
  const det = document.getElementById('cs-detail');
  if (!classId) { det.innerHTML = ''; return; }
  det.innerHTML = '<div style="text-align:center;padding:20px"><i class="fas fa-spinner fa-spin" style="color:var(--yiriba-vert)"></i></div>';
  try {
    const res = await api(`/api/class-subjects?class_id=${classId}`);
    const css = res?.ok ? (await res.json()).class_subjects || [] : [];
    const allSubjects = window._subjectsList || [];
    det.innerHTML = `
      <div class="card section-card" style="padding:20px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
          <h3 style="margin:0;font-size:15px;font-weight:600">Matières configurées (${css.length})</h3>
          <button class="btn-add" onclick="showAddSubjectModal(${classId})"><i class="fas fa-plus"></i> Ajouter une matière</button>
        </div>
        ${css.length > 0 ? `<table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead><tr style="border-bottom:2px solid var(--border);text-align:left">
            <th style="padding:8px 10px;color:var(--texte-secondaire);font-size:11px;text-transform:uppercase">Matière</th>
            <th style="padding:8px 10px;color:var(--texte-secondaire);font-size:11px;text-transform:uppercase">Coefficient</th>
            <th style="padding:8px 10px;color:var(--texte-secondaire);font-size:11px;text-transform:uppercase">Barème</th>
            <th style="padding:8px 10px;color:var(--texte-secondaire);font-size:11px;text-transform:uppercase">H/Semaine</th>
            <th style="padding:8px 10px;color:var(--texte-secondaire);font-size:11px;text-transform:uppercase">Actions</th>
          </tr></thead>
          <tbody>
            ${css.map(cs => `<tr style="border-bottom:1px solid var(--border)">
              <td style="padding:8px 10px;font-weight:600">${cs.subject_name}</td>
              <td style="padding:8px 10px"><input type="number" min="1" max="10" value="${cs.coefficient}" style="width:50px;padding:4px 8px;border:1px solid var(--border);border-radius:6px;font-size:13px;text-align:center" onchange="updateCS(${cs.id},'coefficient',this.value)"></td>
              <td style="padding:8px 10px"><input type="number" min="1" value="${cs.max_score}" style="width:60px;padding:4px 8px;border:1px solid var(--border);border-radius:6px;font-size:13px;text-align:center" onchange="updateCS(${cs.id},'max_score',this.value)"></td>
              <td style="padding:8px 10px"><input type="number" min="0" step="0.5" value="${cs.hours_per_week || ''}" placeholder="--" style="width:60px;padding:4px 8px;border:1px solid var(--border);border-radius:6px;font-size:13px;text-align:center" onchange="updateCS(${cs.id},'hours_per_week',this.value)"></td>
              <td style="padding:8px 10px"><button style="background:none;border:none;color:var(--yiriba-rouge);cursor:pointer;font-size:13px" onclick="deleteCS(${cs.id},${classId})"><i class="fas fa-trash"></i></button></td>
            </tr>`).join('')}
          </tbody>
        </table>` : '<div class="empty" style="padding:20px"><div class="empty-icon"><i class="fas fa-book-open"></i></div><h4>Aucune matière configurée</h4><p>Ajoutez des matières à cette classe.</p></div>'}
      </div>`;
  } catch { det.innerHTML = '<p style="color:var(--yiriba-rouge)">Erreur de chargement</p>'; }
}

function showAddSubjectModal(classId) {
  const allSubjects = window._subjectsList || [];
  showModal('Ajouter une matière', `
    <div style="display:flex;flex-direction:column;gap:12px">
      <label style="font-size:13px;font-weight:600">Matière</label>
      <div style="display:flex;gap:8px">
        <select id="add-cs-subject" style="flex:1;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px">
          ${allSubjects.length > 0 ? allSubjects.map(s => `<option value="${s.id}">${s.name}</option>`).join('') : '<option value="" disabled selected>Aucune matière — créez-en une ci-dessous</option>'}
        </select>
      </div>
      <div style="background:var(--yiriba-ivoire);border-radius:8px;padding:12px;margin-top:4px">
        <div style="font-size:12px;font-weight:600;color:var(--yiriba-text-secondaire);margin-bottom:8px"><i class="fas fa-plus-circle" style="margin-right:4px"></i>Créer une nouvelle matière</div>
        <div style="display:flex;gap:8px">
          <input id="new-subject-name" placeholder="Nom (ex: Mathématiques)" style="flex:1;padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:12px">
          <input id="new-subject-code" placeholder="Code (ex: MATH)" style="width:80px;padding:6px 10px;border:1px solid var(--border);border-radius:6px;font-size:12px;text-transform:uppercase">
          <button onclick="quickCreateSubject(${classId})" style="padding:6px 12px;background:var(--yiriba-vert);color:white;border:none;border-radius:6px;font-size:12px;cursor:pointer;white-space:nowrap">Créer</button>
        </div>
      </div>
      <div style="display:flex;gap:12px">
        <div style="flex:1"><label style="font-size:13px;font-weight:600">Coefficient</label><input id="add-cs-coef" type="number" min="1" max="10" value="1" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px"></div>
        <div style="flex:1"><label style="font-size:13px;font-weight:600">Barème</label><input id="add-cs-max" type="number" min="1" value="20" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px"></div>
      </div>
      <div style="flex:1"><label style="font-size:13px;font-weight:600">Heures/semaine</label><input id="add-cs-hours" type="number" min="0" step="0.5" placeholder="Optionnel" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px"></div>
      <button class="btn-add" style="width:100%" onclick="addCS(${classId})">Ajouter</button>
    </div>`);
}

async function quickCreateSubject(classId) {
  const name = document.getElementById('new-subject-name').value.trim();
  const code = document.getElementById('new-subject-code').value.trim().toUpperCase();
  if (!name || !code) { showToast('Nom et code requis', 'error'); return; }
  try {
    const res = await api('/api/subjects', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({name, code}) });
    if (res?.ok) {
      const newSubject = await res.json();
      window._subjectsList = [...(window._subjectsList || []), {id: newSubject.id, name, code}];
      showToast('Matière créée');
      // Refresh the modal with updated list
      showAddSubjectModal(classId);
      // Auto-select the new subject
      setTimeout(() => { const sel = document.getElementById('add-cs-subject'); if (sel) sel.value = newSubject.id; }, 100);
    } else {
      const d = await res.json().catch(()=>({}));
      showToast(d.detail || 'Erreur lors de la création', 'error');
    }
  } catch { showToast('Erreur réseau', 'error'); }
}

async function addCS(classId) {
  const subject_id = parseInt(document.getElementById('add-cs-subject').value);
  const coefficient = parseInt(document.getElementById('add-cs-coef').value) || 1;
  const max_score = parseFloat(document.getElementById('add-cs-max').value) || 20;
  const hours = parseFloat(document.getElementById('add-cs-hours').value) || null;
  const res = await api('/api/class-subjects', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({class_id: classId, subject_id, coefficient, max_score, hours_per_week: hours}) });
  if (res?.ok) { closeModal(); showToast('Matière ajoutée'); loadClassSubjectsForClass(classId); }
  else { const d = await res.json().catch(()=>({})); showToast(d.detail || 'Erreur', 'error'); }
}

async function updateCS(csId, field, value) {
  const body = {};
  body[field] = field === 'hours_per_week' ? (value ? parseFloat(value) : null) : (field === 'coefficient' ? parseInt(value) : parseFloat(value));
  const res = await api(`/api/class-subjects/${csId}`, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
  if (res?.ok) showToast('Mis à jour');
  else showToast('Erreur', 'error');
}

async function deleteCS(csId, classId) {
  if (!confirm('Supprimer cette matière de la classe ?')) return;
  const res = await api(`/api/class-subjects/${csId}`, { method: 'DELETE' });
  if (res?.ok) { showToast('Supprimé'); loadClassSubjectsForClass(classId); }
  else showToast('Erreur', 'error');
}

/* ==============================================================
/* ================================================================
/* ================================================================
   MODULE EMPLOI DU TEMPS — Planning semaine Yiriba
   ================================================================ */
const TT_DAYS = ['Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi','Dimanche'];
const TT_COLORS = ['#0E5C3F','#2F8F5B','#F2B705','#C94A35','#3A7BBF','#8B5CF6','#B06000','#0891B2'];
let _ttData = { entries: [], classes: [], subjects: [], teachers: [], timeSlots: [], classSubjects: {} };

async function loadTimetable() {
  const c = document.getElementById('main-content');
  c.innerHTML = yiribaLoading();
  try {
    const [ttRes, clRes, sRes, tRes, tsRes] = await Promise.all([
      api('/api/timetable'),
      api('/api/classes?per_page=200'),
      api('/api/subjects'),
      api('/api/admin/users?role_type=teacher&per_page=100'),
      api('/api/timetable/slots'),
    ]);
    _ttData.entries = ttRes?.ok ? (await ttRes.json()).timetable || [] : [];
    _ttData.classes = clRes?.ok ? (await clRes.json()).classes || [] : [];
    _ttData.subjects = sRes?.ok ? (await sRes.json()).subjects || [] : [];
    _ttData.teachers = tRes?.ok ? (await tRes.json()).users || [] : [];
    _ttData.timeSlots = tsRes?.ok ? (await tsRes.json()).time_slots || [] : [];
  } catch {}

  const classId = _ttData.classes[0]?.id || '';
  renderTimetable(classId);
}

async function loadClassSubjects(classId) {
  if (!classId || _ttData.classSubjects[classId]) return _ttData.classSubjects[classId] || [];
  try {
    const res = await api('/api/class-subjects?class_id=' + classId);
    if (res?.ok) {
      const data = await res.json();
      _ttData.classSubjects[classId] = data.class_subjects || data || [];
      return _ttData.classSubjects[classId];
    }
  } catch {}
  return [];
}

function getSubjectsForClass(classId) {
  const csList = _ttData.classSubjects[classId] || [];
  if (csList.length === 0) return _ttData.subjects;
  return _ttData.subjects.filter(s => csList.some(cs => cs.subject_id === s.id));
}

function renderTimetable(classId) {
  const c = document.getElementById('main-content');
  const entries = _ttData.entries.filter(e => !classId || e.class_id == classId);
  const classes = _ttData.classes;
  const subjects = _ttData.subjects;
  const teachers = _ttData.teachers;
  const slots = _ttData.timeSlots;

  // Use configured time slots, or fallback to unique start_times from entries
  let hours = slots.length > 0 ? slots.map(s => ({ label: s.label || (s.start_time + '-' + s.end_time), start: s.start_time, end: s.end_time })) : [];
  // Also include hours from existing entries that aren't in configured slots
  const entryTimes = [...new Set(entries.map(e => e.start_time))].sort();
  entryTimes.forEach(t => { if (!hours.some(h => h.start === t)) hours.push({ label: t, start: t, end: '' }); });
  hours.sort((a, b) => a.start.localeCompare(b.start));
  if (hours.length === 0) hours = [{ label: '08:00', start: '08:00', end: '09:00' }];

  // Build grid
  let gridHtml = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px;min-width:900px">';
  gridHtml += '<thead><tr><th style="width:100px;padding:8px;background:var(--yiriba-vert);color:white;border-radius:8px 0 0 0"></th>';
  TT_DAYS.forEach(d => { gridHtml += '<th style="padding:8px;background:var(--yiriba-vert);color:white;font-weight:600;font-size:11px;text-transform:uppercase">' + d + '</th>'; });
  gridHtml += '</tr></thead><tbody>';

  hours.forEach(h => {
    gridHtml += '<tr><td style="padding:6px 8px;border:1px solid var(--border);background:var(--yiriba-ivoire);font-weight:600;font-size:11px;white-space:nowrap">' + h.label + '</td>';
    for (let d = 0; d < 7; d++) {
      const entry = entries.find(e => e.day_of_week === d && e.start_time === h.start);
      const sub = entry ? subjects.find(s => s.id === entry.subject_id) : null;
      const teacher = entry ? teachers.find(t => t.id === entry.teacher_id) : null;
      const colorIdx = entry ? (entry.subject_id % TT_COLORS.length) : 0;
      if (entry && sub) {
        gridHtml += '<td style="padding:4px;border:1px solid var(--border);background:' + TT_COLORS[colorIdx] + '15;border-left:3px solid ' + TT_COLORS[colorIdx] + ';position:relative;cursor:pointer" onclick="showEditTTModal(' + entry.id + ')">';
        gridHtml += '<div style="font-weight:700;font-size:12px;color:' + TT_COLORS[colorIdx] + '">' + sub.name + '</div>';
        if (teacher) gridHtml += '<div style="font-size:10px;color:var(--texte-secondaire);margin-top:2px">' + teacher.first_name + ' ' + teacher.last_name + '</div>';
        if (entry.room) gridHtml += '<div style="font-size:10px;color:var(--texte-secondaire)"><i class="fas fa-location-dot" style="margin-right:2px"></i>' + entry.room + '</div>';
        gridHtml += '<button onclick="event.stopPropagation();deleteTT(' + entry.id + ')" style="position:absolute;top:2px;right:2px;background:none;border:none;color:var(--yiriba-rouge);cursor:pointer;font-size:10px;opacity:0.6" title="Supprimer"><i class="fas fa-times"></i></button>';
        gridHtml += '</td>';
      } else {
        gridHtml += '<td style="padding:4px;border:1px solid var(--border);cursor:pointer" onclick="showAddTTModal(' + d + ',\'' + h.start + '\',' + classId + ')"><div style="text-align:center;color:var(--border);font-size:16px;opacity:0.3">+</div></td>';
      }
    }
    gridHtml += '</tr>';
  });
  gridHtml += '</tbody></table></div>';

  c.innerHTML = '';
  const welcome = document.createElement('div');
  welcome.className = 'welcome';
  welcome.innerHTML = '<h1>Emploi du temps</h1><p>Planifiez les cours de votre etablissement.</p>';
  c.appendChild(welcome);

  const toolbar = document.createElement('div');
  toolbar.className = 'page-toolbar';
  toolbar.innerHTML = '<div style="display:flex;align-items:center;gap:12px"><select class="filter-select" id="tt-class" onchange="onTTClassChange(this.value)">' +
    '<option value="">Toutes les classes</option>' +
    classes.map(cl => '<option value="' + cl.id + '" ' + (cl.id == classId ? 'selected' : '') + '>' + cl.name + '</option>').join('') +
    '</select></div><div style="display:flex;gap:8px"><button class="btn-secondary" onclick="showTimeSlotModal()"><i class="fas fa-clock"></i> Horaires</button>' +
    '<button class="btn-add" onclick="showAddTTModal(null,null,' + classId + ')"><i class="fas fa-plus"></i> Ajouter un cours</button></div>';
  c.appendChild(toolbar);

  const card = document.createElement('div');
  card.className = 'card section-card';
  card.style.cssText = 'padding:16px;margin-top:16px';
  card.innerHTML = gridHtml;
  c.appendChild(card);

  const legend = document.createElement('div');
  legend.style.cssText = 'margin-top:12px;display:flex;gap:16px;flex-wrap:wrap;font-size:11px;color:var(--texte-secondaire)';
  legend.innerHTML = subjects.map((s, i) => '<span><span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:' + TT_COLORS[i % TT_COLORS.length] + ';margin-right:4px"></span>' + s.name + '</span>').join('');
  c.appendChild(legend);
}

async function onTTClassChange(classId) {
  if (classId) await loadClassSubjects(classId);
  renderTimetable(classId);
}

function showTimeSlotModal() {
  const slots = _ttData.timeSlots;
  let rowsHtml = '';
  slots.forEach(s => {
    rowsHtml += '<tr><td style="padding:6px;border-bottom:1px solid var(--border)">' + s.label + '</td>';
    rowsHtml += '<td style="padding:6px;border-bottom:1px solid var(--border)">' + s.start_time + '</td>';
    rowsHtml += '<td style="padding:6px;border-bottom:1px solid var(--border)">' + s.end_time + '</td>';
    rowsHtml += '<td style="padding:6px;border-bottom:1px solid var(--border);text-align:center"><button onclick="deleteTimeSlot(' + s.id + ')" style="color:var(--yiriba-rouge);background:none;border:none;cursor:pointer"><i class="fas fa-trash"></i></button></td></tr>';
  });
  showModal('Horaires de l\'ecole', '<div class="modal-form">' +
    '<p style="margin:0 0 12px;color:var(--texte-secondaire);font-size:13px">Definissez les creneaux horaires de votre etablissement.</p>' +
    '<table style="width:100%;border-collapse:collapse;font-size:13px">' +
    '<thead><tr style="background:var(--yiriba-ivoire)"><th style="padding:6px 8px;text-align:left">Libelle</th><th style="padding:6px 8px;text-align:left">Debut</th><th style="padding:6px 8px;text-align:left">Fin</th><th style="padding:6px 8px"></th></tr></thead>' +
    '<tbody id="tt-slots-body">' + rowsHtml + '</tbody></table>' +
    '<div style="margin-top:12px;display:flex;gap:8px;align-items:end;flex-wrap:wrap">' +
    '<div class="form-group" style="flex:1;min-width:120px"><label style="font-size:12px">Libelle</label><input id="ts-label" placeholder="Ex: 08:00-09:00" style="font-size:13px"></div>' +
    '<div class="form-group" style="width:100px"><label style="font-size:12px">Debut</label><input id="ts-start" type="time" value="08:00" style="font-size:13px"></div>' +
    '<div class="form-group" style="width:100px"><label style="font-size:12px">Fin</label><input id="ts-end" type="time" value="09:00" style="font-size:13px"></div>' +
    '<button class="btn-add" onclick="addTimeSlot()" style="height:36px"><i class="fas fa-plus"></i> Ajouter</button></div>' +
    '<div class="modal-footer"><button class="btn-secondary" onclick="closeModal()">Fermer</button></div></div>');
}

async function addTimeSlot() {
  const label = document.getElementById('ts-label').value.trim();
  const start = document.getElementById('ts-start').value;
  const end = document.getElementById('ts-end').value;
  if (!label || !start || !end) { showToast('Remplissez tous les champs', 'error'); return; }
  try {
    const res = await api('/api/timetable/slots', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ label: label, start_time: start, end_time: end }) });
    if (res?.ok) { showToast('Creneau ajoute'); loadTimetable(); setTimeout(() => showTimeSlotModal(), 300); }
    else { const d = await res.json().catch(()=>({})); showToast(d.detail || 'Erreur', 'error'); }
  } catch { showToast('Erreur reseau', 'error'); }
}

async function deleteTimeSlot(id) {
  if (!confirm('Supprimer ce creneau ?')) return;
  try {
    const res = await api('/api/timetable/slots/' + id, { method: 'DELETE' });
    if (res?.ok || res?.status === 204) { showToast('Creneau supprime'); loadTimetable(); setTimeout(() => showTimeSlotModal(), 300); }
  } catch { showToast('Erreur', 'error'); }
}

function showAddTTModal(day, startTime, classId) {
  const classes = _ttData.classes;
  const classIdVal = classId || (classes[0] && classes[0].id) || '';
  loadClassSubjects(classIdVal);
  const subjects = getSubjectsForClass(classIdVal);
  const teachers = _ttData.teachers;
  const slots = _ttData.timeSlots;
  const slotOptions = slots.length > 0 ? slots.map(s => '<option value="' + s.start_time + '" data-end="' + s.end_time + '">' + s.label + '</option>').join('') :
    ['07:00','08:00','09:00','10:00','11:00','12:00','13:00','14:00','15:00','16:00','17:00'].map(h => '<option value="' + h + '" data-end="' + (parseInt(h)+1).toString().padStart(2,'0') + ':00">' + h + '</option>').join('');
  showModal('Ajouter un cours', '<div class="modal-form">' +
    '<div class="form-row"><div class="form-group"><label>Classe</label><select id="tt-class-id" onchange="onTTModalClassChange()">' +
    classes.map(cl => '<option value="' + cl.id + '" ' + (cl.id == classIdVal ? 'selected' : '') + '>' + cl.name + '</option>').join('') +
    '</select></div><div class="form-group"><label>Matiere</label><select id="tt-subject-id" onchange="onTTModalSubjectChange()">' +
    subjects.map(s => '<option value="' + s.id + '">' + s.name + '</option>').join('') +
    '</select></div></div>' +
    '<div class="form-row"><div class="form-group"><label>Jour</label><select id="tt-day">' +
    TT_DAYS.map((d, i) => '<option value="' + i + '" ' + (i === (day || 0) ? 'selected' : '') + '>' + d + '</option>').join('') +
    '</select></div><div class="form-group"><label>Creneau</label><select id="tt-slot">' +
    slotOptions + '</select></div></div>' +
    '<div class="form-row"><div class="form-group"><label>Enseignant</label><select id="tt-teacher"><option value="">-- Optionnel --</option>' +
    teachers.map(t => '<option value="' + t.id + '">' + t.first_name + ' ' + t.last_name + '</option>').join('') +
    '</select></div><div class="form-group"><label>Salle</label><input id="tt-room" placeholder="Ex: A101"></div></div>' +
    '<div class="modal-footer"><button class="btn-secondary" onclick="closeModal()">Annuler</button>' +
    '<button class="btn-add" onclick="submitTT()"><i class="fas fa-plus"></i> Ajouter</button></div></div>');
  if (startTime) document.getElementById('tt-slot').value = startTime;
}

function onTTModalClassChange() {
  const classId = parseInt(document.getElementById('tt-class-id').value);
  loadClassSubjects(classId);
  const subjects = getSubjectsForClass(classId);
  const sel = document.getElementById('tt-subject-id');
  sel.innerHTML = subjects.map(s => '<option value="' + s.id + '">' + s.name + '</option>').join('');
  onTTModalSubjectChange();
}

function onTTModalSubjectChange() {
  const classId = parseInt(document.getElementById('tt-class-id').value);
  const subjectId = parseInt(document.getElementById('tt-subject-id').value);
  const csList = _ttData.classSubjects[classId] || [];
  const cs = csList.find(c => c.subject_id === subjectId);
  const sel = document.getElementById('tt-teacher');
  if (cs && cs.teacher_id) {
    const t = _ttData.teachers.find(t => t.id === cs.teacher_id);
    sel.innerHTML = t ? '<option value="' + t.id + '" selected>' + t.first_name + ' ' + t.last_name + '</option><option value="">-- Autre --</option>' : '<option value="">-- Optionnel --</option>' + _ttData.teachers.map(t => '<option value="' + t.id + '">' + t.first_name + ' ' + t.last_name + '</option>').join('');
  } else {
    sel.innerHTML = '<option value="">-- Optionnel --</option>' + _ttData.teachers.map(t => '<option value="' + t.id + '">' + t.first_name + ' ' + t.last_name + '</option>').join('');
  }
}

async function submitTT() {
  const classId = parseInt(document.getElementById('tt-class-id').value);
  const subjectId = parseInt(document.getElementById('tt-subject-id').value);
  const slotEl = document.getElementById('tt-slot');
  const opt = slotEl.options[slotEl.selectedIndex];
  const startTime = slotEl.value;
  const endTime = opt && opt.dataset.end ? opt.dataset.end : startTime;
  const data = {
    class_id: classId,
    subject_id: subjectId,
    teacher_id: parseInt(document.getElementById('tt-teacher').value) || null,
    day_of_week: parseInt(document.getElementById('tt-day').value),
    start_time: startTime,
    end_time: endTime,
    room: document.getElementById('tt-room').value.trim() || null,
  };
  try {
    const res = await api('/api/timetable', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
    if (res?.ok) { closeModal(); showToast('Cours ajoute'); loadTimetable(); }
    else { const d = await res.json().catch(()=>({})); showToast(d.detail || 'Erreur', 'error'); }
  } catch { showToast('Erreur reseau', 'error'); }
}

async function showEditTTModal(id) {
  const entry = _ttData.entries.find(e => e.id === id);
  if (!entry) return;
  const classes = _ttData.classes;
  const subjects = _ttData.subjects;
  const teachers = _ttData.teachers;
  const slots = _ttData.timeSlots;
  const slotOptions = slots.length > 0 ? slots.map(s => '<option value="' + s.start_time + '" data-end="' + s.end_time + '"' + (s.start_time === entry.start_time ? ' selected' : '') + '>' + s.label + '</option>').join('') :
    ['07:00','08:00','09:00','10:00','11:00','12:00','13:00','14:00','15:00','16:00','17:00'].map(h => '<option value="' + h + '"' + (h === entry.start_time ? ' selected' : '') + '>' + h + '</option>').join('');
  showModal('Modifier le cours', '<div class="modal-form">' +
    '<div class="form-row"><div class="form-group"><label>Classe</label><select id="tt-class-id">' +
    classes.map(cl => '<option value="' + cl.id + '" ' + (cl.id === entry.class_id ? 'selected' : '') + '>' + cl.name + '</option>').join('') +
    '</select></div><div class="form-group"><label>Matiere</label><select id="tt-subject-id">' +
    subjects.map(s => '<option value="' + s.id + '" ' + (s.id === entry.subject_id ? 'selected' : '') + '>' + s.name + '</option>').join('') +
    '</select></div></div>' +
    '<div class="form-row"><div class="form-group"><label>Jour</label><select id="tt-day">' +
    TT_DAYS.map((d, i) => '<option value="' + i + '" ' + (i === entry.day_of_week ? 'selected' : '') + '>' + d + '</option>').join('') +
    '</select></div><div class="form-group"><label>Creneau</label><select id="tt-slot">' + slotOptions + '</select></div></div>' +
    '<div class="form-row"><div class="form-group"><label>Enseignant</label><select id="tt-teacher"><option value="">-- Optionnel --</option>' +
    teachers.map(t => '<option value="' + t.id + '" ' + (t.id === entry.teacher_id ? 'selected' : '') + '>' + t.first_name + ' ' + t.last_name + '</option>').join('') +
    '</select></div><div class="form-group"><label>Salle</label><input id="tt-room" value="' + (entry.room || '') + '" placeholder="Ex: A101"></div></div>' +
    '<div class="modal-footer"><button class="btn-danger" onclick="deleteTT(' + id + ');closeModal()" style="margin-right:auto"><i class="fas fa-trash"></i> Supprimer</button>' +
    '<button class="btn-secondary" onclick="closeModal()">Annuler</button>' +
    '<button class="btn-add" onclick="submitEditTT(' + id + ')"><i class="fas fa-check"></i> Enregistrer</button></div></div>');
}

async function submitEditTT(id) {
  const classId = parseInt(document.getElementById('tt-class-id').value);
  const subjectId = parseInt(document.getElementById('tt-subject-id').value);
  const slotEl = document.getElementById('tt-slot');
  const opt = slotEl.options[slotEl.selectedIndex];
  const startTime = slotEl.value;
  const endTime = opt && opt.dataset.end ? opt.dataset.end : startTime;
  const data = {
    class_id: classId,
    subject_id: subjectId,
    teacher_id: parseInt(document.getElementById('tt-teacher').value) || null,
    day_of_week: parseInt(document.getElementById('tt-day').value),
    start_time: startTime,
    end_time: endTime,
    room: document.getElementById('tt-room').value.trim() || null,
  };
  try {
    const res = await api('/api/timetable/' + id, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
    if (res?.ok) { closeModal(); showToast('Cours mis a jour'); loadTimetable(); }
    else { const d = await res.json().catch(()=>({})); showToast(d.detail || 'Erreur', 'error'); }
  } catch { showToast('Erreur reseau', 'error'); }
}

async function deleteTT(id) {
  if (!confirm('Supprimer ce cours ?')) return;
  try {
    const res = await api('/api/timetable/' + id, { method: 'DELETE' });
    if (res?.ok || res?.status === 204) { showToast('Cours supprime'); loadTimetable(); }
  } catch { showToast('Erreur', 'error'); }
}

function closeModal(){document.getElementById('modal-overlay').style.display='none'}
function showToast(m,t='success'){const c=document.getElementById('toast-container');const e=document.createElement('div');e.className=`toast ${t}`;e.textContent=m;c.appendChild(e);setTimeout(()=>e.remove(),4000)}
window.addEventListener('online',()=>{document.getElementById('offline-bar').classList.remove('visible');showToast('Connexion rétablie')});
window.addEventListener('offline',()=>{document.getElementById('offline-bar').classList.add('visible')});


/* === NOTIFICATION & MESSAGING SYSTEM === */
(function(){
  let _notifTimer = null;

  // Update badge counters in header
  async function updateBadges() {
    try {
      const [notifRes, msgRes] = await Promise.all([
        api('/api/notifications/unread-count'),
        api('/api/messages/unread-count'),
      ]);
      if (notifRes?.ok) {
        const d = await notifRes.json();
        const badge = document.getElementById('notif-badge');
        if (badge) {
          badge.style.display = d.unread_count > 0 ? 'block' : 'none';
          badge.textContent = d.unread_count > 99 ? '99+' : d.unread_count;
        }
      }
      if (msgRes?.ok) {
        const d = await msgRes.json();
        const badge = document.getElementById('msg-badge');
        if (badge) {
          badge.style.display = d.unread_count > 0 ? 'block' : 'none';
          badge.textContent = d.unread_count > 99 ? '99+' : d.unread_count;
        }
      }
    } catch {}
  }

  // Start polling
  function startPolling() {
    updateBadges();
    _notifTimer = setInterval(updateBadges, 30000);
  }

  // Notification dropdown
  window.showNotifications = async function() {
    const res = await api('/api/notifications');
    if (!res?.ok) return;
    const data = await res.json();
    const notifications = data.notifications || [];

    let html = '<div style="max-height:400px;overflow-y:auto">';
    if (notifications.length === 0) {
      html += '<div style="padding:24px;text-align:center;color:var(--texte-secondaire)"><i class="fas fa-bell-slash" style="font-size:24px;margin-bottom:8px;display:block"></i>Aucune notification</div>';
    } else {
      notifications.forEach(n => {
        const icon = n.type === 'grade_published' ? 'fa-star' : n.type === 'absence' ? 'fa-user-slash' : n.type === 'payment_due' ? 'fa-money-bill' : 'fa-bell';
        html += '<div style="padding:10px 14px;border-bottom:1px solid var(--border);cursor:pointer;display:flex;gap:10px;align-items:start;' + (!n.is_read ? 'background:#f0fdf4' : '') + '" onclick="markNotifRead(' + n.id + ')">';
        html += '<i class="fas ' + icon + '" style="color:var(--yiriba-vert);margin-top:2px;font-size:13px"></i>';
        html += '<div style="flex:1;min-width:0"><div style="font-size:12px;font-weight:600">' + (n.title || '') + '</div>';
        html += '<div style="font-size:11px;color:var(--texte-secondaire);margin-top:2px">' + (n.body || '').substring(0, 80) + '</div>';
        html += '<div style="font-size:10px;color:var(--texte-secondaire);margin-top:2px">' + formatTime(n.created_at) + '</div>';
        html += '</div>' + (!n.is_read ? '<div style="width:8px;height:8px;border-radius:50%;background:var(--yiriba-vert);flex-shrink:0;margin-top:4px"></div>' : '');
        html += '</div>';
      });
    }
    html += '</div>';

    const dd = document.getElementById('notif-dropdown');
    dd.innerHTML = html;
    dd.style.display = dd.style.display === 'block' ? 'none' : 'block';
  };

  window.markNotifRead = async function(id) {
    await api('/api/notifications/mark-read', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ notification_ids: [id] }) });
    updateBadges();
    showNotifications();
  };

  // MESSAGING PAGE
  window.loadMessaging = async function() {
    const c = document.getElementById('main-content');
    c.innerHTML = '<div style="padding:20px;color:var(--texte-secondaire)">Chargement...</div>';

    const res = await api('/api/messages/conversations');
    if (!res?.ok) { c.innerHTML = '<div class="card section-card" style="padding:24px;text-align:center">Erreur de chargement</div>'; return; }
    const data = await res.json();
    const conversations = data.conversations || [];

    let convListHtml = '';
    if (conversations.length === 0) {
      convListHtml = '<div style="padding:24px;text-align:center;color:var(--texte-secondaire)"><i class="fas fa-envelope" style="font-size:24px;margin-bottom:8px;display:block"></i>Aucune conversation<br><small>Commencez une nouvelle conversation</small></div>';
    } else {
      conversations.forEach(conv => {
        const other = conv.participants[0] || {};
        const lastMsg = conv.last_message;
        const hasUnread = conv.unread_count > 0;
        convListHtml += '<div class="conv-item" data-id="' + conv.id + '" onclick="openConversation(' + conv.id + ')" style="padding:12px 14px;border-bottom:1px solid var(--border);cursor:pointer;display:flex;gap:10px;align-items:center;transition:background 0.15s" onmouseenter="this.style.background=\'var(--yiriba-ivoire)\'" onmouseleave="this.style.background=\'\'">';
        convListHtml += '<div style="width:36px;height:36px;border-radius:50%;background:var(--yiriba-vert);color:white;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;flex-shrink:0">' + (other.name || '?')[0] + '</div>';
        convListHtml += '<div style="flex:1;min-width:0">';
        convListHtml += '<div style="display:flex;justify-content:space-between;align-items:center"><span style="font-size:13px;font-weight:' + (hasUnread ? '700' : '400') + '">' + (other.name || 'Inconnu') + '</span>';
        convListHtml += '<span style="font-size:10px;color:var(--texte-secondaire)">' + (lastMsg ? formatTime(lastMsg.created_at) : '') + '</span></div>';
        convListHtml += '<div style="font-size:12px;color:var(--texte-secondaire);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:' + (hasUnread ? '600' : '400') + '">' + (lastMsg ? lastMsg.content.substring(0, 60) : '') + '</div>';
        convListHtml += '</div>';
        if (hasUnread) convListHtml += '<div style="width:20px;height:20px;border-radius:50%;background:var(--yiriba-vert);color:white;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;flex-shrink:0">' + conv.unread_count + '</div>';
        convListHtml += '</div>';
      });
    }

    c.innerHTML = `
      <div class="welcome"><h1>Messagerie</h1><p>Communiquez avec votre equipe.</p></div>
      <div style="display:flex;gap:16px;height:calc(100vh - 180px)">
        <div class="card section-card" style="width:340px;flex-shrink:0;display:flex;flex-direction:column;overflow:hidden">
          <div style="padding:12px 14px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
            <span style="font-weight:600;font-size:14px">Conversations</span>
            <button class="btn-add" onclick="showNewMessageModal()" style="padding:5px 12px;font-size:12px"><i class="fas fa-plus"></i> Nouveau</button>
          </div>
          <div id="conv-list" style="flex:1;overflow-y:auto">${convListHtml}</div>
        </div>
        <div id="chat-area" class="card section-card" style="flex:1;display:flex;flex-direction:column;overflow:hidden">
          <div style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--texte-secondaire)">
            <div style="text-align:center"><i class="fas fa-comments" style="font-size:48px;margin-bottom:12px;display:block;opacity:0.3"></i>Selectionnez une conversation</div>
          </div>
        </div>
      </div>`;
  };

  window.openConversation = async function(convId) {
    const chatArea = document.getElementById('chat-area');
    chatArea.innerHTML = '<div style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--texte-secondaire)">Chargement...</div>';

    const res = await api('/api/messages/conversations/' + convId);
    if (!res?.ok) { chatArea.innerHTML = '<div style="padding:20px;color:var(--yiriba-rouge)">Erreur</div>'; return; }
    const data = await res.json();
    const messages = data.messages || [];

    let msgsHtml = '';
    messages.forEach(m => {
      const isMe = m.sender_id === state.user?.id;
      msgsHtml += '<div style="display:flex;justify-content:' + (isMe ? 'flex-end' : 'flex-start') + ';margin-bottom:8px">';
      msgsHtml += '<div style="max-width:70%;padding:8px 12px;border-radius:12px;font-size:13px;' + (isMe ? 'background:var(--yiriba-vert);color:white;border-bottom-right-radius:4px' : 'background:var(--yiriba-ivoire);border-bottom-left-radius:4px') + '">';
      if (!isMe) msgsHtml += '<div style="font-size:11px;font-weight:600;margin-bottom:2px">' + m.sender_name + '</div>';
      msgsHtml += m.content;
      msgsHtml += '<div style="font-size:10px;margin-top:4px;opacity:0.6;text-align:right">' + formatTime(m.created_at) + '</div>';
      msgsHtml += '</div></div>';
    });

    chatArea.innerHTML = `
      <div style="padding:10px 14px;border-bottom:1px solid var(--border);font-weight:600;font-size:14px" id="chat-header">Conversation</div>
      <div id="chat-messages" style="flex:1;overflow-y:auto;padding:14px">${msgsHtml || '<div style="text-align:center;color:var(--texte-secondaire);padding:20px">Aucun message</div>'}</div>
      <div style="padding:10px 14px;border-top:1px solid var(--border);display:flex;gap:8px">
        <input id="chat-input" placeholder="Ecrivez un message..." style="flex:1;padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px;outline:none" onkeydown="if(event.key==='Enter')sendMsg(${convId})">
        <button class="btn-add" onclick="sendMsg(${convId})" style="padding:8px 16px"><i class="fas fa-paper-plane"></i></button>
      </div>`;

    // Scroll to bottom
    const msgContainer = document.getElementById('chat-messages');
    if (msgContainer) msgContainer.scrollTop = msgContainer.scrollHeight;

    // Highlight active conversation
    document.querySelectorAll('.conv-item').forEach(el => {
      el.style.background = el.dataset.id == convId ? 'var(--yiriba-ivoire)' : '';
    });
  };

  window.sendMsg = async function(convId) {
    const input = document.getElementById('chat-input');
    const content = input.value.trim();
    if (!content) return;
    input.value = '';

    await api('/api/messages/conversations/' + convId + '/messages', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ content }),
    });
    openConversation(convId);
  };

  window.showNewMessageModal = async function() {
    const res = await api('/api/messages/recipients');
    if (!res?.ok) return;
    const data = await res.json();
    const recipients = data.recipients || [];

    let options = recipients.map(r => '<option value="' + r.id + '">' + r.name + ' (' + r.role + ')</option>').join('');

    showModal('Nouveau message', '<div class="modal-form">' +
      '<div class="form-group"><label>Destinataire</label><select id="msg-recipient">' + options + '</select></div>' +
      '<div class="form-group"><label>Message</label><textarea id="msg-content" rows="4" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:6px;font-size:13px;resize:vertical;outline:none" placeholder="Ecrivez votre message..."></textarea></div>' +
      '<div class="modal-footer"><button class="btn-secondary" onclick="closeModal()">Annuler</button>' +
      '<button class="btn-add" onclick="submitNewMessage()"><i class="fas fa-paper-plane"></i> Envoyer</button></div></div>');
  };

  window.submitNewMessage = async function() {
    const recipientId = parseInt(document.getElementById('msg-recipient').value);
    const content = document.getElementById('msg-content').value.trim();
    if (!content) { showToast('Ecrivez un message', 'error'); return; }

    const res = await api('/api/messages/conversations', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ recipient_id: recipientId, content }),
    });
    if (res?.ok) {
      closeModal();
      showToast('Message envoye');
      loadMessaging();
    } else {
      const d = await res.json().catch(()=>({}));
      showToast(d.detail || 'Erreur', 'error');
    }
  };

  function formatTime(isoStr) {
    if (!isoStr) return '';
    const d = new Date(isoStr);
    const now = new Date();
    const diffMs = now - d;
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return 'A l\'instant';
    if (diffMin < 60) return diffMin + ' min';
    const diffH = Math.floor(diffMin / 60);
    if (diffH < 24) return diffH + 'h';
    return d.toLocaleDateString('fr-FR', {day:'numeric', month:'short'});
  }

  // Init on DOM ready
  document.addEventListener('DOMContentLoaded', function() {
    startPolling();
    // Add msg-badge to envelope button
    const envelopeBtn = document.querySelector('.topbar-btn[title="Messages"]');
    if (envelopeBtn) {
      envelopeBtn.setAttribute('onclick', 'loadPage(\'messaging\')');
      const badge = document.createElement('span');
      badge.id = 'msg-badge';
      badge.style.cssText = 'display:none;position:absolute;top:2px;right:2px;width:8px;height:8px;border-radius:50%;background:var(--yiriba-vert);border:2px solid white';
      envelopeBtn.style.position = 'relative';
      envelopeBtn.appendChild(badge);
    }
    // Add onclick to bell button
    const bellBtn = document.querySelector('.topbar-btn[title="Notifications"]');
    if (bellBtn) {
      bellBtn.setAttribute('onclick', 'showNotifications()');
      bellBtn.style.position = 'relative';
      const dd = document.createElement('div');
      dd.id = 'notif-dropdown';
      dd.style.cssText = 'display:none;position:absolute;top:100%;right:0;width:340px;background:white;border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,0.12);z-index:1000';
      bellBtn.appendChild(dd);
    }
  });
})();

/* === GLOBAL SEARCH === */
(function(){
  let _gsTimer = null;
  const _gsIcons = {student:'fa-user-graduate',teacher:'fa-person-chalkboard',class:'fa-chalkboard',payment:'fa-money-bill'};
  const _gsPages = {student:'students',teacher:'teachers',class:'classes',payment:'payments'};
  document.addEventListener('DOMContentLoaded',function(){
    const si = document.querySelector('.search');
    if (!si) return;
    // Create dropdown
    const dd = document.createElement('div');
    dd.id = 'global-search-dropdown';
    dd.style.cssText = 'display:none;position:absolute;top:100%;left:0;right:0;background:white;border-radius:0 0 8px 8px;box-shadow:0 8px 24px rgba(0,0,0,0.12);z-index:1000;max-height:320px;overflow-y:auto;min-width:280px';
    si.parentElement.style.position = 'relative';
    si.parentElement.appendChild(dd);
    si.addEventListener('input',function(){
      clearTimeout(_gsTimer);
      const q = this.value.trim();
      if (q.length < 2) { dd.style.display='none'; return; }
      _gsTimer = setTimeout(async function(){
        try {
          const r = await api('/api/admin/search?q=' + encodeURIComponent(q));
          if (!r?.ok) { dd.style.display='none'; return; }
          const data = await r.json();
          const results = data.results || [];
          if (results.length === 0) { dd.innerHTML = '<div style="padding:12px;text-align:center;color:var(--texte-secondaire);font-size:13px">Aucun resultat pour "' + q + '"</div>'; dd.style.display='block'; return; }
          dd.innerHTML = results.map(function(item){
            var icon = _gsIcons[item.type] || 'fa-search';
            return '<div class="gs-result" onclick="loadPage(\'' + item.page + '\');document.getElementById(\'global-search-dropdown\').style.display=\'none\'" style="display:flex;align-items:center;gap:10px;padding:10px 14px;cursor:pointer;border-bottom:1px solid var(--border);transition:background 0.15s" onmouseenter="this.style.background=\'var(--yiriba-ivoire)\'" onmouseleave="this.style.background=\'\'">'
              + '<i class="fas ' + icon + '" style="color:var(--yiriba-vert);font-size:14px;width:20px;text-align:center"></i>'
              + '<div style="flex:1;min-width:0"><div style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + item.label + '</div>'
              + (item.subtitle ? '<div style="font-size:11px;color:var(--texte-secondaire)">' + item.subtitle + '</div>' : '') + '</div>'
              + '<span style="font-size:10px;color:var(--texte-secondaire);text-transform:capitalize;background:var(--yiriba-ivoire);padding:2px 6px;border-radius:4px;white-space:nowrap">' + item.type + '</span>'
              + '</div>';
          }).join('');
          dd.style.display='block';
        } catch(e) { dd.style.display='none'; }
      }, 300);
    });
    si.addEventListener('blur',function(){ setTimeout(function(){ dd.style.display='none'; }, 200); });
    si.addEventListener('focus',function(){ if (dd.innerHTML.trim()) dd.style.display='block'; });
  });
})();

document.addEventListener('DOMContentLoaded',function(){
  // Initialize i18n
  if (typeof YIRIBA_I18N !== 'undefined') YIRIBA_I18N.apply();
  if (!handleGoogleAuthFragment()){
    if (state.token) enterApp();
    else document.getElementById('auth-screen').style.display='flex';
  }
});


/* ==============================================================
   PRÉSENCES — Justifications + tableau de bord admin
   ============================================================== */

async function loadAttendanceJustify() {
  const c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  let data = { total: 0, items: [] };
  let dash = null;
  try {
    const [jRes, dRes] = await Promise.all([
      api('/api/attendance/justifications/pending'),
      api('/api/attendance/dashboard/today'),
    ]);
    if (jRes?.ok) data = await jRes.json();
    if (dRes?.ok) dash = await dRes.json();
  } catch {}

  const t = dash?.today || {};
  const dashHtml = dash ? `
    <div class="indicator-row">
      <div class="indicator-card hero"><div class="indicator-icon"><i class="fas fa-users"></i></div><div class="indicator-info"><h4>Pointés aujourd'hui</h4><div class="indicator-val">${t.total ?? 0}</div><div class="indicator-sub">${dash.date}</div></div></div>
      <div class="indicator-card"><div class="indicator-icon"><i class="fas fa-check-circle"></i></div><div class="indicator-info"><h4>Présents</h4><div class="indicator-val">${t.present ?? 0}</div></div></div>
      <div class="indicator-card"><div class="indicator-icon" style="color:var(--yiriba-rouge)"><i class="fas fa-times-circle"></i></div><div class="indicator-info"><h4>Absents</h4><div class="indicator-val">${t.absent ?? 0}</div></div></div>
      <div class="indicator-card"><div class="indicator-icon" style="color:var(--yiriba-jaune)"><i class="fas fa-clock"></i></div><div class="indicator-info"><h4>Retards</h4><div class="indicator-val">${t.late ?? 0}</div></div></div>
    </div>` : '';

  const repeatHtml = (dash?.repeat_absentees?.length || dash?.classes_most_absent?.length) ? `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px;">
      <div class="card section-card">
        <h3 style="margin-bottom:10px;"><i class="fas fa-triangle-exclamation" style="color:var(--yiriba-rouge)"></i> Absences répétées (30 j)</h3>
        ${dash.repeat_absentees?.length ? dash.repeat_absentees.map(s => `
          <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border);font-size:13px;">
            <span>${escapeHtml(s.student_name)}</span><strong style="color:var(--yiriba-rouge)">${s.absences} abs.</strong>
          </div>`).join('') : '<p style="color:var(--texte-secondaire);font-size:13px;">Aucune absence répétée.</p>'}
      </div>
      <div class="card section-card">
        <h3 style="margin-bottom:10px;"><i class="fas fa-school" style="color:var(--yiriba-vert)"></i> Classes les plus absentes (30 j)</h3>
        ${dash.classes_most_absent?.length ? dash.classes_most_absent.map(cl => `
          <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border);font-size:13px;">
            <span>${escapeHtml(cl.class_name)}</span><strong style="color:var(--yiriba-jaune)">${cl.absences} abs.</strong>
          </div>`).join('') : '<p style="color:var(--texte-secondaire);font-size:13px;">Aucune donnée.</p>'}
      </div>
    </div>` : '';

  c.innerHTML = `
    <div class="welcome"><h1>Présences & Absences</h1><p>Suivi, justifications et statistiques d'assiduité.</p></div>
    ${dashHtml}
    <div class="page-toolbar"><h2 style="font-size:18px;"><i class="fas fa-file-signature" style="color:var(--yiriba-jaune)"></i> Absences à justifier (${data.total})</h2><div></div></div>
    ${data.items.length > 0 ? `
    <div class="yiriba-table-wrap">
      <table class="yiriba-table">
        <thead><tr><th>Élève</th><th>Date</th><th>Période</th><th>Statut</th><th>Motif soumis</th><th style="text-align:right">Décision</th></tr></thead>
        <tbody>${data.items.map(j => `
          <tr>
            <td><span class="name-cell" style="font-weight:600">${escapeHtml(j.student_name)}</span><br><small style="color:var(--texte-secondaire)">${escapeHtml(j.matricule || '')}</small></td>
            <td>${new Date(j.date).toLocaleDateString('fr-FR')}</td>
            <td>${j.period}</td>
            <td><span class="badge badge-danger"><span class="badge-dot"></span>${j.status === 'absent' ? 'Absent' : 'Retard'}</span></td>
            <td style="max-width:260px;">${escapeHtml(j.justification || '—')}</td>
            <td><div class="table-actions" style="justify-content:flex-end">
              <button class="btn-add" style="padding:6px 12px;font-size:12px;" onclick="decideJustification(${j.id}, 'accept')"><i class="fas fa-check"></i> Accepter</button>
              <button class="btn-secondary" style="padding:6px 12px;font-size:12px;" onclick="decideJustification(${j.id}, 'refuse')"><i class="fas fa-ban"></i> Refuser</button>
            </div></td>
          </tr>`).join('')}</tbody>
      </table>
    </div>` : `
    <div class="card section-card"><div class="empty">
      <div class="empty-icon"><i class="fas fa-folder-open"></i></div>
      <h4>Aucune justification en attente</h4><p>Toutes les demandes ont été traitées.</p>
    </div></div>`}
    ${repeatHtml}
  `;
}

async function decideJustification(attId, decision) {
  let comment = null;
  if (decision === 'refuse') {
    comment = prompt('Motif du refus (optionnel) :');
    if (comment === null) return;
  }
  try {
    const res = await api(`/api/attendance/${attId}/justify/decision`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, comment }),
    });
    if (res?.ok) { showToast(decision === 'accept' ? 'Justification acceptée — parent notifié' : 'Justification refusée'); loadAttendanceJustify(); }
    else { const j = await res.json().catch(() => ({})); showToast(j.detail || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}
