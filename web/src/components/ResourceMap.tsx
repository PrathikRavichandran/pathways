import { useEffect, useMemo, useRef } from "react";
import { motion, useReducedMotion } from "framer-motion";
import {
  MapContainer,
  Marker,
  Popup,
  TileLayer,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import type { ResourceCard } from "../api";
import { type Lang, t } from "../i18n";

// ---------------------------------------------------------------------------
// Marigold drop-pin icon. Built from inline SVG so we don't need to ship a
// raster asset alongside the bundle. The default Leaflet marker images
// reference 1x and 2x PNGs that break under Vite's asset pipeline anyway,
// so a divIcon is both prettier and simpler.
// ---------------------------------------------------------------------------

const PIN_SVG = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 44" width="32" height="44">
  <defs>
    <filter id="pin-shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="2" stdDeviation="1.5" flood-opacity="0.35" />
    </filter>
  </defs>
  <path
    d="M16 1c-7.18 0-13 5.82-13 13 0 9.5 13 28 13 28s13-18.5 13-28c0-7.18-5.82-13-13-13z"
    fill="#ECB13B"
    stroke="#FAF6E8"
    stroke-width="2"
    filter="url(#pin-shadow)"
  />
  <circle cx="16" cy="14" r="5" fill="#1F4A2C" />
</svg>
`.trim();

const pinIcon = L.divIcon({
  className: "pathways-pin",
  html: PIN_SVG,
  iconSize: [32, 44],
  iconAnchor: [16, 42],
  popupAnchor: [0, -36],
});

// ---------------------------------------------------------------------------
// Google Maps deep-link
// ---------------------------------------------------------------------------

function googleMapsUrl(name: string, lat: number, lon: number): string {
  // The Google Maps URL API documented at developers.google.com/maps/documentation/urls.
  // On iOS Safari + Android Chrome this URL opens the native Google Maps app
  // when installed, otherwise the maps.google.com web page. No detection
  // logic needed in our code.
  const query = encodeURIComponent(`${name} ${lat},${lon}`);
  return `https://www.google.com/maps/search/?api=1&query=${query}`;
}

// ---------------------------------------------------------------------------
// FitBounds: snaps the map to enclose every pin on first render.
// react-leaflet 5 keeps the map instance behind useMap(); call once per
// resource-set change.
// ---------------------------------------------------------------------------

function FitBounds({ pins }: { pins: PinnedCard[] }) {
  const map = useMap();
  const lastKey = useRef<string>("");

  useEffect(() => {
    if (!pins.length) return;
    const key = pins
      .map((p) => `${p.lat.toFixed(4)},${p.lon.toFixed(4)}`)
      .join("|");
    if (key === lastKey.current) return;
    lastKey.current = key;

    if (pins.length === 1) {
      map.setView([pins[0].lat, pins[0].lon], 13, { animate: true });
      return;
    }
    const bounds = L.latLngBounds(pins.map((p) => [p.lat, p.lon] as [number, number]));
    map.fitBounds(bounds, {
      padding: [32, 32],
      maxZoom: 14,
      animate: true,
    });
  }, [pins, map]);

  return null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type PinnedCard = ResourceCard & { lat: number; lon: number };

function pinnable(cards: ResourceCard[]): PinnedCard[] {
  return cards
    .filter((c): c is PinnedCard => c.lat != null && c.lon != null)
    .map((c) => ({ ...c, lat: Number(c.lat), lon: Number(c.lon) }));
}

export function ResourceMap({
  cards,
  lang,
}: {
  cards: ResourceCard[];
  lang: Lang;
}) {
  const reduce = useReducedMotion();
  const pins = useMemo(() => pinnable(cards), [cards]);

  // Self-gate: render nothing when no resource has coordinates. This is the
  // explicit contract documented in the plan; the call site doesn't need to
  // guard.
  if (pins.length === 0) return null;

  // Initial center is a fallback; FitBounds overrides on mount. Pick the
  // first pin so the map isn't visibly snapping from somewhere random.
  const center: [number, number] = [pins[0].lat, pins[0].lon];

  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={reduce ? false : { opacity: 1, y: 0 }}
      transition={{ duration: 0.36, ease: [0.16, 1, 0.3, 1] }}
      className="overflow-hidden rounded-2xl border border-cream-300 bg-cream-50 shadow-soft dark:border-ink-700 dark:bg-ink-800"
    >
      <div className="flex items-center justify-between px-4 py-2.5">
        <span className="text-xs font-semibold uppercase tracking-wider text-ink-500 dark:text-cream-300">
          {t("map_title", lang)}
        </span>
        <span className="text-[11px] text-ink-400 dark:text-cream-400">
          {pins.length} {pins.length === 1 ? "place" : "places"}
        </span>
      </div>
      <div className="h-[280px] w-full">
        <MapContainer
          center={center}
          zoom={11}
          scrollWheelZoom={false}
          style={{ height: "100%", width: "100%" }}
          // Avoid the map grabbing focus on mount; the chat input should
          // keep focus so the user can keep typing.
          attributionControl={false}
        >
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
            maxZoom={19}
          />
          <FitBounds pins={pins} />
          {pins.map((p) => (
            <Marker key={p.id} position={[p.lat, p.lon]} icon={pinIcon}>
              <Popup>
                <div className="min-w-[180px]">
                  <div className="text-sm font-semibold text-ink-700">
                    {p.name}
                  </div>
                  {p.distance_miles != null && (
                    <div className="mt-0.5 text-xs text-ink-400">
                      {`~${Math.round(p.distance_miles)} ${t("map_distance_suffix", lang)}`}
                    </div>
                  )}
                  <a
                    href={googleMapsUrl(p.name, p.lat, p.lon)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-forest-600 px-3 py-1.5 text-xs font-semibold text-cream-50 shadow-soft transition hover:bg-forest-700"
                  >
                    {t("map_open_in_google_maps", lang)}
                    <svg
                      width="11"
                      height="11"
                      viewBox="0 0 24 24"
                      fill="none"
                      aria-hidden="true"
                    >
                      <path
                        d="M14 3h7v7m0-7L10 14m-4-9H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </a>
                </div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      </div>
      <div className="px-4 py-1.5 text-[10px] text-ink-400 dark:text-cream-400">
        {t("map_attribution_note", lang)}
      </div>
    </motion.div>
  );
}
