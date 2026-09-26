/*
 * Copyright (c) 2024 Gregor Zunic
 * Modifications Copyright 2025 CUGA
 * Licensed under the Apache License, Version 2.0
 * Original code licensed under MIT License
 */

import { IDomCache as IDomCache } from "./types";

export class DomCache implements IDomCache {
  public boundingRects = new WeakMap<Element, DOMRect>();
  public clientRects = new WeakMap<Element, DOMRectList>();
  public computedStyles = new WeakMap<Element, CSSStyleDeclaration>();

  public clearCache = () => {
    this.boundingRects = new WeakMap<Element, DOMRect>();
    this.clientRects = new WeakMap<Element, DOMRectList>();
    this.computedStyles = new WeakMap<Element, CSSStyleDeclaration>();
  };

  /**
   * Gets the cached bounding rect for an element.
   */
  public getCachedBoundingRect(element: Element | null): DOMRect | null {
    if (!element) return null;

    if (this.boundingRects.has(element)) {
      return this.boundingRects.get(element) || null;
    }

    const rect = element.getBoundingClientRect();

    if (rect) {
      this.boundingRects.set(element, rect);
    }
    return rect;
  }

  /**
   * Gets the cached computed style for an element.
   */
  public getCachedComputedStyle(
    element: Element | null
  ): CSSStyleDeclaration | null {
    if (!element) return null;

    if (this.computedStyles.has(element)) {
      return this.computedStyles.get(element) || null;
    }

    const style = window.getComputedStyle(element as HTMLElement);

    if (style) {
      this.computedStyles.set(element, style);
    }
    return style;
  }

  /**
   * Gets the cached client rects for an element.
   */
  public getCachedClientRects(element: Element | null): DOMRectList | null {
    if (!element) return null;

    if (this.clientRects.has(element)) {
      return this.clientRects.get(element) || null;
    }

    const rects = element.getClientRects();

    if (rects) {
      this.clientRects.set(element, rects);
    }
    return rects;
  }
}
