import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { applyInitialSidebarState } from '../../static/js/setup.js';

let originalMatchMedia;
let originalLocalStorageDescriptor;
let originalWindowLocalStorage;

function setStoredSidebarPreference(value) {
    const storage = {
        getItem(key) {
            return key === 'sidebar_collapsed' ? value : null;
        },
    };
    Object.defineProperty(globalThis, 'localStorage', {
        value: storage,
        configurable: true,
        writable: true,
    });
    globalThis.window.localStorage = storage;
}

function setCompactViewport(matches) {
    globalThis.window.matchMedia = () => ({
        matches,
        addListener() {},
        removeListener() {},
        addEventListener() {},
        removeEventListener() {},
    });
}

describe('initial sidebar state', () => {
    beforeEach(() => {
        originalMatchMedia = globalThis.window.matchMedia;
        originalLocalStorageDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
        originalWindowLocalStorage = globalThis.window.localStorage;
        globalThis.document.body.className = '';
    });

    afterEach(() => {
        globalThis.window.matchMedia = originalMatchMedia;
        globalThis.window.localStorage = originalWindowLocalStorage;
        if (originalLocalStorageDescriptor) {
            Object.defineProperty(globalThis, 'localStorage', originalLocalStorageDescriptor);
        } else {
            delete globalThis.localStorage;
        }
        globalThis.document.body.className = '';
    });

    it('defaults compact screens to a collapsed sidebar when no preference exists', () => {
        setStoredSidebarPreference(null);
        setCompactViewport(true);

        applyInitialSidebarState();

        assert.equal(globalThis.document.body.classList.contains('sidebar-collapsed'), true);
    });

    it('keeps the sidebar open on compact screens when the user explicitly opened it', () => {
        globalThis.document.body.classList.add('sidebar-collapsed');
        setStoredSidebarPreference('false');
        setCompactViewport(true);

        applyInitialSidebarState();

        assert.equal(globalThis.document.body.classList.contains('sidebar-collapsed'), false);
    });

    it('honors a stored collapsed preference on wide screens', () => {
        setStoredSidebarPreference('true');
        setCompactViewport(false);

        applyInitialSidebarState();

        assert.equal(globalThis.document.body.classList.contains('sidebar-collapsed'), true);
    });

    it('keeps wide screens open when no preference exists', () => {
        globalThis.document.body.classList.add('sidebar-collapsed');
        setStoredSidebarPreference(null);
        setCompactViewport(false);

        applyInitialSidebarState();

        assert.equal(globalThis.document.body.classList.contains('sidebar-collapsed'), false);
    });
});
