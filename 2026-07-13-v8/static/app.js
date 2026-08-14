/* ============================================================
   Stock Agent v8 — Vue3 应用（CDN 零构建）
   对话（SSE）· 分类回答 · 算法选择
   ============================================================ */
const { createApp, nextTick } = Vue;

/* ---------- 分类元数据：Agent 回答按类别分块展现 ---------- */
const CAT_HEAD = {
  quote:    { label: "行情", icon: "📊" },
  finance:  { label: "财务", icon: "💰" },
  forecast: { label: "预测", icon: "🔮" },
  analysis: { label: "分析", icon: "🧮" },
  info:     { label: "概况", icon: "🏢" },
  answer:   { label: "回答", icon: "💬" },
};
const TOOL_CAT = {
  get_profile: "info",
  get_history: "quote", get_intraday: "quote",
  get_financials: "finance", get_dividend: "finance",
  get_key_metrics: "finance", get_forecast: "finance",
  get_price_prediction: "forecast",
  get_technical_indicators: "analysis",
  get_capital_flow: "analysis", get_indicators: "analysis",
  search_stocks: "info",
};
const TOOL_ICON = {
  get_profile: "🏢", get_history: "📜", get_intraday: "⏱️", get_financials: "💰",
  get_dividend: "🧧", get_key_metrics: "📐", get_forecast: "🎯",
  get_price_prediction: "🔮", get_technical_indicators: "🧮",
  get_capital_flow: "💸", get_indicators: "📊", search_stocks: "🔍",
};
const cssVar = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#6366f1";
const at = (arr, i) => (arr && arr[i] != null ? arr[i] : null);
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

/* ---------- App ---------- */
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
          chips: [], cats: [], analysis: null,
        }));
      } catch (e) { this.messages = []; }
      this.scrollBottom();
    },
    async renameSession(s) {
      const title = prompt("重命名会话：", s.title);
      if (!title || title === s.title) return;
      await api(`/api/sessions/${s.id}`, { title }, "PUT").catch(() => {});
      await this.loadSessions();
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
          const offset = last.offsetTop - 12;
          el.scrollTo({ top: Math.max(0, offset), behavior: "smooth" });
        } else {
          el.scrollTop = el.scrollHeight;
        }
      });
    },
    autosize() {
      const ta = this.$refs.ta;
      if (!ta) return;
      ta.style.height = "0";
      const minH = 46;
      const maxH = 160;
      const scrollH = ta.scrollHeight;
      ta.style.height = Math.min(Math.max(scrollH, minH), maxH) + "px";
      ta.style.overflowY = scrollH > maxH ? "auto" : "hidden";
    },
    async send() {
      if (this.thinking) return;
      const text = this.input.trim();
      if (!text || !this.currentId) return;
      if (this.activeEs) { try { this.activeEs.close(); } catch (_) {} this.activeEs = null; }
      this.thinking = true;
      this.input = ""; this.autosize();

      const userMsg = { id: `u-${Date.now()}`, role: "user", text, chips: [], cats: [], analysis: null };
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

      const assistantMsg = { id: `a-${Date.now()}`, role: "assistant", text: "", chips: [], cats: [], analysis: null };
      this.messages.push(assistantMsg);
      const es = new EventSource(
        `/api/chat/stream?${new URLSearchParams({ session_id: this.currentId, message: text })}`);
      this.activeEs = es;
      es.addEventListener("tool", (ev) => {
        const tc = JSON.parse(ev.data);
        (assistantMsg.chips = assistantMsg.chips || []).push({
          name: tc.name, icon: TOOL_ICON[tc.name] || "🔧", status: tc.result_summary || "",
        });
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
    /* 将 LLM 回答按 markdown 标题拆分，分配到对应分类块 */
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
        const allText = text;
        const matched = [];
        for (const cat of order) {
          if (CAT_KEYWORDS[cat].test(allText)) matched.push(cat);
        }
        if (matched.length) {
          matched.forEach(cat => { buckets[cat].push(allText); });
          return matched.map(k => ({ key: k, ...CAT_HEAD[k], text: buckets[k].join("\n\n") }));
        }
        return [{ key: "answer", ...CAT_HEAD.answer, text: allText }];
      }
      const cats = [];
      order.forEach(k => {
        if (buckets[k].length) cats.push({ key: k, ...CAT_HEAD[k], text: buckets[k].join("\n\n") });
      });
      if (buckets["answer"].length) cats.push({ key: "answer", ...CAT_HEAD.answer, text: buckets["answer"].join("\n\n") });
      return cats;
    },
    /* ================= 数据分析 ================= */
    async runAnalysis() {
      if (this.running) return;
      this.running = true;
      try {
        const res = await api("/api/analysis/run", {
          code: this.picker.code, algorithm: this.picker.algorithm,
        });
        this.picker.show = false;
        if (res.error) {
          this.messages.push({ id: `e-${Date.now()}`, role: "assistant", text: `⚠️ ${res.error}`, chips: [], cats: [], analysis: null });
        } else {
          const msg = {
            id: `a-${Date.now()}`, role: "assistant", text: "",
            chips: [{ name: res.algorithm_label, icon: "🧮", status: res.code }],
            cats: [], analysis: res,
          };
          this.messages.push(msg);
        }
      } catch (err) {
        this.picker.show = false;
        this.messages.push({ id: `e-${Date.now()}`, role: "assistant", text: `⚠️ 分析失败：${err.message}`, chips: [], cats: [], analysis: null });
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
