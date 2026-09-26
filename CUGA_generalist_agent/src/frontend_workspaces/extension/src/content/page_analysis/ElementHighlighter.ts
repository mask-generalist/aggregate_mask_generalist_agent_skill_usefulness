/*
 * Copyright (c) 2024 Gregor Zunic
 * Modifications Copyright 2025 CUGA
 * Licensed under the Apache License, Version 2.0
 * Original code licensed under MIT License
 */

import { HIGHLIGHT_CONTAINER_ID } from "./constants";
import { OverlayData, IframeOffset, WindowWithHighlightCleanup } from "./types";

export class ElementHighlighter {
  /**
   * Hash map of DOM nodes indexed by their highlight index.
   */
  public highlightElement(
    element: HTMLElement,
    index: number,
    parentIframe: HTMLIFrameElement | null = null
  ): number {
    if (!element) return index;

    const overlays: OverlayData[] = [];
    let label: HTMLElement | null = null;
    let labelWidth = 20;
    let labelHeight = 16;
    let cleanupFn: (() => void) | null = null;

    try {
      // Create or get highlight container
      let container = document.getElementById(HIGHLIGHT_CONTAINER_ID);
      if (!container) {
        container = document.createElement("div");
        container.id = HIGHLIGHT_CONTAINER_ID;
        container.style.position = "fixed";
        container.style.pointerEvents = "none";
        container.style.top = "0";
        container.style.left = "0";
        container.style.width = "100%";
        container.style.height = "100%";
        // Use the maximum valid value in zIndex to ensure the element is not blocked by overlapping elements.
        container.style.zIndex = "2147483647";
        container.style.backgroundColor = "transparent";
        document.body.appendChild(container);
      }

      // Get element client rects
      const rects = element.getClientRects(); // Use getClientRects()

      if (!rects || rects.length === 0) return index; // Exit if no rects

      // Generate a color based on the index
      const colors = [
        "#FF0000",
        "#00FF00",
        "#0000FF",
        "#FFA500",
        "#800080",
        "#008080",
        "#FF69B4",
        "#4B0082",
        "#FF4500",
        "#2E8B57",
        "#DC143C",
        "#4682B4",
      ];
      const colorIndex = index % colors.length;
      const baseColor = colors[colorIndex];
      const backgroundColor = baseColor + "1A"; // 10% opacity version of the color

      // Get iframe offset if necessary
      let iframeOffset: IframeOffset = { x: 0, y: 0 };
      if (parentIframe) {
        const iframeRect = parentIframe.getBoundingClientRect(); // Keep getBoundingClientRect for iframe offset
        iframeOffset.x = iframeRect.left;
        iframeOffset.y = iframeRect.top;
      }

      // Create fragment to hold overlay elements
      const fragment = document.createDocumentFragment();

      // Create highlight overlays for each client rect
      for (const rect of rects) {
        if (rect.width === 0 || rect.height === 0) continue; // Skip empty rects

        const overlay = document.createElement("div");
        overlay.style.position = "fixed";
        overlay.style.border = `2px solid ${baseColor}`;
        overlay.style.backgroundColor = backgroundColor;
        overlay.style.pointerEvents = "none";
        overlay.style.boxSizing = "border-box";

        const top = rect.top + iframeOffset.y;
        const left = rect.left + iframeOffset.x;

        overlay.style.top = `${top}px`;
        overlay.style.left = `${left}px`;
        overlay.style.width = `${rect.width}px`;
        overlay.style.height = `${rect.height}px`;

        fragment.appendChild(overlay);
        overlays.push({ element: overlay, initialRect: rect }); // Store overlay and its rect
      }

      // Create and position a single label relative to the first rect
      const firstRect = rects[0];
      label = document.createElement("div");
      label.className = "playwright-highlight-label";
      label.style.position = "fixed";
      label.style.background = baseColor;
      label.style.color = "white";
      label.style.padding = "1px 4px";
      label.style.borderRadius = "4px";
      label.style.fontSize = `${Math.min(12, Math.max(8, firstRect.height / 2))}px`;
      const domTreeId = element.getAttribute("dom-tree-id");
      label.textContent = domTreeId ? domTreeId : index.toString();

      labelWidth = label.offsetWidth > 0 ? label.offsetWidth : labelWidth; // Update actual width if possible
      labelHeight = label.offsetHeight > 0 ? label.offsetHeight : labelHeight; // Update actual height if possible

      const firstRectTop = firstRect.top + iframeOffset.y;
      const firstRectLeft = firstRect.left + iframeOffset.x;

      let labelTop = firstRectTop + 2;
      let labelLeft = firstRectLeft + firstRect.width - labelWidth - 2;

      // Adjust label position if first rect is too small
      if (
        firstRect.width < labelWidth + 4 ||
        firstRect.height < labelHeight + 4
      ) {
        labelTop = firstRectTop - labelHeight - 2;
        labelLeft = firstRectLeft + firstRect.width - labelWidth; // Align with right edge
        if (labelLeft < iframeOffset.x) labelLeft = firstRectLeft; // Prevent going off-left
      }

      // Ensure label stays within viewport bounds slightly better
      labelTop = Math.max(
        0,
        Math.min(labelTop, window.innerHeight - labelHeight)
      );
      labelLeft = Math.max(
        0,
        Math.min(labelLeft, window.innerWidth - labelWidth)
      );

      label.style.top = `${labelTop}px`;
      label.style.left = `${labelLeft}px`;

      fragment.appendChild(label);

      // Update positions on scroll/resize
      const updatePositions = (): void => {
        const newRects = element.getClientRects(); // Get fresh rects
        let newIframeOffset: IframeOffset = { x: 0, y: 0 };

        if (parentIframe) {
          const iframeRect = parentIframe.getBoundingClientRect(); // Keep getBoundingClientRect for iframe
          newIframeOffset.x = iframeRect.left;
          newIframeOffset.y = iframeRect.top;
        }

        // Update each overlay
        overlays.forEach((overlayData, i) => {
          if (i < newRects.length) {
            // Check if rect still exists
            const newRect = newRects[i];
            const newTop = newRect.top + newIframeOffset.y;
            const newLeft = newRect.left + newIframeOffset.x;

            overlayData.element.style.top = `${newTop}px`;
            overlayData.element.style.left = `${newLeft}px`;
            overlayData.element.style.width = `${newRect.width}px`;
            overlayData.element.style.height = `${newRect.height}px`;
            overlayData.element.style.display =
              newRect.width === 0 || newRect.height === 0 ? "none" : "block";
          } else {
            // If fewer rects now, hide extra overlays
            overlayData.element.style.display = "none";
          }
        });

        // If there are fewer new rects than overlays, hide the extras
        if (newRects.length < overlays.length) {
          for (let i = newRects.length; i < overlays.length; i++) {
            overlays[i].element.style.display = "none";
          }
        }

        // Update label position based on the first new rect
        if (label && newRects.length > 0) {
          const firstNewRect = newRects[0];
          const firstNewRectTop = firstNewRect.top + newIframeOffset.y;
          const firstNewRectLeft = firstNewRect.left + newIframeOffset.x;

          let newLabelTop = firstNewRectTop + 2;
          let newLabelLeft =
            firstNewRectLeft + firstNewRect.width - labelWidth - 2;

          if (
            firstNewRect.width < labelWidth + 4 ||
            firstNewRect.height < labelHeight + 4
          ) {
            newLabelTop = firstNewRectTop - labelHeight - 2;
            newLabelLeft = firstNewRectLeft + firstNewRect.width - labelWidth;
            if (newLabelLeft < newIframeOffset.x)
              newLabelLeft = firstNewRectLeft;
          }

          // Ensure label stays within viewport bounds
          newLabelTop = Math.max(
            0,
            Math.min(newLabelTop, window.innerHeight - labelHeight)
          );
          newLabelLeft = Math.max(
            0,
            Math.min(newLabelLeft, window.innerWidth - labelWidth)
          );

          label.style.top = `${newLabelTop}px`;
          label.style.left = `${newLabelLeft}px`;
          label.style.display = "block";
        } else if (label) {
          // Hide label if element has no rects anymore
          label.style.display = "none";
        }
      };

      const throttleFunction = <T extends (...args: any[]) => any>(
        func: T,
        delay: number
      ): T => {
        let lastCall = 0;
        return ((...args: Parameters<T>) => {
          const now = performance.now();
          if (now - lastCall < delay) return;
          lastCall = now;
          return func(...args);
        }) as T;
      };

      const throttledUpdatePositions = throttleFunction(updatePositions, 16); // ~60fps
      window.addEventListener("scroll", throttledUpdatePositions, true);
      window.addEventListener("resize", throttledUpdatePositions);

      // Add cleanup function
      cleanupFn = (): void => {
        window.removeEventListener("scroll", throttledUpdatePositions, true);
        window.removeEventListener("resize", throttledUpdatePositions);
        // Remove overlay elements if needed
        overlays.forEach((overlay) => overlay.element.remove());
        if (label) label.remove();
      };

      // Then add fragment to container in one operation
      container.appendChild(fragment);

      return index + 1;
    } finally {
      // Store cleanup function for later use
      if (cleanupFn) {
        // Keep a reference to cleanup functions in a global array
        const windowWithCleanup = window as WindowWithHighlightCleanup;
        (windowWithCleanup._highlightCleanupFunctions =
          windowWithCleanup._highlightCleanupFunctions || []).push(cleanupFn);
      }
    }
  }
}
