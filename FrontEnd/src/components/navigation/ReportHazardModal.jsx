import React, { useState } from 'react';
import { X, Construction, Ban, Cone, AlertTriangle, CheckCircle2, Loader2, MapPin } from 'lucide-react';

const REPORT_TYPES = [
  {
    id: 'CONSTRUCTION',
    label: 'Construction',
    icon: Construction,
    bgColor: 'bg-amber-500',
    hoverBg: 'hover:bg-amber-600',
    lightBg: 'bg-amber-50 dark:bg-amber-950/40',
    borderColor: 'border-amber-300 dark:border-amber-800',
    textColor: 'text-amber-700 dark:text-amber-300',
    severity: 'MEDIUM',
    defaultTitle: 'Road Construction Ahead',
  },
  {
    id: 'POTHOLE',
    label: 'Pothole',
    icon: Cone,
    bgColor: 'bg-orange-500',
    hoverBg: 'hover:bg-orange-600',
    lightBg: 'bg-orange-50 dark:bg-orange-950/40',
    borderColor: 'border-orange-300 dark:border-orange-800',
    textColor: 'text-orange-700 dark:text-orange-300',
    severity: 'MEDIUM',
    defaultTitle: 'Pothole / Road Damage',
  },
  {
    id: 'ROAD_CLOSURE',
    label: 'Road Closure',
    icon: Ban,
    bgColor: 'bg-red-500',
    hoverBg: 'hover:bg-red-600',
    lightBg: 'bg-red-50 dark:bg-red-950/40',
    borderColor: 'border-red-300 dark:border-red-800',
    textColor: 'text-red-700 dark:text-red-300',
    severity: 'HIGH',
    defaultTitle: 'Road Blocked / Closed',
  },
  {
    id: 'HAZARD',
    label: 'Hazard',
    icon: AlertTriangle,
    bgColor: 'bg-yellow-500',
    hoverBg: 'hover:bg-yellow-600',
    lightBg: 'bg-yellow-50 dark:bg-yellow-950/40',
    borderColor: 'border-yellow-300 dark:border-yellow-800',
    textColor: 'text-yellow-700 dark:text-yellow-300',
    severity: 'MEDIUM',
    defaultTitle: 'Road Obstruction',
  },
];

export default function ReportHazardModal({
  isOpen,
  onClose,
  userLocation,
  onSubmit,
}) {
  const [selectedType, setSelectedType] = useState(null);
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [successMessage, setSuccessMessage] = useState(null);

  if (!isOpen) return null;

  const currLat = userLocation?.latitude ?? userLocation?.lat ?? 19.9975;
  const currLng = userLocation?.longitude ?? userLocation?.lng ?? 73.7898;
  const hasValidCoords = !isNaN(currLat) && !isNaN(currLng);

  const handleSelectType = async (typeObj) => {
    setSelectedType(typeObj);
  };

  const handleConfirmSubmit = async () => {
    if (!selectedType) return;
    if (!hasValidCoords) {
      alert('Valid GPS location is required to submit a road report.');
      return;
    }

    setIsSubmitting(true);
    try {
      await onSubmit({
        hazard_type: selectedType.id,
        latitude: Number(currLat),
        longitude: Number(currLng),
        title: selectedType.defaultTitle,
        description: description.trim() || `User reported ${selectedType.label.toLowerCase()} in Nashik`,
        severity: selectedType.severity,
        source: 'USER_REPORT',
      });

      setSuccessMessage(`${selectedType.label} reported successfully!`);
      setTimeout(() => {
        setSuccessMessage(null);
        setSelectedType(null);
        setDescription('');
        onClose();
      }, 1200);
    } catch (err) {
      console.error('Failed to report hazard:', err);
      alert('Failed to submit report. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[1000] flex items-end sm:items-center justify-center p-0 sm:p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-200">
      {/* Modal Card / Bottom Sheet matching Reference Screenshot */}
      <div 
        className="w-full sm:max-w-md bg-white dark:bg-slate-900 rounded-t-3xl sm:rounded-3xl shadow-2xl border border-gray-200 dark:border-slate-800 p-5 space-y-4 animate-in slide-in-from-bottom duration-300"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 dark:border-slate-800 pb-3">
          <h2 className="text-lg font-extrabold text-navy-950 dark:text-white tracking-tight">
            Add a report
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-full hover:bg-gray-100 dark:hover:bg-slate-800 text-gray-500 hover:text-gray-900 dark:text-slate-400 dark:hover:text-white transition-colors cursor-pointer"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {successMessage ? (
          <div className="py-8 flex flex-col items-center justify-center text-center space-y-2">
            <CheckCircle2 className="w-12 h-12 text-emerald-500 animate-bounce" />
            <div className="text-base font-bold text-slate-900 dark:text-white">
              {successMessage}
            </div>
            <p className="text-xs text-slate-400">
              Live hazard placed on map for all Nashik drivers.
            </p>
          </div>
        ) : (
          <>
            {/* Location context */}
            <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/60 p-2.5 rounded-xl border border-slate-200/60 dark:border-slate-700/60">
              <MapPin className="w-4 h-4 text-blue-500 shrink-0" />
              <span className="truncate">
                {hasValidCoords
                  ? `Report location: ${Number(currLat).toFixed(4)}, ${Number(currLng).toFixed(4)}`
                  : 'Acquiring GPS location...'}
              </span>
            </div>

            {/* 4 Report Type Buttons in a 2x2 or 4-row layout matching Google Maps visual reference */}
            <div className="grid grid-cols-2 gap-3 py-1">
              {REPORT_TYPES.map((type) => {
                const IconComponent = type.icon;
                const isSelected = selectedType?.id === type.id;

                return (
                  <button
                    key={type.id}
                    type="button"
                    onClick={() => handleSelectType(type)}
                    className={`p-4 rounded-2xl flex flex-col items-center justify-center gap-2.5 border-2 transition-all cursor-pointer ${
                      isSelected
                        ? `${type.borderColor} ${type.lightBg} shadow-md scale-102 ring-2 ring-blue-500/30`
                        : 'border-gray-200 dark:border-slate-800 bg-gray-50/50 dark:bg-slate-800/40 hover:border-gray-300 dark:hover:border-slate-700'
                    }`}
                  >
                    <div className={`w-12 h-12 rounded-full ${type.bgColor} text-white flex items-center justify-center shadow-md transition-transform hover:scale-105`}>
                      <IconComponent className="w-6 h-6 stroke-[2.2]" />
                    </div>
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200">
                      {type.label}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Optional Details Input */}
            {selectedType && (
              <div className="space-y-2 pt-1 animate-in fade-in duration-150">
                <label className="text-[11px] font-bold text-slate-500 uppercase block">
                  Optional Note ({selectedType.label})
                </label>
                <input
                  type="text"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="e.g. Left lane closed, waterlogged pothole..."
                  className="w-full px-3 py-2 text-xs rounded-xl border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  maxLength={120}
                />
              </div>
            )}

            {/* Submit Action */}
            <div className="pt-2">
              <button
                type="button"
                onClick={handleConfirmSubmit}
                disabled={!selectedType || isSubmitting || !userLocation}
                className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold rounded-xl transition shadow-md flex items-center justify-center gap-2 text-xs cursor-pointer min-h-[44px]"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Broadcasting Hazard to Nashik Fleet...</span>
                  </>
                ) : (
                  <span>Submit {selectedType ? selectedType.label : 'Report'}</span>
                )}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
