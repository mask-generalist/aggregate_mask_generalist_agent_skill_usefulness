/*
 * Copyright (c) 2024 Gregor Zunic
 * Modifications Copyright 2025 CUGA
 * Licensed under the Apache License, Version 2.0
 * Original code licensed under MIT License
 */

import { CachedXPathBuilder } from "./CachedXPathBuilder";
import { NodeHelper } from "./NodeHelper";
import { DomCache } from "./DomCache";
import { NodeData, CheckPoint } from "./types";

export class NodeElementCollector {
  /**
   *
   */
  constructor(
    private domCache: DomCache,
    private nodeHelper: NodeHelper,
    private xPathBuilder: CachedXPathBuilder,
    private viewportExpansion = 0
  ) {}

  public collect(element: HTMLElement): NodeData {
    // Ensure each element has a stable incrementing "dom-tree-id" attribute
    const globalKey = "__CUGA_DOM_TREE_ID_COUNTER" as const;
    let domTreeId: number;
    const existingIdAttr = element.getAttribute("dom-tree-id");

    if (existingIdAttr) {
      // Extract trailing numeric part (supports patterns like "frame:123").
      const numericMatch = existingIdAttr.match(/(\d+)(?!.*\d)/);
      if (numericMatch) {
        domTreeId = parseInt(numericMatch[1], 10);

        // Ensure global counter is at least this value to avoid duplicates.
        const currentCounter = (window as any)[globalKey] ?? 0;
        if (domTreeId > currentCounter) {
          (window as any)[globalKey] = domTreeId;
        }
      } else {
        // Attribute exists but has no numeric component – generate new numeric id
        // WITHOUT overwriting the existing attribute value.
        const nextId = ((window as any)[globalKey] ?? 0) + 1;
        (window as any)[globalKey] = nextId;
        domTreeId = nextId;
      }
    } else {
      // No attribute present – generate and persist a fresh id.
      const nextId = ((window as any)[globalKey] ?? 0) + 1;
      (window as any)[globalKey] = nextId;
      domTreeId = nextId;
      try {
        element.setAttribute("dom-tree-id", String(domTreeId));
      } catch {
        /* Some elements may be read-only, ignore errors */
      }
    }

    // Special handling for root node (body)
    if (element === document.body) {
      const nodeData: NodeData = {
        tagName: "body",
        xpath: "/body",
        domTreeId: domTreeId,
        children: [],
        attributes: { "dom-tree-id": String(domTreeId) },
      };

      return nodeData;
    }

    const nodeData: NodeData = {
      tagName: element.tagName.toLowerCase(),
      attributes: {},
      xpath: this.xPathBuilder.getXPathTree(element, true),
      domTreeId: domTreeId,
      children: [],
      shadowRoot: !!element.shadowRoot,
    };

    // Get attributes for interactive elements or potential text containers
    // Always include the dom-tree-id attribute
    nodeData.attributes["dom-tree-id"] = existingIdAttr ?? String(domTreeId);

    if (
      this.isInteractiveCandidate(element) ||
      element.tagName.toLowerCase() === "iframe" ||
      element.tagName.toLowerCase() === "body"
    ) {
      const attributeNames = element.getAttributeNames?.() || [];
      for (const name of attributeNames) {
        const value = element.getAttribute(name);
        nodeData.attributes[name] = value;
      }
    }

    // Perform visibility, interactivity, and highlighting checks
    if (element.nodeType === Node.ELEMENT_NODE) {
      nodeData.isVisible = this.nodeHelper.isElementVisible(element); // isElementVisible uses offsetWidth/Height, which is fine
      if (nodeData.isVisible) {
        nodeData.isTopElement = this.isTopElement(element);

        // Special handling for ARIA menu containers - check interactivity even if not top element
        const role = element.getAttribute("role");
        const isMenuContainer =
          role === "menu" || role === "menubar" || role === "listbox";

        if (nodeData.isTopElement || isMenuContainer) {
          nodeData.isInteractive =
            this.nodeHelper.isInteractiveElement(element);
        }
      }
    }

    return nodeData;
  }

  /**
   * Checks if an element is the topmost element at its position.
   */
  public isTopElement(element: HTMLElement): boolean {
    // Special case: when viewportExpansion is -1, consider all elements as "top" elements
    if (this.viewportExpansion === -1) {
      return true;
    }

    const rects = this.domCache.getCachedClientRects(element);

    if (!rects || rects.length === 0) {
      return false; // No geometry, cannot be top
    }

    let isAnyRectInViewport = false;
    for (const rect of rects) {
      // Use the same logic as isInExpandedViewport check
      if (
        rect.width > 0 &&
        rect.height > 0 &&
        !(
          // Only check non-empty rects
          (
            rect.bottom < -this.viewportExpansion ||
            rect.top > window.innerHeight + this.viewportExpansion ||
            rect.right < -this.viewportExpansion ||
            rect.left > window.innerWidth + this.viewportExpansion
          )
        )
      ) {
        isAnyRectInViewport = true;
        break;
      }
    }

    if (!isAnyRectInViewport) {
      return false; // All rects are outside the viewport area
    }

    // Find the correct document context and root element
    let doc = element.ownerDocument;

    // If we're in an iframe, elements are considered top by default
    if (doc !== window.document) {
      return true;
    }

    // For shadow DOM, we need to check within its own root context
    const shadowRoot = element.getRootNode();
    if (shadowRoot instanceof ShadowRoot) {
      const centerX =
        rects[Math.floor(rects.length / 2)].left +
        rects[Math.floor(rects.length / 2)].width / 2;
      const centerY =
        rects[Math.floor(rects.length / 2)].top +
        rects[Math.floor(rects.length / 2)].height / 2;

      try {
        const topEl = shadowRoot.elementFromPoint(centerX, centerY);
        if (!topEl) return false;

        let current: Node | null = topEl;
        while (current && current !== shadowRoot) {
          if (current === element) return true;
          current = current.parentElement;
        }
        return false;
      } catch (e) {
        return true;
      }
    }

    const margin = 5;
    const rect = rects[Math.floor(rects.length / 2)];

    // For elements in viewport, check if they're topmost. Do the check in the
    // center of the element and at the corners to ensure we catch more cases.
    const checkPoints: CheckPoint[] = [
      // Initially only this was used, but it was not enough
      { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 },
      { x: rect.left + margin, y: rect.top + margin }, // top left
      { x: rect.right - margin, y: rect.bottom - margin }, // bottom right
    ];

    return checkPoints.some(({ x, y }) => {
      try {
        const topEl = document.elementFromPoint(x, y);
        if (!topEl) return false;

        let current: Element | null = topEl;
        while (current && current !== document.documentElement) {
          if (current === element) return true;
          current = current.parentElement;
        }
        return false;
      } catch (e) {
        return true;
      }
    });
  }

  public isInteractiveCandidate(element: HTMLElement): boolean {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;

    const tagName = element.tagName.toLowerCase();

    // Fast-path for common interactive elements
    const interactiveElements = new Set([
      "a",
      "button",
      "input",
      "select",
      "textarea",
      "details",
      "summary",
      "label",
    ]);

    if (interactiveElements.has(tagName)) return true;

    // Quick attribute checks without getting full lists
    const hasQuickInteractiveAttr =
      element.hasAttribute("onclick") ||
      element.hasAttribute("role") ||
      element.hasAttribute("tabindex") ||
      element.hasAttribute("aria-") ||
      element.hasAttribute("data-action") ||
      element.getAttribute("contenteditable") === "true";

    return hasQuickInteractiveAttr;
  }

  /**
   * Checks if a text node is visible.
   */
  public isTextNodeVisible(textNode: Text): boolean {
    try {
      // Special case: when this.viewportExpansion is -1, consider all text nodes as visible
      if (this.viewportExpansion === -1) {
        // Still check parent visibility for basic filtering
        const parentElement = textNode.parentElement;
        if (!parentElement) return false;

        try {
          return (parentElement as any).checkVisibility({
            checkOpacity: true,
            checkVisibilityCSS: true,
          });
        } catch (e) {
          // Fallback if checkVisibility is not supported
          const style = window.getComputedStyle(parentElement);
          return (
            style.display !== "none" &&
            style.visibility !== "hidden" &&
            style.opacity !== "0"
          );
        }
      }

      const range = document.createRange();
      range.selectNodeContents(textNode);
      const rects = range.getClientRects(); // Use getClientRects for Range

      if (!rects || rects.length === 0) {
        return false;
      }

      let isAnyRectVisible = false;
      let isAnyRectInViewport = false;

      for (const rect of rects) {
        // Check size
        if (rect.width > 0 && rect.height > 0) {
          isAnyRectVisible = true;

          // Viewport check for this rect
          if (
            !(
              rect.bottom < -this.viewportExpansion! ||
              rect.top > window.innerHeight + this.viewportExpansion! ||
              rect.right < -this.viewportExpansion! ||
              rect.left > window.innerWidth + this.viewportExpansion!
            )
          ) {
            isAnyRectInViewport = true;
            break; // Found a visible rect in viewport, no need to check others
          }
        }
      }

      if (!isAnyRectVisible || !isAnyRectInViewport) {
        return false;
      }

      // Check parent visibility
      const parentElement = textNode.parentElement;
      if (!parentElement) return false;

      try {
        return (parentElement as any).checkVisibility({
          checkOpacity: true,
          checkVisibilityCSS: true,
        });
      } catch (e) {
        // Fallback if checkVisibility is not supported
        const style = window.getComputedStyle(parentElement);
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          style.opacity !== "0"
        );
      }
    } catch (e) {
      console.warn("Error checking text node visibility:", e);
      return false;
    }
  }
}
