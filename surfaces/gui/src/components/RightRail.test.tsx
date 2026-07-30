import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { isRvmPanelTab, RightRail } from "./RightRail";

vi.mock("./AccessSection", () => ({ AccessSection: () => <div data-testid="access-section" /> }));
vi.mock("./Markdown", () => ({ Markdown: () => null, OPEN_ARTIFACT_EVENT: "open-artifact" }));

describe("right panel tab model", () => {
  it("keeps RVM-only tabs distinct from local data tabs", () => {
    expect(isRvmPanelTab("shell")).toBe(true);
    expect(isRvmPanelTab("ide")).toBe(true);
    expect(isRvmPanelTab("desktop")).toBe(true);
    expect(isRvmPanelTab("info")).toBe(false);
    expect(isRvmPanelTab("worklog")).toBe(false);
    expect(isRvmPanelTab("changes")).toBe(false);
  });

  it("uses a vertical icon rail that toggles without unmounting panes", () => {
    const host = { id: "local", name: "Local", base_url: "http://local", ws_url: "ws://local", token: "", local: true };
    render(
      <RightRail
        active
        sessionId="session-1"
        host={host}
        refreshKey={0}
        toolNames={[]}
        todo={[]}
        items={[]}
        running={false}
        showArtifacts={false}
      />,
    );
    const info = screen.getByRole("button", { name: "Info" });
    const worklog = screen.getByRole("button", { name: "Worklog" });
    expect(screen.getAllByText("Worklog").length).toBeGreaterThan(0);
    fireEvent.click(info);
    fireEvent.click(worklog);
    expect(screen.getAllByText("Worklog").length).toBeGreaterThan(0);
    expect((screen.getByRole("button", { name: "Shell" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Web IDE" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Browser/Desktop" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
