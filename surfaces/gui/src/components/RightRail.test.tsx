import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { formatTime, isRvmPanelTab, RightRail } from "./RightRail";
import * as api from "../api";

vi.mock("./AccessSection", () => ({ AccessSection: () => <div data-testid="access-section" /> }));
vi.mock("./Markdown", () => ({ Markdown: () => null, OPEN_ARTIFACT_EVENT: "open-artifact" }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("right panel tab model", () => {
  it("formats ISO artifact timestamps without producing Invalid Date", () => {
    expect(formatTime("2026-01-02T03:04:05.000Z")).not.toContain("Invalid");
    expect(formatTime("2026-01-02T03:04:05.000Z")).not.toBe("");
  });

  it("keeps RVM-only tabs distinct from local data tabs", () => {
    expect(isRvmPanelTab("shell")).toBe(true);
    expect(isRvmPanelTab("ide")).toBe(true);
    expect(isRvmPanelTab("desktop")).toBe(true);
    expect(isRvmPanelTab("info")).toBe(false);
    expect(isRvmPanelTab("worklog")).toBe(false);
    expect(isRvmPanelTab("changes")).toBe(false);
  });

  it("uses a vertical icon rail and mounts only the selected local pane", () => {
    const host = { id: "local", name: "Local", base_url: "http://local", ws_url: "ws://local", token: "", local: true };
    const transcriptText = "assistant text belongs in the transcript";
    render(
      <RightRail
        active
        sessionId="session-1"
        host={host}
        refreshKey={0}
        toolNames={[]}
        todo={[]}
        items={[{ kind: "assistant", text: transcriptText }]}
        running={false}
        showArtifacts={false}
      />,
    );
    const info = screen.getByRole("button", { name: "Info" });
    const worklog = screen.getByRole("button", { name: "Worklog" });
    expect(worklog).toBeTruthy();
    expect(screen.queryAllByText(transcriptText)).toHaveLength(0);
    fireEvent.click(info);
    fireEvent.click(worklog);
    expect(screen.getByRole("heading", { name: "Worklog" })).toBeTruthy();
    expect(screen.getAllByText(transcriptText)).toHaveLength(1);
    expect((screen.getByRole("button", { name: "Shell" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Web IDE" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Browser/Desktop" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText("Requires an RVM host")).toBeNull();
  });

  it("preserves the selected panel when the active persona changes", async () => {
    const host = { id: "local", name: "Local", base_url: "http://local", ws_url: "ws://local", token: "", local: true };
    const view = render(
      <RightRail
        active
        sessionId="session-1"
        host={host}
        refreshKey={0}
        toolNames={[]}
        todo={[]}
        items={[]}
        running={false}
        personaId="cowork"
        showArtifacts
      />,
    );
    fireEvent.click(screen.getAllByRole("button", { name: "Worklog" }).find((button) => button.getAttribute("aria-pressed") === "false")!);
    view.rerender(
      <RightRail
        active
        sessionId="session-1"
        host={host}
        refreshKey={0}
        toolNames={[]}
        todo={[]}
        items={[]}
        running={false}
        personaId="code"
        showArtifacts={false}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: "Worklog" }).find((button) => button.getAttribute("aria-pressed") === "true"),
      ).toBeTruthy(),
    );
  });

  it("opens a workspace diff and returns to the change list", async () => {
    vi.spyOn(api, "getArtifacts").mockResolvedValue([]);
    vi.spyOn(api, "getGitStatus").mockResolvedValue({
      repository: true,
      branch: "main",
      dirty: true,
      files: [{ path: "app.ts", status: "M", additions: 2, deletions: 1 }],
    });
    vi.spyOn(api, "getGitDiff").mockResolvedValue({
      ok: true,
      path: "app.ts",
      diff: "@@ -1 +1 @@\n-old\n+new",
    });
    const host = { id: "local", name: "Local", base_url: "http://local", ws_url: "ws://local", token: "", local: true };
    render(
      <RightRail active sessionId="git" host={host} refreshKey={0} toolNames={[]} todo={[]} items={[]} running={false} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "File changes" }));
    await waitFor(() => expect(screen.getByText("app.ts")).toBeTruthy());
    fireEvent.click(screen.getByText("app.ts"));
    await waitFor(() => expect(screen.getByText("+new")).toBeTruthy());
    fireEvent.click(screen.getByTitle("Back"));
    await waitFor(() => expect(screen.getByText("app.ts")).toBeTruthy());
  });

  it("surfaces an offline workspace state", async () => {
    vi.spyOn(api, "getArtifacts").mockResolvedValue([]);
    vi.spyOn(api, "getGitStatus").mockResolvedValue({
      repository: false,
      files: [],
      status: "offline",
      error: "offline",
    });
    const host = { id: "remote", name: "Windows", base_url: "http://remote", ws_url: "ws://remote", token: "", local: false };
    render(
      <RightRail active sessionId="offline" host={host} refreshKey={0} toolNames={[]} todo={[]} items={[]} running={false} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "File changes" }));
    await waitFor(() => expect(screen.getByText("Workspace Git state is offline.")).toBeTruthy());
  });
});
