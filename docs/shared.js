/* Shared utilities & design system helpers for Precios YPF */
(() => {
  const FUELS = {
    NS: ['Nafta Súper', 'Súper'],
    IN: ['Infinia', 'Infinia'],
    EURO: ['Euro Diésel', 'Euro'],
    D500: ['Diésel 500', 'D500']
  };
  const FUEL_SHORT = { NS: 'Súper', IN: 'Infinia', EURO: 'Euro Diésel', D500: 'Diésel 500' };
  const FUEL_FULL = { NS: 'Nafta Súper', IN: 'Infinia', EURO: 'Euro Diésel', D500: 'Diésel 500' };
  const FKEYS = ['NS', 'IN', 'EURO', 'D500'];
  const FKEYS_SALES = ['NS', 'IN', 'D500', 'EURO'];
  const FCOL = { NS: '#1747d6', IN: '#3b82f6', EURO: '#059669', D500: '#eab308' };
  const PAL = ['#1747d6', '#059669', '#f97316', '#dc2626', '#8b5cf6'];
  const RANGE = [
    ['30d', '30 días', '30 días'],
    ['3m', '3 meses', '3 meses'],
    ['6m', '6 meses', '6 meses'],
    ['1y', '1 año', '1 año'],
    ['ytd', 'YTD', 'año en curso']
  ];
  const MES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  const EXACT = new Set(['altura', 'exacta_csv_oficial', 'altura_osm', 'interseccion', 'poste_kilometrico', 'calle_csv_oficial', 'revisada']);

  const $ = s => document.querySelector(s);
  const $$ = s => document.querySelectorAll(s);

  const money = n => '$' + new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 }).format(n);
  const money2 = n => '$' + new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
  const moneyK = n => Math.abs(n) >= 1e6
    ? '$' + new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(n / 1e6) + ' M'
    : money(n);
  const fmtL = n => new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 }).format(n);
  const litK = n => Math.abs(n) >= 1e6
    ? new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(n / 1e6) + ' M L'
    : fmtL(n) + ' L';

  const pct = n => (n > 0 ? '+' : '') + n.toFixed(1).replace('.', ',') + '%';
  const pctF = n => (n * 100).toFixed(1).replace('.', ',') + '%';
  const f2 = d => String(d || '—').split('-').reverse().join('/');
  const mesLbl = p => {
    const [a, b] = String(p).split('-');
    return (MES[(+b) - 1] || '') + ' ' + String(a || '').slice(2);
  };

  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));

  const norm = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

  const DAY = 864e5;
  const T = d => Date.parse(d + 'T12:00:00');
  const iso = t => new Date(t).toISOString().slice(0, 10);

  const med = a => {
    if (!a || !a.length) return null;
    const s = [...a].sort((x, y) => x - y);
    const m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  };

  const km = (a, b, c, d) => {
    const r = Math.PI / 180;
    const x = Math.sin((c - a) * r / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin((d - b) * r / 2) ** 2;
    return 12742 * Math.asin(Math.sqrt(x));
  };

  const fmtDateLong = new Intl.DateTimeFormat('es-AR', {
    timeZone: 'America/Argentina/Buenos_Aires',
    dateStyle: 'long',
    timeStyle: 'short'
  });

  const fmtDateShort = new Intl.DateTimeFormat('es-AR', {
    timeZone: 'America/Argentina/Buenos_Aires',
    dateStyle: 'medium',
    timeStyle: 'short'
  });

  const YPF_LOGO = `<span class="ypf-logo" aria-hidden="true">
    <svg width="54" height="24" viewBox="0 0 108 48" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="108" height="48" rx="10" fill="#004B93"/>
      <text x="54" y="33.5" text-anchor="middle" fill="#FFFFFF" font-family="'Plus Jakarta Sans', 'Inter', Arial, sans-serif" font-weight="900" font-size="27" letter-spacing="1.5">YPF</text>
      <rect x="14" y="39" width="80" height="2.6" rx="1.3" fill="#38BDF8"/>
    </svg>
  </span>`;

  function renderTopbar(active, rightHtml = '') {
    const links = [
      ['index.html', 'Mapa', 'mapa'],
      ['argentina.html', 'Panorama', 'argentina'],
      ['ranking.html', 'Ranking', 'ranking']
    ];
    return `<header class="topbar">
      <div class="topbar-inner">
        <a class="brand" href="index.html" aria-label="Precios YPF">
          ${YPF_LOGO}
          <span>Precios</span>
        </a>
        <nav class="nav-pills" aria-label="Secciones">
          ${links.map(([href, label, id]) =>
            `<a href="${href}" class="${active === id ? 'active' : ''}">${label}</a>`
          ).join('')}
        </nav>
        <div class="topbar-sp"></div>
        ${rightHtml}
      </div>
    </header>`;
  }

  window.YPF = {
    FUELS, FUEL_SHORT, FUEL_FULL, FKEYS, FKEYS_SALES, FCOL, PAL, RANGE, MES, EXACT, YPF_LOGO,
    $, $$, money, money2, moneyK, fmtL, litK, pct, pctF, f2, mesLbl,
    esc, norm, DAY, T, iso, med, km, fmtDateLong, fmtDateShort, renderTopbar
  };
})();
