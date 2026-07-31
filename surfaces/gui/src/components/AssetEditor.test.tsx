import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AssetEditor, SecretsEditor, TextAssetEditor } from "./AssetEditor";

const mocks = vi.hoisted(() => ({
  getAssets: vi.fn().mockResolvedValue([]),
  createAsset: vi.fn().mockResolvedValue({}),
  updateAsset: vi.fn().mockResolvedValue({}),
  deleteAsset: vi.fn().mockResolvedValue({ ok: true }),
  getSecrets: vi.fn().mockResolvedValue([]),
  saveSecret: vi.fn().mockResolvedValue({ ok: true }),
  deleteSecret: vi.fn().mockResolvedValue({ ok: true }),
  getSkills: vi.fn().mockResolvedValue([{ name: "review", description: "Review code", body: "steps", enabled: true, path: "/skills/review/SKILL.md" }]),
  saveSkill: vi.fn().mockResolvedValue({ name: "review", description: "Review code", body: "updated", enabled: true, path: "/skills/review/SKILL.md" }),
  deleteSkill: vi.fn().mockResolvedValue({ ok: true }),
  getAgentsMd: vi.fn().mockResolvedValue({ name: "AGENTS.md", body: "" }),
  saveAgentsMd: vi.fn().mockResolvedValue({ name: "AGENTS.md", body: "saved" }),
}));

vi.mock("../api", () => ({
  ...mocks,
}));
afterEach(() => cleanup());

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

  it("lists, edits, and deletes a skill", async () => {
    render(<TextAssetEditor skill />);
    expect(await screen.findByText("review")).toBeTruthy();
    fireEvent.click(screen.getByText("review"));
    expect(screen.getByDisplayValue("Review code")).toBeTruthy();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByText("Delete"));
    await waitFor(() => expect(mocks.deleteSkill).toHaveBeenCalledWith("review"));
  });

  it("deletes a secret without rendering its value", async () => {
    mocks.getSecrets.mockResolvedValueOnce([{ profile: "github", type: "token", expired: false }]);
    render(<SecretsEditor />);
    expect(await screen.findByText("github")).toBeTruthy();
    expect(screen.queryByText("secret-value")).toBeNull();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByText("Delete"));
    await waitFor(() => expect(mocks.deleteSecret).toHaveBeenCalledWith("github"));
  });

  it("surfaces a failed asset save", async () => {
    mocks.createAsset.mockRejectedValueOnce(new Error("save failed"));
    render(<AssetEditor kind="knowledge" />);
    fireEvent.change(screen.getByPlaceholderText("Name"), { target: { value: "note" } });
    fireEvent.click(screen.getByText("Save"));
    expect((await screen.findByRole("alert")).textContent).toContain("save failed");
  });
});
