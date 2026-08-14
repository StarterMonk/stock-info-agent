/* ============================================================
   Stock Agent v9 — Vue3 应用（CDN 零构建）
   多智能体对话（SSE）· 分类回答 · 图表 · 异常处理
   ============================================================ */
const { createApp, nextTick } = Vue;

const CAT_HEAD = {
  quote:    { label: "行情", icon: "📊" },
  finance:  { label: "财务", icon: "💰" },
  forecast: { label: "预测", icon: "🔮" },
  analysis: { label: "分析", icon: "🧮" },
  info:     { label: "概况", icon: "🏢" },
  answer:   { label: "回答", icon: "💬" },
};
const TOOL_ICON = {
  get_profile: "🏢", get_history: "📜", get_intraday: "⏱️", get_financials: "💰",
  get_dividend: "🧧", get_key_metrics: "📐", get_forecast: "🎯",
  get_price_prediction: "🔮", get_technical_indicators: "🧮",
  get_capital_flow: "💸", get_indicators: "📊", search_stocks: "🔍",
};
const AGENT_ICON = { A: "📡", B: "📊", C: "🧮" };
const AGENT_NAME = { A: "数据获取", B: "图表生成", C: "数据处理" };

const api = async (path, body, method) => {
  const m = method || (body ? "POST" : "GET");
  const opt = body
    ? { method: m, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : { method: m };
  const resp = await fetch(path, opt);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
};
const extractCode = (text) => { const m = String(text || "").match(/\d{6}/); return m ? m[0] : ""; };

createApp({
  data() {
    return {
      sessions: [], currentId: null, messages: [],
      input: "", thinking: false, online: false, llmStatus: "checking", llmError: "",
      renamingId: null, renamingValue: "",
      activeEs: null,
      algorithms: [],
      picker: { show: false, code: "", algorithm: "" },
      running: false,
      // v9: 多智能体状态
      agentProgress: { A: false, B: false, C: false },
      lastChart: null,
      showChartDock: false,
      // v9: 异常处理
      anomalyModal: { show: false, anomalies: [], question: "" },
      anomalyResolutions: {},
      // v9: 图表 dock
      dockWidth: 420,
      dockDragging: false,
    };
  },
  methods: {
    /* ================= 会话 ================= */
    async loadSessions() {
      try { this.sessions = await api("/api/sessions"); } catch (e) { this.sessions = []; }
    },
    async newSession() {
      const s = await api("/api/sessions", {}).catch(() => null);
      if (!s) return;
      await this.loadSessions();
      await this.selectSession(s.id);
    },
    async selectSession(id) {
      if (this.activeEs) { try { this.activeEs.close(); } catch (_) {} this.activeEs = null; this.thinking = false; }
      this.currentId = id;
      this.messages = [];
      try {
        const msgs = await api(`/api/sessions/${id}/messages`);
        this.messages = msgs.map((m, i) => ({
          id: `${id}-${m.created_at}-${i}`, role: m.role, text: m.content,
          chips: [], cats: [], analysis: null, charts: [],
        }));
      } catch (e) { this.messages = []; }
      this.scrollBottom();
    },
    startRename(s) {
      this.renamingId = s.id;
      this.renamingValue = s.title;
      this.$nextTick(() => {
        const inp = document.querySelector(".session-item.active .rename-input");
        if (inp) { inp.focus(); inp.select(); }
      });
    },
    async confirmRename(s) {
      const title = this.renamingValue.trim();
      this.renamingId = null;
      if (!title || title === s.title) return;
      await api(`/api/sessions/${s.id}`, { title }, "PUT").catch(() => {});
      await this.loadSessions();
    },
    async deleteSession(s) {
      if (!confirm(`确定删除会话「${s.title}」？`)) return;
      await api(`/api/sessions/${s.id}`, null, "DELETE").catch(() => {});
      await this.loadSessions();
      if (this.currentId === s.id) {
        if (this.sessions.length) await this.selectSession(this.sessions[0].id);
        else await this.newSession();
      }
    },
    toggleTheme() {
      const root = document.documentElement;
      const next = root.dataset.theme === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      localStorage.setItem("v8-theme", next);
    },

    /* ================= 发送 / SSE 对话 ================= */
    scrollBottom() {
      this.$nextTick(() => {
        const el = this.$refs.chatRef;
        if (!el) return;
        const userRows = el.querySelectorAll(".msg-row.user");
        if (userRows.length) {
          const last = userRows[userRows.length - 1];
          el.scrollTo({ top: Math.max(0, last.offsetTop - 12), behavior: "smooth" });
        } else {
          el.scrollTop = el.scrollHeight;
        }
      });
    },
    autosize() {
      const ta = this.$refs.ta;
      if (!ta) return;
      ta.style.height = "0";
      const scrollH = ta.scrollHeight;
      ta.style.height = Math.min(Math.max(scrollH, 46), 160) + "px";
      ta.style.overflowY = scrollH > 160 ? "auto" : "hidden";
    },
    async send() {
      if (this.thinking) return;
      const text = this.input.trim();
      if (!text || !this.currentId) return;
      if (this.activeEs) { try { this.activeEs.close(); } catch (_) {} this.activeEs = null; }
      this.thinking = true;
      this.input = ""; this.autosize();
      this.agentProgress = { A: false, B: false, C: false };

      const userMsg = { id: `u-${Date.now()}`, role: "user", text, chips: [], cats: [], analysis: null, charts: [] };
      this.messages.push(userMsg);

      const code = extractCode(text);
      if (/(分析|算法)/.test(text) && code) {
        this.picker.code = code;
        this.picker.algorithm = this.algorithms[0] ? this.algorithms[0].key : "";
        this.picker.show = true;
        this.thinking = false;
        this.scrollBottom();
        return;
      }

      const assistantMsg = { id: `a-${Date.now()}`, role: "assistant", text: "", chips: [], cats: [], analysis: null, charts: [] };
      this.messages.push(assistantMsg);

      // v9: 使用多智能体端点
      const es = new EventSource(
        `/api/chat/multi?${new URLSearchParams({ session_id: this.currentId, message: text })}`);
      this.activeEs = es;

      es.addEventListener("tool", (ev) => {
        const tc = JSON.parse(ev.data);
        (assistantMsg.chips = assistantMsg.chips || []).push({
          name: tc.name, icon: TOOL_ICON[tc.name] || "🔧", status: tc.result_summary || "",
        });
      });

      // v9: 智能体进度事件
      es.addEventListener("agent", (ev) => {
        const data = JSON.parse(ev.data);
        const agent = data.agent;
        const action = data.action || "";
        if (agent && this.agentProgress.hasOwnProperty(agent)) {
          this.agentProgress[agent] = true;
        }
      });

      // v9: 图表事件
      es.addEventListener("chart", (ev) => {
        const chart = JSON.parse(ev.data);
        assistantMsg.charts = assistantMsg.charts || [];
        assistantMsg.charts.push(chart);
        this.lastChart = chart;
        this.showChartDock = true;
        this.$nextTick(() => this.renderChart());
      });

      // v9: 异常事件
      es.addEventListener("anomaly", (ev) => {
        const data = JSON.parse(ev.data);
        this.anomalyModal.anomalies = data.anomalies || [];
        this.anomalyModal.question = data.question || "检测到数据异常";
        this.anomalyModal.show = true;
      });

      es.addEventListener("chunk", (ev) => {
        assistantMsg.text = (assistantMsg.text || "") + ev.data + "\n";
        this.scrollBottom();
      });
      es.addEventListener("data", () => {});
      es.addEventListener("error", (ev) => {
        assistantMsg.text = (assistantMsg.text || "") + `⚠️ ${ev.data || "处理失败"}`;
      });
      es.addEventListener("done", () => {
        es.close(); this.activeEs = null;
        this.thinking = false;
        assistantMsg.cats = this.categorize(assistantMsg);
        this.scrollBottom();
      });
      es.onerror = () => { es.close(); this.activeEs = null; this.thinking = false; };
    },

    /* v9: 异常处理 */
    async resolveAnomaly(anomalyId, resolution) {
      this.anomalyResolutions[anomalyId] = resolution;
      try {
        await api("/api/anomaly/resolve", {
          session_id: this.currentId,
          anomaly_id: anomalyId,
          resolution: resolution,
        });
      } catch (e) { console.error("resolve anomaly failed", e); }
      // 移除已处理的异常
      this.anomalyModal.anomalies = this.anomalyModal.anomalies.filter(a => a.id !== anomalyId);
      if (this.anomalyModal.anomalies.length === 0) {
        this.anomalyModal.show = false;
      }
    },

    /* v9: 图表 dock */
    toggleChart() {
      this.showChartDock = !this.showChartDock;
      if (this.showChartDock) {
        this.$nextTick(() => this.renderChart());
      }
    },
    startDockResize(e) {
      this.dockDragging = true;
      const startX = e.clientX;
      const startW = this.dockWidth;
      const onMove = (ev) => {
        const delta = startX - ev.clientX;
        this.dockWidth = Math.min(Math.max(startW + delta, 300), window.innerWidth * 0.7);
        this.$nextTick(() => this.renderChart());
      };
      const onUp = () => {
        this.dockDragging = false;
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },

    /* v9: ECharts 渲染 */
    renderChart() {
      const container = this.$refs.chartContainer;
      if (!container || !this.lastChart) return;

      // 清理旧实例
      if (this._chartInstance) {
        this._chartInstance.dispose();
        this._chartInstance = null;
      }

      const chart = echarts.init(container, document.documentElement.dataset.theme === "dark" ? "dark" : null);
      this._chartInstance = chart;

      const chartData = this.lastChart;
      const option = this._buildChartOption(chartData);
      chart.setOption(option, true);

      // 响应式
      this._chartResizeHandler = () => chart.resize();
      window.addEventListener("resize", this._chartResizeHandler);
    },

    _buildChartOption(cd) {
      const type = cd.type || "candlestick";
      const xData = cd.x_axis || [];
      const series = cd.series || [];

      if (type === "candlestick") {
        return this._candlestickOption(xData, series, cd);
      } else if (type === "prediction") {
        return this._predictionOption(xData, series, cd);
      } else if (type === "technical") {
        return this._technicalOption(xData, series, cd);
      }
      return {};
    },

    _candlestickOption(xData, series, cd) {
      const kline = series.find(s => s.type === "candlestick");
      const ma5 = series.find(s => s.name === "MA5");
      const ma10 = series.find(s => s.name === "MA10");
      const ma20 = series.find(s => s.name === "MA20");
      const vol = series.find(s => s.name === "成交量");

      const result = {
        title: { text: cd.title, left: "center", textStyle: { fontSize: 13 } },
        tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
        legend: { bottom: 0, textStyle: { fontSize: 11 } },
        grid: [
          { left: 60, right: 20, top: 40, height: "55%" },
          { left: 60, right: 20, top: "73%", height: "18%" },
        ],
        xAxis: [
          { type: "category", data: xData, gridIndex: 0, axisLabel: { fontSize: 10, rotate: 30, interval: Math.floor(xData.length / 8) } },
          { type: "category", data: xData, gridIndex: 1, axisLabel: { show: false } },
        ],
        yAxis: [
          { scale: true, gridIndex: 0, splitLine: { lineStyle: { type: "dashed" } } },
          { scale: true, gridIndex: 1, splitLine: { show: false }, axisLabel: { show: false } },
        ],
        dataZoom: [
          { type: "inside", xAxisIndex: [0, 1], start: Math.max(0, 100 - 100 * 60 / Math.max(xData.length, 1)), end: 100 },
          { type: "slider", xAxisIndex: [0, 1], bottom: 28, height: 16, start: Math.max(0, 100 - 100 * 60 / Math.max(xData.length, 1)), end: 100 },
        ],
        series: [],
      };

      if (kline) {
        result.series.push({
          name: "K线", type: "candlestick", data: kline.data,
          xAxisIndex: 0, yAxisIndex: 0,
          itemStyle: {
            color: "#e6545a", color0: "#10b981",
            borderColor: "#e6545a", borderColor0: "#10b981",
          },
        });
      }
      for (const ma of [ma5, ma10, ma20]) {
        if (ma) {
          result.series.push({
            name: ma.name, type: "line", data: ma.data,
            xAxisIndex: 0, yAxisIndex: 0,
            lineStyle: ma.lineStyle || { width: 1 },
            itemStyle: ma.itemStyle || {},
            symbol: "none",
          });
        }
      }
      if (vol) {
        result.series.push({
          name: "成交量", type: "bar", data: vol.data,
          xAxisIndex: 1, yAxisIndex: 1,
          itemStyle: { color: "#999" },
        });
      }
      return result;
    },

    _predictionOption(xData, series, cd) {
      const result = {
        title: { text: cd.title, left: "center", textStyle: { fontSize: 13 } },
        tooltip: { trigger: "axis" },
        legend: { bottom: 0, textStyle: { fontSize: 11 } },
        grid: { left: 60, right: 20, top: 40, bottom: 50 },
        xAxis: { type: "category", data: xData, axisLabel: { fontSize: 11 } },
        yAxis: { scale: true, splitLine: { lineStyle: { type: "dashed" } } },
        series: [],
      };

      for (const s of series) {
        result.series.push({
          name: s.name, type: "line", data: s.data,
          lineStyle: s.lineStyle || { width: 2 },
          itemStyle: s.itemStyle || {},
          symbol: "circle", symbolSize: 6,
        });
      }
      return result;
    },

    _technicalOption(xData, series, cd) {
      const result = {
        title: { text: cd.title, left: "center", textStyle: { fontSize: 13 } },
        tooltip: { trigger: "axis" },
        legend: { bottom: 0, textStyle: { fontSize: 11 } },
        grid: [
          { left: 60, right: 20, top: 40, height: "55%" },
          { left: 60, right: 20, top: "73%", height: "18%" },
        ],
        xAxis: [
          { type: "category", data: xData, gridIndex: 0, axisLabel: { fontSize: 10, rotate: 30, interval: Math.floor(xData.length / 8) } },
          { type: "category", data: xData, gridIndex: 1, axisLabel: { show: false } },
        ],
        yAxis: [
          { scale: true, gridIndex: 0, splitLine: { lineStyle: { type: "dashed" } } },
          { scale: true, gridIndex: 1, gridIndex: 1, splitLine: { show: false }, axisLabel: { show: false } },
        ],
        series: [],
      };

      for (const s of series) {
        const isMacd = s.name === "MACD柱";
        result.series.push({
          name: s.name, type: s.type, data: s.data,
          xAxisIndex: isMacd ? 1 : 0,
          yAxisIndex: isMacd ? 1 : 0,
          lineStyle: s.lineStyle || { width: 1.5 },
          itemStyle: s.itemStyle || {},
          symbol: "none",
          barWidth: isMacd ? 1 : undefined,
        });
      }
      return result;
    },

    /* 分类 */
    categorize(m) {
      const text = (m.text || "").trim();
      if (!text) return [];
      const order = ["info", "quote", "finance", "forecast", "analysis"];
      const CAT_KEYWORDS = {
        info:     /公司|简介|主营|行业|板块|上市|信息|概况|背景|代码|名称/,
        quote:    /行情|涨跌|收盘|开盘|最高|最低|K线|日线|盘中|股价|走势/,
        finance:  /财务|营收|利润|净利|毛利|ROE|分红|股息|报告|指标/,
        forecast: /预测|预估|未来|趋势|上涨|下跌|方向|概率|支撑|压力|置信/,
        analysis: /技术|指标|MACD|RSI|均线|MA\d|布林|BOLL|KDJ|趋势|动量/,
      };
      const sections = text.split(/(?=^###\s)/m).filter(s => s.trim());
      const buckets = {};
      order.forEach(k => { buckets[k] = []; });
      buckets["answer"] = [];
      for (const sec of sections) {
        const header = (sec.match(/^###\s*(.+)/m) || [])[1] || "";
        let placed = false;
        for (const [cat, re] of Object.entries(CAT_KEYWORDS)) {
          if (re.test(header)) { buckets[cat].push(sec.trim()); placed = true; break; }
        }
        if (!placed) {
          const snippet = sec.replace(/^###\s*.+\n?/, "").slice(0, 80);
          for (const [cat, re] of Object.entries(CAT_KEYWORDS)) {
            if (re.test(snippet)) { buckets[cat].push(sec.trim()); placed = true; break; }
          }
        }
        if (!placed) buckets["answer"].push(sec.trim());
      }
      if (sections.length <= 1) {
        const matched = [];
        for (const cat of order) { if (CAT_KEYWORDS[cat].test(text)) matched.push(cat); }
        if (matched.length) {
          matched.forEach(cat => { buckets[cat].push(text); });
          return matched.map(k => ({ key: k, ...CAT_HEAD[k], text: buckets[k].join("\n\n") }));
        }
        return [{ key: "answer", ...CAT_HEAD.answer, text }];
      }
      const cats = [];
      order.forEach(k => { if (buckets[k].length) cats.push({ key: k, ...CAT_HEAD[k], text: buckets[k].join("\n\n") }); });
      if (buckets["answer"].length) cats.push({ key: "answer", ...CAT_HEAD.answer, text: buckets["answer"].join("\n\n") });
      return cats;
    },

    /* 数据分析 */
    async runAnalysis() {
      if (this.running) return;
      this.running = true;
      try {
        const res = await api("/api/analysis/run", { code: this.picker.code, algorithm: this.picker.algorithm });
        this.picker.show = false;
        if (res.error) {
          this.messages.push({ id: `e-${Date.now()}`, role: "assistant", text: `⚠️ ${res.error}`, chips: [], cats: [], analysis: null, charts: [] });
        } else {
          this.messages.push({ id: `a-${Date.now()}`, role: "assistant", text: "", chips: [{ name: res.algorithm_label, icon: "🧮", status: res.code }], cats: [], analysis: res, charts: [] });
        }
      } catch (err) {
        this.picker.show = false;
        this.messages.push({ id: `e-${Date.now()}`, role: "assistant", text: `⚠️ 分析失败：${err.message}`, chips: [], cats: [], analysis: null, charts: [] });
      } finally {
        this.running = false;
        this.scrollBottom();
      }
    },
  },

  async mounted() {
    const theme = localStorage.getItem("v8-theme") || "light";
    document.documentElement.dataset.theme = theme;
    this.llmStatus = "checking";
    try {
      const st = await api("/api/llm-status");
      this.online = st.ok;
      this.llmStatus = st.ok ? "online" : "offline";
      this.llmError = st.ok ? "" : (st.error || "连接失败");
    } catch (e) {
      this.online = false;
      this.llmStatus = "offline";
      this.llmError = "服务不可达";
    }
    try {
      const res = await api("/api/analysis/options");
      this.algorithms = res.algorithms || [];
    } catch (e) { this.algorithms = []; }
    await this.loadSessions();
    if (this.sessions.length > 0) {
      await this.selectSession(this.sessions[0].id);
    } else {
      await this.newSession();
    }
  },
}).mount("#app");
