/**
 * TrackPulse - Production-Grade 1-Second Real-Time Location Tracker
 * Architecture: 1-Second GPS Heartbeat Emitter + requestAnimationFrame LERP Engine
 * Author: Antigravity AI
 */

// =========================================================
// 1. App State & Globals
// =========================================================
let socket = null;

function isLocalEnvironment() {
    const host = window.location.hostname;
    return host === "localhost" || host === "127.0.0.1" || host === "::1" || host.startsWith("192.168.") || host.startsWith("10.");
}

function isSelfUser(id) {
    if (!id) return false;
    if (id === "local-user" || id === "local-demo") return true;
    if (socket && socket.id && id === socket.id) return true;
    return false;
}

function getLocalUserId() {
    return (socket && socket.id) || "local-user";
}

// Map & Layer references
let map = null;
let currentTileLayer = null;
let routingControl = null;

// Points and Pins
let sourcePoint = null;        // { lat, lng, name }
let destPoint = null;          // { lat, lng, name }
let sourceMarker = null;
let destMarker = null;
let activePickingMode = null;  // 'source' | 'dest' | null

// Vehicle & Settings
let selectedVehicleType = "car";
let isCameraFollowEnabled = true;
let isBreadcrumbEnabled = true;
let trackedFocusId = null; // id of user to auto-follow, default self

// Simulation State
let isSimulating = false;
let simInterval = null;
let simRouteCoords = [];
let simIndex = 0;
let simSpeedMultiplier = 2;

// Telemetry & GPS State
let lastRawGpsReading = null;
let previousGpsCoord = null;
let lastGpsTimestamp = 0;
let computedGpsSpeed = 0;
let computedGpsHeading = 0;
let gpsWatchId = null;
let heartbeatTimer = null;
let lastPingTime = 0;

// Multi-user Smooth Tracker Registry: { [socketId]: SmoothMarker }
const userTrackers = {};

// =========================================================
// API Keys & Config (MapTiler / LocationIQ / OSM / Server)
// =========================================================
const API_CONFIG = {
    maptiler: localStorage.getItem("MAPTILER_API_KEY") || "",
    locationiq: localStorage.getItem("LOCATIONIQ_API_KEY") || "",
    socketServer: localStorage.getItem("TRACKPULSE_SERVER_URL") || ""
};

let activeLayerKey = "dark";

function getTileLayers() {
    const key = API_CONFIG.maptiler;
    if (key) {
        return {
            osm: {
                url: `https://api.maptiler.com/maps/streets-v2/256/{z}/{x}/{y}.png?key=${key}`,
                options: { maxZoom: 19, attribution: "&copy; MapTiler &copy; OpenStreetMap" }
            },
            dark: {
                url: `https://api.maptiler.com/maps/dataviz-dark/256/{z}/{x}/{y}.png?key=${key}`,
                options: { maxZoom: 19, attribution: "&copy; MapTiler &copy; OpenStreetMap" }
            },
            voyager: {
                url: `https://api.maptiler.com/maps/outdoor-v2/256/{z}/{x}/{y}.png?key=${key}`,
                options: { maxZoom: 19, attribution: "&copy; MapTiler &copy; OpenStreetMap" }
            },
            satellite: {
                url: `https://api.maptiler.com/maps/satellite/256/{z}/{x}/{y}.jpg?key=${key}`,
                options: { maxZoom: 18, attribution: "&copy; MapTiler &copy; OpenStreetMap" }
            }
        };
    }

    // Default 100% Free OpenStreetMap & CartoDB Layers (No API Key Required)
    return {
        dark: {
            url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
            options: { maxZoom: 19, attribution: "&copy; CARTO &copy; OpenStreetMap" }
        },
        osm: {
            url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            options: { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" }
        },
        voyager: {
            url: "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
            options: { maxZoom: 19, attribution: "&copy; CARTO &copy; OpenStreetMap" }
        },
        satellite: {
            url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            options: { maxZoom: 18, attribution: "&copy; Esri &mdash; World Imagery" }
        }
    };
}

// =========================================================
// 2. DOM Elements
// =========================================================
const sourceInput = document.getElementById("sourceInput");
const destInput = document.getElementById("destInput");
const sourceResults = document.getElementById("sourceResults");
const destResults = document.getElementById("destResults");
const clearSourceBtn = document.getElementById("clearSourceBtn");
const clearDestBtn = document.getElementById("clearDestBtn");
const useMyGpsBtn = document.getElementById("useMyGpsBtn");
const pickSourceBtn = document.getElementById("pickSourceBtn");
const pickDestBtn = document.getElementById("pickDestBtn");
const swapPointsBtn = document.getElementById("swapPointsBtn");
const calculateRouteBtn = document.getElementById("calculateRouteBtn");
const resetRouteBtn = document.getElementById("resetRouteBtn");

// Panels and Drawers
const routePanel = document.getElementById("routePanel");
const collapsePanelBtn = document.getElementById("collapsePanelBtn");
const fleetDrawer = document.getElementById("fleetDrawer");
const toggleFleetBtn = document.getElementById("toggleFleetBtn");
const closeFleetBtn = document.getElementById("closeFleetBtn");
const fleetList = document.getElementById("fleetList");
const fleetCount = document.getElementById("fleetCount");

// Status Header Elements
const socketIndicator = document.getElementById("socketIndicator");
const socketStatusText = document.getElementById("socketStatusText");
const pingBadge = document.getElementById("pingBadge");
const gpsStatusText = document.getElementById("gpsStatusText");
const gpsAccuracyBadge = document.getElementById("gpsAccuracyBadge");
const activeUsersCount = document.getElementById("activeUsersCount");

// Telemetry HUD Elements
const telemetryHud = document.getElementById("telemetryHud");
const hudCollapseBtn = document.getElementById("hudCollapseBtn");
const hudSpeed = document.getElementById("hudSpeed");
const speedoBar = document.getElementById("speedoBar");
const compassNeedle = document.getElementById("compassNeedle");
const hudHeadingDeg = document.getElementById("hudHeadingDeg");
const hudHeadingCardinal = document.getElementById("hudHeadingCardinal");
const hudCoords = document.getElementById("hudCoords");
const hudAccuracy = document.getElementById("hudAccuracy");
const heartbeatLed = document.getElementById("heartbeatLed");
const cameraFollowBtn = document.getElementById("cameraFollowBtn");
const breadcrumbToggleBtn = document.getElementById("breadcrumbToggleBtn");

// Trip & Sim Elements
const tripSummary = document.getElementById("tripSummary");
const tripDistance = document.getElementById("tripDistance");
const tripDuration = document.getElementById("tripDuration");
const toggleDirectionsBtn = document.getElementById("toggleDirectionsBtn");
const directionsList = document.getElementById("directionsList");
const startSimBtn = document.getElementById("startSimBtn");
const stopSimBtn = document.getElementById("stopSimBtn");
const simStatus = document.getElementById("simStatus");
const simProgressFill = document.getElementById("simProgressFill");
const simSpeedSelect = document.getElementById("simSpeedSelect");

// Map Controls
const recenterBtn = document.getElementById("recenterBtn");
const fitRouteBtn = document.getElementById("fitRouteBtn");
const zoomInBtn = document.getElementById("zoomInBtn");
const zoomOutBtn = document.getElementById("zoomOutBtn");
const layerBtn = document.getElementById("layerBtn");
const layerMenu = document.getElementById("layerMenu");

// Toast & Tips
const toastContainer = document.getElementById("toastContainer");
const tipsBanner = document.getElementById("tipsBanner");
const closeTipBtn = document.getElementById("closeTipBtn");

// =========================================================
// 3. Mathematical Helpers: Haversine & Azimuth Heading
// =========================================================
const toRad = (deg) => (deg * Math.PI) / 180;
const toDeg = (rad) => (rad * 180) / Math.PI;

/**
 * Calculates Great-Circle distance between two coordinates in meters
 */
function calculateDistanceMeters(lat1, lon1, lat2, lon2) {
    const R = 6371000; // Earth radius in meters
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
              Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
              Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
}

/**
 * Calculates forward azimuth (bearing) from coordinate 1 to coordinate 2 in degrees [0, 360)
 */
function calculateBearing(lat1, lon1, lat2, lon2) {
    const phi1 = toRad(lat1);
    const phi2 = toRad(lat2);
    const deltaLambda = toRad(lon2 - lon1);

    const y = Math.sin(deltaLambda) * Math.cos(phi2);
    const x = Math.cos(phi1) * Math.sin(phi2) -
              Math.sin(phi1) * Math.cos(phi2) * Math.cos(deltaLambda);
    const theta = Math.atan2(y, x);
    return (toDeg(theta) + 360) % 360;
}

/**
 * Converts degree angle to cardinal direction
 */
function degreeToCardinal(deg) {
    const directions = [
        "NORTH", "NNE", "NE", "ENE",
        "EAST", "ESE", "SE", "SSE",
        "SOUTH", "SSW", "SW", "WSW",
        "WEST", "WNW", "NW", "NNW"
    ];
    const index = Math.round(deg / 22.5) % 16;
    return directions[index];
}

// =========================================================
// 4. SmoothMarker Controller (Linear Interpolation LERP Engine)
// =========================================================
class SmoothMarker {
    constructor(id, data, mapInstance) {
        this.id = id;
        this.data = data;
        this.map = mapInstance;

        // Position states
        this.startLat = data.latitude;
        this.startLng = data.longitude;
        this.targetLat = data.latitude;
        this.targetLng = data.longitude;
        this.currentLat = data.latitude;
        this.currentLng = data.longitude;

        // Bearing / Rotation states
        this.startBearing = data.heading || 0;
        this.targetBearing = data.heading || 0;
        this.currentBearing = data.heading || 0;

        // Timing & Speed
        this.startTime = performance.now();
        this.lastPacketTime = performance.now();
        this.duration = 180; // Fast sub-second default
        this.currentSpeed = data.speed || 0;
        this.lastPanTime = 0;

        // Leaflet Marker & Breadcrumb Polyline
        this.marker = null;
        this.polyline = null;
        this.breadcrumbHistory = [];

        this.initElements();
    }

    initElements() {
        const isSelf = isSelfUser(this.id);
        const displayName = isSelf ? `${this.data.name} (You)` : this.data.name;
        const color = this.data.color || "#3b82f6";
        const vehicleType = this.data.vehicleType || "car";

        // Create custom Leaflet Marker with directional beacon
        const icon = createFleetBeaconIcon(color, vehicleType, this.currentBearing);
        this.marker = L.marker([this.currentLat, this.currentLng], {
            icon,
            zIndexOffset: isSelf ? 2000 : 1000
        }).addTo(this.map);

        this.updatePopupContent();

        // Glowing breadcrumb trail polyline
        this.polyline = L.polyline([[this.currentLat, this.currentLng]], {
            color: color,
            weight: 4,
            opacity: 0.75,
            dashArray: "6, 8",
            lineCap: "round"
        });

        if (isBreadcrumbEnabled) {
            this.polyline.addTo(this.map);
        }
    }

    updateTarget(newData) {
        this.data = { ...this.data, ...newData };
        const now = performance.now();

        // Dynamically compute interpolation duration matching transmission cadence
        const timeDelta = this.lastPacketTime ? (now - this.lastPacketTime) : 180;
        this.lastPacketTime = now;
        // Keep duration responsive (clamped between 80ms and 260ms, zero lag!)
        this.duration = Math.min(260, Math.max(80, timeDelta * 1.05));

        // Fast teleport check (> 300m sudden movement)
        const jumpDistance = calculateDistanceMeters(this.currentLat, this.currentLng, newData.latitude, newData.longitude);
        if (jumpDistance > 300) {
            this.currentLat = newData.latitude;
            this.currentLng = newData.longitude;
            this.startLat = newData.latitude;
            this.startLng = newData.longitude;
            this.targetLat = newData.latitude;
            this.targetLng = newData.longitude;
            if (this.marker) this.marker.setLatLng([this.currentLat, this.currentLng]);
        } else {
            this.startLat = this.currentLat;
            this.startLng = this.currentLng;
            this.targetLat = newData.latitude;
            this.targetLng = newData.longitude;
        }

        // Rotate through shortest angular distance
        this.startBearing = this.currentBearing;
        this.targetBearing = typeof newData.heading === "number" ? newData.heading : this.currentBearing;

        this.currentSpeed = newData.speed || 0;
        this.startTime = now;

        // Append to breadcrumb trail
        this.breadcrumbHistory.push([newData.latitude, newData.longitude]);
        if (this.breadcrumbHistory.length > 30) {
            this.breadcrumbHistory.shift();
        }
        if (this.polyline && isBreadcrumbEnabled) {
            this.polyline.setLatLngs(this.breadcrumbHistory);
        }

        this.updatePopupContent();
    }

    /**
     * Called on each requestAnimationFrame tick
     */
    animate(now) {
        const elapsed = now - this.startTime;
        const t = this.duration > 0 ? Math.min(1, Math.max(0, elapsed / this.duration)) : 1;

        // Linear interpolation for lat & lng
        this.currentLat = this.startLat + (this.targetLat - this.startLat) * t;
        this.currentLng = this.startLng + (this.targetLng - this.startLng) * t;

        // Shortest-distance angular interpolation
        const angleDiff = ((this.targetBearing - this.startBearing + 540) % 360) - 180;
        this.currentBearing = (this.startBearing + angleDiff * t + 360) % 360;

        // Update marker position
        if (this.marker) {
            this.marker.setLatLng([this.currentLat, this.currentLng]);

            // Rotate inner directional vehicle element directly
            const el = this.marker.getElement();
            if (el) {
                const rotEl = el.querySelector(".beacon-rotator");
                if (rotEl) {
                    rotEl.style.transform = `rotate(${Math.round(this.currentBearing)}deg)`;
                }
            }
        }

        // Camera Follow Mode: Pan map smoothly without main-thread jank (throttled to ~90ms)
        const isSelf = isSelfUser(this.id);
        const shouldFollow = isCameraFollowEnabled && (trackedFocusId === this.id || (!trackedFocusId && isSelf));
        if (shouldFollow && map) {
            if (!this.lastPanTime || (now - this.lastPanTime > 90)) {
                this.lastPanTime = now;
                map.panTo([this.currentLat, this.currentLng], { animate: false });
            }
        }

        // If this is self, update the telemetry HUD
        if (isSelf) {
            updateTelemetryHUD(this.currentSpeed, this.currentBearing, this.currentLat, this.currentLng, this.data.accuracy);
        }
    }

    updatePopupContent() {
        if (!this.marker) return;
        const isSelf = isSelfUser(this.id);
        const displayName = isSelf ? `${this.data.name} (You)` : this.data.name;
        const color = this.data.color || "#3b82f6";
        const speed = Math.round(this.currentSpeed);

        this.marker.bindPopup(`
            <div class="popup-card">
                <div class="popup-title" style="color: ${color}">
                    <i class="fa-solid fa-${this.data.vehicleType === 'bike' ? 'motorcycle' : (this.data.vehicleType === 'van' ? 'truck' : 'car')}"></i>
                    ${displayName}
                </div>
                <div class="popup-sub">Speed: ${speed} km/h • Heading: ${Math.round(this.currentBearing)}°</div>
                <div class="popup-sub">${this.currentLat.toFixed(5)}, ${this.currentLng.toFixed(5)}</div>
            </div>
        `);
    }

    destroy() {
        if (this.marker) {
            this.map.removeLayer(this.marker);
            this.marker = null;
        }
        if (this.polyline) {
            this.map.removeLayer(this.polyline);
            this.polyline = null;
        }
    }
}

// Master requestAnimationFrame loop for all smooth markers
function startAnimationLoop() {
    function loop(now) {
        for (const id in userTrackers) {
            userTrackers[id].animate(now);
        }
        requestAnimationFrame(loop);
    }
    requestAnimationFrame(loop);
}

// =========================================================
// 5. Initialize Leaflet Map
// =========================================================
function initMap() {
    // Default coordinates: New Delhi, India
    const defaultCoords = [28.6139, 77.2090];

    map = L.map("map", {
        zoomControl: false,
        attributionControl: true
    }).setView(defaultCoords, 14);

    // Set Default Dark Tile Layer
    setMapLayer("dark");

    // Map Click Listener for Route Planning
    map.on("click", handleMapClick);

    // Start Master Lerp Animation Loop
    startAnimationLoop();

    showToast("TrackPulse active: 1-Second GPS sync & Lerp motion enabled! 🚀", "info");
}

function setMapLayer(layerKey) {
    activeLayerKey = layerKey;
    const tileLayers = getTileLayers();
    const layerConf = tileLayers[layerKey] || tileLayers.dark;
    if (currentTileLayer) {
        map.removeLayer(currentTileLayer);
    }
    currentTileLayer = L.tileLayer(layerConf.url, layerConf.options).addTo(map);

    document.querySelectorAll(".dropdown-item").forEach(item => {
        item.classList.toggle("active", item.getAttribute("data-layer") === layerKey);
    });
}

// =========================================================
// 6. Custom Pin & Beacon Icons
// =========================================================
function createCustomPin(type) {
    const isSource = type === "source";
    const className = isSource ? "start-pin" : "dest-pin";
    const iconClass = isSource ? "fa-circle-dot" : "fa-flag-checkered";

    return L.divIcon({
        className: "custom-pin-marker",
        html: `<div class="${className}"><i class="fa-solid ${iconClass}"></i></div>`,
        iconSize: [34, 34],
        iconAnchor: [17, 34],
        popupAnchor: [0, -32]
    });
}

function createFleetBeaconIcon(color = "#3b82f6", vehicleType = "car", heading = 0) {
    let vehicleIcon = "fa-car";
    if (vehicleType === "bike") vehicleIcon = "fa-motorcycle";
    if (vehicleType === "van") vehicleIcon = "fa-truck";

    return L.divIcon({
        className: "custom-pin-marker",
        html: `
            <div class="live-tracker-beacon" style="--beacon-color: ${color}">
                <div class="beacon-pulse"></div>
                <div class="beacon-rotator" style="position: absolute; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; transform: rotate(${Math.round(heading)}deg);">
                    <div class="heading-cone"></div>
                    <div class="beacon-core">
                        <i class="fa-solid ${vehicleIcon}"></i>
                    </div>
                </div>
            </div>
        `,
        iconSize: [44, 44],
        iconAnchor: [22, 22],
        popupAnchor: [0, -20]
    });
}

// =========================================================
// 7. Toast Notification System
// =========================================================
function showToast(message, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;

    let icon = "fa-circle-info";
    if (type === "success") icon = "fa-circle-check";
    if (type === "error") icon = "fa-triangle-exclamation";

    toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${message}</span>`;
    toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = "toast-out 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards";
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// =========================================================
// 8. High-Frequency Real-Time Geolocation & Heartbeat Emitter
// =========================================================
let lastGpsEmitTime = 0;

function initGeolocation() {
    if (!navigator.geolocation) {
        gpsStatusText.textContent = "GPS Unavailable";
        showToast("Geolocation is not supported by your browser.", "error");
        return;
    }

    gpsStatusText.textContent = "Acquiring GPS...";

    // 1. High-Accuracy Geolocation Watcher
    gpsWatchId = navigator.geolocation.watchPosition(
        (pos) => {
            const { latitude, longitude, speed, heading, accuracy, altitude } = pos.coords;
            const now = Date.now();

            // Compute dynamic fallback bearing & speed if device reports null
            let resolvedHeading = heading;
            let resolvedSpeed = speed ? speed * 3.6 : 0; // m/s to km/h

            if (previousGpsCoord) {
                const distMeters = calculateDistanceMeters(
                    previousGpsCoord.lat, previousGpsCoord.lng,
                    latitude, longitude
                );
                const timeDiffSec = (now - lastGpsTimestamp) / 1000;

                // If speed is not provided by hardware, calculate from distance/time
                if (speed === null || isNaN(speed)) {
                    if (timeDiffSec > 0) {
                        resolvedSpeed = (distMeters / timeDiffSec) * 3.6;
                    }
                }

                // If heading is not provided by hardware, calculate forward azimuth
                if (heading === null || isNaN(heading)) {
                    if (distMeters >= 1.0) { // Update bearing if motion > 1m
                        resolvedHeading = calculateBearing(
                            previousGpsCoord.lat, previousGpsCoord.lng,
                            latitude, longitude
                        );
                        computedGpsHeading = resolvedHeading;
                    } else {
                        resolvedHeading = computedGpsHeading;
                    }
                }
            }

            previousGpsCoord = { lat: latitude, lng: longitude };
            lastGpsTimestamp = now;
            computedGpsSpeed = resolvedSpeed;

            lastRawGpsReading = {
                latitude,
                longitude,
                speed: Math.round(resolvedSpeed * 10) / 10,
                heading: Math.round(resolvedHeading || 0),
                accuracy: Math.round(accuracy || 0),
                altitude: altitude ? Math.round(altitude) : null,
                timestamp: now
            };

            gpsStatusText.textContent = "GPS Active";
            gpsAccuracyBadge.textContent = `±${Math.round(accuracy)}m`;

            // Auto-center map on initial GPS lock if start point not set
            const localId = getLocalUserId();
            if (!sourcePoint && userTrackers[localId] === undefined) {
                map.setView([latitude, longitude], 15);
            }

            const gpsPayload = {
                id: localId,
                name: "Fleet #1 (You)",
                latitude,
                longitude,
                speed: computedGpsSpeed,
                heading: Math.round(resolvedHeading || 0),
                accuracy: Math.round(accuracy || 0),
                altitude: altitude ? Math.round(altitude) : null,
                vehicleType: selectedVehicleType,
                color: "#10b981",
                timestamp: now
            };

            // Instant local render for smooth responsiveness
            if (!isSimulating) {
                handleIncomingUserLocation(gpsPayload);
                renderFleetDrawer();
            }

            // INSTANT TRANSMISSION: Emit immediately when hardware reports position!
            if (!isSimulating && socket && socket.connected) {
                if (now - lastGpsEmitTime >= 100) {
                    lastGpsEmitTime = now;
                    socket.emit("send-location", gpsPayload);
                    triggerHeartbeatVisual();
                }
            }
        },
        (err) => {
            console.warn("[Geolocation Warning]", err.message);
            gpsStatusText.textContent = "GPS Denied";
            gpsAccuracyBadge.textContent = "Off";
            showToast("GPS permission denied. You can use 'Demo Drive' or pick locations on map!", "info");
        },
        {
            enableHighAccuracy: true,
            maximumAge: 300,
            timeout: 10000 // 10-second timeout avoids constant watchPosition restart errors
        }
    );

    // 2. High-Frequency Fallback Heartbeat (every 300ms for continuous streaming)
    heartbeatTimer = setInterval(() => {
        if (isSimulating) return;

        const now = Date.now();
        if (lastRawGpsReading && socket && socket.connected) {
            // Keep stream active if no hardware event was triggered in 300ms
            if (now - lastGpsEmitTime >= 300) {
                lastGpsEmitTime = now;
                socket.emit("send-location", {
                    id: getLocalUserId(),
                    ...lastRawGpsReading,
                    vehicleType: selectedVehicleType
                });
                triggerHeartbeatVisual();
            }
        }
    }, 300);
}

function triggerHeartbeatVisual() {
    heartbeatLed.classList.add("flash");
    setTimeout(() => heartbeatLed.classList.remove("flash"), 220);
}

// =========================================================
// 9. Telemetry HUD Updater
// =========================================================
function updateTelemetryHUD(speed, heading, lat, lng, accuracy) {
    // 1. Numeric Speed
    const roundedSpeed = Math.max(0, Math.round(speed));
    hudSpeed.textContent = roundedSpeed;

    // 2. Speedometer Gauge Arc (0 to 120 km/h)
    // Circumference = 2 * PI * 42 ~= 264
    const maxSpeed = 120;
    const progress = Math.min(1, roundedSpeed / maxSpeed);
    const strokeOffset = 264 - progress * 264;
    speedoBar.style.strokeDashoffset = strokeOffset;

    if (roundedSpeed > 80) {
        speedoBar.style.stroke = "var(--accent-red)";
    } else if (roundedSpeed > 50) {
        speedoBar.style.stroke = "var(--accent-amber)";
    } else {
        speedoBar.style.stroke = "var(--accent-cyan)";
    }

    // 3. Compass Rose
    const deg = Math.round((heading % 360 + 360) % 360);
    compassNeedle.style.transform = `rotate(${deg}deg)`;
    hudHeadingDeg.textContent = `${deg}°`;
    hudHeadingCardinal.textContent = degreeToCardinal(deg);

    // 4. Coordinates & Accuracy
    hudCoords.textContent = `Lat: ${lat.toFixed(5)}, Lng: ${lng.toFixed(5)}`;
    if (accuracy) {
        hudAccuracy.textContent = `Precision: ±${Math.round(accuracy)}m (High Accuracy)`;
    } else {
        hudAccuracy.textContent = `Precision: High-Def Interpolation`;
    }
}

// =========================================================
// 10. Socket Connection & Streaming Events
// =========================================================
function initSocket() {
    if (socket) {
        try {
            socket.removeAllListeners();
            socket.disconnect();
        } catch (e) {}
        socket = null;
    }

    const customServer = API_CONFIG.socketServer && API_CONFIG.socketServer.trim();
    const isLocal = isLocalEnvironment();

    let targetUrl = null;
    if (customServer) {
        targetUrl = customServer;
    } else if (isLocal) {
        targetUrl = window.location.origin;
    }

    // Standalone Live mode if hosted on Netlify and no backend URL provided
    if (!targetUrl) {
        if (socketIndicator) socketIndicator.className = "status-indicator standalone";
        if (socketStatusText) socketStatusText.textContent = "Standalone Live";
        if (pingBadge) pingBadge.textContent = "Local";
        if (activeUsersCount) activeUsersCount.textContent = "1";
        if (fleetCount) fleetCount.textContent = "1";
        return;
    }

    if (typeof io === "undefined") {
        console.warn("[TrackPulse] Socket.io client not loaded yet.");
        if (socketIndicator) socketIndicator.className = "status-indicator offline";
        if (socketStatusText) socketStatusText.textContent = "Offline";
        return;
    }

    try {
        if (socketIndicator) socketIndicator.className = "status-indicator offline";
        if (socketStatusText) socketStatusText.textContent = "Connecting...";

        socket = io(targetUrl, {
            transports: ["websocket", "polling"],
            reconnection: true,
            reconnectionDelay: 2000,
            reconnectionAttempts: 10,
            timeout: 10000
        });

        socket.on("connect", () => {
            if (socketIndicator) socketIndicator.className = "status-indicator online";
            if (socketStatusText) socketStatusText.textContent = "Connected";
            measurePing();
            showToast("Connected to live fleet server! 🚀", "success");
        });

        socket.on("disconnect", (reason) => {
            if (socketIndicator) socketIndicator.className = "status-indicator offline";
            if (socketStatusText) socketStatusText.textContent = "Reconnecting...";
            if (pingBadge) pingBadge.textContent = "-- ms";
        });

        socket.on("connect_error", (err) => {
            console.warn("[TrackPulse] Socket connection failed:", err.message);
            if (socketIndicator) socketIndicator.className = "status-indicator offline";
            if (socketStatusText) socketStatusText.textContent = "Server Offline";
            if (pingBadge) pingBadge.textContent = "Offline";
        });

        socket.on("user-count", (count) => {
            if (activeUsersCount) activeUsersCount.textContent = count;
            if (fleetCount) fleetCount.textContent = count;
        });

        socket.on("init-users", (users) => {
            if (Array.isArray(users)) {
                users.forEach(user => {
                    if (user && user.latitude && user.longitude && !isSelfUser(user.id)) {
                        handleIncomingUserLocation(user);
                    }
                });
                renderFleetDrawer();
            }
        });

        socket.on("receive-location", (data) => {
            if (data && data.id && !isSelfUser(data.id)) {
                handleIncomingUserLocation(data);
                renderFleetDrawer();
            }
        });

        socket.on("user-disconnected", (id) => {
            if (userTrackers[id]) {
                userTrackers[id].destroy();
                delete userTrackers[id];
                renderFleetDrawer();
                showToast("A fleet tracker went offline.", "info");
            }
        });
    } catch (err) {
        console.error("[TrackPulse] Failed to initialize socket:", err);
    }
}

// Calculate socket ping latency
function measurePing() {
    if (!socket || !socket.connected) return;
    lastPingTime = Date.now();
    socket.emit("ping-test", null, () => {
        const latency = Date.now() - lastPingTime;
        if (pingBadge) pingBadge.textContent = `${latency}ms`;
    });
}
setInterval(measurePing, 10000);

function handleIncomingUserLocation(data) {
    const { id } = data;
    if (userTrackers[id]) {
        // Feed into existing smooth lerp controller
        userTrackers[id].updateTarget(data);
    } else {
        // Instantiate new SmoothMarker instance
        userTrackers[id] = new SmoothMarker(id, data, map);
    }
}

// =========================================================
// 11. Active Fleet Drawer Rendering & Focus
// =========================================================
function renderFleetDrawer() {
    const keys = Object.keys(userTrackers);
    if (keys.length === 0) {
        fleetList.innerHTML = `<div class="empty-fleet">Waiting for live location signals...</div>`;
        return;
    }

    fleetList.innerHTML = keys.map(id => {
        const tracker = userTrackers[id];
        const data = tracker.data;
        const isSelf = isSelfUser(id);
        const color = data.color || "#3b82f6";
        const speed = Math.round(tracker.currentSpeed || 0);
        const vehicleIcon = data.vehicleType === "bike" ? "motorcycle" : (data.vehicleType === "van" ? "truck" : "car");

        return `
            <div class="fleet-item">
                <div class="fleet-user-info">
                    <span class="user-avatar-dot" style="background-color: ${color}; color: ${color}"></span>
                    <div class="user-name-wrapper">
                        <span class="user-name-title">
                            <i class="fa-solid fa-${vehicleIcon}"></i>
                            ${isSelf ? data.name + ' (You)' : data.name}
                        </span>
                        <span class="user-coords">${speed} km/h • ${tracker.currentLat.toFixed(4)}, ${tracker.currentLng.toFixed(4)}</span>
                    </div>
                </div>
                <button type="button" class="fleet-focus-btn" onclick="focusUser('${id}')">
                    <i class="fa-solid fa-crosshairs"></i> Follow
                </button>
            </div>
        `;
    }).join("");
}

window.focusUser = function (id) {
    if (userTrackers[id]) {
        trackedFocusId = id;
        isCameraFollowEnabled = true;
        cameraFollowBtn.classList.add("active");

        const tracker = userTrackers[id];
        map.flyTo([tracker.currentLat, tracker.currentLng], 16, { duration: 1.2 });
        tracker.marker.openPopup();
        fleetDrawer.classList.remove("show");
        showToast(`Camera locked on ${tracker.data.name}`, "info");
    }
};

// =========================================================
// 12. Nominatim Address Search & Autocomplete
// =========================================================
let debounceTimer = null;

function setupSearchInput(inputEl, resultsEl, clearBtn, onSelect) {
    inputEl.addEventListener("input", (e) => {
        const val = e.target.value.trim();
        clearBtn.style.display = val.length > 0 ? "block" : "none";

        if (debounceTimer) clearTimeout(debounceTimer);

        if (val.length < 3) {
            resultsEl.classList.remove("active");
            resultsEl.innerHTML = "";
            return;
        }

        debounceTimer = setTimeout(() => {
            fetchPlaces(val, resultsEl, onSelect);
        }, 350);
    });

    clearBtn.addEventListener("click", () => {
        inputEl.value = "";
        clearBtn.style.display = "none";
        resultsEl.classList.remove("active");
        resultsEl.innerHTML = "";
    });
}

async function fetchPlaces(query, resultsEl, onSelect) {
    try {
        let url;
        if (API_CONFIG.locationiq) {
            url = `https://us1.locationiq.com/v1/search?key=${API_CONFIG.locationiq}&q=${encodeURIComponent(query)}&format=json&limit=5`;
        } else {
            url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=5&addressdetails=1`;
        }
        const res = await fetch(url);
        const data = await res.json();

        if (!data || data.length === 0) {
            resultsEl.innerHTML = `<div class="result-item"><i class="fa-solid fa-magnifying-glass"></i> No places found</div>`;
            resultsEl.classList.add("active");
            return;
        }

        resultsEl.innerHTML = data.map((item, idx) => `
            <div class="result-item" data-idx="${idx}">
                <i class="fa-solid fa-location-dot"></i>
                <span>${item.display_name}</span>
            </div>
        `).join("");

        resultsEl.classList.add("active");

        resultsEl.querySelectorAll(".result-item").forEach(itemEl => {
            itemEl.addEventListener("click", () => {
                const idx = itemEl.getAttribute("data-idx");
                const chosen = data[idx];
                if (chosen) {
                    onSelect({
                        lat: parseFloat(chosen.lat),
                        lng: parseFloat(chosen.lon),
                        name: chosen.display_name
                    });
                    resultsEl.classList.remove("active");
                }
            });
        });
    } catch (err) {
        console.error("Geocoding fetch error:", err);
    }
}

async function reverseGeocode(lat, lng) {
    try {
        let url;
        if (API_CONFIG.locationiq) {
            url = `https://us1.locationiq.com/v1/reverse?key=${API_CONFIG.locationiq}&lat=${lat}&lon=${lng}&format=json`;
        } else {
            url = `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`;
        }
        const res = await fetch(url);
        const data = await res.json();
        return data?.display_name || `Location (${lat.toFixed(4)}, ${lng.toFixed(4)})`;
    } catch (e) {
        return `Location (${lat.toFixed(4)}, ${lng.toFixed(4)})`;
    }
}

// =========================================================
// 13. Map Click & Route Point Selection
// =========================================================
async function handleMapClick(e) {
    const latlng = e.latlng;

    if (activePickingMode === "source") {
        setSourcePoint({ lat: latlng.lat, lng: latlng.lng });
        resetPickModes();
        showToast("Start Point selected from map!", "success");
        return;
    }

    if (activePickingMode === "dest") {
        setDestPoint({ lat: latlng.lat, lng: latlng.lng });
        resetPickModes();
        showToast("Destination selected from map!", "success");
        return;
    }

    if (!sourcePoint) {
        setSourcePoint({ lat: latlng.lat, lng: latlng.lng });
        showToast("Start Point set! Now pick or search for Destination.", "info");
    } else if (!destPoint) {
        setDestPoint({ lat: latlng.lat, lng: latlng.lng });
        showToast("Destination set! Drawing route...", "success");
        calculateAndDrawRoute();
    } else {
        showToast("Both points are set. Click 'Reset' to plan a new route.", "info");
    }
}

function resetPickModes() {
    activePickingMode = null;
    pickSourceBtn.classList.remove("active");
    pickDestBtn.classList.remove("active");
}

async function setSourcePoint(point) {
    sourcePoint = point;

    if (!point.name) {
        sourceInput.value = "Resolving address...";
        reverseGeocode(point.lat, point.lng).then(name => {
            sourcePoint.name = name;
            sourceInput.value = name;
            clearSourceBtn.style.display = "block";
            if (sourceMarker) {
                sourceMarker.getPopup().setContent(`<b>Start Point:</b><br>${name}`);
            }
        });
    } else {
        sourceInput.value = point.name;
        clearSourceBtn.style.display = "block";
    }

    if (sourceMarker) {
        sourceMarker.setLatLng([point.lat, point.lng]);
    } else {
        sourceMarker = L.marker([point.lat, point.lng], {
            icon: createCustomPin("source"),
            draggable: true
        }).addTo(map);

        sourceMarker.on("dragend", async (e) => {
            const pos = e.target.getLatLng();
            setSourcePoint({ lat: pos.lat, lng: pos.lng });
            if (destPoint) calculateAndDrawRoute();
        });
    }

    sourceMarker.bindPopup(`<b>Start Point:</b><br>${sourcePoint.name || 'Selected Location'}`).openPopup();
}

async function setDestPoint(point) {
    destPoint = point;

    if (!point.name) {
        destInput.value = "Resolving address...";
        reverseGeocode(point.lat, point.lng).then(name => {
            destPoint.name = name;
            destInput.value = name;
            clearDestBtn.style.display = "block";
            if (destMarker) {
                destMarker.getPopup().setContent(`<b>Destination:</b><br>${name}`);
            }
        });
    } else {
        destInput.value = point.name;
        clearDestBtn.style.display = "block";
    }

    if (destMarker) {
        destMarker.setLatLng([point.lat, point.lng]);
    } else {
        destMarker = L.marker([point.lat, point.lng], {
            icon: createCustomPin("dest"),
            draggable: true
        }).addTo(map);

        destMarker.on("dragend", async (e) => {
            const pos = e.target.getLatLng();
            setDestPoint({ lat: pos.lat, lng: pos.lng });
            if (sourcePoint) calculateAndDrawRoute();
        });
    }

    destMarker.bindPopup(`<b>Destination:</b><br>${destPoint.name || 'Selected Destination'}`).openPopup();
}

// =========================================================
// 14. Route Calculation (OSRM & Leaflet Routing Machine)
// =========================================================
function calculateAndDrawRoute() {
    if (!sourcePoint || !destPoint) {
        showToast("Please select both a Start point and a Destination.", "error");
        return;
    }

    if (routingControl) {
        map.removeControl(routingControl);
    }

    stopSimulation();

    routingControl = L.Routing.control({
        waypoints: [
            L.latLng(sourcePoint.lat, sourcePoint.lng),
            L.latLng(destPoint.lat, destPoint.lng)
        ],
        router: L.Routing.osrmv1({
            serviceUrl: 'https://router.project-osrm.org/route/v1'
        }),
        routeWhileDragging: false,
        addWaypoints: false,
        fitSelectedRoutes: true,
        show: false,
        createMarker: () => null,
        lineOptions: {
            styles: [
                { color: '#1e3a8a', opacity: 0.8, weight: 8 },  // Deep neon underlay
                { color: '#38bdf8', opacity: 1, weight: 5 }     // Bright vibrant route
            ]
        }
    }).addTo(map);

    routingControl.on("routesfound", function (e) {
        const routes = e.routes;
        if (!routes || routes.length === 0) return;

        const summary = routes[0].summary;
        const distKm = (summary.totalDistance / 1000).toFixed(1);
        const timeMin = Math.round(summary.totalTime / 60);

        tripDistance.textContent = `${distKm} km`;
        tripDuration.textContent = timeMin > 60
            ? `${Math.floor(timeMin / 60)}h ${timeMin % 60}m`
            : `${timeMin} min`;

        const instructions = routes[0].instructions || [];
        if (instructions.length > 0) {
            directionsList.innerHTML = instructions.map(inst => `
                <div class="direction-step">
                    <i class="fa-solid fa-diamond-turn-right"></i>
                    <span>${inst.text} (${Math.round(inst.distance)}m)</span>
                </div>
            `).join("");
        } else {
            directionsList.innerHTML = `<div class="direction-step">Follow the highlighted route on the map.</div>`;
        }

        tripSummary.style.display = "flex";
        simRouteCoords = routes[0].coordinates || [];

        showToast(`Route plotted: ${distKm} km (${timeMin} mins)`, "success");
    });

    routingControl.on("routingerror", function (err) {
        console.error("Routing error:", err);
        showToast("Could not compute route between points. Try different locations.", "error");
    });
}

// =========================================================
// 15. Ultra-Fast Live Simulation Mode
// =========================================================
function startSimulation() {
    if (!simRouteCoords || simRouteCoords.length < 2) {
        showToast("Please calculate a route first before starting simulation.", "error");
        return;
    }

    if (isSimulating) return;

    isSimulating = true;
    simStatus.textContent = "Driving...";
    simStatus.style.background = "rgba(16, 185, 129, 0.25)";
    simStatus.style.color = "#34d399";
    startSimBtn.disabled = true;
    stopSimBtn.disabled = false;

    simIndex = 0;
    // Step interval: 120ms ultra-fast streaming (8-9 updates/sec for silky smooth live driving)
    const stepIntervalMs = 120;

    simInterval = setInterval(() => {
        if (simIndex >= simRouteCoords.length - 1) {
            stopSimulation();
            showToast("Demo drive arrived at destination! 🏁", "success");
            return;
        }

        // Advance along coordinate array proportional to speed multiplier
        const stepJump = Math.max(1, Math.round(1 * simSpeedMultiplier));
        const currentCoord = simRouteCoords[simIndex];
        const nextIndex = Math.min(simRouteCoords.length - 1, simIndex + stepJump);
        const nextCoord = simRouteCoords[nextIndex];

        // Compute simulated forward azimuth & speed
        const bearing = calculateBearing(currentCoord.lat, currentCoord.lng, nextCoord.lat, nextCoord.lng);
        const distMeters = calculateDistanceMeters(currentCoord.lat, currentCoord.lng, nextCoord.lat, nextCoord.lng);
        const simulatedSpeed = Math.round((distMeters / (stepIntervalMs / 1000)) * 3.6);

        // Update progress bar
        const progress = Math.round(((nextIndex + 1) / simRouteCoords.length) * 100);
        simProgressFill.style.width = `${progress}%`;

        // Broadcast simulated location through socket immediately!
        const payload = {
            id: (socket && socket.id) || "local-demo",
            name: "Fleet #1 (Demo Drive)",
            latitude: nextCoord.lat,
            longitude: nextCoord.lng,
            speed: simulatedSpeed,
            heading: bearing,
            vehicleType: selectedVehicleType,
            color: "#3b82f6",
            timestamp: Date.now()
        };

        if (socket && socket.connected) {
            socket.emit("send-location", payload);
        }

        // Always update local marker & HUD for buttery smooth demo driving
        handleIncomingUserLocation(payload);
        renderFleetDrawer();
        triggerHeartbeatVisual();

        simIndex = nextIndex;
    }, stepIntervalMs);
}

function stopSimulation() {
    if (simInterval) {
        clearInterval(simInterval);
        simInterval = null;
    }
    isSimulating = false;
    simStatus.textContent = "Stopped";
    simStatus.style.background = "rgba(239, 68, 68, 0.25)";
    simStatus.style.color = "#f87171";
    startSimBtn.disabled = false;
    stopSimBtn.disabled = true;
    simProgressFill.style.width = "0%";
}

// =========================================================
// 16. Event Listeners & Interactions
// =========================================================
function setupEventListeners() {
    // Autocomplete for Source & Destination
    setupSearchInput(sourceInput, sourceResults, clearSourceBtn, (place) => {
        setSourcePoint(place);
        map.flyTo([place.lat, place.lng], 15);
    });

    setupSearchInput(destInput, destResults, clearDestBtn, (place) => {
        setDestPoint(place);
        map.flyTo([place.lat, place.lng], 15);
        if (sourcePoint) calculateAndDrawRoute();
    });

    // Close dropdowns when clicking outside
    document.addEventListener("click", (e) => {
        if (!sourceInput.contains(e.target) && !sourceResults.contains(e.target)) {
            sourceResults.classList.remove("active");
        }
        if (!destInput.contains(e.target) && !destResults.contains(e.target)) {
            destResults.classList.remove("active");
        }
        if (!layerBtn.contains(e.target) && !layerMenu.contains(e.target)) {
            layerMenu.classList.remove("show");
        }
    });

    // Quick GPS Button
    useMyGpsBtn.addEventListener("click", () => {
        if (previousGpsCoord) {
            setSourcePoint({ lat: previousGpsCoord.lat, lng: previousGpsCoord.lng });
            map.flyTo([previousGpsCoord.lat, previousGpsCoord.lng], 16);
            showToast("Current GPS set as Start Point!", "success");
        } else {
            showToast("Acquiring GPS fix... Please wait.", "info");
        }
    });

    // Pick on Map buttons
    pickSourceBtn.addEventListener("click", () => {
        activePickingMode = "source";
        pickSourceBtn.classList.add("active");
        pickDestBtn.classList.remove("active");
        showToast("Click anywhere on map to set Start Point.", "info");
    });

    pickDestBtn.addEventListener("click", () => {
        activePickingMode = "dest";
        pickDestBtn.classList.add("active");
        pickSourceBtn.classList.remove("active");
        showToast("Click anywhere on map to set Destination.", "info");
    });

    // Swap Source & Destination
    swapPointsBtn.addEventListener("click", () => {
        if (!sourcePoint && !destPoint) return;

        const tempPoint = sourcePoint;
        sourcePoint = destPoint;
        destPoint = tempPoint;

        sourceInput.value = sourcePoint?.name || "";
        destInput.value = destPoint?.name || "";

        if (sourceMarker && sourcePoint) sourceMarker.setLatLng([sourcePoint.lat, sourcePoint.lng]);
        if (destMarker && destPoint) destMarker.setLatLng([destPoint.lat, destPoint.lng]);

        showToast("Start and Destination swapped!", "info");

        if (sourcePoint && destPoint) {
            calculateAndDrawRoute();
        }
    });

    // Calculate Route Button
    calculateRouteBtn.addEventListener("click", calculateAndDrawRoute);

    // Reset Route
    resetRouteBtn.addEventListener("click", () => {
        stopSimulation();
        if (routingControl) {
            map.removeControl(routingControl);
            routingControl = null;
        }
        if (sourceMarker) {
            map.removeLayer(sourceMarker);
            sourceMarker = null;
        }
        if (destMarker) {
            map.removeLayer(destMarker);
            destMarker = null;
        }
        sourcePoint = null;
        destPoint = null;
        sourceInput.value = "";
        destInput.value = "";
        clearSourceBtn.style.display = "none";
        clearDestBtn.style.display = "none";
        tripSummary.style.display = "none";
        directionsList.style.display = "none";
        directionsList.innerHTML = "";
        resetPickModes();
        showToast("Route and waypoints cleared.", "info");
    });

    // Route Panel Collapse
    collapsePanelBtn.addEventListener("click", () => {
        routePanel.classList.toggle("collapsed");
    });

    // Telemetry HUD Collapse
    hudCollapseBtn.addEventListener("click", () => {
        telemetryHud.classList.toggle("minimized");
    });

    // Directions Toggle
    toggleDirectionsBtn.addEventListener("click", () => {
        const isShown = directionsList.style.display === "flex";
        directionsList.style.display = isShown ? "none" : "flex";
        toggleDirectionsBtn.classList.toggle("open", !isShown);
    });

    // Simulation Controls
    startSimBtn.addEventListener("click", startSimulation);
    stopSimBtn.addEventListener("click", stopSimulation);
    simSpeedSelect.addEventListener("change", (e) => {
        simSpeedMultiplier = parseFloat(e.target.value);
    });

    // Vehicle Type Picker in HUD
    document.querySelectorAll(".vehicle-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".vehicle-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            selectedVehicleType = btn.getAttribute("data-vehicle");
            showToast(`Vehicle mode switched to ${selectedVehicleType.toUpperCase()}`, "info");

            // Refresh self marker icon if exists
            const selfId = Object.keys(userTrackers).find(id => isSelfUser(id)) || getLocalUserId();
            if (userTrackers[selfId]) {
                userTrackers[selfId].data.vehicleType = selectedVehicleType;
                const icon = createFleetBeaconIcon(
                    userTrackers[selfId].data.color,
                    selectedVehicleType,
                    userTrackers[selfId].currentBearing
                );
                userTrackers[selfId].marker.setIcon(icon);
            }
        });
    });

    // Camera Follow Mode Toggle
    cameraFollowBtn.addEventListener("click", () => {
        isCameraFollowEnabled = !isCameraFollowEnabled;
        cameraFollowBtn.classList.toggle("active", isCameraFollowEnabled);
        showToast(isCameraFollowEnabled ? "Camera Lock enabled (auto-following)" : "Camera Lock disabled", "info");
    });

    // Breadcrumb Trail Toggle
    breadcrumbToggleBtn.addEventListener("click", () => {
        isBreadcrumbEnabled = !isBreadcrumbEnabled;
        breadcrumbToggleBtn.classList.toggle("active", isBreadcrumbEnabled);

        // Add/remove polyline layers for all active trackers
        for (const id in userTrackers) {
            const tracker = userTrackers[id];
            if (isBreadcrumbEnabled) {
                tracker.polyline.addTo(map);
            } else {
                map.removeLayer(tracker.polyline);
            }
        }
        showToast(isBreadcrumbEnabled ? "Breadcrumb trails shown" : "Breadcrumb trails hidden", "info");
    });

    // Map Utilities
    recenterBtn.addEventListener("click", () => {
        if (previousGpsCoord) {
            map.flyTo([previousGpsCoord.lat, previousGpsCoord.lng], 16, { duration: 1.2 });
            showToast("Centered to your live location", "info");
        } else {
            showToast("Waiting for GPS position fix...", "info");
        }
    });

    fitRouteBtn.addEventListener("click", () => {
        if (sourcePoint && destPoint) {
            const bounds = L.latLngBounds([
                [sourcePoint.lat, sourcePoint.lng],
                [destPoint.lat, destPoint.lng]
            ]);
            map.fitBounds(bounds, { padding: [60, 60] });
        } else {
            showToast("Please calculate a route first.", "info");
        }
    });

    zoomInBtn.addEventListener("click", () => map.zoomIn());
    zoomOutBtn.addEventListener("click", () => map.zoomOut());

    // Layer Switcher Dropdown
    layerBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        layerMenu.classList.toggle("show");
    });

    document.querySelectorAll(".dropdown-item").forEach(item => {
        item.addEventListener("click", () => {
            const layerKey = item.getAttribute("data-layer");
            setMapLayer(layerKey);
            layerMenu.classList.remove("show");
            showToast(`Map style changed to ${item.textContent.trim()}`, "info");
        });
    });

    // Fleet Drawer Toggle
    toggleFleetBtn.addEventListener("click", () => {
        fleetDrawer.classList.toggle("show");
    });

    closeFleetBtn.addEventListener("click", () => {
        fleetDrawer.classList.remove("show");
    });

    // Dismiss Tips
    closeTipBtn.addEventListener("click", () => {
        tipsBanner.style.display = "none";
    });

    // API Keys & Server Settings Modal
    const settingsBtn = document.getElementById("settingsBtn");
    const settingsModal = document.getElementById("settingsModal");
    const closeSettingsBtn = document.getElementById("closeSettingsBtn");
    const maptilerKeyInput = document.getElementById("maptilerKeyInput");
    const locationiqKeyInput = document.getElementById("locationiqKeyInput");
    const serverUrlInput = document.getElementById("serverUrlInput");
    const saveKeysBtn = document.getElementById("saveKeysBtn");
    const resetKeysBtn = document.getElementById("resetKeysBtn");

    if (settingsBtn && settingsModal) {
        settingsBtn.addEventListener("click", () => {
            maptilerKeyInput.value = API_CONFIG.maptiler;
            locationiqKeyInput.value = API_CONFIG.locationiq;
            if (serverUrlInput) serverUrlInput.value = API_CONFIG.socketServer;
            settingsModal.style.display = "flex";
        });

        closeSettingsBtn.addEventListener("click", () => {
            settingsModal.style.display = "none";
        });

        settingsModal.addEventListener("click", (e) => {
            if (e.target === settingsModal) settingsModal.style.display = "none";
        });

        saveKeysBtn.addEventListener("click", () => {
            const mKey = maptilerKeyInput.value.trim();
            const lKey = locationiqKeyInput.value.trim();
            const sUrl = serverUrlInput ? serverUrlInput.value.trim() : "";

            API_CONFIG.maptiler = mKey;
            API_CONFIG.locationiq = lKey;
            API_CONFIG.socketServer = sUrl;

            if (mKey) localStorage.setItem("MAPTILER_API_KEY", mKey);
            else localStorage.removeItem("MAPTILER_API_KEY");

            if (lKey) localStorage.setItem("LOCATIONIQ_API_KEY", lKey);
            else localStorage.removeItem("LOCATIONIQ_API_KEY");

            if (sUrl) localStorage.setItem("TRACKPULSE_SERVER_URL", sUrl);
            else localStorage.removeItem("TRACKPULSE_SERVER_URL");

            setMapLayer(activeLayerKey || "dark");
            initSocket();
            settingsModal.style.display = "none";
            showToast("Settings saved & applied successfully! ✨", "success");
        });

        resetKeysBtn.addEventListener("click", () => {
            localStorage.removeItem("MAPTILER_API_KEY");
            localStorage.removeItem("LOCATIONIQ_API_KEY");
            localStorage.removeItem("TRACKPULSE_SERVER_URL");
            API_CONFIG.maptiler = "";
            API_CONFIG.locationiq = "";
            API_CONFIG.socketServer = "";
            maptilerKeyInput.value = "";
            locationiqKeyInput.value = "";
            if (serverUrlInput) serverUrlInput.value = "";
            setMapLayer(activeLayerKey || "dark");
            initSocket();
            settingsModal.style.display = "none";
            showToast("Reset to default settings!", "info");
        });
    }
}

// =========================================================
// 17. Run on DOM Load
// =========================================================
document.addEventListener("DOMContentLoaded", () => {
    initMap();
    initSocket();
    initGeolocation();
    setupEventListeners();
});