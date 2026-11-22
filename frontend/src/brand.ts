import { t } from "./i18n";

/** Product and operator names shown in the UI. Change them here (and their texts in locales/dashboard.ts). */
export const BRAND = {
  product: "Plan B",
  get tagline() {
    return t("dash.brand.tagline"); // "AI dispatch co-pilot: a new plan when things go wrong"
  },
  // A fictional EMS operator for the demo; deliberately not a real organisation.
  get operator() {
    return t("dash.brand.operator"); // "Ljubljana Demo EMS (fictional)"
  },
};
