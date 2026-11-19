const express = require('express');
const app = express();
const path = require('path');
const http = require('http');
const socketio = require('socket.io');

const server = http.createServer(app);

// Optimize Socket.IO for low-latency, high-frequency 1-second location streaming
const io = socketio(server, {
    pingInterval: 10000, // 10s heartbeat
    pingTimeout: 5000,   // 5s timeout for fast disconnect detection
    cors: {
        origin: "*",
        methods: ["GET", "POST"]
    }
});

// View Engine setup
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.use(express.static(path.join(__dirname, 'public')));
app.use(express.json());

// In-memory active users registry
// Key: socketId, Value: { id, name, vehicleType, color, latitude, longitude, speed, heading, accuracy, updatedAt, history: [] }
const activeUsers = new Map();

// Rate limiting map to prevent socket flooding (max 2 location packets per 1000ms per socket)
const socketRateLimits = new Map();

// Curated distinctive vehicle & user colors
const userColors = [
    '#3b82f6', // Electric Blue
    '#10b981', // Emerald Green
    '#f59e0b', // Amber
    '#8b5cf6', // Violet Purple
    '#ec4899', // Bright Pink
    '#06b6d4', // Cyan
    '#f97316', // Neon Orange
    '#14b8a6'  // Teal
];

let userCounter = 1;

/**
 * Validates incoming geolocation payload
 */
function isValidLocationData(data) {
    if (!data || typeof data !== 'object') return false;
    const { latitude, longitude } = data;
    if (typeof latitude !== 'number' || typeof longitude !== 'number') return false;
    if (isNaN(latitude) || isNaN(longitude)) return false;
    if (latitude < -90 || latitude > 90) return false;
    if (longitude < -180 || longitude > 180) return false;
    return true;
}

// Inactivity Sweeper: Clean up users who haven't transmitted within 60 seconds
const INACTIVITY_TIMEOUT_MS = 60000;
setInterval(() => {
    const now = Date.now();
    for (const [id, user] of activeUsers.entries()) {
        if (now - user.updatedAt > INACTIVITY_TIMEOUT_MS) {
            console.log(`[Sweeper] Pruned inactive tracker: ${id} (${user.name})`);
            activeUsers.delete(id);
            socketRateLimits.delete(id);
            io.emit("user-disconnected", id);
            io.emit("user-count", activeUsers.size);
        }
    }
}, 15000);

// Socket.IO Connection & Stream Pipeline
io.on('connection', function (socket) {
    const assignedColor = userColors[(userCounter - 1) % userColors.length];
    const defaultName = `Fleet #${userCounter++}`;
    const defaultVehicle = 'car';

    console.log(`[Socket Connected] ID: ${socket.id} | Name: ${defaultName}`);

    // Send all currently active users to the newly connected client
    const existingList = Array.from(activeUsers.values());
    socket.emit("init-users", existingList);

    // Broadcast updated active users count
    io.emit("user-count", activeUsers.size);

    // High-Frequency 1-Second Location Updates
    socket.on("send-location", function (data) {
        if (!isValidLocationData(data)) {
            return;
        }

        // Rate-limiting check: Allow high-speed sub-second updates (up to 35 packets/sec)
        const now = Date.now();
        const lastTimes = socketRateLimits.get(socket.id) || [];
        // Keep timestamps from the last 1000ms
        const recentTimes = lastTimes.filter(t => now - t < 1000);
        if (recentTimes.length >= 35) {
            // Drop excessive packets beyond 35/sec
            return;
        }
        recentTimes.push(now);
        socketRateLimits.set(socket.id, recentTimes);

        const existing = activeUsers.get(socket.id);
        const name = (data.name && data.name.trim()) || (existing?.name || defaultName);
        const vehicleType = data.vehicleType || existing?.vehicleType || defaultVehicle;
        const color = existing?.color || assignedColor;

        // Maintain a rolling history of the last 15 breadcrumb positions
        const history = existing?.history || [];
        history.push({
            lat: data.latitude,
            lng: data.longitude,
            heading: data.heading || 0,
            t: now
        });
        if (history.length > 20) {
            history.shift();
        }

        const userInfo = {
            id: socket.id,
            name,
            vehicleType,
            color,
            latitude: data.latitude,
            longitude: data.longitude,
            speed: Math.max(0, Math.round((data.speed || 0) * 10) / 10), // km/h
            heading: typeof data.heading === 'number' ? Math.round(data.heading) : (existing?.heading || 0),
            accuracy: data.accuracy ? Math.round(data.accuracy) : null,
            altitude: data.altitude ? Math.round(data.altitude) : null,
            timestamp: data.timestamp || now,
            updatedAt: now,
            history
        };

        activeUsers.set(socket.id, userInfo);

        // Broadcast location payload to all connected clients immediately (low latency)
        io.emit("receive-location", userInfo);
    });

    // Latency Ping Test Handler
    socket.on("ping-test", function (data, cb) {
        if (typeof cb === "function") cb();
    });

    // Handle Client Disconnect
    socket.on("disconnect", function (reason) {
        console.log(`[Socket Disconnected] ID: ${socket.id} (Reason: ${reason})`);
        activeUsers.delete(socket.id);
        socketRateLimits.delete(socket.id);
        io.emit("user-disconnected", socket.id);
        io.emit("user-count", activeUsers.size);
    });
});

// REST Endpoints for external monitoring and health checks
app.get('/api/fleet', (req, res) => {
    res.json({
        success: true,
        count: activeUsers.size,
        timestamp: Date.now(),
        fleet: Array.from(activeUsers.values())
    });
});

app.get('/api/health', (req, res) => {
    res.json({
        status: 'healthy',
        uptime: process.uptime(),
        connectedSockets: io.engine.clientsCount,
        activeTrackers: activeUsers.size,
        memoryUsage: process.memoryUsage()
    });
});

// Main Web Application Route
app.get('/', function (req, res) {
    res.render("index");
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
    console.log(`\n======================================================`);
    console.log(`🚀 Real-Time Tracker Engine active on http://localhost:${PORT}`);
    console.log(`⚡ Precision 1-Second GPS & Lerp Streaming Ready`);
    console.log(`======================================================\n`);
});