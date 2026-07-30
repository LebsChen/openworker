import type { Item } from "./types";

export type WorklogEntryKind = "user" | "assistant" | "tool" | "file" | "notice";

export interface WorklogEntry {
  id: string;
  kind: WorklogEntryKind;
  title: string;
  detail?: string;
  filePaths?: string[];
  status?: string;
  ts?: number;
}

const FILE_TOOL_RE = /(?:write|edit|patch|file|artifact|read_file|delete_file|move_file)/i;

function filePathsFrom(value: unknown): string[] {
  if (!value || typeof value !== "object") return [];
  const result: string[] = [];
  const visit = (candidate: unknown) => {
    if (typeof candidate === "string") {
      if (candidate.includes("/") || /\.[a-z0-9]{1,8}$/i.test(candidate)) result.push(candidate);
      return;
    }
    if (Array.isArray(candidate)) {
      candidate.forEach(visit);
      return;
    }
    if (candidate && typeof candidate === "object") {
      Object.entries(candidate).forEach(([key, child]) => {
        if (/^(?:path|file|file_path|filename|filePath)$/i.test(key)) visit(child);
        else if (/^(?:files|changes|updates|paths)$/i.test(key)) visit(child);
      });
    }
  };
  visit(value);
  return [...new Set(result)];
}

function textFrom(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === undefined || value === null) return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** Convert the transcript/event-shaped Item list into stable panel rows.
 *  The panel consumes this selector rather than App's live state fragments. */
export function selectWorklog(items: Item[]): WorklogEntry[] {
  return items.flatMap((item, index): WorklogEntry[] => {
    const id = "worklog-" + (item.kind === "tool" && item.id ? item.id : index);
    if (item.kind === "user") {
      return [{ id, kind: "user", title: "User message", detail: item.text, ts: item.ts }];
    }
    if (item.kind === "assistant") {
      return [{
        id,
        kind: "assistant",
        title: "Assistant response",
        detail: item.text,
        ts: item.ts,
      }];
    }
    if (item.kind === "tool") {
      const filePaths = FILE_TOOL_RE.test(item.name) ? filePathsFrom(item.args) : [];
      return [{
        id,
        kind: filePaths.length ? "file" : "tool",
        title: item.name.replace(/[_-]+/g, " "),
        detail: item.preview || textFrom(item.args),
        filePaths,
        status: item.status,
      }];
    }
    if (item.kind === "notice") {
      return [{ id, kind: "notice", title: item.text, status: item.tone }];
    }
    return [];
  });
}
