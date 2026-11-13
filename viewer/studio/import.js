// Import & Adaptation: bring your own rig, review its joint labels and facing, then build
// the asset UniMate animates. The port of UniMate's own workflow, in the studio.

import { followJob, statusUrlFor, jobEnd } from './jobs.js';
import { closeSheet } from './pages.js';
import { openMotionImport } from './motion.js';

const esc = (text) => String(text ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function openRigImport({ stage, ctx, onResult, prefill = null }) {
  closeSheet(stage);
  const el = document.createElement('div');
  el.className = 'sheet';
  el.innerHTML = `
    <form class="sheet-card rig-import" novalidate>
      <div class="sheet-top"><h2>Import a <span>rig</span></h2><button type="button" class="ghost" data-close>Cancel</button></div>
      <p class="hint">Bring a rigged GLB / glTF / FBX. UniMate labels its joints, you check and
        fix them, then it builds the asset — after which the studio can move it.
        ${ctx.motionReady === false ? `<b>${esc(ctx.motionNote || 'UniMate is not set up.')}</b>` : ''}</p>
      <div data-source>
        <input type="file" data-upload accept=".glb,.gltf,.fbx" hidden>
        <div class="drop" data-drop tabindex="0" role="button">Drop a rigged GLB / glTF / FBX here, or click to choose</div>
        <label class="field">…or a server path<input type="text" data-path placeholder="D:\\models\\my_rig.fbx"></label>
        <div class="row">
          <label class="field">Asset name<input type="text" data-name placeholder="from the file"></label>
          <label class="field">Profile<select data-profile>
            <option value="auto">auto</option><option value="general">general</option>
            <option value="objaverse">objaverse</option><option value="truebones">truebones</option></select></label>
        </div>
        <label class="field">Joint labels<select data-annotate>
          <option value="rule">rules (offline, no model)</option><option value="llm">an LLM (local or API)</option></select></label>
        <div data-llm hidden>
          <div class="row">
            <label class="field">Backend<select data-backend>
              <option value="openai">OpenAI-compatible server (LM Studio / Ollama / vLLM)</option>
              <option value="local">local HuggingFace model</option></select></label>
            <label class="field">Model<input type="text" data-model placeholder="the name your server shows"></label>
          </div>
          <div class="row">
            <label class="field">Base URL <span class="hint">LM Studio: http://127.0.0.1:1234/v1</span><input type="text" data-base-url value="http://127.0.0.1:1234/v1"></label>
            <label class="field">API key <span class="hint">blank for a local server</span><input type="text" data-api-key placeholder="(none)"></label>
          </div>
          <p class="hint" data-local-note hidden>A local model is fetched from Hugging Face on first use (size depends on
            the model) and loads into UniMate's own environment. Keep the rig in rule mode if
            you would rather not download one.</p>
        </div>
        <label class="check"><input type="checkbox" data-clips><span>Keep the asset's clips <span class="hint">for in-betweening / editing</span></span></label>
        <button type="submit" class="primary">Analyse</button>
      </div>
      <div data-review hidden></div>
      <p class="error" data-error hidden></p>
      <div data-out class="rig-out" hidden></div>
    </form>`;
  stage.appendChild(el);

  const $ = (sel) => el.querySelector(sel);
  const upload = $('[data-upload]');
  const drop = $('[data-drop]');
  const path = $('[data-path]');
  const name = $('[data-name]');
  const profile = $('[data-profile]');
  const clips = $('[data-clips]');
  const annotate = $('[data-annotate]');
  const llmBox = $('[data-llm]');
  const backend = $('[data-backend]');
  const model = $('[data-model]');
  const baseUrl = $('[data-base-url]');
  const apiKey = $('[data-api-key]');
  const localNote = $('[data-local-note]');
  const out = $('[data-out]');
  const fail = (message) => { const e = $('[data-error]'); e.textContent = message; e.hidden = false; };
  const progress = (text) => {
    out.hidden = false;
    out.innerHTML = `<div class="job"><div class="bigbar"><span></span></div><p class="job-msg">${esc(text)}</p></div>`;
    return { bar: out.querySelector('.bigbar span'), msg: out.querySelector('.job-msg') };
  };

  drop.onclick = () => upload.click();
  drop.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); upload.click(); } };
  upload.onchange = () => { drop.textContent = upload.files[0]?.name || 'Drop a rigged GLB / glTF / FBX here, or click to choose'; };

  const llmSettings = () => {
    if (annotate.value !== 'llm') return {};
    return { model: model.value.trim(), backend: backend.value, base_url: baseUrl.value.trim(),
      api_key: apiKey.value.trim() };
  };
  const syncLlm = () => {
    llmBox.hidden = annotate.value !== 'llm';
    localNote.hidden = backend.value !== 'local';
  };
  annotate.onchange = syncLlm;
  backend.onchange = syncLlm;
  syncLlm();

  let analysed = null;   // { directory, annotation, source }
  const chosenFile = () => upload.files[0] || prefill?.file || null;

  const runAnalyse = async () => {
    const file = chosenFile();
    const pathValue = path.value.trim();
    if (!file && !pathValue) return fail('Choose a GLB to upload, or give a path.');
    let body;
    if (file) {
      const form = new FormData();
      form.append('asset', file);
      form.append('settings', JSON.stringify({ name: name.value.trim(), profile: profile.value,
        annotate: annotate.value, ...llmSettings(), rest_rotation: '', save_clips: clips.checked }));
      body = form;
    } else {
      body = JSON.stringify({ path: pathValue, name: name.value.trim(), profile: profile.value,
        annotate: annotate.value, ...llmSettings(), rest_rotation: '', save_clips: clips.checked });
    }
    const { bar, msg } = progress('Analysing…');
    let start;
    try {
      const response = await fetch('/api/import/analyze', { method: 'POST',
        ...(typeof body === 'string' ? { headers: { 'Content-Type': 'application/json' }, body } : { body }) });
      start = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(start.error || `HTTP ${response.status}`);
    } catch (error) {
      out.innerHTML = `<p class="job-msg">${esc(error.message || 'Could not start.')}</p>`;
      return;
    }
    const job = followJob(statusUrlFor('import', start), { interval: 1200, onUpdate: ({ event, percent }) => {
      msg.textContent = event.message || event.phase || 'Analysing…';
      if (percent != null) bar.style.width = `${percent}%`; else bar.classList.add('busy');
    } });
    const final = await job.done;
    if (final.status !== 'done') {
      out.innerHTML = `<p class="job-msg">${esc(jobEnd(final).why)}</p>`;
      return;
    }
    const directory = final.last_event?.directory;
    const annotation = await (await fetch(`/${directory}/annotation.json`)).json().catch(() => null);
    if (!annotation || !Array.isArray(annotation.joints)) {
      out.innerHTML = '<p class="job-msg">The analysis produced no annotation.</p>';
      return;
    }
    analysed = { directory, annotation };
    $('[data-source]').hidden = true;
    out.hidden = true;
    renderReview(directory, annotation);
  };

  const renderReview = (directory, annotation) => {
    const review = $('[data-review]');
    review.hidden = false;
    const fp = annotation.face_pair || {};
    review.innerHTML = `
      <p class="hint">Check the joint labels and the facing pair, fix what is wrong, then build.
        Only the <b>label</b> column and the facing pair are editable.</p>
      <div class="row">
        <img class="rig-preview" src="${esc(`/${directory}/annotation_preview.png`)}" alt="Annotation preview">
        <div class="grow">
          <label class="field">Facing pair — two joints that define forward<span class="hint">right / left limbs, or head/tail with “head–tail axis”.</span></label>
          <div class="row">
            <input type="text" data-face-r placeholder="right (or head)" value="${esc(fp.right || '')}">
            <input type="text" data-face-l placeholder="left (or tail)" value="${esc(fp.left || '')}">
          </div>
          <label class="check"><input type="checkbox" data-body-axis ${fp.body_axis ? 'checked' : ''}><span>Head / tail axis (limbless body)</span></label>
        </div>
      </div>
      <div class="joints"><table>
        <thead><tr><th>#</th><th>raw</th><th>parent</th><th>label</th></tr></thead>
        <tbody>${annotation.joints.map((j, i) => `<tr>
          <td class="meta">${i}</td><td>${esc(j.raw || '')}</td><td class="meta">${esc(j.parent || '')}</td>
          <td><input data-label="${i}" value="${esc(j.label || '')}"></td></tr>`).join('')}
        </tbody></table></div>
      <div class="row end">
        <button type="button" class="ghost" data-again>Analyse again</button>
        <button type="button" class="primary" data-build>Build asset</button>
      </div>`;

    review.querySelector('[data-again]').onclick = () => { $('[data-source]').hidden = false; review.hidden = true; analysed = null; };
    review.querySelector('[data-build]').onclick = () => runBuild(directory, annotation);
  };

  const runBuild = async (directory, annotation) => {
    // read the edited labels and facing back into the annotation
    const review = $('[data-review]');
    annotation.joints.forEach((j, i) => {
      const input = review.querySelector(`[data-label="${i}"]`);
      if (input) {
        const label = input.value.trim();
        if (label) { j.label = label; j.source = 'manual'; delete j.check; delete j.reasons; }
      }
    });
    annotation.face_pair = { right: review.querySelector('[data-face-r]').value.trim(),
      left: review.querySelector('[data-face-l]').value.trim(),
      body_axis: review.querySelector('[data-body-axis]').checked, source: 'manual' };
    annotation.n_flagged = 0;

    const { bar, msg } = progress('Building…');
    let start;
    try {
      const response = await fetch('/api/import/build', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ directory, profile: profile.value, annotation, save_clips: clips.checked }) });
      start = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(start.error || `HTTP ${response.status}`);
    } catch (error) {
      out.innerHTML = `<p class="job-msg">${esc(error.message || 'Could not start.')}</p>`;
      return;
    }
    const job = followJob(statusUrlFor('import', start), { interval: 1200, onUpdate: ({ event, percent }) => {
      msg.textContent = event.message || event.phase || 'Building…';
      if (percent != null) bar.style.width = `${percent}%`; else bar.classList.add('busy');
    } });
    const final = await job.done;
    if (final.status !== 'done') {
      out.innerHTML = `<p class="job-msg">${esc(jobEnd(final).why)}</p>`;
      return;
    }
    const summary = await (await fetch(`/${directory}/summary.json`)).json().catch(() => null);
    const glb = summary?.canonical_glb || `/${directory}/${name.value || 'asset'}.glb`;
    out.innerHTML = `<p class="job-msg">Asset ready.</p>
      <div class="row end"><button type="button" class="primary" data-animate>Animate it</button></div>`;
    out.querySelector('[data-animate]').onclick = () => {
      el.remove();
      openMotionImport({ stage, ctx, onResult, prefill: { path: directory } });
    };
  };

  el.querySelector('form').onsubmit = (event) => { event.preventDefault(); runAnalyse(); };
  $('[data-close]').addEventListener('click', () => el.remove());
  el.addEventListener('keydown', (e) => { if (e.key === 'Escape') el.remove(); });
  // opened from Create's "Review the joint labels" for an already-rigged upload: start at once
  if (prefill?.file) {
    drop.textContent = prefill.file.name;
    runAnalyse();
  }
}
