/**
 * widget.js
 * ---------
 * Embeddable, course-aware chat widget. Drop this on any course page:
 *
 *   <script>
 *     window.COURSE_ASSISTANT_CONFIG = {
 *       apiBase: "http://127.0.0.1:8080",
 *       courseId: "ISWE411L",   // fixes the widget to one course (typical: embedded
 *                                  on that course's own material page). Omit this to
 *                                  show a course picker instead (a portal-wide assistant).
 *       title: "Course Assistant"
 *     };
 *   </script>
 *   <script src="widget.js"></script>
 *
 * What it does:
 *   - Retrieval + answers are always scoped to ONE course (courseId).
 *   - Answers render as a short explanation + an "Important Concepts" list.
 *   - After each answer, the host page's material list is visually updated:
 *     rows matching the answer's source documents are highlighted, everything
 *     else is dimmed â€” via [data-course-material][data-source="..."] elements
 *     already present on the host page (see demo-course-page.html).
 *   - No upload/reset UI. Students only ask questions.
 *
 * Styles for the popup itself live in a Shadow DOM (isolated from the host
 * page's CSS). The highlight/dim styles are injected once into the host
 * page's <head> because they need to affect the host page's own elements.
 */

(function () {
  const CONFIG = window.COURSE_ASSISTANT_CONFIG || {};
  const API_BASE = CONFIG.apiBase || "http://127.0.0.1:8080";
  const TITLE = CONFIG.title || "Course Assistant";
  const EXTERNAL_COURSE_CONTROL = CONFIG.courseSelector === "external";
  let courseId = CONFIG.courseId || null;
  let courseName = CONFIG.courseId || null;

  // ---------- Host-page highlight styles (injected once, outside shadow DOM) ----------
  if (!document.getElementById("course-assistant-highlight-styles")) {
    const hostStyle = document.createElement("style");
    hostStyle.id = "course-assistant-highlight-styles";
    hostStyle.textContent = `
      [data-course-material] { transition: opacity .35s ease, box-shadow .35s ease, background-color .35s ease; }
      [data-course-material].ca-dimmed { opacity: 0.32; }
      [data-course-material].ca-highlight {
        opacity: 1;
        box-shadow: inset 0 0 0 2px #d4a94a;
        background-color: rgba(212,169,74,0.08);
        border-radius: 4px;
      }
    `;
    document.head.appendChild(hostStyle);
  }

  let highlightTimer = null;
  function highlightMaterials(sources) {
    const all = document.querySelectorAll("[data-course-material]");
    if (!all.length) return;

    clearTimeout(highlightTimer);
    all.forEach((el) => {
      const src = el.getAttribute("data-source");
      if (sources.includes(src)) {
        el.classList.add("ca-highlight");
        el.classList.remove("ca-dimmed");
        el.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } else {
        el.classList.add("ca-dimmed");
        el.classList.remove("ca-highlight");
      }
    });

    highlightTimer = setTimeout(() => {
      all.forEach((el) => el.classList.remove("ca-dimmed", "ca-highlight"));
    }, 9000);
  }

  // ---------- Host + Shadow root for the popup UI ----------
  const hostEl = document.createElement("div");
  hostEl.id = "course-assistant-widget";
  document.body.appendChild(hostEl);
  const root = hostEl.attachShadow({ mode: "open" });

  const style = document.createElement("style");
  style.textContent = `
    :host, * { box-sizing: border-box; }
    .wrap {
      position: fixed; bottom: 22px; right: 22px; z-index: 999999;
      font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    .bubble-btn {
      width: 56px; height: 56px; border-radius: 50%;
      background: #d4a94a; border: none; cursor: pointer;
      box-shadow: 0 6px 20px rgba(0,0,0,0.28);
      display: flex; align-items: center; justify-content: center;
      transition: transform .15s ease; position: relative;
    }
    .bubble-btn:hover { transform: scale(1.06); }
    .bubble-btn svg { width: 26px; height: 26px; }

    .panel {
      position: absolute; bottom: 68px; right: 0;
      width: 380px; max-width: calc(100vw - 40px);
      height: 540px; max-height: calc(100vh - 120px);
      background: #16211c;
      border: 1px solid rgba(237,232,218,0.14);
      border-radius: 14px;
      box-shadow: 0 20px 50px rgba(0,0,0,0.4);
      display: none; flex-direction: column; overflow: hidden;
      color: #ede8da;
    }
    .panel.open { display: flex; }

    .panel-header {
      padding: 14px 16px;
      border-bottom: 1px solid rgba(237,232,218,0.14);
      display: flex; align-items: center; justify-content: space-between;
      background: #1c2b23;
      gap: 10px;
    }
    .panel-header-title {
      font-family: 'Source Serif 4', Georgia, serif;
      font-weight: 600; font-size: 0.96rem;
      display: flex; align-items: center; gap: 8px;
      overflow: hidden;
    }
    .panel-header-title .course-name {
      color: #b9c2b6; font-family: 'IBM Plex Sans', sans-serif; font-weight: 400;
      font-size: 0.78rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .status-dot { width: 7px; height: 7px; border-radius: 50%; background: #6f8f7f; flex-shrink: 0; }
    .status-dot.off { background: #d47a4a; }
    .close-btn {
      background: none; border: none; color: #b9c2b6; cursor: pointer;
      font-size: 1.1rem; line-height: 1; padding: 4px; flex-shrink: 0;
    }
    .close-btn:hover { color: #ede8da; }

    .course-picker {
      padding: 12px 14px; border-bottom: 1px solid rgba(237,232,218,0.14);
      display: flex; flex-direction: column; gap: 8px;
    }
    .course-picker label { font-size: 0.72rem; color: #b9c2b6; font-family: 'IBM Plex Mono', monospace; text-transform: uppercase; letter-spacing: .06em; }
    .course-picker select {
      background: rgba(237,232,218,0.06); color: #ede8da;
      border: 1px solid rgba(237,232,218,0.18); border-radius: 6px;
      padding: 8px 10px; font-size: 0.85rem; font-family: inherit;
    }

    .log { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 14px; }
    .log::-webkit-scrollbar { width: 6px; }
    .log::-webkit-scrollbar-thumb { background: rgba(237,232,218,0.14); border-radius: 3px; }

    .msg { max-width: 90%; display: flex; flex-direction: column; gap: 6px; }
    .msg.user { align-self: flex-end; align-items: flex-end; }
    .msg.bot { align-self: flex-start; align-items: flex-start; }

    .bubble-text {
      padding: 10px 12px; border-radius: 10px; font-size: 0.86rem; line-height: 1.55;
      white-space: pre-wrap;
    }
    .msg.user .bubble-text { background: #d4a94a; color: #22190a; border-radius: 10px 10px 2px 10px; }
    .msg.bot .bubble-text { background: rgba(237,232,218,0.05); border: 1px solid rgba(237,232,218,0.14); border-radius: 10px 10px 10px 2px; }

    .concepts-block {
      background: rgba(212,169,74,0.06);
      border: 1px solid rgba(212,169,74,0.3);
      border-radius: 8px;
      padding: 9px 11px;
      width: 100%;
    }
    .concepts-title {
      font-family: 'IBM Plex Mono', monospace;
      font-size: 0.65rem; text-transform: uppercase; letter-spacing: .08em;
      color: #d4a94a; margin-bottom: 6px;
    }
    .concepts-list { display: flex; flex-wrap: wrap; gap: 6px; }
    .concept-chip {
      font-size: 0.74rem; background: rgba(212,169,74,0.14);
      color: #ecd9ab; border: 1px solid rgba(212,169,74,0.35);
      border-radius: 100px; padding: 3px 9px;
    }

    .sources-row { display: flex; flex-wrap: wrap; gap: 6px; }
    .source-tag {
      font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; color: #6f8f7f;
      border: 1px solid #4a6058; border-radius: 3px; padding: 2px 6px; cursor: default;
    }

    .type-badge {
      font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; text-transform: uppercase;
      letter-spacing: .06em; padding: 3px 8px; border-radius: 4px; align-self: flex-start;
    }
    .type-badge.general { background: rgba(212,122,74,0.15); color: #e2a988; border: 1px solid rgba(212,122,74,0.4); }

    .toolbar {
      padding: 8px 12px; border-bottom: 1px solid rgba(237,232,218,0.14);
      display: flex; align-items: center; justify-content: space-between; gap: 8px;
      background: #1c2b23;
    }
    .tabs { display: flex; gap: 4px; }
    .tab-btn, .topics-btn, .mode-btn {
      background: rgba(237,232,218,0.05); border: 1px solid rgba(237,232,218,0.14);
      color: #b9c2b6; font-family: 'IBM Plex Sans', sans-serif; font-size: 0.72rem;
      padding: 5px 10px; border-radius: 6px; cursor: pointer; white-space: nowrap;
    }
    .tab-btn.active, .mode-btn.active {
      background: rgba(212,169,74,0.16); border-color: rgba(212,169,74,0.45); color: #ecd9ab;
    }
    .topics-btn:hover, .tab-btn:hover:not(.active), .mode-btn:hover:not(.active) { border-color: rgba(237,232,218,0.3); }
    .topics-btn:disabled, .tab-btn:disabled, .mode-btn:disabled { opacity: 0.4; cursor: not-allowed; }

    .mode-row {
      padding: 8px 12px; border-bottom: 1px solid rgba(237,232,218,0.14);
      display: flex; gap: 6px; background: #1c2b23;
    }
    .mode-row.hidden { display: none; }

    .search-results { display: flex; flex-direction: column; gap: 8px; width: 100%; }
    .search-result-card {
      background: rgba(237,232,218,0.04); border: 1px solid rgba(237,232,218,0.14);
      border-radius: 8px; padding: 8px 10px;
    }
    .search-result-source {
      font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; color: #d4a94a; margin-bottom: 4px;
    }
    .search-result-snippet { font-size: 0.8rem; line-height: 1.45; color: #ede8da; }

    .typing { display: flex; gap: 4px; padding: 10px 12px; }
    .typing span { width: 5px; height: 5px; border-radius: 50%; background: #b9c2b6; animation: blink 1.2s infinite; }
    .typing span:nth-child(2) { animation-delay: .2s; }
    .typing span:nth-child(3) { animation-delay: .4s; }
    @keyframes blink { 0%,80%,100% { opacity: .25; } 40% { opacity: 1; } }

    .composer { padding: 10px; border-top: 1px solid rgba(237,232,218,0.14); display: flex; gap: 8px; background: #1c2b23; }
    .composer input {
      flex: 1; background: rgba(237,232,218,0.06); border: 1px solid rgba(237,232,218,0.14);
      border-radius: 8px; padding: 9px 11px; color: #ede8da; font-size: 0.85rem; font-family: inherit;
    }
    .composer input:focus { outline: none; border-color: #d4a94a; }
    .composer input::placeholder { color: #8b9389; }
    .composer input:disabled { opacity: 0.5; }
    .composer button {
      background: #d4a94a; color: #22190a; border: none; border-radius: 8px;
      padding: 0 14px; font-weight: 600; font-size: 0.82rem; cursor: pointer;
    }
    .composer button:disabled { opacity: .45; cursor: not-allowed; }

    .footer-note { font-size: 0.65rem; color: #8b9389; text-align: center; padding: 6px 10px 10px; font-family: 'IBM Plex Mono', monospace; }

    /* ---------- Quiz ---------- */
    .quiz-panel { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 16px; }
    .quiz-panel::-webkit-scrollbar { width: 6px; }
    .quiz-panel::-webkit-scrollbar-thumb { background: rgba(237,232,218,0.14); border-radius: 3px; }

    .quiz-section-title {
      font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; text-transform: uppercase;
      letter-spacing: .08em; color: #d4a94a; margin-bottom: 8px;
    }
    .quiz-choice-row { display: flex; flex-wrap: wrap; gap: 6px; }
    .quiz-choice-btn {
      background: rgba(237,232,218,0.05); border: 1px solid rgba(237,232,218,0.14);
      color: #ede8da; font-family: 'IBM Plex Sans', sans-serif; font-size: 0.82rem;
      padding: 8px 12px; border-radius: 8px; cursor: pointer; text-align: left;
    }
    .quiz-choice-btn:hover { border-color: rgba(212,169,74,0.4); }
    .quiz-choice-btn.selected { background: rgba(212,169,74,0.14); border-color: #d4a94a; color: #ecd9ab; }
    .quiz-choice-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    .quiz-topic-list { display: flex; flex-wrap: wrap; gap: 6px; max-height: 130px; overflow-y: auto; padding: 2px; }

    .quiz-generate-btn {
      background: #d4a94a; color: #22190a; border: none; border-radius: 8px;
      padding: 11px 14px; font-weight: 600; font-size: 0.86rem; cursor: pointer;
      font-family: 'IBM Plex Sans', sans-serif; margin-top: 4px;
    }
    .quiz-generate-btn:disabled { opacity: 0.4; cursor: not-allowed; }
    .quiz-secondary-btn {
      background: rgba(237,232,218,0.05); border: 1px solid rgba(237,232,218,0.18);
      color: #ede8da; border-radius: 8px; padding: 10px 14px; font-size: 0.84rem;
      cursor: pointer; font-family: 'IBM Plex Sans', sans-serif;
    }
    .quiz-secondary-btn:hover { border-color: rgba(237,232,218,0.35); }
    .quiz-actions-row { display: flex; gap: 8px; flex-wrap: wrap; }

    .quiz-status-msg { font-size: 0.85rem; color: #b9c2b6; line-height: 1.5; }
    .quiz-error-box {
      background: rgba(212,122,74,0.1); border: 1px solid rgba(212,122,74,0.35);
      border-radius: 8px; padding: 10px 12px; font-size: 0.84rem; color: #e2a988;
    }

    .quiz-progress {
      font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; color: #b9c2b6;
      text-transform: uppercase; letter-spacing: .06em;
    }
    .quiz-question-text { font-size: 0.94rem; line-height: 1.55; color: #ede8da; }
    .quiz-answer-btn {
      background: rgba(237,232,218,0.05); border: 1px solid rgba(237,232,218,0.14);
      color: #ede8da; font-family: 'IBM Plex Sans', sans-serif; font-size: 0.86rem;
      padding: 10px 12px; border-radius: 8px; cursor: pointer; text-align: left; line-height: 1.4;
    }
    .quiz-answer-btn:hover:not(:disabled) { border-color: rgba(212,169,74,0.4); }
    .quiz-answer-btn:disabled { cursor: default; }
    .quiz-answer-btn.correct { background: rgba(111,143,127,0.18); border-color: #6f8f7f; color: #d7e2dc; }
    .quiz-answer-btn.incorrect { background: rgba(212,122,74,0.15); border-color: #d47a4a; color: #f0c9b2; }

    .quiz-feedback-box {
      background: rgba(237,232,218,0.04); border: 1px solid rgba(237,232,218,0.14);
      border-radius: 8px; padding: 10px 12px; display: flex; flex-direction: column; gap: 6px;
    }
    .quiz-feedback-verdict { font-weight: 600; font-size: 0.85rem; }
    .quiz-feedback-verdict.correct { color: #9fbcaf; }
    .quiz-feedback-verdict.incorrect { color: #e2a988; }
    .quiz-feedback-explanation { font-size: 0.82rem; line-height: 1.5; color: #ede8da; }

    .quiz-score-display { text-align: center; padding: 10px 0; }
    .quiz-score-number { font-family: 'Source Serif 4', Georgia, serif; font-size: 2.1rem; color: #d4a94a; font-weight: 600; }
    .quiz-score-label { font-size: 0.78rem; color: #b9c2b6; margin-top: 2px; }

    .quiz-review-item { border-top: 1px solid rgba(237,232,218,0.14); padding: 10px 0; display: flex; flex-direction: column; gap: 5px; }
    .quiz-review-item:first-child { border-top: none; }
    .quiz-review-question { font-size: 0.85rem; font-weight: 600; color: #ede8da; }
    .quiz-review-line { font-size: 0.8rem; line-height: 1.5; }
    .quiz-review-line.correct { color: #9fbcaf; }
    .quiz-review-line.incorrect { color: #e2a988; }
    .quiz-review-explanation { font-size: 0.78rem; color: #b9c2b6; line-height: 1.5; }
  `;
  root.appendChild(style);

  // ---------- Markup ----------
  const wrap = document.createElement("div");
  wrap.className = "wrap";
  wrap.innerHTML = `
    <div class="panel" id="panel">
      <div class="panel-header">
        <div class="panel-header-title">
          <span class="status-dot off" id="status-dot"></span>
          <span>${TITLE}</span>
          <span class="course-name" id="course-name-label"></span>
        </div>
        <button class="close-btn" id="close-btn">&times;</button>
      </div>
      <div class="course-picker" id="course-picker" style="display:none;">
        <label>Select your course</label>
        <select id="course-select">
          <option value="">Loading coursesâ€¦</option>
        </select>
      </div>
      <div class="toolbar">
        <div class="tabs">
          <button type="button" class="tab-btn active" id="tab-ask" data-tab="ask">Ask</button>
          <button type="button" class="tab-btn" id="tab-search" data-tab="search">Search</button>
          <button type="button" class="tab-btn" id="tab-quiz" data-tab="quiz">Quiz</button>
        </div>
        <button type="button" class="topics-btn" id="topics-btn" disabled>Important Topics</button>
      </div>
      <div class="mode-row" id="mode-row">
        <button type="button" class="mode-btn active" id="mode-normal" data-mode="normal">Normal</button>
        <button type="button" class="mode-btn" id="mode-simple" data-mode="simple">Simple</button>
        <button type="button" class="mode-btn" id="mode-exam" data-mode="exam">Exam</button>
      </div>
      <div class="log" id="log"></div>
      <div class="quiz-panel" id="quiz-panel" style="display:none;"></div>
      <form class="composer" id="composer">
        <input type="text" id="question-input" placeholder="Ask about this course..." autocomplete="off" disabled />
        <button type="submit" id="send-btn" disabled>Ask</button>
      </form>
      <div class="footer-note" id="footer-note">Answers are based only on materials your faculty uploaded.</div>
    </div>
    <button class="bubble-btn" id="bubble-btn" aria-label="Open course assistant">
      <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M4 4h16v12H7l-3 3V4z" stroke="#22190a" stroke-width="1.8" stroke-linejoin="round"/>
      </svg>
    </button>
  `;
  root.appendChild(wrap);

  // ---------- Elements ----------
  const panel = root.getElementById("panel");
  const bubbleBtn = root.getElementById("bubble-btn");
  const closeBtn = root.getElementById("close-btn");
  const log = root.getElementById("log");
  const composer = root.getElementById("composer");
  const input = root.getElementById("question-input");
  const sendBtn = root.getElementById("send-btn");
  const statusDot = root.getElementById("status-dot");
  const courseNameLabel = root.getElementById("course-name-label");
  const coursePicker = root.getElementById("course-picker");
  const courseSelect = root.getElementById("course-select");
  const tabAsk = root.getElementById("tab-ask");
  const tabSearch = root.getElementById("tab-search");
  const tabQuiz = root.getElementById("tab-quiz");
  const topicsBtn = root.getElementById("topics-btn");
  const modeRow = root.getElementById("mode-row");
  const modeButtons = [root.getElementById("mode-normal"), root.getElementById("mode-simple"), root.getElementById("mode-exam")];
  const quizPanel = root.getElementById("quiz-panel");
  const footerNote = root.getElementById("footer-note");

  let opened = false;
  let greeted = false;
  let currentTab = "ask";      // "ask" | "search" | "quiz"
  let currentMode = "normal";  // "normal" | "simple" | "exam"

  function setComposerEnabled(enabled) {
    input.disabled = !enabled;
    sendBtn.disabled = !enabled;
    topicsBtn.disabled = !enabled;
    tabAsk.disabled = !enabled;
    tabSearch.disabled = !enabled;
    tabQuiz.disabled = !enabled;
  }

  function setTab(tab) {
    currentTab = tab;
    tabAsk.classList.toggle("active", tab === "ask");
    tabSearch.classList.toggle("active", tab === "search");
    tabQuiz.classList.toggle("active", tab === "quiz");
    modeRow.classList.toggle("hidden", tab !== "ask");

    if (tab === "quiz") {
      log.style.display = "none";
      composer.style.display = "none";
      footerNote.style.display = "none";
      quizPanel.style.display = "flex";
      if (quizState === "idle") renderQuizSetup();
    } else {
      log.style.display = "flex";
      composer.style.display = "flex";
      footerNote.style.display = "block";
      quizPanel.style.display = "none";
      input.placeholder = tab === "ask" ? "Ask about this course..." : "Search course materials...";
      sendBtn.textContent = tab === "ask" ? "Ask" : "Search";
    }
  }
  tabAsk.addEventListener("click", () => setTab("ask"));
  tabSearch.addEventListener("click", () => setTab("search"));
  tabQuiz.addEventListener("click", () => setTab("quiz"));

  modeButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      currentMode = btn.dataset.mode;
      modeButtons.forEach((b) => b.classList.toggle("active", b === btn));
    });
  });

  // ================================================================
  // Quiz tab â€” self-contained: setup (scope/topic, count, difficulty)
  // -> one question at a time -> score/review/retry. Does not touch
  // ask()/runSearch()/addMessage() or any existing Ask/Search behavior.
  // ================================================================
  let quizState = "idle";        // "idle" | "setup" | "loading" | "active" | "result"
  let quizScope = null;          // "entire" | "topic"
  let quizTopic = null;
  let quizNumQuestions = 5;
  let quizDifficulty = "medium";
  let quizQuestions = [];
  let quizIndex = 0;
  let quizAnswers = [];          // selected option index per question, or null
  let quizTopicsCache = null;    // cached Important Topics list for the "Select Topic" step

  function resetQuizState() {
    quizState = "idle";
    quizScope = null;
    quizTopic = null;
    quizNumQuestions = 5;
    quizDifficulty = "medium";
    quizQuestions = [];
    quizIndex = 0;
    quizAnswers = [];
    quizTopicsCache = null;
  }

  async function fetchQuizTopics() {
    if (quizTopicsCache) return quizTopicsCache;
    try {
      const res = await fetch(`${API_BASE}/important-topics?course_id=${encodeURIComponent(courseId)}`);
      const data = await res.json();
      quizTopicsCache = res.ok ? (data.topics || []) : [];
    } catch (e) {
      quizTopicsCache = [];
    }
    return quizTopicsCache;
  }

  function renderQuizSetup() {
    quizState = "setup";
    quizPanel.innerHTML = `
      <div>
        <div class="quiz-section-title">Quiz Scope</div>
        <div class="quiz-choice-row">
          <button type="button" class="quiz-choice-btn" data-scope="entire">Entire Course</button>
          <button type="button" class="quiz-choice-btn" data-scope="topic">Select Topic</button>
        </div>
        <div id="quiz-topic-area" style="margin-top:8px;"></div>
      </div>
      <div>
        <div class="quiz-section-title">Number of Questions</div>
        <div class="quiz-choice-row">
          <button type="button" class="quiz-choice-btn" data-count="5">5</button>
          <button type="button" class="quiz-choice-btn" data-count="10">10</button>
          <button type="button" class="quiz-choice-btn" data-count="15">15</button>
        </div>
      </div>
      <div>
        <div class="quiz-section-title">Difficulty</div>
        <div class="quiz-choice-row">
          <button type="button" class="quiz-choice-btn" data-difficulty="easy">Easy</button>
          <button type="button" class="quiz-choice-btn" data-difficulty="medium">Medium</button>
          <button type="button" class="quiz-choice-btn" data-difficulty="hard">Hard</button>
        </div>
      </div>
      <div id="quiz-setup-error"></div>
      <button type="button" class="quiz-generate-btn" id="quiz-generate-btn" disabled>Generate Quiz</button>
    `;

    const scopeBtns = [...quizPanel.querySelectorAll("[data-scope]")];
    const countBtns = [...quizPanel.querySelectorAll("[data-count]")];
    const difficultyBtns = [...quizPanel.querySelectorAll("[data-difficulty]")];
    const topicArea = quizPanel.querySelector("#quiz-topic-area");
    const generateBtn = quizPanel.querySelector("#quiz-generate-btn");
    const setupError = quizPanel.querySelector("#quiz-setup-error");

    // Pre-select current defaults (persist choices if the student re-opens setup).
    countBtns.forEach((b) => b.classList.toggle("selected", Number(b.dataset.count) === quizNumQuestions));
    difficultyBtns.forEach((b) => b.classList.toggle("selected", b.dataset.difficulty === quizDifficulty));
    if (quizScope) scopeBtns.forEach((b) => b.classList.toggle("selected", b.dataset.scope === quizScope));

    function updateGenerateEnabled() {
      const ready = quizScope && (quizScope === "entire" || (quizScope === "topic" && quizTopic));
      generateBtn.disabled = !ready;
    }

    scopeBtns.forEach((btn) => {
      btn.addEventListener("click", async () => {
        quizScope = btn.dataset.scope;
        scopeBtns.forEach((b) => b.classList.toggle("selected", b === btn));
        if (quizScope === "entire") {
          quizTopic = null;
          topicArea.innerHTML = "";
        } else {
          topicArea.innerHTML = `<div class="quiz-status-msg">Loading topicsâ€¦</div>`;
          const topics = await fetchQuizTopics();
          if (!topics.length) {
            topicArea.innerHTML = `<div class="quiz-status-msg">No Important Topics available for this course yet â€” try "Entire Course" instead.</div>`;
          } else {
            topicArea.innerHTML = `<div class="quiz-topic-list">${topics
              .map((t) => `<button type="button" class="quiz-choice-btn" data-topic="${t}">${t}</button>`)
              .join("")}</div>`;
            const topicBtns = [...topicArea.querySelectorAll("[data-topic]")];
            topicBtns.forEach((tb) => {
              tb.addEventListener("click", () => {
                quizTopic = tb.dataset.topic;
                topicBtns.forEach((b) => b.classList.toggle("selected", b === tb));
                updateGenerateEnabled();
              });
            });
          }
        }
        updateGenerateEnabled();
      });
    });

    countBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        quizNumQuestions = Number(btn.dataset.count);
        countBtns.forEach((b) => b.classList.toggle("selected", b === btn));
      });
    });

    difficultyBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        quizDifficulty = btn.dataset.difficulty;
        difficultyBtns.forEach((b) => b.classList.toggle("selected", b === btn));
      });
    });

    generateBtn.addEventListener("click", async () => {
      quizState = "loading";
      setupError.innerHTML = "";
      quizPanel.innerHTML = `<div class="quiz-status-msg">Generating your quiz â€” this can take a little while on a local modelâ€¦</div>`;
      try {
        const res = await fetch(`${API_BASE}/quiz/generate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            course_id: courseId,
            scope: quizScope,
            topic: quizScope === "topic" ? quizTopic : null,
            num_questions: quizNumQuestions,
            difficulty: quizDifficulty,
          }),
        });
        const data = await res.json();
        if (res.ok && data.questions && data.questions.length) {
          quizQuestions = data.questions;
          quizAnswers = new Array(quizQuestions.length).fill(null);
          quizIndex = 0;
          quizState = "active";
          renderQuizQuestion();
        } else {
          quizState = "setup";
          renderQuizSetup();
          const err = quizPanel.querySelector("#quiz-setup-error");
          if (err) {
            err.innerHTML = `<div class="quiz-error-box">${data.detail || "Couldn't generate a quiz. Try again."}</div>`;
          }
        }
      } catch (e) {
        quizState = "setup";
        renderQuizSetup();
        const err = quizPanel.querySelector("#quiz-setup-error");
        if (err) {
          err.innerHTML = `<div class="quiz-error-box">Can't reach the course assistant right now. Try again shortly.</div>`;
        }
      }
    });

    updateGenerateEnabled();
  }

  function renderQuizQuestion() {
    const q = quizQuestions[quizIndex];
    const total = quizQuestions.length;
    const alreadyAnswered = quizAnswers[quizIndex] !== null;

    quizPanel.innerHTML = `
      <div class="quiz-progress">Question ${quizIndex + 1} of ${total}</div>
      <div class="quiz-question-text">${q.question}</div>
      <div id="quiz-options" style="display:flex; flex-direction:column; gap:8px;"></div>
      <div id="quiz-feedback-area"></div>
      <div class="quiz-actions-row" id="quiz-nav-area"></div>
    `;

    const optionsWrap = quizPanel.querySelector("#quiz-options");
    q.options.forEach((optionText, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "quiz-answer-btn";
      btn.textContent = optionText;
      if (alreadyAnswered) {
        btn.disabled = true;
        if (i === q.correct_index) btn.classList.add("correct");
        else if (i === quizAnswers[quizIndex]) btn.classList.add("incorrect");
      }
      btn.addEventListener("click", () => selectQuizAnswer(i));
      optionsWrap.appendChild(btn);
    });

    if (alreadyAnswered) {
      renderQuizFeedback();
      renderQuizNav();
    }
  }

  function renderQuizFeedback() {
    const q = quizQuestions[quizIndex];
    const selected = quizAnswers[quizIndex];
    const isCorrect = selected === q.correct_index;
    const area = quizPanel.querySelector("#quiz-feedback-area");
    if (!area) return;
    area.innerHTML = `
      <div class="quiz-feedback-box">
        <div class="quiz-feedback-verdict ${isCorrect ? "correct" : "incorrect"}">${isCorrect ? "Correct" : "Not quite"}</div>
        <div class="quiz-feedback-explanation">${q.explanation}</div>
        <span class="source-tag">${q.source}</span>
      </div>
    `;
  }

  function renderQuizNav() {
    const area = quizPanel.querySelector("#quiz-nav-area");
    if (!area) return;
    const isLast = quizIndex === quizQuestions.length - 1;
    area.innerHTML = `<button type="button" class="quiz-generate-btn" id="quiz-next-btn">${isLast ? "See Results" : "Next Question"}</button>`;
    area.querySelector("#quiz-next-btn").addEventListener("click", () => {
      if (isLast) {
        quizState = "result";
        renderQuizResult();
      } else {
        quizIndex += 1;
        renderQuizQuestion();
      }
    });
  }

  function selectQuizAnswer(optionIndex) {
    if (quizAnswers[quizIndex] !== null) return; // already answered, ignore further clicks
    quizAnswers[quizIndex] = optionIndex;
    renderQuizQuestion();

    // Surface where this question's answer came from, same visual language
    // as Ask/Search, without touching their code paths.
    const q = quizQuestions[quizIndex];
    if (q.source) highlightMaterials([q.source]);
  }

  function renderQuizResult() {
    const total = quizQuestions.length;
    const correctCount = quizQuestions.reduce(
      (acc, q, i) => acc + (quizAnswers[i] === q.correct_index ? 1 : 0), 0
    );

    const reviewHtml = quizQuestions.map((q, i) => {
      const selected = quizAnswers[i];
      const isCorrect = selected === q.correct_index;
      return `
        <div class="quiz-review-item">
          <div class="quiz-review-question">${i + 1}. ${q.question}</div>
          <div class="quiz-review-line ${isCorrect ? "correct" : "incorrect"}">
            Your answer: ${q.options[selected]}${isCorrect ? "" : ` â€” Correct: ${q.options[q.correct_index]}`}
          </div>
          <div class="quiz-review-explanation">${q.explanation}</div>
          <span class="source-tag">${q.source}</span>
        </div>
      `;
    }).join("");

    quizPanel.innerHTML = `
      <div class="quiz-score-display">
        <div class="quiz-score-number">${correctCount} / ${total}</div>
        <div class="quiz-score-label">${quizScope === "topic" ? `Topic: ${quizTopic}` : "Entire Course"} Â· ${quizDifficulty}</div>
      </div>
      <div class="quiz-actions-row">
        <button type="button" class="quiz-secondary-btn" id="quiz-retry-btn">Retry Same Quiz</button>
        <button type="button" class="quiz-secondary-btn" id="quiz-new-btn">New Quiz</button>
      </div>
      <div class="quiz-section-title">Review</div>
      ${reviewHtml}
    `;

    quizPanel.querySelector("#quiz-retry-btn").addEventListener("click", () => {
      quizAnswers = new Array(quizQuestions.length).fill(null);
      quizIndex = 0;
      quizState = "active";
      renderQuizQuestion();
    });
    quizPanel.querySelector("#quiz-new-btn").addEventListener("click", () => {
      quizQuestions = [];
      quizAnswers = [];
      quizIndex = 0;
      quizState = "setup";
      renderQuizSetup();
    });
  }

  function addMessage(role, { text, concepts = [], sources = [], badge = null } = {}) {
    const msg = document.createElement("div");
    msg.className = `msg ${role}`;

    if (badge) {
      const badgeEl = document.createElement("div");
      badgeEl.className = `type-badge ${badge.kind}`;
      badgeEl.textContent = badge.label;
      msg.appendChild(badgeEl);
    }

    const bubble = document.createElement("div");
    bubble.className = "bubble-text";
    bubble.textContent = text;
    msg.appendChild(bubble);

    if (concepts && concepts.length) {
      const block = document.createElement("div");
      block.className = "concepts-block";
      const t = document.createElement("div");
      t.className = "concepts-title";
      t.textContent = "Important Concepts";
      block.appendChild(t);
      const list = document.createElement("div");
      list.className = "concepts-list";
      concepts.forEach((c) => {
        const chip = document.createElement("span");
        chip.className = "concept-chip";
        chip.textContent = c;
        list.appendChild(chip);
      });
      block.appendChild(list);
      msg.appendChild(block);
    }

    if (sources && sources.length) {
      const row = document.createElement("div");
      row.className = "sources-row";
      sources.forEach((s) => {
        const tag = document.createElement("span");
        tag.className = "source-tag";
        tag.textContent = s;
        row.appendChild(tag);
      });
      msg.appendChild(row);
    }

    log.appendChild(msg);
    log.scrollTop = log.scrollHeight;
  }

  function addSearchResults(results) {
    const msg = document.createElement("div");
    msg.className = "msg bot";

    if (!results.length) {
      const bubble = document.createElement("div");
      bubble.className = "bubble-text";
      bubble.textContent = "No matching materials found for that search.";
      msg.appendChild(bubble);
      log.appendChild(msg);
      log.scrollTop = log.scrollHeight;
      return;
    }

    const wrapEl = document.createElement("div");
    wrapEl.className = "search-results";
    results.forEach((r) => {
      const card = document.createElement("div");
      card.className = "search-result-card";
      const src = document.createElement("div");
      src.className = "search-result-source";
      src.textContent = r.title;
      const snippet = document.createElement("div");
      snippet.className = "search-result-snippet";
      snippet.textContent = r.snippet;
      card.appendChild(src);
      card.appendChild(snippet);
      wrapEl.appendChild(card);
    });
    msg.appendChild(wrapEl);
    log.appendChild(msg);
    log.scrollTop = log.scrollHeight;
  }

  function addTopics(topics, sourceType, courseLabel) {
    const msg = document.createElement("div");
    msg.className = "msg bot";

    if (!topics.length) {
      const bubble = document.createElement("div");
      bubble.className = "bubble-text";
      bubble.textContent = "No materials are indexed for this course yet, so there's nothing to summarize.";
      msg.appendChild(bubble);
      log.appendChild(msg);
      log.scrollTop = log.scrollHeight;
      return;
    }

    const block = document.createElement("div");
    block.className = "concepts-block";
    const t = document.createElement("div");
    t.className = "concepts-title";
    t.textContent = `Important Topics â€” ${courseLabel}`;
    block.appendChild(t);
    const list = document.createElement("div");
    list.className = "concepts-list";
    topics.forEach((c) => {
      const chip = document.createElement("span");
      chip.className = "concept-chip";
      chip.textContent = c;
      list.appendChild(chip);
    });
    block.appendChild(list);
    msg.appendChild(block);

    if (sourceType === "document_titles_fallback") {
      const note = document.createElement("div");
      note.className = "bubble-text";
      note.style.fontSize = "0.76rem";
      note.style.opacity = "0.75";
      note.textContent = "(Local LLM unavailable â€” showing document titles instead of a synthesized summary.)";
      msg.appendChild(note);
    }

    log.appendChild(msg);
    log.scrollTop = log.scrollHeight;
  }

  function addTyping() {
    const msg = document.createElement("div");
    msg.className = "msg bot";
    msg.id = "typing-el";
    msg.innerHTML = `<div class="bubble-text typing"><span></span><span></span><span></span></div>`;
    log.appendChild(msg);
    log.scrollTop = log.scrollHeight;
  }
  function removeTyping() {
    const el = root.getElementById("typing-el");
    if (el) el.remove();
  }

  async function checkHealth() {
    try {
      const res = await fetch(`${API_BASE}/`);
      statusDot.classList.toggle("off", !res.ok);
    } catch (e) {
      statusDot.classList.add("off");
    }
  }

  async function ask(question) {
    if (!courseId) return;
    addMessage("user", { text: question });
    setComposerEnabled(false);
    addTyping();
    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, course_id: courseId, mode: currentMode }),
      });
      const data = await res.json();
      removeTyping();
      if (res.ok) {
        const badge = data.source_type === "general_fallback"
          ? { kind: "general", label: "General knowledge â€” not from course material" }
          : null;
        addMessage("bot", {
          text: data.explanation,
          concepts: data.concepts,
          sources: data.sources,
          badge,
        });
        if (data.sources && data.sources.length) {
          highlightMaterials(data.sources);
        }
      } else {
        addMessage("bot", { text: data.detail || "Something went wrong. Try again." });
      }
    } catch (e) {
      removeTyping();
      addMessage("bot", { text: "Can't reach the course assistant right now. Try again shortly." });
    } finally {
      setComposerEnabled(true);
    }
  }

  async function runSearch(query) {
    if (!courseId) return;
    addMessage("user", { text: query });
    setComposerEnabled(false);
    addTyping();
    try {
      const url = `${API_BASE}/search-materials?course_id=${encodeURIComponent(courseId)}&query=${encodeURIComponent(query)}`;
      const res = await fetch(url);
      const data = await res.json();
      removeTyping();
      if (res.ok) {
        addSearchResults(data.results || []);
        const uniqueSources = [...new Set((data.results || []).map((r) => r.source))];
        if (uniqueSources.length) highlightMaterials(uniqueSources);
      } else {
        addMessage("bot", { text: data.detail || "Search failed. Try again." });
      }
    } catch (e) {
      removeTyping();
      addMessage("bot", { text: "Can't reach the course assistant right now. Try again shortly." });
    } finally {
      setComposerEnabled(true);
    }
  }

  async function loadTopics() {
    if (!courseId) return;
    topicsBtn.disabled = true;
    addTyping();
    try {
      const res = await fetch(`${API_BASE}/important-topics?course_id=${encodeURIComponent(courseId)}`);
      const data = await res.json();
      removeTyping();
      if (res.ok) {
        addTopics(data.topics || [], data.source_type, courseName || courseId);
      } else {
        addMessage("bot", { text: data.detail || "Couldn't load important topics." });
      }
    } catch (e) {
      removeTyping();
      addMessage("bot", { text: "Can't reach the course assistant right now. Try again shortly." });
    } finally {
      topicsBtn.disabled = false;
    }
  }
  topicsBtn.addEventListener("click", loadTopics);

  composer.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) return;
    input.value = "";
    if (currentTab === "search") {
      runSearch(q);
    } else {
      ask(q);
    }
  });

  function activateCourse(id, name) {
    courseId = id;
    courseName = name || id;
    courseNameLabel.textContent = courseName;
    resetQuizState();
    setTab("ask");
    currentMode = "normal";
    modeButtons.forEach((b) => b.classList.toggle("active", b.dataset.mode === "normal"));
    setComposerEnabled(true);
    if (!greeted) {
      greeted = true;
      addMessage("bot", { text: `Hi! Ask me anything about ${courseName}'s materials.` });
    }
  }

  async function initCoursePicker() {
    coursePicker.style.display = "flex";
    try {
      const res = await fetch(`${API_BASE}/courses`);
      const data = await res.json();
      const courses = data.courses || [];
      courseSelect.innerHTML = courses.length
        ? `<option value="">Choose a courseâ€¦</option>` +
          courses.map((c) => `<option value="${c.id}">${c.name} (${c.id})</option>`).join("")
        : `<option value="">No courses available</option>`;
    } catch (e) {
      courseSelect.innerHTML = `<option value="">Couldn't load courses</option>`;
    }
  }

  courseSelect.addEventListener("change", () => {
    const opt = courseSelect.selectedOptions[0];
    if (!opt || !opt.value) return;
    activateCourse(opt.value, opt.textContent.replace(/\s*\(.+\)$/, ""));
  });

  async function resolveCourseName(id) {
    try {
      const res = await fetch(`${API_BASE}/courses`);
      const data = await res.json();
      const match = (data.courses || []).find((c) => c.id === id);
      return match ? match.name : id;
    } catch (e) {
      return id;
    }
  }

  bubbleBtn.addEventListener("click", async () => {
    opened = !opened;
    panel.classList.toggle("open", opened);
    if (opened) {
      checkHealth();
      if (courseId) {
        // Fixed-course mode: resolve display name then greet.
        if (!greeted) {
          const name = await resolveCourseName(courseId);
          activateCourse(courseId, name);
        }
      } else if (EXTERNAL_COURSE_CONTROL) {
        // Host page owns course selection (e.g. a "Select Registered Course"
        // dropdown). Don't show our own picker â€” just prompt to use theirs.
        if (!greeted) {
          greeted = true;
          addMessage("bot", { text: "Select a course above to start asking questions." });
        }
      } else {
        // No courseId configured and no external selector: act as a
        // portal-wide assistant, let the student pick from our own dropdown.
        initCoursePicker();
      }
      if (!input.disabled) input.focus();
    }
  });
  closeBtn.addEventListener("click", () => {
    opened = false;
    panel.classList.remove("open");
  });

  // ---------- Public API for host pages with their own course selector ----------
  // (e.g. a "Select Registered Course" dropdown like a real student portal).
  // Calling this switches the assistant's context live, no page reload needed.
  window.CourseAssistant = {
    setCourse(id, name) {
      if (!id) {
        courseId = null;
        courseName = null;
        courseNameLabel.textContent = "";
        resetQuizState();
        setTab("ask");
        currentMode = "normal";
        modeButtons.forEach((b) => b.classList.toggle("active", b.dataset.mode === "normal"));
        setComposerEnabled(false);
        log.innerHTML = "";
        greeted = false;
        addMessage("bot", { text: "Select a course above to start asking questions." });
        return;
      }
      courseId = id;
      courseName = name || id;
      courseNameLabel.textContent = courseName;
      coursePicker.style.display = "none";
      resetQuizState();
      setTab("ask");
      currentMode = "normal";
      modeButtons.forEach((b) => b.classList.toggle("active", b.dataset.mode === "normal"));
      log.innerHTML = "";
      greeted = false;
      setComposerEnabled(true);
      addMessage("bot", { text: `Hi! Ask me anything about ${courseName}'s materials.` });
      greeted = true;
      if (opened) checkHealth();
    },
  };
})();

