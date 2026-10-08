import { afterAll, beforeAll } from 'vitest'

// jsdom lays nothing out (every size is 0), so a virtualised list would think every row is in view. Give elements a
// fixed viewport (the scroll container is 448px tall) and a fixed row height instead.
export function mockElementSizes({ viewport = 448, row = 64, width = 800 } = {}) {
  const proto = HTMLElement.prototype
  const saved = {
    offsetHeight: Object.getOwnPropertyDescriptor(proto, 'offsetHeight'),
    offsetWidth: Object.getOwnPropertyDescriptor(proto, 'offsetWidth'),
    rect: Element.prototype.getBoundingClientRect,
  }
  beforeAll(() => {
    Object.defineProperty(proto, 'offsetHeight', { configurable: true, get: () => viewport })
    Object.defineProperty(proto, 'offsetWidth', { configurable: true, get: () => width })
    Element.prototype.getBoundingClientRect = function () {
      const isRow = this instanceof HTMLElement && this.hasAttribute('data-index')
      const height = isRow ? row : viewport
      return { x: 0, y: 0, top: 0, left: 0, right: width, bottom: height, width, height, toJSON: () => ({}) } as DOMRect
    }
  })
  afterAll(() => {
    if (saved.offsetHeight) Object.defineProperty(proto, 'offsetHeight', saved.offsetHeight)
    if (saved.offsetWidth) Object.defineProperty(proto, 'offsetWidth', saved.offsetWidth)
    Element.prototype.getBoundingClientRect = saved.rect
  })
}
