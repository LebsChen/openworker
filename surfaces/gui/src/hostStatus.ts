import type { RemoteHostProbeResult } from "./tauri";

export const HOST_STATUS_CHANGED = "coworker-host-status-changed";

export function hostProbeResults(): Record<string, RemoteHostProbeResult> {
  const value = (globalThis as any).__COWORKER_HOST_PROBES__;
  return value && typeof value === "object" ? value : {};
}

export function hostProbeResult(id: string): RemoteHostProbeResult | undefined {
  return hostProbeResults()[id];
}

export function setHostProbeResult(id: string, result: RemoteHostProbeResult): void {
  const next = { ...hostProbeResults(), [id]: result };
  (globalThis as any).__COWORKER_HOST_PROBES__ = next;
  const statuses = { ...((globalThis as any).__COWORKER_HOST_STATUS__ || {}), [id]: result.status };
  (globalThis as any).__COWORKER_HOST_STATUS__ = statuses;
  window.dispatchEvent(new CustomEvent(HOST_STATUS_CHANGED, { detail: { id, result } }));
}
