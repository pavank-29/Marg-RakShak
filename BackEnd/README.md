# MargRakshak AI — Backend Service & ML Risk Prediction Engine

FastAPI backend service and Machine Learning pipeline for the **AI-Based Dynamic Accident Hotspot Prediction and Multi-Route Navigation System**.

---

## 1. System Overview & Key Enhancements

MargRakshak AI enhances road safety navigation across Nashik City through:
1. **Dynamic ML Accident Hotspot Prediction**: Complements the 102 verified historical accident blackspots by evaluating candidate route corridors with a trained Machine Learning model to identify elevated-risk road segments in real-time.
2. **Two Feasible Alternative Routes**: Calculates and displays two distinct, navigable road options (Primary and Alternative) with individual distance, duration, safety scores, verified blackspot counts, and ML-predicted hotspot counts.
3. **Removal of Real-Time Traffic Dependencies**: Eliminates traffic flow overlays, congestion delay multipliers, and bottleneck node polling while preserving pure routing geometry, travel distance, and non-traffic duration.
4. **Transparent Risk Communication**: Clearly differentiates **Verified Historical Blackspots** (Red pins, accident/fatality history) from **ML-Predicted Risk Areas** (Violet pins with "ML" badge, confidence score, corridor factors, and model uncertainty disclaimer).

---

## 2. Directory Structure

```
BackEnd/
├── app/
│   ├── main.py                  # FastAPI entry point & CORS configuration
│   ├── core/
│   │   ├── config.py            # Pydantic Settings & environment variables
│   │   └── security.py          # JWT, bcrypt & authentication dependencies
│   ├── api/v1/                  # API routers & endpoints
│   │   ├── endpoints/
│   │   │   ├── route.py         # Route calculation & safety evaluation endpoints
│   │   │   ├── hotspots.py      # Unified blackspots & ML hotspot endpoints
│   │   │   ├── auth.py          # User registration, login & profile
│   │   │   ├── hazards.py       # Road hazard reporting & retrieval
│   │   │   └── tracking.py      # WebSocket telemetry & live tracking
│   ├── database/                # SQLAlchemy session & database initialization
│   ├── models/                  # SQLAlchemy ORM models (User, Hotspot, Hazard, etc.)
│   ├── schemas/                 # Pydantic request/response schemas
│   ├── services/
│   │   ├── routing_service.py   # Multi-route calculation (Direct & Alternative)
│   │   ├── hazard_service.py    # Road hazard management
│   │   └── hotspot_service.py   # Historical blackspot queries
│   └── ml/
│       ├── risk_model.py        # XGBoost & Random Forest model training with spatial CV
│       ├── route_risk.py        # Route corridor sampling & dynamic hotspot clustering
│       └── schemas.py           # ML training/prediction request & response models
├── models/risk_model/           # Persisted ML model artifact (.joblib) & metadata (.json)
├── Nashik_Unified_Blackspots.csv # Verified 102 Nashik accident blackspots dataset
├── tests/                       # Automated pytest test suite
└── requirements.txt             # Backend dependencies
```

---

## 3. Machine Learning Architecture & Training Pipeline

### Dataset
- **Primary Source**: `Nashik_Unified_Blackspots.csv` containing 102 verified, geocoded accident blackspots with historical collision counts, fatalities, radius, road type, and police station jurisdictions.
- **Synthesized Corridor Controls**: To prevent class imbalance and enable supervised risk estimation, the training dataset balances confirmed historical incidents with spatial road corridor segments across diverse speed limits, lighting, weather, and road conditions.

### Feature Engineering
The model extracts and normalizes the following features:
- `latitude`, `longitude` (spatial coordinates)
- `radius_meters` (corridor influence zone)
- `speed_limit` (posted road speed limit)
- `fatalities`, `historical_accidents`
- `spatial_density` (accidents per km² in the local cluster)
- `lighting` (`DAYLIGHT`, `NIGHT_LIT`, `NIGHT_UNLIT`, `DUSK_DAWN`)
- `road_condition` (`NORMAL`, `WET`, `DAMAGED`, `CONSTRUCTION`, `UNPAVED`)
- `weather` (`CLEAR`, `RAIN`, `FOG`, `STORM`)
- `vehicle_type` (`CAR`, `MOTORCYCLE`, `HEAVY_VEHICLE`, `BUS`)

### Spatial Cross-Validation Strategy
To prevent spatial autocorrelation leakage (where training and validation points from the same road segment leak geographic information), training uses a **Spatial Block Grouping Strategy**:
- Points are mapped into spatial grid blocks (~2.2 km resolution: `floor(lat / 0.02), floor(lng / 0.02)`), generating **358 spatial groups**.
- `GroupShuffleSplit` ensures entire spatial regions belong strictly to either the train or test set.

### Models & Validation Performance
- **Primary Model**: **XGBoost Classifier** with probability calibration and multi-class Brier loss tracking.
- **Baseline Model**: Random Forest Classifier.
- **Validation Metrics**:
  - Accuracy: **~83.9%**
  - F1-Score (macro): **~83.7%**
  - Multi-class Brier Score: **0.241**
  - Probability Calibration: Verified finite, monotonically increasing risk probabilities.

---

## 4. Dynamic Route Hotspot Generation Workflow

When a route is requested:
1. **Corridor Sub-Sampling**: The route polyline is divided into uniform 180-meter segments.
2. **Context Feature Injection**: Speed limits, vehicle type, and spatial density features are assigned to each segment.
3. **ML Inference**: The pre-loaded model predicts the risk level (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) and risk probability for each segment.
4. **Deduplication & Spatial Clustering**: Segments with risk scores $\ge 0.48$ or level `HIGH`/`CRITICAL` are clustered using Euclidean distance (300-meter threshold).
5. **Separation from Blackspots**: Predicted clusters located within 250 meters of any of the 102 verified blackspots are filtered out to avoid double-counting.
6. **Output**: The API returns:
   - `existing_blackspots`: Confirmed historical blackspots along the route.
   - `predicted_hotspots`: Dynamically predicted elevated-risk road segments with confidence scores, contributing factors, and uncertainty disclaimers.

---

## 5. Alternative Route Calculation

- **Service**: `RoutingService.calculate_routes(origin, destination, waypoints, ...)`
- **Multi-Route Generation**:
  - **Route 1 (Primary)**: Direct shortest navigable road path via OSRM.
  - **Route 2 (Alternative)**: Feasible Nashik arterial alternative generated via midpoint corridor deviation.
  - **Distinctness Constraints**: Overlap ratio $\le 0.75$, distance $\le 1.35\times$ primary, duration $\le 1.45\times$ primary.
  - If a viable second alternative cannot be found, the system gracefully falls back to displaying Route 1 without crashing or fabricating fake paths.

---

## 6. Removal of Real-Time Traffic Data

All real-time traffic dependencies have been cleanly removed from the navigation path:
- `traffic_segments` polyline color-coding (green/orange/red) removed.
- Congestion multipliers and delay additions removed from travel duration calculation.
- Background polling for traffic bottleneck nodes removed.
- Traffic toggle button and traffic intensity legend removed from frontend map.
- The routing engine continues to provide clean travel distance (`km`) and clean duration (`minutes`).

---

## 7. Setup & Execution

### Prerequisites
- Python 3.10+ (tested on Python 3.14)
- Node.js 18+ (for frontend)

### Backend Installation & Startup
```bash
# Navigate to backend directory
cd BackEnd

# Install dependencies
pip install -r requirements.txt

# Run database migrations / initialization
py -3.14 -m app.database.init_db

# Start backend server
py -3.14 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Model Retraining (Optional)
The model loads automatically from `models/risk_model/risk_model.joblib`. To retrain via Python or API:
```bash
# Trigger retrain via API:
curl -X POST http://127.0.0.1:8000/api/v1/hotspots/ml/retrain \
     -H "Content-Type: application/json" \
     -d "{\"algorithm\": \"XGBoost\", \"n_estimators\": 60}"
```

### Running Automated Tests
```bash
# Run complete test suite (71 test items)
py -3.14 -m pytest BackEnd/tests
```

### Frontend Startup
```bash
cd FrontEnd
npm install
npm run dev     # Starts Vite dev server at http://localhost:5173
npm run build   # Verifies production build
```
