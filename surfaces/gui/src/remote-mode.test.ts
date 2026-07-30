import { afterEach, expect, it, vi } from "vitest";
import { getHealth, isRemoteMode, remoteProfileName } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("uses runtime remote mode metadata and reports authentication failures", async () => {
  vi.stubGlobal("__COWORKER_REMOTE_MODE__", true);
  vi.stubGlobal("__COWORKER_REMOTE_NAME__", "rvm");
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 401 })));

  expect(isRemoteMode()).toBe(true);
  expect(remoteProfileName()).toBe("rvm");
  await expect(getHealth()).rejects.toThrow("Remote host authentication failed");
});

it("reports unreachable remote hosts without changing mode", async () => {
  vi.stubGlobal("__COWORKER_REMOTE_MODE__", true);
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 503 })));

  await expect(getHealth()).rejects.toThrow("Remote host connection failed");
  expect(isRemoteMode()).toBe(true);
});

it("authenticates remote health checks against a protected endpoint", async () => {
  vi.stubGlobal("__COWORKER_REMOTE_MODE__", true);
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ status: "ok" }) })
      .mockResolvedValueOnce({ ok: false, status: 401 }),
  );

  await expect(getHealth()).rejects.toThrow("Remote host authentication failed");
});
