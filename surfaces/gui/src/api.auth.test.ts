import { afterEach, expect, it, vi } from "vitest";
import {
  getArtifacts,
  createAsset,
  getHealth,
  getInbox,
  getSessionMessages,
  getSessions,
  getUnattended,
  isCurrentSessionBinding,
  isCurrentSessionLoad,
  Session,
  type SessionHost,
} from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("authenticates REST and session WebSocket calls with the launch token", async () => {
  vi.stubGlobal("__COWORKER_API_TOKEN__", "launch-token");
  const request = vi.fn(async (_url: string, init?: RequestInit) => {
    expect(new Headers(init?.headers).get("X-OpenWorker-Token")).toBe("launch-token");
    return { json: async () => ({ status: "ok" }) } as Response;
  });
  vi.stubGlobal("fetch", request);

  class FakeWebSocket {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    readyState = FakeWebSocket.CONNECTING;
    onmessage: ((event: MessageEvent) => void) | null = null;
    onopen: (() => void) | null = null;
    onclose: (() => void) | null = null;
    send = vi.fn();

    constructor(
      public readonly url: string,
      public readonly protocols?: string | string[],
    ) {}
  }
  vi.stubGlobal("WebSocket", FakeWebSocket);

  await getHealth();
  expect(request).toHaveBeenCalledOnce();

  const session = new Session("s1", "/workspace", "code", { onEvent: vi.fn() });
  const socket = (session as unknown as { ws: FakeWebSocket }).ws;
  expect(socket.protocols).toEqual(["openworker", "launch-token"]);
});

it("adds JSON content type for generic JSON writes without replacing explicit headers", async () => {
  const request = vi.fn(async (_url: string, init?: RequestInit) => ({
    ok: true,
    json: async () => ({ name: "note", description: "", body: "", enabled: true, scope: "global" }),
    init,
  }) as unknown as Response);
  vi.stubGlobal("fetch", request);

  await createAsset("knowledge", {
    name: "note",
    description: "",
    body: "",
    enabled: true,
    scope: "global",
  });
  const headers = new Headers(request.mock.calls[0][1]?.headers);
  expect(headers.get("Content-Type")).toBe("application/json");
});

it("routes every session REST request through the bound remote host", async () => {
  const remote: SessionHost = {
    id: "rvm-a",
    name: "rvm-a",
    base_url: "http://remote.example",
    ws_url: "ws://remote.example",
    token: "remote-token",
    local: false,
  };
  vi.stubGlobal("__COWORKER_HOSTS__", [remote]);
  const request = vi.fn(async (url: string) => ({
    json: async () => (
      url.includes("/messages") ? { messages: [] } :
      url.includes("/artifacts") ? { artifacts: [] } :
      url.includes("/inbox") ? { items: [] } :
      { unattended: false }
    ),
  }) as Response);
  vi.stubGlobal("fetch", request);

  await getSessionMessages("s1", remote);
  await getArtifacts("s1", remote);
  await getInbox("s1", "pending", remote);
  await getUnattended("s1", remote);

  expect(request).toHaveBeenCalledTimes(4);
  for (const [url] of request.mock.calls) {
    expect(url).toMatch(/^http:\/\/remote\.example\//);
    expect(url).not.toContain("127.0.0.1");
  }
});

it("uses the server's persisted host binding for sessions", async () => {
  const local: SessionHost = {
    id: "local",
    name: "Local",
    base_url: "http://local.example",
    ws_url: "ws://local.example",
    token: "",
    local: true,
  };
  const remote: SessionHost = {
    id: "rvm-a",
    name: "rvm-a",
    base_url: "http://remote.example",
    ws_url: "ws://remote.example",
    token: "remote-token",
    local: false,
  };
  vi.stubGlobal("__COWORKER_HOSTS__", [local, remote]);
  vi.stubGlobal("fetch", vi.fn(async (_url: string) => ({
    json: async () => ({
      sessions: [{ session_id: "shared", title: "remote", host_id: "rvm-a" }],
    }),
  }) as Response));

  const sessions = await getSessions();
  expect(sessions).toHaveLength(1);
  expect(sessions[0].host_id).toBe("rvm-a");
  expect(sessions[0].title).toBe("remote");
});

it("keeps the selected session's host on its WebSocket client", () => {
  const remote: SessionHost = {
    id: "rvm-a",
    name: "rvm-a",
    base_url: "http://remote.example",
    ws_url: "ws://remote.example",
    token: "remote-token",
    local: false,
  };
  class FakeWebSocket {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    readyState = FakeWebSocket.CONNECTING;
    onmessage: ((event: MessageEvent) => void) | null = null;
    onopen: (() => void) | null = null;
    onclose: (() => void) | null = null;
    constructor(public readonly url: string, public readonly protocols?: string | string[]) {}
    send = vi.fn();
    close = vi.fn();
  }
  vi.stubGlobal("WebSocket", FakeWebSocket);

  const session = new Session("selected", "", "cowork", { onEvent: vi.fn() }, remote);
  const socket = (session as unknown as { ws: FakeWebSocket }).ws;
  expect(session.sessionId).toBe("selected");
  expect(session.hostId).toBe("rvm-a");
  expect(socket.url).toContain("ws://remote.example/ws/session/selected");
  expect(socket.protocols).toEqual(["openworker", "remote-token"]);
});

it("rejects a late response from session A after switching to session B", () => {
  expect(isCurrentSessionBinding("session-a", "local", "session-b", "local")).toBe(false);
  expect(isCurrentSessionBinding("session-b", "rvm-a", "session-b", "local")).toBe(false);
  expect(isCurrentSessionBinding("session-b", "rvm-a", "session-b", "rvm-a")).toBe(true);
});

it("rejects a late startup restore after the user selects another session", () => {
  expect(
    isCurrentSessionLoad(1, 2, "restored-session", "local", "selected-session", "local"),
  ).toBe(false);
  expect(
    isCurrentSessionLoad(1, 1, "restored-session", "local", "restored-session", "local"),
  ).toBe(true);
});
