(function () {
  var box = document.getElementById('gboard'), upd = document.getElementById('upd');
  function load() {
    fetch(box.dataset.url, { cache: 'no-store', credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) { box.innerHTML = html; upd.textContent = 'Updated ' + new Date().toLocaleTimeString() + '.'; })
      .catch(function () { upd.textContent = 'Could not refresh.'; });
  }
  setInterval(function () { if (!document.hidden) load(); }, 10000);
})();
