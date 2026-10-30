// Presentation only. Trading, provider connections and settings remain in the original modules.
const root = document.documentElement;
const themeButton = document.getElementById('theme-toggle');
const icons = {
  dashboard: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  scanner: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5M8 13l2-4 3 2"/>',
  positions: '<path d="M4 20V10m6 10V4m6 16v-7m5 7H2"/>',
  orders: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 9h6M9 13h6M9 17h3M9 2h6"/>',
  journal: '<path d="M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-4-3H4V4Zm9 3a3 3 0 0 1 3-3h5v14h-4a4 4 0 0 0-4 3"/>',
  settings: '<path d="M12 3v3m0 12v3M3 12h3m12 0h3M6 6l2 2m8 8 2 2M6 18l2-2M16 8l2-2"/><circle cx="12" cy="12" r="5"/>',
  watchlist: '<path d="M5 5h14M5 12h14M5 19h14"/>'
};
const svg = path => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
for (const a of document.querySelectorAll('[data-nav]')) a.insertAdjacentHTML('afterbegin', svg(icons[a.dataset.nav]));
function showTheme() {
  const dark = root.dataset.theme === 'dark';
  themeButton.innerHTML = svg(dark ? '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>' : '<path d="M20 14a8 8 0 0 1-10-10 8 8 0 1 0 10 10Z"/>');
  themeButton.setAttribute('aria-label', `Switch to ${dark ? 'light' : 'dark'} theme`);
  themeButton.title = `Switch to ${dark ? 'light' : 'dark'} theme`;
  themeButton.setAttribute('aria-pressed', String(dark));
  document.querySelector('meta[name="theme-color"]').content = dark ? '#161c26' : '#3878ed';
}
showTheme();
themeButton.addEventListener('click', () => {
  root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem('indiantrader-theme', root.dataset.theme); } catch {}
  showTheme();
});
const view = document.getElementById('view');
function decorate() {
  const page = (location.hash.replace(/^#\/?/, '').split(/[/?]/)[0] || 'dashboard');
  document.body.dataset.page = page;
  const head = view.querySelector('.page-head');
  if (head && !head.querySelector('.eyebrow')) {
    const eyebrow = document.createElement('div');
    eyebrow.className = 'eyebrow';
    eyebrow.textContent = ({dashboard:'YOUR TRADING OVERVIEW',scanner:'DISCOVER YOUR NEXT SETUP',positions:'MANAGE YOUR EXPOSURE',orders:'YOUR TRADE DESK',journal:'TRACK. REFLECT. IMPROVE.',settings:'MAKE IT YOURS',stock:'NSE · EQUITY'})[page] || 'PAPER TRADING';
    head.prepend(eyebrow);
  }
  if (page === 'settings' && head && !view.querySelector('.settings-jumps')) {
    const sections = [...view.querySelectorAll('section.panel')];
    const nav = document.createElement('nav');
    nav.className = 'settings-jumps';
    nav.setAttribute('aria-label', 'Settings sections');
    for (const section of sections) {
      const title = section.querySelector('h2')?.textContent;
      if (!title) continue;
      const button = document.createElement('button'); button.type = 'button'; button.textContent = title;
      button.onclick = () => { section.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',block:'start'}); };
      nav.append(button);
    }
    head.after(nav);
  }
}
// Observe replaced screens without touching the original fields or their event handlers.
new MutationObserver(decorate).observe(view, {childList:true});
window.addEventListener('hashchange', decorate);
decorate();

// The session belongs to the signed-in user; mode balances are kept by the server.
async function signOut(){await fetch('/api/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});location.href='/start.html';}
document.getElementById('logout')?.addEventListener('click',signOut);
const badge=document.querySelector('.practice-badge');
fetch('/api/auth/status',{headers:sessionStorage.getItem('indiantrader-mode')?{'X-Trade-Mode':sessionStorage.getItem('indiantrader-mode')}:{}}).then(r=>r.json()).then(s=>{if(s.user){sessionStorage.setItem('indiantrader-mode',s.user.mode);if(badge)badge.textContent=s.user.mode==='demo'?'DEMO ACCOUNT':'PAPER ACCOUNT';}});
function accountLinks(){if(document.body.dataset.page!=='settings'||view.querySelector('.session-controls'))return;const box=document.createElement('div');box.className='session-controls panel';box.style.marginTop='20px';box.innerHTML='<div class="panel-body" style="display:flex;flex-wrap:wrap;gap:12px"><a class="btn" href="/start.html">Switch Demo / Paper Trading</a><button class="btn" type="button">Log out</button><a class="btn" href="/setup.html">Gmail setup (owner)</a></div>';box.querySelector('button').onclick=signOut;view.append(box);}
new MutationObserver(accountLinks).observe(view,{childList:true});accountLinks();
