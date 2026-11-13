// Import & Adaptation: bring your own rig, review its joint labels and facing, then build
// the asset UniMate animates. The port of UniMate's own workflow, in the studio.

import { followJob, statusUrlFor, jobEnd } from './jobs.js';
import { closeSheet } from './pages.js';
import { openMotionImport } from './motion.js';

const esc = (text) => String(text ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function openRigImport({ stage, ctx, onResult }) {
  closeSheet(stage);
  const el = document.createElement('div');
  el.className = 'sheet';
  el.innerHTML = `
    <form class="sheet-card rig-import" novalidate>
      <div class="sheet-top"><h2>Import a <span>rig</span></h2><button type="button" class="ghost" data-close>Cancel</button></div>
      <p class="hint">Bring a rigged GLB / glTF / FBX. UniMate labels its joints, you check and
        fix them, then it builds the asset — after which Animate a rig can move it.
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

  let analysed = null;   // { directory, annotation, source }

  const runAnalyse = async () => {
    const file = upload.files[0];
    const pathValue = path.value.trim();
    if (!file && !pathValue) return fail('Choose a GLB to upload, or give a path.');
    let body;
    if (file) {
      const form = new FormData();
      form.append('asset', file);
      form.append('settings', JSON.stringify({ name: name.value.trim(), profile: profile.value,
        annotate: 'rule', rest_rotation: '', save_clips: clips.checked }));
      body = form;
    } else {
      body = JSON.stringify({ path: pathValue, name: name.value.trim(), profile: profile.value,
        annotate: 'rule', rest_rotation: '', save_clips: clips.checked });
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
}
