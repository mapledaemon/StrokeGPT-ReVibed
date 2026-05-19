import { afterEach, beforeEach, describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { resetStubElement } from './_harness.mjs';
import {
    configureMotionProgramList,
    deleteMotionProgram,
    formatProgramDuration,
    formatProgramMetadata,
    renameMotionProgram,
    renderMotionPrograms,
    setMotionProgramTags,
} from '../../static/js/motion/program-list.js';
import { el, state } from '../../static/js/context.js';


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
        clone() { return factory(); },
    });
    return factory();
}


async function flushAsyncClickHandlers() {
    await Promise.resolve();
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
}


describe('motion program list helpers', () => {
    let originalFetch;
    let originalConfirm;
    let originalPrompt;

    beforeEach(() => {
        resetStubElement('motion-program-list');
        resetStubElement('motion-program-status');
        resetStubElement('motion-program-dialog-title');
        resetStubElement('motion-program-dialog-meta');
        resetStubElement('status-text');
        state.connectionLost = false;
        state.motionPrograms = [];
        state.motionProgramSelected = null;
        configureMotionProgramList({openMotionProgramWindow: null});
        originalFetch = globalThis.fetch;
        originalConfirm = globalThis.window.confirm;
        originalPrompt = globalThis.window.prompt;
        globalThis.window.confirm = () => true;
        globalThis.window.prompt = undefined;
    });

    afterEach(() => {
        globalThis.fetch = originalFetch;
        globalThis.window.confirm = originalConfirm;
        globalThis.window.prompt = originalPrompt;
    });

    it('formats long program durations in minutes', () => {
        assert.equal(formatProgramDuration(600_000), '10m');
        assert.equal(formatProgramDuration(610_000), '10m 10s');
        assert.equal(formatProgramDuration(1800), '1.8s');
    });

    it('renders a separate Programs list without touching motion patterns', () => {
        resetStubElement('motion-program-list');
        resetStubElement('motion-program-status');
        state.motionPatterns = [{id: 'stroke'}];

        renderMotionPrograms({
            programs: [
                {
                    id: 'long-wave',
                    name: 'Long Wave',
                    description: 'Saved long-form timeline.',
                    source: 'imported',
                    duration_ms: 600_000,
                    action_count: 2501,
                },
            ],
            errors: [],
        });

        assert.equal(state.motionPrograms.length, 1);
        assert.deepEqual(state.motionPatterns, [{id: 'stroke'}]);
        assert.equal(el.motionProgramList.children.length, 1);
        assert.equal(el.motionProgramStatus.textContent, 'Loaded 1 programs.');
        assert.equal(formatProgramMetadata(state.motionPrograms[0]), 'imported | 10m duration | 2501 actions | long funscript');
    });

    it('renders open, rename, tags, and trash buttons for Programs', async () => {
        const calls = [];
        const opened = [];
        configureMotionProgramList({openMotionProgramWindow: programId => opened.push(programId)});
        globalThis.fetch = async (endpoint, options = {}) => {
            calls.push({endpoint, options});
            return jsonResponse(200, {
                status: 'success',
                message: 'Deleted program: Long Wave.',
                program: {id: 'long-wave', name: 'Long Wave'},
                motion_programs: {programs: [], errors: []},
            });
        };

        renderMotionPrograms({
            programs: [{
                id: 'long-wave',
                name: 'Long Wave',
                source: 'imported',
                duration_ms: 600_000,
                action_count: 2501,
            }],
            errors: [],
        });

        const row = el.motionProgramList.children[0];
        const actions = row.children[1];
        const openButton = actions.children[0];
        const renameButton = actions.children[1];
        const tagsButton = actions.children[2];
        const deleteButton = actions.children[4];
        openButton.click();
        assert.deepEqual(opened, ['long-wave']);
        assert.equal(renameButton.textContent, 'Rename');
        assert.equal(tagsButton.textContent, 'Tags');
        assert.equal(tagsButton.hasAttribute('data-requires-backend'), true);
        assert.equal(deleteButton.getAttribute('aria-label'), 'Delete Long Wave');
        assert.equal(deleteButton.hasAttribute('data-requires-backend'), true);

        deleteButton.click();
        await flushAsyncClickHandlers();

        assert.equal(calls.length, 1);
        assert.equal(calls[0].endpoint, '/motion_programs/long-wave');
        assert.equal(calls[0].options.method, 'DELETE');
        assert.equal(state.motionPrograms.length, 0);
        assert.match(el.motionProgramList.children[0].textContent, /No long programs saved yet/);
        assert.equal(el.statusText.textContent, 'Deleted program: Long Wave.');
    });

    it('updates Program tags and mirrors an open Program player metadata row', async () => {
        const calls = [];
        state.motionProgramSelected = {
            id: 'long-wave',
            name: 'Long Wave',
            source: 'imported',
            duration_ms: 600_000,
            action_count: 2501,
            tags: ['program'],
        };
        el.motionProgramDialogMeta.textContent = 'baseline';
        globalThis.fetch = async (endpoint, options = {}) => {
            calls.push({endpoint, options});
            return jsonResponse(200, {
                status: 'success',
                message: 'Updated tags for Long Wave.',
                program: {
                    id: 'long-wave',
                    name: 'Long Wave',
                    source: 'imported',
                    duration_ms: 600_000,
                    action_count: 2501,
                    tags: ['teasing', 'program'],
                },
                motion_programs: {
                    programs: [{
                        id: 'long-wave',
                        name: 'Long Wave',
                        source: 'imported',
                        duration_ms: 600_000,
                        action_count: 2501,
                        tags: ['teasing', 'program'],
                    }],
                    errors: [],
                },
            });
        };

        const data = await setMotionProgramTags('long-wave', 'teasing, program');

        assert.equal(data.status, 'success');
        assert.equal(calls[0].endpoint, '/motion_programs/long-wave/tags');
        assert.equal(calls[0].options.method, 'POST');
        assert.deepEqual(JSON.parse(calls[0].options.body), {tags: ['teasing', 'program']});
        assert.equal(state.motionPrograms[0].tags[0], 'teasing');
        assert.match(el.motionProgramDialogMeta.textContent, /tags teasing, program/);
        assert.equal(el.statusText.textContent, 'Updated tags for Long Wave.');
    });

    it('renames a Program and updates an open Program player title', async () => {
        const calls = [];
        state.motionProgramSelected = {
            id: 'long-wave',
            name: 'Long Wave',
            source: 'imported',
            duration_ms: 600_000,
            action_count: 2501,
        };
        el.motionProgramDialogTitle.textContent = 'Long Wave';
        globalThis.fetch = async (endpoint, options = {}) => {
            calls.push({endpoint, options});
            return jsonResponse(200, {
                status: 'success',
                message: 'Renamed program: Renamed Wave.',
                program: {
                    id: 'long-wave',
                    name: 'Renamed Wave',
                    source: 'imported',
                    duration_ms: 600_000,
                    action_count: 2501,
                },
                motion_programs: {
                    programs: [{id: 'long-wave', name: 'Renamed Wave', source: 'imported', duration_ms: 600_000, action_count: 2501}],
                    errors: [],
                },
            });
        };

        const data = await renameMotionProgram({id: 'long-wave', name: 'Long Wave'}, 'Renamed Wave');

        assert.equal(data.status, 'success');
        assert.equal(calls[0].endpoint, '/motion_programs/long-wave/rename');
        assert.equal(calls[0].options.method, 'POST');
        assert.deepEqual(JSON.parse(calls[0].options.body), {name: 'Renamed Wave'});
        assert.equal(state.motionPrograms[0].name, 'Renamed Wave');
        assert.equal(state.motionProgramSelected.name, 'Renamed Wave');
        assert.equal(el.motionProgramDialogTitle.textContent, 'Renamed Wave');
        assert.equal(el.statusText.textContent, 'Renamed program: Renamed Wave.');
    });

    it('prompts for Program rename when no name is provided', async () => {
        const calls = [];
        globalThis.window.prompt = () => 'Prompted Wave';
        globalThis.fetch = async (endpoint, options = {}) => {
            calls.push({endpoint, options});
            return jsonResponse(200, {
                status: 'success',
                program: {id: 'long-wave', name: 'Prompted Wave'},
                motion_programs: {programs: [{id: 'long-wave', name: 'Prompted Wave'}], errors: []},
            });
        };

        await renameMotionProgram({id: 'long-wave', name: 'Long Wave'});

        assert.equal(calls.length, 1);
        assert.deepEqual(JSON.parse(calls[0].options.body), {name: 'Prompted Wave'});
    });

    it('does not delete when confirmation is cancelled', async () => {
        let called = false;
        globalThis.window.confirm = () => false;
        globalThis.fetch = async () => {
            called = true;
            return jsonResponse(200, {status: 'success'});
        };

        const result = await deleteMotionProgram({id: 'long-wave', name: 'Long Wave'});

        assert.equal(result, null);
        assert.equal(called, false);
    });

    it('renders an empty-state message for no saved programs', () => {
        renderMotionPrograms({programs: [], errors: []});

        assert.equal(el.motionProgramList.children.length, 1);
        assert.match(el.motionProgramList.children[0].textContent, /No long programs saved yet/);
        assert.equal(el.motionProgramStatus.textContent, 'No long funscript programs saved yet.');
    });
});
