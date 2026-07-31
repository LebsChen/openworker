import { afterEach, expect, it, vi } from "vitest";
import { bindSessionHost, getSessionHost, saveRemoteHost } from "./tauri";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("passes camelCase arguments to Tauri commands", async () => {
  const invoke = vi.fn(async () => null);
  vi.stubGlobal("__TAURI__", { core: { invoke } });
  vi.stubGlobal("__COWORKER_HOSTS__", [
    {
      id: "local",
      name: "Local",
      base_url: "http://127.0.0.1:8765",
      ws_url: "ws://127.0.0.1:8765",
      token: "local-token",
      local: true,
    },
  ]);

  await saveRemoteHost("rvm-a", "http://172.16.0.2:18773", "remote-token");
  expect(invoke).toHaveBeenNthCalledWith(1, "save_remote_host", {
    name: "rvm-a",
    baseUrl: "http://172.16.0.2:18773",
    token: "remote-token",
  });

  await bindSessionHost("session-a", "rvm-a");
  expect(invoke).toHaveBeenNthCalledWith(2, "bind_session_host", {
    sessionId: "session-a",
    hostId: "rvm-a",
  });

  await getSessionHost("session-a");
  expect(invoke).toHaveBeenNthCalledWith(3, "session_host", {
    sessionId: "session-a",
  });
});
