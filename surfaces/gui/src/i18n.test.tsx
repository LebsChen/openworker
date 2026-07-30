import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test } from "vitest";
import { I18nProvider, useI18n } from "./i18n";

function Probe() {
  const { locale, setLocale, t } = useI18n();
  return (
    <>
      <output data-testid="locale">{locale}</output>
      <output data-testid="label">{t("ui.SettingsView.language")}</output>
      <output data-testid="fallback">{t("test.englishFallback")}</output>
      <button onClick={() => void setLocale("zh-CN")}>switch</button>
    </>
  );
}

test("missing locale entries fall back to English and switching rerenders", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    return {
      json: async () => (url.endsWith("/v1/settings") ? { locale: "en" } : { ok: true }),
    } as Response;
  }) as typeof fetch;
  try {
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("locale").textContent).toBe("en"));
    expect(screen.getByTestId("fallback").textContent).toBe("English fallback");
    fireEvent.click(screen.getByText("switch"));
    await waitFor(() => expect(screen.getByTestId("locale").textContent).toBe("zh-CN"));
    expect(screen.getByTestId("label").textContent).toBe("语言");
    expect(screen.getByTestId("fallback").textContent).toBe("English fallback");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
