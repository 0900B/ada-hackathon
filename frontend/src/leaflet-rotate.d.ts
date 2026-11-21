// Types for the parts of leaflet-rotate (0.2.8) the tablet's navigation map uses.
import "leaflet";

declare module "leaflet" {
  interface MapOptions {
    rotate?: boolean;
    bearing?: number;
    touchRotate?: boolean;
    shiftKeyRotate?: boolean;
    rotateControl?: boolean | Record<string, unknown>;
    compassBearing?: boolean;
  }
  interface Map {
    /** Rotate the map content clockwise by theta degrees (north then points to theta on screen). */
    setBearing(theta: number): this;
    getBearing(): number;
  }
  interface MarkerOptions {
    rotateWithView?: boolean;
    rotation?: number;
  }
}

declare module "leaflet-rotate";
