/* ===================================================================
   YIRIBA i18n - Centralized translation system
   =================================================================== */

const YIRIBA_I18N = {
  _lang: localStorage.getItem('yiriba_lang') || 'fr',
  _listeners: [],

  get lang() { return this._lang; },

  set lang(code) {
    if (code !== 'fr' && code !== 'en') return;
    this._lang = code;
    localStorage.setItem('yiriba_lang', code);
    document.documentElement.lang = code;
    this.apply();
    this._listeners.forEach(function(fn) { fn(code); });
  },

  t: function(key) {
    var dict = this._lang === 'en' ? EN : FR;
    return dict[key] || FR[key] || key;
  },

  apply: function() {
    var self = this;
    document.querySelectorAll('[data-i18n]').forEach(function(el) {
      var key = el.getAttribute('data-i18n');
      var text = self.t(key);
      if (el.tagName === 'INPUT' && el.hasAttribute('placeholder')) {
        el.placeholder = text;
      } else {
        el.textContent = text;
      }
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el) {
      el.placeholder = self.t(el.getAttribute('data-i18n-placeholder'));
    });
    document.documentElement.lang = this._lang;
  },

  onChange: function(fn) { this._listeners.push(fn); }
};

/* --- French dictionary ------------------------------------------ */
var FR = {
  'brand.slogan': 'VOS RACINES DIGITALISEES',
  'brand.headline1': 'La gestion scolaire',
  'brand.headline2': 'reinventee',
  'brand.description': 'YIRIBA accompagne les etablissements scolaires dans leur transformation digitale simple, securisee et efficace.',
  'brand.feature1.title': 'Gestion complete',
  'brand.feature1.desc': 'Notes, presences, bulletins et plus encore.',
  'brand.feature2.title': 'Pilotage en temps reel',
  'brand.feature2.desc': 'Tableaux de bord et statistiques avancees.',
  'brand.feature3.title': 'Securise & fiable',
  'brand.feature3.desc': 'Vos donnees sont protegees et accessibles partout.',
  'brand.copyright': '2025 Yiriba - Tous droits reserves',
  'brand.lang': 'Francais',

  'auth.welcome': 'Bienvenue sur YIRIBA',
  'auth.subtitle': 'Connectez-vous a votre espace',
  'auth.tab.login': 'Connexion',
  'auth.tab.register': 'Creer une ecole',

  'login.email': 'Email ou identifiant',
  'login.email.placeholder': 'ex : directeur@ecole.com',
  'login.password': 'Mot de passe',
  'login.password.placeholder': '********',
  'login.school_slug': 'Sigle de l\'ecole',
  'login.school_slug.hint': '(optionnel si 1 seul compte)',
  'login.school_slug.placeholder': 'ex: college-yiriba',
  'login.remember': 'Se souvenir de moi',
  'login.forgot': 'Mot de passe oublie ?',
  'login.submit': 'Se connecter',
  'login.loading': 'Connexion en cours...',
  'login.error.default': 'Identifiants incorrects',
  'login.error.locked': 'Compte temporairement verrouille',
  'login.error.inactive': 'Compte en attente de validation',
  'login.error.disabled': 'Compte desactive',
  'login.error.network': 'Erreur reseau. Verifiez votre connexion.',

  'auth.separator': 'ou continuer avec',
  'auth.google': 'Google',
  'auth.security': 'Plateforme securisee et certifiee',

  'reset.title': 'Recuperer votre mot de passe',
  'reset.subtitle': 'Entrez votre adresse email pour recevoir un lien de reinitialisation.',
  'reset.email': 'Adresse email',
  'reset.email.placeholder': 'votre@email.com',
  'reset.submit': 'Envoyer le lien',
  'reset.loading': 'Envoi en cours...',
  'reset.back': 'Retour a la connexion',
  'reset.success.title': 'Email envoye !',
  'reset.success.message': 'Si un compte est associe a cette adresse, vous recevrez un lien de reinitialisation.',
  'reset.new_password.title': 'Nouveau mot de passe',
  'reset.new_password.label': 'Nouveau mot de passe',
  'reset.new_password.placeholder': 'Min. 8 caracteres',
  'reset.confirm_password.label': 'Confirmer le mot de passe',
  'reset.confirm_password.placeholder': 'Repetez le mot de passe',
  'reset.confirm_submit': 'Reinitialiser',
  'reset.confirm_loading': 'Reinitialisation...',
  'reset.error.mismatch': 'Les mots de passe ne correspondent pas',
  'reset.error.expired': 'Ce lien a expire. Veuillez faire une nouvelle demande.',
  'reset.error.invalid': 'Lien invalide.',
  'reset.confirmed.title': 'Mot de passe modifie !',
  'reset.confirmed.message': 'Vous pouvez maintenant vous connecter avec votre nouveau mot de passe.',

  'register.school_name': 'Nom de l\'ecole',
  'register.school_name.placeholder': 'College Yiriba Ouaga',
  'register.school_slug': 'Slug de l\'ecole',
  'register.school_slug.placeholder': 'college-yiriba-ouaga',
  'register.first_name': 'Prenom',
  'register.last_name': 'Nom',
  'register.email': 'Email du directeur',
  'register.email.placeholder': 'directeur@ecole.com',
  'register.password': 'Mot de passe',
  'register.password.placeholder': 'Min. 8 caracteres',
  'register.submit': 'Creer l\'ecole',

  'error.multiple_accounts': 'Plusieurs comptes existent avec cet email. Veuillez preciser le sigle de l\'ecole.',
  'error.email_required': 'Veuillez entrer votre adresse email.',
  'error.password_required': 'Veuillez entrer votre mot de passe.'
};

/* --- English dictionary ----------------------------------------- */
var EN = {
  'brand.slogan': 'YOUR DIGITAL ROOTS',
  'brand.headline1': 'School management',
  'brand.headline2': 'reinvented',
  'brand.description': 'YIRIBA supports schools in their digital transformation - simple, secure and effective.',
  'brand.feature1.title': 'Complete management',
  'brand.feature1.desc': 'Grades, attendance, report cards and more.',
  'brand.feature2.title': 'Real-time overview',
  'brand.feature2.desc': 'Dashboards and advanced statistics.',
  'brand.feature3.title': 'Secure & reliable',
  'brand.feature3.desc': 'Your data is protected and accessible everywhere.',
  'brand.copyright': '2025 Yiriba - All rights reserved',
  'brand.lang': 'English',

  'auth.welcome': 'Welcome to YIRIBA',
  'auth.subtitle': 'Sign in to your account',
  'auth.tab.login': 'Sign in',
  'auth.tab.register': 'Create a school',

  'login.email': 'Email or username',
  'login.email.placeholder': 'e.g. principal@school.com',
  'login.password': 'Password',
  'login.password.placeholder': '********',
  'login.school_slug': 'School code',
  'login.school_slug.hint': '(optional if only 1 account)',
  'login.school_slug.placeholder': 'e.g. college-yiriba',
  'login.remember': 'Remember me',
  'login.forgot': 'Forgot password?',
  'login.submit': 'Sign in',
  'login.loading': 'Signing in...',
  'login.error.default': 'Invalid credentials',
  'login.error.locked': 'Account temporarily locked',
  'login.error.inactive': 'Account pending validation',
  'login.error.disabled': 'Account disabled',
  'login.error.network': 'Network error. Check your connection.',

  'auth.separator': 'or continue with',
  'auth.google': 'Google',
  'auth.security': 'Secure and certified platform',

  'reset.title': 'Recover your password',
  'reset.subtitle': 'Enter your email to receive a reset link.',
  'reset.email': 'Email address',
  'reset.email.placeholder': 'your@email.com',
  'reset.submit': 'Send link',
  'reset.loading': 'Sending...',
  'reset.back': 'Back to sign in',
  'reset.success.title': 'Email sent!',
  'reset.success.message': 'If an account exists with this address, you will receive a reset link.',
  'reset.new_password.title': 'New password',
  'reset.new_password.label': 'New password',
  'reset.new_password.placeholder': 'Min. 8 characters',
  'reset.confirm_password.label': 'Confirm password',
  'reset.confirm_password.placeholder': 'Repeat password',
  'reset.confirm_submit': 'Reset',
  'reset.confirm_loading': 'Resetting...',
  'reset.error.mismatch': 'Passwords do not match',
  'reset.error.expired': 'This link has expired. Please request a new one.',
  'reset.error.invalid': 'Invalid link.',
  'reset.confirmed.title': 'Password updated!',
  'reset.confirmed.message': 'You can now sign in with your new password.',

  'register.school_name': 'School name',
  'register.school_name.placeholder': 'Yiriba College Ouaga',
  'register.school_slug': 'School slug',
  'register.school_slug.placeholder': 'yiriba-college-ouaga',
  'register.first_name': 'First name',
  'register.last_name': 'Last name',
  'register.email': 'Principal email',
  'register.email.placeholder': 'principal@school.com',
  'register.password': 'Password',
  'register.password.placeholder': 'Min. 8 characters',
  'register.submit': 'Create school',

  'error.multiple_accounts': 'Multiple accounts exist with this email. Please specify the school code.',
  'error.email_required': 'Please enter your email address.',
  'error.password_required': 'Please enter your password.'
};
