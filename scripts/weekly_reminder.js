// 定投日提醒：算出这次该投多少、买哪个，生成一条 GitHub Issue 的标题和正文。
// 纳指100（QQQ + TQQQ）和标普500（VOO + UPRO）两个计划合并成一封。
// 被 .github/workflows/weekly-reminder.yml 调用；也能单独跑：node scripts/weekly_reminder.js
const fs = require("fs");
const path = require("path");
const DCA = require("../docs/strategy.js");

const DATA = path.join(__dirname, "..", "docs", "data.json");
const DATA_SP = path.join(__dirname, "..", "docs", "data-sp500.json");

// 美东时间的今天（工作流里 GitHub 的时钟是 UTC）
function todayInNewYork(now) {
  const d = now || new Date();
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
}

// 仓库名就是 <用户名>.github.io 时，网站在根目录；否则在 /<仓库名>/ 下
function siteUrl(owner, repo) {
  if (String(repo).toLowerCase() === (String(owner) + ".github.io").toLowerCase()) return `https://${repo}/`;
  return `https://${owner}.github.io/${repo}/`;
}

function fmtMoney(v) {
  return "$" + (v < 1000 ? v.toFixed(2) : Math.round(v).toLocaleString("en-US"));
}
function fmtPct(v, d) {
  return (v < 0 ? "−" : "") + Math.abs(v).toFixed(d == null ? 1 : d) + "%";
}

// 今天发不发：周末不发；每周定投只在定投日发（手动测试除外）
function dayCheck(cfg, opts) {
  const today = opts.today || todayInNewYork();
  const wd = DCA.weekdayOf(DCA.dayNumber(today));
  if (!opts.force && (wd < 1 || wd > 5)) return { skip: true, reason: "周末不投" };
  if (!opts.force && cfg.frequency !== "daily" && wd !== cfg.investWeekday) {
    return { skip: true, reason: "今天不是定投日" };
  }
  return { skip: false, today, wd };
}

// 一个计划的那一段：标题里的一句 + 正文。传了 h（合并成一封时）会在大标题前写上是哪个计划
function planSection(data, opts, h) {
  const cfg = DCA.withDefaults(opts.config || {});
  const series = DCA.prepare(data);
  if (!series.n) return null;
  const N = series.names, BASE = N.base, LEV = N.lev;
  const H2 = h || "##", H3 = H2 + "#";

  const dd = DCA.drawdowns(series, cfg.basis).dd;
  const tl = DCA.trendLines(series, cfg.maWindow);
  const i = series.n - 1; // 用最后一个交易日的收盘价
  const r = DCA.decide(cfg, dd, tl.dev, tl.ok, i);
  const amount = cfg.baseAmount * r.multiplier;
  const role = r.buyTqqq ? "TQQQ" : "QQQ";
  const asset = r.buyTqqq ? LEV : BASE;
  const toT = r.buyTqqq ? amount * cfg.flowShare / 100 : 0;

  const sellNow = DCA.sellTargetFor(cfg, dd, tl, i) !== null && cfg.sellMode !== "none";
  // 标题里这个计划的那一句
  let brief = `投 ${fmtMoney(amount)} 买 ${asset}（×${r.multiplier}）`;
  if (sellNow) brief += ` ⚠️ 该减 ${LEV}`;

  const lines = [];
  lines.push(`${H2} ${h ? N.index + "：" : ""}这次投 ${fmtMoney(amount)}，买 **${asset}**`);
  lines.push("");
  lines.push(`- 基础金额 ${fmtMoney(cfg.baseAmount)} × **${r.multiplier}** 倍`);
  if (r.buyTqqq && cfg.flowShare < 100) {
    lines.push(`- 其中 ${fmtMoney(toT)} 买 ${LEV}，剩下 ${fmtMoney(amount - toT)} 买 ${BASE}`);
  }
  lines.push(`- 依据 ${series.dates[i]} 收盘：${BASE} ${fmtMoney(series.close[i])}，${LEV} ${fmtMoney(series.t[i])}`);
  lines.push(`- 离${cfg.basis === "ath" ? "历史" : "近一年"}最高点跌了 **${fmtPct(dd[i])}**`);
  if (tl.ok[i]) {
    // 均线是按复权价算的，换算成和收盘价同一个尺度再显示
    const maPx = tl.ma[i] * (series.close[i] / series.adj[i]);
    lines.push(`- ${cfg.maWindow} 日均线 ${fmtMoney(maPx)}，现价比它` +
      (tl.dev[i] < 0 ? `低 ${fmtPct(-tl.dev[i])}（下跌趋势）` : `高 ${fmtPct(tl.dev[i])}`));
  }
  // 离「买 TQQQ」还差多少 / 要不要卖
  const st = DCA.currentStatus(series, cfg, null, { dd: dd, tl: tl });
  lines.push("");
  lines.push(`${H3} 买 ${LEV} 的两个条件`);
  lines.push(`- ${st.gap.belowMA ? "✅" : "⬜️"} 跌破 ${cfg.maWindow} 日均线：` +
    (st.gap.maGap == null ? "均线数据还不够"
      : st.gap.belowMA ? `已经在均线下方 ${fmtPct(-st.gap.maGap)}`
      : `现在比均线高 ${fmtPct(st.gap.maGap)}，还要再跌这么多才到`));
  lines.push(`- ${st.gap.deepEnough ? "✅" : "⬜️"} 离${cfg.basis === "ath" ? "历史" : "近一年"}最高点跌 ≥ ${cfg.dipThreshold}%：` +
    (st.gap.deepEnough ? `已经跌了 ${fmtPct(st.gap.ddNow)}`
      : `现在跌了 ${fmtPct(st.gap.ddNow)}，还差 ${fmtPct(st.gap.ddGap)}`));
  lines.push("");
  lines.push(`${H3} 要不要卖 ${LEV}`);
  if (cfg.sellMode === "none") {
    lines.push(`你把规则设成了「完全不卖」，连占比上限也不管。${LEV} 会一直累积，风险自负。`);
  } else if (st.sell.triggered) {
    lines.push(`**该减 ${LEV} 了。** ${nm(st.sell.note)}`);
    lines.push("具体卖几股要按你自己的持仓算——打开网站，在「我的持仓」填上股数，提醒区会直接给出数字。");
  } else {
    lines.push(`暂时不用卖。${nm(st.sell.note)}`);
    lines.push(`（当前规则：${DCA.SELL_NAMES[cfg.sellMode]}）`);
  }

  lines.push("");
  if (r.buyTqqq) {
    lines.push(`> 回撤已经到了 ${cfg.dipThreshold}% 的门槛，按规则这次买 ${LEV}。`);
    lines.push(`> 买完记得看一眼 ${LEV} 占组合的比例，超过 ${cfg.tqqqCap}% 就把超出的部分换回 ${BASE}。`);
  } else if (tl.ok[i] && tl.dev[i] < 0) {
    lines.push(`> 虽然跌破了 200 日均线，但还没跌到 ${cfg.dipThreshold}%，这次仍然买 ${BASE}。`);
  } else {
    lines.push(`> 不是大跌，这次买 ${BASE}。`);
  }
  if (cfg.sellOnRecover && tl.ok[i] && tl.dev[i] >= 0) {
    lines.push(`> 你开了「涨回均线就换回 ${BASE}」：现在在均线上方，手里的 ${LEV} 该换成 ${BASE}。`);
  }
  return {
    lines, brief, sellNow, cfg, names: N,
    amount, multiplier: r.multiplier, asset, role, state: r.state, basedOn: series.dates[i],
  };

  // strategy.js 里的说明文字写的是 QQQ / TQQQ，换成这个计划的代码
  function nm(t) { return String(t || "").replace(/TQQQ/g, LEV).replace(/QQQ/g, BASE); }
}

function footer(lines, cfg, opts) {
  lines.push("");
  lines.push(`美股开盘：北京时间 21:30（夏令时）/ 22:30（冬令时）。`);
  if (opts.owner && opts.repo) {
    lines.push("");
    lines.push(`网站：${siteUrl(opts.owner, opts.repo)}`);
  }
  if (opts.owner) {
    // @ 一下仓库主人：提醒是机器人发的，@ 了才一定会收到邮件通知
    lines.push("");
    lines.push(`@${opts.owner}`);
  }
  lines.push("");
  lines.push(`<sub>提醒按仓库里的默认基础金额 ${fmtMoney(cfg.baseAmount)} 算。你自己的金额只存在浏览器里，按上面的倍数乘一下就行。这不是投资建议。</sub>`);
  return lines;
}

function titleDate(today, wd, force) {
  const dateCn = today.slice(5, 7).replace(/^0/, "") + "月" + today.slice(8, 10).replace(/^0/, "") + "日";
  return (force ? "【测试】" : "") + `${dateCn}（${DCA.WEEKDAY_CN[wd]}）：`; // 【测试】= 手动点 Run workflow 发的
}

// 只发一个计划。data: 原始 data.json；opts: { today, owner, repo, config, force }
function buildReminder(data, opts) {
  opts = opts || {};
  const cfg = DCA.withDefaults(opts.config || {});
  if (!DCA.prepare(data).n) return { skip: true, reason: "没有行情数据" };
  const day = dayCheck(cfg, opts);
  if (day.skip) return day;
  const sec = planSection(data, opts);
  const title = titleDate(day.today, day.wd, opts.force) + sec.brief;
  return {
    skip: false, title, body: footer(sec.lines, cfg, opts).join("\n"),
    amount: sec.amount, multiplier: sec.multiplier, asset: sec.asset, state: sec.state, basedOn: sec.basedOn,
  };
}

// 两个计划合并成一封：datas = [纳指 data, 标普 data]（标普那份拿不到时传 null）
function buildCombined(datas, opts) {
  opts = opts || {};
  const cfg = DCA.withDefaults(opts.config || {});
  const secs = [], missing = [];
  datas.forEach(function (d) {
    const s = d && DCA.prepare(d).n ? planSection(d, opts, "##") : null;
    if (s) secs.push(s); else missing.push(d && d.names ? d.names.index : null);
  });
  if (!secs.length) return { skip: true, reason: "没有行情数据" };
  const day = dayCheck(cfg, opts);
  if (day.skip) return day;
  const title = titleDate(day.today, day.wd, opts.force) +
    secs.map(function (s) { return s.names.short + s.brief; }).join(" · ");
  const lines = [];
  secs.forEach(function (s, k) {
    if (k) { lines.push(""); lines.push("---"); lines.push(""); }
    s.lines.forEach(function (l) { lines.push(l); });
  });
  if (secs.length < datas.length) {
    lines.push("");
    lines.push("> 标普500 的行情这次没拿到，这封只写了纳指100。打开网站切到标普500 能看到最近一次的结果。");
  }
  return {
    skip: false, title, body: footer(lines, cfg, opts).join("\n"),
    plans: secs.map(function (s) { return { plan: s.names.index, amount: s.amount, multiplier: s.multiplier, asset: s.asset, basedOn: s.basedOn }; }),
  };
}

if (require.main === module) {
  main().catch(function (e) { console.error(e); process.exit(1); });
}

// 标普那份：工作流只下载了 data.json，这里自己去网站上取 data-sp500.json；拿不到就只发纳指
async function loadSp500(owner, repo) {
  try { return JSON.parse(fs.readFileSync(DATA_SP, "utf8")); } catch (e) { /* 本地没有就去网站上取 */ }
  if (!owner || !repo || typeof fetch !== "function") return null;
  const url = siteUrl(owner, repo) + "data-sp500.json";
  for (let k = 0; k < 3; k++) {
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (r.ok) return await r.json();
    } catch (e) { /* 再试 */ }
    await new Promise(function (res) { setTimeout(res, 5000); });
  }
  console.log("::warning::标普500 数据下载不到：" + url);
  return null;
}

async function main() {
  const owner = process.env.GITHUB_REPOSITORY_OWNER;
  const repo = (process.env.GITHUB_REPOSITORY || "/").split("/")[1];
  const data = JSON.parse(fs.readFileSync(DATA, "utf8"));
  const sp = await loadSp500(owner, repo);
  const out = buildCombined([data, sp], { owner, repo, force: process.argv.includes("--force") });
  if (out.skip) {
    console.log("skip: " + out.reason);
    if (process.env.GITHUB_OUTPUT) fs.appendFileSync(process.env.GITHUB_OUTPUT, "skip=true\n");
  } else {
    console.log(out.title);
    console.log("");
    console.log(out.body);
    var bodyPath = path.join(process.env.RUNNER_TEMP || require("os").tmpdir(), "issue-body.md");
    fs.writeFileSync(bodyPath, out.body);
    if (process.env.GITHUB_OUTPUT) {
      fs.appendFileSync(process.env.GITHUB_OUTPUT,
        "skip=false\ntitle=" + out.title.replace(/\r?\n/g, " ") + "\nbody_path=" + bodyPath + "\n");
    }
  }
}

module.exports = { buildReminder, buildCombined, todayInNewYork, siteUrl };
