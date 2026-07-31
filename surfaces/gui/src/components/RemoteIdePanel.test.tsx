import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RemoteIdePanel } from "./RemoteIdePanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("loads the same-origin IDE bootstrap without exposing an RVM token", async () => {
  vi.stubGlobal("__COWORKER_HTTP__", "http://127.0.0.1:8765");
  const host = {
    id: "rvm-a",
    name: "Windows",
    base_url: "http://ignored",
    ws_url: "ws://ignored",
    token: "not-for-the-browser",
    local: false,
  };
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true })) as unknown as typeof fetch);
  render(<RemoteIdePanel active sessionId="session-1" host={host} />);
  const frame = await waitFor(() => screen.getByTitle("Web IDE")) as HTMLIFrameElement;
  expect(frame.src).toBe("http://127.0.0.1:8765/v1/sessions/session-1/ide/");
  expect(frame.src).not.toContain("token");
  fireEvent.load(frame);
  expect(screen.getByText("Connected")).toBeTruthy();
});

it("does not render an iframe for local sessions", () => {
  const host = {
    id: "local",
    name: "Local",
    base_url: "http://local",
    ws_url: "ws://local",
    token: "",
    local: true,
  };
  render(<RemoteIdePanel active sessionId="session-1" host={host} />);
  expect(screen.queryByTitle("Web IDE")).toBeNull();
  expect(screen.getByText(/Requires an RVM host/)).toBeTruthy();
});
