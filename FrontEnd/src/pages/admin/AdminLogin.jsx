import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Eye, EyeOff, ArrowLeft, ShieldCheck, Loader2, AlertCircle } from 'lucide-react';
import LanguageSelector from '../../components/common/LanguageSelector';
import { useLanguage } from '../../context/LanguageContext';
import { useAuth } from '../../context/AuthContext';

const DEFAULT_ADMIN_EMAIL = 'admin@margrakshak.in';
const DEFAULT_ADMIN_PASSWORD = 'Admin@123';

/**
 * Admin Login page — unified light theme, same design system as User Login
 * and User Sign Up.  Authentication logic is unchanged from original.
 */
export default function AdminLogin() {
  const navigate = useNavigate();
  const { t } = useLanguage();
  const { login } = useAuth();

  // Pre-filled per original requirement 3
  const [email, setEmail] = useState(DEFAULT_ADMIN_EMAIL);
  const [password, setPassword] = useState(DEFAULT_ADMIN_PASSWORD);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!email.trim() || !password.trim()) {
      setError(t('login.errorRequired') || 'Email and password are required.');
      return;
    }
    setError('');
    setIsSubmitting(true);

    const normalizedEmail = email.trim().toLowerCase();

    // Enforce only the authorized admin email
    if (normalizedEmail !== DEFAULT_ADMIN_EMAIL.toLowerCase()) {
      setError(
        t('login.adminRestricted') ||
          'Admin access is restricted to the authorized administrator account.'
      );
      setIsSubmitting(false);
      return;
    }

    let authUser = {
      full_name: 'System Administrator',
      email: normalizedEmail,
      role: 'admin',
    };

    try {
      const loginPayload = JSON.stringify({
        email: normalizedEmail,
        password: password.trim(),
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
          authUser = { ...authUser, ...data.user, role: 'admin' };
        }
        const token = data.access_token || data.token || null;
        login(authUser, token);
        navigate('/admin/dashboard');
        return;
      } else if (res.status === 403) {
        const errData = await res.json().catch(() => ({}));
        setError(errData.detail || 'Admin access is restricted to authorized credentials.');
        setIsSubmitting(false);
        return;
      } else if (res.status === 401) {
        setError('Incorrect email or password.');
        setIsSubmitting(false);
        return;
      } else if (res.status >= 500) {
        throw new Error('Backend server unreachable');
      } else {
        const errData = await res.json().catch(() => ({}));
        setError(errData.detail || 'Authentication failed. Please check server status.');
        setIsSubmitting(false);
        return;
      }
    } catch (err) {
      // Offline fallback — check password locally before granting session
      console.warn('Backend unreachable during admin login, using local session:', err);
      if (password.trim() !== DEFAULT_ADMIN_PASSWORD) {
        setError('Incorrect email or password.');
        setIsSubmitting(false);
        return;
      }
      login(authUser);
      navigate('/admin/dashboard');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F5F8FC] flex items-start sm:items-center justify-center p-4 sm:p-5">
      <div className="w-full max-w-sm mt-8 sm:mt-0">

        {/* Top bar */}
        <div className="flex items-center justify-between mb-6">
          <button
            type="button"
            onClick={() => navigate('/')}
            className="flex items-center gap-1.5 text-sm text-[#64748B] hover:text-[#111827] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#D49A00] rounded"
            aria-label="Back to Home"
          >
            <ArrowLeft className="w-4 h-4" aria-hidden="true" />
            <span>{t('login.backToHome') || 'Back to Home'}</span>
          </button>
          <LanguageSelector variant="light" />
        </div>

        {/* Card */}
        <div
          className="bg-white rounded-2xl border border-[#D9E2EF] shadow-[0_2px_16px_0_rgba(17,24,39,0.06)] p-8"
          role="main"
          aria-labelledby="admin-login-heading"
        >
          {/* Shield logo */}
          <div className="flex justify-center mb-4">
            <span
              className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-[#FFC21A] text-[#111827] shadow-sm"
              aria-hidden="true"
            >
              <ShieldCheck className="w-7 h-7" />
            </span>
          </div>

          {/* Badge */}
          <div className="flex justify-center mb-3">
            <span className="inline-block text-[11px] font-bold uppercase tracking-wider text-[#64748B] bg-[#F5F8FC] border border-[#D9E2EF] px-3 py-0.5 rounded-full">
              Authorized Access Only
            </span>
          </div>

          <h1
            id="admin-login-heading"
            className="text-center text-xl font-extrabold text-[#111827] leading-snug tracking-tight"
          >
            Admin Login
          </h1>
          <p className="text-center text-sm text-[#64748B] mt-1 mb-6 leading-relaxed">
            Municipal Corporation &amp; Traffic Police Command
          </p>

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
            {/* Admin Email */}
            <div>
              <label
                htmlFor="admin-email"
                className="block text-xs font-semibold text-[#111827] mb-1.5"
              >
                Admin Email Address{' '}
                <span className="text-red-500" aria-hidden="true">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <input
                id="admin-email"
                type="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  setError('');
                }}
                placeholder="admin@margrakshak.in"
                required
                disabled={isSubmitting}
                autoComplete="email"
                className="w-full text-sm px-3.5 py-2.5 rounded-lg border border-[#D9E2EF] bg-[#F5F8FC] text-[#111827] placeholder-[#64748B]/60 focus:outline-none focus:ring-2 focus:ring-[#FFC21A]/50 focus:border-[#D49A00] transition disabled:opacity-60"
              />
            </div>

            {/* Admin Password */}
            <div>
              <label
                htmlFor="admin-password"
                className="block text-xs font-semibold text-[#111827] mb-1.5"
              >
                Admin Password{' '}
                <span className="text-red-500" aria-hidden="true">*</span>
                <span className="sr-only">(required)</span>
              </label>
              <div className="relative">
                <input
                  id="admin-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    setError('');
                  }}
                  placeholder="Enter admin password"
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
                  {showPassword ? (
                    <EyeOff className="w-4 h-4" aria-hidden="true" />
                  ) : (
                    <Eye className="w-4 h-4" aria-hidden="true" />
                  )}
                </button>
              </div>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full flex items-center justify-center gap-2 bg-[#FFC21A] hover:bg-[#D49A00] active:bg-[#B87D00] text-[#111827] text-sm font-bold py-3 rounded-xl transition-colors shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#D49A00] disabled:opacity-60 disabled:cursor-not-allowed mt-1"
              aria-busy={isSubmitting}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                  <span>Authenticating…</span>
                </>
              ) : (
                <>
                  <ShieldCheck className="w-4 h-4" aria-hidden="true" />
                  <span>Sign In as Admin</span>
                </>
              )}
            </button>
          </form>
        </div>

        {/* Disclaimer */}
        <p className="mt-4 text-center text-[11px] text-[#64748B] leading-relaxed px-2">
          Access is restricted to the authorized system administrator only.
        </p>
      </div>
    </div>
  );
}
