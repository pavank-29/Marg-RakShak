/**
 * MargRakshak AI — Geodetic Distance, Bearing & Route Corridor Geometry Utilities.
 */

/**
 * Calculates the geodetic distance between two points on the Earth's surface
 * using the Haversine formula in kilometers.
 * 
 * @param {Object} loc1 - First location {latitude, longitude} or {lat, lng}
 * @param {Object} loc2 - Second location {latitude, longitude} or {lat, lng}
 * @returns {number} Distance in kilometers
 */
export function calculateDistance(loc1, loc2) {
  const lat1 = loc1.latitude !== undefined ? loc1.latitude : loc1.lat;
  const lon1 = loc1.longitude !== undefined ? loc1.longitude : loc1.lng;
  
  const lat2 = loc2.latitude !== undefined ? loc2.latitude : loc2.lat;
  const lon2 = loc2.longitude !== undefined ? loc2.longitude : loc2.lng;

  if (lat1 === undefined || lon1 === undefined || lat2 === undefined || lon2 === undefined) {
    return 0;
  }

  const R = 6371; // Radius of the earth in km
  const dLat = deg2rad(lat2 - lat1);
  const dLon = deg2rad(lon2 - lon1);
  
  const a = 
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(deg2rad(lat1)) * Math.cos(deg2rad(lat2)) * 
    Math.sin(dLon / 2) * Math.sin(dLon / 2); 
    
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)); 
  return R * c;
}

function deg2rad(deg) {
  return deg * (Math.PI / 180);
}

function rad2deg(rad) {
  return (rad * 180) / Math.PI;
}

/**
 * Calculates great-circle distance between two coordinates in meters
 * @param {number} lat1 
 * @param {number} lon1 
 * @param {number} lat2 
 * @param {number} lon2 
 * @returns {number} Distance in meters
 */
export function calculateDistanceMeters(lat1, lon1, lat2, lon2) {
  const R = 6371000; // Earth radius in meters
  const dLat = deg2rad(lat2 - lat1);
  const dLon = deg2rad(lon2 - lon1);
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(deg2rad(lat1)) * Math.cos(deg2rad(lat2)) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

/**
 * Calculates forward azimuth (bearing) from coordinate 1 to coordinate 2 in degrees [0, 360)
 * @param {number} lat1 
 * @param {number} lon1 
 * @param {number} lat2 
 * @param {number} lon2 
 * @returns {number} Bearing angle in degrees [0, 360)
 */
export function calculateBearing(lat1, lon1, lat2, lon2) {
  const phi1 = deg2rad(lat1);
  const phi2 = deg2rad(lat2);
  const deltaLambda = deg2rad(lon2 - lon1);

  const y = Math.sin(deltaLambda) * Math.cos(phi2);
  const x = Math.cos(phi1) * Math.sin(phi2) -
            Math.sin(phi1) * Math.cos(phi2) * Math.cos(deltaLambda);
  const theta = Math.atan2(y, x);
  return (rad2deg(theta) + 360) % 360;
}

/**
 * Converts degree angle to 16-point cardinal compass direction
 * @param {number} deg 
 * @returns {string} Cardinal direction (e.g. NORTH, NE, SW)
 */
export function degreeToCardinal(deg) {
  const directions = [
    "NORTH", "NNE", "NE", "ENE",
    "EAST", "ESE", "SE", "SSE",
    "SOUTH", "SSW", "SW", "WSW",
    "WEST", "WNW", "NW", "NNW"
  ];
  const normalized = ((deg % 360) + 360) % 360;
  const index = Math.round(normalized / 22.5) % 16;
  return directions[index];
}

/**
 * Linearly interpolates between two [lat, lng] coordinates
 * @param {Array<number>} coord1 [lat, lng]
 * @param {Array<number>} coord2 [lat, lng]
 * @param {number} t Progress from 0 to 1
 * @returns {Array<number>} [lat, lng]
 */
export function interpolateCoordinate(coord1, coord2, t) {
  const lat = coord1[0] + (coord2[0] - coord1[0]) * t;
  const lng = coord1[1] + (coord2[1] - coord1[1]) * t;
  return [lat, lng];
}

/**
 * Calculates the exact perpendicular distance from point P to segment [A, B] in meters.
 * Clamps projection scalar t to [0, 1] so points past endpoints measure to segment ends.
 */
export function pointToSegmentDistanceMeters(pLat, pLng, aLat, aLng, bLat, bLng) {
  const segLen = calculateDistanceMeters(aLat, aLng, bLat, bLng);
  if (segLen === 0) {
    return {
      distanceMeters: calculateDistanceMeters(pLat, pLng, aLat, aLng),
      t: 0,
      projLat: aLat,
      projLng: aLng,
      segLen: 0,
    };
  }

  const midLat = deg2rad((aLat + bLat + pLat) / 3.0);
  const cosLat = Math.cos(midLat);
  const dx = (bLng - aLng) * cosLat;
  const dy = (bLat - aLat);
  const px = (pLng - aLng) * cosLat;
  const py = (pLat - aLat);

  const denom = dx * dx + dy * dy;
  if (denom === 0) {
    return {
      distanceMeters: calculateDistanceMeters(pLat, pLng, aLat, aLng),
      t: 0,
      projLat: aLat,
      projLng: aLng,
      segLen,
    };
  }

  const t = Math.max(0, Math.min(1, (px * dx + py * dy) / denom));
  const projLat = aLat + t * (bLat - aLat);
  const projLng = aLng + t * (bLng - aLng);
  const distanceMeters = calculateDistanceMeters(pLat, pLng, projLat, projLng);

  return {
    distanceMeters,
    t,
    projLat,
    projLng,
    segLen,
  };
}

/**
 * Finds the minimum perpendicular distance and progress along a polyline for a coordinate point.
 */
export function getPointRouteCorridorInfo(pLat, pLng, path) {
  if (!path || path.length < 2) {
    return { minDistanceMeters: Infinity, segmentIndex: -1, distanceAlongRouteMeters: 0 };
  }

  let minDistanceMeters = Infinity;
  let bestSegIndex = 0;
  let bestT = 0;
  let cumulativeDistBeforeBest = 0;
  let currentAccumulated = 0;

  for (let i = 0; i < path.length - 1; i++) {
    const p1 = path[i];
    const p2 = path[i + 1];
    const { distanceMeters, t, segLen } = pointToSegmentDistanceMeters(
      pLat, pLng, p1[0], p1[1], p2[0], p2[1]
    );

    if (distanceMeters < minDistanceMeters) {
      minDistanceMeters = distanceMeters;
      bestSegIndex = i;
      bestT = t;
      cumulativeDistBeforeBest = currentAccumulated;
    }

    currentAccumulated += segLen;
  }

  const bestSegLen = calculateDistanceMeters(
    path[bestSegIndex][0], path[bestSegIndex][1],
    path[bestSegIndex + 1][0], path[bestSegIndex + 1][1]
  );
  const distanceAlongRouteMeters = cumulativeDistBeforeBest + (bestT * bestSegLen);

  return {
    minDistanceMeters,
    segmentIndex: bestSegIndex,
    distanceAlongRouteMeters,
  };
}

/**
 * Given a road route's [lat, lng] path and a list of hotspots, returns ONLY the
 * hotspots that fall within the road corridor threshold (default: 80m, configurable).
 * 
 * Features:
 * - Uses true perpendicular segment geometry projection (not coarse vertex-only distance).
 * - Excludes parallel and unrelated roads beyond the narrow corridor.
 * - Supports ahead-of-user filtering: when userLocation and onlyAhead=true are passed,
 *   hotspots already passed by the driver (behind current position) are excluded.
 * - Annotates each match with distanceToRouteMeters and distanceAlongRouteMeters.
 * - Sorts hotspots sequentially along the route direction.
 * 
 * @param {Array<Array<number>>} path - [[lat, lng], ...]
 * @param {Array<Object>} hotspots - List of hotspot records
 * @param {number|Object} [options=80] - Corridor threshold in meters OR options object
 * @returns {Array<Object>} Route-specific hotspots
 */
export function findHotspotsNearRoute(path, hotspots, options = 80) {
  if (!path || path.length < 2 || !hotspots || hotspots.length === 0) return [];

  let thresholdMeters = 80;
  let userLocation = null;
  let onlyAhead = false;

  if (typeof options === 'number') {
    thresholdMeters = options;
  } else if (typeof options === 'object' && options !== null) {
    thresholdMeters = options.thresholdMeters ?? 80;
    userLocation = options.userLocation ?? null;
    onlyAhead = Boolean(options.onlyAhead);
  }

  // Pre-filter bounding box with safety padding for O(N) spatial pruning
  let minLat = 90, maxLat = -90, minLng = 180, maxLng = -180;
  for (const pt of path) {
    if (pt[0] < minLat) minLat = pt[0];
    if (pt[0] > maxLat) maxLat = pt[0];
    if (pt[1] < minLng) minLng = pt[1];
    if (pt[1] > maxLng) maxLng = pt[1];
  }
  const padDeg = (thresholdMeters + 120) / 111000.0;
  minLat -= padDeg; maxLat += padDeg; minLng -= padDeg; maxLng += padDeg;

  // Determine user progress along route if ahead filtering requested
  let userProgressMeters = 0;
  if (onlyAhead && userLocation && !isNaN(userLocation.latitude) && !isNaN(userLocation.longitude)) {
    const userCorridor = getPointRouteCorridorInfo(userLocation.latitude, userLocation.longitude, path);
    userProgressMeters = userCorridor.distanceAlongRouteMeters;
  }

  const results = [];

  for (const spot of hotspots) {
    const spotLat = Number(spot.latitude ?? spot.lat);
    const spotLng = Number(spot.longitude ?? spot.lng);
    if (isNaN(spotLat) || isNaN(spotLng)) continue;

    // Fast bounding box reject
    if (spotLat < minLat || spotLat > maxLat || spotLng < minLng || spotLng > maxLng) {
      continue;
    }

    const corridorInfo = getPointRouteCorridorInfo(spotLat, spotLng, path);
    if (corridorInfo.minDistanceMeters <= thresholdMeters) {
      // Ahead-of-user check: allow 30m grace behind current GPS position
      if (onlyAhead && userLocation) {
        if (corridorInfo.distanceAlongRouteMeters < userProgressMeters - 30) {
          continue; // Passed already
        }
      }

      results.push({
        ...spot,
        lat: spotLat,
        lng: spotLng,
        latitude: spotLat,
        longitude: spotLng,
        distanceToRouteMeters: Math.round(corridorInfo.minDistanceMeters),
        distanceAlongRouteMeters: Math.round(corridorInfo.distanceAlongRouteMeters),
      });
    }
  }

  // Sort sequentially along the direction of travel
  return results.sort((a, b) => a.distanceAlongRouteMeters - b.distanceAlongRouteMeters);
}

/**
 * Filters road hazards (construction, potholes, closures) strictly within the route corridor.
 */
export function findHazardsNearRoute(path, hazards, thresholdMeters = 120) {
  if (!path || path.length < 2 || !hazards || hazards.length === 0) return [];

  return hazards
    .map((haz) => {
      const hLat = Number(haz.latitude ?? haz.lat);
      const hLng = Number(haz.longitude ?? haz.lng);
      if (isNaN(hLat) || isNaN(hLng)) return null;

      const corridor = getPointRouteCorridorInfo(hLat, hLng, path);
      if (corridor.minDistanceMeters <= thresholdMeters) {
        return {
          ...haz,
          lat: hLat,
          lng: hLng,
          latitude: hLat,
          longitude: hLng,
          distanceToRouteMeters: Math.round(corridor.minDistanceMeters),
          distanceAlongRouteMeters: Math.round(corridor.distanceAlongRouteMeters),
        };
      }
      return null;
    })
    .filter(Boolean)
    .sort((a, b) => a.distanceAlongRouteMeters - b.distanceAlongRouteMeters);
}
