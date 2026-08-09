const $ = (s) => document.querySelector(s);
let current = null;

async function loadSessions() {
  const list = await (await fetch("/api/sessions")).json();
  $("#sessionList").innerHTML = list.map(s =>
    `<li data-id="${s.id}">${s.title}<span class="del" data-id="${s.id}">✕</span></li>`).join("");
  $("#sessionList").querySelectorAll("li").forEach(li =>
    li.onclick = (e) => { if (!e.target.classList.contains("del")) select(li.dataset.id); });
  $("#sessionList").querySelectorAll(".del").forEach(d =>
    d.onclick = async (e) => {
      e.stopPropagation();
      await fetch("/api/sessions/" + d.dataset.id, { method: "DELETE" });
      loadSessions();
    });
  $("#sessionList").querySelectorAll("li").forEach(li =>
    li.ondblclick = async () => {
      const title = prompt("重命名会话：", li.childNodes[0].textContent.trim());
      if (title && title.trim()) {
        await fetch("/api/sessions/" + li.dataset.id, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: title.trim() })
        });
        loadSessions();
      }
    });
}

async function select(id) {
  current = id;
  const msgs = await (await fetch(`/api/sessions/${id}/messages`)).json();
  $("#messages").innerHTML = msgs.map(m =>
    `<div class="msg ${m.role}">${m.content.replace(/\n/g, "<br>")}</div>`).join("");
  $("#chart").style.display = "none";
}

$("#newBtn").onclick = async () => {
  const s = await (await fetch("/api/sessions", { method: "POST" })).json();
  await loadSessions();
  select(s.id);
};

$("#form").onsubmit = async (e) => {
  e.preventDefault();
  if (!current) await ($("#newBtn").onclick());
  const text = $("#input").value.trim();
  if (!text) return;
  $("#input").value = "";
  $("#messages").insertAdjacentHTML("beforeend", `<div class="msg user">${text}</div>`);
  const bubble = document.createElement("div");
  bubble.className = "msg assistant";
  $("#messages").appendChild(bubble);
  let chart = null;
  const es = new EventSource("/api/chat/stream?" + new URLSearchParams({
    session_id: current, message: text
  }));
  es.addEventListener("start", (ev) => { bubble.textContent = ev.data + "\n"; });
  es.addEventListener("tool", (ev) => {
    const tc = JSON.parse(ev.data);
    const args = Object.entries(tc.args || {}).map(([k, v]) => `${k}=${v}`).join(", ");
    bubble.innerHTML += `<div class="tool-call">🔧 调用工具 <b>${tc.name}</b>(${args}) → ${tc.result_summary}</div>`;
  });
  es.addEventListener("chunk", (ev) => { bubble.innerHTML += ev.data.replace(/\n/g, "<br>") + "<br>"; });
  es.addEventListener("data", (ev) => {
    const d = JSON.parse(ev.data);
    chart = d.chart;
  });
  es.addEventListener("done", () => {
    es.close();
    if (!chart) { loadSessions(); return; }
    if (chart.type === "get_price_prediction") renderForecast(chart);
    else if (chart.data && chart.data.length) renderChart(chart.data, chart.type === "get_intraday");
    loadSessions();  // 刷新侧栏，使会话标题变为首条消息摘要
  });
  es.onerror = () => { es.close(); };
};

async function exportSession(fmt) {
  if (!current) return;
  const res = await (await fetch(`/api/sessions/${current}/export?fmt=${fmt}`)).json();
  const blob = new Blob([fmt === "json" ? JSON.stringify(res, null, 2) : res.markdown],
    { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `会话导出.${fmt === "json" ? "json" : "md"}`;
  a.click();
  URL.revokeObjectURL(a.href);
}
$("#exportMd").onclick = () => exportSession("markdown");
$("#exportJson").onclick = () => exportSession("json");

function renderChart(data, isIntraday) {
  $("#chart").style.display = "block";
  const chart = echarts.init($("#chart"));
  const xkey = isIntraday ? "time" : "date";
  chart.setOption({
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: data.map(d => d[xkey]) },
    yAxis: { scale: true },
    dataZoom: [{ type: "inside" }],
    series: [
      { type: "candlestick", name: isIntraday ? "分时" : "K线",
        data: data.map(d => [d.open, d.close, d.low, d.high]) },
      { type: "bar", name: "成交量", yAxisIndex: 0,
        data: data.map(d => d.volume) }
    ]
  });
}

function renderForecast(pred) {
  $("#chart").style.display = "block";
  const chart = echarts.init($("#chart"));
  const labels = ["当前", ...pred.forecasts.map(f => `+${f.horizon_days}日`)];
  const current = pred.current_price;
  const median = [current, ...pred.forecasts.map(f => f.median_price)];
  const low = [current, ...pred.forecasts.map(f => f.low_price)];
  const high = [current, ...pred.forecasts.map(f => f.high_price)];
  const bandDelta = high.map((v, i) => +(v - low[i]).toFixed(2));
  const markLine = [
    { yAxis: pred.support_level, name: "支撑位", lineStyle: { color: "#2f9e44" }, label: { formatter: "支撑 {c}" } },
    { yAxis: pred.resistance_level, name: "压力位", lineStyle: { color: "#e8590c" }, label: { formatter: "压力 {c}" } }
  ].filter(m => m.yAxis != null);
  chart.setOption({
    title: { text: `${pred.code} 价格预测 · ${pred.direction}`, left: "center", textStyle: { fontSize: 14 } },
    tooltip: { trigger: "axis" },
    legend: { data: ["置信区间", "中位价"], bottom: 0 },
    xAxis: { type: "category", data: labels },
    yAxis: { scale: true },
    series: [
      { type: "line", name: "置信区间下沿", stack: "band", data: low, lineStyle: { opacity: 0 }, symbol: "none", tooltip: { show: false } },
      { type: "line", name: "置信区间", stack: "band", data: bandDelta, lineStyle: { opacity: 0 }, areaStyle: { color: "rgba(56,132,255,0.25)" }, symbol: "none" },
      { type: "line", name: "中位价", data: median, lineStyle: { width: 2 }, symbolSize: 7, markLine: { symbol: "none", data: markLine } }
    ]
  });
}

loadSessions();
