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

    const stub = {
        tagName: tag.toUpperCase(),
        nodeName: tag.toUpperCase(),
        nodeType: 1,
        className: '',
        classList: null, // populated below so it can reference `stub`
        style: {},
        dataset: {},
        textContent: '',
        innerHTML: '',
        title: '',
        value: '',
        hidden: false,
        checked: false,
        disabled: false,
        files: null,
        parentNode: null,
        children,
        get childNodes() { return children; },
        get firstChild() { return children[0] || null; },
        get firstElementChild() { return children[0] || null; },
        get lastChild() { return children[children.length - 1] || null; },
        get lastElementChild() { return children[children.length - 1] || null; },
        appendChild(child) {
            child.parentNode = stub;
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
        querySelectorAll() {
            const list = [];
            list.constructor = { name: NODE_LIST_TYPE };
            return list;
        },
        querySelector() { return null; },
        getAttribute() { return null; },
        setAttribute() {},
        removeAttribute() {},
        hasAttribute() { return false; },
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
    };

    stub.classList = {
        _set: new Set(),
        add(...cls) {
            for (const c of cls) this._set.add(c);
            stub.className = [...this._set].join(' ');
        },
        remove(...cls) {
            for (const c of cls) this._set.delete(c);
            stub.className = [...this._set].join(' ');
        },
        contains(c) { return this._set.has(c); },
        toggle(c) {
            if (this._set.has(c)) this._set.delete(c);
            else this._set.add(c);
            stub.className = [...this._set].join(' ');
            return this._set.has(c);
        },
    };

    return stub;
}

const elementStore = new Map();

function getOrCreateElement(id, tag = 'div') {
    if (!elementStore.has(id)) elementStore.set(id, makeStubElement(tag));
    return elementStore.get(id);
}

globalThis.document = {
    getElementById(id) { return getOrCreateElement(id); },
    querySelectorAll() {
        const list = [];
        list.constructor = { name: NODE_LIST_TYPE };
        return list;
    },
    querySelector() { return null; },
    createElement(tag) { return makeStubElement(tag); },
    createTextNode(text) { return { nodeType: 3, textContent: String(text), data: String(text) }; },
    createDocumentFragment() {
        const frag = makeStubElement('#document-fragment');
        frag.nodeType = 11;
        return frag;
    },
    addEventListener() {},
    removeEventListener() {},
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

globalThis.navigator = globalThis.window.navigator;
globalThis.location = globalThis.window.location;

// Default fetch throws; tests that exercise apiCall must replace it.
globalThis.fetch = async () => {
    throw new Error('fetch is not stubbed; replace globalThis.fetch in your test');
};

// performance.now exists by default in modern Node; guard for older builds.
if (!globalThis.performance) globalThis.performance = { now: () => Date.now() };

// MediaRecorder, FormData, Blob: provide stub-shaped placeholders so
// imports that REFERENCE these constructors at top-level succeed. Tests
// that exercise voice input can replace these with real implementations.
globalThis.MediaRecorder = globalThis.MediaRecorder || class StubMediaRecorder {};
globalThis.FormData = globalThis.FormData || class StubFormData {};
globalThis.Blob = globalThis.Blob || class StubBlob {};

// Helpers for tests to peek into the store. Importable from test files.
export function getStubElement(id) {
    return getOrCreateElement(id);
}

export function resetStubElement(id) {
    const stub = getOrCreateElement(id);
    stub.replaceChildren();
    stub.textContent = '';
    stub.title = '';
    stub.style = {};
    stub.className = '';
    stub.classList._set.clear();
    return stub;
}

export function makeStandaloneStubElement(tag = 'div') {
    return makeStubElement(tag);
}
