import { t, useT } from "../i18n";
import { useEffect, useState } from "react";
import {
  getSettings,
  deleteRvmHost,
  listRvmHosts,
  saveRvmHost,
  testRvmHost,
  type RvmHostInfo,
  getTrustedWorkspaces,
  setCompactionSettings,
  setOnboarded,
  setPdfSettings,
  setScratchBase,
  setSessionsPeek,
  setWorkspaceTrusted,
  type CompactionSettings,
  type ModelSettings,
  type PdfSettings,
  type WorkspaceCommandTrust,
} from "../api";
import {
  cancelDictationModelDownload,
  deleteDictationModel,
  downloadDictationModel,
  getAutostart,
  getDictationStatus,
  getKeepAwake,
  checkForUpdate,
  installUpdate,
  isTauri,
  listenDictationDownloadProgress,
  markDictationTestPassed,
  pickFolder,
  setAutostart,
  setKeepAwake,
  type RemoteHostProbeResult,
  startDictation,
  stopDictation,
  verifyDictationModel,
  type DictationDownloadProgress,
  type DictationStatus,
} from "../tauri";
import { useThemePref } from "../theme";
import { Icon } from "./Icon";
import { PanelHead } from "./IntegrationsView";
import { ModelsTab } from "./ManageTabs";
import { GalleryModal } from "./GalleryModal";
import { PersonasTab } from "./PersonasTab";
import { showPersonas } from "../flags";
import { setHostProbeResult } from "../hostStatus";
import { availableLocales, useI18n } from "../i18n";

// Settings, restructured (Option 2) into a full-page surface that mirrors IntegrationsView's shell:
// a left sub-nav (Appearance · Files · Models · Personas) + centered panel, replacing the old
// top-tab ManageModal. Local/app concerns live here; anything external (Connectors, Messaging, MCP,
// Activity) stays under Integrations. Appearance + Files are re-skinned to the mock's Tailwind idiom;
// Models + Personas host the existing tab components inside the page shell (field re-skin to follow).
// "appearance" is the General tab's stable key — callers deep-link with it, so the
// rename (UX-021) changed only the label. "files" folded into General as a card.
type SetTab = "appearance" | "models" | "voice" | "personas" | "remote";

const CARD = "rounded-xl2 border border-line bg-panel";
const FIELD_LABEL = "text-[12.5px] font-medium text-ink";
const FIELD_HELP = "text-[12px] text-muted mt-1.5 leading-relaxed";
const INPUT =
  "flex-1 min-w-0 px-3 py-2 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent";
const BTN_ACCENT = "text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40";
const BTN_BORDERED =
  "text-[12.5px] px-3 py-2 rounded-lg border border-line bg-paper hover:border-lineStrong shrink-0";

const SET_TABS: { key: SetTab; labelKey: string; icon: "sliders" | "code" | "mic" | "sparkle" }[] = [
  { key: "appearance", labelKey: "settings.generalTab", icon: "sliders" },
  { key: "models", labelKey: "settings.modelsTab", icon: "code" },
  { key: "voice", labelKey: "settings.voiceInputTab", icon: "mic" },
  { key: "remote", labelKey: "settings.remoteHostTab", icon: "sliders" },
  { key: "personas", labelKey: "settings.personasTab", icon: "sparkle" },
];

export function SettingsView({
  initialTab,
  onOpenPersona,
}: {
  initialTab?: SetTab;
  onOpenPersona?: (id: string) => void;
}) {
  useT();
  // Personas is flag-gated (hidden for launch) — filter the tab AND coerce a stale
  // deep-link to it (openSettings("personas") callers) so the page never opens on a
  // section with no nav entry.
  const personas = showPersonas();
  const tabs = personas ? SET_TABS : SET_TABS.filter((t) => t.key !== "personas");
  const wanted = initialTab && (personas || initialTab !== "personas") ? initialTab : "appearance";
  const [tab, setTab] = useState<SetTab>(wanted);

  return (
    <main className="flex-1 min-w-0 flex bg-paper">
      <nav className="page-subnav w-[208px] shrink-0 border-r border-line bg-panel/40 px-3 py-4">
        <div className="px-2 text-[13.5px] font-semibold mb-3 flex items-center gap-2">
          <Icon name="gear" size={16} /> {t("settings.settings")}
        </div>
        {tabs.map((entry) => {
          const active = tab === entry.key;
          return (
            <button
              key={entry.key}
              className={
                "w-full text-left px-2.5 py-2 rounded-lg text-[13px] flex items-center gap-2 " +
                (active ? "bg-paper text-accent font-medium" : "text-muted hover:bg-paper hover:text-ink")
              }
              onClick={() => setTab(entry.key)}
            >
              <Icon name={entry.icon} size={15} /> {t(entry.labelKey)}
            </button>
          );
        })}
      </nav>

      <div className="flex-1 min-w-0 overflow-y-auto hairline-scroll">
        <div className="max-w-3xl mx-auto px-7 py-6">
          {tab === "remote" ? (
            <RemoteHostsSection />
          ) : tab === "appearance" ? (
            <AppearanceSection />
          ) : tab === "models" ? (
            <section>
              <PanelHead
                title={t("settings.models")}
                sub="Providers and the models offered in the composer's picker. Keys are stored only on this computer."
              />
              <ModelsTab />
              {/* Token savings is model-spend behavior, so it lives here (UX-021),
                  not under General. */}
              <div className="mt-6">
                <TokenSavingsCard />
                <CompactionCard />
              </div>
            </section>
          ) : tab === "voice" ? (
            <VoiceInputSection />
          ) : (
            <PersonasSection onOpenPersona={onOpenPersona} />
          )}
        </div>
      </div>
    </main>
  );
}

function RemoteHostsSection() {
  const [hosts, setHosts] = useState<RvmHostInfo[]>([]);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [vncPassword, setVncPassword] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [probeState, setProbeState] = useState<Record<string, RemoteHostProbeResult>>({});
  const [testing, setTesting] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [lastSeen, setLastSeen] = useState<Record<string, number>>({});
  const refresh = async () => {
    const listed = await listRvmHosts().catch(() => []);
    setHosts(listed || []);
    for (const host of listed || []) {
      void test(host.id);
    }
  };
  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 30_000);
    return () => window.clearInterval(timer);
  }, []);
  const save = async () => {
    setError(null);
    try {
      await saveRvmHost(name, name, url, token);
      setToken("");
      setEditing(null);
      setSaved(true);
      refresh();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : typeof e === "string"
            ? e
            : "Could not save remote host.",
      );
    }
  };
  const test = async (hostName: string) => {
    setHostProbeResult(hostName, { status: "checking", error: "Checking connection…" });
    setProbeState((current) => ({
      ...current,
      [hostName]: { status: "unknown", error: "Checking connection…" },
    }));
    setTesting(hostName);
    try {
      const result = await testRvmHost(hostName) as RemoteHostProbeResult;
      if (result.status === "online") setLastSeen((current) => ({ ...current, [hostName]: Date.now() }));
      setProbeState((current) => ({ ...current, [hostName]: result }));
      setHostProbeResult(hostName, result);
    } catch (error) {
      const result: RemoteHostProbeResult = {
        status: "offline",
        error: error instanceof Error ? error.message : "Connection test failed.",
      };
      setProbeState((current) => ({ ...current, [hostName]: result }));
      setHostProbeResult(hostName, result);
    } finally {
      setTesting(null);
    }
  };
  const statusLabel = (status: RemoteHostProbeResult["status"]) =>
    status === "online" ? "online" :
    status === "auth_failed" ? "auth failed" :
    status === "offline" ? "offline" : "unknown";
  const currentFormResult = probeState[name];
  return (
    <section>
      <PanelHead
        title={t("settings.rvmRemoteVirtualMachines")}
        sub="Connect a remote host for shared development. Run node agent.js on the remote machine to start the agent."
      />
      <div className={`${CARD} p-4 space-y-3`}>
        {hosts.map((host) => (
          <div key={host.id} className="flex items-center gap-3 border-b border-line pb-3">
            <div className="min-w-0 flex-1">
              <div className="text-[13px] font-medium">
                {host.name}
                <span className="ml-2 text-[11px] text-muted">
                  {probeState[host.id]?.error === "Checking connection…"
                    ? "checking"
                    : statusLabel(probeState[host.id]?.status || "unknown")}
                </span>
              </div>
              <div className="text-[12px] text-muted truncate">{host.base_url || "Configured remote host"}</div>
              {probeState[host.id] && (
                <div className="text-[11px] text-muted">
                  {probeState[host.id].error === "Checking connection…"
                    ? "checking"
                    : probeState[host.id].latency_ms != null
                      ? `${probeState[host.id].latency_ms} ms`
                      : ""}
                  {probeState[host.id]?.health?.platform && ` · ${probeState[host.id]?.health?.platform}`}
                  {probeState[host.id]?.health?.host && ` · ${probeState[host.id]?.health?.host}`}
                  {probeState[host.id]?.health?.version && ` · v${probeState[host.id]?.health?.version}`}
                  {probeState[host.id]?.info?.hostname && ` · ${probeState[host.id]?.info?.hostname}`}
                  {probeState[host.id]?.health?.vnc_port != null && " · VNC"}
                  {probeState[host.id]?.health?.ide_port != null && " · IDE"}
                  {probeState[host.id]?.info?.cpus != null && ` · ${probeState[host.id]?.info?.cpus} CPU`}
                  {probeState[host.id]?.info?.memory_gb != null && ` · ${probeState[host.id]?.info?.memory_gb} GB`}
                  {lastSeen[host.id] && ` · Last seen: ${new Date(lastSeen[host.id]).toLocaleString()}`}
                  {probeState[host.id]?.health?.capabilities?.length && ` · ${probeState[host.id]?.health?.capabilities?.join(", ")}`}
                  {probeState[host.id]?.error && probeState[host.id].error !== "Checking connection…" && ` · ${probeState[host.id].error}`}
                </div>
              )}
            </div>
            <button
              className={BTN_BORDERED}
              disabled={testing === host.id}
              onClick={() => test(host.id)}
            >
              {testing === host.id ? "Testing…" : "Test connection"}
            </button>
            <button className="text-[12px]" onClick={() => {
              setEditing(host.id);
              setName(host.name);
              setUrl(host.base_url || "");
              setToken("");
              setVncPassword("");
            }}>
              Edit
            </button>
            <button className="text-[12px] text-danger" onClick={() => deleteRvmHost(host.id).then(refresh)}>
              Delete
            </button>
          </div>
        ))}
        <div className="pt-2 text-[12px] font-medium">{editing ? "Edit host" : "Add host"}</div>
        <input className={INPUT} placeholder={t("settings.eGLinuxDevServer")} value={name} onChange={(e) => setName(e.target.value)} />
        <input className={INPUT} placeholder="http://192.168.1.100:9920 or https://xxx.trycloudflare.com" value={url} onChange={(e) => setUrl(e.target.value)} />
        <input className={INPUT} type="password" placeholder={t("settings.tokenShownWhenAgentJsStarts")} value={token} onChange={(e) => setToken(e.target.value)} />
        <input className={INPUT} type="password" placeholder={t("settings.leaveEmptyReuseToken")} value={vncPassword} onChange={(e) => setVncPassword(e.target.value)} />
        <button
          className={BTN_BORDERED}
          disabled={!name || !url || !token || testing === name}
          onClick={async () => {
            await save();
            await test(name);
          }}
        >
          {testing === name ? "Testing…" : "Test connection"}
        </button>
        {currentFormResult && (
          <div role="status" className="text-[12px] text-muted">
            {statusLabel(currentFormResult.status)}
            {currentFormResult.latency_ms != null && ` · ${currentFormResult.latency_ms} ms`}
            {currentFormResult.health?.platform && ` · ${currentFormResult.health.platform}`}
            {currentFormResult.health?.version && ` · v${currentFormResult.health.version}`}
            {currentFormResult.info?.hostname && ` · ${currentFormResult.info.hostname}`}
            {currentFormResult.health?.vnc_port != null && " · VNC"}
            {currentFormResult.health?.ide_port != null && " · IDE"}
            {currentFormResult.info?.cpus != null && ` · ${currentFormResult.info.cpus} CPU`}
            {currentFormResult.error && ` · ${currentFormResult.error}`}
          </div>
        )}
        <button className={BTN_ACCENT} disabled={!name || !url || !token} onClick={save}>{editing ? "Save" : "Add"}</button>
        {editing && <button className={BTN_BORDERED} onClick={() => {
          setEditing(null); setName(""); setUrl(""); setToken(""); setVncPassword("");
        }}>{t("settings.cancel")}</button>}
        {saved && <div className="text-[12px] text-accent">{t("settings.remoteHostsSaved")}</div>}
        {error && <div role="alert" className="text-[12px] text-danger">{error}</div>}
      </div>
    </section>
  );
}

// -- Voice input: deliberate model provisioning + compatibility + microphone test (§37) --------
const voiceError = (error: unknown) =>
  error instanceof Error ? error.message : typeof error === "string" ? error : "Voice Input could not complete that action.";

const formatBytes = (bytes: number) => {
  if (!bytes) return "0 MiB";
  return `${Math.round(bytes / 1024 / 1024)} MiB`;
};

function VoiceInputSection() {
  const [status, setStatus] = useState<DictationStatus | null>(null);
  const [progress, setProgress] = useState<DictationDownloadProgress | null>(null);
  const [phase, setPhase] = useState<"idle" | "downloading" | "verifying" | "testing" | "transcribing">("idle");
  const [error, setError] = useState<string | null>(null);
  const [testTranscript, setTestTranscript] = useState("");
  const desktop = isTauri();

  const publish = (next: DictationStatus) => {
    setStatus(next);
    window.dispatchEvent(new CustomEvent("coworker:voice-input-changed", { detail: next }));
  };

  useEffect(() => {
    if (!desktop) return;
    let active = true;
    let unlisten = () => {};
    void listenDictationDownloadProgress((next) => {
      if (active) setProgress(next);
    }).then((stop) => {
      unlisten = stop;
    });
    void getDictationStatus().then(async (initial) => {
      if (!active || !initial) return;
      publish(initial);
      // One-time migration for models installed by the first STT cut, before verification markers.
      if (initial.model_installed && !initial.model_verified) {
        setPhase("verifying");
        try {
          const verified = await verifyDictationModel();
          if (active) publish(verified);
        } catch (verifyError) {
          if (active) setError(voiceError(verifyError));
        } finally {
          if (active) setPhase("idle");
        }
      }
    });
    return () => {
      active = false;
      unlisten();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [desktop]);

  const download = async () => {
    setError(null);
    setProgress({ downloaded_bytes: 0, total_bytes: status?.model_bytes || 0 });
    setPhase("downloading");
    try {
      publish(await downloadDictationModel());
    } catch (downloadError) {
      setError(voiceError(downloadError));
      const latest = await getDictationStatus();
      if (latest) publish(latest);
    } finally {
      setPhase("idle");
    }
  };

  const cancelDownload = async () => {
    await cancelDictationModelDownload().catch(() => undefined);
  };

  const repair = async () => {
    setError(null);
    try {
      publish(await deleteDictationModel());
      await download();
    } catch (repairError) {
      setError(voiceError(repairError));
    }
  };

  const remove = async () => {
    if (!window.confirm("Delete the local Whisper model and disable Voice Input?")) return;
    setError(null);
    try {
      publish(await deleteDictationModel());
      setTestTranscript("");
      setProgress(null);
    } catch (deleteError) {
      setError(voiceError(deleteError));
    }
  };

  const toggleTest = async () => {
    if (!status?.supported || !status.model_verified) return;
    setError(null);
    try {
      if (status.recording) {
        setPhase("transcribing");
        const transcript = (await stopDictation()).trim();
        setTestTranscript(transcript);
        if (!transcript) throw new Error("No speech was detected. Try again and speak for a little longer.");
        publish(await markDictationTestPassed());
      } else {
        setTestTranscript("");
        setPhase("testing");
        publish(await startDictation());
      }
    } catch (testError) {
      setError(voiceError(testError));
      const latest = await getDictationStatus();
      if (latest) publish(latest);
    } finally {
      setPhase("idle");
    }
  };

  const downloading = phase === "downloading" || !!status?.download_in_progress;
  const progressTotal = progress?.total_bytes || status?.model_bytes || 1;
  const progressPercent = Math.min(100, Math.round(((progress?.downloaded_bytes || 0) / progressTotal) * 100));
  const ready = !!status?.supported && !!status?.model_verified && !!status?.test_passed;

  return (
    <section>
      <PanelHead
        title={t("settings.voiceInput")}
        sub="Speak naturally in the composer. Recordings and transcripts stay on this device."
      />

      {!desktop ? (
        <div className={CARD + " p-4 text-[13px] text-muted"}>{t("settings.voiceSetupAvailable")}</div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-xl border border-green-200 bg-green-50/70 px-4 py-3 text-[12.5px] text-green-800">
            <span className="font-medium">{t("settings.privateDesign")}</span> Audio is held in memory only while you record and is transcribed locally.
          </div>

          <div className={CARD}>
            <div className="p-4 flex items-start gap-3">
              <Icon name="code" size={18} className="text-accent mt-0.5" />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium">{t("settings.device")}</div>
                <div className="text-[12px] text-muted mt-1">{status?.device_summary || "Checking compatibility…"}</div>
                {status?.compatibility_reason && <div className="text-[12px] text-red-600 mt-1.5">{status.compatibility_reason}</div>}
              </div>
              {status && (
                <span className={"text-[11.5px] px-2 py-1 rounded-full " + (status.supported ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600")}>
                  {status.supported ? "● Compatible" : "Unsupported"}
                </span>
              )}
            </div>
            <div className="border-t border-line bg-paper/50 px-4 py-3 grid grid-cols-2 gap-3 text-[12px] text-muted">
              <div><span className="block text-ink font-medium">Mac</span>{t("settings.macos12AppleSiliconM1")}</div>
              <div><span className="block text-ink font-medium">Windows</span>{t("settings.windows1022H211X64")}</div>
              <div><span className="block text-ink font-medium">Memory</span>{t("settings.8GbRecommended")}</div>
              <div><span className="block text-ink font-medium">Processor</span>{t("settings.4CpuCoresRecommended")}</div>
            </div>
          </div>

          <div className={CARD}>
            <div className="p-4 flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-accentSoft text-accent grid place-items-center font-semibold">W</div>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium">{t("settings.whisperBaseEnglish")}</div>
                <div className="text-[12px] text-muted mt-0.5">
                  {status?.model_verified ? `Installed and verified · ${formatBytes(status.model_bytes)}` : `Local voice model · ${formatBytes(status?.model_bytes || 147_964_211)}`}
                </div>
              </div>
              {status?.model_verified ? (
                <>
                  <span className="text-[11.5px] px-2 py-1 rounded-full bg-green-50 text-green-700">Verified</span>
                  <button className={BTN_BORDERED} onClick={() => void repair()}>Repair</button>
                  <button className="text-[12px] text-red-600 px-2 py-2" onClick={() => void remove()}>{t("settings.delete")}</button>
                </>
              ) : downloading ? (
                <button className={BTN_BORDERED} onClick={() => void cancelDownload()}>{t("settings.cancel")}</button>
              ) : phase === "verifying" ? (
                <span className="text-[12px] text-muted">{t("settings.verifying")}</span>
              ) : (
                <button className={BTN_ACCENT} disabled={!status?.supported} onClick={() => void download()}>{t("settings.downloadModel")}</button>
              )}
            </div>
            {downloading && (
              <div className="border-t border-line px-4 py-3">
                <div className="h-1.5 rounded-full bg-line overflow-hidden"><div className="h-full bg-accent transition-all" style={{ width: `${progressPercent}%` }} /></div>
                <div className="mt-1.5 text-[11.5px] text-muted flex"><span>{formatBytes(progress?.downloaded_bytes || 0)} of {formatBytes(progressTotal)}</span><span className="ml-auto">{progressPercent}%</span></div>
              </div>
            )}
          </div>

          <div className={CARD}>
            <div className="p-4 flex items-center gap-3">
              <Icon name="mic" size={18} className={ready ? "text-green-600" : "text-muted"} />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-medium">{t("settings.microphoneTest")}</div>
                <div className="text-[12px] text-muted mt-0.5">
                  {ready ? "Your microphone and local transcription engine are working." : "Record a short phrase to enable the composer microphone."}
                </div>
              </div>
              {ready && <span className="text-[11.5px] px-2 py-1 rounded-full bg-green-50 text-green-700">{t("settings.ready")}</span>}
              <button className={BTN_BORDERED} disabled={!status?.supported || !status?.model_verified || phase === "transcribing"} onClick={() => void toggleTest()}>
                {status?.recording ? "Stop and check" : phase === "transcribing" ? "Transcribing…" : ready ? "Test again" : "Test microphone"}
              </button>
            </div>
            {status?.recording && <div className="border-t border-line px-4 py-3 text-[12px] text-accent" role="status">{t("settings.listeningSpeakShortPhraseThenStop")}</div>}
            {testTranscript && <div className="border-t border-line bg-paper/50 px-4 py-3 text-[13px]">“{testTranscript}”</div>}
          </div>

          {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-[12px] text-red-700">{error}</div>}
        </div>
      )}
    </section>
  );
}

// -- Personas: installed/enabled/delete management, the dir/Git importer, and the
// entry point to the Persona Gallery (a screen-sized modal — installs finish back
// here, disabled pending consent; a gallery install re-mounts the list in place).
function PersonasSection({ onOpenPersona }: { onOpenPersona?: (id: string) => void }) {
  const [galleryBump, setGalleryBump] = useState(0);
  const [galleryOpen, setGalleryOpen] = useState(false);

  return (
    <section>
      <PanelHead
        title={t("settings.personas")}
        sub="Which coworkers are enabled and shown in the picker, plus installing new persona bundles."
      />
      <PersonasTab key={galleryBump} onOpenPersona={onOpenPersona} />
      <button
        className="mt-6 w-full rounded-xl2 border border-line bg-panel px-4 py-3.5 flex items-center gap-3 text-left hover:border-lineStrong"
        data-testid="gallery-link"
        onClick={() => setGalleryOpen(true)}
      >
        <Icon name="sparkle" size={16} className="text-accent shrink-0" />
        <span className="min-w-0 flex-1">
          <span className="block text-[13.5px] font-medium">{t("settings.browsePersonaGallery")}</span>
          <span className="block text-[12px] text-muted">
            Curated coworkers from the OpenWorker team — see what each can do before installing.
          </span>
        </span>
        <span className="text-[12.5px] text-accent shrink-0">{t("settings.open")}</span>
      </button>
      {galleryOpen && (
        <GalleryModal
          onClose={() => setGalleryOpen(false)}
          onInstalled={() => setGalleryBump((b) => b + 1)}
        />
      )}
    </section>
  );
}

// -- Appearance + app behaviour ------------------------------------------------
function AppearanceSection() {
  const [theme, setTheme] = useThemePref();
  const { locale, setLocale } = useI18n();
  const [autostart, setAuto] = useState(false);
  const [keepAwake, setKeep] = useState(false);
  const desktop = isTauri();

  useEffect(() => {
    if (isTauri()) {
      getAutostart().then((v) => setAuto(!!v));
      getKeepAwake().then((v) => setKeep(!!v));
    }
  }, []);

  const toggleAuto = async (v: boolean) => setAuto(!!(await setAutostart(v)));
  const toggleKeep = async (v: boolean) => setKeep(!!(await setKeepAwake(v)));
  const runSetupAgain = async () => {
    await setOnboarded(false);
    window.dispatchEvent(new CustomEvent("coworker:open-onboarding"));
  };

  return (
    <section>
      <PanelHead title={t("settings.general")} sub="How OpenWorker looks and behaves on this machine." />

      <div className={CARD + " p-4 mb-4"}>
        <div className={FIELD_LABEL}>{t("settings.theme")}</div>
        <div className="seg mt-2.5" role="radiogroup" aria-label={t("settings.appearance")}>
          {(["light", "dark", "auto"] as const).map((p) => (
            <button key={p} className={p === theme ? "active" : ""} onClick={() => setTheme(p)}>
              {p === "light" ? t("settings.light") : p === "dark" ? t("settings.dark") : t("settings.auto")}
            </button>
          ))}
        </div>
        <div className={FIELD_HELP}>{t("settings.autoFollowsMacAppearance")}</div>
      </div>

      <div className={CARD + " p-4 mb-4"}>
        <div className={FIELD_LABEL}>{t("settings.languageLabel")}</div>
        <select
          className={INPUT + " mt-2.5"}
          value={locale}
          onChange={(event) => void setLocale(event.target.value as "en" | "zh-CN")}
          aria-label={t("settings.language")}
        >
          {availableLocales().map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </div>

      <SidebarCard />

      <FilesCard />

      <TrustedWorkspacesCard />

      {desktop && (
        <div className={CARD + " p-4"}>
          <div className={FIELD_LABEL + " mb-2.5"}>{t("settings.always")}</div>
          <label className="flex items-start gap-3 py-2">
            <input type="checkbox" className="mt-0.5" checked={autostart} onChange={(e) => toggleAuto(e.target.checked)} />
            <span>
              <span className="block text-[13px] text-ink">{t("settings.openLogin")}</span>
              <span className="block text-[12px] text-muted">{t("settings.launchOnSignIn")}</span>
            </span>
          </label>
          <label className="flex items-start gap-3 py-2">
            <input type="checkbox" className="mt-0.5" checked={keepAwake} onChange={(e) => toggleKeep(e.target.checked)} />
            <span>
              <span className="block text-[13px] text-ink">{t("settings.keepSystemAwake")}</span>
              <span className="block text-[12px] text-muted">{t("settings.preventIdleSleep")}</span>
            </span>
          </label>
        </div>
      )}

      {/* One card for the app-lifecycle actions (UX-021): the onboarding replay (§24 —
          every build, the browser dev shell runs the same first-run flow) and, on
          desktop, the manual update check (launch also checks automatically). */}
      <div className={CARD + " p-4 mt-4"}>
        <div className={FIELD_LABEL + " mb-2"}>{t("settings.setupUpdates")}</div>
        <div className="flex items-center gap-2">
          <button className={BTN_BORDERED} onClick={runSetupAgain}>
            {t("settings.runSetupAgain")}
          </button>
          {desktop && <UpdateInline />}
        </div>
        <div className={FIELD_HELP}>{t("settings.replayFirstRunSetup")}</div>
      </div>
    </section>
  );
}

function TrustedWorkspacesCard() {
  const [workspaces, setWorkspaces] = useState<WorkspaceCommandTrust[] | null>(null);

  const refresh = () =>
    getTrustedWorkspaces()
      .then(setWorkspaces)
      .catch(() => setWorkspaces([]));

  useEffect(() => {
    refresh();
  }, []);

  const revoke = async (path: string) => {
    if (!window.confirm(`Revoke command trust for ${path}?`)) return;
    await setWorkspaceTrusted(path, false);
    refresh();
  };

  return (
    <div className={CARD + " p-4 mb-4"} data-testid="trusted-workspaces-card">
      <div className={FIELD_LABEL}>{t("settings.trustedWorkspaces")}</div>
      <div className={FIELD_HELP}>
        Trusted projects may manage their command allowances in .coworker/config.toml.
      </div>
      {workspaces === null ? (
        <div className="text-[12px] text-muted mt-3">{t("settings.loading")}</div>
      ) : workspaces.length === 0 ? (
        <div className="text-[12px] text-muted mt-3">{t("settings.noWorkspacesTrusted")}</div>
      ) : (
        <div className="mt-3 divide-y divide-line">
          {workspaces.map((workspace) => (
            <div key={workspace.workspace} className="py-2.5 flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-[12.5px] text-ink break-all">{workspace.workspace}</div>
                <div className="text-[11.5px] text-muted mt-0.5">
                  {workspace.requested_commands.length
                    ? `${workspace.requested_commands.length} project command allowance${workspace.requested_commands.length === 1 ? "" : "s"}`
                    : "No project command allowances currently declared"}
                  {!workspace.exists ? " · Folder unavailable" : ""}
                </div>
              </div>
              <button
                className="text-[12px] text-red-600 px-2 py-1"
                onClick={() => void revoke(workspace.workspace)}
              >
                Revoke
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function UpdateInline() {
  const [state, setState] = useState<"idle" | "checking" | "none" | "found" | "installing" | "error">("idle");
  const [version, setVersion] = useState("");

  const check = async () => {
    setState("checking");
    try {
      const u = await checkForUpdate();
      if (u) {
        setVersion(u.version);
        setState("found");
      } else {
        setState("none");
      }
    } catch {
      setState("error");
    }
  };

  const install = async () => {
    setState("installing");
    try {
      await installUpdate(); // success restarts the app
    } catch {
      setState("error");
    }
  };

  return (
    <span className="inline-flex items-center gap-2.5">
      {state === "found" ? (
        <button className={BTN_BORDERED} onClick={install} data-testid="settings-update-install">
          Update to v{version} and restart
        </button>
      ) : (
        <button
          className={BTN_BORDERED}
          onClick={check}
          disabled={state === "checking" || state === "installing"}
          data-testid="settings-update-check"
        >
          {state === "checking" ? t("settings.checkingForUpdates") : t("settings.checkForUpdates")}
        </button>
      )}
      {(state === "none" || state === "error" || state === "installing") && (
        <span className="text-[12px] text-muted">
          {state === "none"
            ? "You're on the latest version."
            : state === "error"
              ? "Couldn't check right now — try again later."
              : "Downloading — OpenWorker restarts by itself when it's ready."}
        </span>
      )}
    </span>
  );
}

// Telemetry/Privacy card removed for this release (owner ask 2026-07-22); the
// setCloudTelemetry API stays for a future opt-out surface.

// -- Sidebar density -------------------------------------------------------------
// -- Token savings (PDF attachments; owner ask, 2026-07-17) ---------------------
// Attachments replay with EVERY turn, so a big PDF quietly multiplies token spend.
// This card is the attachment dial: attach thresholds + the fallback for models
// without native PDF support. (Long-history spend is handled by auto-compaction —
// the CompactionCard below, OPE-27.)
function TokenSavingsCard() {
  const [pdf, setPdf] = useState<PdfSettings | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) =>
        setPdf({
          pdf_fallback: s.pdf_fallback || "text",
          pdf_max_pages: s.pdf_max_pages || 20,
          pdf_max_mb: s.pdf_max_mb || 10,
        }),
      )
      .catch(() => setPdf({ pdf_fallback: "text", pdf_max_pages: 20, pdf_max_mb: 10 }));
  }, []);

  const save = async (patch: Partial<PdfSettings>) => {
    setPdf((p) => (p ? { ...p, ...patch } : p));
    await setPdfSettings(patch);
  };

  if (!pdf) return null;
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="token-savings-card">
      <div className={FIELD_LABEL}>{t("settings.tokenSavings")}</div>
      <div className={FIELD_HELP}>
        PDF attachments travel with every turn of a conversation, so large documents multiply
        what you spend on tokens.
      </div>

      <div className="mt-3 text-[13px] text-ink">{t("settings.pdfsModelsWithoutNativePdfSupport")}</div>
      <div className="seg mt-2" role="radiogroup" aria-label={t("settings.pdfFallback")} data-testid="pdf-fallback">
        <button
          className={pdf.pdf_fallback === "text" ? "active" : ""}
          onClick={() => save({ pdf_fallback: "text" })}
        >
          Extract text
        </button>
        <button
          className={pdf.pdf_fallback === "images" ? "active" : ""}
          onClick={() => save({ pdf_fallback: "images" })}
        >
          Send page images
        </button>
      </div>
      <div className={FIELD_HELP}>
        Claude, GPT and Gemini read PDFs natively — this only applies to models that
        don&rsquo;t (GLM, Kimi, DeepSeek, local models…). Text extraction is cheapest; page
        images cost more tokens and need a vision-capable model.
      </div>

      <div className="mt-3 flex items-center gap-5">
        <label className="flex items-center gap-2.5">
          <span className="text-[13px] text-ink">{t("settings.maxPages")}</span>
          <input
            type="number"
            min={1}
            max={100}
            value={pdf.pdf_max_pages}
            data-testid="pdf-max-pages"
            className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) => save({ pdf_max_pages: Math.max(1, Math.min(Number(e.target.value) || 20, 100)) })}
          />
        </label>
        <label className="flex items-center gap-2.5">
          <span className="text-[13px] text-ink">{t("settings.maxSize")}</span>
          <input
            type="number"
            min={1}
            max={10}
            value={pdf.pdf_max_mb}
            data-testid="pdf-max-mb"
            className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) => save({ pdf_max_mb: Math.max(1, Math.min(Number(e.target.value) || 10, 10)) })}
          />
          <span className="text-[12.5px] text-muted">{t("settings.mb")}</span>
        </label>
      </div>
      <div className={FIELD_HELP}>
        PDFs over these limits are not attached — you&rsquo;ll see a notice in the composer
        instead.
      </div>
    </div>
  );
}

// -- Context compaction (OPE-27) ------------------------------------------------
// Long sessions are summarized automatically when they approach the model's context
// limit, so work continues instead of hitting a raw provider error. Two spec'd
// overrides (trigger % + token cap) and the summarizer-model pin — nothing more.
function CompactionCard() {
  const [cfg, setCfg] = useState<CompactionSettings | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [labels, setLabels] = useState<Record<string, string>>({});

  useEffect(() => {
    getSettings()
      .then((s) => {
        setCfg({
          compaction_threshold_pct: s.compaction_threshold_pct ?? 0.8,
          compaction_cap_tokens: s.compaction_cap_tokens ?? 250_000,
          compaction_model: s.compaction_model ?? "",
        });
        setModels(s.models || []);
        setLabels(s.model_labels || {});
      })
      .catch(() =>
        setCfg({
          compaction_threshold_pct: 0.8,
          compaction_cap_tokens: 250_000,
          compaction_model: "",
        }),
      );
  }, []);

  const save = async (patch: Partial<CompactionSettings>) => {
    setCfg((p) => (p ? { ...p, ...patch } : p));
    await setCompactionSettings(patch);
  };

  if (!cfg) return null;
  const modelLabel = (id: string) => labels[id]?.split(" · ")[0] || id;
  return (
    <div className={CARD + " p-4 mb-4"} data-testid="compaction-card">
      <div className={FIELD_LABEL}>{t("settings.contextCompaction")}</div>
      <div className={FIELD_HELP}>
        Long sessions are compacted automatically: older turns are summarized so the
        coworker keeps working instead of running out of context. Your visible transcript
        is never changed — a small marker shows where compaction happened.
      </div>

      <div className="mt-3 flex items-center gap-5 flex-wrap">
        <label className="flex items-center gap-2.5">
          <span className="text-[13px] text-ink">{t("settings.compact")}</span>
          <input
            type="number"
            min={10}
            max={95}
            value={Math.round(cfg.compaction_threshold_pct * 100)}
            data-testid="compaction-threshold"
            className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) =>
              save({
                compaction_threshold_pct:
                  Math.max(10, Math.min(Number(e.target.value) || 80, 95)) / 100,
              })
            }
          />
          <span className="text-[12.5px] text-muted">{t("settings.contextWindow")}</span>
        </label>
        <label className="flex items-center gap-2.5">
          <span className="text-[13px] text-ink">{t("settings.label")}</span>
          <input
            type="number"
            min={10_000}
            max={2_000_000}
            step={10_000}
            value={cfg.compaction_cap_tokens}
            data-testid="compaction-cap"
            className="w-28 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
            onChange={(e) =>
              save({
                compaction_cap_tokens: Math.max(
                  10_000,
                  Math.min(Number(e.target.value) || 250_000, 2_000_000),
                ),
              })
            }
          />
          <span className="text-[12.5px] text-muted">{t("settings.tokensWhicheverSmaller")}</span>
        </label>
      </div>
      <div className={FIELD_HELP}>
        The cap makes very-large-context models compact early — quality and speed degrade
        well before their nominal limit.
      </div>

      <div className="mt-3 flex items-center gap-2.5">
        <span className="text-[13px] text-ink">{t("settings.summarizerModel")}</span>
        <select
          value={cfg.compaction_model}
          data-testid="compaction-model"
          className="px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
          onChange={(e) => save({ compaction_model: e.target.value })}
        >
          <option value="">{t("settings.sessionOwnModelDefault")}</option>
          {models.map((m) => (
            <option key={m} value={m}>
              {modelLabel(m)}
            </option>
          ))}
        </select>
      </div>
      <div className={FIELD_HELP}>
        The summary is written by this model. The default follows whatever model the
        session is using.
      </div>
    </div>
  );
}

function SidebarCard() {
  const [peek, setPeek] = useState<number | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => setPeek(s.sessions_peek || 5))
      .catch(() => setPeek(5));
  }, []);

  const save = async (n: number) => {
    const clamped = Math.max(1, Math.min(n || 5, 50));
    setPeek(clamped);
    await setSessionsPeek(clamped);
  };

  if (peek === null) return null;
  return (
    <div className={CARD + " p-4 mb-4"}>
      <div className={FIELD_LABEL}>{t("settings.sidebarLabel")}</div>
      <label className="flex items-center gap-3 mt-2.5">
        <span className="text-[13px] text-ink">{t("settings.conversationsShownPerCoworker")}</span>
        <input
          type="number"
          min={1}
          max={50}
          value={peek}
          className="w-16 px-2 py-1.5 rounded-lg border border-line bg-paper text-[13px] text-ink outline-none focus:border-accent"
          onChange={(e) => save(Number(e.target.value))}
        />
      </label>
      <div className={FIELD_HELP}>
        Longer lists collapse behind &ldquo;Show more&rdquo;. Applies per coworker and per project.
      </div>
    </div>
  );
}

// -- Files (scratch location) — one card inside General (UX-021: a single option
// doesn't earn its own tab) -----------------------------------------------------
function FilesCard() {
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [scratchDraft, setScratchDraft] = useState("");
  const [scratchMsg, setScratchMsg] = useState<string | null>(null);
  const desktop = isTauri();

  const refresh = () =>
    getSettings()
      .then((s) => {
        setSettings(s);
        setScratchDraft((d) => d || s.scratch_base || "");
      })
      .catch(() => setSettings(null));
  useEffect(() => {
    refresh();
  }, []);

  const saveScratch = async () => {
    setScratchMsg(null);
    const res = await setScratchBase(scratchDraft.trim());
    if (res.ok) {
      setScratchMsg("Saved. New conversations will use this location.");
      refresh();
    } else {
      setScratchMsg(res.error || "Could not use that location.");
    }
  };
  const browseScratch = async () => {
    const picked = await pickFolder();
    if (picked) setScratchDraft(picked);
  };

  if (!settings) return null;

  return (
    <div className={CARD + " p-4 mb-4"}>
      <div className={FIELD_LABEL}>{t("settings.files")}</div>
        <div className="flex items-center gap-2 mt-2.5">
          <input
            className={INPUT}
            type="text"
            placeholder={t("settings.openworker")}
            value={scratchDraft}
            spellCheck={false}
            autoComplete="off"
            onChange={(e) => setScratchDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && saveScratch()}
          />
          {desktop && (
            <button className={BTN_BORDERED} onClick={browseScratch} title={t("settings.pickFolder")}>
              {t("settings.browse")}
            </button>
          )}
          <button className={BTN_ACCENT} onClick={saveScratch} disabled={!scratchDraft.trim()}>
            {t("settings.save")}
          </button>
        </div>
      <div className={FIELD_HELP}>
        Each conversation gets its own folder under this location. Existing conversations keep their current
        folder; you can grant access to more folders inside any conversation.
      </div>
      {scratchMsg && <div className="text-[12.5px] text-muted mt-2.5">{scratchMsg}</div>}
    </div>
  );
}
