'use client';

// Suppress unhandled removeChild and insertBefore DOMExceptions caused by third-party DOM mutators
// such as Google Translate, browser auto-translation, and certain browser extensions.
// When Google Translate translates a page, it wraps text nodes in <font> tags. When React subsequently
// reconciles during background updates or re-renders and attempts to remove or reinsert the original child,
// native Node.removeChild/insertBefore throws NotFoundError: "The node to be removed is not a child of this node".
if (typeof window !== 'undefined' && typeof Node === 'function' && Node.prototype) {
  const originalRemoveChild = Node.prototype.removeChild;
  Node.prototype.removeChild = function <T extends Node>(child: T): T {
    if (child.parentNode !== this) {
      if (process.env.NODE_ENV !== 'production') {
        console.warn(
          'Suppressed removeChild: Node is not a child of this parent (often caused by browser translation or extensions).',
          child,
          this
        );
      }
      return child;
    }
    return originalRemoveChild.call(this, child) as T;
  };

  const originalInsertBefore = Node.prototype.insertBefore;
  Node.prototype.insertBefore = function <T extends Node>(newNode: T, referenceNode: Node | null): T {
    if (referenceNode && referenceNode.parentNode !== this) {
      if (process.env.NODE_ENV !== 'production') {
        console.warn(
          'Suppressed insertBefore: Reference node is not a child of this parent (often caused by browser translation or extensions).',
          referenceNode,
          this
        );
      }
      return newNode;
    }
    return originalInsertBefore.call(this, newNode, referenceNode) as T;
  };
}

/**
 * DomPatchGuard: Headless component that ensures DOM manipulation patches
 * are loaded into the browser client before any React DOM reconciliations occur.
 */
export function DomPatchGuard() {
  return null;
}
