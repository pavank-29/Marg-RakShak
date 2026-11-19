import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import MapView from '../../components/MapView';
import { getHotspots, saveNavigationHistory, evaluateRouteRisk, getHazards, reportHazard } from '../../services/api';
import { normalizeHotspot, getFallbackHotspots } from '../../data/hotspots';

import RiskBadge from '../../components/common/RiskBadge';
import NotificationToast from '../../components/common/NotificationToast';
import TelemetryHUD from '../../components/common/TelemetryHUD';
import ReportHazardModal from '../../components/navigation/ReportHazardModal';
import { useGeolocation } from '../../hooks/useGeolocation';
import { useTrackingSocket } from '../../hooks/useTrackingSocket';
import { useAuth } from '../../context/AuthContext';
import { voiceAlert } from '../../utils/voice';
import { getSpeechLang, t as tVoicePhrase, getSavedLanguage, buildHotspotAlertMessage, PHRASES } from '../../utils/i18n';
import { useLanguage } from '../../context/LanguageContext';
import { 
  geocodePlace, 
  reverseGeocode, 
  fetchRoadRoutes, 
  searchPlaces, 
  validateRouteCoordinates 
} from '../../utils/geocode';
import { findHotspotsNearRoute, findHazardsNearRoute, calculateDistanceMeters, getPointRouteCorridorInfo } from '../../utils/distance';
import {
  isPushSupported,
  getNotificationPermission,
  requestNotificationPermission,
  sendHotspotPushNotification,
  resetNotificationTracker
} from '../../utils/notifications';
import {
  MapPin,
  Navigation,
  Volume2,
  VolumeX,
  Play,
  Square,
  AlertCircle,
  AlertTriangle,
  LocateFixed,
  Search,
  Loader2,
  Crosshair,
  X,
  Car,
  Bike,
  ShieldAlert,
  Plus,
  Trash2,
  ChevronUp,
  ChevronDown,
  Sparkles,
  Route as RouteIcon,
  Radio,
  Bell,
  BellOff,
  Construction,
  Ban,
  Cone
} from 'lucide-react';

/**
 * Calculates perpendicular shortest geographic distance in meters from a user point to a polyline
 */
function getDistanceToRouteMeters(userLat, userLng, path) {
  if (!path || path.length < 2) return Infinity;
  let minDistance = Infinity;

  for (let i = 0; i < path.length - 1; i++) {
    const p1 = path[i];
    const p2 = path[i + 1];

    const d1 = calculateDistanceMeters(userLat, userLng, p1[0], p1[1]);
    const segLen = calculateDistanceMeters(p1[0], p1[1], p2[0], p2[1]);

    let dSeg;
    if (segLen === 0) {
      dSeg = d1;
    } else {
      const dLat = p2[0] - p1[0];
      const dLng = p2[1] - p1[1];
      const t = Math.max(0, Math.min(1, ((userLat - p1[0]) * dLat + (userLng - p1[1]) * dLng) / (dLat * dLat + dLng * dLng)));
      const projLat = p1[0] + t * dLat;
      const projLng = p1[1] + t * dLng;
      dSeg = calculateDistanceMeters(userLat, userLng, projLat, projLng);
    }

    if (dSeg < minDistance) {
      minDistance = dSeg;
    }
  }

  return minDistance;
}

function buildRouteSummary(rawRoute, activeHotspots = [], hazardsList = []) {
  // Use exact 80m corridor threshold for accident hotspots
  const hotspotsEnRoute = findHotspotsNearRoute(rawRoute.path, activeHotspots, 80);
  // Use 120m corridor threshold for road hazards (construction, potholes, closures)
  const hazardsEnRoute = findHazardsNearRoute(rawRoute.path, hazardsList, 120);

  const hasCritical = hotspotsEnRoute.some((h) => h.riskLevel === 'CRITICAL');
  const hasHigh = hotspotsEnRoute.some((h) => h.riskLevel === 'HIGH');

  let riskLevel = 'LOW';
  if (hasCritical) {
    riskLevel = 'HIGH';
  } else if (hasHigh || hotspotsEnRoute.length >= 2) {
    riskLevel = 'MODERATE';
  }

  const distKm = Number(rawRoute.distanceKm || 0);
  const durMin = Number(rawRoute.durationMin || 0);

  return {
    ...rawRoute,
    distance: `${distKm.toFixed(1)} km`,
    time: `${Math.round(durMin)} mins`,
    distanceKm: distKm,
    durationMin: durMin,
    isRecommended: Boolean(rawRoute.isRecommended),
    recommendationReason: rawRoute.recommendationReason || (rawRoute.isAlternative ? 'Alternative Road Option' : 'Primary Road Route'),
    riskLevel,
    totalHotspots: hotspotsEnRoute.length,
    totalHazards: hazardsEnRoute.length,
    hazardsEnRoute,
    hotspotsEnRoute: hotspotsEnRoute.map((h) => ({
      name: h.name,
      risk: h.riskLevel,
      detail: `${h.distanceToRouteMeters} m from route`,
      lat: h.latitude ?? h.lat,
      lng: h.longitude ?? h.lng,
      policeStation: h.policeStation || '',
      is_predicted: Boolean(h.is_predicted || h.isPredicted),
      source: h.source || 'HISTORICAL_BLACKSPOT',
      confidence: h.confidence,
      uncertainty_note: h.uncertainty_note,
    })),
  };
}

export default function UserNavigation() {
  const navigate = useNavigate();
  const routerLocation = useLocation();
  const { t } = useLanguage();
  const { user } = useAuth();
  const { location: userLoc, status: locationStatus, heartbeatTick } = useGeolocation(true);
  const [vehicleType, setVehicleType] = useState('car');
  const [isNavigating, setIsNavigating] = useState(false);
  const [followCamera, setFollowCamera] = useState(true);
  const [showBreadcrumbs, setShowBreadcrumbs] = useState(false);
  const [navigationStats, setNavigationStats] = useState({
    distanceRemainingMeters: 0,
    etaMinutes: 0,
    nearestBlackspot: null,
    nearestBlackspotDistanceM: null,
  });

  const [showFleet, setShowFleet] = useState(true);
  const lastProximityCheckRef = useRef({ lat: 0, lng: 0, time: 0 });

  // Tracking WebSocket hook for 1-second telemetry broadcasting & live fleet updates
  const { isConnected: isSocketConnected, latencyMs, activeFleet } = useTrackingSocket({
    enabled: true,
    location: userLoc,
    userName: user?.full_name || 'Driver #1',
    vehicleType,
    vehicleColor: '#2563eb',
  });

  // Deduplication cache for voice alerts
  const alertedThresholds = useRef({});
  const alertedHazards = useRef({});
  const hasAnnouncedArrival = useRef(false);

  // Prominent Hotspot Proximity Alert Banner State (Requirement 8)
  const [activeHotspotAlert, setActiveHotspotAlert] = useState(null);

  useEffect(() => {
    if (!activeHotspotAlert) return;
    const timer = setTimeout(() => {
      setActiveHotspotAlert(null);
    }, 8000);
    return () => clearTimeout(timer);
  }, [activeHotspotAlert]);

  // Nashik road hazards state
  const [hazards, setHazards] = useState([]);
  const [showReportModal, setShowReportModal] = useState(false);

  const handleReportHazard = async (hazardPayload) => {
    try {
      const res = await reportHazard(hazardPayload);
      const newHazard = res?.hazard || {
        ...hazardPayload,
        id: `user_hz_${Date.now()}`,
        is_active: true,
        source: 'USER_REPORT',
      };
      setHazards((prev) => [newHazard, ...prev]);
      setToastType('success');
      setToastMessage(`Report submitted: ${hazardPayload.title} placed on map.`);
    } catch (err) {
      console.error('Failed to submit hazard report:', err);
      throw err;
    }
  };

  useEffect(() => {
    let isMounted = true;
    getHazards({ is_active: true })
      .then((data) => {
        if (isMounted && data && Array.isArray(data.hazards)) {
          setHazards(data.hazards);
        }
      })
      .catch((err) => console.warn('Could not load hazards:', err));
    return () => { isMounted = false; };
  }, []);


  // Dynamic Rerouting & Off-Route tracking refs
  const offRouteCount = useRef(0);
  const lastRerouteTime = useRef(0);
  const isRerouting = useRef(false);
  const lastGeocodedCoords = useRef(null);

  // Push notifications permission state
  const [pushPermission, setPushPermission] = useState(() => getNotificationPermission());

  // Source state: live GPS by default, can be overridden by manual entry or picking on map
  const [sourceLabel, setSourceLabel] = useState(t('user.navigation.fetchingLocation'));
  const [sourceInputText, setSourceInputText] = useState('');
  const [customSourceCoords, setCustomSourceCoords] = useState(null); // { lat, lng, displayName }
  const [sourceSuggestions, setSourceSuggestions] = useState([]);
  const [showSourceSuggestions, setShowSourceSuggestions] = useState(false);
  const [isSearchingSource, setIsSearchingSource] = useState(false);
  const sourceSearchTimeout = useRef(null);

  // Destination (Blank by default per Requirement 2)
  const [destinationQuery, setDestinationQuery] = useState(() => routerLocation.state?.destinationQuery || '');
  const [destinationCoords, setDestinationCoords] = useState(() => routerLocation.state?.destinationCoords || null);
  const [destinationSuggestions, setDestinationSuggestions] = useState([]);
  const [showDestSuggestions, setShowDestSuggestions] = useState(false);
  const [isSearchingDest, setIsSearchingDest] = useState(false);
  const destSearchTimeout = useRef(null);

  // Dynamic intermediate stops / waypoints: Source -> Stop 1 -> Stop 2 -> Stop 3 -> Destination
  const [waypoints, setWaypoints] = useState(() => {
    if (Array.isArray(routerLocation.state?.waypoints) && routerLocation.state.waypoints.length > 0) {
      return routerLocation.state.waypoints.map((wp, idx) => ({
        id: wp.id || `stop_${Date.now()}_${idx}`,
        query: wp.label || wp.displayName || '',
        coords: wp.lat && wp.lng ? { lat: wp.lat, lng: wp.lng, displayName: wp.label } : null,
      }));
    }
    return [];
  });

  // Manual map location selection modes
  // pickingMode can be: 'source' | 'destination' | { type: 'stop', id: string, index: number } | null
  const [pickingMode, setPickingMode] = useState(null);
  const [clickedPoint, setClickedPoint] = useState(null); // { lat, lng, label }

  // Available route alternatives: Route 1, Route 2
  const [availableRoutes, setAvailableRoutes] = useState(() => {
    if (routerLocation.state?.selectedRoute) {
      const initRoute = {
        ...routerLocation.state.selectedRoute,
        id: 'route-1',
        label: 'Route 1',
        routeNumber: 1
      };
      return [initRoute];
    }
    return [];
  });

  const [selectedRouteId, setSelectedRouteId] = useState(() => {
    return routerLocation.state?.selectedRoute ? 'route-1' : null;
  });

  const [isSearchingRoute, setIsSearchingRoute] = useState(false);
  const [filterRouteHotspotsOnly, setFilterRouteHotspotsOnly] = useState(true);

  // Unified Blackspots dataset with live DB & offline fallback
  const [hotspots, setHotspots] = useState(getFallbackHotspots);
  const [isHotspotsLoading, setIsHotspotsLoading] = useState(true);

  const loadHotspots = useCallback(async () => {
    setIsHotspotsLoading(true);
    try {
      const data = await getHotspots({ limit: 200 });
      const items = Array.isArray(data) ? data : (data?.items || []);
      if (items.length > 0) {
        const normalized = items.map(normalizeHotspot);
        const unique = [];
        for (const spot of normalized) {
          const sLat = spot.latitude ?? spot.lat;
          const sLng = spot.longitude ?? spot.lng;
          const isDup = unique.some((prev) => {
            const pLat = prev.latitude ?? prev.lat;
            const pLng = prev.longitude ?? prev.lng;
            return calculateDistanceMeters(sLat, sLng, pLat, pLng) < 250;
          });
          if (!isDup) unique.push(spot);
        }
        setHotspots(unique);
      } else {
        const rawFallback = getFallbackHotspots();
        const unique = [];
        for (const spot of rawFallback) {
          const sLat = spot.latitude ?? spot.lat;
          const sLng = spot.longitude ?? spot.lng;
          const isDup = unique.some((prev) => {
            const pLat = prev.latitude ?? prev.lat;
            const pLng = prev.longitude ?? prev.lng;
            return calculateDistanceMeters(sLat, sLng, pLat, pLng) < 250;
          });
          if (!isDup) unique.push(spot);
        }
        setHotspots(unique);
      }
    } catch (err) {
      console.warn('Backend unreachable in UserNavigation, using fallback mock hotspots:', err);
      const rawFallback = getFallbackHotspots();
      const unique = [];
      for (const spot of rawFallback) {
        const sLat = spot.latitude ?? spot.lat;
        const sLng = spot.longitude ?? spot.lng;
        const isDup = unique.some((prev) => {
          const pLat = prev.latitude ?? prev.lat;
          const pLng = prev.longitude ?? prev.lng;
          return calculateDistanceMeters(sLat, sLng, pLat, pLng) < 250;
        });
        if (!isDup) unique.push(spot);
      }
      setHotspots(unique);
    } finally {
      setIsHotspotsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadHotspots();
  }, [loadHotspots]);

  const [voiceOn, setVoiceOn] = useState(false);
  const [alertLang] = useState(() => getSavedLanguage() || 'en');
  const [toastMessage, setToastMessage] = useState(null);
  const [toastType, setToastType] = useState('success');

  // Currently selected active route object
  const selectedRoute = useMemo(() => {
    if (!availableRoutes || availableRoutes.length === 0) return null;
    return availableRoutes.find((r) => r.id === selectedRouteId) || availableRoutes[0];
  }, [availableRoutes, selectedRouteId]);

  // Combined hotspots for MapView: verified blackspots + ML predicted hotspots along active route
  const activeMapHotspots = useMemo(() => {
    if (selectedRoute && Array.isArray(selectedRoute.predictedHotspots) && selectedRoute.predictedHotspots.length > 0) {
      return [...hotspots, ...selectedRoute.predictedHotspots];
    }
    return hotspots;
  }, [hotspots, selectedRoute]);

  // GPS fix reverse geocode: Produces short readable name and preserves coordinates internally
  useEffect(() => {
    if (customSourceCoords) return; // User selected/typed a manual source

    if (locationStatus === 'active') {
      const currLat = userLoc.latitude;
      const currLng = userLoc.longitude;

      let shouldGeocode = false;
      if (!lastGeocodedCoords.current) {
        shouldGeocode = true;
      } else {
        const d = calculateDistanceMeters(
          lastGeocodedCoords.current.lat,
          lastGeocodedCoords.current.lng,
          currLat,
          currLng
        );
        if (d > 45) shouldGeocode = true;
      }

      if (shouldGeocode) {
        lastGeocodedCoords.current = { lat: currLat, lng: currLng };
        reverseGeocode(currLat, currLng).then((shortName) => {
          const name = shortName || `Current Location (${currLat.toFixed(4)}, ${currLng.toFixed(4)})`;
          setSourceLabel(name);
          setSourceInputText(name);
        });
      }
    } else if (locationStatus === 'error') {
      const errLabel = `${t('user.navigation.locationUnavailable')} (${userLoc.latitude.toFixed(4)}, ${userLoc.longitude.toFixed(4)})`;
      setSourceLabel(errLabel);
      setSourceInputText(errLabel);
    } else if (locationStatus === 'locating') {
      setSourceLabel(t('user.navigation.fetchingLocation'));
      setSourceInputText(t('user.navigation.fetchingLocation'));
    }
  }, [locationStatus, userLoc.latitude, userLoc.longitude, customSourceCoords, t]);

  // Handle source manual typing & autocomplete
  const handleSourceInputChange = (val) => {
    setSourceInputText(val);
    setCustomSourceCoords(null); // Typing invalidates previous coordinate

    if (sourceSearchTimeout.current) clearTimeout(sourceSearchTimeout.current);
    if (!val || val.trim().length < 2) {
      setSourceSuggestions([]);
      setShowSourceSuggestions(false);
      return;
    }

    setIsSearchingSource(true);
    sourceSearchTimeout.current = setTimeout(async () => {
      try {
        const results = await searchPlaces(val, 5);
        setSourceSuggestions(results);
        setShowSourceSuggestions(results.length > 0);
      } catch {
        setSourceSuggestions([]);
      } finally {
        setIsSearchingSource(false);
      }
    }, 280);
  };

  const handleSelectSourceSuggestion = (sug) => {
    setCustomSourceCoords({ lat: sug.lat, lng: sug.lng, displayName: sug.shortName });
    setSourceLabel(sug.shortName);
    setSourceInputText(sug.shortName);
    setShowSourceSuggestions(false);
    setSourceSuggestions([]);
    setToastType('success');
    setToastMessage(`Source set: ${sug.shortName}`);
  };

  // Handle destination typing & autocomplete
  const handleDestinationInputChange = (val) => {
    setDestinationQuery(val);
    setDestinationCoords(null);

    if (destSearchTimeout.current) clearTimeout(destSearchTimeout.current);
    if (!val || val.trim().length < 2) {
      setDestinationSuggestions([]);
      setShowDestSuggestions(false);
      return;
    }

    setIsSearchingDest(true);
    destSearchTimeout.current = setTimeout(async () => {
      try {
        const results = await searchPlaces(val, 5);
        setDestinationSuggestions(results);
        setShowDestSuggestions(results.length > 0);
      } catch {
        setDestinationSuggestions([]);
      } finally {
        setIsSearchingDest(false);
      }
    }, 280);
  };

  const handleSelectDestSuggestion = (sug) => {
    setDestinationCoords({ lat: sug.lat, lng: sug.lng, displayName: sug.shortName });
    setDestinationQuery(sug.shortName);
    setShowDestSuggestions(false);
    setDestinationSuggestions([]);
    setToastType('success');
    setToastMessage(`Destination set: ${sug.shortName}`);
  };

  // Push notifications toggle handler
  const handleTogglePushNotifications = async () => {
    if (!isPushSupported()) {
      setToastType('error');
      setToastMessage('Push notifications are not supported in this browser.');
      return;
    }

    const current = getNotificationPermission();
    if (current === 'granted') {
      setToastType('info');
      setToastMessage('Push notifications are already active for 500m, 300m, and 200m warnings.');
      return;
    }

    const nextPerm = await requestNotificationPermission();
    setPushPermission(nextPerm);
    if (nextPerm === 'granted') {
      setToastType('success');
      setToastMessage('Push notifications enabled! You will receive alerts at 500m, 300m, and 200m.');
      sendHotspotPushNotification({
        name: 'MargRakshak Navigation',
        distanceMeters: 500,
        riskLevel: 'LOW',
        policeStation: 'System Active',
      });
    } else if (nextPerm === 'denied') {
      setToastType('error');
      setToastMessage('Notification permission was denied in browser settings.');
    }
  };

  // Waypoint / Intermediate Stops Management
  const handleAddStop = () => {
    if (waypoints.length >= 5) {
      setToastType('error');
      setToastMessage('Maximum 5 intermediate stops allowed.');
      return;
    }
    const newId = `stop_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`;
    setWaypoints((prev) => [...prev, { id: newId, query: '', coords: null }]);
  };

  const handleRemoveStop = (id) => {
    setWaypoints((prev) => prev.filter((w) => w.id !== id));
    setAvailableRoutes([]);
    setSelectedRouteId(null);
  };

  const handleMoveStop = (index, direction) => {
    setWaypoints((prev) => {
      const next = [...prev];
      const targetIdx = direction === 'up' ? index - 1 : index + 1;
      if (targetIdx < 0 || targetIdx >= next.length) return prev;
      const temp = next[index];
      next[index] = next[targetIdx];
      next[targetIdx] = temp;
      return next;
    });
    setAvailableRoutes([]);
    setSelectedRouteId(null);
  };

  const handleStopQueryChange = (id, value) => {
    setWaypoints((prev) =>
      prev.map((w) => (w.id === id ? { ...w, query: value, coords: null } : w))
    );
  };

  // Map click handler (supports Source, Stops, Destination, and General click)
  const handleMapClick = async ({ lat, lng }) => {
    if (pickingMode === 'source') {
      setCustomSourceCoords({ lat, lng });
      const fallbackDisplay = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
      setSourceLabel(`Selected: ${fallbackDisplay}`);
      setSourceInputText(fallbackDisplay);
      setPickingMode(null);
      setToastType('success');
      setToastMessage('Source location selected from map.');
      try {
        const placeName = await reverseGeocode(lat, lng);
        if (placeName) {
          setCustomSourceCoords({ lat, lng, displayName: placeName });
          setSourceLabel(placeName);
          setSourceInputText(placeName);
        }
      } catch {}
    } else if (pickingMode === 'destination') {
      const coords = { lat, lng, displayName: `${lat.toFixed(4)}, ${lng.toFixed(4)}` };
      setDestinationCoords(coords);
      setDestinationQuery(`${lat.toFixed(4)}, ${lng.toFixed(4)}`);
      setPickingMode(null);
      setToastType('success');
      setToastMessage('Destination selected from map.');
      try {
        const placeName = await reverseGeocode(lat, lng);
        if (placeName) {
          setDestinationCoords({ lat, lng, displayName: placeName });
          setDestinationQuery(placeName);
        }
      } catch {}
    } else if (pickingMode && typeof pickingMode === 'object' && pickingMode.type === 'stop') {
      const stopId = pickingMode.id;
      const stopNumber = pickingMode.index + 1;
      const display = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;

      setWaypoints((prev) =>
        prev.map((w) =>
          w.id === stopId ? { ...w, query: display, coords: { lat, lng, displayName: display } } : w
        )
      );
      setPickingMode(null);
      setToastType('success');
      setToastMessage(`Stop #${stopNumber} set from map.`);

      try {
        const placeName = await reverseGeocode(lat, lng);
        if (placeName) {
          setWaypoints((prev) =>
            prev.map((w) =>
              w.id === stopId ? { ...w, query: placeName, coords: { lat, lng, displayName: placeName } } : w
            )
          );
        }
      } catch {}
    } else {
      setClickedPoint({ lat, lng, label: `${lat.toFixed(4)}, ${lng.toFixed(4)}` });
      try {
        const placeName = await reverseGeocode(lat, lng);
        if (placeName) {
          setClickedPoint({ lat, lng, label: placeName });
        }
      } catch {}
    }
  };

  const handleSetFromClicked = (type) => {
    if (!clickedPoint) return;
    if (type === 'source') {
      setCustomSourceCoords({ lat: clickedPoint.lat, lng: clickedPoint.lng, displayName: clickedPoint.label });
      setSourceLabel(clickedPoint.label);
      setSourceInputText(clickedPoint.label);
      setToastType('success');
      setToastMessage('Source location updated from map.');
    } else if (type === 'destination') {
      setDestinationCoords({ lat: clickedPoint.lat, lng: clickedPoint.lng, displayName: clickedPoint.label });
      setDestinationQuery(clickedPoint.label);
      setToastType('success');
      setToastMessage('Destination location updated from map.');
    } else if (type === 'stop') {
      if (waypoints.length >= 5) {
        setToastType('error');
        setToastMessage('Maximum 5 intermediate stops allowed.');
      } else {
        const newId = `stop_${Date.now()}`;
        setWaypoints((prev) => [
          ...prev,
          {
            id: newId,
            query: clickedPoint.label,
            coords: { lat: clickedPoint.lat, lng: clickedPoint.lng, displayName: clickedPoint.label },
          },
        ]);
        setToastType('success');
        setToastMessage(`Added Stop: ${clickedPoint.label}`);
      }
    }
    setClickedPoint(null);
  };

  const handleResetGpsSource = () => {
    setCustomSourceCoords(null);
    lastGeocodedCoords.current = null;
    setShowSourceSuggestions(false);
    setToastType('info');
    setToastMessage('Reset source to live GPS location.');

    if (locationStatus === 'active') {
      reverseGeocode(userLoc.latitude, userLoc.longitude).then((shortName) => {
        const name = shortName || `Current Location (${userLoc.latitude.toFixed(4)}, ${userLoc.longitude.toFixed(4)})`;
        setSourceLabel(name);
        setSourceInputText(name);
      });
    } else {
      setSourceLabel(t('user.navigation.fetchingLocation'));
      setSourceInputText(t('user.navigation.fetchingLocation'));
    }
  };

  // Find routes including all intermediate stops + genuine alternatives
  const handleFindRoute = async () => {
    if (!destinationQuery.trim() && !destinationCoords) {
      setToastType('error');
      setToastMessage('Please enter or pick a destination on the map.');
      return;
    }

    setIsSearchingRoute(true);
    setAvailableRoutes([]);
    setSelectedRouteId(null);
    setShowSourceSuggestions(false);
    setShowDestSuggestions(false);

    try {
      // 1. Resolve Destination coordinates
      let dest = destinationCoords;
      if (!dest || !dest.lat || !dest.lng) {
        dest = await geocodePlace(
          /nashik/i.test(destinationQuery) ? destinationQuery : `${destinationQuery}, Nashik`
        );
        setDestinationCoords(dest);
        setDestinationQuery(dest.displayName || destinationQuery);
      }

      // 2. Resolve Source coordinates
      let from = null;
      if (customSourceCoords && !isNaN(customSourceCoords.lat) && !isNaN(customSourceCoords.lng)) {
        from = customSourceCoords;
      } else if (sourceInputText && sourceInputText.trim() && sourceInputText !== sourceLabel) {
        const geocodedSrc = await geocodePlace(
          /nashik/i.test(sourceInputText) ? sourceInputText : `${sourceInputText}, Nashik`
        );
        from = geocodedSrc;
        setCustomSourceCoords(geocodedSrc);
        setSourceLabel(geocodedSrc.displayName || sourceInputText);
      } else if (!isNaN(userLoc.latitude) && !isNaN(userLoc.longitude)) {
        from = { lat: userLoc.latitude, lng: userLoc.longitude, displayName: sourceLabel || 'Current Location' };
      }

      if (!from || isNaN(from.lat) || isNaN(from.lng)) {
        throw new Error('Valid starting source coordinates not available. Please allow GPS or pick on map.');
      }

      // Validate coordinates
      validateRouteCoordinates(from, dest);

      // 3. Resolve all intermediate waypoints
      const resolvedWaypoints = [];
      for (let i = 0; i < waypoints.length; i++) {
        const wp = waypoints[i];
        if (wp.coords && !isNaN(wp.coords.lat) && !isNaN(wp.coords.lng)) {
          resolvedWaypoints.push({
            id: wp.id,
            lat: wp.coords.lat,
            lng: wp.coords.lng,
            label: wp.coords.displayName || wp.query || `Stop ${i + 1}`,
            stopNumber: i + 1,
          });
        } else if (wp.query && wp.query.trim()) {
          const q = /nashik/i.test(wp.query) ? wp.query : `${wp.query}, Nashik`;
          try {
            const geocoded = await geocodePlace(q);
            resolvedWaypoints.push({
              id: wp.id,
              lat: geocoded.lat,
              lng: geocoded.lng,
              label: geocoded.displayName || wp.query,
              stopNumber: i + 1,
            });
            setWaypoints((prev) =>
              prev.map((item) => (item.id === wp.id ? { ...item, coords: geocoded } : item))
            );
          } catch (err) {
            throw new Error(`Could not find location for Stop #${i + 1} ("${wp.query}"). Please refine or pick on map.`);
          }
        }
      }

      // 4. Fetch routes from Backend Traffic Routing API (or OSRM fallback)
      const rawRoutes = await fetchRoadRoutes(from, dest, { 
        waypoints: resolvedWaypoints,
        vehicleType,
        alternatives: true 
      });

      if (!rawRoutes || rawRoutes.length === 0) {
        throw new Error('No drivable road route found connecting all points.');
      }

      // 5. Query Backend ML Route Safety Engine for multi-route evaluation
      let evaluatedRoutes = null;
      try {
        const routePayload = {
          routes: rawRoutes.map((r, idx) => ({
            route_id: r.id || `route-${idx + 1}`,
            label: r.label || `Route ${idx + 1}`,
            distance_km: Number(r.distanceKm.toFixed(2)),
            duration_minutes: Number(r.durationMin.toFixed(1)),
            path: r.path || []
          })),
          vehicle_type: (vehicleType || 'CAR').toUpperCase(),
          current_speed: userLoc?.speed ? userLoc.speed * 3.6 : 35.0,
          weather: 'CLEAR',
          road_condition: 'NORMAL',
          lighting: 'DAYLIGHT'
        };
        const mlRouteRes = await evaluateRouteRisk(routePayload);
        if (mlRouteRes?.routes && Array.isArray(mlRouteRes.routes)) {
          evaluatedRoutes = mlRouteRes.routes;
        }
      } catch (mlErr) {
        console.warn('Backend ML route risk calculation failed, using heuristic:', mlErr);
      }

      // 6. Build Route summaries enriched with ML dynamic risk scoring & predicted hotspots
      const summarized = rawRoutes.map((r, idx) => {
        const summary = buildRouteSummary(r, hotspots, hazards);
        const routeId = r.id || `route-${idx + 1}`;
        const mlEval = evaluatedRoutes?.find((m) => m.route_id === routeId);

        const category = mlEval?.category || (r.isRecommended ? 'Recommended Practical Route' : (idx === 0 ? 'Primary Road Route' : 'Alternative Road Route'));
        const safetyScore = mlEval?.safety_score ?? (summary.riskLevel === 'CRITICAL' ? 35 : (summary.riskLevel === 'HIGH' ? 62 : 88));
        const riskLevel = mlEval?.risk_level || summary.riskLevel;
        const riskScore = mlEval?.risk_score ?? (summary.riskLevel === 'CRITICAL' ? 0.82 : (summary.riskLevel === 'HIGH' ? 0.60 : 0.22));

        const existingBlackspots = mlEval?.existing_blackspots || [];
        const rawPredicted = mlEval?.predicted_hotspots || [];
        const predictedHotspots = rawPredicted.map((p, pIdx) => ({
          ...p,
          id: p.id || `ml-predicted-${routeId}-${pIdx}`,
          name: p.name || `ML Risk Area ${pIdx + 1}`,
          lat: Number(p.latitude ?? p.lat),
          lng: Number(p.longitude ?? p.lng),
          latitude: Number(p.latitude ?? p.lat),
          longitude: Number(p.longitude ?? p.lng),
          riskLevel: p.risk_level || 'HIGH',
          riskScore: p.risk_score || 0.72,
          confidence: p.confidence || 0.84,
          contributingFactors: p.contributing_factors || [],
          uncertaintyNote: p.uncertainty_note || 'Dynamic road segment risk estimate computed by ML model. Not a verified historical collision blackspot.',
          is_predicted: true,
          isPredicted: true,
          source: 'ML_PREDICTED',
        }));

        const blackspotsCount = mlEval?.existing_blackspots_count ?? mlEval?.blackspots_count ?? summary.totalHotspots;
        const mlHotspotsCount = mlEval?.predicted_hotspots_count ?? mlEval?.ml_hotspots_count ?? predictedHotspots.length;
        const totalHotspots = mlEval?.total_hotspots_count ?? (blackspotsCount + mlHotspotsCount);
        const contributingFactors = mlEval?.contributing_factors || [];

        return {
          ...summary,
          id: routeId,
          label: r.label || `Route ${idx + 1}`,
          routeNumber: idx + 1,
          category,
          safetyScore,
          riskLevel,
          riskScore,
          blackspotsCount,
          mlHotspotsCount,
          totalHotspots,
          existingBlackspots,
          predictedHotspots,
          contributingFactors,
          tag: `${category} • ${safetyScore}/100 Safety`,
          isAlternative: idx > 0,
          isRecommended: r.isRecommended || idx === 0,
        };
      });

      const recIndex = summarized.findIndex((r) => r.isRecommended);
      const chosenId = recIndex >= 0 ? summarized[recIndex].id : (summarized[0]?.id || 'route-1');

      setAvailableRoutes(summarized);
      setSelectedRouteId(chosenId);

      setToastType('success');
      const destName = (dest.displayName || destinationQuery).split(',')[0];
      setToastMessage(
        summarized.length > 1
          ? `Calculated ${summarized.length} practical road routes to ${destName}.`
          : `Route calculated successfully to ${destName}.`
      );
    } catch (err) {
      setToastType('error');
      setToastMessage(err.message || t('user.navigation.toastCouldNotFindRoute'));
    } finally {
      setIsSearchingRoute(false);
    }
  };

  const handleVoiceToggle = () => {
    const nextVoiceState = !voiceOn;
    setVoiceOn(nextVoiceState);
    voiceAlert.setMute(!nextVoiceState);

    if (nextVoiceState) {
      setToastType('success');
      setToastMessage(t('user.navigation.toastVoiceActive'));
      voiceAlert.speak(tVoicePhrase('voiceActivated', alertLang), getSpeechLang(alertLang));
    } else {
      setToastType('info');
      setToastMessage(t('user.navigation.toastVoiceMuted'));
      voiceAlert.cancel();
    }
  };

  const handleSelectRoute = (routeId) => {
    setSelectedRouteId(routeId);
    alertedThresholds.current = {};
    alertedHazards.current = {};
    setActiveHotspotAlert(null);
    resetNotificationTracker();
    const chosen = availableRoutes.find((r) => r.id === routeId);
    if (chosen) {
      setToastType('info');
      setToastMessage(`Selected ${chosen.label || 'Route'} as active route. Corridor blackspots updated.`);
      if (voiceOn && isNavigating) {
        voiceAlert.speak(`Switched active route to ${chosen.label || 'Route'}.`, getSpeechLang(alertLang));
      }
    }
  };

  const handleStartTrip = () => {
    if (!selectedRoute) {
      setToastType('error');
      setToastMessage(t('user.navigation.toastFindRouteFirst'));
      return;
    }

    setIsNavigating(true);
    hasAnnouncedArrival.current = false;
    alertedThresholds.current = {};
    alertedHazards.current = {};
    setActiveHotspotAlert(null);
    resetNotificationTracker();
    offRouteCount.current = 0;

    setToastType('success');
    setToastMessage('Live GPS navigation active. Tracking along active route.');

    if (voiceOn) {
      voiceAlert.speak(tVoicePhrase('tripStarted', alertLang), getSpeechLang(alertLang));
    }

    try {
      const srcName = (sourceLabel || 'Starting Location').split(',')[0].trim();
      const dstName = (destinationCoords?.displayName || destinationQuery || 'Destination').split(',')[0].trim();
      const hotspotsSummary = (selectedRoute.hotspotsEnRoute || []).map((h) => h.name).slice(0, 5).join(', ');

      saveNavigationHistory({
        source_name: srcName,
        source_lat: effectiveSource?.lat,
        source_lng: effectiveSource?.lng,
        destination_name: dstName,
        destination_lat: destinationCoords?.lat,
        destination_lng: destinationCoords?.lng,
        selected_route: selectedRoute.label || `Route ${selectedRoute.routeNumber || 1}`,
        distance_km: parseFloat(selectedRoute.distanceKm) || 0.0,
        duration_min: parseFloat(selectedRoute.durationMin) || 0.0,
        hotspots_count: selectedRoute.totalHotspots || 0,
        hotspots_en_route: hotspotsSummary || null,
        risk_level: selectedRoute.riskLevel || 'LOW',
        status: 'COMPLETED',
      }).catch((err) => {
        console.warn('Could not record trip history in DB:', err);
      });
    } catch (err) {
      console.warn('Trip history logging error:', err);
    }
  };

  const handleStopNavigation = () => {
    setIsNavigating(false);
    voiceAlert.cancel();
    alertedThresholds.current = {};
    alertedHazards.current = {};
    setActiveHotspotAlert(null);
    resetNotificationTracker();
    hasAnnouncedArrival.current = false;
    offRouteCount.current = 0;
    setToastType('info');
    setToastMessage('Live navigation stopped.');
  };

  // Dynamic reroute trigger when user deviates off-route
  const triggerOffRouteReroute = async () => {
    if (isRerouting.current || !destinationCoords) return;
    isRerouting.current = true;

    try {
      const msg = PHRASES.offRouteRerouting?.[alertLang] || 'Off-route detected. Recalculating route to destination.';
      setToastType('warning');
      setToastMessage(msg);
      if (voiceOn) {
        voiceAlert.speak(msg, getSpeechLang(alertLang));
      }

      const currFrom = {
        lat: userLoc.latitude,
        lng: userLoc.longitude,
        displayName: 'Current Location',
      };

      const newRoutes = await fetchRoadRoutes(currFrom, destinationCoords, {
        waypoints: waypoints.map((w, idx) => ({
          lat: w.coords?.lat,
          lng: w.coords?.lng,
          label: w.coords?.displayName || w.query || `Stop ${idx + 1}`,
        })).filter((w) => w.lat && w.lng),
        vehicleType,
        alternatives: false,
      });

      if (newRoutes && newRoutes.length > 0) {
        const newSummary = buildRouteSummary(newRoutes[0], hotspots, hazards);
        const reroutedObj = {
          ...newSummary,
          id: `reroute-${Date.now()}`,
          label: 'Rerouted Path',
          routeNumber: 1,
          category: 'Dynamic Reroute',
          tag: 'Dynamic Reroute Active',
          safetyScore: newSummary.riskLevel === 'CRITICAL' ? 45 : (newSummary.riskLevel === 'HIGH' ? 65 : 88),
          isAlternative: false,
          isRecommended: true,
        };

        setAvailableRoutes([reroutedObj]);
        setSelectedRouteId(reroutedObj.id);
        alertedThresholds.current = {};
        alertedHazards.current = {};
        setActiveHotspotAlert(null);
        resetNotificationTracker();

        setToastType('success');
        setToastMessage('New dynamic road route active.');
      }
    } catch (err) {
      console.warn('Dynamic rerouting failed:', err);
    } finally {
      isRerouting.current = false;
    }
  };

  // Continuous Proximity, Blackspot Safety Monitor & Off-Route Detection along active selected route
  useEffect(() => {
    if (!isNavigating || !selectedRoute) return;
    if (isNaN(userLoc.latitude) || isNaN(userLoc.longitude)) return;

    // Movement & time throttle: avoid running heavy proximity math if standing still or < 2.5m moved in < 1000ms
    const now = Date.now();
    const distMoved = calculateDistanceMeters(
      userLoc.latitude,
      userLoc.longitude,
      lastProximityCheckRef.current.lat,
      lastProximityCheckRef.current.lng
    );
    if (distMoved < 2.5 && (now - lastProximityCheckRef.current.time) < 1000) {
      return;
    }
    lastProximityCheckRef.current = { lat: userLoc.latitude, lng: userLoc.longitude, time: now };

    // 1. Destination distance check
    if (destinationCoords && destinationCoords.lat && destinationCoords.lng) {
      const distToDest = calculateDistanceMeters(
        userLoc.latitude,
        userLoc.longitude,
        destinationCoords.lat,
        destinationCoords.lng
      );
      const speedKmh = Math.max(15, userLoc.speed || 30);
      const estEta = Math.max(1, Math.round((distToDest / 1000) / (speedKmh / 60)));

      if (distToDest <= 40 && !hasAnnouncedArrival.current) {
        hasAnnouncedArrival.current = true;
        const msg = PHRASES.arrived[alertLang] || 'You have arrived at your destination.';
        setToastType('success');
        setToastMessage(msg);
        if (voiceOn) {
          voiceAlert.speak(msg, getSpeechLang(alertLang));
        }
      }

      // 2. Dynamic Off-Route Deviation Detection & Recalculation
      if (selectedRoute.path && selectedRoute.path.length >= 2 && !isRerouting.current) {
        const distFromRoute = getDistanceToRouteMeters(
          userLoc.latitude,
          userLoc.longitude,
          selectedRoute.path
        );

        // Threshold: 65 meters or 1.5x GPS accuracy
        const offRouteThreshold = Math.max(65, (userLoc.accuracy || 10) * 1.5);

        if (distFromRoute > offRouteThreshold) {
          offRouteCount.current += 1;
          const now = Date.now();
          if (offRouteCount.current >= 3 && now - lastRerouteTime.current > 15000) {
            lastRerouteTime.current = now;
            offRouteCount.current = 0;
            triggerOffRouteReroute();
          }
        } else {
          offRouteCount.current = 0;
        }
      }

      // 3. Active route blackspots proximity check (deduplicated per active route)
      // Required alert thresholds: 500m, 300m, 200m
      const routeHotspots = selectedRoute.hotspotsEnRoute || [];
      let closestSpot = null;
      let minSpotDist = Infinity;

      const userRouteInfo = selectedRoute.path?.length >= 2
        ? getPointRouteCorridorInfo(userLoc.latitude, userLoc.longitude, selectedRoute.path)
        : null;
      const userProgress = userRouteInfo?.distanceAlongRouteMeters ?? 0;

      const ALERT_THRESHOLDS = [500, 300, 200];

      for (const spot of routeHotspots) {
        const spotLat = spot.lat ?? spot.latitude;
        const spotLng = spot.lng ?? spot.longitude;
        if (spotLat == null || spotLng == null) continue;

        // Skip hotspots that have already been passed (behind user by > 30m)
        if (selectedRoute.path?.length >= 2) {
          const spotRouteInfo = getPointRouteCorridorInfo(spotLat, spotLng, selectedRoute.path);
          if (spotRouteInfo.distanceAlongRouteMeters < userProgress - 30) {
            continue;
          }
        }

        const dM = Math.round(
          calculateDistanceMeters(userLoc.latitude, userLoc.longitude, spotLat, spotLng)
        );

        if (dM < minSpotDist) {
          minSpotDist = dM;
          closestSpot = spot;
        }

        if (!alertedThresholds.current[spot.name]) {
          alertedThresholds.current[spot.name] = new Set();
        }
        const spokenSet = alertedThresholds.current[spot.name];

        // Hysteresis: Reset alert state when user moves sufficiently away (> 650m) and approaches again
        if (dM > 650 && spokenSet.size > 0) {
          spokenSet.clear();
        }

        for (const thresh of ALERT_THRESHOLDS) {
          if (dM <= thresh && !spokenSet.has(thresh)) {
            spokenSet.add(thresh);

            // Exact mandated voice message (Requirement 3)
            const exactVoiceMsg = "Approaching accident hotspot, slow down your speed.";

            // Prominent On-Screen Alert Banner (Requirement 8)
            setActiveHotspotAlert({
              title: 'ACCIDENT HOTSPOT AHEAD',
              distanceMeters: thresh,
              message: exactVoiceMsg,
              spotName: spot.name,
              risk: spot.risk || 'HIGH',
              timestamp: Date.now(),
            });

            setToastType(thresh <= 200 ? 'error' : thresh <= 300 ? 'warning' : 'info');
            setToastMessage(`ACCIDENT HOTSPOT AHEAD (${thresh}m): ${spot.name}`);

            // Voice Alert (fail gracefully without crashing navigation)
            if (voiceOn) {
              try {
                voiceAlert.speak(exactVoiceMsg, 'en-US');
              } catch (voiceErr) {
                console.warn('Speech synthesis unavailable or failed:', voiceErr);
              }
            }

            // Push Notification (500m, 300m, 200m)
            sendHotspotPushNotification({
              name: spot.name,
              distanceMeters: thresh,
              riskLevel: spot.risk,
              policeStation: spot.policeStation || '',
            });
          }
        }
      }

      // 4. Active road hazards proximity alerts along route
      if (hazards && hazards.length > 0) {
        for (const haz of hazards) {
          if (!haz.latitude || !haz.longitude) continue;
          const hDist = Math.round(
            calculateDistanceMeters(userLoc.latitude, userLoc.longitude, haz.latitude, haz.longitude)
          );
          if (hDist <= 350 && !alertedHazards.current[haz.id]) {
            alertedHazards.current[haz.id] = true;
            const hazMsg = `Road hazard ahead in ${hDist}m: ${haz.title || haz.hazard_type}. Drive with caution.`;
            setToastType('warning');
            setToastMessage(hazMsg);
            if (voiceOn) {
              voiceAlert.speak(hazMsg, getSpeechLang(alertLang));
            }
          }
        }
      }

      setNavigationStats({
        distanceRemainingMeters: Math.round(distToDest),
        etaMinutes: estEta,
        nearestBlackspot: closestSpot,
        nearestBlackspotDistanceM: minSpotDist !== Infinity ? minSpotDist : null,
      });
    }
  }, [isNavigating, userLoc, selectedRoute, destinationCoords, voiceOn, alertLang]);

  const isLiveFix = locationStatus === 'active';
  const effectiveSource = customSourceCoords || { lat: userLoc.latitude, lng: userLoc.longitude };

  // Formatted waypoints for MapView
  const mapWaypoints = useMemo(() => {
    return waypoints
      .map((w, idx) => {
        if (!w.coords || isNaN(w.coords.lat) || isNaN(w.coords.lng)) return null;
        return {
          id: w.id,
          lat: w.coords.lat,
          lng: w.coords.lng,
          label: w.coords.displayName || w.query || `Stop ${idx + 1}`,
          stopNumber: idx + 1,
        };
      })
      .filter(Boolean);
  }, [waypoints]);

  return (
    <div className="p-3 sm:p-4 md:p-6 space-y-4 sm:space-y-5 max-w-7xl mx-auto">
      {/* Toast popup */}
      {toastMessage && (
        <NotificationToast message={toastMessage} type={toastType} onClose={() => setToastMessage(null)} />
      )}

      {/* Prominent On-Screen Hotspot Proximity Alert Banner (Requirement 8) */}
      {activeHotspotAlert && (
        <div 
          className="fixed top-6 left-1/2 -translate-x-1/2 z-[5500] w-[92%] sm:w-auto min-w-[340px] max-w-lg bg-gradient-to-r from-red-600 via-rose-600 to-amber-600 text-white p-4 rounded-2xl shadow-2xl border-2 border-white/40 backdrop-blur-md transition-all pointer-events-auto"
          role="alert"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-11 h-11 rounded-xl bg-white/20 flex items-center justify-center shrink-0 shadow-inner">
                <ShieldAlert className="w-6 h-6 text-white animate-pulse" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-extrabold text-xs tracking-wider uppercase text-amber-200">
                    ACCIDENT HOTSPOT AHEAD
                  </span>
                  <span className="px-2 py-0.5 rounded-full bg-black/40 text-xs font-black text-white">
                    {activeHotspotAlert.distanceMeters} m
                  </span>
                </div>
                <p className="font-bold text-white text-sm mt-0.5">
                  {activeHotspotAlert.spotName}
                </p>
                <p className="text-white/95 text-xs mt-1 font-medium">
                  Approaching accident hotspot, slow down your speed.
                </p>
              </div>
            </div>
            <button
              onClick={() => setActiveHotspotAlert(null)}
              className="p-1 rounded-lg hover:bg-white/25 text-white/80 hover:text-white transition-colors cursor-pointer"
              aria-label="Dismiss alert"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="font-display text-xl md:text-2xl font-bold text-navy-900 dark:text-white tracking-tight uppercase flex items-center gap-2">
            <RouteIcon className="w-6 h-6 text-blue-600" />
            {t('user.navigation.pageTitle')}
          </h1>
          <p className="text-gray-500 dark:text-slate-400 text-sm">
            {t('user.navigation.pageSubtitle')}
          </p>
        </div>

        {/* Live GPS Status & Controls */}
        <div className="flex items-center flex-wrap gap-2.5 bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-xl p-1.5 shadow-sm text-xs">
          <div className="flex items-center gap-1.5 px-2 py-1 bg-gray-50 dark:bg-slate-800 rounded-lg">
            <span className="relative flex h-2 w-2">
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${locationStatus === 'active' ? 'bg-emerald-400' : 'bg-amber-400'}`} />
              <span className={`relative inline-flex rounded-full h-2 w-2 ${locationStatus === 'active' ? 'bg-emerald-500' : 'bg-amber-500'}`} />
            </span>
            <span className="text-[11px] font-bold text-slate-700 dark:text-slate-200">
              {locationStatus === 'active' ? 'GPS Active' : 'Acquiring GPS'}
            </span>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded font-bold bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300">
              ±{userLoc.accuracy ? Math.round(userLoc.accuracy) : 8}m
            </span>
          </div>

          {/* Push Notification Toggle Button */}
          <button
            type="button"
            onClick={handleTogglePushNotifications}
            className={`px-2 py-1 rounded-lg text-[11px] font-bold flex items-center gap-1 transition-colors cursor-pointer border ${
              pushPermission === 'granted'
                ? 'bg-blue-50 text-blue-700 border-blue-300 dark:bg-blue-950/60 dark:text-blue-300 dark:border-blue-800'
                : 'bg-gray-50 text-gray-600 border-gray-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700 hover:bg-gray-100'
            }`}
            title={pushPermission === 'granted' ? 'Push Notifications Active (500m, 300m, 200m)' : 'Click to enable hotspot push alerts'}
          >
            {pushPermission === 'granted' ? (
              <>
                <Bell className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
                <span className="hidden sm:inline">Push On</span>
              </>
            ) : (
              <>
                <BellOff className="w-3.5 h-3.5 text-gray-400" />
                <span className="hidden sm:inline">Push Alerts</span>
              </>
            )}
          </button>

          {/* Vehicle Mode Switch */}
          <div className="flex items-center bg-gray-100 dark:bg-slate-800 rounded-lg p-0.5 border border-gray-200 dark:border-slate-700">
            <button
              type="button"
              onClick={() => setVehicleType('car')}
              className={`px-2 py-1 rounded-md text-[11px] font-bold flex items-center gap-1 transition-colors cursor-pointer ${
                vehicleType === 'car' ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm' : 'text-gray-500 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              <Car className="w-3.5 h-3.5" />
              <span>Car</span>
            </button>
            <button
              type="button"
              onClick={() => setVehicleType('bike')}
              className={`px-2 py-1 rounded-md text-[11px] font-bold flex items-center gap-1 transition-colors cursor-pointer ${
                vehicleType === 'bike' ? 'bg-white dark:bg-slate-700 text-emerald-600 dark:text-emerald-400 shadow-sm' : 'text-gray-500 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              <Bike className="w-3.5 h-3.5" />
              <span>Bike</span>
            </button>
            <button
              type="button"
              onClick={() => setVehicleType('emergency')}
              className={`px-2 py-1 rounded-md text-[11px] font-bold flex items-center gap-1 transition-colors cursor-pointer ${
                vehicleType === 'emergency' ? 'bg-white dark:bg-slate-700 text-red-600 dark:text-red-400 shadow-sm' : 'text-gray-500 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              <ShieldAlert className="w-3.5 h-3.5" />
              <span>Emergency</span>
            </button>
          </div>
        </div>
      </div>

      {/* Location Permission Status Banners */}
      {locationStatus === 'denied' && (
        <div className="p-3.5 bg-rose-50 dark:bg-rose-950/40 border border-rose-300 dark:border-rose-800 rounded-xl text-xs text-rose-900 dark:text-rose-200 flex items-start gap-3 shadow-sm">
          <AlertTriangle className="w-5 h-5 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
          <div className="flex-1">
            <div className="font-bold text-sm">GPS Location Access Required for Live Tracking</div>
            <p className="mt-1 text-slate-600 dark:text-slate-300 leading-relaxed">
              Location tracking permission is currently denied or blocked in your browser. Live GPS navigation and telemetry require location permissions. You can enable it in your browser address bar (lock icon) or enter manual source and destination locations.
            </p>
            <div className="mt-2.5 flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  if (navigator.geolocation) {
                    navigator.geolocation.getCurrentPosition(
                      () => window.location.reload(),
                      (err) => console.warn(err),
                      { enableHighAccuracy: true, timeout: 5000 }
                    );
                  }
                }}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white font-bold rounded-lg text-xs transition-colors cursor-pointer"
              >
                <LocateFixed className="w-3.5 h-3.5" />
                Retry GPS Permission
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Active Navigation Live Corridor Status Banner */}
      {isNavigating && selectedRoute && (
        <div className="p-3.5 bg-gradient-to-r from-blue-900 via-indigo-900 to-slate-900 text-white rounded-2xl shadow-xl border border-blue-500/40 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-blue-500/20 border border-blue-400 flex items-center justify-center text-blue-300">
              <Radio className="w-4 h-4 animate-pulse" />
            </div>
            <div>
              <div className="font-bold text-sm flex items-center gap-2">
                <span>Live Navigation: {selectedRoute.label || 'Active Route'}</span>
                <span className="text-[10px] bg-emerald-500 text-slate-950 font-black px-2 py-0.5 rounded-full uppercase">
                  Active GPS
                </span>
                {selectedRoute.trafficStatus && (
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ${
                    selectedRoute.trafficStatus === 'HEAVY' ? 'bg-red-500/80 text-white' : (selectedRoute.trafficStatus === 'MODERATE' ? 'bg-amber-500/80 text-slate-950' : 'bg-blue-500/80 text-white')
                  }`}>
                    {selectedRoute.trafficStatus} Traffic
                  </span>
                )}
              </div>
              <div className="text-slate-300 text-[11px] flex items-center gap-2 mt-0.5 flex-wrap">
                <span>Dist: <strong>{(navigationStats.distanceRemainingMeters / 1000).toFixed(1)} km</strong></span>
                <span>&bull;</span>
                <span>ETA: <strong>~{navigationStats.etaMinutes} mins</strong></span>
                <span>&bull;</span>
                <span>Speed: <strong>{Math.round(userLoc.speed || 0)} km/h</strong></span>
                {isSocketConnected && (
                  <>
                    <span>&bull;</span>
                    <span className="text-emerald-400 flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> WebSocket Live {latencyMs ? `(${latencyMs}ms)` : ''}
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {navigationStats.nearestBlackspot && (
              <div className="px-2.5 py-1.5 rounded-lg bg-red-950/70 border border-red-500/50 text-[11px] text-red-200 flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0" />
                <span>
                  Hazard: <strong>{navigationStats.nearestBlackspot.name}</strong> ({navigationStats.nearestBlackspotDistanceM}m)
                </span>
              </div>
            )}
            <button
              type="button"
              onClick={handleStopNavigation}
              className="px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white font-bold rounded-lg transition-colors flex items-center gap-1.5 cursor-pointer shadow-sm text-xs"
            >
              <Square className="w-3.5 h-3.5" /> Stop Navigation
            </button>
          </div>
        </div>
      )}

      {/* Manual Selection Active Mode Banner */}
      {pickingMode && (
        <div className="flex items-center justify-between p-3.5 bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800 rounded-xl text-xs text-blue-900 dark:text-blue-200 shadow-sm animate-pulse">
          <div className="flex items-center gap-2">
            <Crosshair className="w-4 h-4 text-blue-600 dark:text-blue-400 shrink-0" />
            <span className="font-semibold">
              {pickingMode === 'source'
                ? 'Click anywhere on the map to set Source (Starting Location)'
                : pickingMode === 'destination'
                ? 'Click anywhere on the map to set Destination'
                : `Click anywhere on the map to set Stop #${(pickingMode?.index ?? 0) + 1}`}
            </span>
          </div>
          <button
            type="button"
            onClick={() => setPickingMode(null)}
            className="px-2.5 py-1 text-[11px] font-bold bg-white dark:bg-slate-800 border border-blue-300 dark:border-blue-700 rounded-lg hover:bg-blue-100 transition-colors cursor-pointer"
          >
            Cancel Selection
          </button>
        </div>
      )}

      {/* Clicked Map Location Prompt */}
      {clickedPoint && !pickingMode && (
        <div className="flex flex-wrap items-center justify-between gap-2 p-3 bg-slate-900 text-white dark:bg-slate-800 rounded-xl shadow-lg border border-slate-700 text-xs">
          <div className="flex items-center gap-2">
            <MapPin className="w-4 h-4 text-blue-400 shrink-0" />
            <span>
              Selected point: <strong className="text-white">{clickedPoint.label}</strong>
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => handleSetFromClicked('source')}
              className="px-2.5 py-1 bg-emerald-600 hover:bg-emerald-700 font-bold rounded-lg transition-colors cursor-pointer"
            >
              Set as Source
            </button>
            <button
              type="button"
              onClick={() => handleSetFromClicked('stop')}
              className="px-2.5 py-1 bg-amber-600 hover:bg-amber-700 font-bold rounded-lg transition-colors cursor-pointer"
            >
              Add as Stop
            </button>
            <button
              type="button"
              onClick={() => handleSetFromClicked('destination')}
              className="px-2.5 py-1 bg-indigo-600 hover:bg-indigo-700 font-bold rounded-lg transition-colors cursor-pointer"
            >
              Set as Destination
            </button>
            <button
              type="button"
              onClick={() => setClickedPoint(null)}
              className="p-1 text-gray-400 hover:text-white transition-colors cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Main Container */}
      <div className="flex flex-col lg:flex-row gap-5 items-stretch">

        {/* Left Column: Multi-Stop Route Form & Alternatives */}
        <div className="w-full lg:w-[380px] xl:w-[420px] shrink-0 flex flex-col gap-4 lg:overflow-y-auto lg:max-h-[calc(100vh-140px)] pr-0 lg:pr-1 order-last lg:order-first">

          {/* Route Planner Form Card */}
          <div className="bg-white dark:bg-slate-800 p-4 sm:p-5 rounded-2xl shadow-sm border border-gray-100 dark:border-slate-700 space-y-3.5">
            <div className="flex items-center justify-between border-b border-gray-100 dark:border-slate-700 pb-2">
              <h2 className="text-sm font-bold text-navy-950 dark:text-white uppercase flex items-center gap-1.5">
                <MapPin className="w-4 h-4 text-blue-600" /> Route Planner
              </h2>
              {waypoints.length > 0 && (
                <span className="text-[10px] font-bold text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 px-2 py-0.5 rounded-full border border-amber-200 dark:border-amber-900">
                  {waypoints.length} stop{waypoints.length > 1 ? 's' : ''}
                </span>
              )}
            </div>

            <div className="space-y-3">
              {/* 1. Source (Interactive: Supports Live GPS, Manual Typing, Autocomplete & Pick on Map) */}
              <div className="relative">
                <div className="flex items-center justify-between mb-1">
                  <label className="flex items-center gap-1.5 text-[10px] font-bold text-gray-400 dark:text-slate-500 uppercase">
                    <LocateFixed className={`w-3.5 h-3.5 ${customSourceCoords ? 'text-blue-500' : (isLiveFix ? 'text-emerald-500' : 'text-amber-500')}`} />
                    <span>Source Location</span>
                  </label>
                  {customSourceCoords ? (
                    <button
                      type="button"
                      onClick={handleResetGpsSource}
                      className="inline-flex items-center gap-1 text-[10px] text-emerald-600 dark:text-emerald-400 hover:underline font-bold cursor-pointer"
                    >
                      <LocateFixed className="w-3 h-3" />
                      <span>Use Current Location</span>
                    </button>
                  ) : (
                    <span className="text-[10px] text-emerald-600 dark:text-emerald-400 font-bold flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                      Current Location (GPS)
                    </span>
                  )}
                </div>

                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <input
                      id="source-location-input"
                      type="text"
                      value={sourceInputText}
                      onChange={(e) => handleSourceInputChange(e.target.value)}
                      onFocus={() => {
                        if (sourceSuggestions.length > 0) setShowSourceSuggestions(true);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          setShowSourceSuggestions(false);
                          handleFindRoute();
                        }
                      }}
                      className={`block w-full px-3 py-2 text-xs rounded-lg border text-slate-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-blue-500 min-h-[36px] ${
                        !customSourceCoords
                          ? 'border-emerald-300 dark:border-emerald-800 bg-emerald-50/20 dark:bg-emerald-950/20 font-medium'
                          : 'border-gray-300 dark:border-slate-600 bg-white dark:bg-slate-900'
                      }`}
                      placeholder="Type source address or use current GPS..."
                    />
                    {isSearchingSource && (
                      <div className="absolute right-2.5 top-2.5">
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" />
                      </div>
                    )}

                    {/* Autocomplete Suggestions Dropdown for Source */}
                    {showSourceSuggestions && sourceSuggestions.length > 0 && (
                      <div className="absolute left-0 right-0 top-full mt-1 bg-white dark:bg-slate-900 rounded-xl shadow-xl border border-gray-200 dark:border-slate-700 z-50 max-h-48 overflow-y-auto">
                        {sourceSuggestions.map((sug, sIdx) => (
                          <div
                            key={sIdx}
                            onMouseDown={() => handleSelectSourceSuggestion(sug)}
                            className="px-3 py-2 hover:bg-blue-50 dark:hover:bg-slate-800 cursor-pointer text-xs border-b border-gray-100 dark:border-slate-800 last:border-none"
                          >
                            <div className="font-bold text-slate-900 dark:text-white flex items-center gap-1.5">
                              <MapPin className="w-3 h-3 text-blue-500 shrink-0" />
                              <span>{sug.shortName}</span>
                            </div>
                            <div className="text-[10px] text-slate-400 truncate mt-0.5">{sug.displayName}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => setPickingMode(pickingMode === 'source' ? null : 'source')}
                    className={`shrink-0 px-2.5 py-1 rounded-lg border text-xs font-semibold flex items-center gap-1 transition-colors cursor-pointer min-h-[36px] ${
                      pickingMode === 'source'
                        ? 'bg-emerald-600 text-white border-emerald-600 shadow-sm'
                        : 'bg-white dark:bg-slate-800 text-gray-700 dark:text-slate-200 border-gray-300 dark:border-slate-600 hover:bg-gray-50'
                    }`}
                    title="Click on map to select starting point"
                  >
                    <Crosshair className="w-3.5 h-3.5 text-emerald-500" />
                    <span className="hidden sm:inline">Pick</span>
                  </button>
                </div>
              </div>

              {/* 2. Destination */}
              <div className="relative">
                <label className="block text-[10px] font-bold text-gray-400 dark:text-slate-500 uppercase mb-1">
                  {t('user.navigation.destinationLocation')}
                </label>
                <div className="flex gap-2">
                  <div className="relative flex-1 rounded-md shadow-sm">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                      <Navigation className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400" />
                    </div>
                    <input
                      id="destination-location-input"
                      type="text"
                      value={destinationQuery}
                      onChange={(e) => handleDestinationInputChange(e.target.value)}
                      onFocus={() => {
                        if (destinationSuggestions.length > 0) setShowDestSuggestions(true);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          setShowDestSuggestions(false);
                          handleFindRoute();
                        }
                      }}
                      className="block w-full pl-8 pr-3 py-2 text-xs rounded-lg border border-gray-300 dark:border-slate-600 bg-gray-50 dark:bg-slate-900 text-slate-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-blue-500 min-h-[36px]"
                      placeholder="Enter destination or pick on map..."
                    />
                    {isSearchingDest && (
                      <div className="absolute right-2.5 top-2.5">
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" />
                      </div>
                    )}

                    {/* Autocomplete Suggestions Dropdown for Destination */}
                    {showDestSuggestions && destinationSuggestions.length > 0 && (
                      <div className="absolute left-0 right-0 top-full mt-1 bg-white dark:bg-slate-900 rounded-xl shadow-xl border border-gray-200 dark:border-slate-700 z-50 max-h-48 overflow-y-auto">
                        {destinationSuggestions.map((sug, dIdx) => (
                          <div
                            key={dIdx}
                            onMouseDown={() => handleSelectDestSuggestion(sug)}
                            className="px-3 py-2 hover:bg-blue-50 dark:hover:bg-slate-800 cursor-pointer text-xs border-b border-gray-100 dark:border-slate-800 last:border-none"
                          >
                            <div className="font-bold text-slate-900 dark:text-white flex items-center gap-1.5">
                              <MapPin className="w-3 h-3 text-indigo-500 shrink-0" />
                              <span>{sug.shortName}</span>
                            </div>
                            <div className="text-[10px] text-slate-400 truncate mt-0.5">{sug.displayName}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  
                  <button
                    type="button"
                    onClick={() => setPickingMode(pickingMode === 'destination' ? null : 'destination')}
                    className={`shrink-0 px-2.5 py-1 rounded-lg border text-xs font-semibold flex items-center gap-1 transition-colors cursor-pointer min-h-[36px] ${
                      pickingMode === 'destination'
                        ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm'
                        : 'bg-white dark:bg-slate-800 text-gray-700 dark:text-slate-200 border-gray-300 dark:border-slate-600 hover:bg-gray-50'
                    }`}
                    title="Click on map to select destination"
                  >
                    <Crosshair className="w-3.5 h-3.5 text-indigo-500" />
                    <span className="hidden sm:inline">Pick</span>
                  </button>
                </div>
              </div>

              {/* 3. + Add Stop Option */}
              <div className="pt-0.5">
                <button
                  type="button"
                  onClick={handleAddStop}
                  disabled={waypoints.length >= 5}
                  className="inline-flex items-center gap-1.5 text-xs font-bold text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 transition-colors cursor-pointer disabled:opacity-40 py-1 px-1 rounded"
                >
                  <Plus className="w-4 h-4" />
                  <span>+ Add Stop</span>
                </button>
              </div>

              {/* 4. Intermediate Stops */}
              {waypoints.length > 0 && (
                <div className="space-y-2 pt-1 border-t border-dashed border-gray-200 dark:border-slate-700">
                  {waypoints.map((wp, idx) => {
                    const stopNumber = idx + 1;
                    const isPickingThis = pickingMode && typeof pickingMode === 'object' && pickingMode.type === 'stop' && pickingMode.id === wp.id;

                    return (
                      <div key={wp.id} className="p-2.5 rounded-xl bg-amber-50/60 dark:bg-amber-950/25 border border-amber-200 dark:border-amber-900/50 space-y-1.5 transition-all">
                        <div className="flex items-center justify-between text-[10px] font-bold text-amber-800 dark:text-amber-400 uppercase">
                          <div className="flex items-center gap-1.5">
                            <span className="w-4 h-4 rounded-full bg-amber-500 text-white flex items-center justify-center text-[10px] font-black">
                              {stopNumber}
                            </span>
                            <span>Stop {stopNumber}</span>
                          </div>
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              disabled={idx === 0}
                              onClick={() => handleMoveStop(idx, 'up')}
                              className="p-1 rounded text-slate-500 hover:text-slate-900 dark:hover:text-white disabled:opacity-20 cursor-pointer"
                              title="Move stop earlier"
                            >
                              <ChevronUp className="w-3.5 h-3.5" />
                            </button>
                            <button
                              type="button"
                              disabled={idx === waypoints.length - 1}
                              onClick={() => handleMoveStop(idx, 'down')}
                              className="p-1 rounded text-slate-500 hover:text-slate-900 dark:hover:text-white disabled:opacity-20 cursor-pointer"
                              title="Move stop later"
                            >
                              <ChevronDown className="w-3.5 h-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={() => handleRemoveStop(wp.id)}
                              className="p-1 rounded text-red-500 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-950/50 transition-colors cursor-pointer ml-1"
                              title="Remove stop"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>

                        <div className="flex gap-2">
                          <input
                            type="text"
                            value={wp.query}
                            onChange={(e) => handleStopQueryChange(wp.id, e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleFindRoute()}
                            className="flex-1 px-3 py-1.5 text-xs rounded-lg border border-amber-300 dark:border-amber-800 bg-white dark:bg-slate-900 text-slate-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-amber-500"
                            placeholder={`Enter Stop ${stopNumber} or pick on map...`}
                          />
                          <button
                            type="button"
                            onClick={() => setPickingMode(isPickingThis ? null : { type: 'stop', id: wp.id, index: idx })}
                            className={`shrink-0 px-2.5 py-1 rounded-lg border text-xs font-semibold flex items-center gap-1 transition-colors cursor-pointer ${
                              isPickingThis
                                ? 'bg-amber-600 text-white border-amber-600 shadow-sm'
                                : 'bg-white dark:bg-slate-800 text-amber-900 dark:text-amber-200 border-amber-300 dark:border-amber-700 hover:bg-amber-100/50'
                            }`}
                            title={`Click on map to pick Stop #${stopNumber}`}
                          >
                            <Crosshair className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
                            <span className="hidden sm:inline">Pick</span>
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Quick Find Route action button */}
            <button
              id="calculate-routes-btn"
              type="button"
              onClick={handleFindRoute}
              disabled={isSearchingRoute || (!destinationQuery.trim() && !destinationCoords)}
              className="w-full mt-2 py-2.5 px-4 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold rounded-xl transition-all shadow-md flex items-center justify-center gap-2 text-xs cursor-pointer min-h-[42px]"
            >
              {isSearchingRoute ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Calculating Road Routes & ML Risk Analysis...</span>
                </>
              ) : (
                <>
                  <RouteIcon className="w-4 h-4" />
                  <span>Calculate Available Routes</span>
                </>
              )}
            </button>
          </div>

          {/* ROUTE 1 / ROUTE 2 Selection Section with ML Risk Intelligence */}
          {availableRoutes && availableRoutes.length > 0 && (
            <div className="bg-white dark:bg-slate-800 p-4 sm:p-5 rounded-2xl shadow-sm border border-gray-100 dark:border-slate-700 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold text-gray-400 dark:text-slate-500 uppercase tracking-wider">
                  Road Options ({availableRoutes.length})
                </span>
                <span className="text-[10px] text-blue-600 dark:text-blue-400 font-bold">
                  Tap to Select
                </span>
              </div>

              <div className="space-y-2.5">
                {availableRoutes.slice(0, 3).map((routeOption, idx) => {
                  const isSelected = selectedRoute?.id === routeOption.id;
                  const routeNum = idx + 1;
                  const isRec = routeOption.isRecommended;

                  return (
                    <div
                      key={routeOption.id}
                      onClick={() => handleSelectRoute(routeOption.id)}
                      className={`p-3.5 rounded-xl border-2 transition-all cursor-pointer relative flex flex-col justify-between ${
                        isSelected
                          ? 'border-blue-600 bg-blue-50/70 dark:bg-blue-950/50 shadow-md ring-2 ring-blue-500/20'
                          : isRec
                          ? 'border-emerald-300 dark:border-emerald-800 bg-emerald-50/20 dark:bg-emerald-950/20 hover:border-emerald-500'
                          : 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 hover:border-blue-400'
                      }`}
                    >
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-1.5">
                            <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-black uppercase ${
                              isSelected 
                                ? 'bg-blue-600 text-white' 
                                : isRec
                                ? 'bg-emerald-600 text-white'
                                : 'bg-slate-700 text-white'
                            }`}>
                              <span>Route {routeNum}</span>
                            </span>

                            {isRec && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-black uppercase bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800">
                                <Sparkles className="w-2.5 h-2.5 text-emerald-600" />
                                Practical Choice
                              </span>
                            )}
                          </div>

                          {/* ML Risk Status Indicator */}
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider flex items-center gap-1 bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300 border border-blue-200 dark:border-blue-900">
                            <span className="w-1.5 h-1.5 rounded-full bg-blue-500"></span>
                            {routeOption.category || (routeOption.isAlternative ? 'Alternative Option' : 'Primary Safe Route')}
                          </span>
                        </div>

                        <div className="grid grid-cols-3 gap-2 text-xs mb-2">
                          <div>
                            <span className="text-[10px] text-gray-400 block font-medium">Distance</span>
                            <span className="font-extrabold text-navy-950 dark:text-white text-sm">{routeOption.distance}</span>
                          </div>
                          <div>
                            <span className="text-[10px] text-gray-400 block font-medium">Est. Duration</span>
                            <span className="font-extrabold text-navy-950 dark:text-white text-sm">
                              {routeOption.time}
                            </span>
                          </div>
                          <div>
                            <span className="text-[10px] text-gray-400 block font-medium">Safety Score</span>
                            <span className="font-extrabold text-emerald-600 dark:text-emerald-400 text-sm">
                              {routeOption.safetyScore ?? 85}/100
                            </span>
                          </div>
                        </div>

                        <div className="flex items-center justify-between text-[11px] mb-1 px-2 py-1 rounded bg-slate-100 dark:bg-slate-800/80">
                          <span className="font-bold text-slate-600 dark:text-slate-300">Corridor Risk:</span>
                          <span className="font-semibold text-slate-700 dark:text-slate-200 text-xs">
                            {routeOption.blackspotsCount || 0} Verified • {routeOption.mlHotspotsCount || 0} ML Predicted
                          </span>
                        </div>
                      </div>

                      <div className="mt-1 pt-2 border-t border-gray-200/60 dark:border-slate-700/60 flex items-center justify-between text-[10px]">
                        <RiskBadge level={routeOption.riskLevel} />
                        <div className="flex items-center gap-1.5 text-gray-500 font-bold">
                          <span>
                            {routeOption.blackspotsCount || 0} Blackspot{(routeOption.blackspotsCount || 0) === 1 ? '' : 's'}
                            {routeOption.mlHotspotsCount > 0 ? ` • ${routeOption.mlHotspotsCount} ML Hotspot${routeOption.mlHotspotsCount === 1 ? '' : 's'}` : ''}
                          </span>
                          {(routeOption.totalHazards > 0 || routeOption.hazardsEnRoute?.length > 0) && (
                            <span className="text-amber-600 dark:text-amber-400">
                              • {routeOption.totalHazards || routeOption.hazardsEnRoute?.length} Hazard{(routeOption.totalHazards || routeOption.hazardsEnRoute?.length) === 1 ? '' : 's'}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Active Selected Route Safety Summary Card */}
          <div className="bg-white dark:bg-slate-800 p-4 sm:p-5 rounded-2xl shadow-sm border border-gray-100 dark:border-slate-700 space-y-4">
            <div className="flex items-center justify-between border-b border-gray-100 dark:border-slate-700 pb-2">
              <h3 className="text-sm font-bold text-navy-950 dark:text-white uppercase flex items-center gap-1.5">
                <ShieldAlert className="w-4 h-4 text-emerald-600" />
                {selectedRoute ? `Route Safety: ${selectedRoute.label || 'Active Route'}` : 'Route Safety Summary'}
              </h3>
              {selectedRoute && (
                <button
                  type="button"
                  onClick={() => setFilterRouteHotspotsOnly(!filterRouteHotspotsOnly)}
                  className={`text-[10px] font-bold px-2 py-0.5 rounded-full border transition-colors cursor-pointer ${
                    filterRouteHotspotsOnly
                      ? 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/60 dark:text-blue-300 dark:border-blue-800'
                      : 'bg-gray-100 text-gray-600 border-gray-200 dark:bg-slate-700 dark:text-slate-300'
                  }`}
                  title="Toggle between showing only corridor blackspots vs all city blackspots"
                >
                  {filterRouteHotspotsOnly ? 'Corridor Only' : 'Show All'}
                </button>
              )}
            </div>

            {selectedRoute ? (
              <>
                <div className="flex items-center justify-between p-3 rounded-xl bg-gradient-to-r from-emerald-500/10 via-blue-500/10 to-indigo-500/10 border border-emerald-500/20">
                  <div>
                    <span className="text-[10px] uppercase font-bold text-slate-500 dark:text-slate-400 block">AI Safety Score</span>
                    <div className="flex items-baseline gap-1.5 mt-0.5">
                      <span className="text-2xl font-black text-emerald-600 dark:text-emerald-400">
                        {selectedRoute.safetyScore ?? 85}
                      </span>
                      <span className="text-xs text-slate-400 font-bold">/ 100</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <span className="text-[10px] uppercase font-bold text-slate-500 dark:text-slate-400 block">Classification</span>
                    <span className="inline-block mt-1 px-2.5 py-0.5 rounded-full text-xs font-black uppercase bg-emerald-600 text-white shadow-xs">
                      {selectedRoute.category || 'Safest Corridor'}
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <span className="text-[10px] text-gray-400 dark:text-slate-500 font-semibold block uppercase">{t('user.navigation.estDistance')}</span>
                    <span className="text-xl font-black text-navy-950 dark:text-white">{selectedRoute.distance}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-gray-400 dark:text-slate-500 font-semibold block uppercase">Est. Duration</span>
                    <span className="text-xl font-black text-navy-950 dark:text-white">{selectedRoute.time}</span>
                  </div>
                </div>

                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-[10px] text-gray-400 dark:text-slate-500 font-semibold block uppercase mb-1">{t('user.navigation.accidentRiskLevel')}</span>
                    <RiskBadge level={selectedRoute.riskLevel} />
                  </div>
                  <div className="text-right text-xs">
                    <span className="text-[10px] text-gray-400 dark:text-slate-500 font-semibold block uppercase mb-0.5">Risk Score</span>
                    <span className="font-mono font-bold text-slate-800 dark:text-slate-200">
                      {(selectedRoute.riskScore || 0).toFixed(2)} (0.00 – 1.00)
                    </span>
                  </div>
                </div>

                {/* Major Route Risk Factors */}
                {selectedRoute.contributingFactors && selectedRoute.contributingFactors.length > 0 && (
                  <div className="border-t border-gray-100 dark:border-slate-700 pt-3">
                    <span className="text-[10px] text-gray-400 dark:text-slate-500 font-bold block uppercase mb-1.5">
                      Major Risk Factors en route
                    </span>
                    <div className="space-y-1.5 max-h-36 overflow-y-auto pr-1">
                      {selectedRoute.contributingFactors.map((factor, fi) => (
                        <div key={fi} className="text-xs text-slate-700 dark:text-slate-300 flex items-start gap-1.5 bg-slate-50 dark:bg-slate-900/60 p-2 rounded-lg border border-slate-200/60 dark:border-slate-700/60">
                          <AlertTriangle className="w-3.5 h-3.5 text-amber-500 mt-0.5 shrink-0" />
                          <span className="text-[11px] font-medium">{factor}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* En-route Blackspots & ML Predicted Hotspots strictly for Selected Route */}
                <div className="border-t border-gray-100 dark:border-slate-700 pt-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] text-gray-400 dark:text-slate-500 font-bold uppercase">
                      Risk Hotspots ({selectedRoute.totalHotspots || (selectedRoute.blackspotsCount + selectedRoute.mlHotspotsCount)})
                    </span>
                    <span className="text-[10px] text-indigo-600 dark:text-indigo-400 font-bold">
                      {selectedRoute.blackspotsCount || 0} Verified • {selectedRoute.mlHotspotsCount || 0} ML Predicted
                    </span>
                  </div>

                  {((selectedRoute.hotspotsEnRoute && selectedRoute.hotspotsEnRoute.length > 0) || (selectedRoute.predictedHotspots && selectedRoute.predictedHotspots.length > 0)) ? (
                    <div className="space-y-2 max-h-52 overflow-y-auto pr-1">
                      {/* Verified Historical Blackspots */}
                      {(selectedRoute.hotspotsEnRoute || []).map((spot, i) => (
                        <div key={`verified-${i}`} className="flex items-start space-x-2 bg-red-50 dark:bg-red-950/40 p-2.5 rounded-lg border border-red-100 dark:border-red-900/40">
                          <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0" />
                          <div className="flex-1">
                            <div className="flex items-center justify-between">
                              <span className="text-xs font-bold text-red-900 dark:text-red-200">{spot.name}</span>
                              <span className="text-[9px] font-bold px-1.5 py-0.2 rounded bg-red-200/60 dark:bg-red-900 text-red-800 dark:text-red-200">
                                Verified Blackspot
                              </span>
                            </div>
                            <div className="text-[10px] text-red-700 dark:text-red-300 mt-0.5">{spot.detail} ({spot.risk} risk)</div>
                          </div>
                        </div>
                      ))}

                      {/* ML-Predicted Elevated Risk Areas */}
                      {(selectedRoute.predictedHotspots || []).map((spot, i) => (
                        <div key={`ml-${i}`} className="flex items-start space-x-2 bg-purple-50 dark:bg-purple-950/40 p-2.5 rounded-lg border border-purple-200 dark:border-purple-900/50">
                          <Sparkles className="w-4 h-4 text-purple-600 dark:text-purple-400 mt-0.5 flex-shrink-0" />
                          <div className="flex-1">
                            <div className="flex items-center justify-between">
                              <span className="text-xs font-bold text-purple-950 dark:text-purple-200">{spot.name}</span>
                              <span className="text-[9px] font-bold px-1.5 py-0.2 rounded bg-purple-200/70 dark:bg-purple-900 text-purple-800 dark:text-purple-200">
                                ML Predicted ({Math.round((spot.confidence || 0.84) * 100)}%)
                              </span>
                            </div>
                            <div className="text-[10px] text-purple-700 dark:text-purple-300 mt-0.5">
                              Risk: {spot.riskLevel} ({(spot.riskScore * 100).toFixed(0)}%) • Corridor risk estimate
                            </div>
                            {spot.uncertaintyNote && (
                              <div className="text-[9px] text-amber-700 dark:text-amber-400 italic mt-1 leading-snug">
                                ⚠️ {spot.uncertaintyNote}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-xs text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950/40 p-3 rounded-lg font-semibold text-center border border-blue-200 dark:border-blue-900">
                      Zero critical clusters en-route. Clean safe path.
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="text-xs text-gray-500 dark:text-slate-400 bg-gray-50 dark:bg-slate-900 p-6 rounded-xl text-center border border-dashed border-gray-200 dark:border-slate-700">
                Enter source, destination, and any stops, then calculate to view practical route options.
              </div>
            )}

            {/* Start Trip, Voice & Fleet Controls */}
            <div className="grid grid-cols-4 gap-1.5 pt-2 border-t border-gray-100 dark:border-slate-700">
              <button
                type="button"
                onClick={handleVoiceToggle}
                className={`py-2 px-2 rounded-lg border text-center flex items-center justify-center font-bold text-xs cursor-pointer transition min-h-[42px] ${
                  voiceOn
                    ? 'bg-blue-100 border-blue-300 text-blue-800 hover:bg-blue-200'
                    : 'bg-slate-50 dark:bg-slate-900 border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
                }`}
                title={voiceOn ? t('user.navigation.muteVoice') : t('user.navigation.unmuteVoice')}
              >
                {voiceOn ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
                <span className="ml-1 hidden sm:inline">{voiceOn ? t('user.navigation.on') : t('user.navigation.off')}</span>
              </button>
              <button
                type="button"
                onClick={() => setShowFleet(!showFleet)}
                className={`py-2 px-2 rounded-lg border text-center flex items-center justify-center font-bold text-xs cursor-pointer transition min-h-[42px] ${
                  showFleet
                    ? 'bg-amber-50 dark:bg-amber-950/40 border-amber-300 dark:border-amber-800 text-amber-700 dark:text-amber-300'
                    : 'bg-slate-50 dark:bg-slate-900 border-gray-200 dark:border-slate-700 text-gray-400'
                }`}
                title="Toggle Fleet Vehicles"
              >
                <Radio className={`w-3.5 h-3.5 mr-1 ${isSocketConnected ? 'text-emerald-500 animate-pulse' : 'text-gray-400'}`} />
                <span className="text-[11px]">Fleet ({activeFleet?.length || 0})</span>
              </button>
              {isNavigating ? (
                <button
                  id="stop-navigation-btn"
                  type="button"
                  onClick={handleStopNavigation}
                  className="col-span-2 py-2 px-4 bg-rose-600 hover:bg-rose-700 text-white font-bold rounded-lg transition-colors border border-rose-500 flex items-center justify-center gap-1.5 shadow-sm text-xs cursor-pointer min-h-[42px]"
                >
                  <Square className="w-4 h-4" /> Stop Navigation
                </button>
              ) : (
                <button
                  id="start-navigation-btn"
                  type="button"
                  onClick={handleStartTrip}
                  disabled={!selectedRoute}
                  className="col-span-2 py-2 px-4 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold rounded-lg transition-colors border border-blue-500 flex items-center justify-center gap-1.5 shadow-sm text-xs cursor-pointer min-h-[42px]"
                >
                  <Play className="w-4 h-4" /> Start Navigation
                </button>
              )}
            </div>

            {/* Quick Link to Detailed Alerts Hub */}
            {selectedRoute && (
              <div className="pt-1 text-center">
                <button
                  type="button"
                  onClick={() => {
                    const alternate = availableRoutes.find((r) => r.id !== selectedRoute.id) || null;
                    navigate('/user/alerts', {
                      state: {
                        liveRoute: selectedRoute,
                        alternateRoute: alternate,
                        destinationLabel: destinationCoords?.displayName || destinationQuery,
                        destinationCoords,
                        waypoints: waypoints.map((w, idx) => ({
                          id: w.id,
                          lat: w.coords?.lat,
                          lng: w.coords?.lng,
                          label: w.coords?.displayName || w.query || `Stop ${idx + 1}`,
                          stopNumber: idx + 1,
                        })).filter(w => w.lat && w.lng),
                        sourceCoords: customSourceCoords || { lat: userLoc.latitude, lng: userLoc.longitude },
                        sourceLabel,
                        voiceOn,
                        alertLang,
                        vehicleType,
                      },
                    });
                  }}
                  className="text-[11px] font-bold text-blue-600 dark:text-blue-400 hover:underline flex items-center justify-center gap-1 w-full"
                >
                  <span>Open Full Alerts Screen in Alert Hub</span>
                  <Navigation className="w-3 h-3" />
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Full-Height Leaflet Map (~70% Map space) */}
        <div className="flex-1 min-w-0 w-full h-[48vh] min-h-[380px] sm:h-[65vh] lg:h-[calc(100vh-140px)] lg:min-h-[480px] flex flex-col relative rounded-2xl overflow-hidden border border-gray-200/80 dark:border-slate-700 shadow-md order-first lg:order-last">
          <MapView
            hotspots={activeMapHotspots}
            hazards={hazards}
            showHazards={true}
            routes={availableRoutes}
            selectedRoute={selectedRoute}
            onSelectRoute={(r) => handleSelectRoute(r.id)}
            userLocation={customSourceCoords ? null : userLoc}
            vehicleType={vehicleType}
            enableSmoothLerp={true}
            followUser={isNavigating && followCamera}
            showBreadcrumbs={showBreadcrumbs}
            fleet={activeFleet}
            showFleet={showFleet}
            sourceLocation={effectiveSource ? { lat: effectiveSource.lat, lng: effectiveSource.lng, label: sourceLabel } : null}
            waypoints={mapWaypoints}
            destinationLocation={destinationCoords ? { lat: destinationCoords.lat, lng: destinationCoords.lng, label: destinationQuery } : null}
            selectedPoint={clickedPoint}
            onMapClick={handleMapClick}
            routeHotspotsOnly={filterRouteHotspotsOnly && Boolean(selectedRoute)}
            onSelectAsSource={(spot) => {
              setCustomSourceCoords({ lat: spot.lat, lng: spot.lng, displayName: spot.name });
              setSourceLabel(spot.name);
              setSourceInputText(spot.name);
              setToastType('success');
              setToastMessage(`Source set to ${spot.name}.`);
            }}
            onSelectAsDestination={(spot) => {
              setDestinationCoords({ lat: spot.lat, lng: spot.lng, displayName: spot.name });
              setDestinationQuery(spot.name);
              setToastType('success');
              setToastMessage(`Destination set to ${spot.name}.`);
            }}
            showPins={true}
            showKde={true}
            showSpeedLimits={false}
            zoom={13}
          />

          {/* Floating 'Add a report' button matching Reference Image 4 */}
          <div className="absolute top-3 right-3 sm:top-4 sm:right-4 z-[400]">
            <button
              type="button"
              onClick={() => setShowReportModal(true)}
              className="px-3 py-2 bg-white/95 dark:bg-slate-900/95 backdrop-blur-md border border-amber-300 dark:border-amber-700/80 rounded-xl shadow-lg flex items-center gap-2 text-xs font-extrabold text-amber-700 dark:text-amber-300 hover:bg-amber-50 dark:hover:bg-slate-800 transition cursor-pointer"
              title="Report Road Hazard, Pothole or Construction"
            >
              <div className="w-5 h-5 rounded-full bg-amber-500 text-white flex items-center justify-center shadow-xs">
                <Plus className="w-3.5 h-3.5 stroke-[3]" />
              </div>
              <span className="hidden sm:inline">Add a report</span>
              <span className="sm:hidden">Report</span>
            </button>
          </div>

          {/* Floating Live Telemetry HUD Overlay in Map */}
          {isNavigating && (
            <div className="absolute bottom-3 left-3 right-3 sm:bottom-4 sm:left-4 sm:right-4 z-[450] flex justify-center pointer-events-none">
              <TelemetryHUD
                speed={userLoc.speed || 0}
                speedLimit={40}
                heading={userLoc.heading || 0}
                cardinal={userLoc.cardinal || 'NORTH'}
                accuracy={userLoc.accuracy || 8}
                latitude={userLoc.latitude}
                longitude={userLoc.longitude}
                isLiveTracking={true}
                heartbeatTick={heartbeatTick}
                vehicleType={vehicleType}
                onChangeVehicleType={setVehicleType}
                followUser={followCamera}
                onToggleFollowUser={() => setFollowCamera(!followCamera)}
                showBreadcrumbs={showBreadcrumbs}
                onToggleBreadcrumbs={() => setShowBreadcrumbs(!showBreadcrumbs)}
                className="w-full max-w-xl shadow-2xl"
              />
            </div>
          )}
        </div>

      </div>

      {/* Modern 'Add a report' Bottom Sheet / Modal (Reference Image 4) */}
      <ReportHazardModal
        isOpen={showReportModal}
        onClose={() => setShowReportModal(false)}
        userLocation={effectiveSource || { latitude: userLoc.latitude, longitude: userLoc.longitude }}
        onSubmit={handleReportHazard}
      />
    </div>
  );
}