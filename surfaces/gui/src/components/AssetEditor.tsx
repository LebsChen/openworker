import { useEffect, useState } from "react";
import {
  createAsset, deleteAsset, deleteSecret, deleteSkill, getAgentsMd, getAsset, getAssets,
  getSecrets, getSkills, saveAgentsMd, saveSecret, saveSkill, updateAsset,
  type Asset, type SecretStatus, type Skill,
} from "../api";
import { t, useT } from "../i18n";

type AssetKind = "knowledge" | "playbooks";
type Notice = { error?: string; success?: string };

function Notice({ notice }: { notice: Notice }) {
  if (notice.error) return <div role="alert" className="text-danger text-[12px]">{notice.error}</div>;
  if (notice.success) return <div role="status" className="text-success text-[12px]">{notice.success}</div>;
  return null;
}

const emptyAsset = (): Asset => ({ name: "", description: "", body: "", enabled: true, scope: "global" });

export function AssetEditor({ kind }: { kind: AssetKind }) {
  useT();
  const [items, setItems] = useState<Asset[]>([]);
  const [selected, setSelected] = useState<Asset | null>(null);
  const [draft, setDraft] = useState<Asset>(emptyAsset());
  const [notice, setNotice] = useState<Notice>({});
  const reload = async () => { try { setItems(await getAssets(kind)); } catch (error) { setNotice({ error: String(error) }); } };
  useEffect(() => { void reload(); }, [kind]);
  const edit = async (item?: Asset) => {
    setNotice({});
    if (!item) { setSelected(null); setDraft(emptyAsset()); return; }
    try {
      const detail = await getAsset(kind, item.name);
      setSelected(detail); setDraft(detail);
    } catch (error) { setNotice({ error: String(error) }); }
  };
  const save = async () => {
    if (!draft.name.trim()) return;
    try {
      const saved = selected ? await updateAsset(kind, selected.name, draft) : await createAsset(kind, draft);
      await reload(); setSelected(saved); setDraft(saved); setNotice({ success: t("assets.saved") });
    } catch (error) { setNotice({ error: String(error) }); }
  };
  const remove = async () => {
    if (!selected || !window.confirm(t("assets.confirmDelete"))) return;
    try { await deleteAsset(kind, selected.name); setSelected(null); setDraft(emptyAsset()); await reload(); setNotice({ success: t("assets.deleted") }); }
    catch (error) { setNotice({ error: String(error) }); }
  };
  return <div className="grid grid-cols-[220px_1fr] gap-5">
    <div className="space-y-1"><button className="btn w-full" onClick={() => void edit()}>{t("assets.new")}</button>{items.map((item) => <button key={item.name} className={"w-full text-left px-3 py-2 rounded-lg " + (selected?.name === item.name ? "bg-paper text-accent" : "hover:bg-paper")} onClick={() => void edit(item)}><div className="text-[13px] font-medium">{item.name}</div><div className="text-[11px] text-muted truncate">{item.description}</div></button>)}</div>
    <div className="rounded-xl2 border border-line bg-panel p-5 space-y-4"><Notice notice={notice} />
      <input className="input w-full" placeholder={t("assets.name")} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
      <input className="input w-full" placeholder={t("assets.description")} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
      <div className="flex gap-4 text-[12.5px]"><label><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} /> {t("assets.enabled")}</label><label>{t("assets.scope")} <select value={draft.scope} onChange={(e) => setDraft({ ...draft, scope: e.target.value as Asset["scope"] })}><option value="global">{t("assets.global")}</option><option value="project">{t("assets.project")}</option></select></label></div>
      {draft.scope === "project" && <input className="input w-full" placeholder={t("assets.projectPath")} value={draft.project || ""} onChange={(e) => setDraft({ ...draft, project: e.target.value })} />}
      {kind === "knowledge" && <label className="block text-[12.5px]">{t("assets.trigger")} <select className="input w-full" value={draft.trigger || "manual"} onChange={(e) => setDraft({ ...draft, trigger: e.target.value })}><option value="manual">{t("assets.manual")}</option><option value="always">{t("assets.always")}</option></select></label>}
      <textarea className="input w-full min-h-72 font-mono" placeholder={t("assets.body")} value={draft.body || ""} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />
      <button className="btn btn-primary" onClick={() => void save()}>{t("assets.save")}</button>{selected && <button className="btn text-danger ml-2" onClick={() => void remove()}>{t("assets.delete")}</button>}
    </div>
  </div>;
}

export function SecretsEditor() {
  useT();
  const [items, setItems] = useState<SecretStatus[]>([]);
  const [profile, setProfile] = useState(""); const [value, setValue] = useState(""); const [notice, setNotice] = useState<Notice>({});
  const reload = async () => { try { setItems(await getSecrets()); } catch (error) { setNotice({ error: String(error) }); } };
  useEffect(() => { void reload(); }, []);
  const save = async () => { if (!profile.trim() || !value) return; try { await saveSecret(profile.trim(), { value }); setProfile(""); setValue(""); await reload(); setNotice({ success: t("assets.saved") }); } catch (error) { setNotice({ error: String(error) }); } };
  const remove = async (name: string) => { if (!window.confirm(t("assets.confirmDelete"))) return; try { await deleteSecret(name); await reload(); setNotice({ success: t("assets.deleted") }); } catch (error) { setNotice({ error: String(error) }); } };
  return <div className="space-y-5"><Notice notice={notice} /><div className="rounded-xl2 border border-line bg-panel p-5 space-y-3"><p className="text-[12px] text-muted">{t("assets.writeOnlyNotice")}</p><input className="input w-full" placeholder={t("assets.secretName")} value={profile} onChange={(e) => setProfile(e.target.value)} /><input className="input w-full" type="password" placeholder={t("assets.secretValue")} value={value} onChange={(e) => setValue(e.target.value)} /><button className="btn btn-primary" onClick={() => void save()}>{t("assets.saveSecret")}</button></div><div className="rounded-xl2 border border-line bg-panel divide-y divide-line">{items.map((item) => <div key={item.profile} className="flex items-center justify-between p-3 text-[13px]"><span>{item.profile}</span><span className="flex gap-3 items-center text-muted">{item.type || t("assets.secretStored")}<button className="text-danger" onClick={() => void remove(item.profile)}>{t("assets.delete")}</button></span></div>)}</div></div>;
}

export function TextAssetEditor({ skill = false }: { skill?: boolean }) {
  useT();
  const [items, setItems] = useState<Skill[]>([]); const [selected, setSelected] = useState<Skill | null>(null);
  const [name, setName] = useState(skill ? "" : "AGENTS.md"); const [description, setDescription] = useState(""); const [body, setBody] = useState(""); const [enabled, setEnabled] = useState(true); const [notice, setNotice] = useState<Notice>({});
  const reload = async () => { try { if (skill) setItems(await getSkills()); else { const x = await getAgentsMd(); setBody(x.body); } } catch (error) { setNotice({ error: String(error) }); } };
  useEffect(() => { void reload(); }, [skill]);
  const edit = (item?: Skill) => { setSelected(item || null); setName(item?.name || (skill ? "" : "AGENTS.md")); setDescription(item?.description || ""); setBody(item?.body || ""); setEnabled(item?.enabled ?? true); setNotice({}); };
  const save = async () => { try { if (skill) { const saved = await saveSkill(name, body, enabled, description); setSelected(saved); setName(saved.name); setDescription(saved.description); setBody(saved.body || ""); setItems(await getSkills()); } else { const saved = await saveAgentsMd(body); setBody(saved.body); await reload(); } setNotice({ success: t("assets.saved") }); } catch (error) { setNotice({ error: String(error) }); } };
  const remove = async () => { if (!selected || !window.confirm(t("assets.confirmDelete"))) return; try { await deleteSkill(selected.name); setSelected(null); edit(); setItems(await getSkills()); setNotice({ success: t("assets.deleted") }); } catch (error) { setNotice({ error: String(error) }); } };
  return <div className={skill ? "grid grid-cols-[220px_1fr] gap-5" : "space-y-3"}>{skill && <div className="space-y-1"><button className="btn w-full" onClick={() => edit()}>{t("assets.new")}</button>{items.map((item) => <button key={item.name} className="w-full text-left px-3 py-2 rounded-lg hover:bg-paper" onClick={() => edit(item)}><div className="text-[13px]">{item.name}</div><div className="text-[11px] text-muted truncate">{item.description}</div></button>)}</div>}<div className="rounded-xl2 border border-line bg-panel p-5 space-y-4"><Notice notice={notice} />{skill && <><input className="input w-full" placeholder={t("assets.name")} value={name} onChange={(e) => setName(e.target.value)} /><input className="input w-full" placeholder={t("assets.description")} value={description} onChange={(e) => setDescription(e.target.value)} /><label className="text-[12.5px]"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> {t("assets.enabled")}</label>{selected?.path && <div className="text-[11px] text-muted">{t("assets.path")}: {selected.path}</div>}</>}<textarea className="input w-full min-h-96 font-mono" placeholder={t("assets.body")} value={body} onChange={(e) => setBody(e.target.value)} /><button className="btn btn-primary" onClick={() => void save()}>{t("assets.save")}</button>{skill && selected && <button className="btn text-danger ml-2" onClick={() => void remove()}>{t("assets.delete")}</button>}</div></div>;
}
