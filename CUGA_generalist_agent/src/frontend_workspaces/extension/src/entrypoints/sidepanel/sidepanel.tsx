
import log from "loglevel";
import { CommandType } from "runtime";
import browser from "webextension-polyfill";
import { BootstrapAgentic } from "agentic_chat"


class WorkerConnection {
    private port: browser.Runtime.Port | undefined;
    private onMessageBound: (command: any) => void;
    private logger: log.Logger;

    constructor() {
        this.onMessageBound = this.onMessage.bind(this);
        this.logger = log.getLogger("nocodeui.extension.sidepanel");
    }

    private onMessage(command: any) {
        if (!this.port) {
            this.logger.error("Receiving message on unitialized port");
            return;
        }

        if (command.type === CommandType.RenderSidepanel) {
            const contentRoot = document.getElementById("root");
            BootstrapAgentic(contentRoot!);
        }
    }

    start() {
        this.port = browser.runtime.connect({ name: "sidepanel" });
        this.port.onMessage.addListener(this.onMessageBound);
    }
}

const workerConnection = new WorkerConnection();
workerConnection.start();
