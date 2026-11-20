// Keep the station's background click handler from moving focus off the picker.
document.getElementById('sample-kit').addEventListener('click', event => event.stopPropagation());

document.getElementById('try-badge').addEventListener('click', () => {
  const input = document.getElementById('scan-code');
  if (input.disabled) return;
  input.value = document.getElementById('sample-badge').value;
  input.form.requestSubmit();
});
