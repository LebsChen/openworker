import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RemoteIdePanel } from "./RemoteIdePanel";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("loads an ephemeral IDE origin without exposing an RVM token", async () => {
  vi.stubGlobal("__COWORKER_HTTP__", "http://127.0.0.1:8765");
  const host = {
    id: "rvm-a",
    name: "Windows",
    base_url: "http://ignored",
    ws_url: "ws://ignored",
    token: "not-for-the-browser",
    local: false,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        url: "http://127.0.0.1:39123/ide/?folder=C%3A%5CUsers%5CTeam&key=opaque",
      }),
    })) as unknown as typeof fetch,
  );
  render(<RemoteIdePanel active sessionId="session-1" host={host} />);
  const frame = await waitFor(() => screen.getByTitle("Web IDE")) as HTMLIFrameElement;
  expect(frame.src).toBe(
    "http://127.0.0.1:39123/ide/?folder=C%3A%5CUsers%5CTeam&key=opaque",
  );
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

it("shows the server error and offers retry when bootstrap fails", async () => {
  vi.stubGlobal("__COWORKER_HTTP__", "http://127.0.0.1:8765");
  const host = {
    id: "rvm-a",
    name: "Windows",
    base_url: "http://ignored",
    ws_url: "ws://ignored",
    token: "",
    local: false,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: false,
      status: 503,
      json: async () => ({ error: "RVM host is offline" }),
    })) as unknown as typeof fetch,
  );

  render(<RemoteIdePanel active sessionId="session-1" host={host} />);

  expect((await screen.findByRole("alert")).textContent).toContain("RVM host is offline");
  expect(screen.getByText("Connection error")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
});
