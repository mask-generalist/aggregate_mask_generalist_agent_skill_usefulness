/*
 * Copyright (c) 2024 Gregor Zunic
 * Modifications Copyright 2025 CUGA
 * Licensed under the Apache License, Version 2.0
 * Original code licensed under MIT License
 */

import { DomCache } from "./DomCache";

export class NodeHelper {
  /**
   *
   */
  constructor(private domCache: DomCache) {}

  /**
   * Checks if an element is accepted.
   */
  public isElementAccepted(element: Element): boolean {
    if (!element || !element.tagName) return false;

    // Always accept body and common container elements
    const alwaysAccept = new Set([
      "body",
      "div",
      "main",
      "article",
      "section",
      "nav",
      "header",
      "footer",
    ]);
    const tagName = element.tagName.toLowerCase();

    if (alwaysAccept.has(tagName)) return true;

    const leafElementDenyList = new Set([
      "svg",
      "script",
      "style",
      "link",
      "meta",
      "noscript",
      "template",
    ]);

    return !leafElementDenyList.has(tagName);
  }

  /**
   * Checks if an element is interactive.
   */
  public isInteractiveElement(element: HTMLElement): boolean {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) {
      return false;
    }

    // Cache the tagName and style lookups
    const tagName = element.tagName.toLowerCase();
    const style = this.domCache.getCachedComputedStyle(element);

    // Define interactive cursors
    const interactiveCursors = new Set([
      "pointer", // Link/clickable elements
      "move", // Movable elements
      "text", // Text selection
      "grab", // Grabbable elements
      "grabbing", // Currently grabbing
      "cell", // Table cell selection
      "copy", // Copy operation
      "alias", // Alias creation
      "all-scroll", // Scrollable content
      "col-resize", // Column resize
      "context-menu", // Context menu available
      "crosshair", // Precise selection
      "e-resize", // East resize
      "ew-resize", // East-west resize
      "help", // Help available
      "n-resize", // North resize
      "ne-resize", // Northeast resize
      "nesw-resize", // Northeast-southwest resize
      "ns-resize", // North-south resize
      "nw-resize", // Northwest resize
      "nwse-resize", // Northwest-southeast resize
      "row-resize", // Row resize
      "s-resize", // South resize
      "se-resize", // Southeast resize
      "sw-resize", // Southwest resize
      "vertical-text", // Vertical text selection
      "w-resize", // West resize
      "zoom-in", // Zoom in
      "zoom-out", // Zoom out
    ]);

    // Define non-interactive cursors
    const nonInteractiveCursors = new Set([
      "not-allowed", // Action not allowed
      "no-drop", // Drop not allowed
      "wait", // Processing
      "progress", // In progress
      "initial", // Initial value
      "inherit", // Inherited value
    ]);

    /**
     * Checks if an element has an interactive pointer.
     */
    function doesElementHaveInteractivePointer(element: HTMLElement): boolean {
      if (element.tagName.toLowerCase() === "html") return false;

      if (style?.cursor && interactiveCursors.has(style.cursor)) return true;

      return false;
    }

    let isInteractiveCursor = doesElementHaveInteractivePointer(element);

    // Genius fix for almost all interactive elements
    if (isInteractiveCursor) {
      return true;
    }

    const interactiveElements = new Set([
      "a", // Links
      "button", // Buttons
      "input", // All input types (text, checkbox, radio, etc.)
      "select", // Dropdown menus
      "textarea", // Text areas
      "details", // Expandable details
      "summary", // Summary element (clickable part of details)
      "label", // Form labels (often clickable)
      "option", // Select options
      "optgroup", // Option groups
      "fieldset", // Form fieldsets (can be interactive with legend)
      "legend", // Fieldset legends
    ]);

    // Define explicit disable attributes and properties
    const explicitDisableTags = new Set([
      "disabled", // Standard disabled attribute
      "readonly", // Read-only state
    ]);

    // handle inputs, select, checkbox, radio, textarea, button and make sure they are not cursor style disabled/not-allowed
    if (interactiveElements.has(tagName)) {
      // Check for non-interactive cursor
      if (style?.cursor && nonInteractiveCursors.has(style.cursor)) {
        return false;
      }

      // Check for explicit disable attributes
      for (const disableTag of explicitDisableTags) {
        if (
          element.hasAttribute(disableTag) ||
          element.getAttribute(disableTag) === "true" ||
          element.getAttribute(disableTag) === ""
        ) {
          return false;
        }
      }

      // Check for disabled property on form elements
      if ((element as HTMLInputElement).disabled) {
        return false;
      }

      // Check for readonly property on form elements
      if ((element as HTMLInputElement).readOnly) {
        return false;
      }

      // Check for inert property
      if ((element as any).inert) {
        return false;
      }

      return true;
    }

    const role = element.getAttribute("role");
    const ariaRole = element.getAttribute("aria-role");

    // Check for contenteditable attribute
    if (
      element.getAttribute("contenteditable") === "true" ||
      element.isContentEditable
    ) {
      return true;
    }

    // Added enhancement to capture dropdown interactive elements
    if (
      element.classList &&
      (element.classList.contains("button") ||
        element.classList.contains("dropdown-toggle") ||
        element.getAttribute("data-index") ||
        element.getAttribute("data-toggle") === "dropdown" ||
        element.getAttribute("aria-haspopup") === "true")
    ) {
      return true;
    }

    const interactiveRoles = new Set([
      "button", // Directly clickable element
      "menu", // Menu container (ARIA menus)
      "menubar", // Menu bar container
      "menuitem", // Clickable menu item
      "menuitemradio", // Radio-style menu item (selectable)
      "menuitemcheckbox", // Checkbox-style menu item (toggleable)
      "radio", // Radio button (selectable)
      "checkbox", // Checkbox (toggleable)
      "tab", // Tab (clickable to switch content)
      "switch", // Toggle switch (clickable to change state)
      "slider", // Slider control (draggable)
      "spinbutton", // Number input with up/down controls
      "combobox", // Dropdown with text input
      "searchbox", // Search input field
      "textbox", // Text input field
      "listbox", // Selectable list
      "option", // Selectable option in a list
      "scrollbar", // Scrollable control
    ]);

    // Basic role/attribute checks
    const hasInteractiveRole =
      interactiveElements.has(tagName) ||
      (role && interactiveRoles.has(role)) ||
      (ariaRole && interactiveRoles.has(ariaRole));

    if (hasInteractiveRole) return true;

    // check whether element has event listeners by window.getEventListeners
    try {
      if (typeof window.getEventListeners === "function") {
        const listeners = window.getEventListeners(element);
        const mouseEvents = ["click", "mousedown", "mouseup", "dblclick"];
        for (const eventType of mouseEvents) {
          if (listeners[eventType] && listeners[eventType].length > 0) {
            return true; // Found a mouse interaction listener
          }
        }
      }

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
      const commonMouseAttrs = [
        "onclick",
        "onmousedown",
        "onmouseup",
        "ondblclick",
      ];
      for (const attr of commonMouseAttrs) {
        if (
          element.hasAttribute(attr) ||
          typeof (element as any)[attr] === "function"
        ) {
          return true;
        }
      }
    } catch (e) {
      // If checking listeners fails, rely on other checks
    }

    return false;
  }

  /**
   * Checks if an element is visible.
   */
  public isElementVisible(element: HTMLElement): boolean {
    const style = this.domCache.getCachedComputedStyle(element);
    return (
      element.offsetWidth > 0 &&
      element.offsetHeight > 0 &&
      style?.visibility !== "hidden" &&
      style?.display !== "none"
    );
  }
}
