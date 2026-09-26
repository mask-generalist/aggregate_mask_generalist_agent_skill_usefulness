/*
 * Copyright (c) 2024 Gregor Zunic
 * Modifications Copyright 2025 CUGA
 * Licensed under the Apache License, Version 2.0
 * Original code licensed under MIT License
 */

export class CachedXPathBuilder {
  // Add a WeakMap cache for XPath strings
  private xpathCache = new WeakMap<Element, string>();

  public getXPathTree(
    element: Element,
    stopAtBoundary: boolean = true
  ): string {
    if (this.xpathCache.has(element)) return this.xpathCache.get(element)!;

    const segments: string[] = [];
    let currentElement: Node | null = element;

    while (currentElement && currentElement.nodeType === Node.ELEMENT_NODE) {
      // Stop if we hit a shadow root or iframe
      if (
        stopAtBoundary &&
        (currentElement.parentNode instanceof ShadowRoot ||
          currentElement.parentNode instanceof HTMLIFrameElement)
      ) {
        break;
      }

      const position = this.getElementPosition(currentElement as HTMLElement);
      const tagName = (currentElement as Element).nodeName.toLowerCase();
      const xpathIndex = position > 0 ? `[${position}]` : "";
      segments.unshift(`${tagName}${xpathIndex}`);

      currentElement = currentElement.parentNode;
    }

    const result = segments.join("/");
    this.xpathCache.set(element, result);
    return result;
  }

  public clearCache() {
    this.xpathCache = new WeakMap<Element, string>();
  }

  /**
   * Gets the position of an element in its parent.
   */
  private getElementPosition(currentElement: HTMLElement): number {
    if (!currentElement.parentElement) {
      return 0; // No parent means no siblings
    }

    const tagName = currentElement.nodeName.toLowerCase();

    const siblings = Array.from(currentElement.parentElement.children).filter(
      (sib) => sib.nodeName.toLowerCase() === tagName
    );

    if (siblings.length === 1) {
      return 0; // Only element of its type
    }

    const index = siblings.indexOf(currentElement) + 1; // 1-based index
    return index;
  }
}
