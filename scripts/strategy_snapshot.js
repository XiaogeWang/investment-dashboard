/*
 * 导出 Strategy 官网的 BTC 买卖账本和可转债明细，保存为 snapshots/strategy.json。
 *
 * 为什么要手动：这两份数据只在 www.strategy.com 的页面里，没有公开 API，
 * 而 www.strategy.com 对非浏览器请求返回 403，CI 抓不到。快照之后的买卖会由
 * app/strategy.py 按每日持币变化自动补上（价格是估算），所以不必每周都刷新，
 * 页面提示「快照已过期」或可转债总额对不上时再刷新即可。
 *
 * 用法：浏览器打开 https://www.strategy.com/ledger ，开发者工具 Console 里粘贴整段运行，
 * 会下载 strategy.json，放到项目的 snapshots/ 目录覆盖旧文件，然后跑一次 export_static。
 */
(async () => {
  const build = window.__NEXT_DATA__.buildId;
  const page = (p) => fetch(`/_next/data/${build}/en/${p}.json`).then(r => r.json()).then(j => j.pageProps);
  const [ledger, debt] = await Promise.all([page('ledger'), page('debt')]);

  const transactions = ledger.bitcoinData
    .map(x => ({
      date: x.date_of_purchase,
      title: x.title,
      btc: x.count,                                  // 买为正，卖为负
      price: x.purchase_price,                       // 这一笔的成交均价，美元/枚
      amount_musd: x.total_purchase_price / 1e6,     // 这一笔的金额，百万美元（卖出为负）
      avg_cost: x.average_price,                     // 这一笔之后的累计平均成本，美元/枚
      total_cost_musd: x.total_acquisition_cost,     // 这一笔之后的累计成本，百万美元
      holdings: x.btc_holdings,
      sale: !!x.sale,
      filing: x.sec?.url || null,
    }))
    .sort((a, b) => a.date.localeCompare(b.date) || a.holdings - b.holdings);

  const converts = debt.convertData
    .map(c => ({
      name: c.title,
      issue_date: c.issue_date,
      maturity_date: c.maturity_date,
      put_date: c.put_date,                          // 持有人可要求按面值现金赎回的日期
      call_date: c.earliest_call_date,               // 公司最早可赎回日期
      notional_musd: c.notional / 1e6,
      coupon: c.coupon,
      strike: c.strike_price,                        // 转股价
    }))
    .sort((a, b) => a.put_date.localeCompare(b.put_date));

  const out = { exported_at: new Date().toISOString().slice(0, 10), source: 'www.strategy.com/ledger, /debt', transactions, converts };
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], { type: 'application/json' }));
  a.download = 'strategy.json';
  a.click();
  console.log(`导出 ${transactions.length} 笔交易、${converts.length} 笔可转债`);
})();
