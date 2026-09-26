/*
 * Copyright (c) 2024 Gregor Zunic
 * Modifications Copyright 2025 CUGA
 * Licensed under the Apache License, Version 2.0
 * Original code licensed under MIT License
 */

import { CachedXPathBuilder } from "./CachedXPathBuilder";
import { HIGHLIGHT_CONTAINER_ID } from "./constants";
import { DomCache } from "./DomCache";
import { ElementHighlighter } from "./ElementHighlighter";
import { NodeElementCollector } from "./NodeElementCollector";
import { NodeHelper } from "./NodeHelper";
import { PageHighlighter } from "./PageHighlighter";
import {
  DomTreeArgs,
  DomTreeResult,
  IDomCache,
  NodeData,
  TextNodeData,
  CollectedNode,
} from "./types";

// Extend global interfaces for dev tools functions
declare global {
  interface Window {
    getEventListeners?: (element: Element) => Record<string, any[]>;
    getEventListenersForNode?: (element: Element) => any[];
  }
}

class DomTreeBuilder {
  /**
   * Hash map of DOM nodes indexed by their highlight index.
   */
  private DOM_HASH_MAP: Record<string, NodeData | TextNodeData> = {};
  private collectedNodes: CollectedNode[] = [];
  private ID = { current: 0 };

  constructor(
    private domCache: IDomCache,
    private nodeValidator: NodeHelper,
    private nodeCollector: NodeElementCollector,
    private pageHighlighter: PageHighlighter,
    private viewportExpansion: number
  ) {}

  public buildDomTree(): {
    rootId: string;
    map: Record<string, NodeData | TextNodeData>;
  } {
    const rootId = this.buildDomTreeRecursive(document.body);
    this.pageHighlighter.highlight(this.collectedNodes);

    const map = structuredClone(this.DOM_HASH_MAP);

    this.resetState();
    return { rootId: rootId!, map: map };
  }

  /**
   * Creates a node data object for a given node and its descendants.
   */
  public buildDomTreeRecursive(
    node: Node,
    parentIFrame?: HTMLIFrameElement
  ): string | null {
    // Fast rejection checks first
    if (shouldHandleNode()) {
      return null;
    }

    // Special handling for root node (body)
    if (node === document.body) {
      const nodeData = this.nodeCollector.collect(document.body);

      // Process children of body
      for (const child of node.childNodes) {
        const domElementId = this.buildDomTreeRecursive(child);
        if (domElementId) nodeData.children.push(domElementId);
      }

      const id = `${this.ID.current++}`;
      this.DOM_HASH_MAP[id] = nodeData;
      this.collectedNodes.push({ node, nodeData });
      return id;
    }

    // Early bailout for non-element nodes except text
    if (
      node.nodeType !== Node.ELEMENT_NODE &&
      node.nodeType !== Node.TEXT_NODE
    ) {
      return null;
    }

    // Process text nodes
    if (node.nodeType === Node.TEXT_NODE) {
      const textContent = node.textContent?.trim();
      if (!textContent) {
        return null;
      }

      // Only check visibility for text nodes that might be visible
      const parentElement = node.parentElement;
      if (!parentElement || parentElement.tagName.toLowerCase() === "script") {
        return null;
      }

      const id = `${this.ID.current++}`;
      this.DOM_HASH_MAP[id] = {
        type: "TEXT_NODE",
        text: textContent,
        isVisible: this.isTextNodeVisible(node as Text),
      };
      return id;
    }

    const element = node as HTMLElement;

    // Quick checks for element nodes
    if (
      node.nodeType === Node.ELEMENT_NODE &&
      !this.isElementAccepted(element)
    ) {
      return null;
    }

    // Early viewport check - only filter out elements clearly outside viewport
    if (this.viewportExpansion !== -1 && !element.shadowRoot) {
      const rect = this.domCache.getCachedBoundingRect(element); // Keep for initial quick check
      const style = this.domCache.getCachedComputedStyle(element);

      // Skip viewport check for fixed/sticky elements as they may appear anywhere
      const isFixedOrSticky =
        style && (style.position === "fixed" || style.position === "sticky");

      // Check if element has actual dimensions using offsetWidth/Height (quick check)
      const hasSize = element.offsetWidth > 0 || element.offsetHeight > 0;

      // Use getBoundingClientRect for the quick OUTSIDE check.
      // isInExpandedViewport will do the more accurate check later if needed.
      if (
        !rect ||
        (!isFixedOrSticky &&
          !hasSize &&
          (rect.bottom < -this.viewportExpansion! ||
            rect.top > window.innerHeight + this.viewportExpansion! ||
            rect.right < -this.viewportExpansion! ||
            rect.left > window.innerWidth + this.viewportExpansion!))
      ) {
        return null;
      }
    }

    const nodeData = this.nodeCollector.collect(element);

    // Process children, with special handling for iframes and rich text editors
    if (element.tagName) {
      const tagName = element.tagName.toLowerCase();

      // Handle iframes
      if (tagName === "iframe") {
        try {
          const iframeDoc =
            (element as HTMLIFrameElement).contentDocument ||
            (element as HTMLIFrameElement).contentWindow?.document;
          if (iframeDoc) {
            for (const child of iframeDoc.childNodes) {
              const domElement = this.buildDomTreeRecursive(
                child,
                element as HTMLIFrameElement
              );
              if (domElement) nodeData.children.push(domElement);
            }
          }
        } catch (e) {
          console.warn("Unable to access iframe:", e);
        }
      }
      // Handle rich text editors and contenteditable elements
      else if (
        element.isContentEditable ||
        element.getAttribute("contenteditable") === "true" ||
        element.id === "tinymce" ||
        element.classList.contains("mce-content-body") ||
        (tagName === "body" &&
          element.getAttribute("data-id")?.startsWith("mce_"))
      ) {
        // Process all child nodes to capture formatted text
        for (const child of element.childNodes) {
          const domElement = this.buildDomTreeRecursive(child, parentIFrame);
          if (domElement) nodeData.children.push(domElement);
        }
      } else {
        // Handle shadow DOM
        if (element.shadowRoot) {
          for (const child of element.shadowRoot.childNodes) {
            const domElement = this.buildDomTreeRecursive(child, parentIFrame);
            if (domElement) nodeData.children.push(domElement);
          }
        }
        // Handle regular elements
        for (const child of element.childNodes) {
          const domElement = this.buildDomTreeRecursive(child, parentIFrame);
          if (domElement) nodeData.children.push(domElement);
        }
      }
    }

    // Skip empty anchor tags only if they have no dimensions and no children
    if (
      nodeData.tagName === "a" &&
      nodeData.children.length === 0 &&
      !nodeData.attributes.href
    ) {
      // Check if the anchor has actual dimensions
      const rect = this.domCache.getCachedBoundingRect(element);
      const hasSize =
        (rect && rect.width > 0 && rect.height > 0) ||
        element.offsetWidth > 0 ||
        element.offsetHeight > 0;

      if (!hasSize) {
        return null;
      }
    }

    const id = `${this.ID.current++}`;
    this.DOM_HASH_MAP[id] = nodeData;
    this.collectedNodes.push({ node, nodeData, parentIFrame });
    return id;

    function shouldHandleNode() {
      return (
        !node ||
        (node as HTMLElement).id === HIGHLIGHT_CONTAINER_ID ||
        (node.nodeType !== Node.ELEMENT_NODE &&
          node.nodeType !== Node.TEXT_NODE)
      );
    }
  }

  /**
   * Checks if a text node is visible.
   */
  private isTextNodeVisible(textNode: Text): boolean {
    return this.nodeCollector.isTextNodeVisible(textNode);
  }

  /**
   * Checks if an element is accepted.
   */
  private isElementAccepted(element: Element): boolean {
    return this.nodeValidator.isElementAccepted(element);
  }

  private resetState() {
    this.ID = { current: 0 };
    this.collectedNodes = [];
    this.DOM_HASH_MAP = {};
  }
}

/**
 * DOM Tree Builder Function
 * Creates a comprehensive DOM tree representation with interactive element highlighting
 */
export const buildDomTree = (args: DomTreeArgs): DomTreeResult => {
  const {
    doHighlightElements = true,
    focusHighlightIndex = -1,
    viewportExpansion = 0,
  } = args;

  // Add caching mechanisms at the top level
  const domCache: IDomCache = new DomCache();
  const elementHighlighter = new ElementHighlighter();
  const xPathBuilder = new CachedXPathBuilder();
  const nodeHelper = new NodeHelper(domCache);
  const nodeCollector = new NodeElementCollector(
    domCache,
    nodeHelper,
    xPathBuilder,
    viewportExpansion
  );
  const pageHighlighter = new PageHighlighter(
    elementHighlighter,
    nodeHelper,
    domCache,
    viewportExpansion,
    focusHighlightIndex,
    doHighlightElements
  );

  const domTreeBuilder = new DomTreeBuilder(
    domCache,
    nodeHelper,
    nodeCollector,
    pageHighlighter,
    viewportExpansion
  );

  const domTree = domTreeBuilder.buildDomTree();

  // Clear the cache before starting
  domCache.clearCache();
  xPathBuilder.clearCache();

  return domTree;
};
