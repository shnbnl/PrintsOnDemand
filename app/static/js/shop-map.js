"use strict";

// Map discovery uses only server-rendered, student-visible shops. Order prices
// are still calculated by the existing server-side checkout service.
(() => {
  const canvas = document.querySelector("#shop-map");
  const data = document.querySelector("#map-shop-data");
  if (!canvas || !data) return;

  const shops = JSON.parse(data.textContent);
  const message = document.querySelector("#map-message");
  const locateButton = document.querySelector("#locate-me");
  const locationStatus = document.querySelector("#location-status");
  const choices = [...document.querySelectorAll("[data-shop-id]")];
  const panels = [...document.querySelectorAll("[data-shop-panel]")];
  const markers = new Map();
  let map;
  let userMarker;
  let loadTimer;

  function selectShop(id, moveMap = false, revealPanel = false) {
    const shop = shops.find((item) => String(item.id) === String(id));
    if (!shop) return;
    choices.forEach((choice) => {
      choice.setAttribute("aria-pressed", String(choice.dataset.shopId === String(id)));
    });
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.shopPanel !== String(id);
    });
    if (revealPanel && window.matchMedia("(max-width: 48rem)").matches) {
      document.querySelector(`[data-shop-panel="${shop.id}"]`)?.scrollIntoView({
        behavior: "smooth", block: "start",
      });
    }
    markers.forEach(({ pin, marker }, shopId) => {
      const selected = String(shopId) === String(id);
      pin.classList.toggle("is-selected", selected);
      marker.zIndex = selected ? 100 : 1;
    });
    if (moveMap && map) map.panTo(shop.position);
  }

  choices.forEach((choice) => {
    choice.addEventListener("click", () => selectShop(choice.dataset.shopId, true));
  });

  function showMapFailure() {
    clearTimeout(loadTimer);
    locateButton.disabled = true;
    const link = message.querySelector("a");
    const title = document.createElement("h2");
    title.textContent = "Map unavailable";
    const detail = document.createElement("p");
    detail.textContent = "The interactive map could not load. You can still choose a shop below.";
    message.replaceChildren(title, detail, link);
    message.hidden = false;
  }

  const apiKey = canvas.dataset.apiKey;
  const mapId = canvas.dataset.mapId;
  if (!apiKey || !mapId) return;

  window.gm_authFailure = showMapFailure;
  window.__podInitMap = async () => {
    try {
      const [{ Map: GoogleMap }, { AdvancedMarkerElement }] = await Promise.all([
        google.maps.importLibrary("maps"),
        google.maps.importLibrary("marker"),
      ]);
      const center = {
        lat: Number(canvas.dataset.centerLat),
        lng: Number(canvas.dataset.centerLng),
      };
      map = new GoogleMap(canvas, {
        center,
        zoom: 17,
        mapId,
        clickableIcons: false,
        mapTypeControl: false,
        streetViewControl: false,
      });

      shops.forEach((shop) => {
        const pin = document.createElement("span");
        pin.className = "map-pin";
        pin.textContent = "P";
        const marker = new AdvancedMarkerElement({
          map,
          position: shop.position,
          title: `${shop.name}${shop.is_demo ? " (demo location)" : ""}`,
          gmpClickable: true,
        });
        marker.append(pin);
        marker.addEventListener("gmp-click", () => selectShop(shop.id, false, true));
        markers.set(shop.id, { pin, marker });
      });
      if (shops.length) selectShop(shops[0].id);
      message.hidden = true;
      locateButton.disabled = false;
      clearTimeout(loadTimer);

      locateButton.addEventListener("click", () => {
        if (!navigator.geolocation) {
          locationStatus.textContent = "This browser does not support location sharing. The campus map remains available.";
          return;
        }
        locateButton.disabled = true;
        locationStatus.textContent = "Requesting your location…";
        navigator.geolocation.getCurrentPosition(
          ({ coords }) => {
            const position = { lat: coords.latitude, lng: coords.longitude };
            if (userMarker) userMarker.map = null;
            const pin = document.createElement("span");
            pin.className = "map-user-pin";
            pin.textContent = "You";
            userMarker = new AdvancedMarkerElement({
              map, position, title: "Your current location",
            });
            userMarker.append(pin);
            map.panTo(position);
            locationStatus.textContent = "Your current location is shown on this map only.";
            locateButton.disabled = false;
          },
          () => {
            locationStatus.textContent = "Location was unavailable or permission was denied. The campus map remains available.";
            locateButton.disabled = false;
          },
          { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
        );
      });
    } catch (error) {
      showMapFailure();
    }
  };

  const script = document.createElement("script");
  const url = new URL("https://maps.googleapis.com/maps/api/js");
  url.search = new URLSearchParams({
    key: apiKey, v: "weekly", loading: "async", callback: "__podInitMap",
  }).toString();
  script.src = url.toString();
  script.async = true;
  script.onerror = showMapFailure;
  document.head.append(script);
  loadTimer = window.setTimeout(() => {
    if (!map) showMapFailure();
  }, 15000);
})();
