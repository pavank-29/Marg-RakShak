import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Eye, EyeOff, ArrowLeft, ShieldAlert, CheckCircle2, Loader2, AlertCircle } from 'lucide-react';
import LanguageSelectModal from '../components/common/LanguageSelectModal';
import LanguageSelector from '../components/common/LanguageSelector';
import { getSavedLanguage, saveLanguage } from '../utils/i18n';
import { useLanguage } from '../context/LanguageContext';
import { useAuth } from '../context/AuthContext';

/**
 * User Login page.
 *
 * Collects: Name, Phone Number, Password.
 *
 * Backend note: The /api/v1/auth/login endpoint (UserLogin schema) expects
 * { email, password }.  Phone-number-based accounts are stored with the
 * synthetic email  <phone>@margrakshak.in — the same convention the original
 * Login.jsx already used for non-@ identifiers.  Name is used to populate
 * the local session display name and is never sent to the backend.
 *
 * If the backend is unavailable the page falls back to an offline local
 * session (same behaviour as the original implementation).
 */
export default function Login() {
  const navigate = useNavigate();
  const routerLocation = useLocation();
  const { t } = useLanguage();
  const { login } = useAuth();

  // Pre-fill email/phone forwarded from Register success redirect
  const prefill = routerLocation.state?.registeredEmail || '';
  const initialPhone = prefill.includes('@margrakshak.in')
    ? prefill.replace('@margrakshak.in', '')
    : prefill;

  const [name, setName] = useState('');
  const [phone, setPhone] = useState(initialPhone);
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const [error, setError] = useState('');
  const [infoMessage] = useState(routerLocation.state?.message || '');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showLanguagePrompt, setShowLanguagePrompt] = useState(false);

  // ─── helpers ────────────────────────────────────────────────────────────────

  /** Strip non-digits except leading + */
  const normalizePhone = (raw) => raw.trim().replace(/[\s\-().]/g, '');

  /** Accepts valid email address or 7-15 digit phone */
  const isValidContact = (raw) => {
    const val = raw.trim();
    if (val.includes('@')) {
      return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val);
    }
    return /^\+?\d{7,15}$/.test(normalizePhone(val));
  };

  const enterPortal = () => navigate('/user/navigation');

  // ─── submit ─────────────────────────────────────────────────────────────────

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    const trimmedName = name.trim();
    const rawContact = phone.trim();
    const isEmailContact = rawContact.includes('@');
    const normalizedContact = isEmailContact ? rawContact.toLowerCase() : normalizePhone(rawContact);
    const trimmedPassword = password.trim();

    if (!trimmedName) {
      setError('Please enter your name.');
      return;
    }
    if (!rawContact) {
      setError('Please enter your phone number or email.');
      return;
    }
    if (!isValidContact(rawContact)) {
      setError('Please enter a valid phone number (7–15 digits) or valid email address.');
      return;
    }
    if (!trimmedPassword) {
      setError('Please enter your password.');
      return;
    }

    setIsSubmitting(true);

    const syntheticEmail = isEmailContact
      ? normalizedContact
      : `${normalizedContact.replace(/^\+/, '')}@margrakshak.in`;

    let authUser = {
      full_name: trimmedName,
      email: isEmailContact ? normalizedContact : syntheticEmail,
      mobile: isEmailContact ? undefined : normalizedContact,
      role: 'user',
    };

    try {
      const loginPayload = JSON.stringify({
        name: trimmedName,
        phone: !isEmailContact ? normalizedContact : undefined,
        email: isEmailContact ? normalizedContact : syntheticEmail,
        password: trimmedPassword,
      });

      let res;
      try {
        res = await fetch('/api/v1/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: loginPayload,
        });
      } catch {
        res = await fetch('http://localhost:8000/api/v1/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: loginPayload,
        });
      }

      if (res.ok) {
        const data = await res.json();
        if (data.user) {
          authUser = {
            ...authUser,
            ...data.user,
            full_name: data.user.full_name || trimmedName,
            role: 'user',
          };
        }
        const token = data.access_token || data.token || null;
        login(authUser, token);
      } else if (res.status === 401) {
        setError('Incorrect name, phone number, or password.');
        setIsSubmitting(false);
        return;
      } else if (res.status === 422) {
        const errData = await res.json().catch(() => ({}));
        const detail = Array.isArray(errData.detail)
          ? errData.detail.map((d) => d.msg || d).join(', ')
          : errData.detail || 'Validation error.';
        setError(detail);
        setIsSubmitting(false);
        return;
      } else if (res.status >= 500) {
        throw new Error('Backend server unreachable');
      } else {
        const errData = await res.json().catch(() => ({}));
        setError(errData.detail || 'Authentication failed. Please check your details.');
        setIsSubmitting(false);
        return;
      }
    } catch (err) {
      // Offline fallback — same pattern as original Login.jsx
      console.warn('Backend unreachable, using local session:', err);
      login(authUser);
    } finally {
      setIsSubmitting(false);
    }

    // First-time login: ask for preferred alert language
    if (!getSavedLanguage()) {
      setShowLanguagePrompt(true);
      return;
    }

    enterPortal();
  };

  const handleLanguageConfirm = (code) => {
    saveLanguage(code);
    setShowLanguagePrompt(false);
    enterPortal();
  };

  // ─── render ─────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-[#F5F8FC] flex items-start sm:items-center justify-center p-4 sm:p-5">
      <div className="w-full max-w-sm mt-8 sm:mt-0">

        {/* Top bar */}
        <div className="flex items-center justify-between mb-6">
          <button
            type="button"
            onClick={() => navigate('/')}
            className="flex items-center gap-1.5 text-sm text-[#64748B] hover:text-[#111827] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#D49A00] rounded"
          >
            <ArrowLeft className="w-4 h-4" aria-hidden="true" />
            <span>{t('login.backToHome')}</span>
          </button>
          <LanguageSelector variant="light" />
        </div>

        {/* Card */}
        <div
          className="bg-white rounded-2xl border border-[#D9E2EF] shadow-[0_2px_16px_0_rgba(17,24,39,0.06)] p-8"
          role="main"
          aria-labelledby="login-heading"
        >
          {/* Shield logo */}
          <div className="flex justify-center mb-5">
            <span
              className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-[#FFC21A] text-[#111827] shadow-sm"
              aria-hidden="true"
            >
              <ShieldAlert className="w-7 h-7" />
            </span>
          </div>

          {/* Heading */}
          <h1
            id="login-heading"
            className="text-center text-xl font-extrabold text-[#111827] leading-snug tracking-tight"
          >
            {t('login.heading1')}
          </h1>
          <p className="text-center text-sm text-[#64748B] mt-1.5 mb-6 leading-relaxed">
            {t('login.subtitle')}
          </p>

          {/* Post-registration info banner */}
          {infoMessage && (
            <div
              role="status"
              className="flex items-start gap-2 text-xs text-emerald-800 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2.5 mb-5"
            >
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" aria-hidden="true" />
              <span>{infoMessage}</span>
            </div>
          )}

          {/* Error banner */}
          {error && (
            <div
              role="alert"
              aria-live="assertive"
              className="flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2.5 mb-5"
            >
              <AlertCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" aria-hidden="true" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate className="space-y-4">

            {/* Name */}
            <div>
              <label htmlFor="login-name" className="block text-xs font-semibold text-[#111827] mb-1.5">
                Name <span className="text-red-500" aria-hidden="true">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <input
                id="login-name"
                type="text"
                value={name}
                onChange={(e) => { setName(e.target.value); setError(''); }}
                placeholder="Enter your name"
                required
                disabled={isSubmitting}
                autoComplete="name"
                className="w-full text-sm px-3.5 py-2.5 rounded-lg border border-[#D9E2EF] bg-[#F5F8FC] text-[#111827] placeholder-[#64748B]/60 focus:outline-none focus:ring-2 focus:ring-[#FFC21A]/50 focus:border-[#D49A00] transition disabled:opacity-60"
              />
            </div>

            {/* Phone Number or Email */}
            <div>
              <label htmlFor="login-phone" className="block text-xs font-semibold text-[#111827] mb-1.5">
                Phone Number or Email <span className="text-red-500" aria-hidden="true">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <input
                id="login-phone"
                type="text"
                value={phone}
                onChange={(e) => { setPhone(e.target.value); setError(''); }}
                placeholder="Enter your phone number or email"
                required
                disabled={isSubmitting}
                autoComplete="username"
                className="w-full text-sm px-3.5 py-2.5 rounded-lg border border-[#D9E2EF] bg-[#F5F8FC] text-[#111827] placeholder-[#64748B]/60 focus:outline-none focus:ring-2 focus:ring-[#FFC21A]/50 focus:border-[#D49A00] transition disabled:opacity-60"
              />
            </div>

            {/* Password */}
            <div>
              <label htmlFor="login-password" className="block text-xs font-semibold text-[#111827] mb-1.5">
                Password <span className="text-red-500" aria-hidden="true">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <div className="relative">
                <input
                  id="login-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setError(''); }}
                  placeholder="Enter your password"
                  required
                  disabled={isSubmitting}
                  autoComplete="current-password"
                  className="w-full text-sm px-3.5 py-2.5 pr-11 rounded-lg border border-[#D9E2EF] bg-[#F5F8FC] text-[#111827] placeholder-[#64748B]/60 focus:outline-none focus:ring-2 focus:ring-[#FFC21A]/50 focus:border-[#D49A00] transition disabled:opacity-60"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#64748B] hover:text-[#111827] transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#D49A00] rounded"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword
                    ? <EyeOff className="w-4 h-4" aria-hidden="true" />
                    : <Eye className="w-4 h-4" aria-hidden="true" />}
                </button>
              </div>
            </div>

            {/* Login button */}
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full flex items-center justify-center gap-2 bg-[#FFC21A] hover:bg-[#D49A00] active:bg-[#B87D00] text-[#111827] text-sm font-bold py-3 rounded-xl transition-colors shadow-sm mt-1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#D49A00] disabled:opacity-60 disabled:cursor-not-allowed"
              aria-busy={isSubmitting}
            >
              {isSubmitting
                ? <><Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /><span>Logging in…</span></>
                : <span>{t('login.loginButton')}</span>}
            </button>

            {/* Sign up link */}
            <div className="pt-3 border-t border-[#D9E2EF] text-center">
              <p className="text-xs text-[#64748B]">
                Don't have an account?{' '}
                <button
                  type="button"
                  onClick={() => navigate('/register')}
                  className="text-[#D49A00] font-semibold hover:underline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#D49A00] rounded"
                >
                  Sign Up
                </button>
              </p>
            </div>

          </form>
        </div>

        {/* Fine print */}
        <p className="mt-4 text-center text-[11px] text-[#64748B] leading-relaxed px-2">
          By continuing you agree to our{' '}
          <span className="font-medium text-[#111827]">Terms of Service</span>
          {' '}and{' '}
          <span className="font-medium text-[#111827]">Privacy Policy</span>.
        </p>
      </div>

      <LanguageSelectModal
        isOpen={showLanguagePrompt}
        mode="onboarding"
        onConfirm={handleLanguageConfirm}
      />
    </div>
  );
}
