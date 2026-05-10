// Behavioral coverage for the connection-lost banner/control-lock contract.
//
// Older coverage inspected context.js as source text. These tests drive the
// exported runtime helpers directly so a future refactor can move code without
// losing the user-visible behavior.

import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement, resetStubElement } from './_harness.mjs';
import {
    apiCall,
    applyBackendRequiredControlState,
    markRequiresBackend,
    setConnectionLost,
    state,
} from '../../static/js/context.js';


function jsonResponse(httpStatus, body) {
    const factory = () => ({
        ok: httpStatus >= 200 && httpStatus < 300,
        status: httpStatus,
        headers: {
            get(name) {
                return name && name.toLowerCase() === 'content-type'
                    ? 'application/json'
                    : null;
            },
        },
        async json() { return body; },
        async blob() { return null; },
        clone() { return factory(); },
    });
    return factory();
}


describe('connection-lost behavior', () => {
    let originalFetch;

    beforeEach(() => {
        originalFetch = globalThis.fetch;
        state.connectionLost = false;
        resetStubElement('connection-lost-banner').hidden = true;
        resetStubElement('status-text').textContent = 'baseline';
        resetStubElement('save-motion-backend-btn');
        resetStubElement('save-timings-btn');
    });

    afterEach(() => {
        globalThis.fetch = originalFetch;
        state.connectionLost = false;
        setConnectionLost(false);
    });

    it('setConnectionLost toggles the persistent banner and restores controls', () => {
        const banner = getStubElement('connection-lost-banner');
        const control = markRequiresBackend(getStubElement('save-motion-backend-btn'));

        setConnectionLost(true);

        assert.equal(state.connectionLost, true);
        assert.equal(banner.hidden, false);
        assert.equal(control.disabled, true);
        assert.equal(control.dataset.backendLocked, 'true');
        assert.equal(control.getAttribute('aria-disabled'), 'true');

        setConnectionLost(false);

        assert.equal(state.connectionLost, false);
        assert.equal(banner.hidden, true);
        assert.equal(control.disabled, false);
        assert.equal(control.dataset.backendLocked, undefined);
        assert.equal(control.getAttribute('aria-disabled'), null);
    });

    it('restores only controls that were enabled before the backend lock', () => {
        const initiallyDisabled = markRequiresBackend(getStubElement('save-timings-btn'));
        initiallyDisabled.disabled = true;

        setConnectionLost(true);
        assert.equal(initiallyDisabled.disabled, true);

        setConnectionLost(false);
        assert.equal(initiallyDisabled.disabled, true);
        assert.equal(initiallyDisabled.dataset.backendLocked, undefined);
    });

    it('network failures show the banner while HTTP errors keep it hidden', async () => {
        globalThis.fetch = async () => {
            throw new Error('backend is gone');
        };

        const networkResult = await apiCall('/check_settings');
        assert.equal(networkResult, undefined);
        assert.equal(state.connectionLost, true);
        assert.equal(getStubElement('connection-lost-banner').hidden, false);
        assert.equal(getStubElement('status-text').textContent, 'Error: Cannot connect to server.');

        globalThis.fetch = async () => jsonResponse(400, {
            status: 'error',
            message: 'Persona prompt is required.',
        });

        const httpResult = await apiCall('/set_persona_prompt', { method: 'POST' });
        assert.equal(httpResult, undefined);
        assert.equal(state.connectionLost, false);
        assert.equal(getStubElement('connection-lost-banner').hidden, true);
        assert.equal(getStubElement('status-text').textContent, 'Persona prompt is required.');
    });

    it('applyBackendRequiredControlState can lock dynamic controls immediately', () => {
        const dynamic = getStubElement('dynamic-import-pattern');
        dynamic.dataset.requiresBackend = 'true';
        state.connectionLost = true;

        applyBackendRequiredControlState(dynamic);

        assert.equal(dynamic.disabled, true);
        assert.equal(dynamic.dataset.backendLocked, 'true');
    });
});
