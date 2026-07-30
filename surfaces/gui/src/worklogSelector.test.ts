import { describe, expect, it } from "vitest";
import { selectWorklog } from "./worklogSelector";
import type { Item } from "./types";

describe("selectWorklog", () => {
  it("normalizes transcript items into stable worklog rows", () => {
    const items: Item[] = [
      { kind: "user", text: "Inspect the project", ts: 1 },
      { kind: "tool", id: "tool-1", name: "write_file", args: { path: "src/main.ts" }, status: "ok" },
      { kind: "assistant", text: "Done", ts: 2 },
    ];
    expect(selectWorklog(items)).toMatchObject([
      { id: "worklog-0", kind: "user", title: "User message" },
      { id: "worklog-tool-1", kind: "file", title: "write file", filePaths: ["src/main.ts"] },
      { id: "worklog-2", kind: "assistant", title: "Assistant response" },
    ]);
  });

  it("keeps notices and tool statuses visible", () => {
    const rows = selectWorklog([
      { kind: "tool", id: "tool-2", name: "shell", args: { command: "pwd" }, status: "failed", preview: "exit 1" },
      { kind: "notice", tone: "warn", text: "Interrupted." },
    ]);
    expect(rows[0]).toMatchObject({ kind: "tool", status: "failed", detail: "exit 1" });
    expect(rows[1]).toMatchObject({ kind: "notice", title: "Interrupted.", status: "warn" });
  });
});
