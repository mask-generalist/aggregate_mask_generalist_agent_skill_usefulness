/**
 * Chrome Extension Content Script for marking DOM elements
 * Replaces the original Playwright-based frame_mark_elements.js
 */

// Constants for BrowserGym attributes
// Attribute used for stable DOM element identification
export const DOM_TREE_ID_ATTRIBUTE = "dom-tree-id"; // previously data-browsergym-id
// Keep alias for backward compatibility
export const BROWSERGYM_ID_ATTRIBUTE = DOM_TREE_ID_ATTRIBUTE;
const BROWSERGYM_SETOFMARKS_ATTRIBUTE = "data-browsergym-setofmarks";
const BROWSERGYM_VISIBILITY_ATTRIBUTE = "data-browsergym-visibility";

export class FrameMarkElementsModule {
    // Class state
    private elementIdCounter: number = 0;
    private isInitialized: boolean = false;

    /**
     * Start the content script module
     */
    start(): void {
        console.log("Starting FrameMarkElements module...");
        this.initialize();
    }

    /**
     * Stop the content script module
     */
    stop(): void {
        console.log("Stopping FrameMarkElements module...");
        this.cleanup();
    }

    /**
     * Initialize the content script
     */
    private initialize(): void {
        if (this.isInitialized) {
            return;
        }

        // Set up message listener
        this.setupMessageListener();
        
        // Set up page unload listener
        this.setupPageUnloadListener();
        
        // Export functions to window for external access
        this.exportToWindow();
        
        this.isInitialized = true;
        console.log("CUGA Chrome Extension: Content script loaded and ready");
    }

    /**
     * Cleanup when stopping
     */
    private cleanup(): void {
        // Remove element marks
        this.unmarkElements();
        
        // Reset state
        this.elementIdCounter = 0;
        this.isInitialized = false;
    }

    /**
     * Generate a unique element ID
     */
    private generateElementId(frameId: string): string {
        const fullId = frameId ? frameId + ":" + this.elementIdCounter : this.elementIdCounter.toString();
        this.elementIdCounter++;
        return fullId;
    }

    /**
     * Check if element is visible
     */
    private isElementVisible(element: Element): boolean {
        if (!element || element.nodeType !== Node.ELEMENT_NODE) {
            return false;
        }
        
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        
        return (
            style.display !== "none" &&
            style.visibility !== "hidden" &&
            style.opacity !== "0" &&
            rect.width > 0 &&
            rect.height > 0
        );
    }

    /**
     * Calculate element visibility score
     */
    private calculateVisibility(element: Element): number {
        if (!this.isElementVisible(element)) {
            return 0;
        }
        
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        
        // Basic visibility score based on opacity and size
        let score = parseFloat(style.opacity) || 1;
        
        // Adjust score based on element size
        const area = rect.width * rect.height;
        if (area < 100) {
            score *= 0.5; // Smaller elements are less visible
        }
        
        // Check if element is in viewport
        const inViewport = (
            rect.top >= 0 &&
            rect.left >= 0 &&
            rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
            rect.right <= (window.innerWidth || document.documentElement.clientWidth)
        );
        
        if (!inViewport) {
            score *= 0.3; // Elements outside viewport are less visible
        }
        
        return Math.min(1, Math.max(0, score));
    }

    /**
     * Check if element should be marked based on tag filtering
     */
    private shouldMarkElement(element: Element, tagsToMark: string): boolean {
        if (!element || element.nodeType !== Node.ELEMENT_NODE) {
            return false;
        }
        
        const tagName = element.tagName.toLowerCase();
        
        if (tagsToMark === "all") {
            return true;
        }
        
        // Standard HTML tags that are typically interactive or meaningful
        const standardTags = [
            "a", "button", "input", "textarea", "select", "option",
            "form", "label", "fieldset", "legend",
            "img", "video", "audio", "canvas", "svg",
            "div", "span", "p", "h1", "h2", "h3", "h4", "h5", "h6",
            "ul", "ol", "li", "dl", "dt", "dd",
            "table", "tr", "td", "th", "tbody", "thead", "tfoot",
            "nav", "header", "footer", "section", "article", "aside",
            "main", "details", "summary", "dialog",
            "menu", "menuitem"
        ];
        
        return standardTags.includes(tagName);
    }

    /**
     * Mark DOM elements with BrowserGym attributes
     */
    public markElements(frameId: string, bidAttribute: string, tagsToMark: string): string[] {
        const warnings: string[] = [];
        
        try {
            // Get all elements in the document
            const allElements = document.querySelectorAll("*");
            
            for (const element of allElements) {
                try {
                    if (!this.shouldMarkElement(element, tagsToMark)) {
                        continue;
                    }
                    
                    // Assign ID only if not already present
                    if (!element.hasAttribute(bidAttribute)) {
                        const elementId = this.generateElementId(frameId);
                        element.setAttribute(bidAttribute, elementId);
                    }
                    
                    // Set visibility attribute
                    const visibility = this.calculateVisibility(element);
                    element.setAttribute(BROWSERGYM_VISIBILITY_ATTRIBUTE, visibility.toString());
                    
                    // Mark interactive elements
                    const isInteractive = this.isElementInteractive(element);
                    if (isInteractive) {
                        element.setAttribute(BROWSERGYM_SETOFMARKS_ATTRIBUTE, "1");
                    }
                    
                    // Store dynamic properties in data attributes
                    this.storeDynamicProperties(element);
                    
                } catch (error) {
                    warnings.push(`Failed to mark element ${element.tagName}: ${(error as Error).message}`);
                }
            }
            
            // Mark iframe elements for recursive processing
            const iframes = document.querySelectorAll("iframe, frame");
            for (const iframe of iframes) {
                try {
                    if (!iframe.getAttribute(bidAttribute)) {
                        const iframeId = this.generateElementId(frameId);
                        iframe.setAttribute(bidAttribute, iframeId);
                    }
                } catch (error) {
                    warnings.push(`Failed to mark iframe: ${(error as Error).message}`);
                }
            }
            
        } catch (error) {
            warnings.push(`General marking error: ${(error as Error).message}`);
        }
        
        return warnings;
    }

    /**
     * Check if element is interactive
     */
    private isElementInteractive(element: Element): boolean {
        const tagName = element.tagName.toLowerCase();
        
        // Always interactive elements
        const interactiveTags = [
            "a", "button", "input", "textarea", "select", "option",
            "details", "summary", "dialog", "menu", "menuitem"
        ];
        
        if (interactiveTags.includes(tagName)) {
            return true;
        }
        
        // Check for click handlers
        const hasClickHandler = (
            (element as any).onclick ||
            element.getAttribute("onclick") ||
            (element as HTMLElement).style.cursor === "pointer"
        );
        
        if (hasClickHandler) {
            return true;
        }
        
        // Check for accessibility attributes that indicate interactivity
        const role = element.getAttribute("role");
        const hasInteractiveRole = role !== null && [
            "button", "link", "menuitem", "option", "radio", "checkbox",
            "slider", "spinbutton", "textbox", "combobox", "listbox"
        ].includes(role);
        
        return hasInteractiveRole;
    }

    /**
     * Store dynamic properties of elements
     */
    private storeDynamicProperties(element: Element): void {
        const tagName = element.tagName.toLowerCase();
        
        try {
            // Store input values
            if (["input", "textarea", "select"].includes(tagName)) {
                if (tagName === "input") {
                    const inputElement = element as HTMLInputElement;
                    if (inputElement.type === "checkbox" || inputElement.type === "radio") {
                        element.setAttribute("data-browsergym-checked", inputElement.checked.toString());
                    } else {
                        element.setAttribute("data-browsergym-value", inputElement.value || "");
                    }
                } else {
                    const inputElement = element as HTMLTextAreaElement | HTMLSelectElement;
                    element.setAttribute("data-browsergym-value", inputElement.value || "");
                }
            }
            
            // Store selected state for options
            if (tagName === "option") {
                const optionElement = element as HTMLOptionElement;
                element.setAttribute("data-browsergym-selected", optionElement.selected.toString());
            }
            
            // Store text content for certain elements
            if (["button", "a", "label"].includes(tagName)) {
                const textContent = element.textContent?.trim() || "";
                if (textContent) {
                    element.setAttribute("data-browsergym-text", textContent);
                }
            }
            
        } catch (error) {
            console.warn(`Failed to store dynamic properties for ${tagName}:`, error);
        }
    }

    /**
     * Unmark DOM elements (cleanup)
     */
    public unmarkElements(): void {
        try {
            const elementsWithBid = document.querySelectorAll(`[${BROWSERGYM_ID_ATTRIBUTE}]`);
            
            for (const element of elementsWithBid) {
                // Remove BrowserGym attributes (preserve stable ID)
                element.removeAttribute(BROWSERGYM_VISIBILITY_ATTRIBUTE);
                element.removeAttribute(BROWSERGYM_SETOFMARKS_ATTRIBUTE);
                
                // Remove dynamic property attributes
                const dynamicAttrs = [
                    "data-browsergym-checked",
                    "data-browsergym-value",
                    "data-browsergym-selected",
                    "data-browsergym-text"
                ];
                
                for (const attr of dynamicAttrs) {
                    element.removeAttribute(attr);
                }
            }
            
            // Reset counter
            this.elementIdCounter = 0;
            
        } catch (error) {
            console.warn("Failed to unmark elements:", error);
        }
    }

    /**
     * Get focused element with BrowserGym ID
     */
    public getFocusedElementBid(): string {
        try {
            // Get the currently focused element, diving through shadow DOMs
            const getActiveElement = (root: Document | ShadowRoot): Element | null => {
                const activeElement = root.activeElement;
                
                if (!activeElement) {
                    return null;
                }
                
                if (activeElement.shadowRoot) {
                    return getActiveElement(activeElement.shadowRoot);
                } else {
                    return activeElement;
                }
            };
            
            const focusedElement = getActiveElement(document);
            if (focusedElement) {
                return focusedElement.getAttribute(BROWSERGYM_ID_ATTRIBUTE) || "";
            }
            
            return "";
            
        } catch (error) {
            console.warn("Failed to get focused element BID:", error);
            return "";
        }
    }

    /**
     * Extract page content as HTML
     */
    public extractPageContent(): string {
        try {
            return document.body.innerHTML || "";
        } catch (error) {
            console.warn("Failed to extract page content:", error);
            return "";
        }
    }

    /**
     * Extract page content as plain text
     */
    public extractPageContentAsText(): string {
        try {
            return document.body.textContent || "";
        } catch (error) {
            console.warn("Failed to extract page content as text:", error);
            return "";
        }
    }

    /**
     * Export functions to window for external access
     */
    private exportToWindow(): void {
        if (typeof window !== "undefined") {
            (window as any).browserGymContentScript = {
                markElements: this.markElements.bind(this),
                unmarkElements: this.unmarkElements.bind(this),
                getFocusedElementBid: this.getFocusedElementBid.bind(this),
                extractPageContent: this.extractPageContent.bind(this),
                extractPageContentAsText: this.extractPageContentAsText.bind(this),
                isElementVisible: this.isElementVisible.bind(this),
                calculateVisibility: this.calculateVisibility.bind(this)
            };
        }
    }

    /**
     * Set up message listener for Chrome extension communication
     */
    private setupMessageListener(): void {
        (globalThis as any).chrome.runtime.onMessage.addListener((request: any, sender: any, sendResponse: any) => {
            try {
                switch (request.type) {
                    case "ping":
                        // Simple ping/pong for content script detection
                        sendResponse({
                            type: "pong",
                            timestamp: Date.now()
                        });
                        break;
                        
                    case "mark_elements":
                        // Always remove existing marks before creating new ones
                        this.unmarkElements();
                        
                        const warnings = this.markElements(
                            request.data.frameId || "",
                            request.data.bidAttribute || BROWSERGYM_ID_ATTRIBUTE,
                            request.data.tagsToMark || "standard_html"
                        );
                        sendResponse({
                            type: "success",
                            warnings: warnings
                        });
                        break;
                        
                    case "unmark_elements":
                        this.unmarkElements();
                        sendResponse({
                            type: "success"
                        });
                        break;
                        
                    case "get_focused_element_bid":
                        const focusedBid = this.getFocusedElementBid();
                        sendResponse({
                            type: "success",
                            data: focusedBid
                        });
                        break;

                    case "get_element_rect": {
                        try {
                            const element = document.querySelector(`[${BROWSERGYM_ID_ATTRIBUTE}="${request.bid}"]`);
                            if (!element) {
                                throw new Error(`Element with dom-tree-id '${request.bid}' not found`);
                            }
                            const rect = (element as HTMLElement).getBoundingClientRect();
                            sendResponse({
                                type: "success",
                                data: {
                                    left: rect.left,
                                    top: rect.top,
                                    right: rect.right,
                                    bottom: rect.bottom,
                                    width: rect.width,
                                    height: rect.height
                                }
                            });
                        } catch (error) {
                            sendResponse({
                                type: "error",
                                message: (error as Error).message
                            });
                        }
                        break;
                    }
                        
                    case "extract_page_content":
                        const content = request.data?.asText ? 
                            this.extractPageContentAsText() : 
                            this.extractPageContent();
                        sendResponse({
                            type: "success",
                            data: content
                        });
                        break;
                        
                    case "extract_dom_tree":
                        try {
                            // Use the DOM tree API that should be available globally
                            const domTreeAPI = (window as any).DOMTreeAPI || (window as any).CUGA_DOMTreeAPI;
                            if (!domTreeAPI) {
                                throw new Error("DOM Tree API not available");
                            }
                            
                            const result = domTreeAPI.analyzePage({
                                doHighlightElements: request.data?.doHighlightElements || false,
                                focusHighlightIndex: request.data?.focusHighlightIndex || -1,
                                viewportExpansion: request.data?.viewportExpansion || 0,
                                debugMode: request.data?.debugMode || false
                            });
                            
                            sendResponse({
                                type: "success",
                                data: result
                            });
                        } catch (error) {
                            sendResponse({
                                type: "error",
                                message: (error as Error).message
                            });
                        }
                        break;
                        
                    case "server_disconnected":
                        console.log("CUGA Chrome Extension: Server disconnected, removing element marks");
                        this.unmarkElements();
                        sendResponse({
                            type: "success"
                        });
                        break;

                    case "select_option": {
                        // Select dropdown / radio etc.
                        (async () => {
                            try {
                                const { bid, options } = request;
                                await this.performSelectOption(bid, options);
                                sendResponse({ type: "success" });
                            } catch (error) {
                                sendResponse({ type: "error", message: (error as Error).message });
                            }
                        })();
                        break;
                    }

                    case "add_animation": {
                        // Animation handler for CUGA
                        const injectAnimationStyles = () => {
                            const style = document.createElement('style');
                            style.id = 'ai-animation-styles';
                            style.textContent = `
                                @keyframes pulse {
                                    0% { opacity: 0.6; transform: scale(1); }
                                    50% { opacity: 1; transform: scale(1.03); }
                                    100% { opacity: 0.6; transform: scale(1); }
                                }
                                @keyframes glowing {
                                    0% { box-shadow: 0 0 3px 2px rgba(138, 43, 226, 0.4); }
                                    50% { box-shadow: 0 0 10px 5px rgba(138, 43, 226, 0.8); }
                                    100% { box-shadow: 0 0 3px 2px rgba(138, 43, 226, 0.4); }
                                }
                                @keyframes rotate {
                                    0% { transform: rotate(0deg); }
                                    100% { transform: rotate(360deg); }
                                }
                                .ai-highlight {
                                    position: absolute;
                                    z-index: 9998;
                                    border: 2px solid #8a2be2;
                                    border-radius: 4px;
                                    pointer-events: none;
                                    animation: glowing 1.8s infinite ease-in-out;
                                    background-color: rgba(138, 43, 226, 0.05);
                                }
                                .ai-icon {
                                    position: absolute;
                                    z-index: 9999;
                                    background-size: contain;
                                    background-repeat: no-repeat;
                                    width: 28px;
                                    height: 28px;
                                    pointer-events: none;
                                }
                                .ai-typing-icon {
                                    background-image: url("data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNMTcgMTJINyIgc3Ryb2tlPSIjOGEyYmUyIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPjxwYXRoIGQ9Ik0xMiA3TDEyIDE3IiBzdHJva2U9IiM4YTJiZTIiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+PC9zdmc+");
                                    animation: pulse 1.5s infinite ease-in-out;
                                }
                                .ai-loading-icon {
                                    border: 3px solid rgba(138, 43, 226, 0.3);
                                    border-radius: 50%;
                                    border-top: 3px solid #8a2be2;
                                    animation: rotate 1s linear infinite;
                                }
                                .ai-success-icon {
                                    background-image: url("data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjQiIGhlaWdodD0iMjQiIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNMjAgNkw5IDE3TDQgMTIiIHN0cm9rZT0iIzhhMmJlMiIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiLz48L3N2Zz4=");
                                    animation: pulse 1.5s infinite ease-in-out;
                                }
                                .ai-banner {
                                    position: fixed;
                                    bottom: 20px;
                                    left: 50%;
                                    transform: translateX(-50%);
                                    background: linear-gradient(135deg, #9c27b0, #673ab7);
                                    color: white;
                                    padding: 10px 18px;
                                    border-radius: 20px;
                                    font-family: system-ui, -apple-system, sans-serif;
                                    font-size: 14px;
                                    font-weight: 500;
                                    z-index: 10000;
                                    animation: pulse 1.5s infinite ease-in-out;
                                    pointer-events: none;
                                    box-shadow: 0 3px 10px rgba(0, 0, 0, 0.2);
                                }
                                .ai-focus-outline {
                                    position: absolute;
                                    z-index: 9997;
                                    pointer-events: none;
                                    border-radius: 4px;
                                    box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.15);
                                }
                            `;
                            document.head.appendChild(style);
                        };

                        const addAnimationToElement = (bid: string, iconType: string, bannerText: string) => {
                            injectAnimationStyles();
                            const elem = document.querySelector(`[dom-tree-id="${bid}"]`);
                            if (!elem) return { success: false, message: "Element not found" };
                            const rect = elem.getBoundingClientRect();
                            const idSuffix = Math.random().toString(36).substr(2, 6);
                            
                            // Create highlight
                            const highlight = document.createElement('div');
                            highlight.id = `ai-highlight-${idSuffix}`;
                            highlight.className = 'ai-highlight';
                            highlight.style.left = `${window.scrollX + rect.x - 3}px`;
                            highlight.style.top = `${window.scrollY + rect.y - 3}px`;
                            highlight.style.width = `${rect.width + 6}px`;
                            highlight.style.height = `${rect.height + 6}px`;
                            document.body.appendChild(highlight);
                            
                            // Focus outline
                            const focusOutline = document.createElement('div');
                            focusOutline.id = `ai-focus-outline-${idSuffix}`;
                            focusOutline.className = 'ai-focus-outline';
                            focusOutline.style.left = `${window.scrollX + rect.x - 5}px`;
                            focusOutline.style.top = `${window.scrollY + rect.y - 5}px`;
                            focusOutline.style.width = `${rect.width + 10}px`;
                            focusOutline.style.height = `${rect.height + 10}px`;
                            document.body.appendChild(focusOutline);
                            
                            // Icon
                            const icon = document.createElement('div');
                            icon.id = `ai-icon-${idSuffix}`;
                            icon.className = `ai-icon ai-${iconType}-icon`;
                            icon.style.left = `${window.scrollX + rect.x + rect.width + 8}px`;
                            icon.style.top = `${window.scrollY + rect.y + (rect.height - 28) / 2}px`;
                            document.body.appendChild(icon);
                            
                            // Banner
                            const banner = document.createElement('div');
                            banner.id = `ai-banner-${idSuffix}`;
                            banner.className = 'ai-banner';
                            banner.textContent = bannerText;
                            document.body.appendChild(banner);
                            
                            // Cleanup after 5s
                            setTimeout(() => {
                                [highlight, focusOutline, icon, banner].forEach(el => {
                                    if (el) {
                                        el.style.transition = 'opacity 0.5s ease-out';
                                        el.style.opacity = '0';
                                    }
                                });
                                setTimeout(() => {
                                    [highlight, focusOutline, icon, banner].forEach(el => el && el.remove());
                                }, 500);
                            }, 5000);
                            
                            return { success: true };
                        };

                        console.log("CUGA Chrome Extension: Adding animation to element", request.bid);
                        const { bid, iconType, bannerText } = request;
                        const result = addAnimationToElement(bid, iconType, bannerText);
                        sendResponse(result);
                        break;
                    }
                        
                    default:
                        sendResponse({
                            type: "error",
                            message: `Unknown request type: ${request.type}`
                        });
                }
            } catch (error) {
                sendResponse({
                    type: "error",
                    message: (error as Error).message
                });
            }
            
            return true; // Indicates we will send a response asynchronously
        });
    }

    /**
     * Set up page unload listener for cleanup
     */
    private setupPageUnloadListener(): void {
        window.addEventListener('beforeunload', () => {
            console.log("CUGA Chrome Extension: Page unloading, removing element marks");
            this.unmarkElements();
        });
    }

    /**
     * Handle select_option command.
     */
    private async performSelectOption(bid: string, options: string | string[]): Promise<void> {
        const element = document.querySelector(`[dom-tree-id="${bid}"]`);
        if (!element) {
            throw new Error(`Element with dom-tree-id '${bid}' not found`);
        }
        console.error("Select command not implemented yet");
    }
} 