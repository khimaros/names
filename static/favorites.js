/* localStorage-based favorites */

function getFavs() {
  return JSON.parse(localStorage.getItem('favorites') || '[]');
}

function setFavs(favs) {
  localStorage.setItem('favorites', JSON.stringify(favs));
}

function toggleFav(id) {
  var favs = getFavs();
  var idx = favs.indexOf(id);
  if (idx === -1) {
    favs.push(id);
  } else {
    favs.splice(idx, 1);
  }
  setFavs(favs);
  return idx === -1;
}

function initFavButtons() {
  var favs = getFavs();
  document.querySelectorAll('.fav-btn').forEach(function(btn) {
    var id = parseInt(btn.dataset.id);
    if (favs.indexOf(id) !== -1) {
      btn.textContent = '★';
      btn.classList.add('active');
    } else {
      btn.textContent = '☆';
      btn.classList.remove('active');
    }
    btn.onclick = function() {
      var nowFav = toggleFav(id);
      btn.textContent = nowFav ? '★' : '☆';
      btn.classList.toggle('active', nowFav);
      applyFavFilter();
    };
  });
}

/* hide non-favorited rows when the favorites checkbox is checked */
function applyFavFilter() {
  var cb = document.getElementById('fav-only-cb');
  if (!cb) return;
  var favs = getFavs();
  var show = !cb.checked;
  document.querySelectorAll('tr[data-id]').forEach(function(tr) {
    var id = parseInt(tr.dataset.id);
    tr.style.display = (show || favs.indexOf(id) !== -1) ? '' : 'none';
  });
  /* update visible count */
  var countEl = document.getElementById('word-count');
  if (countEl) {
    var visible = document.querySelectorAll('tr[data-id]:not([style*="display: none"])').length;
    countEl.textContent = '(' + visible + ')';
  }
}

document.addEventListener('DOMContentLoaded', function() {
  initFavButtons();
  restoreSort();
  var cb = document.getElementById('fav-only-cb');
  if (cb) {
    cb.addEventListener('change', applyFavFilter);
  }
});
