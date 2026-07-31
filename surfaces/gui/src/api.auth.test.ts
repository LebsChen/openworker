import { afterEach, expect, it, vi } from "vitest";
import {
  getArtifacts,
  getHealth,
  getInbox,
  getSessionMessages,
  getUnattended,
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
