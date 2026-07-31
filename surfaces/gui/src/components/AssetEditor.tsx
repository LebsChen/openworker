import { useEffect, useState } from "react";
import {
  createAsset,
  deleteAsset,
  getAssets,
  saveSecret,
  getSecrets,
  updateAsset,
  getAgentsMd,
  saveAgentsMd,
  saveSkill,
  type Asset,
  type SecretStatus,
} from "../api";
import { t, useT } from "../i18n";

type AssetKind = "knowledge" | "playbooks";

export function AssetEditor({ kind }: { kind: AssetKind }) {
  useT();
  const [items, setItems] = useState<Asset[]>([]);
  const [selected, setSelected] = useState<Asset | null>(null);
  const [draft, setDraft] = useState<Asset>({ name: "", description: "", body: "", enabled: true, scope: "global" });
  const reload = () => getAssets(kind).then(setItems).catch(() => {});
  useEffect(() => { reload(); }, [kind]);
  const edit = (item?: Asset) => {
    const next = item ? { ...item } : { name: "", description: "", body: "", enabled: true, scope: "global" as const };
    setSelected(item || null);
    setDraft(next);
  };
  const save = async () => {
    if (!draft.name.trim()) return;
    if (selected) await updateAsset(kind, selected.name, draft);
    else await createAsset(kind, draft);
    await reload();
    setSelected(draft);
  };
  const remove = async () => {
    if (selected && window.confirm(t("assets.confirmDelete"))) {
      await deleteAsset(kind, selected.name);
      setSelected(null);
      await reload();
    }
  };
  return (
    <div className="grid grid-cols-[220px_1fr] gap-5">
      <div className="space-y-1">
        <button className="btn w-full" onClick={() => edit()}>{t("assets.new")}</button>
        {items.map((item) => (
          <button key={item.name} className={"w-full text-left px-3 py-2 rounded-lg " + (selected?.name === item.name ? "bg-paper text-accent" : "hover:bg-paper")} onClick={() => edit(item)}>
            <div className="text-[13px] font-medium">{item.name}</div>
            <div className="text-[11px] text-muted truncate">{item.description}</div>
          </button>
        ))}
      </div>
      <div className="rounded-xl2 border border-line bg-panel p-5 space-y-4">
        <input className="input w-full" placeholder={t("assets.name")} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        <input className="input w-full" placeholder={t("assets.description")} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
        <div className="flex gap-4 text-[12.5px]">
          <label><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} /> {t("assets.enabled")}</label>
          <label>{t("assets.scope")} <select value={draft.scope} onChange={(e) => setDraft({ ...draft, scope: e.target.value as Asset["scope"] })}><option value="global">{t("assets.global")}</option><option value="project">{t("assets.project")}</option></select></label>
        </div>
        {draft.scope === "project" && <input className="input w-full" placeholder={t("assets.projectPath")} value={draft.project || ""} onChange={(e) => setDraft({ ...draft, project: e.target.value })} />}
        {kind === "knowledge" && <input className="input w-full" placeholder={t("assets.trigger")} value={draft.trigger || ""} onChange={(e) => setDraft({ ...draft, trigger: e.target.value })} />}
        <textarea className="input w-full min-h-72 font-mono" placeholder={t("assets.body")} value={draft.body || ""} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
        <div className="flex gap-2"><button className="btn btn-primary" onClick={save}>{t("assets.save")}</button>{selected && <button className="btn text-danger" onClick={remove}>{t("assets.delete")}</button>}</div>
      </div>
    </div>
  );
}

export function SecretsEditor() {
  useT();
  const [items, setItems] = useState<SecretStatus[]>([]);
  const [profile, setProfile] = useState("");
  const [value, setValue] = useState("");
  const reload = () => getSecrets().then(setItems).catch(() => {});
  useEffect(() => { reload(); }, []);
  const save = async () => {
    if (!profile.trim() || !value) return;
    await saveSecret(profile.trim(), { value });
    setProfile(""); setValue(""); reload();
  };
  return <div className="space-y-5">
    <div className="rounded-xl2 border border-line bg-panel p-5 space-y-3">
      <input className="input w-full" placeholder={t("assets.secretName")} value={profile} onChange={(e) => setProfile(e.target.value)} />
      <input className="input w-full" type="password" placeholder={t("assets.secretValue")} value={value} onChange={(e) => setValue(e.target.value)} />
      <button className="btn btn-primary" onClick={save}>{t("assets.saveSecret")}</button>
    </div>
    <div className="rounded-xl2 border border-line bg-panel divide-y divide-line">{items.map((item) => <div key={item.profile} className="flex items-center justify-between p-3 text-[13px]"><span>{item.profile}</span><span className="text-muted">{item.type || t("assets.secretStored")}</span></div>)}</div>
  </div>;
}

export function TextAssetEditor({ skill = false }: { skill?: boolean }) {
  useT();
  const [name, setName] = useState(skill ? "" : "AGENTS.md");
  const [body, setBody] = useState("");
  const [enabled, setEnabled] = useState(true);
  useEffect(() => {
    if (!skill) getAgentsMd().then((x) => setBody(x.body)).catch(() => {});
  }, [skill]);
  return <div className="rounded-xl2 border border-line bg-panel p-5 space-y-4">
    {skill && <input className="input w-full" placeholder={t("assets.name")} value={name} onChange={(e) => setName(e.target.value)} />}
    {skill && <label className="text-[12.5px]"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> {t("assets.enabled")}</label>}
    <textarea className="input w-full min-h-96 font-mono" placeholder={t("assets.body")} value={body} onChange={(e) => setBody(e.target.value)} />
    <button className="btn btn-primary" onClick={() => (skill ? saveSkill(name, body, enabled) : saveAgentsMd(body))}>{t("assets.save")}</button>
  </div>;
}
