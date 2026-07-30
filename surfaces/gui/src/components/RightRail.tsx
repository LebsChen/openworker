import { t } from "../i18n";
import { useEffect, useRef, useState, type ReactNode } from "react";
// Emits the asset URL only; the worker itself loads lazily with the pdfjs chunk.
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import {
  getArtifacts,
  readArtifact,
  revealArtifact,
  type ArtifactContent,
  type ArtifactInfo,
  type SessionHost,
} from "../api";
import type { TodoItem } from "../types";
import type { Item } from "../types";
import { AccessSection } from "./AccessSection";
import { Icon } from "./Icon";
import { Markdown, OPEN_ARTIFACT_EVENT } from "./Markdown";
import { hostProbeResult, HOST_STATUS_CHANGED } from "../hostStatus";
import { selectWorklog, type WorklogEntry } from "../worklogSelector";
import { RemoteShellPanel } from "./RemoteShellPanel";

export type PanelTab = "info" | "worklog" | "changes" | "shell" | "ide" | "desktop";
const PANEL_TABS: { id: PanelTab; label: string; icon: "audit" | "clock" | "fileCode" | "terminal" | "code" | "monitor" }[] = [
  { id: "info", label: "Info", icon: "audit" },
  { id: "worklog", label: "Worklog", icon: "clock" },
  { id: "changes", label: "File changes", icon: "fileCode" },
  { id: "shell", label: "Shell", icon: "terminal" },
  { id: "ide", label: "Web IDE", icon: "code" },
  { id: "desktop", label: "Browser/Desktop", icon: "monitor" },
];
export const isRvmPanelTab = (tab: PanelTab): boolean =>
  tab === "shell" || tab === "ide" || tab === "desktop";

// Quiet file-type icons for the artifact list (the colored kind pills read as noisy).
function kindIcon(kind: string): "file" | "fileCode" | "image" | "table" {
  if (kind === "image") return "image";
  if (kind === "html" || kind === "code") return "fileCode";
  if (kind === "csv" || kind === "sheet") return "table";
  return "file"; // markdown, text, pdf, everything else
}

// Fallback kind for an artifact: link whose path isn't in the list (yet) — mirrors the
// server's extension mapping closely enough for the viewer to pick a renderer.
function kindFromPath(path: string): string {
  const ext = (path.split(".").pop() || "").toLowerCase();
  if (["png", "jpg", "jpeg", "gif", "svg", "webp"].includes(ext)) return "image";
  if (["html", "htm"].includes(ext)) return "html";
  if (ext === "md") return "markdown";
  if (ext === "csv") return "csv";
  if (ext === "pdf") return "pdf";
  if (["py", "js", "ts", "tsx", "jsx", "json", "sh", "css"].includes(ext)) return "code";
  return "text";
}

interface Props {
  active: boolean;
  sessionId: string;
  host: SessionHost;
  refreshKey: number;
  toolNames: string[];
  todo: TodoItem[];
  items: Item[];
  running: boolean;
  // Fires when a full artifact preview opens/closes, so the app can auto-collapse the left nav
  // to give the preview (PDF/webpage/sheet) more room (#3).
  onPreviewChange?: (open: boolean) => void;
  // §32: the rail is the ONE session panel for every non-chat persona. Artifacts stays
  // cowork-only (deliverables; code-family gets "Files" later — slot reserved); the Access
  // section (the former Session-settings drawer) renders for all.
  showArtifacts?: boolean;
  personaId?: string;
  projectScoped?: boolean;
  workspace?: string;
  branch?: string | null;
  scratchPrimary?: boolean;
  openAccessKey?: number;
  onOpenIntegrations?: () => void;
}

export function RightRail({
  active,
  sessionId,
  host,
  refreshKey,
  toolNames,
  todo,
  items,
  running,
  onPreviewChange,
  showArtifacts = true,
  personaId,
  projectScoped,
  workspace,
  branch,
  scratchPrimary,
  openAccessKey = 0,
  onOpenIntegrations,
}: Props) {
  const [tab, setTab] = useState<PanelTab>("info");
  const [panelOpen, setPanelOpen] = useState(true);
  const [artifacts, setArtifacts] = useState<ArtifactInfo[]>([]);
  const [selected, setSelected] = useState<ArtifactInfo | null>(null);
  const [content, setContent] = useState<ArtifactContent | null>(null);
  const [, setProbeVersion] = useState(0);
  const worklog = selectWorklog(items);
  const probe = host.local ? undefined : hostProbeResult(host.id);
  const isRvmTab = isRvmPanelTab(tab);

  const refreshArtifacts = () => getArtifacts(sessionId, host).then(setArtifacts).catch(() => setArtifacts([]));

  useEffect(() => {
    if (!active) return;
    if (showArtifacts) refreshArtifacts();
  }, [active, sessionId, host.id, refreshKey, showArtifacts]);

  // Switching conversations closes any open artifact — it belongs to the previous session's
  // workspace, which the new session can't (and shouldn't) read.
  useEffect(() => {
    setSelected(null);
    setContent(null);
    setTab("info");
    setPanelOpen(true);
  }, [sessionId]);

  useEffect(() => {
    const onStatus = () => {
      // The probe cache is shared with Settings/App; the event only exists to
      // force this panel to observe the latest result.
      setProbeVersion((version) => version + 1);
    };
    window.addEventListener(HOST_STATUS_CHANGED, onStatus);
    return () => window.removeEventListener(HOST_STATUS_CHANGED, onStatus);
  }, []);

  useEffect(() => {
    setContent(null);
    if (!selected) return;
    readArtifact(sessionId, selected.path, host).then(setContent).catch(() => setContent(null));
  }, [selected?.path, sessionId, host.id]);

  // Notify the app when a preview opens/closes (drives the left-nav auto-collapse).
  useEffect(() => {
    onPreviewChange?.(!!selected);
  }, [!!selected, onPreviewChange]);

  const reloadSelected = () => {
    if (!selected) return Promise.resolve();
    setContent(null);
    return readArtifact(sessionId, selected.path, host).then(setContent).catch(() => setContent(null));
  };

  // §34 (UX-016): [Title](artifact:path) chips in the transcript open the viewer directly.
  // Resolve against the loaded list first; on a miss, refresh once (the file may be
  // seconds old), then fall back to a minimal record — readArtifact validates the path.
  useEffect(() => {
    if (!active) return;
    const minimal = (path: string): ArtifactInfo => ({
      path,
      name: path.split("/").pop() || path,
      kind: kindFromPath(path),
      size: 0,
      modified_at: 0,
    });
    const match = (list: ArtifactInfo[], path: string) =>
      list.find((a) => a.path === path || a.path.endsWith("/" + path) || a.name === path);
    const onOpen = (e: Event) => {
      const path = String((e as CustomEvent).detail?.path || "");
      if (!path) return;
      const found = match(artifacts, path);
      if (found) {
        setSelected(found);
        return;
      }
      getArtifacts(sessionId, host)
        .then((list) => {
          setArtifacts(list);
          setSelected(match(list, path) ?? minimal(path));
        })
        .catch(() => setSelected(minimal(path)));
    };
    window.addEventListener(OPEN_ARTIFACT_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_ARTIFACT_EVENT, onOpen);
  }, [active, sessionId, host.id, artifacts]);

  if (!active) return null;

  return (
    <aside className={"right-panel-shell" + (!panelOpen ? " collapsed" : "") + (selected ? " artifact-mode" : "")}>
      <div className={"right-panel-drawer" + (panelOpen ? " open" : " collapsed")}>
      <div className="right-panel-tabbody">
        <div style={{ display: panelOpen && tab === "info" && !selected ? "block" : "none" }}>
          <InfoPanel
            host={host}
            probe={probe}
            running={running}
            toolNames={toolNames}
            todo={todo}
            sessionId={sessionId}
            personaId={personaId}
            projectScoped={projectScoped}
            workspace={workspace}
            branch={branch}
            scratchPrimary={scratchPrimary}
            openAccessKey={openAccessKey}
            onOpenIntegrations={onOpenIntegrations}
          />
        </div>
        <div style={{ display: panelOpen && tab === "worklog" && !selected ? "block" : "none" }}>
          <WorklogPanel entries={worklog} />
        </div>
        <div style={{ display: panelOpen && tab === "changes" && !selected ? "block" : "none" }}>
          <FileChangesPanel
            artifacts={artifacts}
            showArtifacts={showArtifacts}
            onRefresh={refreshArtifacts}
            onReveal={() => artifacts[0] && revealArtifact(sessionId, artifacts[0].path, host, "reveal")}
            onSelect={(artifact) => { setSelected(artifact); setTab("changes"); setPanelOpen(true); }}
          />
        </div>
        <div style={{ display: panelOpen && isRvmTab && !selected ? "block" : "none" }}>
          {tab === "shell" ? (
            <RemoteShellPanel active={panelOpen && tab === "shell"} sessionId={sessionId} host={host} />
          ) : (
            <RvmUnavailablePanel host={host} tab={tab} />
          )}
        </div>
      </div>
      {selected && (
        <ArtifactViewer
          sessionId={sessionId}
          host={host}
          artifact={selected}
          content={content}
          onReload={reloadSelected}
          onBack={() => { setSelected(null); setTab("changes"); }}
        />
      )}
      </div>
      <nav className="right-panel-icon-rail" aria-label={t("session.rail.sessionPanel")}>
        {PANEL_TABS.map((entry) => {
          const disabled = isRvmPanelTab(entry.id) && host.local;
          return (
            <button
              key={entry.id}
              type="button"
              className={"right-panel-rail-btn" + (panelOpen && tab === entry.id ? " active" : "")}
              disabled={disabled}
              title={disabled ? "Requires an RVM host" : entry.label}
              aria-label={entry.label}
              aria-pressed={panelOpen && tab === entry.id}
              onClick={() => {
                if (disabled) return;
                if (panelOpen && tab === entry.id) setPanelOpen(false);
                else { setTab(entry.id); setPanelOpen(true); }
              }}
            >
              <Icon name={entry.icon} size={17} />
            </button>
          );
        })}
      </nav>
    </aside>
  );
}

function InfoPanel({
  host,
  probe,
  running,
  toolNames,
  todo,
  sessionId,
  personaId,
  projectScoped,
  workspace,
  branch,
  scratchPrimary,
  openAccessKey,
  onOpenIntegrations,
}: {
  host: SessionHost;
  probe?: ReturnType<typeof hostProbeResult>;
  running: boolean;
  toolNames: string[];
  todo: TodoItem[];
  sessionId: string;
  personaId?: string;
  projectScoped?: boolean;
  workspace?: string;
  branch?: string | null;
  scratchPrimary?: boolean;
  openAccessKey: number;
  onOpenIntegrations?: () => void;
}) {
  return (
    <div className="right-panel-section">
      <h3 className="right-panel-heading">Info</h3>
      <div className="right-panel-host">
        <strong>{host.name}</strong>
        <span className={"right-panel-status " + (host.local ? "online" : (probe?.status || host.status || "unknown"))}>
          {host.local ? "online" : (probe?.status || host.status || "unknown").replace("_", " ")}
        </span>
      </div>
      {host.local ? (
        <div className="rail-muted">{t("session.rail.localSidecarUsedSession")}</div>
      ) : probe ? (
        <>
          {probe.error && <div className="rail-error">{probe.error}</div>}
          {probe.latency_ms !== undefined && <FieldRow label="Latency" value={`${probe.latency_ms} ms`} />}
          {probe.health?.platform && <FieldRow label="Platform" value={probe.health.platform} />}
          {(probe.health?.host || probe.info?.hostname) && <FieldRow label="Host" value={probe.health?.host || probe.info?.hostname || ""} />}
          {probe.health?.version && <FieldRow label="Version" value={probe.health.version} />}
          {!!probe.health?.capabilities?.length && <FieldRow label="Capabilities" value={probe.health.capabilities.join(", ")} />}
          {probe.health?.vnc_port != null && <FieldRow label="VNC" value="Available" />}
          {probe.health?.ide_port != null && <FieldRow label="IDE" value="Available" />}
        </>
      ) : (
        <div className="rail-muted">{t("session.rail.noRvmProbeResultYet")}</div>
      )}
      <RailSection title={t("session.rail.progress")} open onToggle={() => undefined}>
        <ProgressSummary running={running} toolNames={toolNames} todo={todo} />
      </RailSection>
      <AccessSection
        key={sessionId}
        sessionId={sessionId}
        host={host}
        personaId={personaId}
        projectScoped={projectScoped}
        workspace={workspace}
        branch={branch}
        scratchPrimary={scratchPrimary}
        openKey={openAccessKey}
        onOpenIntegrations={onOpenIntegrations}
      />
    </div>
  );
}

function FieldRow({ label, value }: { label: string; value: string }) {
  return <div className="right-panel-field"><span>{label}</span><strong>{value}</strong></div>;
}

function WorklogPanel({ entries }: { entries: WorklogEntry[] }) {
  return (
    <div className="right-panel-section">
      <h3 className="right-panel-heading">Worklog</h3>
      {!entries.length && <div className="rail-muted">{t("session.rail.noEventsYet")}</div>}
      <div className="right-panel-worklog">
        {entries.map((entry) => (
          <div className="right-panel-worklog-row" key={entry.id}>
            <span className={"right-panel-worklog-dot right-panel-worklog-dot--" + entry.kind} />
            <div>
              <strong>{entry.title}</strong>
              {entry.status && <span className="right-panel-worklog-status">{entry.status}</span>}
              {entry.filePaths?.length ? <div className="rail-muted">{entry.filePaths.join(", ")}</div> : null}
              {entry.detail && <pre>{entry.detail}</pre>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FileChangesPanel({
  artifacts,
  showArtifacts,
  onRefresh,
  onReveal,
  onSelect,
}: {
  artifacts: ArtifactInfo[];
  showArtifacts: boolean;
  onRefresh: () => void;
  onReveal: () => void;
  onSelect: (artifact: ArtifactInfo) => void;
}) {
  return (
    <div className="right-panel-section">
      <div className="right-panel-heading-row">
        <h3 className="right-panel-heading">{t("session.rail.fileChanges")}</h3>
        <div>
          <button className="rail-mini-btn" onClick={onRefresh} title={t("session.rail.refreshArtifacts")}><Icon name="refresh" size={13} /></button>
          {artifacts.length > 0 && <button className="rail-mini-btn" onClick={onReveal} title={t("session.rail.showArtifactFolder")}><Icon name="folder" size={13} /></button>}
        </div>
      </div>
      <h4 className="right-panel-subheading">{t("session.rail.workspaceChanges")}</h4>
      <div className="rail-muted">{t("session.rail.noWorkspaceDiffDataAvailableYet")}</div>
      <h4 className="right-panel-subheading">Artifacts</h4>
      {!showArtifacts || !artifacts.length ? (
        <div className="rail-muted">{t("session.rail.noPreviewableFilesYet")}</div>
      ) : (
        <div className="artifact-list">
          {artifacts.slice(0, 16).map((a) => (
            <button className="artifact-row" key={a.path} onClick={() => onSelect(a)}>
              <span className="artifact-ico" title={a.kind}><Icon name={kindIcon(a.kind)} size={17} /></span>
              <span className="artifact-name">{a.name}<span className="artifact-row-meta">{formatBytes(a.size)} · {formatTime(a.modified_at)}</span></span>
              <span className="artifact-open">Open</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function RvmUnavailablePanel({ host, tab }: { host: SessionHost; tab: PanelTab }) {
  return (
    <div className="right-panel-empty">
      <h3>{PANEL_TABS.find((entry) => entry.id === tab)?.label}</h3>
      <p>
        {host.local
          ? "Requires an RVM host. This session is bound to Local."
          : "Secure connection bootstrap is not implemented yet."}
      </p>
    </div>
  );
}

function ProgressSummary({ running, toolNames, todo }: { running: boolean; toolNames: string[]; todo: TodoItem[] }) {
  if (todo.length) {
    return (
      <div className="rail-todo-list">
        {todo.map((item, index) => (
          <div className={"rail-todo " + item.status} key={index}>
            <span className="rail-todo-mark" />
            <span>{item.content}</span>
          </div>
        ))}
        {running && (
          <div className="rail-muted">
            {toolNames.length ? `${toolNames.length} tool call${toolNames.length === 1 ? "" : "s"} so far.` : "Working..."}
          </div>
        )}
      </div>
    );
  }
  if (running) {
    return (
      <div className="rail-muted">
        Working on this task{toolNames.length ? ` with ${toolNames.length} tool call${toolNames.length === 1 ? "" : "s"} so far.` : "."}
      </div>
    );
  }
  return (
    <div className="rail-muted">
      For longer multi-step tasks, progress will appear here while OpenWorker plans, uses tools, waits for approval, and produces artifacts.
    </div>
  );
}

function RailSection({
  title,
  open,
  onToggle,
  children,
  action,
}: {
  title: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="rail-section">
      <div className="rail-section-head">
        <button className="rail-section-toggle" onClick={onToggle}>
          <Icon name={open ? "chevronDown" : "chevronRight"} size={14} className="rail-chev" />
          <span>{title}</span>
        </button>
        {action}
      </div>
      {open && <div className="rail-section-body">{children}</div>}
    </section>
  );
}

function ArtifactViewer({
  sessionId,
  host,
  artifact,
  content,
  onReload,
  onBack,
}: {
  sessionId: string;
  host: SessionHost;
  artifact: ArtifactInfo;
  content: ArtifactContent | null;
  onReload: () => Promise<void>;
  onBack: () => void;
}) {
  const [reloadKey, setReloadKey] = useState(0);
  const isHtml = content?.kind === "html" && !content.error;
  // Best viewed in a real app: spreadsheets, PDFs, and Office docs (pptx/docx can't preview inline)
  const isApp = content?.kind === "sheet" || content?.kind === "pdf" || content?.kind === "office";

  return (
    <div className="artifact-viewer">
      <div className="artifact-head">
        <button className="artifact-icon-btn" onClick={onBack} aria-label={t("session.rail.backArtifacts")} title={t("session.rail.back")}>
          <Icon name="arrowLeft" size={16} />
        </button>
        <div className="artifact-heading">
          <div className="artifact-title"><span>Artifacts</span><span className="artifact-sep">/</span><span>{artifact.name}</span></div>
          <div className="artifact-path">{artifact.path}</div>
        </div>
        <div className="rail-actions">
          {isHtml && (
            <button
              className="artifact-icon-btn"
              onClick={async () => {
                await onReload();
                setReloadKey((k) => k + 1);
              }}
              aria-label={t("session.rail.reloadPreview")}
              title={t("session.rail.reload")}
            >
              <Icon name="refresh" size={16} />
            </button>
          )}
          {isApp && (
            <button
              className="artifact-icon-btn"
              onClick={() => revealArtifact(sessionId, artifact.path, host, "open")}
              aria-label={t("session.rail.openDefaultApp")}
              title={t("session.rail.openDefaultApp")}
            >
              <Icon name="panelOpen" size={16} />
            </button>
          )}
          {/* Copy the ABSOLUTE path — the workspace-relative one is useless outside the app
              (tester catch 2026-07-12: it copied just "slack-connector-debug.md"). */}
          <button
            className="artifact-icon-btn"
            onClick={() => navigator.clipboard?.writeText(artifact.abs_path || artifact.path)}
            aria-label={t("session.rail.copyPath")}
            title={t("session.rail.copyFullPath")}
          >
            <Icon name="copy" size={16} />
          </button>
          <button
            className="artifact-icon-btn"
            onClick={() => revealArtifact(sessionId, artifact.path, host, "reveal")}
            aria-label={t("session.rail.showFolder")}
            title={t("session.rail.showFolder")}
          >
            <Icon name="folder" size={16} />
          </button>
        </div>
      </div>
      <div className="artifact-preview">
        {!content ? (
          <div className="rail-muted">Loading...</div>
        ) : content.error ? (
          <div className="rail-error">{content.error}</div>
        ) : content.kind === "html" ? (
          <iframe
            key={`${artifact.path}-${reloadKey}`}
            sandbox="allow-scripts allow-same-origin"
            className="artifact-frame"
            srcDoc={content.content || ""}
          />
        ) : content.kind === "markdown" ? (
          <div className="artifact-md">
            <Markdown text={content.content || ""} />
          </div>
        ) : content.kind === "image" ? (
          <img className="artifact-image" src={content.data_url} />
        ) : content.kind === "pdf" ? (
          <PdfViewer dataUrl={content.data_url || ""} />
        ) : content.kind === "csv" ? (
          <CsvTable text={content.content || ""} />
        ) : content.kind === "sheet" ? (
          <SheetViewer dataUrl={content.data_url || ""} />
        ) : content.kind === "office" ? (
          <div className="artifact-open-prompt">
            <Icon name="panelOpen" size={28} />
            <p>This {/\.pptx?$/i.test(artifact.name) ? "PowerPoint" : "Word"} file can’t be previewed here.</p>
            <button className="btn sm" onClick={() => revealArtifact(sessionId, artifact.path, host, "open")}>
              Open in default app
            </button>
          </div>
        ) : (
          <pre className="artifact-code">{content.content}</pre>
        )}
      </div>
    </div>
  );
}

const MAX_TABLE_ROWS = 500;

function GridTable({ rows, note }: { rows: unknown[][]; note?: string }) {
  const [head, ...body] = rows;
  return (
    <div className="artifact-tablewrap">
      <table className="artifact-table">
        {head && (
          <thead>
            <tr>{head.map((c, i) => <th key={i}>{String(c ?? "")}</th>)}</tr>
          </thead>
        )}
        <tbody>
          {body.slice(0, MAX_TABLE_ROWS).map((r, i) => (
            <tr key={i}>{r.map((c, j) => <td key={j}>{String(c ?? "")}</td>)}</tr>
          ))}
        </tbody>
      </table>
      {(note || body.length > MAX_TABLE_ROWS) && (
        <div className="rail-muted artifact-table-note">
          {note}
          {body.length > MAX_TABLE_ROWS ? ` Showing first ${MAX_TABLE_ROWS} of ${body.length} rows.` : ""}
        </div>
      )}
    </div>
  );
}

// Minimal RFC-4180-ish CSV parsing: quoted fields, escaped quotes, CRLF. TSV via tab sniffing.
function parseCsv(text: string): string[][] {
  const delim = text.includes("\t") && !text.split("\n")[0]?.includes(",") ? "\t" : ",";
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i++;
        } else quoted = false;
      } else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === delim) {
      row.push(cell);
      cell = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      cell = "";
      rows.push(row);
      row = [];
    } else cell += ch;
  }
  if (cell !== "" || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter((r) => r.some((c) => c !== ""));
}

function CsvTable({ text }: { text: string }) {
  const rows = parseCsv(text);
  if (!rows.length) return <div className="rail-muted artifact-table-note">{t("session.rail.emptyFile")}</div>;
  return <GridTable rows={rows} />;
}

// xlsx/xls preview via SheetJS (loaded on demand — it's a heavy module): sheet tabs + a capped
// grid. Real spreadsheet work belongs in Numbers/Excel via "Open in default app".
// WKWebView has no inline PDF plugin (<embed> shows a gray pane in the Tauri shell), so we
// rasterize pages with pdf.js onto stacked canvases — same lazy-chunk pattern as SheetViewer.
function PdfViewer({ dataUrl }: { dataUrl: string }) {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const holder = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError("");
    setLoading(true);
    const base64 = dataUrl.split(",")[1] || "";
    import("pdfjs-dist")
      .then(async (pdfjs) => {
        pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
        const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
        const doc = await pdfjs.getDocument({ data: bytes }).promise;
        const el = holder.current;
        if (cancelled || !el) return;
        el.innerHTML = "";
        const width = el.clientWidth || 640;
        const dpr = window.devicePixelRatio || 1;
        for (let i = 1; i <= doc.numPages; i++) {
          const page = await doc.getPage(i);
          const base = page.getViewport({ scale: 1 });
          const viewport = page.getViewport({ scale: (width / base.width) * dpr });
          const canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.className = "artifact-pdf-page";
          await page.render({ canvasContext: canvas.getContext("2d")!, viewport }).promise;
          if (cancelled) return;
          el.appendChild(canvas);
        }
        setLoading(false);
      })
      .catch((e) => !cancelled && setError(String(e?.message || e)));
    return () => {
      cancelled = true;
    };
  }, [dataUrl]);

  if (error) return <div className="rail-error artifact-table-note">Could not render PDF: {error}</div>;
  return (
    <div className="artifact-pdfjs">
      {loading && <div className="rail-muted artifact-table-note">{t("session.rail.renderingPdf")}</div>}
      <div ref={holder} />
    </div>
  );
}

function SheetViewer({ dataUrl }: { dataUrl: string }) {
  const [sheets, setSheets] = useState<{ name: string; rows: unknown[][] }[] | null>(null);
  const [error, setError] = useState("");
  const [active, setActive] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setSheets(null);
    setError("");
    setActive(0);
    const base64 = dataUrl.split(",")[1] || "";
    import("xlsx")
      .then((XLSX) => {
        if (cancelled) return;
        const wb = XLSX.read(base64, { type: "base64" });
        setSheets(
          wb.SheetNames.map((name) => ({
            name,
            rows: XLSX.utils.sheet_to_json(wb.Sheets[name], { header: 1, defval: "" }) as unknown[][],
          })),
        );
      })
      .catch((e) => !cancelled && setError(String(e?.message || e)));
    return () => {
      cancelled = true;
    };
  }, [dataUrl]);

  if (error) return <div className="rail-error artifact-table-note">Could not parse spreadsheet: {error}</div>;
  if (!sheets) return <div className="rail-muted artifact-table-note">{t("session.rail.parsingSpreadsheet")}</div>;
  const sheet = sheets[active];
  return (
    <div className="sheet-viewer">
      {sheets.length > 1 && (
        <div className="sheet-tabs">
          {sheets.map((s, i) => (
            <button key={s.name} className={"sheet-tab" + (i === active ? " active" : "")} onClick={() => setActive(i)}>
              {s.name}
            </button>
          ))}
        </div>
      )}
      {sheet.rows.length ? <GridTable rows={sheet.rows} /> : <div className="rail-muted artifact-table-note">{t("session.rail.emptySheet")}</div>}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(epochSeconds: number): string {
  if (!epochSeconds) return "";
  return new Date(epochSeconds * 1000).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
