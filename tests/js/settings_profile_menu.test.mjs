// Behavioral coverage for the upper-right profile menu. The profile image is
// now the settings entry point, so the menu must open/close independently of
// the right sidebar.

import { describe, it, before, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement } from './_harness.mjs';
import { initSettingsControls, openSettings } from '../../static/js/settings.js';


describe('settings profile menu', () => {
    before(() => {
        initSettingsControls({ addChatMessage: () => {} });
    });

    beforeEach(() => {
        const menuButton = getStubElement('profile-menu-btn');
        const popover = getStubElement('profile-menu-popover');
        const settingsDialog = getStubElement('settings-dialog');
        menuButton.setAttribute('aria-expanded', 'false');
        popover.hidden = true;
        settingsDialog.className = '';
    });

    it('toggles the profile menu from the top-bar image button', () => {
        const menuButton = getStubElement('profile-menu-btn');
        const popover = getStubElement('profile-menu-popover');

        menuButton.click();
        assert.strictEqual(menuButton.getAttribute('aria-expanded'), 'true');
        assert.strictEqual(popover.hidden, false);

        menuButton.click();
        assert.strictEqual(menuButton.getAttribute('aria-expanded'), 'false');
        assert.strictEqual(popover.hidden, true);
    });

    it('closes the profile menu when opening settings', () => {
        const menuButton = getStubElement('profile-menu-btn');
        const popover = getStubElement('profile-menu-popover');
        const settingsDialog = getStubElement('settings-dialog');
        menuButton.setAttribute('aria-expanded', 'true');
        popover.hidden = false;

        openSettings('persona');

        assert.strictEqual(menuButton.getAttribute('aria-expanded'), 'false');
        assert.strictEqual(popover.hidden, true);
        assert.strictEqual(settingsDialog.classList.contains('open'), true);
    });
});
