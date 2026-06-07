/**
 * CodEdu — Client Application
 * ============================
 * Vanilla JS with zero innerHTML usage for user data.
 *
 * Modules:
 *   Sanitizer  — XSS prevention helpers (textContent only, DOM builders)
 *   WSClient   — WebSocket manager with exponential backoff reconnection
 *   GameUI     — Gamification display (streak, points, leaderboard)
 *   Editor     — Code editor enhancements (line numbers, tab handling)
 *   App        — Main application controller
 */

"use strict";

const Sanitizer = (() => {
    const ENTITY_MAP = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#x27;",
        "/": "&#x2F;",
    };

    /**
     * Escape HTML entities in a string.
     * Used ONLY for safe static content — never for user code/errors.
     */
    function escapeHTML(str) {
        if (typeof str !== "string") str = String(str);
        return str.replace(/[&<>"'/]/g, (c) => ENTITY_MAP[c] || c);
    }

    /**
     * Safely set text content of an element. NEVER uses innerHTML.
     */
    function safeText(element, text) {
        if (!element) return;
        element.textContent = String(text);
    }

    /**
     * Build a DOM element programmatically. Zero innerHTML.
     * @param {string} tag - HTML tag name
     * @param {Object} attrs - Attributes to set (class, id, etc.)
     * @param {Array} children - Child elements or text strings
     * @returns {HTMLElement}
     */
    function buildEl(tag, attrs, children) {
        const el = document.createElement(tag);

        if (attrs) {
            for (const [key, value] of Object.entries(attrs)) {
                if (key === "class") {
                    el.className = value;
                } else if (key === "style" && typeof value === "object") {
                    Object.assign(el.style, value);
                } else if (key.startsWith("on")) {
                    el.addEventListener(key.slice(2).toLowerCase(), value);
                } else {
                    el.setAttribute(key, value);
                }
            }
        }

        if (children) {
            for (const child of children) {
                if (typeof child === "string" || typeof child === "number") {
                    el.appendChild(document.createTextNode(String(child)));
                } else if (child instanceof Node) {
                    el.appendChild(child);
                }
            }
        }

        return el;
    }

    /**
     * Safe markdown-to-DOM converter.
     * Creates DOM nodes — never produces HTML strings.
     * Supports: headers, bold, italic, code blocks, links, line breaks.
     */
    function renderMarkdown(mdText) {
        const container = document.createDocumentFragment();
        if (!mdText) return container;

        const lines = mdText.split("\n");
        let inCodeBlock = false;
        let codeLines = [];

        for (const line of lines) {
            // Code block fence
            if (line.trim().startsWith("```")) {
                if (inCodeBlock) {
                    // End code block
                    const pre = buildEl("pre", {}, [
                        buildEl("code", {}, [codeLines.join("\n")]),
                    ]);
                    container.appendChild(pre);
                    codeLines = [];
                    inCodeBlock = false;
                } else {
                    inCodeBlock = true;
                }
                continue;
            }

            if (inCodeBlock) {
                codeLines.push(line);
                continue;
            }

            // Headers
            const h2Match = line.match(/^##\s+(.+)$/);
            if (h2Match) {
                container.appendChild(buildEl("h3", {}, [h2Match[1]]));
                continue;
            }

            const h1Match = line.match(/^#\s+(.+)$/);
            if (h1Match) {
                container.appendChild(buildEl("h2", {}, [h1Match[1]]));
                continue;
            }

            // Empty line = paragraph break
            if (line.trim() === "") {
                container.appendChild(buildEl("br", {}, []));
                continue;
            }

            // Regular text — parse inline formatting
            const p = buildEl("p", {}, []);
            _parseInline(line, p);
            container.appendChild(p);
        }

        // Close unclosed code block
        if (inCodeBlock && codeLines.length > 0) {
            const pre = buildEl("pre", {}, [
                buildEl("code", {}, [codeLines.join("\n")]),
            ]);
            container.appendChild(pre);
        }

        return container;
    }

    /**
     * Parse inline markdown (bold, italic, code, links) into DOM nodes.
     */
    function _parseInline(text, parent) {
        // Regex to match inline patterns
        const pattern =
            /(\*\*(.+?)\*\*)|(`(.+?)`)|(\[([^\]]+)\]\(([^)]+)\))/g;
        let lastIndex = 0;
        let match;

        while ((match = pattern.exec(text)) !== null) {
            // Append text before this match
            if (match.index > lastIndex) {
                parent.appendChild(
                    document.createTextNode(text.slice(lastIndex, match.index))
                );
            }

            if (match[1]) {
                // Bold: **text**
                parent.appendChild(buildEl("strong", {}, [match[2]]));
            } else if (match[3]) {
                // Inline code: `code`
                parent.appendChild(buildEl("code", {}, [match[4]]));
            } else if (match[5]) {
                // Link: [text](url)
                parent.appendChild(
                    buildEl(
                        "a",
                        { href: escapeHTML(match[7]), target: "_blank", rel: "noopener noreferrer" },
                        [match[6]]
                    )
                );
            }

            lastIndex = match.index + match[0].length;
        }

        // Append remaining text
        if (lastIndex < text.length) {
            parent.appendChild(
                document.createTextNode(text.slice(lastIndex))
            );
        }
    }

    return { escapeHTML, safeText, buildEl, renderMarkdown };
})();

const WSClient = (() => {
    let ws = null;
    let reconnectAttempts = 0;
    let reconnectTimer = null;
    let heartbeatTimer = null;
    let intentionalClose = false;

    const MAX_RECONNECT_ATTEMPTS = 10;
    const BASE_DELAY = 1000; // 1 second
    const MAX_DELAY = 16000; // 16 seconds
    const HEARTBEAT_INTERVAL = 25000; // 25 seconds (under server's 30s)

    // Event listeners by message type
    const listeners = {};
    // Offline message queue
    const messageQueue = [];

    /**
     * Register a listener for a specific message type.
     */
    function on(type, callback) {
        if (!listeners[type]) listeners[type] = [];
        listeners[type].push(callback);
    }

    /**
     * Emit to all listeners for a message type.
     */
    function _emit(type, data) {
        const cbs = listeners[type];
        if (cbs) {
            for (const cb of cbs) {
                try {
                    cb(data);
                } catch (e) {
                    console.error(`[WSClient] Listener error for '${type}':`, e);
                }
            }
        }
    }

    /**
     * Connect to WebSocket server.
     */
    function connect() {
        if (ws && ws.readyState === WebSocket.OPEN) return;

        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        intentionalClose = false;

        try {
            ws = new WebSocket(wsUrl);
        } catch (e) {
            console.error("[WSClient] WebSocket creation failed:", e);
            _scheduleReconnect();
            return;
        }

        ws.onopen = () => {
            console.log("[WSClient] Connected");
            reconnectAttempts = 0;
            _emit("_connection", { status: "connected" });

            // Try to reconnect existing session
            const savedToken = sessionStorage.getItem("codedu_session_token");
            if (savedToken) {
                send({ type: "reconnect", session_token: savedToken });
            }

            // Flush queued messages
            while (messageQueue.length > 0) {
                const msg = messageQueue.shift();
                _sendRaw(msg);
            }

            // Start heartbeat
            _startHeartbeat();
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const type = data.type;

                // Handle session token persistence
                if (type === "auth_ok" && data.session_token) {
                    sessionStorage.setItem(
                        "codedu_session_token",
                        data.session_token
                    );
                }

                // Handle kick — clear session and don't reconnect
                if (type === "kick") {
                    sessionStorage.removeItem("codedu_session_token");
                    intentionalClose = true;
                }

                _emit(type, data);
            } catch (e) {
                console.error("[WSClient] Message parse error:", e);
            }
        };

        ws.onclose = (event) => {
            console.log(`[WSClient] Disconnected (code: ${event.code})`);
            _stopHeartbeat();
            _emit("_connection", { status: "disconnected", code: event.code });

            if (!intentionalClose) {
                _scheduleReconnect();
            }
        };

        ws.onerror = (error) => {
            console.error("[WSClient] Error:", error);
            _emit("_connection", { status: "error" });
        };
    }

    /**
     * Send a JSON message. Queues if not connected.
     */
    function send(data) {
        const msg = JSON.stringify(data);

        if (ws && ws.readyState === WebSocket.OPEN) {
            _sendRaw(msg);
        } else {
            // Queue for when connection is restored
            messageQueue.push(msg);
        }
    }

    function _sendRaw(msg) {
        try {
            ws.send(msg);
        } catch (e) {
            console.error("[WSClient] Send error:", e);
            messageQueue.push(msg);
        }
    }

    /**
     * Authenticate with the server.
     */
    function authenticate(username) {
        send({ type: "auth", username: username });
    }

    /**
     * Intentionally disconnect.
     */
    function disconnect() {
        intentionalClose = true;
        _stopHeartbeat();
        if (ws) ws.close(1000, "User disconnect");
    }

    /**
     * Exponential backoff reconnection.
     */
    function _scheduleReconnect() {
        if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            console.log("[WSClient] Max reconnect attempts reached");
            _emit("_connection", { status: "failed" });
            return;
        }

        const delay = Math.min(
            BASE_DELAY * Math.pow(2, reconnectAttempts),
            MAX_DELAY
        );
        reconnectAttempts++;

        console.log(
            `[WSClient] Reconnecting in ${delay}ms (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`
        );
        _emit("_connection", {
            status: "reconnecting",
            attempt: reconnectAttempts,
            delay: delay,
        });

        reconnectTimer = setTimeout(() => {
            connect();
        }, delay);
    }

    /**
     * Application-level heartbeat (separate from WS protocol PING).
     */
    function _startHeartbeat() {
        _stopHeartbeat();
        heartbeatTimer = setInterval(() => {
            send({ type: "ping" });
        }, HEARTBEAT_INTERVAL);
    }

    function _stopHeartbeat() {
        if (heartbeatTimer) {
            clearInterval(heartbeatTimer);
            heartbeatTimer = null;
        }
    }

    /**
     * Check if currently connected.
     */
    function isConnected() {
        return ws && ws.readyState === WebSocket.OPEN;
    }

    return { connect, send, authenticate, disconnect, on, isConnected };
})();

const GameUI = (() => {
    function updateStreak(data) {
        const valueEl = document.getElementById("streak-value");
        if (valueEl) Sanitizer.safeText(valueEl, data.current_streak || 0);

        if (data.streak_bonus) {
            triggerStreakAnimation(data);
        }
    }

    function updatePoints(data) {
        const pointsEl = document.getElementById("points-value");
        if (pointsEl) {
            Sanitizer.safeText(pointsEl, data.total_points || 0);
            // Animate points bump
            pointsEl.parentElement.classList.add("bump");
            setTimeout(() => pointsEl.parentElement.classList.remove("bump"), 400);
        }
    }

    function triggerStreakAnimation(data) {
        const indicator = document.getElementById("streak-counter");
        if (indicator) {
            indicator.classList.add("bump");
            setTimeout(() => indicator.classList.remove("bump"), 400);
        }

        // Build modal content safely
        const modal = document.getElementById("streak-modal");
        const detailsEl = document.getElementById("streak-modal-details");

        if (detailsEl) {
            // Clear previous
            detailsEl.textContent = "";

            const text = `+${data.points_earned || 0} points (${data.multiplier || 1.0}x multiplier)`;
            detailsEl.appendChild(document.createTextNode(text));
        }

        if (modal) modal.classList.add("show");
    }

    function closeStreakModal() {
        const modal = document.getElementById("streak-modal");
        if (modal) modal.classList.remove("show");
    }

    function updateLeaderboard(data) {
        const container = document.getElementById("leaderboard-list");
        if (!container) return;

        // Clear safely
        container.textContent = "";

        const rankings = data.rankings || [];

        if (rankings.length === 0) {
            container.appendChild(
                Sanitizer.buildEl("div", { class: "empty-state" }, [
                    "No rankings yet. Be the first to solve a problem!",
                ])
            );
            return;
        }

        rankings.forEach((entry, idx) => {
            const medal = idx === 0 ? "🥇" : idx === 1 ? "🥈" : idx === 2 ? "🥉" : `#${idx + 1}`;

            const row = Sanitizer.buildEl("div", { class: "leaderboard-row" }, [
                Sanitizer.buildEl("span", { class: "lb-rank" }, [medal]),
                Sanitizer.buildEl("span", { class: "lb-name" }, [entry.username || "Anonymous"]),
                Sanitizer.buildEl("span", { class: "lb-points" }, [
                    String(entry.points || 0) + " pts",
                ]),
                Sanitizer.buildEl("span", { class: "lb-streak" }, [
                    "🔥 " + String(entry.streak || 0),
                ]),
                Sanitizer.buildEl("span", { class: "lb-solved" }, [
                    String(entry.solved_count || 0) + " solved",
                ]),
            ]);

            container.appendChild(row);
        });
    }

    function updateConnectionStatus(status) {
        const indicator = document.getElementById("connection-status");
        if (!indicator) return;

        indicator.className = "connection-dot " + status;

        const tooltip = document.getElementById("connection-tooltip");
        if (tooltip) {
            const messages = {
                connected: "Connected",
                disconnected: "Disconnected",
                reconnecting: "Reconnecting...",
                error: "Connection error",
                failed: "Connection failed",
            };
            Sanitizer.safeText(tooltip, messages[status] || status);
        }
    }

    return {
        updateStreak,
        updatePoints,
        triggerStreakAnimation,
        closeStreakModal,
        updateLeaderboard,
        updateConnectionStatus,
    };
})();

const Editor = (() => {
    let _editor = null;
    let _lineNumbers = null;

    function init() {
        _editor = document.getElementById("code-editor");
        _lineNumbers = document.getElementById("line-numbers");

        if (!_editor || !_lineNumbers) return;

        _editor.addEventListener("input", _updateLineNumbers);
        _editor.addEventListener("scroll", () => {
            _lineNumbers.scrollTop = _editor.scrollTop;
        });

        // Tab key → 4 spaces
        _editor.addEventListener("keydown", (e) => {
            if (e.key === "Tab") {
                e.preventDefault();
                const start = _editor.selectionStart;
                const end = _editor.selectionEnd;
                _editor.value =
                    _editor.value.substring(0, start) +
                    "    " +
                    _editor.value.substring(end);
                _editor.selectionStart = _editor.selectionEnd = start + 4;
                _updateLineNumbers();
            }
        });

        _updateLineNumbers();
    }

    function _updateLineNumbers() {
        if (!_editor || !_lineNumbers) return;
        const count = _editor.value.split("\n").length;
        const nums = [];
        for (let i = 1; i <= count; i++) nums.push(i);
        // Safe: only numbers, using textContent-equivalent via join
        _lineNumbers.textContent = "";
        nums.forEach((n, idx) => {
            if (idx > 0) _lineNumbers.appendChild(document.createElement("br"));
            _lineNumbers.appendChild(document.createTextNode(String(n)));
        });
    }

    function getValue() {
        return _editor ? _editor.value : "";
    }

    function setValue(code) {
        if (_editor) {
            _editor.value = code;
            _updateLineNumbers();
        }
    }

    return { init, getValue, setValue };
})();

const Terminal = (() => {
    let _output = null;

    function init() {
        _output = document.querySelector(".terminal-output");
    }

    /**
     * Append a line to terminal using textContent (XSS-safe).
     */
    function appendLine(text) {
        if (!_output) return;

        const line = document.createElement("div");
        line.className = "terminal-line";

        const prefix = document.createTextNode("> ");
        const content = document.createTextNode(String(text));

        line.appendChild(prefix);
        line.appendChild(content);
        _output.appendChild(line);

        _output.scrollTop = _output.scrollHeight;
    }

    /**
     * Append a result line with status coloring.
     */
    function appendResult(text, status) {
        if (!_output) return;

        const line = document.createElement("div");
        line.className = "terminal-line terminal-" + (status || "info");

        const prefix = document.createTextNode("> ");
        const content = document.createTextNode(String(text));

        line.appendChild(prefix);
        line.appendChild(content);
        _output.appendChild(line);

        _output.scrollTop = _output.scrollHeight;
    }

    function clear() {
        if (_output) _output.textContent = "";
    }

    return { init, appendLine, appendResult, clear };
})();

const App = (() => {
    let currentProblemId = null;
    let currentUsername = null;

    function init() {
        Editor.init();
        Terminal.init();

        Terminal.appendLine("CodEdu v2.0 — Initializing...");

        WSClient.on("_connection", (data) => {
            GameUI.updateConnectionStatus(data.status);

            if (data.status === "connected") {
                Terminal.appendLine("Connected to server");
            } else if (data.status === "disconnected") {
                Terminal.appendLine("Disconnected from server");
            } else if (data.status === "reconnecting") {
                Terminal.appendLine(
                    `Reconnecting (attempt ${data.attempt}, delay ${data.delay}ms)...`
                );
            } else if (data.status === "failed") {
                Terminal.appendResult(
                    "Connection failed after max retries. Refresh the page.",
                    "error"
                );
            }
        });

        WSClient.on("auth_ok", (data) => {
            currentUsername = data.user ? data.user.username : null;
            Terminal.appendLine(`Authenticated as: ${currentUsername}`);

            if (data.user) {
                GameUI.updateStreak({ current_streak: data.user.streak });
                GameUI.updatePoints({ total_points: data.user.points });
            }

            if (data.reconnected) {
                Terminal.appendLine("Session resumed successfully");
            }

            // Fetch leaderboard on auth
            WSClient.send({ type: "get_leaderboard" });
        });

        WSClient.on("submission_result", (data) => {
            if (data.status === "Accepted") {
                Terminal.appendResult("✓ Accepted — All test cases passed!", "success");
                if (data.avg_time_ms !== undefined) {
                    Terminal.appendLine(
                        `Runtime: ${data.avg_time_ms}ms | Memory: ${data.max_memory_kb}KB`
                    );
                }
            } else if (data.status === "Blocked") {
                Terminal.appendResult("✗ Blocked — Security violation detected", "error");
                if (data.violations) {
                    data.violations.forEach((v) => Terminal.appendResult(v, "error"));
                }
            } else {
                Terminal.appendResult(`✗ ${data.status}`, "error");
                if (data.details && data.details.length > 0) {
                    const failed = data.details.find((d) => d.status !== "Passed");
                    if (failed) {
                        Terminal.appendLine(
                            `Failed at test case ${failed.test_case}: ${failed.error || "Wrong Answer"}`
                        );
                        if (failed.expected) {
                            Terminal.appendLine(`Expected: ${failed.expected}`);
                            Terminal.appendLine(`Actual:   ${failed.actual}`);
                        }
                    }
                }
            }
        });

        WSClient.on("streak_update", (data) => {
            GameUI.updateStreak(data);
            GameUI.updatePoints(data);
        });

        WSClient.on("leaderboard", (data) => {
            GameUI.updateLeaderboard(data);
        });

        WSClient.on("error", (data) => {
            Terminal.appendResult(`Server: ${data.message}`, "error");

            // If session expired, prompt re-auth
            if (data.code === "SESSION_EXPIRED") {
                _promptAuth();
            }
        });

        WSClient.on("kick", (data) => {
            Terminal.appendResult(
                `Kicked: ${data.reason || "Unknown reason"}`,
                "error"
            );
        });

        const runBtns = document.querySelectorAll(".run-btn");
        runBtns.forEach((btn) => {
            btn.addEventListener("click", _handleSubmit);
        });

        _fetchQuestions();
        WSClient.connect();
        _promptAuth();
    }

    function _promptAuth() {
        // Check if already authed in this session
        const savedToken = sessionStorage.getItem("codedu_session_token");
        if (savedToken) return; // Will reconnect via WS

        // Simple inline prompt (could be replaced with modal)
        const username = "user1"; // Default for demo
        WSClient.authenticate(username);
    }

    function switchView(viewId) {
        const views = document.querySelectorAll(".view");
        views.forEach((v) => v.classList.remove("active-view"));

        const navLinks = document.querySelectorAll(".nav-links a");
        navLinks.forEach((link) => link.classList.remove("active"));

        const target = document.getElementById("view-" + viewId);
        if (target) target.classList.add("active-view");

        const activeLink = Array.from(navLinks).find(
            (link) => link.getAttribute("data-view") === viewId
        );
        if (activeLink) activeLink.classList.add("active");

        // Refresh leaderboard when viewing it
        if (viewId === "leaderboard") {
            WSClient.send({ type: "get_leaderboard" });
        }
    }

    async function openProblem(id) {
        currentProblemId = id;
        switchView("workspace");

        try {
            const response = await fetch(`/api/questions/${id}`);
            if (response.ok) {
                const data = await response.json();

                // Set title safely
                const titleEl = document.getElementById("workspace-title");
                Sanitizer.safeText(titleEl, data.title);

                // Set difficulty badge
                const diffEl = document.getElementById("workspace-difficulty");
                Sanitizer.safeText(diffEl, data.difficulty);
                diffEl.className = `difficulty ${(data.difficulty || "").toLowerCase()}`;
                diffEl.style.display = "inline-block";

                // Render description using safe markdown parser
                const contentEl = document.getElementById("workspace-content");
                contentEl.textContent = ""; // Clear safely
                if (data.description) {
                    const rendered = Sanitizer.renderMarkdown(data.description);
                    contentEl.appendChild(rendered);
                }
            }
        } catch (e) {
            console.error("Failed to load problem details:", e);
            Terminal.appendResult("Failed to load problem details", "error");
        }
    }

    async function _fetchQuestions() {
        try {
            const response = await fetch("/api/questions");
            if (response.ok) {
                const data = await response.json();
                const container = document.getElementById("problem-list-container");
                if (!container) return;

                container.textContent = ""; // Clear safely

                data.forEach((q, index) => {
                    const card = Sanitizer.buildEl(
                        "div",
                        {
                            class: "problem-card",
                            onClick: () => openProblem(q.id),
                        },
                        [
                            Sanitizer.buildEl("div", { class: "problem-card-left" }, [
                                Sanitizer.buildEl("div", { class: "status unsolved" }, [
                                    "○",
                                ]),
                                Sanitizer.buildEl("div", { class: "details" }, [
                                    Sanitizer.buildEl("h3", {}, [
                                        `${index + 1}. ${q.title}`,
                                    ]),
                                    Sanitizer.buildEl(
                                        "span",
                                        {
                                            class: `difficulty ${(q.difficulty || "").toLowerCase()}`,
                                        },
                                        [q.difficulty]
                                    ),
                                ]),
                            ]),
                            Sanitizer.buildEl(
                                "button",
                                { class: "solve-btn" },
                                ["Solve"]
                            ),
                        ]
                    );
                    container.appendChild(card);
                });
            }
        } catch (e) {
            console.error("Failed to load questions:", e);
            const container = document.getElementById("problem-list-container");
            if (container) {
                container.textContent = "";
                container.appendChild(
                    Sanitizer.buildEl(
                        "div",
                        { class: "empty-state", style: { color: "#f87171" } },
                        ["Failed to load questions. Is the server running?"]
                    )
                );
            }
        }
    }

    function _handleSubmit() {
        const code = Editor.getValue();
        if (!code.trim()) {
            Terminal.appendResult("No code to submit", "error");
            return;
        }

        if (!currentProblemId) {
            Terminal.appendResult(
                "Select a problem first before submitting",
                "error"
            );
            return;
        }

        Terminal.appendLine(`Submitting solution for: ${currentProblemId}...`);

        // Use WebSocket if connected, fallback to REST
        if (WSClient.isConnected()) {
            WSClient.send({
                type: "submit_code",
                problem_id: currentProblemId,
                code: code,
            });
        } else {
            _submitViaREST(code);
        }
    }

    async function _submitViaREST(code) {
        try {
            const response = await fetch("/api/submit", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    problem_id: currentProblemId,
                    code: code,
                }),
            });

            const result = await response.json();

            // Reuse the same display logic
            WSClient.on("submission_result", () => {}); // No-op, handled inline
            if (result.status === "Accepted") {
                Terminal.appendResult(
                    "✓ Accepted — All test cases passed!",
                    "success"
                );
                if (result.avg_time_ms !== undefined) {
                    Terminal.appendLine(
                        `Runtime: ${result.avg_time_ms}ms | Memory: ${result.max_memory_kb}KB`
                    );
                }
                if (result.user_stats) {
                    GameUI.updateStreak({
                        current_streak: result.user_stats.current_streak,
                        streak_bonus: result.user_stats.streak_bonus,
                        points_earned: result.user_stats.points_earned,
                    });
                    GameUI.updatePoints({
                        total_points: result.user_stats.total_points,
                    });
                }
            } else if (result.status === "Blocked") {
                Terminal.appendResult(
                    "✗ Blocked — Security violation detected",
                    "error"
                );
                if (result.violations) {
                    result.violations.forEach((v) =>
                        Terminal.appendResult(v, "error")
                    );
                }
            } else {
                Terminal.appendResult(`✗ ${result.status}`, "error");
            }
        } catch (e) {
            Terminal.appendResult("Connection error! Failed to submit.", "error");
        }
    }

    // Expose for HTML onclick handlers
    return { init, switchView, openProblem, closeStreakModal: GameUI.closeStreakModal };
})();

document.addEventListener("DOMContentLoaded", () => App.init());

// eslint-disable-next-line no-unused-vars
function switchView(viewId) {
    App.switchView(viewId);
}

function closeStreakModal() {
    App.closeStreakModal();
}
