import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import Card from '../../components/common/Card';
import Badge from '../../components/common/Badge';
import RiskBadge from '../../components/common/RiskBadge';
import NotificationToast from '../../components/common/NotificationToast';
import { 
  History, 
  Navigation, 
  MapPin, 
  Calendar, 
  Clock, 
  Route as RouteIcon, 
  ShieldAlert, 
  Trash2, 
  Search, 
  ArrowRight, 
  RotateCcw, 
  Loader2, 
  CheckCircle2, 
  TrendingUp, 
  AlertTriangle,
  Play
} from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import { getNavigationHistory, deleteNavigationHistory, clearAllNavigationHistory } from '../../services/api';

export default function UserHistory() {
  const navigate = useNavigate();
  const { t } = useLanguage();

  const [historyItems, setHistoryItems] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterRisk, setFilterRisk] = useState('ALL');

  const [toastMessage, setToastMessage] = useState(null);
  const [toastType, setToastType] = useState('success');

  const fetchHistory = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const resp = await getNavigationHistory({ limit: 100 });
      const items = Array.isArray(resp?.items) ? resp.items : (Array.isArray(resp) ? resp : []);
      setHistoryItems(items);
    } catch (err) {
      console.warn('Failed to load navigation history from backend:', err);
      setError(err.message || 'Failed to load trip history.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  const handleDeleteItem = async (id, e) => {
    if (e) e.stopPropagation();
    if (!confirm('Are you sure you want to delete this trip record?')) return;

    try {
      await deleteNavigationHistory(id);
      setHistoryItems((prev) => prev.filter((item) => item.id !== id));
      setToastType('success');
      setToastMessage('Trip record removed.');
    } catch (err) {
      console.error('Delete history item error:', err);
      setToastType('error');
      setToastMessage(`Failed to delete record: ${err.message}`);
    }
  };

  const handleClearAll = async () => {
    if (!confirm('Clear entire trip history? This action cannot be undone.')) return;

    try {
      await clearAllNavigationHistory();
      setHistoryItems([]);
      setToastType('success');
      setToastMessage('Trip history cleared.');
    } catch (err) {
      console.error('Clear all history error:', err);
      setToastType('error');
      setToastMessage(`Failed to clear history: ${err.message}`);
    }
  };

  const handleNavigateAgain = (item) => {
    navigate('/user/navigation', {
      state: {
        destinationQuery: item.destination_name,
        destinationCoords: item.destination_lat && item.destination_lng ? {
          lat: item.destination_lat,
          lng: item.destination_lng,
          displayName: item.destination_name,
        } : null,
      }
    });
  };

  // Filtered list based on search query and risk level
  const filteredItems = historyItems.filter((item) => {
    const src = (item.source_name || '').toLowerCase();
    const dest = (item.destination_name || '').toLowerCase();
    const q = searchQuery.toLowerCase().trim();
    const matchesSearch = !q || src.includes(q) || dest.includes(q);

    const r = (item.risk_level || 'LOW').toUpperCase();
    const matchesRisk = filterRisk === 'ALL' || r === filterRisk.toUpperCase();

    return matchesSearch && matchesRisk;
  });

  // Aggregate stats
  const totalTrips = historyItems.length;
  const totalDistance = historyItems.reduce((acc, curr) => acc + (Number(curr.distance_km) || 0), 0);
  const totalHotspotsAlerted = historyItems.reduce((acc, curr) => acc + (Number(curr.hotspots_count) || 0), 0);

  return (
    <div className="p-4 sm:p-6 md:p-8 space-y-6 max-w-7xl mx-auto">
      {/* Toast Notification */}
      {toastMessage && (
        <NotificationToast message={toastMessage} type={toastType} onClose={() => setToastMessage(null)} />
      )}

      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-gray-200/80 dark:border-slate-800 pb-4">
        <div>
          <h1 className="font-display text-2xl font-extrabold text-navy-900 dark:text-white tracking-tight flex items-center gap-2">
            <History className="w-7 h-7 text-amber-500" />
            Trip & Navigation History
          </h1>
          <p className="text-gray-500 dark:text-slate-400 text-sm mt-0.5">
            View completed journeys, active route details, distance metrics, and safety hotspots encountered.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={fetchHistory}
            className="px-3 py-2 rounded-xl text-xs font-bold bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 text-slate-700 dark:text-slate-200 hover:bg-gray-50 dark:hover:bg-slate-800 transition shadow-sm flex items-center gap-1.5 cursor-pointer"
            title="Refresh history"
          >
            <RotateCcw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            Refresh
          </button>

          {historyItems.length > 0 && (
            <button
              type="button"
              onClick={handleClearAll}
              className="px-3 py-2 rounded-xl text-xs font-bold bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 text-rose-700 dark:text-rose-300 hover:bg-rose-100 transition shadow-sm flex items-center gap-1.5 cursor-pointer"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Clear History
            </button>
          )}

          <button
            type="button"
            onClick={() => navigate('/user/navigation')}
            className="px-4 py-2 rounded-xl text-xs font-bold bg-amber-400 hover:bg-amber-500 text-slate-900 transition shadow-sm flex items-center gap-1.5 cursor-pointer"
          >
            <Play className="w-3.5 h-3.5" />
            New Trip
          </button>
        </div>
      </div>

      {/* Aggregate Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card className="flex items-center gap-4 p-4 border border-gray-100 dark:border-slate-800">
          <div className="w-12 h-12 rounded-2xl bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-800 flex items-center justify-center text-blue-600 dark:text-blue-400 shrink-0">
            <RouteIcon className="w-6 h-6" />
          </div>
          <div className="min-w-0">
            <span className="text-xs text-gray-500 dark:text-slate-400 uppercase font-bold tracking-wider block">
              Total Journeys
            </span>
            <span className="text-xl sm:text-2xl font-display font-extrabold text-navy-900 dark:text-white mt-0.5 block truncate">
              {totalTrips} {totalTrips === 1 ? 'Trip' : 'Trips'}
            </span>
          </div>
        </Card>

        <Card className="flex items-center gap-4 p-4 border border-gray-100 dark:border-slate-800">
          <div className="w-12 h-12 rounded-2xl bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-800 flex items-center justify-center text-emerald-600 dark:text-emerald-400 shrink-0">
            <TrendingUp className="w-6 h-6" />
          </div>
          <div className="min-w-0">
            <span className="text-xs text-gray-500 dark:text-slate-400 uppercase font-bold tracking-wider block">
              Distance Covered
            </span>
            <span className="text-xl sm:text-2xl font-display font-extrabold text-navy-900 dark:text-white mt-0.5 block truncate">
              {totalDistance.toFixed(1)} km
            </span>
          </div>
        </Card>

        <Card className="flex items-center gap-4 p-4 border border-gray-100 dark:border-slate-800">
          <div className="w-12 h-12 rounded-2xl bg-amber-50 dark:bg-amber-950/60 border border-amber-200 dark:border-amber-800 flex items-center justify-center text-amber-600 dark:text-amber-400 shrink-0">
            <ShieldAlert className="w-6 h-6" />
          </div>
          <div className="min-w-0">
            <span className="text-xs text-gray-500 dark:text-slate-400 uppercase font-bold tracking-wider block">
              Hotspots Monitored
            </span>
            <span className="text-xl sm:text-2xl font-display font-extrabold text-navy-900 dark:text-white mt-0.5 block truncate">
              {totalHotspotsAlerted} Blackspots
            </span>
          </div>
        </Card>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-center justify-between">
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by source or destination..."
            className="w-full text-sm pl-9 pr-4 py-2.5 rounded-xl border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition"
          />
        </div>

        <div className="flex items-center gap-2">
          <select
            value={filterRisk}
            onChange={(e) => setFilterRisk(e.target.value)}
            className="text-xs font-bold px-3 py-2 rounded-xl border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-200 focus:outline-none cursor-pointer"
          >
            <option value="ALL">All Risk Levels</option>
            <option value="LOW">Low Risk</option>
            <option value="MODERATE">Moderate Risk</option>
            <option value="HIGH">High Risk</option>
            <option value="CRITICAL">Critical Risk</option>
          </select>
        </div>
      </div>

      {/* History List Section */}
      {isLoading ? (
        <div className="py-20 flex flex-col items-center justify-center text-center">
          <Loader2 className="w-8 h-8 text-amber-500 animate-spin mb-3" />
          <span className="text-sm font-semibold text-slate-600 dark:text-slate-300">
            Loading your trip records...
          </span>
        </div>
      ) : error ? (
        <div className="p-6 bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 rounded-2xl text-center space-y-3">
          <AlertTriangle className="w-8 h-8 text-rose-600 dark:text-rose-400 mx-auto" />
          <div className="text-sm font-bold text-rose-900 dark:text-rose-200">
            {error}
          </div>
          <button
            type="button"
            onClick={fetchHistory}
            className="px-4 py-2 rounded-xl bg-rose-600 text-white font-bold text-xs hover:bg-rose-700 transition cursor-pointer"
          >
            Try Again
          </button>
        </div>
      ) : filteredItems.length === 0 ? (
        <Card className="py-16 px-6 text-center flex flex-col items-center justify-center border-dashed border-2 border-gray-200 dark:border-slate-800">
          <div className="w-16 h-16 rounded-full bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 flex items-center justify-center text-amber-600 dark:text-amber-400 mb-4">
            <Navigation className="w-8 h-8" />
          </div>
          <h3 className="font-display font-bold text-lg text-navy-900 dark:text-white">
            {searchQuery || filterRisk !== 'ALL' ? 'No matching trips found' : 'No navigation history yet'}
          </h3>
          <p className="text-sm text-gray-500 dark:text-slate-400 mt-1 max-w-md">
            {searchQuery || filterRisk !== 'ALL'
              ? 'Try modifying your search query or risk filter to view other records.'
              : 'Your trips and real-time navigation sessions along selected road corridors will appear here automatically.'}
          </p>
          <div className="mt-5">
            <button
              type="button"
              onClick={() => navigate('/user/navigation')}
              className="px-5 py-2.5 rounded-xl font-bold text-xs bg-amber-400 hover:bg-amber-500 text-slate-900 transition shadow-md shadow-amber-400/25 inline-flex items-center gap-2 cursor-pointer"
            >
              <Navigation className="w-4 h-4" />
              Start Navigation Now
            </button>
          </div>
        </Card>
      ) : (
        <div className="space-y-3.5">
          {filteredItems.map((item) => {
            const dateStr = item.created_at
              ? new Date(item.created_at).toLocaleDateString('en-GB', {
                  day: 'numeric',
                  month: 'short',
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                })
              : 'Recent Trip';

            return (
              <Card 
                key={item.id} 
                className="p-4 sm:p-5 hover:border-amber-400/60 transition-all duration-150 shadow-sm group"
              >
                <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
                  {/* Origin to Destination */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2 flex-wrap">
                      <span className="text-[11px] font-mono font-bold text-slate-400 flex items-center gap-1">
                        <Calendar className="w-3.5 h-3.5" />
                        {dateStr}
                      </span>
                      <span className="text-slate-300 dark:text-slate-700">•</span>
                      <Badge variant="neutral" size="sm">
                        {item.selected_route || 'Route 1'}
                      </Badge>
                      <RiskBadge level={item.risk_level || 'LOW'} size="sm" />
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ${
                        item.status === 'COMPLETED' 
                          ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800'
                          : 'bg-blue-50 text-blue-700 dark:bg-blue-950/60 dark:text-blue-300'
                      }`}>
                        {item.status || 'COMPLETED'}
                      </span>
                    </div>

                    <div className="flex items-start sm:items-center gap-2 text-sm sm:text-base font-bold text-navy-900 dark:text-white">
                      <span className="text-emerald-600 dark:text-emerald-400 shrink-0 flex items-center gap-1">
                        <MapPin className="w-4 h-4" />
                        {item.source_name || 'Current Location'}
                      </span>
                      <ArrowRight className="w-4 h-4 text-slate-400 shrink-0 mx-1" />
                      <span className="text-blue-600 dark:text-blue-400 truncate">
                        {item.destination_name}
                      </span>
                    </div>

                    {item.hotspots_en_route && (
                      <div className="mt-2 text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1.5 flex-wrap">
                        <ShieldAlert className="w-3.5 h-3.5 text-amber-500 shrink-0" />
                        <span className="font-semibold text-slate-700 dark:text-slate-300">Hotspots En Route:</span>
                        <span className="truncate max-w-xl">{item.hotspots_en_route}</span>
                      </div>
                    )}
                  </div>

                  {/* Trip metrics and Actions */}
                  <div className="flex items-center justify-between lg:justify-end gap-3 sm:gap-4 shrink-0 pt-3 lg:pt-0 border-t lg:border-t-0 border-gray-100 dark:border-slate-800">
                    <div className="flex items-center gap-4 text-right">
                      <div>
                        <span className="text-[10px] uppercase font-bold text-gray-400 block tracking-wider">
                          Distance
                        </span>
                        <span className="text-sm font-extrabold text-navy-900 dark:text-white font-mono block">
                          {Number(item.distance_km || 0).toFixed(1)} km
                        </span>
                      </div>
                      <div>
                        <span className="text-[10px] uppercase font-bold text-gray-400 block tracking-wider">
                          Duration
                        </span>
                        <span className="text-sm font-extrabold text-navy-900 dark:text-white font-mono block">
                          {Math.round(item.duration_min || 0)} mins
                        </span>
                      </div>
                      <div>
                        <span className="text-[10px] uppercase font-bold text-gray-400 block tracking-wider">
                          Hotspots
                        </span>
                        <span className="text-sm font-extrabold text-amber-600 dark:text-amber-400 font-mono block">
                          {item.hotspots_count || 0}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5 ml-2">
                      <button
                        type="button"
                        onClick={() => handleNavigateAgain(item)}
                        className="p-2 rounded-xl bg-amber-400 hover:bg-amber-500 text-slate-900 transition shadow-sm cursor-pointer"
                        title="Navigate this route again"
                        aria-label="Navigate this route again"
                      >
                        <Navigation className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => handleDeleteItem(item.id, e)}
                        className="p-2 rounded-xl bg-gray-100 hover:bg-rose-100 dark:bg-slate-800 dark:hover:bg-rose-950/60 text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 transition cursor-pointer"
                        title="Delete trip record"
                        aria-label="Delete trip record"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
