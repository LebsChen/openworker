declare module "@novnc/novnc/lib/rfb.js" {
  export default class RFB {
    constructor(target: HTMLElement, channel: WebSocket, options?: Record<string, unknown>);
    scaleViewport: boolean;
    clipViewport: boolean;
    resizeSession: boolean;
    addEventListener(type: string, callback: (event: Event) => void): void;
    removeEventListener(type: string, callback: (event: Event) => void): void;
    disconnect(): void;
  }
}
