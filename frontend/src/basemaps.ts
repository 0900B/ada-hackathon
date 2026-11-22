import L from "leaflet";
import { t } from "./i18n";

/** Base maps for the layer switcher (Google-Maps style), all keyless. Shared by the dashboard
 * map and the in-vehicle tablet; the choice is remembered in localStorage. */
export type BaseId = "dark" | "standard" | "satellite" | "hybrid" | "terrain";
const BASE_KEY = "planb.basemap";
const OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const ESRI_ATTR = "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community";
const esri = (service: string) => `https://server.arcgisonline.com/ArcGIS/rest/services/${service}/MapServer/tile/{z}/{y}/{x}`;

/** A base map whose label follows the UI language at the time of reading. */
const base = (id: BaseId, layer: L.Layer) => ({
  layer,
  get label() {
    return t(`ops.base.${id}`);
  },
});

/** The base maps of the layer switcher (Google-Maps style), all keyless. */
export function baseMaps(): Record<BaseId, { readonly label: string; layer: L.Layer }> {
  const imagery = () => L.tileLayer(esri("World_Imagery"), { attribution: ESRI_ATTR, maxZoom: 19 });
  return {
    dark: base("dark", L.tileLayer(OSM, { attribution: OSM_ATTR, maxZoom: 19, className: "base-layer dark-layer" })),
    standard: base("standard", L.tileLayer(OSM, { attribution: OSM_ATTR, maxZoom: 19, className: "base-layer" })),
    satellite: base("satellite", imagery()),
    hybrid: base(
      "hybrid",
      L.layerGroup([
        imagery(),
        L.tileLayer(esri("Reference/World_Transportation"), { maxZoom: 19 }),
        L.tileLayer(esri("Reference/World_Boundaries_and_Places"), { maxZoom: 19 }),
      ]),
    ),
    terrain: base(
      "terrain",
      L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
        subdomains: "abc",
        maxNativeZoom: 17,
        maxZoom: 19,
        attribution: `${OSM_ATTR}, SRTM | style &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)`,
      }),
    ),
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
