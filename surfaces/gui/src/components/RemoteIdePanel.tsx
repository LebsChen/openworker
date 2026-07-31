import { useEffect, useState } from "react";
import { openRvmIdeSession, type SessionHost } from "../api";
import { t, useT } from "../i18n";

type Props = {
  active: boolean;
  sessionId: string;
  host: SessionHost;
};

export function RemoteIdePanel({ active, sessionId, host }: Props) {
  useT();
  const [status, setStatus] = useState(() => t("ide.disconnected"));
  const [error, setError] = useState("");
  const [ideUrl, setIdeUrl] = useState("");
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    if (!active || host.local) return;
    setStatus(t("ide.connecting"));
    setError("");
    setIdeUrl("");
    let disposed = false;
    void openRvmIdeSession(sessionId)
      .then((url) => {
        if (!disposed) setIdeUrl(url);
      })
      .catch((reason: unknown) => {
        if (!disposed) {
          setStatus(t("ide.error"));
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    return () => {
      disposed = true;
    };
  }, [active, host.local, sessionId, generation]);

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
        {error && <span className="remote-ide-error" role="alert">{error}</span>}
        {error && (
          <button type="button" onClick={() => setGeneration((value) => value + 1)}>
            {t("ide.retry")}
          </button>
        )}
      </div>
      <div className="remote-ide-frame-holder">
        {active && ideUrl && (
          <iframe
            key={`${sessionId}-${generation}`}
            className="remote-ide-frame"
            src={ideUrl}
            title={t("session.rail.webIde")}
            onLoad={() => setStatus(t("ide.connected"))}
            onError={() => {
              setStatus(t("ide.error"));
              setError(t("ide.frameError"));
            }}
            allow="clipboard-read; clipboard-write"
          />
        )}
      </div>
    </div>
  );
}
