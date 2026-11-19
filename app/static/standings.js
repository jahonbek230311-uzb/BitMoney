(function () {
  var root = document.getElementById('board'), info = document.getElementById('info');
  var cid = root.dataset.cid, me = root.dataset.me;
  function el(t, c, x) { var e = document.createElement(t); if (c) e.className = c; if (x !== undefined) e.textContent = x; return e; }
  function fmt(n) { return Math.abs(n - Math.round(n)) < 1e-9 ? String(Math.round(n)) : n.toFixed(2); }
  function cell(c, d) {
    var td = el('td', 'c');
    if (c.solved) {
      td.className = 'c solved';
      td.appendChild(el('b', null, d.scoring === 'points' ? fmt(c.points) : (c.wrong ? '+' + c.wrong : '+')));
    } else if (c.wrong) {
      td.className = 'c ' + (c.points > 0 ? 'part' : 'wrong');
      td.appendChild(el('b', null, c.points > 0 ? fmt(c.points) : '-' + c.wrong));
      if (c.points > 0) td.appendChild(el('small', null, '-' + c.wrong));
    }
    return td;
  }
  function render(d) {
    info.replaceChildren();
    if (d.hidden) { root.replaceChildren(el('div', 'card', 'The scoreboard is hidden until the contest finishes.')); return; }
    if (d.frozen) info.appendChild(el('div', 'flash', d.admin_view ? 'The board is frozen for students. You are seeing the live board.' : 'The scoreboard is frozen. Results shown are from before the freeze.'));
    var t = el('table', 'tbl standings'), h = el('tr');
    ['#', 'User'].forEach(function (x) { h.appendChild(el('th', null, x)); });
    d.problems.forEach(function (p) {
      var th = el('th'), a = el('a', null, p.letter);
      a.href = '/contests/' + cid + '/problems/' + p.id; a.title = p.title; th.appendChild(a);
      if (d.scoring === 'points') th.appendChild(el('small', null, p.points));
      h.appendChild(th);
    });
    ['Penalty', 'Tried', d.scoring === 'icpc' ? 'Solved' : 'Score'].forEach(function (x) { h.appendChild(el('th', null, x)); });
    t.appendChild(h);
    d.rows.forEach(function (r) {
      var tr = el('tr', r.user === me ? 'me' : '');
      tr.appendChild(el('td', 'c', r.rank)); tr.appendChild(el('td', null, r.user));
      r.cells.forEach(function (c) { tr.appendChild(cell(c, d)); });
      tr.appendChild(el('td', 'c', r.penalty)); tr.appendChild(el('td', 'c', r.tried));
      tr.appendChild(el('td', 'c', d.scoring === 'icpc' ? r.solved : fmt(r.score)));
      t.appendChild(tr);
    });
    if (!d.rows.length) { var tr = el('tr'); var td = el('td', 'muted', 'No participants yet.'); td.colSpan = 4 + d.problems.length; tr.appendChild(td); t.appendChild(tr); }
    var wrap = el('div', 'scroll'); wrap.appendChild(t); root.replaceChildren(wrap);
    document.getElementById('upd').textContent = 'updated ' + new Date().toLocaleTimeString() + ', refreshes every second';
  }
  function load() {
    fetch('/api/contests/' + cid + '/standings').then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.detail || 'error'); return j; }); })
      .then(render).catch(function (e) { info.replaceChildren(el('div', 'err', 'Could not load standings: ' + e.message)); });
  }
  load();
  var busy = false;
  function tick() { if (document.hidden || busy) return; busy = true; load(); setTimeout(function () { busy = false; }, 900); }
  setInterval(tick, 1000);
})();
