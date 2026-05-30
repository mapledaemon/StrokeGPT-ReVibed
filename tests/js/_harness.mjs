// Backlog #13 frontend test harness. Installed via
//   node --import ./tests/js/_harness.mjs --test ./tests/js
// so that `globalThis.document` and friends exist before any production
// browser ES module evaluates.
//
// The browser modules under static/js/ touch `document.getElementById(...)`
// and `document.querySelectorAll(...)` at module-load time (see context.js's
// frozen `el` object). A Node test process that imports those modules
// without a DOM crashes during evaluation, before any test body runs.
//
// This harness does NOT replace jsdom. It is a deliberately tiny stub:
// enough surface for the existing motion-control / sequence-log behavior
// tests, and intended to grow ONLY as new behavioral tests force it. If a
// future test needs a real DOM API the stub does not implement, prefer
// extending the stub by one method over reaching for a heavier dependency
// (jsdom, happy-dom). Drop in jsdom only when the maintenance cost of the
// stub exceeds the install cost of the real DOM library.
//
// Filename starts with `_` so `node --test` does NOT auto-discover it as a
// test file. It is loaded only via `--import`.

const NODE_LIST_TYPE = 'NodeList';

function makeStubElement(tag = 'div') {
    const children = [];
    const listeners = Object.create(null);
    const attributes = Object.create(null);
    // Single source of truth for class state. `className` is a getter/setter
    // that delegates here so the two stay in sync the way the real DOM
    // keeps them in sync. Without this, `el.className = 'foo'` followed by
    // `el.classList.add('bar')` ends up dropping 'foo' because the
    // classList method rewrites the property from its internal Set.
    const classes = new Set();
    // Backing field for the textContent getter/setter. Real DOM clears the
    // element's children when textContent is assigned, replacing them with
    // a single text node holding the new value. Production code under
    // test relies on this to "clear" the sequence log via
    // ``el.motionSequenceIndicator.textContent = 'Idle';`` -- without
    // mirroring that side effect, leftover entry divs stick around and
    // ``resetMotionSequenceLog`` looks like a no-op.
    let textContent = '';

    const stub = {
        tagName: tag.toUpperCase(),
        nodeName: tag.toUpperCase(),
        nodeType: 1,
        style: {},
        dataset: {},
        innerHTML: '',
        title: '',
        value: '',
        hidden: false,
        open: false,
        checked: false,
        disabled: false,
        files: null,
        parentNode: null,
        children,
        get options() { return children; },
        get className() { return [...classes].join(' '); },
        set className(value) {
            classes.clear();
            for (const c of String(value).split(/\s+/).filter(Boolean)) classes.add(c);
        },
        get textContent() { return textContent; },
        set textContent(value) {
            textContent = String(value ?? '');
            for (const c of children) if (c) c.parentNode = null;
            children.length = 0;
        },
        classList: {
            add(...cls) { for (const c of cls) classes.add(c); },
            remove(...cls) { for (const c of cls) classes.delete(c); },
            contains(c) { return classes.has(c); },
            toggle(c, force) {
                if (force === true) classes.add(c);
                else if (force === false) classes.delete(c);
                else if (classes.has(c)) classes.delete(c);
                else classes.add(c);
                return classes.has(c);
            },
            get _set() { return classes; },
        },
        get childNodes() { return children; },
        get firstChild() { return children[0] || null; },
        get firstElementChild() { return children[0] || null; },
        get lastChild() { return children[children.length - 1] || null; },
        get lastElementChild() { return children[children.length - 1] || null; },
        appendChild(child) {
            if (child && typeof child === 'object') child.parentNode = stub;
            children.push(child);
            return child;
        },
        append(...nodes) {
            for (const n of nodes) {
                if (n && typeof n === 'object') n.parentNode = stub;
                children.push(n);
            }
        },
        prepend(...nodes) {
            for (const n of nodes.slice().reverse()) {
                if (n && typeof n === 'object') n.parentNode = stub;
                children.unshift(n);
            }
        },
        insertBefore(newNode, ref) {
            if (newNode && typeof newNode === 'object') newNode.parentNode = stub;
            const i = ref ? children.indexOf(ref) : -1;
            if (i >= 0) children.splice(i, 0, newNode);
            else children.push(newNode);
            return newNode;
        },
        removeChild(child) {
            const i = children.indexOf(child);
            if (i >= 0) {
                children.splice(i, 1);
                if (child) child.parentNode = null;
            }
            return child;
        },
        replaceChildren(...nodes) {
            for (const c of children) if (c) c.parentNode = null;
            children.length = 0;
            for (const n of nodes) {
                if (n && typeof n === 'object') n.parentNode = stub;
                children.push(n);
            }
        },
        addEventListener(name, fn) {
            (listeners[name] ||= []).push(fn);
        },
        removeEventListener(name, fn) {
            if (!listeners[name]) return;
            listeners[name] = listeners[name].filter(f => f !== fn);
        },
        dispatchEvent(name, event = {}) {
            for (const fn of (listeners[name] || [])) fn(event);
        },
        querySelectorAll(selector = '[data-requires-backend]') {
            const list = collectMatchingDescendants(stub, selector);
            list.constructor = { name: NODE_LIST_TYPE };
            return list;
        },
        querySelector(selector) { return stub.querySelectorAll(selector)[0] || null; },
        getAttribute(name) { return attributes[name] ?? null; },
        setAttribute(name, value = '') {
            attributes[name] = String(value);
            if (name === 'data-requires-backend') stub.dataset.requiresBackend = 'true';
        },
        removeAttribute(name) {
            delete attributes[name];
            if (name === 'data-requires-backend') delete stub.dataset.requiresBackend;
        },
        hasAttribute(name) { return Object.hasOwn(attributes, name); },
        matches(selector) {
            return selector === '[data-requires-backend]' && stub.dataset.requiresBackend === 'true';
        },
        closest(selector) {
            let node = stub;
            while (node) {
                if (node.matches?.(selector)) return node;
                node = node.parentNode;
            }
            return null;
        },
        focus() {},
        blur() {},
        click() {
            for (const fn of (listeners.click || [])) fn({ target: stub, type: 'click' });
        },
        scrollTop: 0,
        scrollHeight: 0,
        offsetHeight: 0,
        offsetTop: 0,
        offsetWidth: 0,
        clientHeight: 0,
        clientWidth: 0,
        getBoundingClientRect() { return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }; },
        _clearAttributes() {
            for (const key of Object.keys(attributes)) delete attributes[key];
        },
    };

    return stub;
}

const elementStore = new Map();

function getOrCreateElement(id, tag = 'div') {
    if (!elementStore.has(id)) elementStore.set(id, makeStubElement(tag));
    return elementStore.get(id);
}

function collectMatchingDescendants(root, selector = '[data-requires-backend]') {
    const result = [];
    const visit = node => {
        if (!node || typeof node !== 'object') return;
        if (node !== root && node.matches?.(selector)) result.push(node);
        for (const child of node.children || []) visit(child);
    };
    visit(root);
    return result;
}

function matchingStoredElements(selector = '[data-requires-backend]') {
    return [...elementStore.values()].filter(element => element.matches?.(selector));
}

const documentListeners = Object.create(null);

globalThis.document = {
    getElementById(id) { return getOrCreateElement(id); },
    querySelectorAll(selector = '[data-requires-backend]') {
        const list = matchingStoredElements(selector);
        list.constructor = { name: NODE_LIST_TYPE };
        return list;
    },
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    createElement(tag) { return makeStubElement(tag); },
    createTextNode(text) { return { nodeType: 3, textContent: String(text), data: String(text) }; },
    createDocumentFragment() {
        const frag = makeStubElement('#document-fragment');
        frag.nodeType = 11;
        return frag;
    },
    addEventListener(name, fn) {
        (documentListeners[name] ||= []).push(fn);
    },
    removeEventListener(name, fn) {
        if (!documentListeners[name]) return;
        documentListeners[name] = documentListeners[name].filter(f => f !== fn);
    },
    dispatchEvent(event) {
        const type = typeof event === 'string' ? event : event?.type;
        for (const fn of (documentListeners[type] || [])) fn(event);
    },
    documentElement: makeStubElement('html'),
    body: makeStubElement('body'),
    head: makeStubElement('head'),
};

globalThis.window = {
    addEventListener() {},
    removeEventListener() {},
    requestAnimationFrame: (fn) => setTimeout(fn, 16),
    cancelAnimationFrame: (id) => clearTimeout(id),
    matchMedia: () => ({
        matches: false,
        addListener() {}, removeListener() {},
        addEventListener() {}, removeEventListener() {},
    }),
    location: { href: 'http://localhost/', origin: 'http://localhost', pathname: '/' },
    navigator: { userAgent: 'strokegpt-frontend-test-harness' },
    document: globalThis.document,
    setTimeout, clearTimeout, setInterval, clearInterval,
};

// Some Web API globals (navigator, location, fetch, performance) ship with
// modern Node as read-only getters per the WICG/WebIDL spec. Older Node
// builds let us assign directly. The defensive helper installs the stub
// only when the global is missing, and falls back to defineProperty when
// a plain assignment would throw on a read-only descriptor.
function installGlobal(name, value) {
    if (name in globalThis && globalThis[name] !== undefined) return;
    try {
        globalThis[name] = value;
    } catch {
        try {
            Object.defineProperty(globalThis, name, {
                value,
                writable: true,
                configurable: true,
                enumerable: true,
            });
        } catch { /* unreplaceable on this runtime; production code must tolerate Node's default */ }
    }
}

installGlobal('navigator', globalThis.window.navigator);
installGlobal('location', globalThis.window.location);
installGlobal('CustomEvent', class StubCustomEvent {
    constructor(type, options = {}) {
        this.type = type;
        this.detail = options.detail;
    }
});

// Default fetch throws; tests that exercise apiCall must replace it.
installGlobal('fetch', async () => {
    throw new Error('fetch is not stubbed; replace globalThis.fetch in your test');
});

// performance.now exists by default in modern Node; guard for older builds.
installGlobal('performance', { now: () => Date.now() });

// MediaRecorder, FormData, Blob: provide stub-shaped placeholders so
// imports that REFERENCE these constructors at top-level succeed. Tests
// that exercise voice input can replace these with real implementations.
installGlobal('MediaRecorder', class StubMediaRecorder {});
installGlobal('FormData', class StubFormData {});
installGlobal('Blob', class StubBlob {});

// Helpers for tests to peek into the store. Importable from test files.
export function getStubElement(id) {
    return getOrCreateElement(id);
}

export function resetStubElement(id) {
    const stub = getOrCreateElement(id);
    stub.replaceChildren();
    stub.textContent = '';
    stub.title = '';
    stub.value = '';
    stub.checked = false;
    stub.style = {};
    stub.className = ''; // setter clears the classList _set too
    stub.dataset = {};
    stub.disabled = false;
    stub.hidden = false;
    stub.open = false;
    stub._clearAttributes?.();
    return stub;
}

export function makeStandaloneStubElement(tag = 'div') {
    return makeStubElement(tag);
}
