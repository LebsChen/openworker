import { t } from "../i18n";
import { useEffect, useRef, useState } from "react";
import "@xterm/xterm/css/xterm.css";
import { openRvmPty, type SessionHost } from "../api";

type TerminalInstance = import("@xterm/xterm").Terminal;

type Props = {
  active: boolean;
  sessionId: string;
  host: SessionHost;
};

export function RemoteShellPanel({ active, sessionId, host }: Props) {
  const holder = useRef<HTMLDivElement | null>(null);
  const terminal = useRef<TerminalInstance | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState("Disconnected");
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    if (!active || host.local) return;
    let disposed = false;
    let instance: TerminalInstance | null = null;
    let observer: ResizeObserver | null = null;
    let input: { dispose: () => void } | null = null;
    let ws: WebSocket | null = null;
    const start = async () => {
      const [{ Terminal: XtermTerminal }, { FitAddon }] = await Promise.all([
        import("@xterm/xterm"),
        import("@xterm/addon-fit"),
      ]);
      if (disposed || !holder.current) return;
      instance = new XtermTerminal({
        cursorBlink: true,
        convertEol: true,
        fontSize: 12,
        theme: { background: "#111318", foreground: "#e7eaf0" },
      });
      const fit = new FitAddon();
      instance.loadAddon(fit);
      instance.open(holder.current);
      terminal.current = instance;
      const resize = () => {
        fit.fit();
        if (ws?.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "resize", cols: instance?.cols, rows: instance?.rows }));
        }
      };
      observer = new ResizeObserver(resize);
      observer.observe(holder.current);
      ws = openRvmPty(sessionId, instance.cols || 80, instance.rows || 24);
      socket.current = ws;
      setStatus("Connecting…");
      ws.binaryType = "arraybuffer";
      ws.onopen = () => {
        setStatus("Connected");
        resize();
        instance?.focus();
      };
      ws.onmessage = (event) => {
        if (typeof event.data === "string") instance?.write(event.data);
        else if (event.data instanceof ArrayBuffer) instance?.write(new Uint8Array(event.data));
        else if (event.data instanceof Blob) {
          event.data.arrayBuffer().then((bytes) => instance?.write(new Uint8Array(bytes)));
        }
      };
      ws.onerror = () => setStatus("Disconnected");
      ws.onclose = () => {
        setStatus("Disconnected");
        socket.current = null;
      };
      input = instance.onData((data) => {
        if (ws?.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(data));
      });
    };
    void start();
    return () => {
      disposed = true;
      observer?.disconnect();
      input?.dispose();
      ws?.close();
      socket.current = null;
      instance?.dispose();
      terminal.current = null;
    };
  }, [active, host.local, sessionId, generation]);

  if (host.local) {
    return (
      <div className="right-panel-empty">
        <h3>Shell</h3>
        <p>{t("shell.requiresRvmHostLocalSessionsDoNotProvidePty")}</p>
      </div>
    );
  }

  return (
    <div className="remote-shell-panel">
      <div className="remote-shell-toolbar">
        <span>{status}</span>
        <button type="button" onClick={() => setGeneration((value) => value + 1)}>
          Start a new shell
        </button>
      </div>
      <div ref={holder} className="remote-shell-terminal" onClick={() => terminal.current?.focus()} />
      <div className="remote-shell-note">
        Each reconnect starts a new shell. Windows uses piped PowerShell without ConPTY; resize is
        unavailable and full TUI fidelity is not guaranteed.
      </div>
    </div>
  );
}
