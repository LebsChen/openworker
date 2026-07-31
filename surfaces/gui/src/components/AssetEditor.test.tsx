import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { AssetEditor, SecretsEditor } from "./AssetEditor";

vi.mock("../api", () => ({
  getAssets: vi.fn().mockResolvedValue([]),
  createAsset: vi.fn().mockResolvedValue({}),
  updateAsset: vi.fn().mockResolvedValue({}),
  deleteAsset: vi.fn().mockResolvedValue({ ok: true }),
  getSecrets: vi.fn().mockResolvedValue([]),
  saveSecret: vi.fn().mockResolvedValue({ ok: true }),
}));

describe("connector asset editors", () => {
  it("renders a markdown asset editor and creates a new note", () => {
    render(<AssetEditor kind="knowledge" />);
    expect(screen.getByPlaceholderText("Name")).toBeTruthy();
    expect(screen.getByPlaceholderText("Markdown body")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("Name"), { target: { value: "handoff" } });
    fireEvent.change(screen.getByPlaceholderText("Markdown body"), { target: { value: "Use this" } });
    expect(screen.getByText("Save")).toBeTruthy();
  });

  it("keeps secret values in a password input", () => {
    render(<SecretsEditor />);
    expect(screen.getByPlaceholderText("Secret value (never displayed again)").getAttribute("type")).toBe("password");
  });
});
