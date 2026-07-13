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
  const res = await (await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: current, message: text })
  })).json();
  $("#messages").insertAdjacentHTML("beforeend",
    `<div class="msg assistant">${res.reply.replace(/\n/g, "<br>")}</div>`);
  if (res.history && res.history.length) renderChart(res.history);
};

function renderChart(data) {
  $("#chart").style.display = "block";
  const chart = echarts.init($("#chart"));
  chart.setOption({
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: data.map(d => d.date) },
    yAxis: { scale: true },
    dataZoom: [{ type: "inside" }],
    series: [
      { type: "candlestick", name: "K线",
        data: data.map(d => [d.open, d.close, d.low, d.high]) },
      { type: "bar", name: "成交量", yAxisIndex: 0,
        data: data.map(d => d.volume) }
    ]
  });
}

loadSessions();
