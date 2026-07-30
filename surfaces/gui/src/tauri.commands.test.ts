import { afterEach, expect, it, vi } from "vitest";
import { bindSessionHost, getSessionHost, saveRemoteHost, testRemoteHost } from "./tauri";

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
    rvmUrl: null,
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

it("reports an online host only after the protected settings probe succeeds", async () => {
  const request = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({
      status: "ok",
      service: "dev-agent",
      version: "1.0.32",
      platform: "linux",
      host: "test-host",
      capabilities: ["exec"],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ hostname: "test-host", cpus: 4 }), { status: 200 }));
  vi.stubGlobal("fetch", request);

  const result = await testRemoteHost("http://remote.example", "secret-token");

  expect(result.status).toBe("online");
  expect(result.health?.version).toBe("1.0.32");
  expect(result.info?.hostname).toBe("test-host");
  expect(request.mock.calls[1][1]).toMatchObject({
    headers: { Authorization: "Bearer secret-token" },
  });
  expect(request.mock.calls[0][0]).toBe("http://remote.example/api/health");
  expect(request.mock.calls[1][0]).toBe("http://remote.example/api/info");
});

it("distinguishes authentication failures from unreachable hosts", async () => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(new Response("{}", { status: 200 }))
    .mockResolvedValueOnce(new Response("unauthorized", { status: 401 })));
  await expect(testRemoteHost("http://remote.example", "bad-token")).resolves.toMatchObject({
    status: "auth_failed",
  });

  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network error")));
  await expect(testRemoteHost("http://remote.example", "token")).resolves.toMatchObject({
    status: "offline",
  });
});

it("classifies an aborted RVM probe as offline with a timeout reason", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("timed out", "AbortError")));
  await expect(testRemoteHost("http://remote.example", "token")).resolves.toMatchObject({
    status: "offline",
    error: "Connection timed out. Check the address and network connection.",
  });
});
