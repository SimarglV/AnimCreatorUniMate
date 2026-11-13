// Import a rig — a built-in example, an uploaded GLB, or a server path — and run UniMate
// motion on it. This is the non-humanoid path: no auto-rig, UniMate adapts (rig_preprocess)
// and animates any skeleton that already has one.

import { followJob, statusUrlFor, jobEnd } from './jobs.js';
import { closeSheet } from './pages.js';

const esc = (text) => String(text ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export async function openMotionImport({ stage, ctx, onResult }) {
  closeSheet(stage);
  const prompts = ctx.motionPrompts || [];
  let builtins = [];
  try {
    const answer = await (await fetch('/api/motion/builtins')).json();
    builtins = answer.builtins || [];
  } catch { /* the server will refuse the run if it matters */ }

  const el = document.createElement('div');
  el.className = 'sheet';
  el.innerHTML = `
    <form class="sheet-card motion-import" novalidate>
      <div class="sheet-top"><h2>Animate a <span>rig</span></h2><button type="button" class="ghost" data-close>Cancel</button></div>
      <p class="hint">UniMate animates any rigged skeleton — people, animals, machines. Pick a
        built-in example, upload a rigged GLB/glTF/FBX, or point at one on this machine.
        ${ctx.motionReady === false ? `<b>${esc(ctx.motionNote || 'UniMate is not set up.')}</b>` : ''}</p>
      <label class="field">Rig<select data-src>
        ${builtins.length ? builtins.map((b) => `<option value="${esc(b.name)}">${esc(b.label)} (built-in)</option>`).join('') : ''}
        <option value="upload">Upload a rigged GLB…</option>
        <option value="path">A file on this machine…</option>
      </select></label>
      <input type="file" data-upload accept=".glb,.gltf,.fbx" hidden>
      <input type="text" data-path placeholder="assets/examples/crab/Crab.glb" hidden>
      <label class="field">Motion prompt<span class="hint">Start with “An object”, name one motion.</span></label>
      <div class="moves" role="group" aria-label="Motion prompts">${prompts.map((p, i) => `<button type="button" class="chip" data-mprompt="${esc(p.text)}" aria-pressed="${i === 0}">${esc(p.label)}</button>`).join('')}</div>
      <textarea data-prompt rows="2" maxlength="400" placeholder="An object walks forward.">${esc(prompts[0]?.text || '')}</textarea>
      <details class="adv"><summary>Advanced</summary>
        <label class="field">Samples<select data-reps>${[1, 2, 3, 4].map((n) => `<option value="${n}">${n}${n === 1 ? ' sample' : ' samples — pick the best'}</option>`).join('')}</select></label>
        <label class="field">Prompt strength <output data-o="cfg">3.0</output><input type="range" data-cfg min="1" max="8" step="0.5" value="3"></label>
        <label class="check"><input type="checkbox" data-loop><span>Loop <span class="hint">crossfades the clip into itself.</span></span></label>
      </details>
      <p class="error" data-error hidden></p>
      <div class="row end"><button type="submit" class="primary">Animate</button></div>
      <div data-out class="motion-out" hidden></div>
    </form>`;
  stage.appendChild(el);

  const $ = (sel) => el.querySelector(sel);
  const src = $('[data-src]');
  const upload = $('[data-upload]');
  const path = $('[data-path]');
  const prompt = $('[data-prompt]');
  const out = $('[data-out]');

  const syncSource = () => {
    upload.hidden = src.value !== 'upload';
    path.hidden = src.value !== 'path';
  };
  src.onchange = syncSource;
  syncSource();

  el.querySelectorAll('[data-mprompt]').forEach((chip) => chip.onclick = () => {
    el.querySelectorAll('[data-mprompt]').forEach((c) => c.setAttribute('aria-pressed', String(c === chip)));
    prompt.value = chip.dataset.mprompt;
  });
  prompt.oninput = () => el.querySelectorAll('[data-mprompt]').forEach((c) => c.setAttribute('aria-pressed', 'false'));
  $('[data-cfg]').oninput = () => { $('[data-o="cfg"]').textContent = Number($('[data-cfg]').value).toFixed(1); };

  const fail = (message) => { const e = $('[data-error]'); e.textContent = message; e.hidden = false; };

  el.querySelector('form').onsubmit = async (event) => {
    event.preventDefault();
    if (ctx.motionReady === false) return fail(ctx.motionNote || 'UniMate is not set up.');
    const text = prompt.value.trim();
    if (!text) return fail('Write a motion prompt first.');
    const settings = { cfg_scale: Number($('[data-cfg]').value), repetitions: Number($('[data-reps]').value), loop: $('[data-loop]').checked };
    let body, kind;
    if (src.value === 'upload') {
      if (!upload.files[0]) return fail('Choose a GLB to upload.');
      const form = new FormData();
      form.append('asset', upload.files[0]);
      form.append('settings', JSON.stringify({ prompt: text, ...settings }));
      body = form;
    } else if (src.value === 'path') {
      if (!path.value.trim()) return fail('Give a path to a rigged GLB or an adapted rig folder.');
      body = JSON.stringify({ path: path.value.trim(), prompt: text, ...settings });
    } else {
      body = JSON.stringify({ builtin: src.value, prompt: text, ...settings });
    }
    out.hidden = false;
    out.innerHTML = '<div class="job"><div class="bigbar"><span></span></div><p class="job-msg">Starting…</p></div>';
    const bar = out.querySelector('.bigbar span'), msg = out.querySelector('.job-msg');
    let start;
    try {
      const response = await fetch('/api/motion/import', { method: 'POST',
        ...(typeof body === 'string' ? { headers: { 'Content-Type': 'application/json' }, body } : { body }) });
      start = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(start.error || `HTTP ${response.status}`);
    } catch (error) {
      out.innerHTML = `<p class="job-msg">${esc(error.message || 'Could not start.')}</p>`;
      return;
    }
    const job = followJob(statusUrlFor('motion', start), { interval: 1200, onUpdate: ({ event, percent }) => {
      msg.textContent = event.message || event.phase || 'Working…';
      if (percent != null) bar.style.width = `${percent}%`; else bar.classList.add('busy');
    } });
    const final = await job.done;
    if (final.status !== 'done') {
      out.innerHTML = `<p class="job-msg">${esc(jobEnd(final).why)}</p>`;
      return;
    }
    const done = final.last_event || {};
    const name = (done.path || '').split('/').pop() || 'motion';
    out.innerHTML = `<p class="job-msg">Done</p>`;
    onResult(done.result_url, name, done.path);
    el.querySelector('[data-close]')?.click();
  };

  $('[data-close]').addEventListener('click', () => el.remove());
  el.addEventListener('keydown', (e) => { if (e.key === 'Escape') el.remove(); });
}
