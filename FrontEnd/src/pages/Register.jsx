import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Eye,
  EyeOff,
  ArrowLeft,
  ShieldAlert,
  CheckCircle2,
  Loader2,
  AlertCircle,
  Check,
  X as XIcon,
} from 'lucide-react';
import LanguageSelector from '../components/common/LanguageSelector';
import { useLanguage } from '../context/LanguageContext';
import { registerUser } from '../services/api';

// ────────────────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────────────────

/** Returns a simple array of password-strength rules with pass/fail state. */
function usePasswordRules(password) {
  return [
    { label: 'At least 6 characters', met: password.length >= 6 },
    { label: 'Contains a letter', met: /[a-zA-Z]/.test(password) },
    { label: 'Contains a number', met: /\d/.test(password) },
  ];
}

// ────────────────────────────────────────────────────────────
// Sub-components
// ────────────────────────────────────────────────────────────

function PasswordRules({ password, confirmPassword }) {
  const rules = usePasswordRules(password);
  const mismatch = confirmPassword.length > 0 && password !== confirmPassword;
  const allMet = rules.every((r) => r.met);
  if (!password) return null;

  return (
    <div className="mt-2 space-y-1" role="list" aria-label="Password requirements">
      {rules.map((rule) => (
        <div
          key={rule.label}
          role="listitem"
          className={`flex items-center gap-1.5 text-[11px] font-medium transition-colors ${
            rule.met ? 'text-emerald-700' : 'text-[#64748B]'
          }`}
        >
          {rule.met ? (
            <Check className="w-3 h-3 shrink-0 text-emerald-600" aria-hidden="true" />
          ) : (
            <span className="w-3 h-3 rounded-full border border-[#D9E2EF] shrink-0" aria-hidden="true" />
          )}
          <span>{rule.label}</span>
          <span className="sr-only">{rule.met ? '— requirement met' : '— not yet met'}</span>
        </div>
      ))}
      {allMet && confirmPassword.length > 0 && (
        <div
          role="listitem"
          className={`flex items-center gap-1.5 text-[11px] font-medium ${
            mismatch ? 'text-red-600' : 'text-emerald-700'
          }`}
        >
          {mismatch ? (
            <XIcon className="w-3 h-3 shrink-0" aria-hidden="true" />
          ) : (
            <Check className="w-3 h-3 shrink-0" aria-hidden="true" />
          )}
          <span>{mismatch ? 'Passwords do not match' : 'Passwords match'}</span>
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────
// Main component
// ────────────────────────────────────────────────────────────

export default function Register() {
  const navigate = useNavigate();
  const { t, language } = useLanguage();

  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [mobile, setMobile] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    const trimmedName = fullName.trim();
    const trimmedEmail = email.trim().toLowerCase();
    const trimmedMobile = mobile.trim();
    const trimmedPassword = password.trim();
    const trimmedConfirm = confirmPassword.trim();

    // Client-side validation
    if (!trimmedName || !trimmedEmail || !trimmedPassword || !trimmedConfirm) {
      setError(t('register.errorRequired'));
      return;
    }
    if (trimmedName.length < 2) {
      setError(t('register.errorNameShort'));
      return;
    }
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(trimmedEmail)) {
      setError(t('register.errorInvalidEmail'));
      return;
    }
    if (trimmedPassword.length < 6) {
      setError(t('register.errorPasswordShort'));
      return;
    }
    if (trimmedPassword !== trimmedConfirm) {
      setError(t('register.errorPasswordMismatch'));
      return;
    }

    setIsSubmitting(true);
    try {
      const payload = {
        full_name: trimmedName,
        email: trimmedEmail,
        password: trimmedPassword,
        mobile: trimmedMobile || undefined,
        preferred_language: language || 'en',
        role: 'user',
        voice_alerts: true,
        sound_alerts: true,
        vibration_alerts: true,
      };

      await registerUser(payload);
      setSuccessMessage(t('register.successRedirect'));

      setTimeout(() => {
        navigate('/login', {
          state: {
            role: 'user',
            registeredEmail: trimmedEmail,
            message: t('register.loginRedirectMessage'),
          },
        });
      }, 1200);
    } catch (err) {
      console.error('Registration failed:', err);
      setError(err?.message || t('register.errorGeneric'));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F5F8FC] flex items-start sm:items-center justify-center p-4 sm:p-5">
      <div className="w-full max-w-md mt-8 sm:mt-0">

        {/* Top bar */}
        <div className="flex items-center justify-between mb-6">
          <button
            type="button"
            onClick={() => navigate('/')}
            className="flex items-center gap-1.5 text-sm text-[#64748B] hover:text-[#111827] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#D49A00] rounded"
            aria-label="Back to Home"
          >
            <ArrowLeft className="w-4 h-4" aria-hidden="true" />
            <span>{t('register.backToHome')}</span>
          </button>
          <LanguageSelector variant="light" />
        </div>

        {/* Card */}
        <div
          className="bg-white rounded-2xl border border-[#D9E2EF] shadow-[0_2px_16px_0_rgba(17,24,39,0.06)] p-7 sm:p-8"
          role="main"
          aria-labelledby="register-heading"
        >
          {/* Shield logo */}
          <div className="flex justify-center mb-4">
            <span
              className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-[#FFC21A] text-[#111827] shadow-sm"
              aria-hidden="true"
            >
              <ShieldAlert className="w-7 h-7" />
            </span>
          </div>

          <h1
            id="register-heading"
            className="text-center text-xl font-extrabold text-[#111827] leading-snug tracking-tight"
          >
            {t('register.title')}
          </h1>
          <p className="text-center text-sm text-[#64748B] mt-1 mb-6 leading-relaxed">
            {t('register.subtitle')}
          </p>

          {/* Success banner */}
          {successMessage && (
            <div
              role="status"
              aria-live="polite"
              className="flex items-start gap-2 text-xs text-emerald-800 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2.5 mb-5"
            >
              <CheckCircle2
                className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5"
                aria-hidden="true"
              />
              <span>{successMessage}</span>
            </div>
          )}

          {/* Error banner */}
          {error && (
            <div
              role="alert"
              aria-live="assertive"
              className="flex items-start gap-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2.5 mb-5"
            >
              <AlertCircle
                className="w-4 h-4 text-red-500 shrink-0 mt-0.5"
                aria-hidden="true"
              />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate className="space-y-4">
            {/* Full Name */}
            <div>
              <label
                htmlFor="reg-name"
                className="block text-xs font-semibold text-[#111827] mb-1.5"
              >
                {t('register.fullNameLabel')}{' '}
                <span className="text-red-500" aria-hidden="true">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <input
                id="reg-name"
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder={t('register.fullNamePlaceholder')}
                required
                disabled={isSubmitting}
                autoComplete="name"
                className="w-full text-sm px-3.5 py-2.5 rounded-lg border border-[#D9E2EF] bg-[#F5F8FC] text-[#111827] placeholder-[#64748B]/60 focus:outline-none focus:ring-2 focus:ring-[#FFC21A]/50 focus:border-[#D49A00] transition disabled:opacity-60"
              />
            </div>

            {/* Email */}
            <div>
              <label
                htmlFor="reg-email"
                className="block text-xs font-semibold text-[#111827] mb-1.5"
              >
                {t('register.emailLabel')}{' '}
                <span className="text-red-500" aria-hidden="true">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <input
                id="reg-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t('register.emailPlaceholder')}
                required
                disabled={isSubmitting}
                autoComplete="email"
                inputMode="email"
                className="w-full text-sm px-3.5 py-2.5 rounded-lg border border-[#D9E2EF] bg-[#F5F8FC] text-[#111827] placeholder-[#64748B]/60 focus:outline-none focus:ring-2 focus:ring-[#FFC21A]/50 focus:border-[#D49A00] transition disabled:opacity-60"
              />
            </div>

            {/* Mobile (optional) */}
            <div>
              <label
                htmlFor="reg-mobile"
                className="block text-xs font-semibold text-[#111827] mb-1.5"
              >
                {t('register.mobileLabel')}{' '}
                <span className="text-[#64748B] font-normal text-[11px]">
                  {t('register.optional')}
                </span>
              </label>
              <input
                id="reg-mobile"
                type="tel"
                value={mobile}
                onChange={(e) => setMobile(e.target.value)}
                placeholder={t('register.mobilePlaceholder')}
                disabled={isSubmitting}
                autoComplete="tel"
                inputMode="tel"
                className="w-full text-sm px-3.5 py-2.5 rounded-lg border border-[#D9E2EF] bg-[#F5F8FC] text-[#111827] placeholder-[#64748B]/60 focus:outline-none focus:ring-2 focus:ring-[#FFC21A]/50 focus:border-[#D49A00] transition disabled:opacity-60"
              />
            </div>

            {/* Password */}
            <div>
              <label
                htmlFor="reg-password"
                className="block text-xs font-semibold text-[#111827] mb-1.5"
              >
                {t('register.passwordLabel')}{' '}
                <span className="text-red-500" aria-hidden="true">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <div className="relative">
                <input
                  id="reg-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={t('register.passwordPlaceholder')}
                  required
                  disabled={isSubmitting}
                  autoComplete="new-password"
                  aria-describedby="password-rules"
                  className="w-full text-sm px-3.5 py-2.5 pr-11 rounded-lg border border-[#D9E2EF] bg-[#F5F8FC] text-[#111827] placeholder-[#64748B]/60 focus:outline-none focus:ring-2 focus:ring-[#FFC21A]/50 focus:border-[#D49A00] transition disabled:opacity-60"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#64748B] hover:text-[#111827] transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#D49A00] rounded"
                  aria-label={showPassword ? t('register.hidePassword') : t('register.showPassword')}
                >
                  {showPassword ? (
                    <EyeOff className="w-4 h-4" aria-hidden="true" />
                  ) : (
                    <Eye className="w-4 h-4" aria-hidden="true" />
                  )}
                </button>
              </div>
              <div id="password-rules">
                <PasswordRules password={password} confirmPassword={confirmPassword} />
              </div>
            </div>

            {/* Confirm Password */}
            <div>
              <label
                htmlFor="reg-confirm"
                className="block text-xs font-semibold text-[#111827] mb-1.5"
              >
                {t('register.confirmPasswordLabel')}{' '}
                <span className="text-red-500" aria-hidden="true">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <div className="relative">
                <input
                  id="reg-confirm"
                  type={showConfirmPassword ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder={t('register.confirmPasswordPlaceholder')}
                  required
                  disabled={isSubmitting}
                  autoComplete="new-password"
                  aria-invalid={
                    confirmPassword.length > 0 && password !== confirmPassword
                      ? 'true'
                      : undefined
                  }
                  className={`w-full text-sm px-3.5 py-2.5 pr-11 rounded-lg border bg-[#F5F8FC] text-[#111827] placeholder-[#64748B]/60 focus:outline-none focus:ring-2 transition disabled:opacity-60 ${
                    confirmPassword.length > 0 && password !== confirmPassword
                      ? 'border-red-400 focus:ring-red-400/30 focus:border-red-500'
                      : 'border-[#D9E2EF] focus:ring-[#FFC21A]/50 focus:border-[#D49A00]'
                  }`}
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#64748B] hover:text-[#111827] transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#D49A00] rounded"
                  aria-label={
                    showConfirmPassword ? t('register.hidePassword') : t('register.showPassword')
                  }
                >
                  {showConfirmPassword ? (
                    <EyeOff className="w-4 h-4" aria-hidden="true" />
                  ) : (
                    <Eye className="w-4 h-4" aria-hidden="true" />
                  )}
                </button>
              </div>
              {confirmPassword.length > 0 && password !== confirmPassword && (
                <p role="alert" className="mt-1.5 text-[11px] font-medium text-red-600 flex items-center gap-1">
                  <XIcon className="w-3 h-3" aria-hidden="true" />
                  {t('register.errorPasswordMismatch')}
                </p>
              )}
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={isSubmitting || !!successMessage}
              className="w-full flex items-center justify-center gap-2 bg-[#FFC21A] hover:bg-[#D49A00] active:bg-[#B87D00] text-[#111827] text-sm font-bold py-3 rounded-xl transition-colors shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#D49A00] disabled:opacity-60 disabled:cursor-not-allowed mt-1"
              aria-busy={isSubmitting}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                  <span>{t('register.submitting')}</span>
                </>
              ) : (
                t('register.submitButton')
              )}
            </button>
          </form>

          {/* Footer link */}
          <div className="mt-6 pt-4 border-t border-[#D9E2EF] text-center">
            <p className="text-xs text-[#64748B]">
              Already have an account?{' '}
              <button
                type="button"
                onClick={() => navigate('/login', { state: { role: 'user' } })}
                className="text-[#D49A00] font-semibold hover:underline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#D49A00] rounded"
              >
                Log In
              </button>
            </p>
          </div>
        </div>

        {/* Disclaimer */}
        <p className="mt-4 text-center text-[11px] text-[#64748B] leading-relaxed px-2">
          By creating an account you agree to our{' '}
          <span className="font-medium text-[#111827]">Terms of Service</span>
          {' '}and{' '}
          <span className="font-medium text-[#111827]">Privacy Policy</span>.
        </p>
      </div>
    </div>
  );
}
