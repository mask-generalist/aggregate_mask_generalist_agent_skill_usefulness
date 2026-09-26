/*
 * Copyright (c) 2024 Gregor Zunic
 * Modifications Copyright 2025 CUGA
 * Licensed under the Apache License, Version 2.0
 * Original code licensed under MIT License
 */

import { NodeHelper } from "./NodeHelper";
import { ElementHighlighter } from "./ElementHighlighter";
import { DomCache } from "./DomCache";
import { CollectedNode, NodeData, TextNodeData } from "./types";

export class PageHighlighter {
  highlightIndex: number;

  constructor(
    private elementHighlighter: ElementHighlighter,
    private nodeHelper: NodeHelper,
    private domCache: DomCache,
    private viewportExpansion = 0,
    private focusHighlightIndex = -1,
    private doHighlightElements = true
  ) {
    this.highlightIndex = 0;
  }

  /**
   * Handles the logic for deciding whether to highlight elements on page and performing the highlight.
   */
  public highlight(collectedNodes: CollectedNode[]) {
    const highlightedNodes: Node[] = [];
    
    // Check if there's an active listbox that should restrict highlighting
    const activeListbox = this.findActiveListbox(collectedNodes);

    for (const {
      node,
      nodeData,
      parentIFrame: parentIframe,
    } of collectedNodes) {
      if (this.isTextNode(nodeData)) continue;
      if (!this.isElementNode(node)) continue;

      // If there's an active listbox, only highlight listbox-related elements
      if (activeListbox && !this.isListboxRelatedElement(node as HTMLElement, activeListbox)) {
        continue;
      }

      let isParentHighlighted =
        (node.parentElement && highlightedNodes.includes(node.parentElement)) ||
        false;

      let highlighted = this.handleHighlighting(
        nodeData,
        node,
        parentIframe,
        isParentHighlighted
      );

      if (highlighted) highlightedNodes.push(node);
    }
  }

  public handleHighlighting(
    nodeData: NodeData,
    node: HTMLElement,
    parentIframe: HTMLIFrameElement | undefined,
    isParentHighlighted: boolean
  ): boolean {
    if (!nodeData.isInteractive) return false; // Not interactive, definitely don't highlight

    let shouldHighlight = false;
    if (!isParentHighlighted) {
      // Parent wasn't highlighted, this interactive node can be highlighted.
      shouldHighlight = true;
    } else {
      // Parent *was* highlighted. Only highlight this node if it represents a distinct interaction.
      if (this.isElementDistinctInteraction(node)) {
        shouldHighlight = true;
      } else {
        shouldHighlight = false;
      }
    }

    if (shouldHighlight) {
      // When this.viewportExpansion is -1, all interactive elements should get a highlight index
      // regardless of viewport status
      // Check viewport status before assigning index and highlighting
      nodeData.isInViewport = this.isInExpandedViewport(node);

      if (nodeData.isInViewport || this.viewportExpansion === -1) {
        nodeData.highlightIndex = this.highlightIndex++;

        if (!this.doHighlightElements) return false;

        if (this.focusHighlightIndex >= 0) {
          if (this.focusHighlightIndex === nodeData.highlightIndex) {
            this.elementHighlighter.highlightElement(
              node,
              nodeData.highlightIndex,
              parentIframe
            );
          }
        } else {
          this.elementHighlighter.highlightElement(
            node,
            nodeData.highlightIndex,
            parentIframe
          );
        }
        return true; // Successfully highlighted
      }
    }

    return false; // Did not highlight
  }

  /**
   * Checks if an element is within the expanded viewport.
   */
  public isInExpandedViewport(element: HTMLElement): boolean {
    if (this.viewportExpansion === -1) {
      return true;
    }

    const rects = element.getClientRects(); // Use getClientRects

    if (!rects || rects.length === 0) {
      // Fallback to getBoundingClientRect if getClientRects is empty,
      // useful for elements like <svg> that might not have client rects but have a bounding box.
      const boundingRect = this.domCache.getCachedBoundingRect(element);
      if (
        !boundingRect ||
        boundingRect.width === 0 ||
        boundingRect.height === 0
      ) {
        return false;
      }
      return !(
        boundingRect.bottom < -this.viewportExpansion ||
        boundingRect.top > window.innerHeight + this.viewportExpansion ||
        boundingRect.right < -this.viewportExpansion ||
        boundingRect.left > window.innerWidth + this.viewportExpansion
      );
    }

    // Check if *any* client rect is within the viewport
    for (const rect of rects) {
      if (rect.width === 0 || rect.height === 0) continue; // Skip empty rects

      if (
        !(
          rect.bottom < -this.viewportExpansion ||
          rect.top > window.innerHeight + this.viewportExpansion ||
          rect.right < -this.viewportExpansion ||
          rect.left > window.innerWidth + this.viewportExpansion
        )
      ) {
        return true; // Found at least one rect in the viewport
      }
    }

    return false; // No rects were found in the viewport
  }

  private isTextNode(
    nodeData: NodeData | TextNodeData
  ): nodeData is TextNodeData {
    return "type" in nodeData && nodeData.type === "TEXT_NODE";
  }

  private isElementNode(node: Node): node is HTMLElement {
    return node.nodeType === Node.ELEMENT_NODE;
  }

  /**
   * Heuristically determines if an element should be considered as independently interactive,
   * even if it's nested inside another interactive container.
   */
  private isHeuristicallyInteractive(element: HTMLElement): boolean {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;

    // Skip non-visible elements early for performance
    if (!this.nodeHelper.isElementVisible(element)) return false;

    // Check for common attributes that often indicate interactivity
    const hasInteractiveAttributes =
      element.hasAttribute("role") ||
      element.hasAttribute("tabindex") ||
      element.hasAttribute("onclick") ||
      typeof element.onclick === "function";

    // Check for semantic class names suggesting interactivity
    const hasInteractiveClass =
      /\b(btn|clickable|menu|item|entry|link)\b/i.test(element.className || "");

    // Determine whether the element is inside a known interactive container
    const isInKnownContainer = Boolean(
      element.closest('button,a,[role="button"],.menu,.dropdown,.list,.toolbar')
    );

    // Ensure the element has at least one visible child (to avoid marking empty wrappers)
    const hasVisibleChildren = [...element.children].some((child) =>
      this.nodeHelper.isElementVisible(child as HTMLElement)
    );

    // Avoid highlighting elements whose parent is <body> (top-level wrappers)
    const isParentBody =
      element.parentElement && element.parentElement.isSameNode(document.body);

    return (
      (this.nodeHelper.isInteractiveElement(element) ||
        hasInteractiveAttributes ||
        hasInteractiveClass) &&
      hasVisibleChildren &&
      isInKnownContainer &&
      !isParentBody
    );
  }

  /**
   * Checks if an element likely represents a distinct interaction
   * separate from its parent (if the parent is also interactive).
   */
  private isElementDistinctInteraction(element: HTMLElement): boolean {
    const INTERACTIVE_ROLES = new Set([
      "button",
      "link",
      "menuitem",
      "menuitemradio",
      "menuitemcheckbox",
      "radio",
      "checkbox",
      "tab",
      "switch",
      "slider",
      "spinbutton",
      "combobox",
      "searchbox",
      "textbox",
      "listbox",
      "option",
      "scrollbar",
    ]);

    const DISTINCT_INTERACTIVE_TAGS = new Set([
      "a",
      "button",
      "input",
      "select",
      "textarea",
      "summary",
      "details",
      "label",
      "option",
    ]);

    if (!element || element.nodeType !== Node.ELEMENT_NODE) {
      return false;
    }

    const tagName = element.tagName.toLowerCase();
    const role = element.getAttribute("role");

    // Check if it's an iframe - always distinct boundary
    if (tagName === "iframe") {
      return true;
    }

    // Check tag name
    if (DISTINCT_INTERACTIVE_TAGS.has(tagName)) {
      return true;
    }
    // Check interactive roles
    if (role && INTERACTIVE_ROLES.has(role)) {
      return true;
    }
    // Check contenteditable
    if (
      element.isContentEditable ||
      element.getAttribute("contenteditable") === "true"
    ) {
      return true;
    }
    // Check for common testing/automation attributes
    if (
      element.hasAttribute("data-testid") ||
      element.hasAttribute("data-cy") ||
      element.hasAttribute("data-test")
    ) {
      return true;
    }
    // Check for explicit onclick handler (attribute or property)
    if (
      element.hasAttribute("onclick") ||
      typeof element.onclick === "function"
    ) {
      return true;
    }

    // Check for other common interaction event listeners
    try {
      const getEventListenersForNode =
        element?.ownerDocument?.defaultView?.getEventListenersForNode ||
        window.getEventListenersForNode;
      if (typeof getEventListenersForNode === "function") {
        const listeners = getEventListenersForNode(element);
        const interactionEvents = [
          "click",
          "mousedown",
          "mouseup",
          "keydown",
          "keyup",
          "submit",
          "change",
          "input",
          "focus",
          "blur",
        ];
        for (const eventType of interactionEvents) {
          for (const listener of listeners) {
            if (listener.type === eventType) {
              return true; // Found a common interaction listener
            }
          }
        }
      }
      // Fallback: Check common event attributes if getEventListeners is not available
      const commonEventAttrs = [
        "onmousedown",
        "onmouseup",
        "onkeydown",
        "onkeyup",
        "onsubmit",
        "onchange",
        "oninput",
        "onfocus",
        "onblur",
      ];
      if (commonEventAttrs.some((attr) => element.hasAttribute(attr))) {
        return true;
      }
    } catch (e) {
      // If checking listeners fails, rely on other checks
    }

    // if the element is not strictly interactive but appears clickable based on heuristic signals
    if (this.isHeuristicallyInteractive(element)) {
      return true;
    }

    // Default to false: if it's interactive but doesn't match above,
    // assume it triggers the same action as the parent.
    return false;
  }

  /**
   * Finds an active listbox that should restrict highlighting to its options
   */
  private findActiveListbox(collectedNodes: CollectedNode[]): HTMLElement | null {
    for (const { node, nodeData } of collectedNodes) {
      if (!this.isElementNode(node)) continue;
      if (this.isTextNode(nodeData)) continue;
      
      const element = node as HTMLElement;
      const role = element.getAttribute("role");
      
      // Check for listbox that is visible and in viewport
      if (role === "listbox" && 
          nodeData.isVisible && 
          nodeData.isInViewport !== false) {
        return element;
      }
    }
    return null;
  }

  /**
   * Checks if an element is related to the listbox (only its options, not the listbox itself)
   */
  private isListboxRelatedElement(element: HTMLElement, listbox: HTMLElement): boolean {
    // Don't highlight the listbox itself
    if (element === listbox) return false;
    
    // Check if element is a descendant of the listbox
    if (listbox.contains(element)) return true;
    
    // Check if element has option role (even if not a direct descendant)
    const role = element.getAttribute("role");
    if (role === "option") return true;
    
    return false;
  }
}
