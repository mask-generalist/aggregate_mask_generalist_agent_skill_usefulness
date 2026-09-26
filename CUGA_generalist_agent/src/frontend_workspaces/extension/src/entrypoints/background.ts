import "../symbol.dispose.polyfill";
import browser from "webextension-polyfill";
import log from "loglevel";
import logPrefix from "loglevel-plugin-prefix";
import { SidePanel } from "../worker/sidepanel.module";

import { defineBackground } from "wxt/utils/define-background";
import { HttpStreamModule } from "../worker/http.stream.module";

export default defineBackground(() => {
    logPrefix.reg(log);
    logPrefix.apply(log, { template: "[%t] %l %n:" });
    log.enableAll();


    const modules = [
        new HttpStreamModule(),
        new SidePanel(),
    ];
    for (const module of modules) module.start();

    browser.runtime.onSuspend.addListener(() => {
        for (const module of modules) module.stop();
    });
    browser.runtime.onSuspendCanceled.addListener(() => {
        for (const module of modules) module.start();
    });
});
