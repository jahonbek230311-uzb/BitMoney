(function () {
  var editor = document.getElementById('editor');
  var pid = parseInt(editor.dataset.pid, 10);
  var out = document.getElementById('out');
  var langSel = document.getElementById('lang');
  var STARTER = {
    python3: "# Python 3\nimport sys\n\ndef main():\n    data = sys.stdin.read().split()\n    # write your solution here\n\nmain()\n",
    cpp17: "#include <bits/stdc++.h>\nusing namespace std;\nint main(){ ios::sync_with_stdio(false); cin.tie(nullptr);\n    // write your solution here\n    return 0;\n}\n",
    c: "#include <stdio.h>\nint main(void) {\n    // write your solution here\n    return 0;\n}\n",
    java17: "import java.util.*;\npublic class Main { public static void main(String[] args) {\n    Scanner sc = new Scanner(System.in);\n    // write your solution here\n} }\n",
    javascript: "const fs = require('fs');\nconst input = fs.readFileSync(0, 'utf8').trim();\n// write your solution here\n",
    go: "package main\nimport \"fmt\"\nfunc main() {\n    // write your solution here\n    fmt.Println()\n}\n",
    rust: "use std::io::{self, Read};\nfn main() {\n    let mut input = String::new(); io::stdin().read_to_string(&mut input).unwrap();\n    // write your solution here\n}\n",
    ruby: "input = STDIN.read.split\n# write your solution here\n",
    php: "<?php\n$input = trim(stream_get_contents(STDIN));\n// write your solution here\n"
  };
  var MLANG = { python3: 'python', cpp17: 'cpp', c: 'c', java17: 'java', javascript: 'javascript', go: 'go', rust: 'rust', ruby: 'ruby', php: 'php' };
  var saved = {}, current = langSel.value;
  try { var k = 'code:' + pid + ':'; Object.keys(STARTER).forEach(function (lang) { saved[lang] = localStorage.getItem(k + lang); }); } catch (e) {}

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
  function say(node) { out.replaceChildren(node); }
  function note(text, cls) { say(el('div', cls || 'muted', text)); }

  // Plain textarea editor: all assets are served locally, so coding works without internet.
  editor.value = saved[current] || STARTER[current];
  editor.addEventListener('input', persist);
  function persist() { try { localStorage.setItem('code:' + pid + ':' + current, editor.value); } catch (e) {} }
  langSel.addEventListener('change', function () {
    persist(); current = langSel.value;
    var v = null; try { v = localStorage.getItem('code:' + pid + ':' + current); } catch (e) {}
    editor.value = v || STARTER[current];
  });

  function post(url, body) {
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status)); return j; }); });
  }
  var cidRaw = document.getElementById('editor').dataset.cid;
  function payload() { return { problem_id: pid, language: current, code: editor.value, contest_id: cidRaw ? parseInt(cidRaw, 10) : null }; }
  function busy(b) { document.getElementById('run').disabled = b; document.getElementById('submit').disabled = b; }

  document.getElementById('run').addEventListener('click', function () {
    busy(true); note('Running on sample tests...');
    post('/api/run', payload()).then(function (res) {
      var box = el('div');
      box.appendChild(el('p', 'v v-' + (res.verdict), 'Result: ' + res.verdict));
      if (res.compile_log) box.appendChild(el('pre', 'log', res.compile_log));
      res.tests.forEach(function (t, i) {
        box.appendChild(el('h4', 'v v-' + t.verdict, 'Sample ' + (i + 1) + ': ' + t.verdict + ' (' + t.time_ms + ' ms)' + (t.message ? ' - ' + t.message : '')));
        if (t.verdict !== 'AC') {
          box.appendChild(el('b', null, 'Your output')); box.appendChild(el('pre', null, t.output));
          box.appendChild(el('b', null, 'Expected')); box.appendChild(el('pre', null, t.expected));
          if (t.stderr) { box.appendChild(el('b', null, 'stderr')); box.appendChild(el('pre', 'log', t.stderr)); }
        }
      });
      say(box);
    }).catch(function (e) { note(e.message, 'err'); }).finally(function () { busy(false); });
  });

  document.getElementById('submit').addEventListener('click', function () {
    busy(true); note('Submitting...');
    post('/api/submit', payload()).then(function (r) { poll(r.id); }).catch(function (e) { note(e.message, 'err'); busy(false); });
  });
  function poll(id) {
    fetch('/api/submissions/' + id).then(function (r) { return r.json(); }).then(function (s) {
      if (s.verdict === 'PENDING' || s.verdict === 'JUDGING') { note('Submission #' + id + ': ' + s.verdict + '...'); setTimeout(function () { poll(id); }, 1000); return; }
      var box = el('div');
      box.appendChild(el('p', 'v v-' + s.verdict, 'Verdict: ' + s.verdict + ' (' + s.passed + '/' + s.total + ' tests, ' + s.time_ms + ' ms, ' + Math.round(s.memory_kb / 1024) + ' MB)'));
      if (s.compile_log) box.appendChild(el('pre', 'log', s.compile_log));
      var a = el('a', null, 'Open submission #' + id); a.href = '/submissions/' + id; box.appendChild(a);
      say(box); busy(false);
    }).catch(function (e) { note(e.message, 'err'); busy(false); });
  }
})();
