# 🧭 WeatherRouter — Nordic Route Planner

A weather-aware route planning app for the Nordic countries. Plan driving routes between locations, see real-time weather forecasts along your route, get tire recommendations based on conditions, and receive warnings about seasonally closed Norwegian mountain passes.

![Status](https://img.shields.io/badge/status-V2.0-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Features

### 🗺️ Interactive Map & Routing

- **Interactive Leaflet map** centered on the Nordics (Norway, Sweden, Denmark, Finland, Iceland)
- **Click-to-place** start and end markers, or search for locations by name
- **Draggable markers** — reposition start/end by dragging, with automatic reverse geocoding
- **Multiple route alternatives** displayed in distinct colors with layered border/fill polylines
- **Route comparison** — click on a route card or polyline to highlight it; non-selected routes dim to 50% opacity
- **Autocomplete geocoding** with debounced search, keyboard navigation (↑/↓/Enter/Escape), and dropdown results

### 🌦️ Weather Forecasting

- **Weather sampling** at 15–20 points along each route (~25–30 km intervals)
- **Arrival-time-aware forecasts** — weather is fetched for the estimated time you'll pass each point, based on your departure time
- **Weather markers on the map** — pill-shaped markers showing weather emoji + temperature at each sample point
- **Detailed weather popups** — click any marker to see temperature, feels-like, elevation, arrival time, precipitation, snowfall, and wind speed
- **Mountain pass peak injection** — extra weather samples at the midpoint of detected mountain passes
- **Weather summary** on each route card showing temperature range and condition tags (❄️ Snow, 🌧️ Rain, 🧊 Frost)
- **Two weather providers** to choose from:
  - [Open-Meteo](https://open-meteo.com/) — free, no API key, batched requests (default)
  - [MET Norway / Yr.no](https://developer.yr.no/) — free, requires identification per [Terms of Service](https://developer.yr.no/doc/TermsOfService/), ideal for Nordic forecasts

### 🛞 Tire Recommendations

Automatic tire-type analysis based on weather conditions along your route:

| Verdict | Condition | Icon |
| --- | --- | --- |
| **Summer tires OK** | All temps > 7°C, no snow or ice | ✅ |
| **Winter tires advisory** | Temps between 3–7°C, or precipitation below 5°C | ⚠️ |
| **Winter tires recommended** | Any snow along route, or min temp < 3°C | 🟠 |
| **Winter tires required** | Freezing rain, sub-zero temps with precipitation, or >2 cm snow | 🔴 |

Recommendations include specifics: coldest temperature, distance/elevation where conditions are worst, and snow amounts.

### ⚠️ Mountain Pass Warnings

- Detects when routes pass through any of Norway's **85 seasonal mountain passes** (kolonnestrekning) using Vegvesen's NVDB database
- **Season-aware severity** — high in winter (Nov–Apr), medium in shoulder season (May/Oct), low in summer (Jun–Sep)
- **Visual closure overlay** — affected road stretches highlighted as colored dashed lines on the map (red/orange/yellow by severity)
- Warning banners displayed on route cards with severity-appropriate styling

### 🕐 Departure Time Picker

- **24-hour time format** via [Flatpickr](https://flatpickr.js.org/) date/time picker
- **15-minute increments** for easy time selection
- Defaults to current time + 1 hour, rounded to the nearest hour
- Departure time drives the weather forecast — forecasts are calculated for your estimated arrival at each point along the route

### 📱 Responsive Design

- **Desktop**: Sidebar (350px) + full-height map layout
- **Tablet** (≤ 860px): Sidebar narrows to 300px
- **Mobile** (≤ 640px): Vertical stack layout — sidebar on top (max 45vh), map below

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

### Alternative: Run with Docker Compose

A ready-to-use `docker-compose.yml` is included with every configuration option documented. To get started:

1. Edit `docker-compose.yml` — replace `YOUR_DOCKERHUB_USERNAME` with your Docker Hub username and adjust any settings
2. Run:

```sh
docker compose up
```

The app will be available at **http://localhost:8000**.

The compose file includes all available configuration with comments explaining each option:

```yaml
services:
  weatherrouter:
    image: YOUR_DOCKERHUB_USERNAME/weatherrouter:latest

    ports:
      - "8000:8000"

    environment:
      # ── Server ────────────────────────────────────────────
      # Host and port inside the container (you shouldn't need to change these)
      - HOST=0.0.0.0
      - PORT=8000

      # ── Routing provider ──────────────────────────────────
      # "osrm"   — Free, no API key, public demo server (default)
      # "google" — Paid, requires API key, real-time closures + traffic
      - ROUTING_PROVIDER=osrm
      - OSRM_BASE_URL=https://router.project-osrm.org
      # - GOOGLE_MAPS_API_KEY=your-google-maps-api-key

      # ── Weather provider ──────────────────────────────────
      # "open_meteo" — Free, no API key, batched requests (default)
      # "yr"         — Free, requires identification per TOS, ideal for Nordic
      - WEATHER_PROVIDER=open_meteo
      - OPEN_METEO_BASE_URL=https://api.open-meteo.com
      # - YR_CONTACT_INFO=github.com/youruser/weatherrouter contact@example.com

      # ── Geocoding ─────────────────────────────────────────
      - NOMINATIM_BASE_URL=https://nominatim.openstreetmap.org

    restart: unless-stopped
```

See the full `docker-compose.yml` in the repo for detailed comments on every option.

#### Run with `docker run` instead

If you prefer not to use Compose:

```sh
docker run -p 8000:8000 YOUR_DOCKERHUB_USERNAME/weatherrouter:latest
```

Pass configuration with `-e` flags or `--env-file`:

```sh
docker run -p 8000:8000 \
  -e WEATHER_PROVIDER=yr \
  -e YR_CONTACT_INFO="github.com/youruser/weatherrouter contact@example.com" \
  YOUR_DOCKERHUB_USERNAME/weatherrouter:latest
```

### Build and push to Docker Hub

A helper script is included for building, tagging, and pushing the image:

```sh
# Build only (auto-tags with date + git SHA)
./docker-build-push.sh

# Build with a specific version tag
./docker-build-push.sh --tag 2.1.0

# Build and push to Docker Hub
export DOCKER_USERNAME=yourusername
./docker-build-push.sh --tag 2.1.0 --push
```

This will push both `yourusername/weatherrouter:2.1.0` and `yourusername/weatherrouter:latest` to Docker Hub. Run `./docker-build-push.sh --help` for all options.

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

# Weather provider ("open_meteo" or "yr")
WEATHER_PROVIDER=open_meteo

# Open-Meteo API URL (default: public server)
OPEN_METEO_BASE_URL=https://api.open-meteo.com

# MET Norway (Yr.no) contact info — REQUIRED by their TOS when using "yr" provider
# Must be an app URL or email so MET can reach you if there are problems
# YR_CONTACT_INFO=github.com/youruser/weatherrouter contact@example.com

# Server bind address
HOST=0.0.0.0
PORT=8000
```

---

## Usage

1. **Set your start point** — click on the map or type a place name in the "Start location" field
2. **Set your end point** — click again on the map or type in the "End location" field
3. **Set departure time** — use the 24-hour time picker to choose when you're leaving (defaults to 1 hour from now)
4. **Click "Plan Route"** — the app calculates one or more route alternatives with weather and warnings
5. **Compare routes** — click on route cards in the sidebar or on the map polylines to highlight them
6. **Explore weather** — click weather markers on the map to see detailed forecasts at each point
7. **Check tire recommendations** — each route card shows whether you need winter or summer tires
8. **Drag markers** — reposition start/end by dragging the markers, then re-plan
9. **Clear** — reset everything with the Clear button to start over

---

## Project Structure

```
weatherrouter/
├── run.py                          # Entry point — starts the FastAPI server
├── Dockerfile                      # Multi-stage production Docker image
├── docker-compose.yml              # Docker Compose with all config options
├── docker-build-push.sh            # Build, tag, and push image to Docker Hub
├── .dockerignore                   # Files excluded from Docker build context
├── .env.example                    # Example environment variable configuration
├── backend/
│   ├── main.py                     # FastAPI app, CORS, static file serving
│   ├── config.py                   # Settings from env vars / .env
│   ├── requirements.txt            # Python dependencies
│   ├── models/
│   │   └── route.py                # Pydantic models (Route, Weather, Warnings, etc.)
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
│       └── weather/
│           ├── __init__.py         # Orchestrator + provider factory
│           ├── base.py             # Abstract WeatherClient base class
│           ├── sampler.py          # Route geometry → sample points with arrival times
│           ├── open_meteo.py       # Open-Meteo provider (free, batched requests)
│           ├── yr.py               # MET Norway / Yr.no provider (free, TOS-compliant)
│           └── analyzer.py         # Tire recommendation engine + weather summary
└── frontend/
    ├── index.html                  # Main HTML page (Leaflet, Flatpickr, app.js)
    ├── css/
    │   └── style.css               # Nordic-inspired responsive styling
    └── js/
        └── app.js                  # Map, markers, geocoding, routing, weather UI
```

---

## API Endpoints

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/routes` | Calculate routes with weather and warnings |
| GET | `/api/geocode` | Search for places by name (Nordic countries) |
| GET | `/api/providers` | List available routing providers and their status |

### POST `/api/routes`

**Request:**
```json
{
  "start": { "lat": 59.9139, "lng": 10.7522 },
  "end": { "lat": 60.3913, "lng": 5.3221 },
  "provider": "osrm",
  "departure_time": "2025-01-15T08:00:00Z"
}
```

The `provider` and `departure_time` fields are optional. If `departure_time` is omitted, weather forecasting is skipped. If `provider` is omitted, the configured default (OSRM) is used.

**Response:**
```json
{
  "routes": [
    {
      "geometry": { "type": "LineString", "coordinates": [[10.75, 59.91], "..."] },
      "distance_km": 462.5,
      "duration_minutes": 385.2,
      "summary": "E16, E39",
      "color": "#2196F3",
      "steps": [
        {
          "instruction": "Head north on E18",
          "distance_km": 2.3,
          "duration_minutes": 3.1,
          "start_location": { "lat": 59.91, "lng": 10.75 },
          "end_location": { "lat": 59.93, "lng": 10.75 }
        }
      ],
      "warnings": [
        {
          "type": "mountain_pass",
          "severity": "high",
          "title": "Mountain Pass: Suleskarvegen",
          "message": "This route passes through Suleskarvegen (FV450)...",
          "road_reference": "FV450",
          "geometry": { "type": "MultiLineString", "coordinates": ["..."] }
        }
      ],
      "weather": {
        "departure_time": "2025-01-15T08:00:00+00:00",
        "min_temperature_c": -5.2,
        "max_temperature_c": 3.1,
        "has_snow": true,
        "has_rain": false,
        "has_freezing_conditions": true,
        "tire_recommendation": {
          "verdict": "winter_required",
          "title": "Winter Tires Required",
          "message": "Snowy conditions with 4.2 cm total snowfall...",
          "icon": "🔴"
        },
        "weather_points": [
          {
            "location": { "lat": 59.95, "lng": 10.70 },
            "distance_km": 5.0,
            "elevation_m": 150.0,
            "arrival_time": "2025-01-15T08:15:00+00:00",
            "temperature_c": 1.2,
            "feels_like_c": -2.1,
            "precipitation_mm": 0.5,
            "snowfall_cm": 0.3,
            "weather_code": 71,
            "weather_description": "Slight snow fall",
            "weather_symbol": "❄️",
            "wind_speed_kmh": 15.0
          }
        ]
      }
    }
  ],
  "provider": "osrm"
}
```

---

## How It Works

### Weather Providers

The app supports swappable weather providers via a `WeatherClient` abstraction (same pattern as routing providers). Set `WEATHER_PROVIDER` in your `.env` to choose:

| Provider | Config value | API key | Batching | Best for |
| --- | --- | --- | --- | --- |
| Open-Meteo | `open_meteo` (default) | None | Single batched request | General use, simplest setup |
| MET Norway (Yr.no) | `yr` | None (but requires identification) | One request per point | Nordic-focused, high-quality Nordic data |

### Weather Forecasting Pipeline

1. **Sample** — The route geometry is divided into 15–20 evenly spaced points (~25–30 km apart). Arrival time at each point is estimated via linear interpolation of total duration from departure time.
2. **Peak injection** — If mountain pass warnings are detected, the midpoint of each pass geometry is injected as an extra sample point.
3. **Fetch** — A single batched request to Open-Meteo retrieves hourly forecasts for all sample points. The closest hourly slot to each arrival time is matched.
4. **Analyze** — Temperature, precipitation, snowfall, and WMO weather codes are evaluated to produce a tire recommendation and route weather summary.

### Mountain Pass Detection

1. On the first route request, the app fetches all Kolonnestrekning geometries from the NVDB API (cached in memory for 24 hours).
2. Each route is checked against these geometries using a fast **grid-based spatial index** — rasterizes both geometries into ~300m cells for O(N+M) proximity detection.
3. If the route passes within ~300m of a mountain pass, a warning is attached with severity based on the current month, the pass name and road reference, and GeoJSON geometry for map display.

### MET Norway (Yr.no) TOS Compliance

When using the `yr` provider, the app automatically complies with the [MET Norway Terms of Service](https://developer.yr.no/doc/TermsOfService/):

- **Identification** — Sends a `User-Agent` header with app name + your contact info (configured via `YR_CONTACT_INFO`). You **must** set this so MET can contact you if there are issues.
- **Caching** — Respects the `Expires` response header; cached responses are reused until expiry.
- **Conditional requests** — Uses `If-Modified-Since` with the `Last-Modified` header to avoid re-downloading unchanged data.
- **Rate limiting** — Caps concurrent requests at 10 with a small delay between requests (well under the 20 req/s limit).
- **Coordinate precision** — Truncates all coordinates to 4 decimal places as required.
- **Backend proxy** — All API calls go through the FastAPI backend (not directly from the browser), as recommended by MET.
- **Attribution** — Weather data from MET Norway is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). If you deploy this app publicly, you must give appropriate credit.

To enable:

```env
WEATHER_PROVIDER=yr
YR_CONTACT_INFO=github.com/youruser/weatherrouter contact@example.com
```

### Graceful Degradation

The app is designed to always return routes, even when optional services fail:

- **Weather fetch failure** → route returned without weather data (logged, not raised)
- **Road closure check failure** → route returned without warnings (logged, not raised)
- **Weather API timeout** → fallback weather points with zeroed values (both providers)
- **Yr.no stale cache** → serves cached data when the API is unreachable
- **Flatpickr CDN failure** → falls back to native browser date/time input

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
3. Register it in the `_PROVIDERS` dict in `backend/services/routing/__init__.py`

---

## Roadmap

### V2.1 — Real-Time Road Status

- [ ] Register for Vegvesen's DATEX II node to get real-time open/closed/convoy status
- [ ] Show live status on mountain pass warnings (🟢 Open / 🔴 Closed / 🟡 Convoy)
- [ ] Swedish and Finnish road closure data integration

### V2.2 — Enhanced Weather

- [ ] Color-coded route segments on the map (green → yellow → red) based on conditions
- [ ] Route comparison summary: "Route A is safe with summer tires, Route B requires winter tires"
- [ ] Road surface temperature data integration

### V3 — Future Ideas

- [ ] Elevation profiling and visualization
- [ ] Departure time optimization ("Leave at 11:00 instead of 08:00 to avoid icy conditions")
- [ ] Multi-day trip planning
- [ ] User accounts and saved routes
- [ ] Real-time road condition reports from additional Nordic road authorities

---

## Tech Stack

| Layer | Technology | Cost |
| --- | --- | --- |
| Backend | Python, FastAPI, httpx, Pydantic | Free |
| Frontend | Vanilla JS, Leaflet.js, Flatpickr | Free |
| Routing | OSRM (default) | Free |
| Routing | Google Directions (optional) | Paid |
| Weather | Open-Meteo API (default) | Free |
| Weather | MET Norway / Yr.no (optional) | Free (CC BY 4.0) |
| Road Closures | Vegvesen NVDB API | Free |
| Geocoding | OpenStreetMap Nominatim | Free |
| Map Tiles | OpenStreetMap | Free |

---

## Contributing

This is a personal project, but suggestions and ideas are welcome! Feel free to open an issue or PR.

## License

MIT