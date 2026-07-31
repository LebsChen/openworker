import { useState } from "react";
import {
  addModel,
  getSettings,
  removeModel,
  setDefaultModel,
  setModelCapabilities,
} from "../api";

// Cloud-account providers dispatch by a family segment baked into the model id
// (`bedrock:claude/…`, `vertex:openweight/…`). The add-model row shows a dropdown so
// users pick the family instead of memorizing the prefix; curated matrix ids already
// carry theirs.
const MODEL_FAMILIES: Record<string, { value: string; label: string }[]> = {
  bedrock: [
    { value: "claude", label: "Claude family" },
    { value: "other", label: "Other models" },
  ],
  vertex: [
    { value: "gemini", label: "Gemini family" },
    { value: "claude", label: "Claude family" },
    { value: "openweight", label: "Open-weight" },
  ],
};

// One provider's models as a checklist: tick = shown in the composer's model picker (the
// curated list), the black "default" badge marks the model new sessions use, and hovering any
// other row reveals "Make default". A free-type row below adds models by hand, so brand-new
// releases work without an app update. Shared by Onboarding and Manage → Configure Models.
export function ModelChecklist({
  provider,
  knownProviders,
  suggested,
  curated,
  defaultModel,
  labels,
  capabilityOverrides,
  onCapabilitiesChanged,
  onChanged,
}: {
  provider: string; // decides the id prefix; OpenAI models stay bare
  knownProviders: string[]; // all provider names, to parse prefixes in curated ids
  suggested: string[]; // bare model names suggested by the provider
  curated: string[]; // the full curated list (all providers, full ids)
  defaultModel: string;
  labels?: Record<string, string>; // curated display names (full id → label); raw id when absent
  capabilityOverrides?: Record<string, Record<string, unknown>>;
  onCapabilitiesChanged?: (next: Record<string, Record<string, unknown>>) => void;
  onChanged: (next: { models: string[]; model: string }) => void;
}) {
  const [draft, setDraft] = useState("");
  const families = MODEL_FAMILIES[provider];
  const [family, setFamily] = useState(families?.[0]?.value || "");

  const provOf = (id: string) => {
    const i = id.indexOf(":");
    return i > 0 && knownProviders.includes(id.slice(0, i)) ? id.slice(0, i) : "openai";
  };
  const prefixed = (m: string) => (provider === "openai" || provOf(m) !== "openai" ? m : `${provider}:${m}`);
  const bare = (id: string) => (id.startsWith(`${provider}:`) ? id.slice(provider.length + 1) : id);

  const rows = [
    ...suggested.map(prefixed),
    ...curated.filter((id) => provOf(id) === provider),
  ].filter((id, i, a) => a.indexOf(id) === i);

  const checked = (id: string) => curated.includes(id);
  const refresh = async () => {
    const s = await getSettings();
    onChanged({ models: s.models, model: s.model });
  };

  const tick = async (id: string, on: boolean) => {
    const res = on ? await addModel(id) : await removeModel(id);
    if (res.ok) onChanged({ models: res.models, model: res.model });
  };
  const makeDefault = async (id: string) => {
    if (!checked(id)) await addModel(id); // defaulting an unticked row ticks it too
    await setDefaultModel(id);
    await refresh();
  };
  const add = async () => {
    let typed = draft.trim();
    if (!typed) return;
    // Fold the family choice into the id unless the user already typed one.
    if (families && !families.some((f) => typed.startsWith(`${f.value}/`))) {
      typed = `${family}/${typed}`;
    }
    const res = await addModel(prefixed(typed));
    if (res.ok) {
      setDraft("");
      onChanged({ models: res.models, model: res.model });
    }
  };

  return (
    <div className="mlist">
      {rows.map((id) => {
        const isDefault = id === defaultModel;
        return (
          <div className={"mlist-row" + (checked(id) ? "" : " off")} key={id}>
            <label className="mlist-main">
              <input
                type="checkbox"
                checked={checked(id)}
                disabled={isDefault}
                title={isDefault ? "The default model is always shown — make another model default first" : undefined}
                onChange={(e) => tick(id, e.target.checked)}
              />
              <span className="mlist-name" title={id}>
                {labels?.[id] || bare(id)}
              </span>
            </label>
            {isDefault ? (
              <span className="mlist-default">default</span>
            ) : (
              <button className="mlist-make" onClick={() => makeDefault(id)}>
                Make default
              </button>
            )}
            {provider === "openai" && !labels?.[id] && (
              <CapabilityEditor
                model={id}
                override={capabilityOverrides?.[id]}
                onSaved={(next) => onCapabilitiesChanged?.(next)}
              />
            )}
          </div>
        );
      })}
      <div className="mlist-add">
        {families && (
          <select
            value={family}
            onChange={(e) => setFamily(e.target.value)}
            aria-label="Model family"
            data-testid="mlist-family"
          >
            {families.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        )}
        <input
          placeholder="Add another model…"
          value={draft}
          spellCheck={false}
          autoComplete="off"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
        />
        <button className="btn-primary sm" onClick={add} disabled={!draft.trim()}>
          Add
        </button>
      </div>
    </div>
  );
}

function CapabilityEditor({
  model,
  override,
  onSaved,
}: {
  model: string;
  override?: Record<string, unknown>;
  onSaved: (next: Record<string, Record<string, unknown>>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [vision, setVision] = useState(Boolean(override?.vision));
  const [pdf, setPdf] = useState(Boolean(override?.pdf));
  const [parallel, setParallel] = useState(Boolean(override?.parallel_tool_calls));
  const [context, setContext] = useState(
    override?.context_window ? String(override.context_window) : "",
  );
  const save = async () => {
    const next: Record<string, unknown> = { vision, pdf, parallel_tool_calls: parallel };
    if (context.trim()) next.context_window = Number(context);
    const result = await setModelCapabilities(model, next);
    if (result.ok) {
      setOpen(false);
      onSaved(result.model_capabilities || {});
    }
  };
  return (
    <div className="mlist-cap">
      <button className="mlist-make" onClick={() => setOpen((value) => !value)}>
        capabilities
      </button>
      {open && (
        <div className="absolute z-10 right-0 top-7 rounded-lg border border-line bg-panel p-2.5 shadow-lg text-[11px]">
          <label className="flex gap-1.5"><input type="checkbox" checked={vision} onChange={(e) => setVision(e.target.checked)} /> vision</label>
          <label className="flex gap-1.5"><input type="checkbox" checked={pdf} onChange={(e) => setPdf(e.target.checked)} /> PDF</label>
          <label className="flex gap-1.5"><input type="checkbox" checked={parallel} onChange={(e) => setParallel(e.target.checked)} /> parallel tools</label>
          <label className="mt-1 block">context tokens
            <input className="ml-1 w-24 rounded border border-line bg-paper px-1" value={context} onChange={(e) => setContext(e.target.value)} inputMode="numeric" />
          </label>
          <button className="mt-2 rounded bg-accent px-2 py-1 text-white" onClick={() => void save()}>Save</button>
        </div>
      )}
    </div>
  );
}
