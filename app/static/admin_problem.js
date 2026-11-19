(function () {
  var pid = document.getElementById('tools').dataset.pid;
  var ex = JSON.parse(document.getElementById('examples').textContent);
  var rep = document.getElementById('report');
  function $(id) { return document.getElementById(id); }
  function post(url, body) {
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status)); return j; }); });
  }
  function show(text) { rep.hidden = false; rep.textContent = text; }
  function fail(e) { show('ERROR: ' + e.message); }
  function setValid(n) { if (n !== undefined && n !== null) $('valid').textContent = n; }

  // Manual-only: do not create dozens of empty fields until the admin requests them.
  function buildManualRows() {
    var field = $('manual-count');
    var count = Number(field.value);
    if (!Number.isInteger(count) || count < 20 || count > 100) {
      show('Testlar soni 20 dan 100 gacha butun son bo‘lishi kerak.'); field.focus(); return;
    }
    var host = $('manual-tests'); host.innerHTML = '';
    for (var i = 0; i < count; i++) {
      var card = document.createElement('section'); card.className = 'manual-test-card';
      card.innerHTML = '<h4>Test #' + (i + 1) + '</h4><div class="manual-test-grid"><label>Input<textarea class="code manual-input" rows="4" placeholder="Input qiymatlari" required></textarea></label><label>Expected output<textarea class="code manual-output" rows="4" placeholder="Kutilgan output" required></textarea></label></div><label class="chk"><input type="checkbox" class="manual-sample" ' + (i === 0 ? 'checked' : '') + '> Sample test (studentlarga ko‘rinadi)</label>';
      host.appendChild(card);
    }
    host.scrollIntoView({behavior:'smooth', block:'start'});
  }
  if ($('build-tests')) $('build-tests').onclick = buildManualRows;

  $('ref-example').onclick = function () { $('ref-lang').value = 'python3'; $('ref-src').value = ex.ref; };
  $('ref-save').onclick = function () {
    post('/admin/api/problems/' + pid + '/reference', { language: $('ref-lang').value, source: $('ref-src').value }).then(function (r) { show(r.message); }).catch(fail);
  };
  $('t-add').onclick = async function () {
    var inputs = Array.from(document.querySelectorAll('.manual-input'));
    var outputs = Array.from(document.querySelectorAll('.manual-output'));
    var samples = Array.from(document.querySelectorAll('.manual-sample'));
    if (!inputs.length) { show('Avval testlar sonini tanlang.'); return; }
    for (var i = 0; i < inputs.length; i++) {
      if (!inputs[i].value.trim() || !outputs[i].value.trim()) { show('Test #' + (i + 1) + ': Input va Output maydonlarini to‘ldiring.'); return; }
    }
    $('t-add').disabled = true; var added = 0, errors = [];
    for (var j = 0; j < inputs.length; j++) {
      show('Saqlanmoqda: ' + (j + 1) + '/' + inputs.length);
      try {
        var result = await post('/admin/api/problems/' + pid + '/tests', { input: inputs[j].value, expected: outputs[j].value, is_sample: samples[j].checked });
        if (result.ok) added++; else errors.push('Test #' + (j + 1) + ': ' + result.message);
      } catch (e) { errors.push('Test #' + (j + 1) + ': ' + e.message); }
    }
    show('Saqlangan testlar: ' + added + '/' + inputs.length + (errors.length ? '\n\nXatolar:\n' + errors.join('\n') : ''));
    $('t-add').disabled = false;
    if (added) setTimeout(function () { location.reload(); }, errors.length ? 2500 : 900);
  };
  $('reval').onclick = function () {
    show('Re-running the reference on every test...');
    post('/admin/api/problems/' + pid + '/revalidate').then(function (r) {
      var l = ['Checked: ' + r.checked, 'Invalid: ' + r.invalid.length, 'Total valid: ' + r.total_valid];
      r.invalid.forEach(function (i) { l.push(' - test #' + i.ordinal + ': ' + i.reason); });
      r.errors.forEach(function (e) { l.push('ERROR: ' + e); });
      show(l.join('\n')); setValid(r.total_valid);
    }).catch(fail);
  };
  document.querySelectorAll('.del-test').forEach(function (b) {
    b.onclick = function () {
      if (!confirm('Delete this test?')) return;
      post('/admin/api/tests/' + b.dataset.id + '/delete').then(function () { location.reload(); }).catch(fail);
    };
  });
  document.querySelectorAll('.view-test').forEach(function (b) {
    b.onclick = function () {
      fetch('/admin/api/tests/' + b.dataset.id).then(function (r) { return r.json(); }).then(function (t) {
        var d = $('detail'); d.hidden = false; d.textContent = 'INPUT:\n' + t.input + '\nEXPECTED:\n' + t.expected + (t.truncated ? '\n(truncated)' : '');
      });
    };
  });
})();
