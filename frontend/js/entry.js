const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has('setup')) {
  sessionStorage.setItem('indiantrader-setup',fragment.get('setup'));
  history.replaceState(null,'',location.pathname);
}
const message=document.getElementById('entry-message');
let status={};
try {const r=await fetch('/api/auth/status'); if(!r.ok)throw Error(); status=await r.json();}
catch {message.textContent='Restart using Start IndianTrader.command to load the updated account service.';}
if(status.setup_required)message.innerHTML='First time here? <a href="/setup.html">Connect Gmail</a>, then create your account.';
if(status.user?.role!=='owner'&&!status.setup_required)document.querySelector('.setup-link').hidden=true;
for(const link of document.querySelectorAll('[data-mode]'))link.addEventListener('click',async event=>{
  localStorage.setItem('indiantrader-mode',link.dataset.mode);
  sessionStorage.setItem('indiantrader-mode',link.dataset.mode);
  if(!status.user)return;
  event.preventDefault();
  try {const r=await fetch('/api/auth/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:link.dataset.mode})});if(!r.ok)throw Error('Please log in again.');location.href='/index.html#/dashboard';}
  catch(e){message.textContent=e.message;}
});
