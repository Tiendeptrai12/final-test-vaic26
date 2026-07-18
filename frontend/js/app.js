/*
 * Chat framework wiring for the Điện Máy Xanh AI Advisor.
 * Scope: boilerplate + framework only. Talks to POST /api/chat and renders the
 * result. Visual design/detailing is owned by the frontend teammate.
 *
 * Backend contract (antigravity/views.py -> POST /api/chat):
 *   request : { query: string }
 *   response: current mock path -> { response, source_nodes, safety_checked }
 *             btc advise() path -> { status, profile, result|questions, ... }
 * Renderer below handles both shapes defensively so the UI survives either path.
 */
(function () {
  "use strict";

  var API = "/api/chat";

  var chat = document.getElementById("chat");
  var form = document.getElementById("composer");
  var input = document.getElementById("input");
  var send = document.getElementById("send");
  var status = document.getElementById("status");
  var examples = document.getElementById("examples");

  function setStatus(text, state) {
    status.textContent = text;
    status.dataset.state = state || "idle";
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text; // textContent => no HTML injection
    return node;
  }

  function addMessage(text, who) {
    var wrap = el("div", "msg msg--" + who);
    wrap.appendChild(el("p", "msg__text", text));
    chat.appendChild(wrap);
    chat.scrollTop = chat.scrollHeight;
    return wrap;
  }

  // Render product cards ONLY from backend data — never fabricate specs/prices here.
  function addCards(items) {
    if (!items || !items.length) return;
    var grid = el("div", "cards");
    items.forEach(function (it) {
      var card = el("div", "card");
      var title = it.brand || it.name || it.product_id || "Sản phẩm";
      card.appendChild(el("strong", null, title));
      var price = it.effective_price != null ? it.effective_price : it.price;
      if (price != null) card.appendChild(el("div", null, "Giá: " + price));
      var reasons = it.reasons || [];
      reasons.forEach(function (r) { card.appendChild(el("div", null, "• " + r)); });
      grid.appendChild(card);
    });
    chat.appendChild(grid);
    chat.scrollTop = chat.scrollHeight;
  }

  // Normalize either backend shape into { text, items } for rendering.
  function render(data) {
    if (data && data.status === "need_info") {
      var qs = (data.questions || []).join(" ");
      addMessage(qs || "Bạn bổ sung thêm thông tin giúp mình nhé.", "bot");
      return;
    }
    if (data && data.result && data.result.items) {        // btc advise() path
      addMessage("Đây là Top gợi ý phù hợp:", "bot");
      addCards(data.result.items);
      return;
    }
    if (data && data.response) {                            // current mock path
      addMessage(data.response, "bot");
      addCards(data.source_nodes);
      return;
    }
    addMessage("Xin lỗi, mình chưa có phản hồi phù hợp.", "bot");
  }

  function sendQuery(query) {
    addMessage(query, "user");
    setStatus("Đang xử lý…", "loading");
    send.disabled = true;

    fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query })
    })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) { render(data); setStatus("Sẵn sàng", "idle"); })
      .catch(function () {
        addMessage("Có lỗi kết nối. Bạn thử lại giúp mình nhé.", "bot");
        setStatus("Lỗi", "error");
      })
      .finally(function () { send.disabled = false; input.focus(); });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var q = input.value.trim();
    if (!q) return;
    input.value = "";
    sendQuery(q);
  });

  // Enter to send, Shift+Enter for newline.
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  // Example chips prefill + send.
  if (examples) {
    examples.addEventListener("click", function (e) {
      var btn = e.target.closest(".chip");
      if (!btn) return;
      sendQuery(btn.textContent.trim());
    });
  }
})();
