import L from "leaflet";

/** Base maps for the layer switcher (Google-Maps style), all keyless. Shared by the dashboard
 * map and the in-vehicle tablet; the choice is remembered in localStorage. */
export type BaseId = "dark" | "standard" | "satellite" | "hybrid" | "terrain";
const BASE_KEY = "planb.basemap";
const OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const ESRI_ATTR = "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community";
const esri = (service: string) => `https://server.arcgisonline.com/ArcGIS/rest/services/${service}/MapServer/tile/{z}/{y}/{x}`;

/** The base maps of the layer switcher (Google-Maps style), all keyless. */
export function baseMaps(): Record<BaseId, { label: string; layer: L.Layer }> {
  const imagery = () => L.tileLayer(esri("World_Imagery"), { attribution: ESRI_ATTR, maxZoom: 19 });
  return {
    dark: { label: "🌙 Dark", layer: L.tileLayer(OSM, { attribution: OSM_ATTR, maxZoom: 19, className: "base-layer dark-layer" }) },
    standard: { label: "🗺 Standard", layer: L.tileLayer(OSM, { attribution: OSM_ATTR, maxZoom: 19, className: "base-layer" }) },
    satellite: { label: "🛰 Satellite", layer: imagery() },
    hybrid: {
      label: "🛰 Hybrid (satellite + labels)",
      layer: L.layerGroup([
        imagery(),
        L.tileLayer(esri("Reference/World_Transportation"), { maxZoom: 19 }),
        L.tileLayer(esri("Reference/World_Boundaries_and_Places"), { maxZoom: 19 }),
      ]),
    },
    terrain: {
      label: "⛰ Terrain",
      layer: L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
        subdomains: "abc",
        maxNativeZoom: 17,
        maxZoom: 19,
        attribution: `${OSM_ATTR}, SRTM | style &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)`,
      }),
    },
  };
}

export function savedBase(): BaseId {
  try {
    const v = localStorage.getItem(BASE_KEY);
    if (v === "dark" || v === "standard" || v === "satellite" || v === "hybrid" || v === "terrain") return v;
  } catch {
    // storage blocked: use the default
  }
  return "dark";
}

export function saveBase(id: BaseId): void {
  try {
    localStorage.setItem(BASE_KEY, id);
  } catch {
    // storage blocked (private window): the choice just isn't remembered
  }
}
