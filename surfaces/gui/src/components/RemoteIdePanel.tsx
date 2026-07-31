import { useEffect, useState } from "react";
import { prepareRvmIde, rvmIdeUrl, type SessionHost } from "../api";
import { t, useT } from "../i18n";

type Props = {
  active: boolean;
  sessionId: string;
  host: SessionHost;
};

export function RemoteIdePanel({ active, sessionId, host }: Props) {
  useT();
  const [status, setStatus] = useState(() => t("ide.disconnected"));
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!active || host.local) return;
    setStatus(t("ide.connecting"));
    setReady(false);
    let disposed = false;
    void prepareRvmIde(sessionId)
      .then(() => {
        if (!disposed) setReady(true);
      })
      .catch(() => {
        if (!disposed) setStatus(t("ide.error"));
      });
    return () => {
      disposed = true;
    };
  }, [active, host.local, sessionId]);

  if (host.local) {
    return (
      <div className="right-panel-empty">
        <h3>{t("session.rail.webIde")}</h3>
        <p>{t("ide.rvmRequired")}</p>
      </div>
    );
  }

  return (
    <div className="remote-ide-panel">
      <div className="remote-ide-toolbar">
        <span>{status}</span>
      </div>
      <div className="remote-ide-frame-holder">
        {active && ready && (
          <iframe
            key={sessionId}
            className="remote-ide-frame"
            src={rvmIdeUrl(sessionId)}
            title={t("session.rail.webIde")}
            onLoad={() => setStatus(t("ide.connected"))}
            onError={() => setStatus(t("ide.error"))}
            allow="clipboard-read; clipboard-write"
          />
        )}
      </div>
    </div>
  );
}
