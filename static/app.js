// Checklist item toggle (AJAX)
function toggleItem(boxEl) {
  const item = boxEl.closest('.checklist-item');
  const idx = parseInt(item.dataset.idx);
  const completionId = parseInt(item.dataset.completion);
  const checkNum = parseInt(item.dataset.checknum);
  const nowPassed = item.classList.contains('checked') ? 0 : 1;

  fetch(TOGGLE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ completion_id: completionId, item_idx: idx, passed: nowPassed })
  })
  .then(r => r.json())
  .then(data => {
    if (data.ok) {
      item.classList.toggle('checked', nowPassed === 1);
      boxEl.textContent = nowPassed ? '✓' : '';
      updateCount();
    }
  });
}

function updateCount() {
  const countEl = document.getElementById('checked-count');
  if (!countEl) return;
  const checked = document.querySelectorAll('.checklist-item.checked').length;
  countEl.textContent = checked;
}

// Confirm before quiz submit
const quizForm = document.getElementById('quiz-form');
if (quizForm) {
  quizForm.addEventListener('submit', function(e) {
    const inputs = quizForm.querySelectorAll('input[required], select[required]');
    let ok = true;
    inputs.forEach(el => { if (!el.value) ok = false; });
    if (!ok) { e.preventDefault(); alert('Please answer all questions before submitting.'); }
  });
}
