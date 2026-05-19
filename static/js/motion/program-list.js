import { D, apiCall, el, fetchWithConnectionState, reportSaveFailure, setStatusMessage, state } from '../context.js';
import { formatPatternDuration } from './pattern-list.js';
import { normalizeMotionTagList, tagPromptMessage, updateMotionTagSuggestions } from './tag-editor.js';


const TRASH_ICON = '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-2 6h10l-.7 11H7.7L7 9Zm3 2v7h2v-7h-2Zm3 0v7h2v-7h-2Z"></path></svg>';


let openMotionProgramWindowCallback = null;


export function configureMotionProgramList({openMotionProgramWindow} = {}) {
    openMotionProgramWindowCallback = openMotionProgramWindow || null;
}


export function formatProgramDuration(durationMs) {
    const duration = Math.max(0, Number(durationMs) || 0);
    if (duration >= 60_000) {
        const totalSeconds = Math.round(duration / 1000);
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;
    }
    return formatPatternDuration(duration);
}


export function formatProgramMetadata(program) {
    const parts = [
        program.source || 'imported',
        `${formatProgramDuration(program.duration_ms)} duration`,
        `${program.action_count || 0} actions`,
        'long funscript',
    ];
    const tags = Array.isArray(program.tags) ? program.tags.map(tag => String(tag).trim()).filter(Boolean) : [];
    if (tags.length) parts.push(`tags ${tags.join(', ')}`);
    return parts.join(' | ');
}


export function setProgramStatus(message, tone = 'neutral') {
    setStatusMessage(el.motionProgramStatus, message, tone);
}


function programDisplayName(program) {
    return program.name || program.id || 'Unnamed program';
}


function createProgramText(program) {
    const text = D.createElement('div');
    text.className = 'motion-pattern-text';

    const name = D.createElement('div');
    name.className = 'motion-pattern-name';
    name.textContent = programDisplayName(program);

    const meta = D.createElement('div');
    meta.className = 'motion-pattern-meta';
    meta.textContent = formatProgramMetadata(program);

    text.append(name, meta);
    if (program.description) {
        const description = D.createElement('div');
        description.className = 'motion-pattern-description';
        description.textContent = program.description;
        text.appendChild(description);
    }
    return text;
}


function createProgramExportButton(program) {
    const exportButton = D.createElement('button');
    exportButton.type = 'button';
    exportButton.className = 'my-button motion-pattern-export';
    exportButton.textContent = 'Export';
    exportButton.addEventListener('click', event => {
        event.stopPropagation?.();
        window.location.href = `/motion_programs/${encodeURIComponent(program.id)}/export`;
    });
    return exportButton;
}


function createProgramOpenButton(program) {
    const openButton = D.createElement('button');
    openButton.type = 'button';
    openButton.className = 'my-button motion-pattern-play motion-program-open';
    openButton.textContent = 'Open';
    openButton.addEventListener('click', event => {
        event.stopPropagation?.();
        openMotionProgramWindowCallback?.(program.id);
    });
    return openButton;
}


function createProgramRenameButton(program) {
    const renameButton = D.createElement('button');
    renameButton.type = 'button';
    renameButton.className = 'my-button motion-pattern-export motion-program-rename';
    renameButton.textContent = 'Rename';
    renameButton.addEventListener('click', event => {
        event.stopPropagation?.();
        renameMotionProgram(program);
    });
    return renameButton;
}


function createProgramTagsButton(program) {
    const tagsButton = D.createElement('button');
    tagsButton.type = 'button';
    tagsButton.className = 'my-button motion-pattern-tags motion-program-tags';
    tagsButton.textContent = 'Tags';
    tagsButton.setAttribute('data-requires-backend', '');
    tagsButton.title = `Edit tags for ${programDisplayName(program)}`;
    tagsButton.addEventListener('click', event => {
        event.stopPropagation?.();
        const current = Array.isArray(program.tags) ? program.tags.join(', ') : '';
        const next = window.prompt?.(tagPromptMessage('Program'), current);
        if (next === null || next === undefined) return;
        setMotionProgramTags(program.id, next);
    });
    return tagsButton;
}


function createProgramDeleteButton(program) {
    const deleteButton = D.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'my-button ollama-model-action ollama-model-delete motion-program-delete';
    deleteButton.innerHTML = TRASH_ICON;
    deleteButton.setAttribute('data-requires-backend', '');
    deleteButton.title = `Delete ${programDisplayName(program)}`;
    deleteButton.setAttribute('aria-label', `Delete ${programDisplayName(program)}`);
    deleteButton.addEventListener('click', event => {
        event.stopPropagation?.();
        deleteMotionProgram(program);
    });
    return deleteButton;
}


export async function renameMotionProgram(program, nextName) {
    const programId = typeof program === 'string' ? program : program?.id;
    if (!programId) return null;
    const currentName = typeof program === 'string' ? program : programDisplayName(program);
    let name = nextName;
    if (name === undefined) {
        name = window.prompt?.('Rename Program', currentName);
    }
    if (name === null || name === undefined) return null;
    name = String(name).trim();
    if (!name) {
        setProgramStatus('Program name is required.', 'warning');
        return null;
    }
    if (name === currentName) return null;
    setProgramStatus(`Renaming ${currentName}...`, 'neutral');
    const data = await apiCall(`/motion_programs/${encodeURIComponent(programId)}/rename`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name}),
    });
    if (data && data.status === 'success') {
        if (data.motion_programs) renderMotionPrograms(data.motion_programs);
        if (data.program && state.motionProgramSelected?.id === data.program.id) {
            state.motionProgramSelected = {...state.motionProgramSelected, ...data.program};
            if (el.motionProgramDialogTitle) el.motionProgramDialogTitle.textContent = data.program.name || data.program.id;
            if (el.motionProgramDialogMeta) el.motionProgramDialogMeta.textContent = formatProgramMetadata(data.program);
        }
        setStatusMessage(el.statusText, data.message || `Renamed program: ${name}.`, 'success');
    } else {
        reportSaveFailure(el.motionProgramStatus || el.statusText, data, `Could not rename ${currentName}.`);
    }
    return data;
}


export async function setMotionProgramTags(program, tags) {
    const programId = typeof program === 'string' ? program : program?.id;
    if (!programId) return null;
    const tagList = normalizeMotionTagList(tags);
    const data = await apiCall(`/motion_programs/${encodeURIComponent(programId)}/tags`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({tags: tagList}),
    });
    if (data && data.status === 'success') {
        if (data.motion_programs) renderMotionPrograms(data.motion_programs);
        if (data.program && state.motionProgramSelected?.id === data.program.id) {
            state.motionProgramSelected = {...state.motionProgramSelected, ...data.program};
            if (el.motionProgramDialogMeta) el.motionProgramDialogMeta.textContent = formatProgramMetadata(data.program);
        }
        setStatusMessage(el.statusText, data.message || 'Program tags updated.', 'success');
    } else {
        reportSaveFailure(el.motionProgramStatus || el.statusText, data, 'Could not update program tags.');
    }
    return data;
}


export async function deleteMotionProgram(program) {
    const programId = typeof program === 'string' ? program : program?.id;
    if (!programId) return null;
    const name = typeof program === 'string' ? program : programDisplayName(program);
    const ok = window.confirm(`Delete ${name} from Programs?`);
    if (!ok) return null;
    setProgramStatus(`Deleting ${name}...`, 'neutral');
    const data = await apiCall(`/motion_programs/${encodeURIComponent(programId)}`, {method: 'DELETE'});
    if (data && data.status === 'success') {
        if (data.motion_programs) renderMotionPrograms(data.motion_programs);
        setStatusMessage(el.statusText, data.message || `Deleted program: ${name}.`, 'success');
    } else {
        reportSaveFailure(el.motionProgramStatus || el.statusText, data, `Could not delete ${name}.`);
    }
    return data;
}


export function renderMotionPrograms(catalog = {}) {
    updateMotionTagSuggestions(catalog);
    const programs = Array.isArray(catalog.programs) ? catalog.programs : [];
    state.motionPrograms = programs;
    if (!el.motionProgramList) return;

    el.motionProgramList.replaceChildren();
    if (!programs.length) {
        const empty = D.createElement('div');
        empty.className = 'motion-program-empty';
        empty.textContent = 'No long programs saved yet. Import a funscript here to keep it separate from short LLM-selectable patterns.';
        el.motionProgramList.appendChild(empty);
    } else {
        programs.forEach(program => {
            const row = D.createElement('div');
            row.className = 'motion-pattern-row motion-program-row';

            const main = D.createElement('div');
            main.className = 'motion-pattern-main';
            main.appendChild(createProgramText(program));

            const actions = D.createElement('div');
            actions.className = 'motion-pattern-row-actions';
            actions.append(
                createProgramOpenButton(program),
                createProgramRenameButton(program),
                createProgramTagsButton(program),
                createProgramExportButton(program),
                createProgramDeleteButton(program),
            );

            row.append(main, actions);
            el.motionProgramList.appendChild(row);
        });
    }

    const errors = Array.isArray(catalog.errors) ? catalog.errors : [];
    if (errors.length) {
        setProgramStatus(`Loaded ${programs.length} programs. ${errors.length} file issue(s) need attention.`, 'warning');
    } else if (programs.length) {
        setProgramStatus(`Loaded ${programs.length} programs.`, 'success');
    } else {
        setProgramStatus('No long funscript programs saved yet.', 'neutral');
    }
}


export async function refreshMotionPrograms() {
    setProgramStatus('Loading programs...', 'neutral');
    const data = await apiCall('/motion_programs');
    if (data) renderMotionPrograms(data);
    return data;
}


export async function importMotionProgramFile(file) {
    if (!file) return;
    setProgramStatus(`Importing ${file.name}...`, 'neutral');
    const body = new FormData();
    body.append('program', file);
    try {
        const response = await fetchWithConnectionState('/import_motion_program', {method: 'POST', body});
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status !== 'success') {
            reportSaveFailure(el.motionProgramStatus || el.statusText, data, `Could not import ${file.name}.`);
            return;
        }
        if (data.motion_programs) renderMotionPrograms(data.motion_programs);
        setStatusMessage(el.statusText, `Imported program: ${data.program.name}.`, 'success');
    } catch (error) {
        if (!state.connectionLost) {
            setStatusMessage(el.motionProgramStatus || el.statusText, `Import failed: ${error.message}`, 'warning');
        }
    } finally {
        if (el.motionProgramImportInput) el.motionProgramImportInput.value = '';
    }
}


export function bindMotionProgramControls() {
    el.refreshMotionProgramsBtn?.addEventListener('click', refreshMotionPrograms);
    el.importMotionProgramBtn?.addEventListener('click', () => el.motionProgramImportInput?.click());
    el.motionProgramImportInput?.addEventListener('change', event => importMotionProgramFile(event.target.files?.[0]));
}
