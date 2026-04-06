# 🧭 WeatherRouter — Nordic Route Planner

A weather-aware route planning app for the Nordic countries. Plan driving routes between locations, get warnings about seasonally closed mountain passes, and — in a future release — get recommendations on whether you need winter or summer tires based on real-time weather conditions along your route.

![Status](https://img.shields.io/badge/status-V1.1-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Features (V1)

- 🗺️ **Interactive map** centered on the Nordics (Norway, Sweden, Denmark, Finland, Iceland)
- 📍 **Click-to-place** start and end markers, or search for locations by name
- 🛣️ **Multiple route alternatives** displayed in distinct colors
- 🔀 **Route comparison** — click on a route card or polyline to highlight it
- ⚠️ **Mountain pass warnings** — detects when routes pass through any of Norway's 85 seasonal mountain passes (kolonnestrekning) using Vegvesen's NVDB database
- 🏔️ **Season-aware severity** — warnings are high in winter (Nov–Apr), medium in shoulder season (May/Oct), low in summer
- 🗺️ **Visual closure overlay** — affected road stretches highlighted as dashed lines on the map
- 🔎 **Geocoding** powered by OpenStreetMap Nominatim (free, no API key)
- 🚗 **Routing** powered by OSRM (free, no API key) or Google Directions API (paid, supports real-time closures)
- 🔌 **Provider abstraction** — swap routing providers via config or API parameter

---

## Quick Start

### Prerequisites

- Python 3.11 or higher
- pip

### 1. Clone and install dependencies

```sh
cd weatherrouter
pip install -r backend/requirements.txt
```

### 2. Run the app

```sh
python run.py
```

The app will start at **http://localhost:8000**. Open it in your browser and start planning routes!

### 3. (Optional) Configure via environment variables

Create a `.env` file in the project root:

```env
# Default routing provider ("osrm" or "google")
ROUTING_PROVIDER=osrm

# Google Maps API key (enables the Google routing provider)
# GOOGLE_MAPS_API_KEY=your-key-here

# OSRM server URL (default: public demo server)
OSRM_BASE_URL=https://router.project-osrm.org

# Nominatim server URL (default: public OSM server)
NOMINATIM_BASE_URL=https://nominatim.openstreetmap.org

# Server bind address
HOST=0.0.0.0
PORT=8000
```

---

## Usage

1. **Set your start point** — click on the map or type a place name in the "Start location" field
2. **Set your end point** — click again on the map or type in the "End location" field
3. **Click "Plan Route"** — the app will calculate one or more route alternatives
4. **Compare routes** — click on route cards in the sidebar or on the map polylines to highlight them
5. **Drag markers** — reposition start/end by dragging the markers, then re-plan

---

## Project Structure

```
weatherrouter/
├── run.py                          # Entry point — starts the FastAPI server
├── backend/
│   ├── main.py                     # FastAPI app, CORS, static file serving
│   ├── config.py                   # Settings from env vars / .env
│   ├── requirements.txt            # Python dependencies
│   ├── models/
│   │   └── route.py                # Pydantic models (Route, RouteWarning, Coordinate, etc.)
│   ├── routers/
│   │   └── routes.py               # API endpoints (/api/routes, /api/geocode, etc.)
│   └── services/
│       ├── routing/
│       │   ├── base.py             # Abstract RoutingProvider base class
│       │   ├── osrm.py             # OSRM implementation (free, no API key)
│       │   └── google.py           # Google Directions API (requires API key)
│       ├── road_closures/
│       │   ├── nvdb.py             # NVDB API client — fetches mountain pass data
│       │   └── checker.py          # Route closure checker with grid-based spatial index
│       └── weather/                # Weather service (V2 placeholder)
└── frontend/
    ├── index.html                  # Main HTML page
    ├── css/
    │   └── style.css               # Nordic-inspired styling
    └── js/
        └── app.js                  # Map, markers, geocoding, routing UI
```

---

## API Endpoints

| Method | Path             | Description                                      |
| ------ | ---------------- | ------------------------------------------------ |
| POST   | `/api/routes`    | Calculate routes between two coordinates          |
| GET    | `/api/geocode`   | Search for places by name (Nordic countries)      |
| GET    | `/api/providers` | List available routing providers and their status |

### POST `/api/routes`

**Request:**
```json
{
  "start": { "lat": 59.9139, "lng": 10.7522 },
  "end": { "lat": 60.3913, "lng": 5.3221 },
  "provider": "osrm"
}
```

**Response:**
```json
{
  "routes": [
    {
      "geometry": { "type": "LineString", "coordinates": [[10.75, 59.91], ...] },
      "distance_km": 462.5,
      "duration_minutes": 385.2,
      "summary": "E16, E39",
      "color": "#2196F3",
      "steps": [...],
      "warnings": [
        {
          "type": "mountain_pass",
          "severity": "high",
          "title": "Mountain Pass: Suleskarvegen",
          "message": "This route passes through Suleskarvegen (FV450), a Norwegian mountain pass...",
          "road_reference": "FV450",
          "geometry": { "type": "MultiLineString", "coordinates": [...] }
        }
      ]
    }
  ],
  "provider": "osrm"
}
```

---

## Mountain Pass Detection

WeatherRouter cross-references every computed route against **85 Norwegian mountain pass / convoy stretches** (kolonnestrekning) from Vegvesen's National Road Database (NVDB).

**How it works:**

1. On the first route request, the app fetches all Kolonnestrekning geometries from the NVDB API (cached for 24 hours)
2. Each route is checked against these geometries using a fast grid-based spatial index
3. If the route passes within ~300m of a mountain pass, a warning is attached with:
   - **Severity** based on the current month: 🔴 high (Nov–Apr), 🟠 medium (May/Oct), 🟢 low (Jun–Sep)
   - **Pass name and road reference** (e.g., "Suleskarvegen (FV450)")
   - **GeoJSON geometry** of the affected stretch for map display
4. The frontend renders warnings as banners on route cards and dashed overlays on the map

**Example:** Planning Oslo → Bryne in winter will warn about Suleskarvegen (FV450), a mountain pass typically closed November–May.

---

## Routing Providers

The app uses a provider abstraction so you can plug in different routing engines:

### OSRM (default, free)

No configuration needed. Uses the public OSRM demo server. Note: OSRM does **not** account for real-time road closures — that's why we have the mountain pass detection layer.

### Google Directions API (paid, closure-aware)

Google's routing already accounts for real-time road closures, traffic, and seasonal restrictions. To enable:

```env
GOOGLE_MAPS_API_KEY=your-google-maps-api-key
ROUTING_PROVIDER=google
```

Get an API key at [Google Cloud Console](https://console.cloud.google.com/apis/credentials). You'll need the **Directions API** enabled.

### Adding a Custom Provider

1. Create a new class in `backend/services/routing/` that extends `RoutingProvider`
2. Implement `name`, `is_available()`, and `get_routes()`
3. Register it in the factory function in `backend/services/routing/__init__.py`

---

## Roadmap

### V1.2 — Real-Time Road Closures

- [ ] Register for Vegvesen's DATEX II node to get real-time open/closed/convoy status
- [ ] Show live status on mountain pass warnings (🟢 Open / 🔴 Closed / 🟡 Convoy)
- [ ] Swedish and Finnish road closure data integration

### V2 — Weather Analysis 🌦️

The core differentiator: overlay weather conditions along the route to answer **"Do I need winter tires?"**

- [ ] Sample weather at intervals along each route (every ~50 km)
- [ ] Estimate arrival time at each sample point based on departure time
- [ ] Query [Open-Meteo](https://open-meteo.com/) (free, no API key) for forecasts
- [ ] Analyze conditions: temperature, precipitation type, ice risk
- [ ] Tire recommendation engine with severity levels:
  - ✅ Summer tires OK
  - ⚠️ Winter tires advisory
  - 🟠 Winter tires recommended
  - 🔴 Winter tires required
- [ ] Color-code route segments on the map (green → yellow → red)
- [ ] Weather timeline: "At km 120 near Lillehammer, expect -2°C and snow at ~14:30"
- [ ] Compare routes: "Route A is safe with summer tires, Route B requires winter tires"

### V3 — Future Ideas

- [ ] Elevation profiling (mountain pass awareness)
- [ ] Road surface temperature data integration
- [ ] Departure time optimization ("Leave at 11:00 instead of 08:00 to avoid icy conditions")
- [ ] Multi-day trip planning
- [ ] Mobile-responsive design improvements
- [ ] User accounts and saved routes
- [ ] Real-time road condition reports (e.g., Statens vegvesen API for Norway)

---

## Tech Stack

| Layer            | Technology                     | Cost     |
| ---------------- | ------------------------------ | -------- |
| Backend          | Python, FastAPI, httpx         | Free     |
| Frontend         | Vanilla JS, Leaflet.js         | Free     |
| Routing          | OSRM (default)                 | Free     |
| Routing          | Google Directions (optional)   | Paid     |
| Road Closures    | Vegvesen NVDB API              | Free     |
| Geocoding        | OpenStreetMap Nominatim        | Free     |
| Weather          | Open-Meteo (V2)                | Free     |
| Map Tiles        | OpenStreetMap                  | Free     |

---

## Contributing

This is a personal project, but suggestions and ideas are welcome! Feel free to open an issue or PR.

## License

MIT