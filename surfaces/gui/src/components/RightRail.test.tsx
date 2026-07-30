import { describe, expect, it } from "vitest";
import { isRvmPanelTab } from "./RightRail";

describe("right panel tab model", () => {
  it("keeps RVM-only tabs distinct from local data tabs", () => {
    expect(isRvmPanelTab("shell")).toBe(true);
    expect(isRvmPanelTab("ide")).toBe(true);
    expect(isRvmPanelTab("desktop")).toBe(true);
    expect(isRvmPanelTab("info")).toBe(false);
    expect(isRvmPanelTab("worklog")).toBe(false);
    expect(isRvmPanelTab("changes")).toBe(false);
  });
});
