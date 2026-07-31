import RFB from "@novnc/novnc/lib/rfb.js";
import { useEffect, useRef, useState } from "react";
import { openRvmVnc, type SessionHost } from "../api";
import { t, useT } from "../i18n";

type Props = {
  active: boolean;
  sessionId: string;
  host: SessionHost;
};

type DisconnectDetail = {
  clean?: boolean;
};

export function RemoteDesktopPanel({ active, sessionId, host }: Props) {
  useT();
  const holder = useRef<HTMLDivElement | null>(null);
  const rfb = useRef<RFB | null>(null);
  const [status, setStatus] = useState(() => t("desktop.disconnected"));

  useEffect(() => {
    if (!active || host.local || !holder.current) return;
    let disposed = false;
    const socket = openRvmVnc(sessionId);
    setStatus(t("desktop.connecting"));

    try {
      const connection = new RFB(holder.current, socket);
      connection.scaleViewport = true;
      connection.clipViewport = false;
      connection.resizeSession = false;
      rfb.current = connection;

      const onConnect = () => setStatus(t("desktop.connected"));
      const onDisconnect = (event: Event) => {
        if (disposed) return;
        const detail = (event as CustomEvent<DisconnectDetail>).detail;
        setStatus(detail?.clean ? t("desktop.disconnected") : t("desktop.error"));
      };
      const onFailure = () => setStatus(t("desktop.error"));
      connection.addEventListener("connect", onConnect);
      connection.addEventListener("disconnect", onDisconnect);
      connection.addEventListener("securityfailure", onFailure);
      connection.addEventListener("credentialsrequired", onFailure);

      return () => {
        disposed = true;
        connection.removeEventListener("connect", onConnect);
        connection.removeEventListener("disconnect", onDisconnect);
        connection.removeEventListener("securityfailure", onFailure);
        connection.removeEventListener("credentialsrequired", onFailure);
        connection.disconnect();
        if (rfb.current === connection) rfb.current = null;
      };
    } catch {
      socket.close();
      setStatus(t("desktop.error"));
      return;
    }
  }, [active, host.local, sessionId]);

  if (host.local) {
    return (
      <div className="right-panel-empty">
        <h3>{t("session.rail.browserDesktop")}</h3>
        <p>{t("desktop.rvmRequired")}</p>
      </div>
    );
  }

  return (
    <div className="remote-desktop-panel">
      <div className="remote-desktop-toolbar">
        <span>{status}</span>
      </div>
      <div ref={holder} className="remote-desktop-screen" />
    </div>
  );
}
