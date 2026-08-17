/* 两个页面共用的工具函数与图表主题。 */

const UP = '#26a69a', DOWN = '#ef5350', ACCENT = '#4c8dff';
const AXIS = '#2b3245', GRID_LINE = '#1c2131', LABEL = '#7d8598', FAINT = '#565e72';

// 静态部署：所有数据都是预生成的 JSON 文件，路径固定，见 app/export_static.py。
const dataUrl = {
  meta: () => 'data/meta.json',
  summary: () => 'data/summary.json',
  klines: (asset, period, value) => `data/klines/${asset}_${period}_${value}.json`,
  ratio: (base, quote, period) => `data/ratio/${base}_${quote}_${period}.json`,
  macro: (series, period) => `data/macro/${series}_${period}.json`,
  panel: () => 'data/panel_month.json',
};

async function get(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

const fmtUSD = (n) => {
  if (n == null || !isFinite(n)) return '—';
  const a = Math.abs(n);
  if (a >= 1e12) return '$' + (n / 1e12).toFixed(2) + ' 万亿';
  if (a >= 1e8)  return '$' + (n / 1e8).toFixed(2) + ' 亿';
  if (a >= 1e4)  return '$' + (n / 1e4).toFixed(2) + ' 万';
  return '$' + n.toFixed(2);
};

const fmtAxis = (n) => {
  const a = Math.abs(n);
  if (a >= 1e12) return (n / 1e12).toFixed(a >= 1e13 ? 0 : 1) + 'T';
  if (a >= 1e9)  return (n / 1e9).toFixed(a >= 1e10 ? 0 : 1) + 'B';
  if (a >= 1e6)  return (n / 1e6).toFixed(0) + 'M';
  if (a >= 1e3)  return (n / 1e3).toFixed(0) + 'K';
  return n.toFixed(a < 10 ? 1 : 0);
};

const fmtPct = (x) => x == null ? '—' : (x >= 0 ? '+' : '') + (x * 100).toFixed(2) + '%';

// 比值口径的数值是「倍数」（0.0546 = 5.46%），统一按百分比展示。
// 精度按量级走：黄金占 M2 已经超过 100%，而 BTC 占债务只有 3%，写死小数位会一头太糙一头太啰嗦。
const fmtRatio = (v) => {
  if (v == null || !isFinite(v)) return '—';
  const p = v * 100, a = Math.abs(p);
  return p.toFixed(a >= 100 ? 1 : a >= 1 ? 2 : 3) + '%';
};
const fmtRatioAxis = (v) => {
  const p = v * 100, a = Math.abs(p);
  return p.toFixed(a >= 10 ? 0 : a >= 1 ? 1 : 2) + '%';
};

// 宏观指标单位不统一：M2/债务是美元，利率是百分数，股指是点位
const fmtMacro = (v, unit) => {
  if (v == null || !isFinite(v)) return '—';
  if (unit === 'percent') return v.toFixed(2) + '%';
  if (unit === 'index') return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return fmtUSD(v);
};
const fmtMacroAxis = (v, unit) => {
  if (unit === 'percent') return v.toFixed(1) + '%';
  if (unit === 'index') return fmtAxis(v);
  return fmtAxis(v);
};

const labelOf = (t, p) => {
  if (p === 'year') return t.slice(0, 4);
  if (p === 'quarter') return t.slice(0, 4) + ' Q' + (Math.floor(+t.slice(5, 7) / 3) + 1);
  if (p === 'month') return t.slice(0, 7);
  return t;
};

function zoomCfg(startPct, axes) {
  return [
    { type: 'inside', xAxisIndex: axes, start: startPct, end: 100 },
    { type: 'slider', xAxisIndex: axes, start: startPct, end: 100, bottom: 8, height: 20,
      borderColor: AXIS, fillerColor: 'rgba(76,141,255,.12)',
      handleStyle: { color: ACCENT }, textStyle: { color: FAINT, fontSize: 10 },
      dataBackground: { lineStyle: { color: AXIS }, areaStyle: { color: '#1a1f2e' } } },
  ];
}

const tooltipBase = {
  trigger: 'axis', axisPointer: { type: 'cross' },
  backgroundColor: 'rgba(19,23,34,.96)', borderColor: AXIS, borderWidth: 1,
  textStyle: { color: '#d6dae5', fontSize: 12 },
};

const baseOption = () => ({
  animation: false,
  backgroundColor: 'transparent',
  textStyle: { color: '#d6dae5', fontFamily: 'inherit' },
  legend: { top: 6, left: 12, textStyle: { color: LABEL, fontSize: 12 },
    itemWidth: 14, itemHeight: 9, inactiveColor: '#3a4055' },
  axisPointer: { link: [{ xAxisIndex: 'all' }], label: { backgroundColor: AXIS } },
});

function showLoading(chart) {
  chart.showLoading({ text: '', maskColor: 'rgba(11,14,20,.6)', spinnerRadius: 12,
    color: ACCENT, textColor: LABEL });
}

/** 高亮当前页导航项。放在 common.js 里，两个页面的 nav 标记就能保持一致。 */
function markNav() {
  const here = location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav a').forEach(a => {
    a.classList.toggle('on', a.getAttribute('href') === here);
  });
}
