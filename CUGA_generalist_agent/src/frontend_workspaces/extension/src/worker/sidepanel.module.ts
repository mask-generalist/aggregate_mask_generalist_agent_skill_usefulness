import browser from "webextension-polyfill";
import { browser as wxtBrowser } from "wxt/browser";

import { getManifestVersion } from "../functions";
import { RenderSidepanelCommand } from "runtime";
import { Module } from "runtime";

export class SidePanel implements Module {
    private onConnectBound: (port: browser.Runtime.Port) => void;
    private port: browser.Runtime.Port | undefined;
    private heartbeatInterval: NodeJS.Timeout | undefined;

    constructor(
    ) {
        this.onConnectBound = this.onConnect.bind(this);
    }

    private handleBrowserActionClick() {
        const manifestVersion = getManifestVersion();
        const action = manifestVersion == "v3" ? browser.action : browser.browserAction;
        if (!action)
            throw Error(
                `'WorkerNL2UI' class can only be used in the context of 'service workers' of a browser extension.`,
            );

        action.onClicked.addListener(async (tab: browser.Tabs.Tab) => {
            wxtBrowser.sidePanel.setOptions({
                path: "./sidepanel.html",
            });
            wxtBrowser.sidePanel.open({ windowId: tab.windowId! });
        });
    }

    private startHeartbeat() {
        if (this.heartbeatInterval) return;
        this.heartbeatInterval = setInterval(() => {
            if (this.port) {
                this.port.postMessage({ type: "heartbeat" });
            }
        }, 20000);
    }

    private stopHeartbeat() {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = undefined;
        }
    }

    private async onConnect(port: browser.Runtime.Port) {
        if (port.name !== "sidepanel") return;

        if (this.port) {
            return;
        }

        this.port = port;

        port.onDisconnect.addListener((_) => {
            this.stopHeartbeat();
            this.port = undefined;
        });
        this.startHeartbeat();

        port.postMessage(new RenderSidepanelCommand());
    }


    start(): void {
        this.handleBrowserActionClick();

        browser.runtime.onConnect.addListener(this.onConnectBound);
    }

    stop(): void {
        this.stopHeartbeat();
        browser.runtime.onConnect.removeListener(this.onConnectBound);
    }
}
