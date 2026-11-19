import React, { useState, useEffect, useRef } from 'react';
import Card from '../../components/common/Card';
import Button from '../../components/common/Button';
import NotificationToast from '../../components/common/NotificationToast';
import { UserCircle2, Camera, BellRing, Check, Loader2, ShieldCheck, Mail, Phone, Globe } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { useAuth } from '../../context/AuthContext';
import { getCurrentUserProfile, updateCurrentUserProfile } from '../../services/api';

function ToggleSwitch({ checked, onChange, disabled = false }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex items-center h-6 w-11 rounded-full transition-colors duration-200 focus:outline-none cursor-pointer ${
        checked ? 'bg-emerald-500' : 'bg-slate-300 dark:bg-slate-700'
      } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
    >
      <span
        className={`absolute top-0.5 left-0.5 h-5 w-5 transform rounded-full bg-white shadow transition-transform duration-200 ${
          checked ? 'translate-x-5' : 'translate-x-0'
        }`}
      />
    </button>
  );
}

export default function UserProfile() {
  const { t, language, setLanguage, languages } = useLanguage();
  const { user, updateUser } = useAuth();

  const [fullName, setFullName] = useState(user?.full_name || 'Driver User');
  const [email, setEmail] = useState(user?.email || '');
  const [mobile, setMobile] = useState(user?.mobile || '');
  const [memberSince, setMemberSince] = useState('2024');
  const [userRole, setUserRole] = useState(user?.role || 'user');

  const [voiceAlerts, setVoiceAlerts] = useState(user?.voice_alerts ?? true);
  const [soundAlerts, setSoundAlerts] = useState(user?.sound_alerts ?? true);
  const [vibration, setVibration] = useState(user?.vibration_alerts ?? true);

  const [toastMessage, setToastMessage] = useState(null);
  const [toastType, setToastType] = useState('success');
  const [photoUrl, setPhotoUrl] = useState(user?.avatar_url || null);
  const [isSaving, setIsSaving] = useState(false);
  const [isLoadingProfile, setIsLoadingProfile] = useState(true);

  const fileInputRef = useRef(null);

  // Fetch verified profile from backend database on mount
  useEffect(() => {
    let isMounted = true;
    setIsLoadingProfile(true);

    getCurrentUserProfile()
      .then((profile) => {
        if (!isMounted || !profile) return;
        setFullName(profile.full_name || '');
        setEmail(profile.email || '');
        setMobile(profile.mobile || '');
        setUserRole(profile.role || 'user');
        setPhotoUrl(profile.avatar_url || null);
        setVoiceAlerts(profile.voice_alerts ?? true);
        setSoundAlerts(profile.sound_alerts ?? true);
        setVibration(profile.vibration_alerts ?? true);

        if (profile.created_at) {
          const d = new Date(profile.created_at);
          setMemberSince(d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }));
        }

        if (profile.preferred_language && profile.preferred_language !== language) {
          setLanguage(profile.preferred_language);
        }

        updateUser(profile);
      })
      .catch((err) => {
        console.warn('Could not load profile from server, using cached session:', err);
        if (user) {
          setFullName(user.full_name || '');
          setEmail(user.email || '');
          setMobile(user.mobile || '');
          setUserRole(user.role || 'user');
        }
      })
      .finally(() => {
        if (isMounted) setIsLoadingProfile(false);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const handleChangePhotoClick = () => {
    fileInputRef.current?.click();
  };

  const handlePhotoSelected = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.type.startsWith('image/')) {
      setToastType('error');
      setToastMessage(t('user.profile.toastInvalidImage') || 'Please select a valid image file.');
      return;
    }

    if (file.size > 2 * 1024 * 1024) {
      setToastType('error');
      setToastMessage('Image size exceeds 2MB limit.');
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result;
      setPhotoUrl(dataUrl);
      setToastType('success');
      setToastMessage(t('user.profile.toastPhotoUpdated') || 'Photo selected.');
    };
    reader.readAsDataURL(file);

    e.target.value = '';
  };

  const handleSaveChanges = async (e) => {
    if (e) e.preventDefault();

    const cleanName = fullName.trim();
    if (!cleanName || cleanName.length < 2) {
      setToastType('error');
      setToastMessage('Full name must be at least 2 characters.');
      return;
    }

    setIsSaving(true);
    setToastMessage(null);

    const payload = {
      full_name: cleanName,
      email: email.trim() || null,
      mobile: mobile.trim() || null,
      preferred_language: language,
      avatar_url: photoUrl,
      voice_alerts: voiceAlerts,
      sound_alerts: soundAlerts,
      vibration_alerts: vibration,
    };

    try {
      const updated = await updateCurrentUserProfile(payload);

      // Update persistent auth state
      updateUser(updated || payload);

      setToastType('success');
      setToastMessage(t('user.profile.toastPreferencesSaved') || 'Profile and preferences saved successfully.');
    } catch (err) {
      console.error('Failed to update profile:', err);
      // Fallback local update
      updateUser(payload);
      setToastType('warning');
      setToastMessage(`Saved locally (${err.message})`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="p-4 sm:p-6 md:p-8 space-y-6 max-w-6xl mx-auto">
      {/* Toast Notification */}
      {toastMessage && (
        <NotificationToast message={toastMessage} type={toastType} onClose={() => setToastMessage(null)} />
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 border-b border-gray-200/80 dark:border-slate-800 pb-4">
        <div>
          <h1 className="font-display text-2xl font-extrabold text-navy-900 dark:text-white tracking-tight flex items-center gap-2">
            <UserCircle2 className="w-7 h-7 text-amber-500" />
            {t('user.profile.title')}
          </h1>
          <p className="text-gray-500 dark:text-slate-400 text-sm mt-0.5">
            {t('user.profile.subtitle')}
          </p>
        </div>

        {/* Role badge */}
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-amber-100 text-amber-900 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-300/60 dark:border-amber-800">
            <ShieldCheck className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
            {userRole} Account
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
        {/* Avatar Card */}
        <Card className="md:col-span-4 lg:col-span-3 flex flex-col items-center justify-center text-center py-8">
          <div className="relative group">
            <div className="w-28 h-28 rounded-full bg-slate-100 dark:bg-slate-800 border-2 border-amber-400/80 shadow-md flex items-center justify-center text-slate-400 mb-4 overflow-hidden">
              {photoUrl ? (
                <img src={photoUrl} alt={fullName} className="w-full h-full object-cover" />
              ) : (
                <UserCircle2 className="w-20 h-20 text-slate-400" />
              )}
            </div>
          </div>

          <h3 className="font-display font-bold text-base text-navy-900 dark:text-white truncate max-w-full px-2">
            {fullName || 'Driver User'}
          </h3>
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5 font-mono truncate max-w-full px-2">
            {email || mobile || 'Driver Partner'}
          </p>

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            onChange={handlePhotoSelected}
            className="hidden"
          />
          <div className="mt-4">
            <Button variant="secondary" size="sm" icon={Camera} onClick={handleChangePhotoClick}>
              {t('user.profile.changePhoto')}
            </Button>
          </div>
        </Card>

        {/* Profile details form */}
        <Card className="md:col-span-8 lg:col-span-5">
          <h2 className="text-sm font-bold text-navy-950 dark:text-white uppercase border-b border-gray-100 dark:border-slate-800 pb-2 mb-4 flex items-center gap-2">
            <UserCircle2 className="w-4 h-4 text-amber-500" />
            {t('user.profile.profileDetails')}
          </h2>

          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                {t('user.profile.fullName')}
              </label>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Enter full name"
                className="w-full text-sm px-3.5 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5 flex items-center gap-1.5">
                <Mail className="w-3.5 h-3.5 text-slate-400" />
                {t('user.profile.email')}
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="driver@example.com"
                className="w-full text-sm px-3.5 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5 flex items-center gap-1.5">
                <Phone className="w-3.5 h-3.5 text-slate-400" />
                {t('user.profile.mobileNumber')}
              </label>
              <input
                type="text"
                value={mobile}
                onChange={(e) => setMobile(e.target.value)}
                placeholder="+91 98765 43210"
                className="w-full text-sm px-3.5 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition"
              />
            </div>

            <div className="grid grid-cols-2 gap-3 pt-1">
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5 flex items-center gap-1">
                  <Globe className="w-3 h-3 text-slate-400" />
                  {t('user.profile.preferredLanguage')}
                </label>
                <div className="w-full text-xs font-medium px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                  {languages.find((l) => l.code === language)?.label || 'English'}
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                  {t('user.profile.memberSince')}
                </label>
                <div className="w-full text-xs font-medium px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                  {memberSince}
                </div>
              </div>
            </div>
          </div>
        </Card>

        {/* Alert preferences */}
        <Card className="md:col-span-12 lg:col-span-4">
          <h2 className="text-sm font-bold text-navy-950 dark:text-white uppercase border-b border-gray-100 dark:border-slate-800 pb-2 mb-4 flex items-center gap-1.5">
            <BellRing className="w-4 h-4 text-amber-500" /> {t('user.profile.alertPreferences')}
          </h2>

          <div className="space-y-4">
            <div className="flex items-center justify-between p-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-900/50 transition-colors">
              <div>
                <span className="text-sm font-medium text-slate-800 dark:text-slate-200 block">
                  {t('user.profile.voiceAlerts')}
                </span>
                <span className="text-[11px] text-gray-500 dark:text-slate-400 block">
                  Spoken warnings at 1000m, 500m, and 200m
                </span>
              </div>
              <ToggleSwitch checked={voiceAlerts} onChange={setVoiceAlerts} />
            </div>

            <div className="flex items-center justify-between p-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-900/50 transition-colors">
              <div>
                <span className="text-sm font-medium text-slate-800 dark:text-slate-200 block">
                  {t('user.profile.soundAlerts')}
                </span>
                <span className="text-[11px] text-gray-500 dark:text-slate-400 block">
                  Audible chimes on approaching hazards
                </span>
              </div>
              <ToggleSwitch checked={soundAlerts} onChange={setSoundAlerts} />
            </div>

            <div className="flex items-center justify-between p-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-900/50 transition-colors">
              <div>
                <span className="text-sm font-medium text-slate-800 dark:text-slate-200 block">
                  {t('user.profile.vibration')}
                </span>
                <span className="text-[11px] text-gray-500 dark:text-slate-400 block">
                  Haptic pulses for mobile navigation
                </span>
              </div>
              <ToggleSwitch checked={vibration} onChange={setVibration} />
            </div>

            <div className="pt-3 border-t border-gray-100 dark:border-slate-800">
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5">
                {t('user.profile.language')}
              </label>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full text-sm px-3.5 py-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition"
              >
                {languages.map(({ code, label }) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </select>
            </div>

            <button
              type="button"
              disabled={isSaving}
              onClick={handleSaveChanges}
              className="w-full bg-amber-400 hover:bg-amber-500 text-slate-900 text-sm font-bold py-3 rounded-xl transition-all shadow-md shadow-amber-400/25 flex items-center justify-center gap-2 mt-4 cursor-pointer disabled:opacity-60"
            >
              {isSaving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                <>
                  <Check className="w-4 h-4" />
                  <span>{t('user.profile.saveChanges')}</span>
                </>
              )}
            </button>
          </div>
        </Card>
      </div>
    </div>
  );
}
