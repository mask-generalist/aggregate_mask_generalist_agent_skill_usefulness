/*
 * Copyright (c) 2024 Gregor Zunic
 * Modifications Copyright 2025 CUGA
 * Licensed under the Apache License, Version 2.0
 * Original code licensed under MIT License
 */

// TypeScript interfaces and types
export interface DomTreeArgs {
  doHighlightElements?: boolean;
  focusHighlightIndex?: number;
  viewportExpansion?: number;
  debugMode?: boolean;
}

export interface IDomCache {
  boundingRects: WeakMap<Element, DOMRect>;
  clientRects: WeakMap<Element, DOMRectList>;
  computedStyles: WeakMap<Element, CSSStyleDeclaration>;
  clearCache(): void;
  getCachedClientRects(element: Element | null): DOMRectList | null;
  getCachedComputedStyle(element: Element | null): CSSStyleDeclaration | null;
  getCachedBoundingRect(element: Element | null): DOMRect | null;
}

export interface IframeOffset {
  x: number;
  y: number;
}

export interface OverlayData {
  element: HTMLElement;
  initialRect: DOMRect;
}

export interface CheckPoint {
  x: number;
  y: number;
}

export interface NodeData {
  tagName: string;
  attributes: Record<string, string | null>;
  xpath: string;
  domTreeId?: number;
  children: string[];
  isVisible?: boolean;
  isTopElement?: boolean;
  isInteractive?: boolean;
  isInViewport?: boolean;
  highlightIndex?: number;
  shadowRoot?: boolean;
}

export type CollectedNode = {
  node: Node;
  nodeData: NodeData | TextNodeData;
  parentIFrame?: HTMLIFrameElement;
};

export interface TextNodeData {
  type: "TEXT_NODE";
  text: string;
  isVisible: boolean;
}

export interface DomTreeResult {
  rootId: string;
  map: Record<string, NodeData | TextNodeData>;
}

export interface WindowWithHighlightCleanup extends Window {
  _highlightCleanupFunctions?: (() => void)[];
}

export type DomTreeArgs = {
  doHighlightElements: true;
  focusHighlightIndex: -1;
  viewportExpansion: 0;
  debugMode: false;
};
