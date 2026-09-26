/*
 * Copyright (c) 2024 Gregor Zunic
 * Modifications Copyright 2025 CUGA
 * Licensed under the Apache License, Version 2.0
 * Original code licensed under MIT License
 */

import { Module } from "runtime";
import { buildDomTree } from "./DomTree";
import { DomTreeArgs, DomTreeResult } from "./types";

/**
 * DOM Tree Module Implementation
 * Provides a module interface for managing DOM tree analysis and highlighting
 */
export class DOMTreeModule implements Module {
  private isRunning = false;
  private currentResult: DomTreeResult | null = null;
  private messageListener: ((event: MessageEvent) => void) | null = null;

  /**
   * Start the DOM tree module
   */
  start(): void {
    if (this.isRunning) {
      console.warn("⚠️ DOMTreeModule is already running");
      return;
    }

    console.log("🚀 Starting DOMTreeModule...", {
      window: !!window,
      document: !!document,
      location: window.location?.href,
      readyState: document.readyState,
    });

    this.isRunning = true;

    // Set up message listener for commands
    this.messageListener = (event: MessageEvent) => {
      this.handleMessage(event);
    };

    // Listen for messages from extension background or popup
    window.addEventListener("message", this.messageListener);
    console.log("📨 Message listener added");

    // Wait for DOM to be ready before exposing API
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => {
        console.log("📄 DOM loaded, exposing API...");
        this.exposeGlobalAPI();
      });
    } else {
      // DOM is already ready
      console.log("📄 DOM already ready, exposing API...");
      this.exposeGlobalAPI();
    }

    console.log("✅ DOMTreeModule startup complete");
  }

  /**
   * Stop the DOM tree module
   */
  stop(): void {
    if (!this.isRunning) {
      console.warn("DOMTreeModule is not running");
      return;
    }

    console.log("Stopping DOMTreeModule");
    this.isRunning = false;

    // Remove message listener
    if (this.messageListener) {
      window.removeEventListener("message", this.messageListener);
      this.messageListener = null;
    }

    // Clean up any existing highlights
    this.clearHighlights();

    // Remove global API
    this.removeGlobalAPI();

    console.log("DOMTreeModule stopped successfully");
  }

  /**
   * Handle incoming messages
   */
  private handleMessage(event: MessageEvent): void {
    if (event.source !== window) return;

    const { data } = event;
    if (!data || typeof data !== "object") return;

    switch (data.type) {
      case "DOM_TREE_ANALYZE":
        this.handleAnalyzeCommand(data.args || {});
        break;
      case "DOM_TREE_HIGHLIGHT":
        this.handleHighlightCommand(data.args || {});
        break;
      case "DOM_TREE_CLEAR_HIGHLIGHTS":
        this.clearHighlights();
        break;
      case "DOM_TREE_GET_RESULT":
        this.sendCurrentResult();
        break;
      default:
        // Ignore unknown message types
        break;
    }
  }

  /**
   * Handle analyze command
   */
  private handleAnalyzeCommand(args: DomTreeArgs): void {
    try {
      const result = this.analyzePage(args);
      this.currentResult = result;

      // Send result back
      window.postMessage(
        {
          type: "DOM_TREE_ANALYZE_RESULT",
          result: result,
          success: true,
        },
        "*"
      );

      console.log("DOM analysis completed:", {
        totalNodes: Object.keys(result.map).length,
        rootId: result.rootId,
      });
    } catch (error) {
      console.error("DOM analysis failed:", error);
      window.postMessage(
        {
          type: "DOM_TREE_ANALYZE_RESULT",
          error: error instanceof Error ? error.message : "Unknown error",
          success: false,
        },
        "*"
      );
    }
  }

  /**
   * Handle highlight command
   */
  private handleHighlightCommand(args: DomTreeArgs): void {
    try {
      const result = this.analyzePage({
        ...args,
        doHighlightElements: true,
      });
      this.currentResult = result;

      window.postMessage(
        {
          type: "DOM_TREE_HIGHLIGHT_RESULT",
          result: result,
          success: true,
        },
        "*"
      );

      console.log("DOM highlighting completed");
    } catch (error) {
      console.error("DOM highlighting failed:", error);
      window.postMessage(
        {
          type: "DOM_TREE_HIGHLIGHT_RESULT",
          error: error instanceof Error ? error.message : "Unknown error",
          success: false,
        },
        "*"
      );
    }
  }

  /**
   * Send current result
   */
  private sendCurrentResult(): void {
    window.postMessage(
      {
        type: "DOM_TREE_CURRENT_RESULT",
        result: this.currentResult,
        success: true,
      },
      "*"
    );
  }

  /**
   * Analyze the page DOM
   */
  public analyzePage(args: DomTreeArgs = {}): DomTreeResult {
    // Clear any existing highlights before running new analysis
    if (args.doHighlightElements) {
      this.clearHighlights();
    }
    return buildDomTree(args);
  }

  /**
   * Clear all highlights from the page
   */
  public clearHighlights(): void {
    // Remove highlight container if it exists
    const container = document.getElementById("playwright-highlight-container");
    if (container) {
      container.remove();
    }

    // Call cleanup functions if they exist
    const windowWithCleanup = window as any;
    if (
      windowWithCleanup._highlightCleanupFunctions &&
      Array.isArray(windowWithCleanup._highlightCleanupFunctions)
    ) {
      windowWithCleanup._highlightCleanupFunctions.forEach((fn: () => void) => {
        try {
          fn();
        } catch (e) {
          console.warn("Error calling highlight cleanup function:", e);
        }
      });
      windowWithCleanup._highlightCleanupFunctions = [];
    }
  }

  /**
   * Get current analysis result
   */
  public getCurrentResult(): DomTreeResult | null {
    return this.currentResult;
  }

  /**
   * Check if module is running
   */
  public isModuleRunning(): boolean {
    return this.isRunning;
  }

  /**
   * Expose global API for direct access
   */
  private exposeGlobalAPI(): void {
    const globalAPI = {
      analyzePage: (args?: DomTreeArgs) => this.analyzePage(args),
      clearHighlights: () => this.clearHighlights(),
      getCurrentResult: () => this.getCurrentResult(),
      isRunning: () => this.isModuleRunning(),
      // Add debugging info
      debug: {
        moduleInstance: this,
        exposedAt: new Date().toISOString(),
        context: "content-script",
      },
    };

    try {
      // Expose under a namespace to avoid conflicts
      (window as any).DOMTreeAPI = globalAPI;

      // Also expose under a debug namespace for troubleshooting
      (window as any).CUGA_DOMTreeAPI = globalAPI;

      // Log successful exposure
      console.log("✅ DOMTreeAPI exposed successfully", {
        window: !!window,
        globalAPI: !!globalAPI,
        DOMTreeAPI: !!(window as any).DOMTreeAPI,
        timestamp: new Date().toISOString(),
      });

      // Dispatch a custom event to notify that API is ready
      window.dispatchEvent(
        new CustomEvent("DOMTreeAPI:ready", {
          detail: { api: globalAPI },
        })
      );
    } catch (error) {
      console.error("❌ Failed to expose DOMTreeAPI:", error);
    }
  }

  /**
   * Remove global API
   */
  private removeGlobalAPI(): void {
    delete (window as any).DOMTreeAPI;
  }
}

// Default export for backward compatibility
export default buildDomTree;
