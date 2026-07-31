import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RemoteDesktopPanel } from "./RemoteDesktopPanel";

const mocks = vi.hoisted(() => ({
  openRvmVnc: vi.fn(),
  disconnect: vi.fn(),
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  RFB: vi.fn(),
}));

vi.mock("@novnc/novnc/lib/rfb.js", () => ({
  default: mocks.RFB,
}));

vi.mock("../api", () => ({
  openRvmVnc: mocks.openRvmVnc,
}));

describe("RemoteDesktopPanel", () => {
  beforeEach(() => {
    mocks.openRvmVnc.mockReset();
    mocks.disconnect.mockReset();
    mocks.addEventListener.mockReset();
    mocks.removeEventListener.mockReset();
    mocks.RFB.mockReset();
    mocks.openRvmVnc.mockReturnValue({ close: vi.fn() });
    mocks.RFB.mockImplementation(function MockRfb() {
      return {
        disconnect: mocks.disconnect,
        addEventListener: mocks.addEventListener,
        removeEventListener: mocks.removeEventListener,
        scaleViewport: false,
        clipViewport: false,
        resizeSession: false,
      };
    });
  });

  it("opens a bound RVM VNC socket and configures a docked viewport", () => {
    const host = {
      id: "rvm-1",
      name: "Linux RVM",
      base_url: "http://rvm.example",
      ws_url: "ws://rvm.example",
      token: "",
      local: false,
    };
    render(<RemoteDesktopPanel active sessionId="session-1" host={host} />);

    expect(mocks.openRvmVnc).toHaveBeenCalledWith("session-1");
    expect(mocks.RFB).toHaveBeenCalledTimes(1);
    const connection = mocks.RFB.mock.results[0]?.value;
    expect(connection.scaleViewport).toBe(true);
    expect(connection.clipViewport).toBe(true);
    expect(connection.resizeSession).toBe(true);
    expect(screen.getByText("Connecting…")).toBeTruthy();
  });

  it("tears down the VNC connection when the panel becomes inactive", () => {
    const host = {
      id: "rvm-1",
      name: "Linux RVM",
      base_url: "http://rvm.example",
      ws_url: "ws://rvm.example",
      token: "",
      local: false,
    };
    const view = render(<RemoteDesktopPanel active sessionId="session-1" host={host} />);
    view.rerender(<RemoteDesktopPanel active={false} sessionId="session-1" host={host} />);
    expect(mocks.disconnect).toHaveBeenCalledTimes(1);
  });

  it("does not open a VNC connection for a Local session", () => {
    const host = {
      id: "local",
      name: "Local",
      base_url: "http://local",
      ws_url: "ws://local",
      token: "",
      local: true,
    };
    render(<RemoteDesktopPanel active sessionId="session-1" host={host} />);
    expect(mocks.openRvmVnc).not.toHaveBeenCalled();
    expect(screen.getByText("Requires an RVM host. Local sessions do not provide a desktop.")).toBeTruthy();
  });
});
