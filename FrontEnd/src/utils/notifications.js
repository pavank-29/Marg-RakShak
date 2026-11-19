/**
 * Browser Push & System Notifications Utility for MargRakshak AI.
 * Handles permission requests, notification dispatch at 1000m, 500m, and 300m thresholds,
 * and deduplication to avoid repetitive alerts.
 */

// Deduplication cache of sent notification keys: `${spotName}_${threshold}`
const sentAlertKeys = new Set();

/**
 * Check if the browser supports native desktop/mobile push notifications
 */
export function isPushSupported() {
  return typeof window !== 'undefined' && 'Notification' in window;
}

/**
 * Get current browser notification permission status: 'granted' | 'denied' | 'default' | 'unsupported'
 */
export function getNotificationPermission() {
  if (!isPushSupported()) return 'unsupported';
  return Notification.permission;
}

/**
 * Request notification permission from the user
 * @returns {Promise<'granted' | 'denied' | 'default' | 'unsupported'>}
 */
export async function requestNotificationPermission() {
  if (!isPushSupported()) return 'unsupported';
  try {
    const perm = await Notification.requestPermission();
    return perm;
  } catch (err) {
    console.warn('Failed to request notification permission:', err);
    return Notification.permission;
  }
}

/**
 * Send a proximity warning push notification for a hotspot along the active route
 * @param {Object} options
 * @param {string} options.name - Hotspot name
 * @param {number} options.distanceMeters - Distance threshold (1000, 500, or 300)
 * @param {string} options.riskLevel - 'CRITICAL' | 'HIGH' | 'MODERATE' | 'LOW'
 * @param {string} [options.policeStation] - Police jurisdiction
 */
export function sendHotspotPushNotification({ name, distanceMeters, riskLevel = 'HIGH', policeStation = '' }) {
  if (!isPushSupported() || Notification.permission !== 'granted') {
    return false;
  }

  const alertKey = `${name}_${distanceMeters}`;
  if (sentAlertKeys.has(alertKey)) {
    return false; // Already alerted for this threshold
  }
  sentAlertKeys.add(alertKey);

  let title = '';
  let body = '';

  if (distanceMeters >= 400) {
    title = `⚠️ Caution: Accident Hotspot in 500m`;
    body = `Caution. Accident-prone hotspot ahead in 500 meters: ${name} (${riskLevel} Risk). Maintain speed limit.`;
  } else if (distanceMeters >= 250) {
    title = `🚨 Caution: Accident Hotspot in 300m`;
    body = `Caution. Accident-prone hotspot ahead in 300 meters: ${name}. Slow down and watch for merging traffic.`;
  } else {
    title = `🛑 Critical Caution: Blackspot in 200m!`;
    body = `Caution. Accident-prone hotspot ahead in 200 meters: ${name}. Slow down immediately! Drive with maximum alertness.`;
  }

  if (policeStation) {
    body += ` Jurisdiction: ${policeStation}.`;
  }

  try {
    // Vibrate mobile devices if supported (pattern: vibrate 200ms, pause 100ms, vibrate 200ms)
    if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
      try {
        navigator.vibrate([200, 100, 200]);
      } catch (e) {}
    }

    const notification = new Notification(title, {
      body,
      icon: '/vite.svg',
      tag: `margrakshak-${name}-${distanceMeters}`, // Prevent OS popup pileup
      renotify: true,
      requireInteraction: distanceMeters <= 200,
    });

    notification.onclick = function () {
      window.focus();
      this.close();
    };

    return true;
  } catch (err) {
    console.warn('Could not display system notification:', err);
    return false;
  }
}

/**
 * Resets notification deduplication state when trip or route changes
 */
export function resetNotificationTracker() {
  sentAlertKeys.clear();
}

export const pushNotificationService = {
  isSupported: isPushSupported,
  getPermission: getNotificationPermission,
  requestPermission: requestNotificationPermission,
  notifyHotspot: (hotspot, distanceMeters) =>
    sendHotspotPushNotification({
      name: hotspot?.name || 'Accident Hotspot',
      distanceMeters,
      riskLevel: hotspot?.riskLevel || 'HIGH',
      policeStation: hotspot?.policeStation || '',
    }),
  reset: resetNotificationTracker,
};

export default pushNotificationService;

