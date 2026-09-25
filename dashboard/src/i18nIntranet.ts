/**
 * Intranet fork UI strings (fork-owned). Put new or overridden copy in
 * ``locales/intranet/{en,zh}.json`` (same keys in both), never in the upstream
 * ``locales/{en,zh}.json``. Call only after the upstream bundle is loaded,
 * otherwise ``hasResourceBundle`` short-circuits the upstream load.
 */
import i18n from "i18next";
import intranetEn from "./locales/intranet/en.json";
import intranetZh from "./locales/intranet/zh.json";
import type { UiLocale } from "./utils/localePrefs";

const INTRANET_BUNDLES: Record<UiLocale, object> = {
  en: intranetEn,
  zh: intranetZh,
};

/** Deep-merge the intranet overlay over the already-loaded upstream bundle. */
export function applyIntranetOverlay(locale: UiLocale): void {
  i18n.addResourceBundle(
    locale,
    "translation",
    INTRANET_BUNDLES[locale],
    true,
    true,
  );
}
