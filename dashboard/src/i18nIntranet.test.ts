import { afterAll, describe, expect, it, vi } from "vitest";
import i18n, { ensureLocaleBundle, initI18n } from "./i18n";
import upstreamZh from "./locales/zh.json";
import { UI_LOCALE_STORAGE_KEY } from "./utils/localePrefs";

vi.mock("./locales/intranet/en.json", () => ({
  default: { common: { save: "EN-PROBE" }, intranetProbe: { hello: "en" } },
}));
vi.mock("./locales/intranet/zh.json", () => ({
  default: { common: { save: "ZH-PROBE" }, intranetProbe: { hello: "zh" } },
}));

describe("intranet i18n overlay", () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  afterAll(() => vi.unstubAllGlobals());

  it("overlays the initial locale before initI18n resolves", async () => {
    localStorage.setItem(UI_LOCALE_STORAGE_KEY, "en");
    await initI18n();
    expect(i18n.t("common.save")).toBe("EN-PROBE");
    expect(i18n.t("intranetProbe.hello")).toBe("en");
    expect(i18n.t("common.reset")).toBe("Reset");
  });

  it("overlays a later-loaded locale exactly once", async () => {
    await ensureLocaleBundle("zh");
    const zh = (key: string) => i18n.getResource("zh", "translation", key);
    expect(zh("common.save")).toBe("ZH-PROBE");
    expect(zh("intranetProbe.hello")).toBe("zh");
    expect(zh("common.reset")).toBe(upstreamZh.common.reset);

    const add = vi.spyOn(i18n, "addResourceBundle");
    await ensureLocaleBundle("zh");
    expect(add).not.toHaveBeenCalled();
  });
});
