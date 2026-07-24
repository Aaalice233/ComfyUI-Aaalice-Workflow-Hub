import { afterEach, describe, expect, it, vi } from "vitest";
import { CHANNEL_NAME, requestCanvas } from "./channel";

class FakeChannel {
  static latest: FakeChannel;
  onmessage: ((event: MessageEvent) => void) | null = null;
  name: string;
  constructor(name: string) { this.name = name; FakeChannel.latest = this; }
  postMessage(message: unknown) {
    expect(message).toEqual({ type: "WORKFLOW_HUB_CANVAS_REQUEST" });
    queueMicrotask(() => this.onmessage?.({ data: { type: "WORKFLOW_HUB_CANVAS_RESPONSE", name: "demo", workflow: { nodes: [] } } } as MessageEvent));
  }
  close() {}
}

describe("canvas channel", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("requests the canvas without persistent browser storage", async () => {
    vi.stubGlobal("BroadcastChannel", FakeChannel);
    await expect(requestCanvas()).resolves.toEqual({ name: "demo", workflow: { nodes: [] } });
    expect(FakeChannel.latest.name).toBe(CHANNEL_NAME);
  });
});
