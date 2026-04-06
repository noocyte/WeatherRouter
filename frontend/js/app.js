// =============================================================================
// WeatherRouter — Frontend Application
// Nordic-inspired weather-aware route planner
// =============================================================================

(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // Configuration
  // ---------------------------------------------------------------------------

  const CONFIG = {
    map: {
      center: [63.0, 15.0], // Centered on the Nordics
      zoom: 5,
      tileUrl: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
    api: {
      geocode: "/api/geocode",
      routes: "/api/routes",
    },
    nominatim: {
      reverseUrl: "https://nominatim.openstreetmap.org/reverse",
    },
    debounceMs: 500,
  };

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  const state = {
    map: null, // Leaflet map instance
    startMarker: null, // L.marker for start
    endMarker: null, // L.marker for end
    startCoords: null, // { lat, lng }
    endCoords: null, // { lat, lng }
    routeLayers: [], // Array of { border: L.polyline, line: L.polyline, data: {} }
    selectedRouteIndex: 0, // Currently selected route
    isLoading: false, // Loading state for route planning
    weatherMarkers: [], // L.marker array for weather icons on map
  };

  // ---------------------------------------------------------------------------
  // DOM References
  // ---------------------------------------------------------------------------

  const dom = {
    map: document.getElementById("map"),
    mapOverlay: document.getElementById("map-overlay"),
    startInput: document.getElementById("start-input"),
    endInput: document.getElementById("end-input"),
    startDropdown: document.getElementById("start-dropdown"),
    endDropdown: document.getElementById("end-dropdown"),
    planBtn: document.getElementById("plan-btn"),
    planBtnText: document.getElementById("plan-btn-text"),
    clearBtn: document.getElementById("clear-btn"),
    routesList: document.getElementById("routes-list"),
    toastContainer: document.getElementById("toast-container"),
    departureInput: document.getElementById("departure-input"),
    weatherAttribution: document.getElementById("weather-attribution"),
    mobileAttribution: document.getElementById("mobile-attribution"),
  };

  var departurePicker = null;

  // ---------------------------------------------------------------------------
  // Utility Helpers
  // ---------------------------------------------------------------------------

  /** Debounce a function by `ms` milliseconds. */
  function debounce(fn, ms) {
    let timer;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  /** Format distance in km nicely (e.g. "462.5 km"). */
  function formatDistance(km) {
    if (km < 1) return (km * 1000).toFixed(0) + " m";
    return km.toFixed(1) + " km";
  }

  /** Format duration in minutes to "Xh Ymin" style. */
  function formatDuration(minutes) {
    const h = Math.floor(minutes / 60);
    const m = Math.round(minutes % 60);
    if (h === 0) return m + "min";
    return h + "h " + (m < 10 ? "0" : "") + m + "min";
  }

  // ---------------------------------------------------------------------------
  // Toast Notifications
  // ---------------------------------------------------------------------------

  /**
   * Show a toast notification.
   * @param {string} message
   * @param {'info'|'success'|'error'} type
   */
  function showToast(message, type) {
    type = type || "info";
    var el = document.createElement("div");
    el.className = "toast " + type;
    el.textContent = message;
    dom.toastContainer.appendChild(el);

    // Remove after animation ends (~3.5s)
    setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 3800);
  }

  // ---------------------------------------------------------------------------
  // Custom Marker Icons
  // ---------------------------------------------------------------------------

  function createMarkerIcon(type) {
    var cssClass = type === "start" ? "start" : "end";
    return L.divIcon({
      className: "custom-marker",
      html:
        '<div class="marker-pin ' +
        cssClass +
        '">' +
        '<div class="marker-pin-inner"></div>' +
        "</div>",
      iconSize: [28, 28],
      iconAnchor: [14, 28],
      popupAnchor: [0, -30],
    });
  }

  // ---------------------------------------------------------------------------
  // Map Initialization
  // ---------------------------------------------------------------------------

  function initMap() {
    state.map = L.map(dom.map, {
      center: CONFIG.map.center,
      zoom: CONFIG.map.zoom,
      zoomControl: true,
    });

    L.tileLayer(CONFIG.map.tileUrl, {
      attribution: CONFIG.map.attribution,
      maxZoom: 18,
    }).addTo(state.map);

    // Map click handler — place start / end markers
    state.map.on("click", onMapClick);
  }

  // ---------------------------------------------------------------------------
  // Map Click — Place Markers
  // ---------------------------------------------------------------------------

  function onMapClick(e) {
    var latlng = e.latlng;

    if (!state.startMarker) {
      setStartMarker(latlng);
      reverseGeocode(latlng, dom.startInput);
    } else if (!state.endMarker) {
      setEndMarker(latlng);
      reverseGeocode(latlng, dom.endInput);
    } else {
      // Both exist — replace end marker
      setEndMarker(latlng);
      reverseGeocode(latlng, dom.endInput);
    }
  }

  function setStartMarker(latlng) {
    if (state.startMarker) {
      state.startMarker.setLatLng(latlng);
    } else {
      state.startMarker = L.marker(latlng, {
        icon: createMarkerIcon("start"),
        draggable: true,
      }).addTo(state.map);

      state.startMarker.on("dragend", function () {
        var pos = state.startMarker.getLatLng();
        state.startCoords = { lat: pos.lat, lng: pos.lng };
        reverseGeocode(pos, dom.startInput);
      });
    }
    state.startCoords = { lat: latlng.lat, lng: latlng.lng };
  }

  function setEndMarker(latlng) {
    if (state.endMarker) {
      state.endMarker.setLatLng(latlng);
    } else {
      state.endMarker = L.marker(latlng, {
        icon: createMarkerIcon("end"),
        draggable: true,
      }).addTo(state.map);

      state.endMarker.on("dragend", function () {
        var pos = state.endMarker.getLatLng();
        state.endCoords = { lat: pos.lat, lng: pos.lng };
        reverseGeocode(pos, dom.endInput);
      });
    }
    state.endCoords = { lat: latlng.lat, lng: latlng.lng };
  }

  // ---------------------------------------------------------------------------
  // Reverse Geocoding (Nominatim)
  // ---------------------------------------------------------------------------

  function reverseGeocode(latlng, inputEl) {
    var url =
      CONFIG.nominatim.reverseUrl +
      "?lat=" +
      latlng.lat +
      "&lon=" +
      latlng.lng +
      "&format=json";

    fetch(url, {
      headers: { "Accept-Language": "en" },
    })
      .then(function (res) {
        if (!res.ok) throw new Error("Reverse geocode failed");
        return res.json();
      })
      .then(function (data) {
        var name =
          data.display_name ||
          latlng.lat.toFixed(4) + ", " + latlng.lng.toFixed(4);
        // Use a shorter name if available
        if (data.address) {
          var a = data.address;
          name = a.city || a.town || a.village || a.hamlet || a.county || name;
          if (a.country) name += ", " + a.country;
        }
        inputEl.value = name;
      })
      .catch(function () {
        // Fallback to coords
        inputEl.value = latlng.lat.toFixed(4) + ", " + latlng.lng.toFixed(4);
      });
  }

  // ---------------------------------------------------------------------------
  // Forward Geocoding (via backend /api/geocode)
  // ---------------------------------------------------------------------------

  function forwardGeocode(query) {
    var url = CONFIG.api.geocode + "?q=" + encodeURIComponent(query);

    return fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error("Geocoding request failed");
        return res.json();
      })
      .then(function (data) {
        return data.results || [];
      });
  }

  // ---------------------------------------------------------------------------
  // Autocomplete Logic
  // ---------------------------------------------------------------------------

  function setupAutocomplete(inputEl, dropdownEl, onSelect) {
    var activeIndex = -1;

    var debouncedSearch = debounce(function () {
      var q = inputEl.value.trim();
      if (q.length < 2) {
        hideDropdown(dropdownEl);
        return;
      }

      forwardGeocode(q)
        .then(function (results) {
          if (results.length === 0) {
            hideDropdown(dropdownEl);
            return;
          }
          renderDropdown(dropdownEl, results, onSelect);
          activeIndex = -1;
        })
        .catch(function () {
          hideDropdown(dropdownEl);
        });
    }, CONFIG.debounceMs);

    inputEl.addEventListener("input", debouncedSearch);

    // Keyboard navigation
    inputEl.addEventListener("keydown", function (e) {
      var items = dropdownEl.querySelectorAll(".autocomplete-item");
      if (!items.length) return;

      if (e.key === "ArrowDown") {
        e.preventDefault();
        activeIndex = Math.min(activeIndex + 1, items.length - 1);
        highlightItem(items, activeIndex);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        highlightItem(items, activeIndex);
      } else if (e.key === "Enter" && activeIndex >= 0) {
        e.preventDefault();
        items[activeIndex].click();
      } else if (e.key === "Escape") {
        hideDropdown(dropdownEl);
      }
    });

    // Hide dropdown when clicking elsewhere
    document.addEventListener("click", function (e) {
      if (!inputEl.contains(e.target) && !dropdownEl.contains(e.target)) {
        hideDropdown(dropdownEl);
      }
    });
  }

  function renderDropdown(dropdownEl, results, onSelect) {
    dropdownEl.innerHTML = "";

    results.forEach(function (result) {
      var item = document.createElement("div");
      item.className = "autocomplete-item";
      item.innerHTML =
        '<span class="item-icon">&#x1F4CD;</span>' +
        '<span class="item-text">' +
        escapeHtml(result.name) +
        "</span>";

      item.addEventListener("click", function () {
        onSelect(result);
        hideDropdown(dropdownEl);
      });

      dropdownEl.appendChild(item);
    });

    dropdownEl.classList.add("visible");
  }

  function hideDropdown(dropdownEl) {
    dropdownEl.classList.remove("visible");
    dropdownEl.innerHTML = "";
  }

  function highlightItem(items, index) {
    items.forEach(function (item, i) {
      item.classList.toggle("active", i === index);
    });
    // Scroll into view
    if (items[index]) {
      items[index].scrollIntoView({ block: "nearest" });
    }
  }

  function escapeHtml(text) {
    var div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  // ---------------------------------------------------------------------------
  // Route Planning
  // ---------------------------------------------------------------------------

  function planRoute() {
    // Validate
    if (!state.startCoords || !state.endCoords) {
      showToast("Please set both start and end locations.", "error");
      return;
    }

    if (state.isLoading) return;

    setLoading(true);

    var body = {
      start: state.startCoords,
      end: state.endCoords,
      departure_time:
        departurePicker && departurePicker.selectedDates.length
          ? departurePicker.selectedDates[0].toISOString()
          : dom.departureInput.value
            ? new Date(dom.departureInput.value).toISOString()
            : null,
    };

    fetch(CONFIG.api.routes, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (res) {
        if (!res.ok)
          throw new Error("Route planning failed (HTTP " + res.status + ")");
        return res.json();
      })
      .then(function (data) {
        if (!data.routes || data.routes.length === 0) {
          showToast("No routes found between these locations.", "error");
          return;
        }
        displayRoutes(data.routes);
        showToast("Found " + data.routes.length + " route(s).", "success");
      })
      .catch(function (err) {
        showToast(
          err.message || "Failed to plan route. Please try again.",
          "error",
        );
      })
      .finally(function () {
        setLoading(false);
      });
  }

  function setLoading(loading) {
    state.isLoading = loading;

    if (loading) {
      dom.planBtn.disabled = true;
      dom.planBtnText.textContent = "";
      var spinner = document.createElement("span");
      spinner.className = "spinner";
      dom.planBtnText.appendChild(spinner);
      var text = document.createTextNode(" Planning\u2026");
      dom.planBtnText.appendChild(text);
      dom.mapOverlay.classList.add("visible");
    } else {
      dom.planBtn.disabled = false;
      dom.planBtnText.textContent = "Plan Route";
      dom.mapOverlay.classList.remove("visible");
    }
  }

  // ---------------------------------------------------------------------------
  // Route Display
  // ---------------------------------------------------------------------------

  function displayRoutes(routes) {
    // Clear existing route layers
    clearRoutes();

    state.selectedRouteIndex = 0;

    // Draw each route on the map
    routes.forEach(function (route, index) {
      var coords = geoJsonCoordsToLatLng(route.geometry.coordinates);
      var color = route.color || "#2196F3";

      // White border polyline (drawn first, underneath)
      var borderLine = L.polyline(coords, {
        color: "#ffffff",
        weight: 8,
        opacity: 0.9,
        lineCap: "round",
        lineJoin: "round",
      }).addTo(state.map);

      // Colored route polyline
      var routeLine = L.polyline(coords, {
        color: color,
        weight: 5,
        opacity: index === 0 ? 1.0 : 0.5,
        lineCap: "round",
        lineJoin: "round",
      }).addTo(state.map);

      // Store reference
      var routeLayer = {
        border: borderLine,
        line: routeLine,
        data: route,
        index: index,
      };
      state.routeLayers.push(routeLayer);

      // Hover interaction on map polyline
      routeLine.on("mouseover", function () {
        highlightRoute(index, false);
      });

      routeLine.on("mouseout", function () {
        highlightRoute(state.selectedRouteIndex, false);
      });

      routeLine.on("click", function () {
        selectRoute(index);
      });
    });

    // Bring first route to front
    if (state.routeLayers.length > 0) {
      bringRouteToFront(0);
    }

    // Fit map to first route bounds
    if (state.routeLayers.length > 0) {
      state.map.fitBounds(state.routeLayers[0].line.getBounds(), {
        padding: [40, 40],
      });
    }

    // Draw warning geometry overlays
    routes.forEach(function (route, index) {
      if (!route.warnings || route.warnings.length === 0) return;
      var warningLayers = [];
      route.warnings.forEach(function (warning) {
        if (!warning.geometry) return;
        var warningColor =
          warning.severity === "high"
            ? "#ea4335"
            : warning.severity === "medium"
              ? "#FF9800"
              : "#FBBC04";
        // Handle both LineString and MultiLineString
        var coordSets =
          warning.geometry.type === "MultiLineString"
            ? warning.geometry.coordinates
            : [warning.geometry.coordinates];
        coordSets.forEach(function (coords) {
          var latLngs = geoJsonCoordsToLatLng(coords);
          var warningLine = L.polyline(latLngs, {
            color: warningColor,
            weight: 6,
            opacity: 0.8,
            dashArray: "10, 8",
            lineCap: "round",
          }).addTo(state.map);
          warningLayers.push(warningLine);
        });
      });
      // Store warning layers alongside the route layer
      if (state.routeLayers[index]) {
        state.routeLayers[index].warningLayers = warningLayers;
      }
    });

    // Draw weather markers on the map for the first (selected) route
    clearWeatherMarkers();
    if (routes[0] && routes[0].weather && routes[0].weather.weather_points) {
      drawWeatherMarkers(routes[0].weather.weather_points);
    }

    // Update weather attribution based on the provider
    updateWeatherAttribution(routes);

    // Render route cards in sidebar
    renderRouteCards(routes);
  }

  /** Convert GeoJSON [lng, lat] to Leaflet [lat, lng]. */
  function geoJsonCoordsToLatLng(coordinates) {
    return coordinates.map(function (coord) {
      return [coord[1], coord[0]];
    });
  }

  function clearRoutes() {
    state.routeLayers.forEach(function (rl) {
      state.map.removeLayer(rl.border);
      state.map.removeLayer(rl.line);
      if (rl.warningLayers) {
        rl.warningLayers.forEach(function (wl) {
          state.map.removeLayer(wl);
        });
      }
    });
    state.routeLayers = [];
    state.selectedRouteIndex = 0;
  }

  /**
   * On mobile screens (≤640px), reduce the number of weather markers shown
   * while always preserving peaks (mountain passes), temperature extremes,
   * notable weather events, and the start/end of the route.
   */
  function thinWeatherPointsForMobile(weatherPoints) {
    if (window.innerWidth > 640 || weatherPoints.length <= 8) {
      return weatherPoints;
    }

    var targetCount = 8;
    var kept = new Set();

    // Always keep first and last points
    kept.add(0);
    kept.add(weatherPoints.length - 1);

    // Always keep peaks, notable weather, and find temperature extremes
    var minTempIdx = 0;
    var maxTempIdx = 0;
    weatherPoints.forEach(function (wp, i) {
      if (wp.is_peak) kept.add(i);
      if (wp.snowfall_cm > 0) kept.add(i);
      if (wp.temperature_c <= 0 && wp.precipitation_mm > 0) kept.add(i);
      if (wp.temperature_c < weatherPoints[minTempIdx].temperature_c)
        minTempIdx = i;
      if (wp.temperature_c > weatherPoints[maxTempIdx].temperature_c)
        maxTempIdx = i;
    });
    kept.add(minTempIdx);
    kept.add(maxTempIdx);

    // Fill remaining slots evenly from the leftover points
    var remaining = targetCount - kept.size;
    if (remaining > 0) {
      var candidates = [];
      for (var i = 0; i < weatherPoints.length; i++) {
        if (!kept.has(i)) candidates.push(i);
      }
      var step = candidates.length / (remaining + 1);
      for (var j = 1; j <= remaining && j * step < candidates.length; j++) {
        kept.add(candidates[Math.round(j * step)]);
      }
    }

    // Return kept points in original (distance) order
    var result = [];
    weatherPoints.forEach(function (wp, i) {
      if (kept.has(i)) result.push(wp);
    });
    return result;
  }

  function drawWeatherMarkers(weatherPoints) {
    clearWeatherMarkers();
    weatherPoints = thinWeatherPointsForMobile(weatherPoints);
    weatherPoints.forEach(function (wp) {
      var icon = L.divIcon({
        className: "weather-marker",
        html:
          '<div class="weather-marker-inner">' +
          '<span class="weather-marker-symbol">' +
          wp.weather_symbol +
          "</span>" +
          '<span class="weather-marker-temp">' +
          Math.round(wp.temperature_c) +
          "°</span>" +
          "</div>",
        iconSize: [50, 36],
        iconAnchor: [25, 18],
      });

      var marker = L.marker([wp.location.lat, wp.location.lng], {
        icon: icon,
        interactive: true,
        zIndexOffset: 500,
      }).addTo(state.map);

      // Build popup content
      var arrivalStr = "";
      try {
        var d = new Date(wp.arrival_time);
        arrivalStr = d.toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        });
      } catch (e) {
        arrivalStr = wp.arrival_time;
      }

      var popupHtml =
        '<div class="weather-popup">' +
        '<div class="weather-popup-header">' +
        '<span class="weather-popup-symbol">' +
        wp.weather_symbol +
        "</span>" +
        '<span class="weather-popup-desc">' +
        escapeHtml(wp.weather_description) +
        "</span>" +
        "</div>" +
        '<div class="weather-popup-details">' +
        "<div>🌡️ " +
        wp.temperature_c.toFixed(1) +
        "°C" +
        (wp.feels_like_c != null
          ? " (feels " + wp.feels_like_c.toFixed(1) + "°C)"
          : "") +
        "</div>" +
        "<div>⛰️ Elevation: " +
        Math.round(wp.elevation_m) +
        " m</div>" +
        "<div>🕐 Arrival: ~" +
        arrivalStr +
        "</div>" +
        "<div>📍 " +
        wp.distance_km.toFixed(0) +
        " km from start</div>" +
        (wp.precipitation_mm > 0
          ? "<div>🌧️ Precip: " + wp.precipitation_mm.toFixed(1) + " mm</div>"
          : "") +
        (wp.snowfall_cm > 0
          ? "<div>❄️ Snow: " + wp.snowfall_cm.toFixed(1) + " cm</div>"
          : "") +
        "<div>💨 Wind: " +
        wp.wind_speed_kmh.toFixed(0) +
        " km/h</div>" +
        "</div>" +
        "</div>";

      marker.bindPopup(popupHtml, {
        maxWidth: 220,
        className: "weather-popup-container",
      });
      state.weatherMarkers.push(marker);
    });
  }

  function clearWeatherMarkers() {
    state.weatherMarkers.forEach(function (m) {
      state.map.removeLayer(m);
    });
    state.weatherMarkers = [];
  }

  // ---------------------------------------------------------------------------
  // Route Cards (Sidebar)
  // ---------------------------------------------------------------------------

  function renderRouteCards(routes) {
    dom.routesList.innerHTML = "";

    routes.forEach(function (route, index) {
      var card = document.createElement("div");
      card.className = "route-card" + (index === 0 ? " selected" : " dimmed");
      card.style.borderLeftColor = route.color || "#2196F3";
      card.dataset.index = index;

      // Determine highest severity for badge
      var hasWarnings = route.warnings && route.warnings.length > 0;
      var highestSeverity = "";
      if (hasWarnings) {
        var severityOrder = { high: 3, medium: 2, low: 1 };
        route.warnings.forEach(function (w) {
          if (
            !highestSeverity ||
            (severityOrder[w.severity] || 0) >
              (severityOrder[highestSeverity] || 0)
          ) {
            highestSeverity = w.severity;
          }
        });
      }

      var badgeHtml = "";
      if (hasWarnings && highestSeverity === "high") {
        badgeHtml =
          ' <span class="route-warning-badge route-warning-badge--high">&#x26A0;&#xFE0F; Warning</span>';
      } else if (hasWarnings && highestSeverity === "medium") {
        badgeHtml =
          ' <span class="route-warning-badge route-warning-badge--medium">&#x26A0;&#xFE0F; Caution</span>';
      }

      card.innerHTML =
        '<div class="route-card-header">' +
        '<div class="route-card-title">' +
        '<span class="route-color-dot" style="background:' +
        (route.color || "#2196F3") +
        '"></span>' +
        "Route " +
        (index + 1) +
        badgeHtml +
        "</div>" +
        "</div>" +
        '<div class="route-card-meta">' +
        "<span>&#x1F4CF; " +
        formatDistance(route.distance_km) +
        "</span>" +
        "<span>&#x23F1;&#xFE0F; " +
        formatDuration(route.duration_minutes) +
        "</span>" +
        "</div>" +
        (route.summary
          ? '<div class="route-card-summary">via ' +
            escapeHtml(route.summary) +
            "</div>"
          : "");

      // Append warning banners
      if (hasWarnings) {
        route.warnings.forEach(function (warning) {
          card.innerHTML +=
            '<div class="route-warning route-warning--' +
            (warning.severity || "medium") +
            '">' +
            '<span class="route-warning-icon">&#x26A0;&#xFE0F;</span>' +
            '<div class="route-warning-content">' +
            '<div class="route-warning-title">' +
            escapeHtml(warning.title || "") +
            "</div>" +
            '<div class="route-warning-message">' +
            escapeHtml(warning.message || "") +
            "</div>" +
            "</div>" +
            "</div>";
        });
      }

      // Weather / Tire recommendation
      if (route.weather && route.weather.tire_recommendation) {
        var rec = route.weather.tire_recommendation;
        var verdictClass = "tire-" + rec.verdict.replace(/_/g, "-");
        card.innerHTML +=
          '<div class="tire-recommendation ' +
          verdictClass +
          '">' +
          '<div class="tire-recommendation-header">' +
          '<span class="tire-recommendation-icon">' +
          rec.icon +
          "</span>" +
          '<span class="tire-recommendation-title">' +
          escapeHtml(rec.title) +
          "</span>" +
          "</div>" +
          '<div class="tire-recommendation-message">' +
          escapeHtml(rec.message) +
          "</div>" +
          "</div>";
      }

      // Sunglasses advisory
      if (route.weather && route.weather.sunglasses_advisory) {
        var sun = route.weather.sunglasses_advisory;
        var sunClass = sun.needed ? "sunglasses-needed" : "sunglasses-ok";
        card.innerHTML +=
          '<div class="sunglasses-advisory ' +
          sunClass +
          '">' +
          '<div class="sunglasses-advisory-header">' +
          '<span class="sunglasses-advisory-icon">' +
          sun.icon +
          "</span>" +
          '<span class="sunglasses-advisory-title">' +
          escapeHtml(sun.title) +
          "</span>" +
          "</div>" +
          '<div class="sunglasses-advisory-message">' +
          escapeHtml(sun.message) +
          "</div>" +
          "</div>";
      }

      if (route.weather && route.weather.tire_recommendation) {
        // Weather summary bar
        var w = route.weather;
        card.innerHTML +=
          '<div class="weather-summary">' +
          "<span>🌡️ " +
          w.min_temperature_c.toFixed(0) +
          "° to " +
          w.max_temperature_c.toFixed(0) +
          "°</span>" +
          (w.has_snow ? "<span>❄️ Snow</span>" : "") +
          (w.has_rain ? "<span>🌧️ Rain</span>" : "") +
          (w.has_freezing_conditions ? "<span>🧊 Frost</span>" : "") +
          "</div>";
      }

      // Click to select
      card.addEventListener("click", function () {
        selectRoute(index);
      });

      // Hover to highlight
      card.addEventListener("mouseenter", function () {
        highlightRoute(index, false);
      });

      card.addEventListener("mouseleave", function () {
        highlightRoute(state.selectedRouteIndex, false);
      });

      dom.routesList.appendChild(card);
    });
  }

  // ---------------------------------------------------------------------------
  // Route Selection & Highlighting
  // ---------------------------------------------------------------------------

  function selectRoute(index) {
    state.selectedRouteIndex = index;
    highlightRoute(index, true);
    bringRouteToFront(index);
    // Update weather markers for the selected route
    var rl = state.routeLayers[index];
    if (rl && rl.data && rl.data.weather && rl.data.weather.weather_points) {
      drawWeatherMarkers(rl.data.weather.weather_points);
    } else {
      clearWeatherMarkers();
    }
  }

  /**
   * Highlight a specific route: full opacity on the target, dimmed on others.
   * If `updateCards` is true, also update sidebar card classes.
   */
  function highlightRoute(index, updateCards) {
    state.routeLayers.forEach(function (rl, i) {
      var isTarget = i === index;
      rl.line.setStyle({ opacity: isTarget ? 1.0 : 0.5 });
      rl.border.setStyle({ opacity: isTarget ? 0.9 : 0.4 });
      if (rl.warningLayers) {
        rl.warningLayers.forEach(function (wl) {
          wl.setStyle({ opacity: isTarget ? 0.8 : 0.3 });
        });
      }
    });

    if (updateCards) {
      var cards = dom.routesList.querySelectorAll(".route-card");
      cards.forEach(function (card, i) {
        card.classList.toggle("selected", i === index);
        card.classList.toggle("dimmed", i !== index);
      });
    }
  }

  /** Bring a route's polylines to the front of the map. */
  function bringRouteToFront(index) {
    var rl = state.routeLayers[index];
    if (rl) {
      rl.border.bringToFront();
      rl.line.bringToFront();
      if (rl.warningLayers) {
        rl.warningLayers.forEach(function (wl) {
          wl.bringToFront();
        });
      }
    }
    // Keep markers on top
    if (state.startMarker) state.startMarker.setZIndexOffset(1000);
    if (state.endMarker) state.endMarker.setZIndexOffset(1000);
    // Keep weather markers visible
    state.weatherMarkers.forEach(function (m) {
      m.setZIndexOffset(800);
    });
  }

  // ---------------------------------------------------------------------------
  // Clear Everything
  // ---------------------------------------------------------------------------

  function setAttributionHtml(html) {
    if (dom.weatherAttribution) dom.weatherAttribution.innerHTML = html;
    if (dom.mobileAttribution) dom.mobileAttribution.innerHTML = html;
  }

  function updateWeatherAttribution(routes) {
    // Find the first route with weather data to determine the provider
    var provider = "";
    for (var i = 0; i < routes.length; i++) {
      if (routes[i].weather && routes[i].weather.weather_provider) {
        provider = routes[i].weather.weather_provider;
        break;
      }
    }

    if (
      provider.toLowerCase().indexOf("yr") !== -1 ||
      provider.toLowerCase().indexOf("met norway") !== -1
    ) {
      setAttributionHtml(
        "\uD83C\uDF26\uFE0F Weather data by " +
          '<a href="https://www.met.no/en" target="_blank" rel="noopener">MET Norway</a>' +
          " / " +
          '<a href="https://developer.yr.no/" target="_blank" rel="noopener">Yr.no</a>' +
          ', licensed under <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC BY 4.0</a>',
      );
    } else if (provider) {
      setAttributionHtml(
        "\uD83C\uDF26\uFE0F Weather data by " +
          '<a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo</a>',
      );
    }
  }

  function clearAll() {
    // Remove markers
    if (state.startMarker) {
      state.map.removeLayer(state.startMarker);
      state.startMarker = null;
    }
    if (state.endMarker) {
      state.map.removeLayer(state.endMarker);
      state.endMarker = null;
    }
    state.startCoords = null;
    state.endCoords = null;

    // Clear inputs
    dom.startInput.value = "";
    dom.endInput.value = "";

    // Remove routes
    clearWeatherMarkers();
    clearRoutes();
    dom.routesList.innerHTML =
      '<div class="routes-empty">' +
      '<div class="empty-icon">&#x1F5FA;&#xFE0F;</div>' +
      "<div>Set start & end points to discover routes</div>" +
      "</div>";

    // Reset map view
    state.map.setView(CONFIG.map.center, CONFIG.map.zoom);

    // Reset weather attribution to default
    setAttributionHtml(
      "\uD83C\uDF26\uFE0F Weather data by " +
        '<a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo</a>' +
        " &middot; Click map to set points",
    );
  }

  // ---------------------------------------------------------------------------
  // Event Binding
  // ---------------------------------------------------------------------------

  function bindEvents() {
    // Plan route button
    dom.planBtn.addEventListener("click", planRoute);

    // Clear button
    dom.clearBtn.addEventListener("click", clearAll);

    // Autocomplete for start input
    setupAutocomplete(dom.startInput, dom.startDropdown, function (result) {
      var latlng = L.latLng(result.lat, result.lng);
      setStartMarker(latlng);
      dom.startInput.value = result.name;
      state.map.setView(latlng, Math.max(state.map.getZoom(), 10));
    });

    // Autocomplete for end input
    setupAutocomplete(dom.endInput, dom.endDropdown, function (result) {
      var latlng = L.latLng(result.lat, result.lng);
      setEndMarker(latlng);
      dom.endInput.value = result.name;
      state.map.setView(latlng, Math.max(state.map.getZoom(), 10));
    });
  }

  // ---------------------------------------------------------------------------
  // Initialization
  // ---------------------------------------------------------------------------

  function init() {
    // Set default departure time to now + 1 hour, rounded to nearest hour
    var now = new Date();
    now.setHours(now.getHours() + 1, 0, 0, 0);

    // Initialize flatpickr with 24-hour time format
    if (typeof flatpickr !== "undefined") {
      departurePicker = flatpickr(dom.departureInput, {
        enableTime: true,
        time_24hr: true,
        dateFormat: "Y-m-d H:i",
        defaultDate: now,
        minuteIncrement: 15,
      });
    } else {
      // Fallback to native input if flatpickr is not loaded
      var localIso =
        now.getFullYear() +
        "-" +
        String(now.getMonth() + 1).padStart(2, "0") +
        "-" +
        String(now.getDate()).padStart(2, "0") +
        "T" +
        String(now.getHours()).padStart(2, "0") +
        ":00";
      dom.departureInput.value = localIso;
    }

    initMap();
    bindEvents();
  }

  // Start the application when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
