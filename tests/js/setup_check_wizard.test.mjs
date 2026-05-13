import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { renderLatencyResults, renderMotionTransportCapture, renderSetupCheckResults } from '../../static/js/setup-check.js';


describe('settings diagnostics tab', () => {
    beforeEach(() => {
        resetStubElement('setup-check-results');
        resetStubElement('latency-test-results');
        resetStubElement('motion-capture-results');
        resetStubElement('motion-capture-output');
        resetStubElement('start-motion-capture-btn');
        resetStubElement('finish-motion-capture-btn');
        resetStubElement('download-motion-capture-btn');
        resetStubElement('setup-check-status');
    });

    it('renders grouped setup rows without losing backend detail', () => {
        renderSetupCheckResults({
            summary: {
                status: 'warning',
                message: 'Setup check completed with performance warnings.',
            },
            sections: [
                {
                    id: 'ollama',
                    title: 'Ollama',
                    items: [
                        {
                            id: 'ollama-gpu',
                            label: 'Ollama GPU acceleration',
                            status: 'warning',
                            detail: 'Ollama reports the selected model is running in system memory only.',
                        },
                    ],
                },
            ],
        });

        const setupResults = getStubElement('setup-check-results');
        assert.match(setupResults.children[0].className, /setup-check-summary warning/);
        assert.equal(setupResults.children[0].textContent, 'Setup check completed with performance warnings.');

        const list = setupResults.children[1];
        const section = list.children[0];
        const row = section.children[1];
        assert.match(row.className, /setup-check-row warning/);
        assert.equal(row.children[0].textContent, 'Warning');
        assert.equal(row.children[1].children[0].textContent, 'Ollama GPU acceleration');
        assert.equal(
            row.children[1].children[1].textContent,
            'Ollama reports the selected model is running in system memory only.',
        );
    });

    it('renders latency measurements and skip detail', () => {
        renderLatencyResults({
            summary: { status: 'warning', message: 'Latency diagnostics completed with warnings or skipped checks.' },
            tests: [
                {
                    id: 'ollama-generation',
                    label: 'Ollama response',
                    status: 'ok',
                    elapsed_ms: 523,
                    detail: 'model responded in 523 ms.',
                    metrics: { ollama_total_ms: 520, eval_count: 7 },
                },
                {
                    id: 'voice-output',
                    label: 'Voice output',
                    status: 'skipped',
                    detail: 'Local voice model is not loaded.',
                },
            ],
        });

        const results = getStubElement('latency-test-results');
        assert.match(results.children[0].className, /setup-check-summary warning/);
        const firstRow = results.children[1].children[0];
        assert.match(firstRow.className, /latency-test-row ok/);
        assert.equal(firstRow.children[1].children[0].textContent, 'Ollama response');
        assert.equal(firstRow.children[2].textContent, '523ms');
        assert.match(firstRow.children[1].children[2].children[0].textContent, /Ollama Total Ms: 520/);

        const secondRow = results.children[1].children[1];
        assert.match(secondRow.className, /latency-test-row skipped/);
        assert.equal(secondRow.children[0].textContent, 'Skipped');
    });

    it('renders motion transport capture summary and JSON payload', () => {
        renderMotionTransportCapture({
            active: false,
            capture: {
                run: { backend: 'continuous', firmware: 'fw4' },
                summary: {
                    status: 'ok',
                    message: 'Captured HSP timed-point transport.',
                    trace_rows: 3,
                    command_rows: 2,
                    hsp_commands: 2,
                    hdsp_commands: 0,
                    hamp_or_mode_commands: 0,
                    failed_commands: 0,
                    path_counts: { 'hsp/add': 1, 'hsp/play': 1 },
                },
                motion_trace: [{ continuous_schema: 'hsp', depth: 60 }],
                handy_command_history: [{ path: 'hsp/play', ok: true }],
            },
        });

        const results = getStubElement('motion-capture-results');
        assert.match(results.children[0].className, /setup-check-summary ok/);
        assert.equal(results.children[0].textContent, 'Captured HSP timed-point transport.');
        assert.match(results.children[1].children[0].textContent, /Trace rows: 3/);
        assert.match(results.children[2].children[0].textContent, /hsp\/add: 1/);

        const output = getStubElement('motion-capture-output');
        assert.match(output.textContent, /"continuous_schema": "hsp"/);
        assert.equal(getStubElement('start-motion-capture-btn').disabled, false);
        assert.equal(getStubElement('finish-motion-capture-btn').disabled, true);
        assert.equal(getStubElement('download-motion-capture-btn').disabled, false);
    });
});
