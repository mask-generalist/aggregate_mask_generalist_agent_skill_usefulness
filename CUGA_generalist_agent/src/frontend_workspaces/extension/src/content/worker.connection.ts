import browser from "webextension-polyfill";
import log from "loglevel";
import * as responses from "runtime/responses";
import { Command, Channels, RuntimeContext, uuidv4 } from "runtime";
import { ExponentialBackoff, retry, handleAll, handleWhen } from "cockatiel";
import { resolve } from "path";

/**
 * Provides a mechanism to connect to the service worker and listen for commands.
 */
export class WorkerConnection {
    private logger = log.getLogger("ibm.content.WorkerConnection");
    private isFrame = window.top !== window.self;
    private port: browser.Runtime.Port | undefined;
    private onMessageBound: (command: Command) => void;
    private onDisconnectBound: (command: browser.Runtime.Port) => void;
    private checkingStatus: boolean = false;
    private lastChecked: number | undefined = undefined;

    constructor(
        private channel: string = Channels.PU,
        private rutimeContext: RuntimeContext,
    ) {
        //NOTE: this is needed because the '.bind(this)' creates a new function, and '.removeListener' needs the exact same function to remove.
        this.onMessageBound = this.onMessage.bind(this);
        this.onDisconnectBound = this.onDisconnect.bind(this);
    }

    private async onMessage(command: Command): Promise<void> {
        try {
            if (command.type.startsWith("nl2ui.page.internal.")) return;

            if (command.type == undefined)
                throw Error(`The command 'type' is required and it was not specified: ${JSON.stringify(command)}`);
            if (command.id == undefined || command.id == "")
                throw Error(`The command 'id' is required and it was not specified: ${JSON.stringify(command)}`);

            if (command.type == "pu.connection.keep-alive") {
                this.port?.postMessage(new responses.Response(command.id, true));
                return;
            }

            this.logger.info(
                `${this.isFrame ? "Frame" : "Window"} '${document.location.href}', on channel '${
                    this.port!.name
                }', received command of type '${command.type}'`,
                command,
            );
            const response = await this.rutimeContext.execute(command);
            this.safePostMessage(response);
        } catch (error: any) {
            this.logger.error(`Error handling command '${command.type}'`, error);
            this.port!.postMessage(new responses.Response(command.id, undefined, error));
        }
    }

    private async onDisconnect(): Promise<void> {
        this.ensureConnected();
    }

    public safePostMessage(message: any): void {
        const timeout = 1000 * 30;
        const maxAttempts = 10;

        const policy = handleWhen((error) =>
            error.message.toLowerCase().includes("Attempting to use a disconnected port object"),
        );

        const retryPolicy = retry(policy, {
            maxAttempts: maxAttempts,
            backoff: new ExponentialBackoff({ maxDelay: timeout, initialDelay: 500 }),
        });

        retryPolicy.onRetry(() => {
            this.ensureConnected(true);
        });

        retryPolicy.execute(() => {
            this.port!.postMessage(message);
        });
    }

    public connect(): void {
        this.port = browser.runtime.connect({ name: this.channel });
        this.port.onMessage.addListener(this.onMessageBound);
        this.port.onDisconnect.addListener(this.onDisconnectBound);

        /**
         * We need to disconnect the content script as soon as the browser navigates to another page.
         * The browser extension will eventually disconnect the content script, but it might take a while.
         * In this little time that it takes, the service worker will try to use a 'soon to be disconnected' port to send messages to when running automations that navigates to different pages.
         *
         * Although 'unload' event is not recommended, it's the only event that works when the page is being redirected/navigated.
         *  - 'pagehide' only works when the page is refreshed
         *  -  'visibilitychange' triggers when you minimize the browser, which we don't want to trigger the 'disconnect'.
         * Read more about page lifecycle (https://developer.chrome.com/docs/web-platform/page-lifecycle-api).
         */
        window.addEventListener("unload", () => {
            this.disconnect();
        });

        const handleStateChange = () => {
            if (document.visibilityState === "visible" && document.hasFocus()) this.ensureConnected();
        };

        ["pageshow", "focus", "blur", "visibilitychange", "resume"].forEach((type) => {
            window.addEventListener(type, handleStateChange, { capture: true });
        });
    }

    public async ensureConnected(force: boolean = false): Promise<void> {
        if (force || !this.port || (this.port && this.port?.error)) {
            return this.reconnect();
        }

        if (this.canRetryChecking()) return;

        this.checkingStatus = true;
        const portStatus = await this.getPortClosed();
        this.lastChecked = new Date().getTime();
        if (!portStatus) this.reconnect();
        this.checkingStatus = false;
    }

    private canRetryChecking(): boolean {
        if (this.checkingStatus) return false;

        if (!this.lastChecked) return true;

        return this.lastChecked + 1000 > new Date().getTime();
    }

    reconnect() {
        log.info("Forcing port reconnection");

        this.disconnect();
        this.connect();
    }

    private async getPortClosed() {
        return new Promise<boolean>((resolve) => {
            const id = uuidv4();
            if (!this.port) {
                resolve(true);
                return;
            }

            try {
                // Send a message to check the connection
                this.port.postMessage({ id: id, type: "nl2ui.page.internal.checkportstatus" });
                resolve(true);
            } catch (error: any) {
                console.warn("error checking the port connection", error);
                resolve(false);
            }
        });
    }

    public disconnect(): void {
        this.port?.onMessage.removeListener(this.onMessageBound);
        this.port?.disconnect();
        this.port = undefined;
    }
}
