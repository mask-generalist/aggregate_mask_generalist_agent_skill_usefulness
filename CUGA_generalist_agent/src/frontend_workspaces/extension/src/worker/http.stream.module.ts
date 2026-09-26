// HTTP streaming background worker for extension <-> backend communication
// Similar API to websocket.module.ts, but uses EventSource and POST

import { sleep } from "runtime";

const SERVER_BASE = process.env.REACT_APP_API_URL || "http://localhost:7860";
const COMMAND_STREAM_URL = `${SERVER_BASE}/extension/command_stream`;
const COMMAND_RESULT_URL = `${SERVER_BASE}/extension/command_result`;

export class HttpStreamModule {
    private eventSource: EventSource | null = null;
    private isConnected: boolean = false;
    // Track pending agent queries from popup
    private pendingAgentQueries: Map<string, (response: any) => void> = new Map();

    start(): void {
        this.connectToCommandStream();
        this.setupEventListeners();
    }

    stop(): void {
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
        this.isConnected = false;
    }

    private connectToCommandStream(): void {
        this.eventSource = new EventSource(COMMAND_STREAM_URL);
        this.eventSource.onopen = () => {
            console.log("[HTTP-STREAM] Connected to command stream");
            this.isConnected = true;
        };
        this.eventSource.onerror = (err) => {
            console.error("[HTTP-STREAM] EventSource error", err);
            this.isConnected = false;
        };
        this.eventSource.onmessage = async (event) => {
            try {
                const cmd = JSON.parse(event.data);
                console.log("[HTTP-STREAM] Received command:", cmd);
                // If this is an agent response, forward to popup if needed
                if (cmd.type === "agent_response" || cmd.type === "agent_complete" || cmd.type === "agent_error") {
                    // If this was initiated by a popup, resolve the pending promise
                    if (cmd.request_id && this.pendingAgentQueries.has(cmd.request_id)) {
                        const resolver = this.pendingAgentQueries.get(cmd.request_id);
                        if (resolver) {
                            resolver(cmd);
                        }
                        this.pendingAgentQueries.delete(cmd.request_id);
                    }
                    // Forward to popup (if open)
                    try {
                        await (globalThis as any).chrome.runtime.sendMessage({
                            source: 'background',
                            ...cmd
                        });
                        console.log("[HTTP-STREAM] Forwarded agent message to popup:", cmd.type);
                    } catch (error) {
                        // Popup might not be open, which is fine
                        console.log("[HTTP-STREAM] Could not forward message to popup (popup might be closed):", (error as Error).message);
                    }
                    return;
                }
                const result = await this.executeCommand(cmd);
                await this.sendCommandResult(cmd.request_id, result);
            } catch (e) {
                console.error("[HTTP-STREAM] Failed to process command:", e);
            }
        };
    }

    private async sendCommandResult(requestId: string, result: any): Promise<void> {
        try {
            await fetch(COMMAND_RESULT_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ request_id: requestId, ...result })
            });
            console.log("[HTTP-STREAM] Sent command result for", requestId);
        } catch (e) {
            console.error("[HTTP-STREAM] Failed to send command result:", e);
        }
    }

    // --- Command execution logic (reuse from websocket.module.ts) ---
    private async executeCommand(cmd: any): Promise<any> {
        switch (cmd.type) {
            case "ping":
                return { 
                    type: "pong",
                    timestamp: Date.now()
                };
            case "mark_elements":
                return await this.handleMarkElements(cmd.data);
            case "unmark_elements":
                return await this.handleUnmarkElements();
            case "extract_dom_snapshot":
                return await this.handleExtractDomSnapshot(cmd.data);
            case "extract_accessibility_tree":
                return await this.handleExtractAccessibilityTree();
            case "extract_dom_tree":
                return await this.handleExtractDomTree(cmd.data);
            case "extract_screenshot":
                return await this.handleExtractScreenshot(cmd.data);
            case "extract_focused_element_bid":
                return await this.handleExtractFocusedElementBid(cmd.data);
            case "extract_page_content":
                return await this.handleExtractPageContent(cmd.data);
            case "get_active_tab_url":
                return await this.handleGetActiveTabUrl();
            case "get_active_tab_title":
                return await this.handleGetActiveTabTitle();
            case "browser_command":
                return await this.handleBrowserCommand(cmd.command, cmd.args, cmd.request_id);
            default:
                return { type: "error", message: `Unknown command type: ${cmd.type}` };
        }
    }

    private async handleBrowserCommand(command: string, args: any, requestId: string): Promise<any> {
        try {
            switch (command) {
                case "click":
                    return await this.handleClickCommand(args);
                case "type":
                    return await this.handleTypeCommand(args);
                case "add_animation":
                    return await this.handleAddAnimation(args);
                case "select_option":
                    return await this.handleSelectOption(args);
                default:
                    return { type: "error", message: `Unknown browser command: ${command}` };
            }
        } catch (e: any) {
            return { type: "error", message: e.message || String(e) };
        }
    }

    // --- The following methods are adapted from websocket.module.ts ---
    private async handleClickCommand(args: any): Promise<any> {
        const activeTab = await this.getActiveTab();
        if (!activeTab) {
            throw new Error("No active tab found");
        }
        const { bid, button = "left", modifiers = [] } = args;
        if (!bid) {
            throw new Error("BID is required for click command");
        }
        console.log(`[CUGA] Clicking element with BID: ${bid}, button: ${button}, modifiers: ${modifiers}`);
        let nodeId = await this.findElementByDomTreeId(activeTab.id, bid);
        if (!nodeId) {
            throw new Error(`Element with BID '${bid}' not found`);
        }

        // --- Redirect click if the element is a <label> with a 'for' attribute ---
        try {
            const nodeInfo = await (globalThis as any).chrome.debugger.sendCommand(
                { tabId: activeTab.id },
                "DOM.describeNode",
                { nodeId }
            );

            const nodeName: string | undefined = nodeInfo?.node?.nodeName;
            const attrs: string[] = nodeInfo?.node?.attributes ?? [];

            if (nodeName && nodeName.toLowerCase() === "label" && attrs.length > 0) {
                const forIndex = attrs.findIndex((v) => v === "for");
                if (forIndex !== -1 && forIndex + 1 < attrs.length) {
                    const forValue = attrs[forIndex + 1];
                    if (forValue) {
                        // Try to find the element with the corresponding id
                        const documentNode = await (globalThis as any).chrome.debugger.sendCommand(
                            { tabId: activeTab.id },
                            "DOM.getDocument"
                        );
                        const queryRes = await (globalThis as any).chrome.debugger.sendCommand(
                            { tabId: activeTab.id },
                            "DOM.querySelector",
                            { nodeId: documentNode.root.nodeId, selector: `#${forValue}` }
                        );
                        if (queryRes && queryRes.nodeId) {
                            console.log(`[CUGA] Redirecting click from <label> to associated element id '${forValue}', nodeId: ${queryRes.nodeId}`);
                            nodeId = queryRes.nodeId;
                        }
                    }
                }
            }
        } catch (labelErr) {
            console.warn("[CUGA] Failed to resolve label target element:", labelErr);
        }

        const boxModel = await (globalThis as any).chrome.debugger.sendCommand(
            { tabId: activeTab.id },
            "DOM.getBoxModel",
            { nodeId: nodeId }
        );
        if (!boxModel || !boxModel.model) {
            throw new Error("Could not get element bounding box");
        }
        let centerX: number | null = null;
        let centerY: number | null = null;

        // Attempt to obtain accurate bounding rect via content script first
        const elementRect = await this.getElementRect(activeTab.id, bid);
        if (elementRect) {
            centerX = Math.round(elementRect.left + elementRect.width / 2);
            centerY = Math.round(elementRect.top + elementRect.height / 2);
            console.log(`[CUGA] Bounding rect via content script, center: (${centerX}, ${centerY})`);
        }

        if (centerX === null || centerY === null) {
            const border = boxModel.model.border;
            // border contains 8 numbers: [xTL, yTL, xTR, yTR, xBR, yBR, xBL, yBL]
            const xs = [border[0], border[2], border[4], border[6]];
            const ys = [border[1], border[3], border[5], border[7]];
            centerX = Math.round((Math.min(...xs) + Math.max(...xs)) / 2);
            centerY = Math.round((Math.min(...ys) + Math.max(...ys)) / 2);
            console.log(`[CUGA] Fallback BoxModel center: (${centerX}, ${centerY})`);
        }
        await (globalThis as any).chrome.debugger.sendCommand(
            { tabId: activeTab.id },
            "Input.dispatchMouseEvent",
            {
                type: "mousePressed",
                x: centerX,
                y: centerY,
                button: button,
                clickCount: 1
            }
        );
        sleep(100); // Wait a bit to simulate real user interaction
        await (globalThis as any).chrome.debugger.sendCommand(
            { tabId: activeTab.id },
            "Input.dispatchMouseEvent",
            {
                type: "mouseReleased",
                x: centerX,
                y: centerY,
                button: button,
                clickCount: 1
            }
        );
        console.log(`[CUGA] Click completed successfully`);
        return { success: true, position: { x: centerX, y: centerY } };
    }

    private async handleTypeCommand(args: any): Promise<any> {
        const activeTab = await this.getActiveTab();
        if (!activeTab) {
            throw new Error("No active tab found");
        }
        const { bid, value, press_enter = false } = args;
        if (!bid) {
            throw new Error("BID is required for type command");
        }
        if (!value) {
            throw new Error("Value is required for type command");
        }
        console.log(`[CUGA] Typing in element with BID: ${bid}, value: "${value}", press_enter: ${press_enter}`);
        const nodeId = await this.findElementByDomTreeId(activeTab.id, bid);
        if (!nodeId) {
            throw new Error(`Element with BID '${bid}' not found`);
        }
        await (globalThis as any).chrome.debugger.sendCommand(
            { tabId: activeTab.id },
            "DOM.focus",
            { nodeId: nodeId }
        );
        await (globalThis as any).chrome.debugger.sendCommand(
            { tabId: activeTab.id },
            "Input.dispatchKeyEvent",
            {
                type: "keyDown",
                windowsVirtualKeyCode: 46, // Delete key
                code: "Delete",
                key: "Delete"
            }
        );
        for (let i = 0; i < value.length; i++) {
            const char = value[i];
            await (globalThis as any).chrome.debugger.sendCommand(
                { tabId: activeTab.id },
                "Input.dispatchKeyEvent",
                {
                    type: "keyDown",
                    text: char,
                    key: char,
                    code: `Key${char.toUpperCase()}`
                }
            );
            await (globalThis as any).chrome.debugger.sendCommand(
                { tabId: activeTab.id },
                "Input.dispatchKeyEvent",
                {
                    type: "keyUp",
                    text: char,
                    key: char,
                    code: `Key${char.toUpperCase()}`
                }
            );
            await new Promise(resolve => setTimeout(resolve, 10));
        }
        if (press_enter) {
            console.log(`[CUGA] Pressing Enter after typing`);
            await (globalThis as any).chrome.debugger.sendCommand(
                { tabId: activeTab.id },
                "Input.dispatchKeyEvent",
                {
                    type: "keyDown",
                    windowsVirtualKeyCode: 13, // Enter key
                    code: "Enter",
                    key: "Enter"
                }
            );
            await (globalThis as any).chrome.debugger.sendCommand(
                { tabId: activeTab.id },
                "Input.dispatchKeyEvent",
                {
                    type: "keyUp",
                    windowsVirtualKeyCode: 13, // Enter key
                    code: "Enter",
                    key: "Enter"
                }
            );
        }
        console.log(`[CUGA] Type completed successfully`);
        return { success: true, value: value, press_enter: press_enter };
    }

    private async handleAddAnimation(args: any): Promise<any> {
        const activeTab = await this.getActiveTab();
        if (!activeTab) {
            throw new Error("No active tab found");
        }
        await this.ensureContentScriptInjected(activeTab.id);
        const { bid, icon_type, banner_text } = args;
        const animResult = await (globalThis as any).chrome.tabs.sendMessage(activeTab.id, {
            type: "add_animation",
            bid,
            iconType: icon_type,
            bannerText: banner_text
        });
        return animResult;
    }

    private async handleSelectOption(args: any): Promise<any> {
        const activeTab = await this.getActiveTab();
        if (!activeTab) {
            throw new Error("No active tab found");
        }
        await this.ensureContentScriptInjected(activeTab.id);

        const { bid, options } = args;
        const selectResult = await (globalThis as any).chrome.tabs.sendMessage(activeTab.id, {
            type: "select_option",
            bid,
            options,
        });
        return selectResult;
    }

    // --- Handler methods for extraction commands ---
    private async handleMarkElements(data: any): Promise<any> {
        try {
            const activeTab = await this.getActiveTab();
            if (!activeTab) {
                throw new Error("No active tab found");
            }
            
            // Ensure content script is injected before sending message
            await this.ensureContentScriptInjected(activeTab.id);
            
            // Send message to content script
            const response = await (globalThis as any).chrome.tabs.sendMessage(activeTab.id, {
                type: "mark_elements",
                data: {
                    frameId: data.frameId || "",
                    bidAttribute: data.bid_attribute || "dom-tree-id",
                    tagsToMark: data.tags_to_mark || "standard_html"
                }
            });
            
            return {
                type: "success",
                warnings: response.warnings || []
            };
            
        } catch (error) {
            return {
                type: "error",
                message: (error as Error).message
            };
        }
    }

    private async handleUnmarkElements(): Promise<any> {
        try {
            const activeTab = await this.getActiveTab();
            if (!activeTab) {
                throw new Error("No active tab found");
            }
            
            // Ensure content script is injected before sending message
            await this.ensureContentScriptInjected(activeTab.id);
            
            await (globalThis as any).chrome.tabs.sendMessage(activeTab.id, {
                type: "unmark_elements"
            });
            
            return {
                type: "success"
            };
            
        } catch (error) {
            return {
                type: "error",
                message: (error as Error).message
            };
        }
    }

    private async handleExtractDomSnapshot(data: any): Promise<any> {
        try {
            const activeTab = await this.getActiveTab();
            if (!activeTab) {
                throw new Error("No active tab found");
            }
            
            // Ensure debugger is attached before using DevTools Protocol
            await this.ensureDebuggerAttached(activeTab.id);
            // Use Chrome DevTools Protocol to get DOM snapshot
            const domSnapshot = await (globalThis as any).chrome.debugger.sendCommand(
                { tabId: activeTab.id },
                "DOMSnapshot.captureSnapshot",
                {
                    computedStyles: data.computed_styles || [],
                    includeDOMRects: data.include_dom_rects !== false,
                    includePaintOrder: data.include_paint_order !== false
                }
            );
            
            return {
                type: "success",
                data: domSnapshot
            };
            
        } catch (error) {
            return {
                type: "error",
                message: (error as Error).message
            };
        }
    }

    private async handleExtractAccessibilityTree(): Promise<any> {
        try {
            const activeTab = await this.getActiveTab();
            if (!activeTab) {
                throw new Error("No active tab found");
            }
            
            // Ensure debugger is attached before using DevTools Protocol
            await this.ensureDebuggerAttached(activeTab.id);
            // Use Chrome DevTools Protocol to get accessibility tree
            const axTree = await (globalThis as any).chrome.debugger.sendCommand(
                { tabId: activeTab.id },
                "Accessibility.getFullAXTree"
            );
            
            return {
                type: "success",
                data: axTree
            };
            
        } catch (error) {
            return {
                type: "error",
                message: (error as Error).message
            };
        }
    }

    private async handleExtractScreenshot(data: any): Promise<any> {
        try {
            const activeTab = await this.getActiveTab();
            if (!activeTab) {
                throw new Error("No active tab found");
            }
            
            // Ensure debugger is attached before using DevTools Protocol
            await this.ensureDebuggerAttached(activeTab.id);
            // Use Chrome DevTools Protocol to capture screenshot
            const screenshot = await (globalThis as any).chrome.debugger.sendCommand(
                { tabId: activeTab.id },
                "Page.captureScreenshot",
                {
                    format: data.format || "png",
                    quality: data.quality || 100
                }
            );
            
            // Schedule non-blocking cleanup of marked elements after a short delay
            // Default delay: 3000ms, configurable via data.cleanup_delay_ms
            try {
                const cleanupDelayMs = (data && typeof data.cleanup_delay_ms === "number") ? data.cleanup_delay_ms : 3000;
                const tabIdForCleanup = activeTab.id;
                setTimeout(async () => {
                    try {
                        await this.ensureContentScriptInjected(tabIdForCleanup);
                        await (globalThis as any).chrome.tabs.sendMessage(tabIdForCleanup, {
                            type: "unmark_elements"
                        });
                        console.log("[HTTP-STREAM] Cleaned marked elements after screenshot");
                    } catch (cleanupErr) {
                        console.warn("[HTTP-STREAM] Failed to clean elements after screenshot:", cleanupErr);
                    }
                }, cleanupDelayMs);
            } catch (scheduleErr) {
                console.warn("[HTTP-STREAM] Failed to schedule cleanup after screenshot:", scheduleErr);
            }
            
            return {
                type: "success",
                data: screenshot.data
            };
            
        } catch (error) {
            return {
                type: "error",
                message: (error as Error).message
            };
        }
    }

    private async handleExtractFocusedElementBid(data: any): Promise<any> {
        try {
            const activeTab = await this.getActiveTab();
            if (!activeTab) {
                throw new Error("No active tab found");
            }
            
            // Ensure content script is injected before sending message
            await this.ensureContentScriptInjected(activeTab.id);
            
            const response = await (globalThis as any).chrome.tabs.sendMessage(activeTab.id, {
                type: "get_focused_element_bid",
                data: {
                    bidAttribute: data.bid_attribute || "dom-tree-id"
                }
            });
            
            return {
                type: "success",
                data: response.data || ""
            };
            
        } catch (error) {
            return {
                type: "error",
                message: (error as Error).message
            };
        }
    }

    private async handleExtractDomTree(data: any): Promise<any> {
        try {
            const activeTab = await this.getActiveTab();
            if (!activeTab) {
                throw new Error("No active tab found");
            }
            
            // Ensure content script is injected before sending message
            await this.ensureContentScriptInjected(activeTab.id);
            
            const response = await (globalThis as any).chrome.tabs.sendMessage(activeTab.id, {
                type: "extract_dom_tree",
                data: {
                    doHighlightElements: data.do_highlight_elements || false,
                    focusHighlightIndex: data.focus_highlight_index || -1,
                    viewportExpansion: data.viewport_expansion || 0,
                    debugMode: data.debug_mode || false
                }
            });
            
            return {
                type: "success",
                data: response.data || null
            };
            
        } catch (error) {
            return {
                type: "error",
                message: (error as Error).message
            };
        }
    }

    private async handleExtractPageContent(data: any): Promise<any> {
        try {
            const activeTab = await this.getActiveTab();
            if (!activeTab) {
                throw new Error("No active tab found");
            }
            
            // Ensure content script is injected before sending message
            await this.ensureContentScriptInjected(activeTab.id);
            
            const response = await (globalThis as any).chrome.tabs.sendMessage(activeTab.id, {
                type: "extract_page_content",
                data: {
                    asText: data.as_text || false
                }
            });
            
            return {
                type: "success",
                data: response.data || ""
            };
            
        } catch (error) {
            return {
                type: "error",
                message: (error as Error).message
            };
        }
    }

    private async handleGetActiveTabUrl(): Promise<any> {
        try {
            const activeTab = await this.getActiveTab();
            if (!activeTab) {
                throw new Error("No active tab found");
            }
            return {
                type: "success",
                data: activeTab.url
            };
        } catch (error) {
            return {
                type: "error",
                message: (error as Error).message
            };
        }
    }

    private async handleGetActiveTabTitle(): Promise<any> {
        try {
            const activeTab = await this.getActiveTab();
            if (!activeTab) {
                throw new Error("No active tab found");
            }
            return {
                type: "success",
                data: (activeTab.title ?? "")
            };
        } catch (error) {
            return {
                type: "error",
                message: (error as Error).message
            };
        }
    }

    // --- Utility methods ---
    private async findElementByDomTreeId(tabId: number, bid: string): Promise<number | null> {
        console.log(`[CUGA] Searching for element with BID: ${bid}`);
        const document = await (globalThis as any).chrome.debugger.sendCommand(
            { tabId: tabId },
            "DOM.getDocument"
        );
        const searchResult = await (globalThis as any).chrome.debugger.sendCommand(
            { tabId: tabId },
            "DOM.performSearch",
            {
                query: `[dom-tree-id="${bid}"]`
            }
        );
        if (!searchResult.searchId) {
            throw new Error("Search failed");
        }
        const results = await (globalThis as any).chrome.debugger.sendCommand(
            { tabId: tabId },
            "DOM.getSearchResults",
            {
                searchId: searchResult.searchId,
                fromIndex: 0,
                toIndex: 1
            }
        );
        await (globalThis as any).chrome.debugger.sendCommand(
            { tabId: tabId },
            "DOM.discardSearchResults",
            {
                searchId: searchResult.searchId
            }
        );
        if (!results.nodeIds || results.nodeIds.length === 0) {
            console.log(`[CUGA] Element with BID '${bid}' not found`);
            return null;
        }
        const nodeId = results.nodeIds[0];
        console.log(`[CUGA] Found element with BID '${bid}', nodeId: ${nodeId}`);
        return nodeId;
    }

    private async getActiveTab(): Promise<any> {
        const tabs = await (globalThis as any).chrome.tabs.query({ active: true, currentWindow: true });
        return tabs[0] || null;
    }

    private async ensureContentScriptInjected(tabId: number): Promise<void> {
        try {
            // Check if the tab exists and is accessible
            const tab = await (globalThis as any).chrome.tabs.get(tabId);
            if (!tab || tab.url.startsWith("chrome://") || tab.url.startsWith("chrome-extension://")) {
                throw new Error("Cannot inject content script into restricted page");
            }
            
            // Try to ping the content script with a timeout
            await new Promise((resolve, reject) => {
                const timeout = setTimeout(() => {
                    reject(new Error("Content script ping timeout"));
                }, 1000);
                
                (globalThis as any).chrome.tabs.sendMessage(tabId, { type: "ping" }, (response: any) => {
                    clearTimeout(timeout);
                    if ((globalThis as any).chrome.runtime.lastError) {
                        reject(new Error((globalThis as any).chrome.runtime.lastError.message));
                    } else if (response && response.type === "pong") {
                        resolve(response);
                    } else {
                        reject(new Error("Invalid ping response"));
                    }
                });
            });
            
            console.log("Content script already injected and responding");
            
        } catch (error) {
            console.log("Content script not present or not responding:", (error as Error).message);
            
            // Instead of trying to inject dynamically, we'll rely on the manifest-declared content script
            // The content script should be automatically injected by Chrome based on the manifest
            console.log("Content script should be automatically injected via manifest");
            
            // Wait a bit for the content script to load if it was just injected
            await new Promise(resolve => setTimeout(resolve, 1000));
            
            // Try to ping again
            try {
                await new Promise((resolve, reject) => {
                    const timeout = setTimeout(() => {
                        reject(new Error("Content script verification timeout"));
                    }, 2000);
                    
                    (globalThis as any).chrome.tabs.sendMessage(tabId, { type: "ping" }, (response: any) => {
                        clearTimeout(timeout);
                        if ((globalThis as any).chrome.runtime.lastError) {
                            reject(new Error((globalThis as any).chrome.runtime.lastError.message));
                        } else if (response && response.type === "pong") {
                            resolve(response);
                        } else {
                            reject(new Error("Content script injection verification failed"));
                        }
                    });
                });
                
                console.log("Content script injection verified");
                
            } catch (verificationError) {
                console.error("Failed to verify content script injection:", verificationError);
                throw new Error(`Content script not available: ${(verificationError as Error).message}`);
            }
        }
    }

    private async ensureDebuggerAttached(tabId: number): Promise<void> {
        try {
            await (globalThis as any).chrome.debugger.attach({ tabId: tabId }, "1.3");
        } catch (error) {
            // Ignore the error if we are already attached, propagate otherwise
            if (!(error && ((error as Error).message?.includes("already attached") || (error as Error).message?.includes("Already attached")))) {
                console.error("Failed to attach Chrome debugger:", error);
                throw new Error("Chrome debugger not attached and could not attach");
            }
        }
    }

    // Obtain bounding rect of element via content script (viewport coordinates)
    private async getElementRect(tabId: number, bid: string): Promise<{ left: number; top: number; width: number; height: number } | null> {
        try {
            // Ensure content script is injected
            await this.ensureContentScriptInjected(tabId);
            const response = await (globalThis as any).chrome.tabs.sendMessage(tabId, {
                type: "get_element_rect",
                bid: bid
            });
            if (response && response.type === "success" && response.data) {
                return response.data as { left: number; top: number; width: number; height: number };
            }
        } catch (err) {
            console.warn("[CUGA] Failed to get element rect via content script:", err);
        }
        return null;
    }

    // --- Event listeners for popup communication ---
    public setupEventListeners(): void {
        (globalThis as any).chrome.runtime.onMessage.addListener((request: any, sender: any, sendResponse: any) => {
            if (request.source === "popup") {
                this.handlePopupMessage(request)
                    .then(response => sendResponse(response))
                    .catch(error => sendResponse({
                        type: "error",
                        message: (error as Error).message
                    }));
                return true; // Indicates we will send a response asynchronously
            }
        });
    }

    private async handlePopupMessage(request: any): Promise<any> {
        switch (request.type) {
            case "ping":
                return {
                    type: "pong",
                    connected: this.isConnected
                };
            case "send_agent_query":
                if (!this.isConnected) {
                    throw new Error("Not connected to backend server");
                }
                return await this.handleAgentQuery(request.query);
            default:
                throw new Error(`Unknown popup message type: ${request.type}`);
        }
    }

    // --- Agent query logic ---
    private async handleAgentQuery(query: string): Promise<any> {
        // Generate a unique request_id
        const requestId = `agent_query_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        
        try {
            const response = await fetch(`${SERVER_BASE}/extension/agent_query`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query, request_id: requestId })
            });
            
            if (!response.ok) {
                throw new Error(`Failed to send agent query: ${response.statusText}`);
            }
            
            // The server streams JSON lines back to this request
            // We need to consume the stream and forward responses to the popup
            const reader = response.body?.getReader();
            if (!reader) {
                throw new Error("No response body reader available");
            }
            
            const decoder = new TextDecoder();
            let buffer = '';
            
            try {
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    
                    buffer += decoder.decode(value, { stream: true });
                    
                    // Process complete lines
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || ''; // Keep incomplete line in buffer
                    
                    for (const line of lines) {
                        if (line.trim()) {
                            try {
                                const data = JSON.parse(line);
                                console.log("[HTTP-STREAM] Received agent response:", data.type);
                                
                                // Forward to popup if it's open
                                try {
                                    await (globalThis as any).chrome.runtime.sendMessage({
                                        source: 'background',
                                        ...data
                                    });
                                } catch (error) {
                                    // Popup might not be open, which is fine
                                    console.log("[HTTP-STREAM] Could not forward to popup:", (error as Error).message);
                                }
                                
                                // If this is the completion message, resolve the promise
                                if (data.type === "agent_complete" || data.type === "agent_error") {
                                    return { type: "success", message: "Agent query completed" };
                                }
                                
                            } catch (parseError) {
                                console.error("[HTTP-STREAM] Failed to parse agent response:", parseError);
                            }
                        }
                    }
                }
                
                // Process any remaining data in buffer
                if (buffer.trim()) {
                    try {
                        const data = JSON.parse(buffer);
                        console.log("[HTTP-STREAM] Final agent response:", data.type);
                        
                        // Forward to popup
                        try {
                            await (globalThis as any).chrome.runtime.sendMessage({
                                source: 'background',
                                ...data
                            });
                        } catch (error) {
                            console.log("[HTTP-STREAM] Could not forward final response to popup:", (error as Error).message);
                        }
                        
                    } catch (parseError) {
                        console.error("[HTTP-STREAM] Failed to parse final agent response:", parseError);
                    }
                }
                
                return { type: "success", message: "Agent query stream completed" };
                
            } finally {
                reader.releaseLock();
            }
            
        } catch (e: any) {
            throw new Error(e.message || String(e));
        }
    }
}

// Export a flag for selection
export const EXTENSION_TRANSPORT = "http_stream"; 