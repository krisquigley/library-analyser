// A small stand-in for the browser DOM, for testing the views in Node (#146). Only what the views use.

export function fakeElement(tagName) {
  const attributes = new Map();
  return {
    tagName: String(tagName).toUpperCase(), id: '', className: '', type: '', hidden: false, disabled: false, value: '',
    textContent: '', dataset: {}, style: {}, children: [], onclick: null, oninput: null,
    setAttribute(name, value) { attributes.set(name, String(value)); },
    getAttribute(name) { return attributes.has(name) ? attributes.get(name) : null; },
    removeAttribute(name) { attributes.delete(name); },
    append(...nodes) { this.children.push(...nodes); },
    replaceChildren(...nodes) { this.children = nodes; },
    replaceChild(node, old) { this.children = this.children.map(child => (child === old ? node : child)); },
    focus() { this.focused = true; },
    get classList() {
      const element = this;
      const names = () => element.className.split(/\s+/).filter(Boolean);
      return {
        add(...added) { element.className = [...new Set([...names(), ...added])].join(' '); },
        remove(...removed) { element.className = names().filter(name => !removed.includes(name)).join(' '); },
        contains(name) { return names().includes(name); },
      };
    },
  };
}

export function installFakeDocument(ids) {
  const roots = Object.fromEntries(ids.map(id => [id, Object.assign(fakeElement(id === 'track-search' ? 'input' : 'div'), {id})]));
  globalThis.document = {createElement: fakeElement, getElementById: id => roots[id] || null};
  return roots;
}

export function descendants(node) {
  return [node, ...(node.children || []).flatMap(descendants)];
}

export function byTag(node, tagName) {
  return descendants(node).filter(each => each.tagName === tagName.toUpperCase());
}
