/* eslint-disable */
/**
 * Smart Assistant - Trợ Lý Mua Sắm Thông Thái (JS Engine Nâng Cấp Toàn Diện)
 * Bộ điều phối hội thoại thông minh tích hợp bộ trích xuất thực thể (Slot-Filling)
 * Hoàn toàn không cắt xén logic - Sẵn sàng chạy Production Mockup
 */

const MOCK_CATALOG = {
  ac: [
    {
      id: 'ac-pana-01',
      name: 'Panasonic Inverter 1 HP CU/CS-XPU9XKH-8',
      price: 11490000,
      brand: 'Panasonic',
      room_size: 'Dưới 15m²',
      noise: '19dB - siêu êm',
      inverter: true,
      stock: 12,
    },
    {
      id: 'ac-daikin-02',
      name: 'Daikin Inverter 1.5 HP FTKB35WAVMV',
      price: 13990000,
      brand: 'Daikin',
      room_size: 'Từ 15 đến 20m²',
      noise: '22dB - rất yên tĩnh',
      inverter: true,
      stock: 8,
    },
    {
      id: 'ac-casper-03',
      name: 'Casper Inverter 1 HP TC-09IS35',
      price: 5890000,
      brand: 'Casper',
      room_size: 'Dưới 15m²',
      noise: '28dB - trung bình',
      inverter: true,
      stock: 25,
    }
  ],
  fridge: [
    {
      id: 'fridge-samsung-01',
      name: 'Tủ lạnh Samsung Inverter 236 lít RT22M4032BY/SV',
      price: 6490000,
      brand: 'Samsung',
      liters: 236,
      family_size: '2 - 4 người',
      cooling: 'Chế độ đông mềm Optimal Fresh Zone tiện lợi',
      stock: 5,
    },
    {
      id: 'fridge-lg-02',
      name: 'Tủ lạnh LG Inverter 315 lít GN-D312PS',
      price: 8890000,
      brand: 'LG',
      liters: 315,
      family_size: '3 - 5 người',
      cooling: 'Hệ thống làm lạnh đa chiều Door Cooling tỏa đều',
      stock: 15,
    },
    {
      id: 'fridge-aqua-03',
      name: 'Tủ lạnh Aqua 90 lít AQR-D99FA',
      price: 2790000,
      brand: 'Aqua',
      liters: 90,
      family_size: '1 - 2 người (Sinh viên)',
      cooling: 'Làm lạnh trực tiếp bằng mạch khí cơ bản',
      stock: 4,
    }
  ],
  laptop: [
    {
      id: 'laptop-hp-01',
      name: 'HP Pavilion 14-dv2073TU (Core i5 / 8GB RAM / 512GB SSD)',
      price: 14500000,
      brand: 'HP',
      weight: '1.4kg',
      screen: '14 inch Full HD',
      stock: 9,
    },
    {
      id: 'laptop-asus-02',
      name: 'Asus Vivobook 14 OLED (Core i5 / 8GB RAM / 512GB SSD)',
      price: 15200000,
      brand: 'Asus',
      weight: '1.6kg',
      screen: '14 inch OLED siêu sắc nét',
      stock: 14,
    },
    {
      id: 'laptop-lenovo-03',
      name: 'Lenovo IdeaPad Slim 3 (Core i5 / 16GB RAM / 512GB SSD)',
      price: 12900000,
      brand: 'Lenovo',
      weight: '1.43kg',
      screen: '14 inch viền mỏng',
      stock: 22,
    }
  ]
};

const MOCK_PROMOTIONS = {
  installment_0: ['ac-pana-01', 'ac-daikin-02', 'fridge-lg-02'],
  discounts: {
    'ac-pana-01': 'Tặng combo ống đồng vật tư 800.000đ',
    'laptop-asus-02': 'Tặng chuột không dây Bluetooth chính hãng',
    'fridge-lg-02': 'Phiếu mua hàng gia dụng trị giá 300.000đ',
  }
};

const MOCK_FAQ = {
  'bảo hành': 'Dạ, sản phẩm tại Điện Máy Xanh được bảo hành chính hãng 1 đổi 1 trong vòng 30 ngày đầu nếu có lỗi phần cứng từ nhà sản xuất ạ!',
  'giao hàng': 'Dạ, hệ thống miễn phí vận chuyển lắp đặt trong bán kính 10km quanh siêu thị gần nhất ngay trong ngày ạ.',
  'trả góp': 'Dạ, hiện tại có chương trình hỗ trợ trả góp 0% lãi suất qua căn cước công dân gắn chip cực nhanh chóng, xét duyệt chỉ 5 phút ạ.'
};

const MASCOT_IMAGES = [
  'mascot-01.png',
  'mascot-02.png',
  'mascot-03.png',
  'mascot-04.png',
  'mascot-05.png',
  'mascot-06.png',
  'mascot-07.png',
  'mascot-08.png',
  'mascot-09.png',
  'mascot-10.png',
  'mascot-11.png',
  'mascot-12.png',
  'mascot-13.png',
  'mascot-14.png',
  'mascot-15.png',
  'mascot-16.png',
  'mascot-17.png'
];

let sessionState = {
  stage: 'INIT', // INIT -> PROBING -> RECOMMENDATION
  category: null, // ac, fridge, laptop
  collectedData: {
    brand: null,
    budget: null, // { modifier: 'dưới'|'trên'|'tầm', value: số }
    roomSize: null, // số m2
    familySize: null, // số thành viên
    purpose: null // học tập, gaming...
  }
};

let consumerChatSessions = [];
let activeSessionId = null;

// ==========================================
// AI BACKEND CONNECTION (/api/chat — same-origin Vercel)
// ==========================================
let currentProfile = {}; // Multi-turn NeedProfile — resent each turn

async function fetchConfig() {
  try {
    const res = await fetch('/api/health', { cache: 'no-cache' });
    if (res.ok) {
      console.log('[AI] Vercel backend sẵn sàng.');
      updateSystemStatus(true);
    } else {
      updateSystemStatus(false);
    }
  } catch (e) {
    console.warn('[AI] Backend không phản hồi, chế độ demo.', e);
    updateSystemStatus(false);
  }
}

function updateSystemStatus(online) {
  const statusEl = document.getElementById('system-status-text');
  const dotEl = document.getElementById('system-status-dot');
  if (!statusEl) return;
  if (online) {
    statusEl.textContent = 'Hệ thống Sẵn Sàng';
    if (dotEl) dotEl.classList.replace('bg-yellow-400', 'bg-green-400');
  } else {
    statusEl.textContent = 'Chế độ Demo';
    if (dotEl) dotEl.classList.replace('bg-green-400', 'bg-yellow-400');
  }
}

async function callBackendChat(query, chosenFactors) {
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        profile: currentProfile || {},
        chosen_factors: chosenFactors || []
      }),
      signal: AbortSignal.timeout(20000)
    });
    if (!res.ok) {
      console.warn('[AI] /api/chat trả về', res.status);
      return null;
    }
    const data = await res.json();
    if (data.profile) {
      currentProfile = data.profile;
      if (activeSessionId) {
        const s = consumerChatSessions.find(item => item.id === activeSessionId);
        if (s) s.profile = currentProfile;
      }
    }
    return data;
  } catch (e) {
    console.warn('[AI] Gọi backend thất bại, fallback mock.', e);
    return null;
  }
}

function renderBackendResponse(data, startTime) {
  const mode = data.mode || 'message';
  const message = data.message || '';
  const items = data.items || [];
  const explanation = data.explanation || '';
  const questions = data.questions || [];

  // Update debug panel
  const latencyEl = document.getElementById('latency-val');
  if (latencyEl) latencyEl.textContent = Math.round(performance.now() - startTime) + 'ms';
  const stageEl = document.getElementById('chat-stage');
  if (stageEl) stageEl.textContent = mode.toUpperCase();
  const catalogEl = document.getElementById('rag-catalog-status');
  if (catalogEl) catalogEl.textContent = items.length > 0 ? `${items.length} sản phẩm từ AI` : 'AI RAG';

  // Detect category from profile
  const cat = data.profile && data.profile.category;
  if (cat) {
    sessionState.category = cat;
    document.getElementById('active-category') && (document.getElementById('active-category').textContent = cat);
    const labelMap = { ac: 'Tư vấn Máy Lạnh', fridge: 'Tư vấn Tủ Lạnh', laptop: 'Tư vấn Laptop', phone: 'Tư vấn Điện Thoại' };
    if (labelMap[cat]) updateActiveSessionTitle(labelMap[cat], cat);
  }

  // --- CHOOSE FACTORS: present ≤4 consideration factors (3-layer) + A/B/C/D chips ---
  if (mode === 'choose_factors') {
    renderChooseFactors(data);
    return;
  }

  if (mode === 'need_info' || items.length === 0) {
    // Câu hỏi hỏi ngược hoặc chưa đủ thông tin
    const html = `<p class="text-sm">${message}</p>`;
    appendAssistantMessage(html);
    return;
  }

  // Decision badge (1 dominant vs 3 trade-offs)
  const decKind = data.decision && data.decision.kind;

  // Render message intro
  if (message) {
    appendAssistantMessage(`<p class="text-sm">${message}</p>`);
  }

  // Render product cards
  if (items.length > 0) {
    let cardsHtml = `<div class="grid grid-cols-1 gap-3 mt-2">`;
    items.forEach((item, idx) => {
      const name = item.name || 'Sản phẩm';
      const price = item.price_display || item.price || '';
      const url = item.url || '#';
      const reasons = (item.reasons || []).slice(0, 2);
      const reasonsHtml = reasons.map(r => `<li class="flex items-start gap-1"><i class="fa-solid fa-check text-emerald-500 mt-0.5 text-[10px] shrink-0"></i><span>${r}</span></li>`).join('');
      const brand = item.brand || '';
      // choose-factors decision tags: single = "nổi trội nhất"; tradeoff = "mạnh về <factor>"
      const badge = decKind === 'single'
        ? '<span class="px-2 py-0.5 text-[10px] font-bold bg-emerald-200/60 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200 rounded">★ Nổi trội nhất</span>'
        : `<span class="px-2 py-0.5 text-[10px] font-bold bg-amber-200/50 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200 rounded">Đề xuất ${idx + 1}</span>`;
      const winsOn = (decKind === 'tradeoff' && item._wins_on)
        ? `<span class="text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold"><i class="fa-solid fa-trophy text-[9px] mr-0.5"></i>mạnh về: ${item._wins_on}</span>` : '';

      cardsHtml += `
        <div class="bg-amber-50/60 dark:bg-amber-950/20 rounded-xl p-4 border border-amber-200/80 dark:border-amber-500/20 flex flex-col justify-between space-y-3 shadow-sm transition-all hover:shadow-md hover:border-amber-400/80">
          <div>
            <div class="flex items-center justify-between mb-1">
              ${badge}
              ${brand ? `<span class="text-[10px] text-slate-500 dark:text-slate-400 font-medium">${brand}</span>` : ''}
            </div>
            ${winsOn ? `<div class="mb-1">${winsOn}</div>` : ''}
            <h3 class="font-bold text-[12.5px] text-slate-900 dark:text-white mt-1 leading-snug">${name}</h3>
            ${price ? `<div class="text-[15px] font-extrabold text-blue-600 dark:text-brand-electric mt-1.5">${price}</div>` : ''}
            ${reasonsHtml ? `<ul class="text-[11px] text-slate-600 dark:text-slate-400 mt-2.5 space-y-1 bg-white/80 dark:bg-brand-dark/40 p-2.5 rounded-lg border border-amber-100 dark:border-brand-border/30">${reasonsHtml}</ul>` : ''}
          </div>
          <div class="flex gap-2">
            <button class="flex-1 custom-btn-select text-xs py-2.5 rounded-xl font-bold transition-all shadow-sm">Đặt Mua Ngay</button>
            ${url !== '#' ? `<a href="${url}" target="_blank" class="flex items-center justify-center px-3 py-2.5 rounded-xl border border-brand-electric/40 text-brand-electric text-xs font-semibold hover:bg-brand-electric/10 transition-all"><i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i></a>` : ''}
          </div>
        </div>`;
    });
    cardsHtml += `</div>`;
    appendAssistantMessage(cardsHtml);
  }

  // Render explanation prose từ LLM (Call B — z.ai)
  if (explanation) {
    const exHtml = `
      <div class="mt-1 p-3 rounded-xl bg-blue-50/80 dark:bg-blue-950/30 border border-blue-200/60 dark:border-blue-800/40 text-[12px] text-slate-700 dark:text-slate-300 leading-relaxed">
        <i class="fa-solid fa-brain text-brand-electric mr-1.5 text-[10px]"></i>
        <span>${explanation}</span>
      </div>`;
    appendAssistantMessage(exHtml);
  }
}

// ==========================================
// CHOOSE-FACTORS UI (yếu tố cân nhắc — 3 tầng ngôn ngữ + A/B/C/D)
// ==========================================
let lastQuery = '';               // resent verbatim when the user confirms factors
let selectedFactors = [];         // ids picked this round (max 4); budget uses "budget:tier"

function renderChooseFactors(data) {
  selectedFactors = [];
  const factors = data.factors || [];
  const room = data.room_context || [];
  const roomHtml = room.length
    ? `<p class="text-[11px] text-slate-400 mb-2 italic"><i class="fa-solid fa-location-dot mr-1"></i>Gợi ý theo không gian: ${room.join(' · ')}</p>` : '';

  let html = `<p class="text-sm mb-2">${data.message || 'Anh/chị ưu tiên yếu tố nào ạ?'}</p>${roomHtml}`;
  html += `<div class="flex flex-col gap-2.5 mt-1">`;
  factors.forEach(f => {
    const ctx = (f.contextual || []).map(c =>
      `<span class="px-1.5 py-0.5 text-[10px] rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400">${c}</span>`).join(' ');
    if (f.budget_tier) {
      // budget factor -> tier chips thấp / trung bình / cao
      const tiers = (f.tier_options || []).map(t =>
        `<button data-factor="budget:${t.key}" class="factor-chip px-3 py-1.5 rounded-lg text-[11px] font-semibold border border-slate-300 dark:border-slate-600 hover:border-brand-electric transition-all">
           ${t.label}<span class="block text-[9px] font-normal text-slate-400">${t.hint}</span></button>`).join('');
      html += `
        <div class="p-3 rounded-xl border border-slate-200 dark:border-slate-700 bg-white/60 dark:bg-slate-900/30">
          <div class="flex items-center gap-2 mb-1.5">
            <span class="w-5 h-5 flex items-center justify-center rounded-md bg-brand-electric/15 text-brand-electric text-[11px] font-bold">${f.letter}</span>
            <span class="text-[12.5px] font-bold text-slate-800 dark:text-slate-100">${f.spec_label}</span>
          </div>
          <p class="text-[11.5px] text-slate-600 dark:text-slate-300 mb-2">${f.simple_label}</p>
          <div class="flex flex-wrap gap-1.5">${tiers}</div>
        </div>`;
    } else {
      html += `
        <button data-factor="${f.id}" class="factor-chip text-left p-3 rounded-xl border border-slate-200 dark:border-slate-700 bg-white/60 dark:bg-slate-900/30 hover:border-brand-electric transition-all">
          <div class="flex items-center gap-2 mb-1">
            <span class="w-5 h-5 flex items-center justify-center rounded-md bg-brand-electric/15 text-brand-electric text-[11px] font-bold">${f.letter}</span>
            <span class="text-[12.5px] font-bold text-slate-800 dark:text-slate-100">${f.spec_label}</span>
          </div>
          <p class="text-[11.5px] text-slate-600 dark:text-slate-300 mb-1.5">${f.simple_label}</p>
          <div class="flex flex-wrap gap-1">${ctx}</div>
        </button>`;
    }
  });
  html += `</div>`;
  html += `<button id="confirm-factors-btn" class="mt-3 w-full custom-btn-select text-xs py-2.5 rounded-xl font-bold opacity-50 pointer-events-none transition-all">Xác nhận ưu tiên</button>`;
  appendAssistantMessage(html);
}

// delegated: toggle a factor chip (multi-select, max 4). Budget tier is single-choice
// within its group (picking a new tier replaces the old budget:* selection).
window.toggleFactorChip = function(btn) {
  const fid = btn.getAttribute('data-factor');
  if (!fid) return;
  const isBudget = fid.startsWith('budget:');
  if (isBudget) {
    // drop any prior budget:* then toggle this one
    selectedFactors = selectedFactors.filter(x => !x.startsWith('budget:'));
    document.querySelectorAll('.factor-chip[data-factor^="budget:"]').forEach(b => {
      b.classList.remove('ring-2', 'ring-brand-electric', 'border-brand-electric');
    });
    selectedFactors.push(fid);
    btn.classList.add('ring-2', 'ring-brand-electric', 'border-brand-electric');
  } else {
    const i = selectedFactors.indexOf(fid);
    if (i >= 0) {
      selectedFactors.splice(i, 1);
      btn.classList.remove('ring-2', 'ring-brand-electric', 'border-brand-electric');
    } else {
      if (selectedFactors.filter(x => !x.startsWith('budget:')).length >= 4) return; // max 4
      selectedFactors.push(fid);
      btn.classList.add('ring-2', 'ring-brand-electric', 'border-brand-electric');
    }
  }
  const confirm = document.getElementById('confirm-factors-btn');
  if (confirm) {
    const on = selectedFactors.length > 0;
    confirm.classList.toggle('opacity-50', !on);
    confirm.classList.toggle('pointer-events-none', !on);
  }
};

window.confirmFactors = function() {
  if (!selectedFactors.length) return;
  const chosen = selectedFactors.slice();
  const summary = chosen.map(c => c.startsWith('budget:') ? 'Ngân sách: ' + c.split(':')[1] : c).join(', ');
  appendUserMessage('Ưu tiên: ' + summary);
  showTypingIndicator();
  const startTime = performance.now();
  callBackendChat(lastQuery, chosen).then(data => {
    removeTypingIndicator();
    if (data) renderBackendResponse(data, startTime);
    else appendAssistantMessage('<p class="text-sm">Dạ hệ thống đang bận, anh/chị thử lại giúp em nhé.</p>');
  });
};

// ==========================================
// HỆ THỐNG ĐIỀU KHIỂN ĐÓNG/MỞ SIDEBAR
// ==========================================
function initCollapsibleSidebarLogic() {
  const sidebarPanel = document.getElementById('sidebar-panel');
  const btnClose = document.getElementById('btn-close-sidebar');
  const btnOpen = document.getElementById('btn-open-sidebar');

  if (!sidebarPanel || !btnClose || !btnOpen) return;

  btnClose.addEventListener('click', () => {
    sidebarPanel.classList.remove('w-80', 'p-5', 'border-r');
    sidebarPanel.classList.add('w-0', 'p-0', 'border-r-0', 'opacity-0', 'pointer-events-none');
    btnOpen.classList.remove('hidden');
  });

  btnOpen.addEventListener('click', () => {
    sidebarPanel.classList.remove('w-0', 'p-0', 'border-r-0', 'opacity-0', 'pointer-events-none');
    sidebarPanel.classList.add('w-80', 'p-5', 'border-r');
    btnOpen.classList.add('hidden');
  });
}

// ==========================================
// HIỆU ỨNG RUNG LẮC ĐỒNG LOẠT CHO TOÀN BỘ MASCOT
// ==========================================
function injectJiggleStyles() {
  if (document.getElementById('mascot-jiggle-style')) return;
  const style = document.createElement('style');
  style.id = 'mascot-jiggle-style';
  style.innerHTML = `
    @keyframes jiggleVivid {
      0% { transform: scale(1) rotate(0deg); }
      15% { transform: scale(1.15) rotate(-10deg); }
      30% { transform: scale(1.15) rotate(8deg); }
      45% { transform: scale(1.08) rotate(-6deg); }
      60% { transform: scale(1.08) rotate(4deg); }
      75% { transform: scale(1.02) rotate(-2deg); }
      100% { transform: scale(1) rotate(0deg); }
    }
    .animate-jiggle-vivid {
      animation: jiggleVivid 0.6s ease-in-out;
      display: inline-block !important;
    }
  `;
  document.head.appendChild(style);
}

function triggerMascotJiggle() {
  const allMascots = document.querySelectorAll('img[src*="mascot"]');
  allMascots.forEach(mascot => {
    // Không rung jiggle cho phần Header Mascot để dành riêng cho chuyển động violent bounce
    if (mascot.id === 'header-mascot') return;
    mascot.classList.add('animate-jiggle-vivid');
  });
  setTimeout(() => {
    allMascots.forEach(mascot => {
      if (mascot.id === 'header-mascot') return;
      mascot.classList.remove('animate-jiggle-vivid');
    });
  }, 600);
}

window.handleBuyProduct = function() {
  window.appendAssistantMessage('<p class="text-sm font-semibold text-emerald-600 dark:text-emerald-400"><i class="fa-solid fa-circle-check mr-1.5"></i>Dạ tuyệt vời, hệ thống Điện Máy Xanh đã ghi nhận yêu cầu đặt mua sản phẩm của anh/chị! Nhân viên tổng đài sẽ liên hệ hỗ trợ mình sau ít phút ạ.</p>');
  triggerMascotJiggle();

  // KÍCH HOẠT HIỆU ỨNG DI CHUYỂN BẬT NHẢY MẠNH BẠO CHO HEADER MASCOT
  const headerMascot = document.getElementById('header-mascot');
  if (headerMascot) {
    headerMascot.classList.remove('animate-glowing-orb');
    headerMascot.classList.add('animate-violent-bounce');
    setTimeout(() => {
      headerMascot.classList.remove('animate-violent-bounce');
      headerMascot.classList.add('animate-glowing-orb');
    }, 1000);
  }
};

// ==========================================
// UTILITIES & CHAT UI RENDERERS
// ==========================================
function formatVND(amount) {
  return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(amount).replace('₫', 'đ');
}

document.addEventListener('click', function(e) {
  const confirmBtn = e.target && e.target.closest && e.target.closest('#confirm-factors-btn');
  if (confirmBtn) { window.confirmFactors(); return; }
  const chip = e.target && e.target.closest && e.target.closest('.factor-chip');
  if (chip) { window.toggleFactorChip(chip); return; }
  if (e.target && e.target.classList.contains('custom-btn-select')) {
    window.handleBuyProduct();
  }
});

function scrollChatToBottom() {
  const chatBox = document.getElementById('chat-box');
  if (chatBox) chatBox.scrollTop = chatBox.scrollHeight;
}

// INTEGRATED EFFECT: The Liquid Elastic Wave with Glow on typing indicator
function showTypingIndicator() {
  const chatBox = document.getElementById('chat-box');
  if (!chatBox) return;
  const html = `
    <div id="typing-indicator" class="flex items-start space-x-3.5 message-fade-in">
      <div class="w-10 h-10 rounded-xl bg-white border border-slate-200 dark:border-brand-border flex items-center justify-center overflow-hidden shrink-0 shadow-md">
        <img src="img/mascot.png" alt="..." class="w-full h-full object-contain p-0.5 animate-mascot-idle" onerror="this.src='https://placehold.co/100x100?text=Mascot'">
      </div>
      <div class="bg-blue-50/60 dark:bg-blue-950/30 text-slate-400 rounded-2xl rounded-tl-none px-4 py-3 border border-blue-100 dark:border-blue-900/50 shadow-sm">
        <div class="flex items-center space-x-1.5 py-1">
          <span class="w-2 h-2 bg-slate-500 dark:bg-slate-400 rounded-full typing-dot inline-block"></span>
          <span class="w-2 h-2 bg-slate-500 dark:bg-slate-400 rounded-full typing-dot inline-block"></span>
          <span class="w-2 h-2 bg-slate-500 dark:bg-slate-400 rounded-full typing-dot inline-block"></span>
        </div>
      </div>
    </div>`;
  chatBox.insertAdjacentHTML('beforeend', html);
  scrollChatToBottom();
}

function removeTypingIndicator() {
  const indicator = document.getElementById('typing-indicator');
  if (indicator) indicator.remove();
}

function appendUserMessage(text) {
  const chatBox = document.getElementById('chat-box');
  if (!chatBox) return;
  const html = `
    <div class="flex items-start space-x-3 justify-end message-fade-in">
      <div class="space-y-1 max-w-[80%]">
        <div class="bg-gradient-to-r from-[#1d4ed8] to-[#0095da] text-white rounded-2xl rounded-tl-none px-4 py-3 shadow-md">
          <p class="text-sm leading-relaxed">${text}</p>
        </div>
      </div>
      <div class="w-9 h-9 rounded-xl bg-white dark:bg-brand-panel border border-slate-200 dark:border-brand-border flex items-center justify-center shrink-0 shadow-sm">
        <i class="fa-solid fa-user text-brand-electric text-sm"></i>
      </div>
    </div>`;
  chatBox.insertAdjacentHTML('beforeend', html);
  scrollChatToBottom();

  if (activeSessionId) {
    const s = consumerChatSessions.find(item => item.id === activeSessionId);
    if (s) s.messages.push({ role: 'user', content: text });
  }
}

// INTEGRATED EFFECT: The Liquid Elastic Wave with Glow on Assistant Avatar
function appendAssistantMessage(htmlContent) {
  const chatBox = document.getElementById('chat-box');
  if (!chatBox) return;
  const html = `
    <div class="flex items-start space-x-3.5 message-fade-in">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-white to-slate-100 border border-white flex items-center justify-center shrink-0 shadow-[0_4px_10px_rgba(0,149,218,0.15)] overflow-hidden">
        <img src="img/mascot.png" alt="Avatar" class="w-[85%] h-[85%] object-contain animate-mascot-idle" onerror="this.src='https://placehold.co/100x100?text=AI'">
      </div>
      <div class="space-y-1 max-w-[85%] w-full">
        <div class="bg-blue-50/60 dark:bg-blue-950/30 text-slate-800 dark:text-slate-200 rounded-2xl rounded-tl-none px-5 py-3.5 border border-blue-100 dark:border-blue-900/50 shadow-sm">
          ${htmlContent}
        </div>
      </div>
    </div>`;
  chatBox.insertAdjacentHTML('beforeend', html);
  scrollChatToBottom();

  if (activeSessionId) {
    const s = consumerChatSessions.find(item => item.id === activeSessionId);
    if (s) s.messages.push({ role: 'assistant', content: htmlContent });
  }
}
window.appendAssistantMessage = appendAssistantMessage;

// ==========================================
// QUẢN LÝ LỊCH SỬ PHIÊN TRÒ CHUYỆN (SESSIONS)
// ==========================================
function createNewChatSession(initialTitle = "Cuộc trò chuyện mới") {
  const newId = 'session_' + Date.now();
  const randomMascot = MASCOT_IMAGES[Math.floor(Math.random() * MASCOT_IMAGES.length)];

  const newSession = {
    id: newId,
    title: initialTitle,
    timestamp: new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }),
    messages: [],
    category: null,
    profile: {},
    mascot: randomMascot
  };
  consumerChatSessions.unshift(newSession);
  activeSessionId = newId;
  renderChatHistoryUI();
  return newSession;
}

function updateActiveSessionTitle(newTitle, categoryCode) {
  if (!activeSessionId) return;
  const s = consumerChatSessions.find(item => item.id === activeSessionId);
  if (s) {
    s.title = newTitle;
    if (categoryCode) s.category = categoryCode;
    renderChatHistoryUI();
  }
}

function renderChatHistoryUI() {
  const container = document.getElementById('chat-history-list');
  if (!container) return;

  if (consumerChatSessions.length === 0) {
    container.innerHTML = `
      <div id="history-empty-state" class="text-center py-8 px-4 border border-dashed border-amber-200 dark:border-amber-500/20 rounded-xl bg-amber-50/20">
        <p class="text-[11px] text-amber-600 italic">Chưa có cuộc trò chuyện cũ.</p>
      </div>`;
    return;
  }

  container.innerHTML = '';
  consumerChatSessions.forEach(session => {
    const isActive = session.id === activeSessionId;
    const pill = document.createElement('div');

    pill.className = `group flex items-center justify-between p-3 rounded-xl border transition-all duration-200 cursor-pointer text-xs font-medium history-item-appear ${
      isActive
      ? 'border-brand-electric/50 bg-brand-electric/5 text-brand-electric dark:bg-brand-electric/10'
      : 'border-amber-200/70 dark:border-amber-500/20 bg-amber-50/50 dark:bg-amber-950/10 text-amber-800 dark:text-amber-300 hover:bg-amber-100/60 dark:hover:bg-amber-900/20'
    }`;

    const mascotFile = session.mascot || 'mascot.png';
    const iconImageHtml = `<img src="img/${mascotFile}" alt="Mascot" class="w-6 h-6 object-contain rounded-md shadow-sm bg-white" onerror="this.src='img/mascot.png'">`;

    pill.innerHTML = `
      <div class="flex items-center space-x-2.5 truncate w-[90%]">
        <span class="shrink-0 flex items-center">${iconImageHtml}</span>
        <div class="truncate flex flex-col text-left">
          <span class="truncate font-semibold text-amber-950 dark:text-amber-100">${session.title}</span>
          <span class="text-[10px] text-amber-600/80 dark:text-amber-400/60 mt-0.5">${session.timestamp} • Điện Máy Xanh</span>
        </div>
      </div>`;

    pill.addEventListener('click', () => {
      activeSessionId = session.id;
      renderChatHistoryUI();
      restoreSessionMessages(session);
    });
    container.appendChild(pill);
  });
}

function restoreSessionMessages(session) {
  currentProfile = session.profile || {};
  const chatBox = document.getElementById('chat-box');
  if (!chatBox) return;

  if (!session.messages || session.messages.length === 0) {
    chatBox.innerHTML = `
      <div class="flex items-start space-x-3.5 message-fade-in">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-white to-slate-100 border border-white flex items-center justify-center overflow-hidden shrink-0 shadow-[0_4px_10px_rgba(0,149,218,0.15)] bg-white">
          <img src="img/mascot.png" alt="Avatar" class="w-[85%] h-[85%] object-contain animate-mascot-idle" onerror="this.src='https://placehold.co/100x100?text=AI'">
        </div>
        <div class="space-y-1 max-w-[85%] w-full">
          <div class="bg-blue-50/60 dark:bg-blue-950/30 text-slate-800 dark:text-slate-200 rounded-2xl rounded-tl-none px-5 py-3.5 border border-blue-100 dark:border-blue-900/50 shadow-sm">
            <p class="text-sm">Dạ, phiên hội thoại tư vấn mua sắm mới đã sẵn sàng phục vụ rồi ạ! Anh/chị cần em hỗ trợ tìm kiếm dòng thiết bị công nghệ điện máy nào thế ạ?</p>
          </div>
        </div>
      </div>`;
    sessionState.stage = 'INIT';
    sessionState.category = null;
    sessionState.collectedData = { brand: null, budget: null, roomSize: null, familySize: null, purpose: null };

    document.getElementById('active-category').textContent = 'Chưa xác định';
    document.getElementById('chat-stage').textContent = 'INIT';
    scrollChatToBottom();
    return;
  }

  chatBox.innerHTML = '';
  session.messages.forEach(msg => {
    if (msg.role === 'user') {
      const html = `<div class="flex items-start space-x-3 justify-end message-fade-in"><div class="max-w-[80%] bg-gradient-to-r from-[#1d4ed8] to-[#0095da] text-white rounded-2xl rounded-tl-none px-4 py-3 text-[13.5px] shadow-sm">${msg.content}</div></div>`;
      chatBox.insertAdjacentHTML('beforeend', html);
    } else {
      const html = `<div class="flex items-start space-x-3.5 message-fade-in"><div class="w-10 h-10 rounded-xl bg-white border border-white flex items-center justify-center shrink-0 shadow-[0_4px_10px_rgba(0,149,218,0.15)] overflow-hidden"><img src="img/mascot.png" class="w-[85%] h-[85%] object-contain animate-mascot-idle"></div><div class="max-w-[85%] w-full bg-blue-50/60 dark:bg-blue-950/30 text-slate-800 dark:text-slate-200 rounded-2xl rounded-tl-none px-5 py-3.5 border border-blue-100 dark:border-blue-900/50 text-[13.5px] shadow-sm">${msg.content}</div></div>`;
      chatBox.insertAdjacentHTML('beforeend', html);
    }
  });

  sessionState.category = session.category;
  sessionState.stage = session.messages.length > 0 ? 'RECOMMENDATION' : 'INIT';
  document.getElementById('active-category').textContent = session.category || 'Chưa xác định';
  document.getElementById('chat-stage').textContent = sessionState.stage;
  scrollChatToBottom();
}

// ========================================================
// HEURISTIC NLP PARSER - TRÍCH XUẤT THÔNG TIN TỰ NHIÊN TIẾNG VIỆT
// ========================================================
function extractEntitiesFromText(text) {
  const lower = text.toLowerCase();
  let result = {};

  if (lower.includes('máy lạnh') || lower.includes('điều hòa') || lower.includes('đh')) {
    result.category = 'ac';
  } else if (lower.includes('tủ lạnh') || lower.includes('tl')) {
    result.category = 'fridge';
  } else if (lower.includes('laptop') || lower.includes('máy tính')) {
    result.category = 'laptop';
  }

  const brandsList = ['panasonic', 'daikin', 'casper', 'samsung', 'lg', 'aqua', 'hp', 'asus', 'lenovo'];
  for (const b of brandsList) {
    if (lower.includes(b)) {
      result.brand = b.charAt(0).toUpperCase() + b.slice(1);
      break;
    }
  }
  if (!result.brand && lower.includes('pana')) result.brand = 'Panasonic';

  const priceRegex = /(dưới|trên|tầm|khoảng|~)?\s*(\d+)\s*(triệu|tr|củ)/i;
  const matchPrice = lower.match(priceRegex);
  if (matchPrice) {
    const modifier = matchPrice[1] || 'tầm';
    const numericValue = parseInt(matchPrice[2], 10) * 1000000;
    result.budget = { modifier, value: numericValue };
  }

  const roomRegex = /(\d+)\s*(m2|m²)/i;
  const matchRoom = lower.match(roomRegex);
  if (matchRoom) {
    result.roomSize = parseInt(matchRoom[1], 10);
  } else if (lower.includes('phòng ngủ')) {
    result.roomSize = 12;
  } else if (lower.includes('phòng khách')) {
    result.roomSize = 22;
  }

  const familyRegex = /(\d+)\s*(người|thành viên|nhân khẩu)/i;
  const matchFamily = lower.match(familyRegex);
  if (matchFamily) {
    result.familySize = parseInt(matchFamily[1], 10);
  } else if (lower.includes('sinh viên') || lower.includes('ở một mình') || lower.includes('trọ')) {
    result.familySize = 1;
  }

  if (lower.includes('sinh viên') || lower.includes('học tập') || lower.includes('văn phòng') || lower.includes('mỏng nhẹ')) {
    result.purpose = 'office';
  } else if (lower.includes('gaming') || lower.includes('đồ họa') || lower.includes('chơi game')) {
    result.purpose = 'heavy';
  }

  return result;
}

// ========================================================
// CORE LOGIC ENGINE - ĐIỀU PHỐI HỘI THOẠI & DỮ LIỆU RAG
// ========================================================
function handleFormSubmit(event) {
  if (event && typeof event.preventDefault === 'function') {
    event.preventDefault();
  }

  const input = document.getElementById('user-input');
  if (!input) return;
  const val = input.value.trim();
  if (!val) return;

  if (!activeSessionId) createNewChatSession();

  const s = consumerChatSessions.find(item => item.id === activeSessionId);
  const hasBought = s && s.messages && s.messages.some(msg => 
    msg.role === 'assistant' && msg.content.includes('yêu cầu đặt mua')
  );

  if (hasBought) {
    const householdKeywords = [
      'điện thoại', 'điên thoai', 'đt', 'dt', 'iphone', 'samsung', 'oppo', 'xiaomi', 'realme',
      'máy lạnh', 'may lanh', 'điều hòa', 'dieu hoa', 'đh', 'dh', 'daikin', 'panasonic',
      'tủ lạnh', 'tu lanh', 'hitachi', 'toshiba', 'panasonic',
      'laptop', 'máy tính', 'may tinh', 'asus', 'dell', 'hp', 'macbook', 'acer',
      'máy giặt', 'may giat',
      'máy sấy', 'may say',
      'máy rửa chén', 'may rua chen', 'rửa bát', 'rua bat',
      'máy nước nóng', 'may nuoc nong',
      'tủ đông', 'tu dong', 'tủ mát', 'tu mat',
      'màn hình', 'man hinh',
      'máy in', 'may in',
      'đồng hồ', 'dong ho',
      'micro', 'mic', 'tivi', 'tv'
    ];
    const lowerVal = val.toLowerCase();
    const isAppliance = householdKeywords.some(kw => lowerVal.includes(kw));
    if (isAppliance) {
      window.resetConversation();
    }
  }

  appendUserMessage(val);
  input.value = '';
  showTypingIndicator();

  // Gọi backend AI hoặc fallback mock
  dispatchLogicEngine(val);
}
async function dispatchLogicEngine(text) {
  const startTime = performance.now();
  const lower = text.toLowerCase();

  // FAQ cục bộ - trả lời ngay không cần backend
  for (const [key, answer] of Object.entries(MOCK_FAQ)) {
    if (lower.includes(key)) {
      removeTypingIndicator();
      document.getElementById('rag-faq-status').textContent = `Khớp FAQ: [${key}]`;
      document.getElementById('latency-val').textContent = Math.round(performance.now() - startTime) + 'ms';
      appendAssistantMessage(`<p class="text-sm"><i class="fa-solid fa-circle-info text-brand-electric mr-1.5"></i>${answer}</p>`);
      return;
    }
  }
  document.getElementById('rag-faq-status').textContent = 'Không khớp FAQ';

  // --- Gọi Backend AI thật (Vercel /api/chat) ---
  lastQuery = text;  // remembered so confirmFactors() can resend it with chosen_factors
  const data = await callBackendChat(text);
  if (data) {
    removeTypingIndicator();
    renderBackendResponse(data, startTime);
    return;
  }
  // Backend lỗi → fallback mock bên dưới
  console.warn('[AI] Backend không phản hồi, fallback mock.');

  const extracted = extractEntitiesFromText(text);

  if (extracted.category) sessionState.category = extracted.category;
  if (extracted.brand) sessionState.collectedData.brand = extracted.brand;
  if (extracted.budget) sessionState.collectedData.budget = extracted.budget;
  if (extracted.roomSize) sessionState.collectedData.roomSize = extracted.roomSize;
  if (extracted.familySize) sessionState.collectedData.familySize = extracted.familySize;
  if (extracted.purpose) sessionState.collectedData.purpose = extracted.purpose;

  document.getElementById('active-category').textContent = sessionState.category || 'Chưa xác định';
  document.getElementById('slang-inspector').textContent = JSON.stringify(sessionState.collectedData);

  if (!sessionState.category) {
    sessionState.stage = 'INIT';
    document.getElementById('chat-stage').textContent = sessionState.stage;
    document.getElementById('latency-val').textContent = Math.round(performance.now() - startTime) + 'ms';
    appendAssistantMessage('<p class="text-sm">Dạ, em có thể hỗ trợ tư vấn chuyên sâu và so sánh thông thái về 3 nhóm sản phẩm: <strong>Máy lạnh, Tủ lạnh, hoặc Laptop</strong>. Anh/chị đang có nhu cầu tìm mua sản phẩm nào ạ?</p>');
    return;
  }

  let categoryLabel = "Trò chuyện";
  if (sessionState.category === 'ac') categoryLabel = "Tư vấn Máy Lạnh";
  if (sessionState.category === 'fridge') categoryLabel = "Tư vấn Tủ Lạnh";
  if (sessionState.category === 'laptop') categoryLabel = "Tư vấn Laptop";
  updateActiveSessionTitle(categoryLabel, sessionState.category);

  if (sessionState.category === 'ac' && !sessionState.collectedData.roomSize) {
    if (sessionState.stage === 'PROBING') {
      sessionState.collectedData.roomSize = 12;
      appendAssistantMessage('<p class="text-xs italic text-slate-400 mb-2"><i class="fa-solid fa-wand-magic-sparkles mr-1"></i> Em xin phép lấy mức diện tích phòng ngủ tiêu chuẩn phổ thông (dưới 15m²) để lọc sản phẩm ngay cho mình nhé.</p>');
    } else {
      sessionState.stage = 'PROBING';
      document.getElementById('chat-stage').textContent = sessionState.stage;
      document.getElementById('latency-val').textContent = Math.round(performance.now() - startTime) + 'ms';
      appendAssistantMessage('<p class="text-sm">Dạ, để em tính toán công suất số Ngựa (HP) tối ưu nhất, anh/chị cho em hỏi <strong>diện tích phòng lắp đặt khoảng bao nhiêu m²</strong> (hoặc lắp cho không gian nào như phòng ngủ, phòng khách) ạ?</p>');
      return;
    }
  }

  if (sessionState.category === 'fridge' && !sessionState.collectedData.familySize) {
    if (sessionState.stage === 'PROBING') {
      sessionState.collectedData.familySize = 3;
      appendAssistantMessage('<p class="text-xs italic text-slate-400 mb-2"><i class="fa-solid fa-wand-magic-sparkles mr-1"></i> Em xin phép lấy dung tích tiêu chuẩn cho hộ gia đình 3 - 4 thành viên phổ biến để đề xuất các mẫu tối ưu nhé.</p>');
    } else {
      sessionState.stage = 'PROBING';
      document.getElementById('chat-stage').textContent = sessionState.stage;
      document.getElementById('latency-val').textContent = Math.round(performance.now() - startTime) + 'ms';
      appendAssistantMessage('<p class="text-sm">Dạ, nhà mình dự kiến **có khoảng bao nhiêu thành viên** sẽ dùng chung tủ lạnh ạ, để em lọc mức dung tích (lít) chứa thực phẩm vừa vặn nhất cho gia đình mình?</p>');
      return;
    }
  }

  if (sessionState.category === 'laptop' && !sessionState.collectedData.brand && !sessionState.collectedData.budget) {
    if (sessionState.stage !== 'PROBING') {
      sessionState.stage = 'PROBING';
      document.getElementById('chat-stage').textContent = sessionState.stage;
      document.getElementById('latency-val').textContent = Math.round(performance.now() - startTime) + 'ms';
      appendAssistantMessage('<p class="text-sm">Dạ, anh/chị tìm mua laptop phục vụ chính cho **nhu cầu học tập văn phòng mỏng nhẹ** hay **đồ họa chơi game nặng** ạ? Nếu mình có khoảng ngân sách dự kiến, hãy chia sẻ để em định hình máy chuẩn nhất nha!</p>');
      return;
    }
  }

  sessionState.stage = 'RECOMMENDATION';
  document.getElementById('chat-stage').textContent = sessionState.stage;

  const catalog = MOCK_CATALOG[sessionState.category];
  let filteredProducts = [...catalog];

  if (sessionState.collectedData.brand) {
    const targetBrand = sessionState.collectedData.brand.toLowerCase();
    filteredProducts = filteredProducts.filter(p => p.brand.toLowerCase().includes(targetBrand));
  }

  if (sessionState.collectedData.budget) {
    const { modifier, value } = sessionState.collectedData.budget;
    if (modifier === 'dưới') {
      filteredProducts = filteredProducts.filter(p => p.price <= value);
    } else if (modifier === 'trên') {
      filteredProducts = filteredProducts.filter(p => p.price >= value);
    } else {
      filteredProducts = filteredProducts.filter(p => p.price <= value * 1.15);
    }
  }

  if (sessionState.category === 'ac' && sessionState.collectedData.roomSize) {
    const size = sessionState.collectedData.roomSize;
    if (size <= 15) {
      filteredProducts = filteredProducts.filter(p => p.room_size.includes('Dưới 15m²'));
    } else {
      filteredProducts = filteredProducts.filter(p => p.room_size.includes('15 đến 20m²'));
    }
  }

  if (sessionState.category === 'fridge' && sessionState.collectedData.familySize) {
    const size = sessionState.collectedData.familySize;
    if (size <= 2) {
      filteredProducts = filteredProducts.filter(p => p.family_size.includes('1 - 2') || p.family_size.includes('2 - 4'));
    } else if (size >= 3 && size <= 4) {
      filteredProducts = filteredProducts.filter(p => p.family_size.includes('2 - 4') || p.family_size.includes('3 - 5'));
    } else {
      filteredProducts = filteredProducts.filter(p => p.family_size.includes('3 - 5'));
    }
  }

  let isFallbackTriggered = false;
  if (filteredProducts.length === 0) {
    filteredProducts = [...catalog];
    isFallbackTriggered = true;
  }

  document.getElementById('rag-catalog-status').textContent = `Tìm thấy ${filteredProducts.length} mẫu`;
  document.getElementById('rag-promo-status').textContent = 'Đã áp mã khuyến mãi dynamic';

  let introductionPrompt = "";
  if (isFallbackTriggered) {
    introductionPrompt = `Dạ hiện tại kho hàng không có mẫu nào khớp hoàn hảo 100% tiêu chí đặc thù trên, em xin phép đề xuất **Top ${filteredProducts.length} sản phẩm bán chạy nhất** thuộc nhóm ngành hàng này tại Điện Máy Xanh để anh/chị cân nhắc ạ:`;
  } else {
    introductionPrompt = `Dạ tuyệt vời! Khảo sát kho hàng thời gian thực, em đã tìm thấy **${filteredProducts.length} sản phẩm tối ưu nhất** phù hợp hoàn chỉnh với mong muốn của mình. Dưới đây là phân tích đặc tính kỹ thuật kèm điểm đánh đổi thực tế:`;
  }

  let cardsHtml = `<p class="text-[13.5px] leading-relaxed mb-4 text-slate-800 dark:text-slate-200">${introductionPrompt}</p>
  <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">`;

  filteredProducts.forEach((product, idx) => {
    const hasZeroInstallment = MOCK_PROMOTIONS.installment_0.includes(product.id);
    const promotionGift = MOCK_PROMOTIONS.discounts[product.id] || 'Tặng phiếu mua hàng trị giá 200.000đ (Áp dụng mua đồ gia dụng)';

    let tradeOffAnalysis = "Dòng sản phẩm quốc dân, lượng đặt mua rất cao dễ gặp tình trạng thiếu hàng cục bộ tại một số quận huyện.";
    if (product.price < 6000000) {
      tradeOffAnalysis = "Giá thành siêu rẻ tiết kiệm chi phí, tuy nhiên tính năng chỉ dừng ở mức cơ bản, không tích hợp nhiều công nghệ cảm biến cao cấp.";
    } else if (product.price > 13000000) {
      tradeOffAnalysis = "Công nghệ và độ bền xuất sắc hàng đầu, tuy nhiên tổng chi phí đầu tư ban đầu sẽ cao hơn các thương hiệu phổ thông.";
    }

    let specsHtml = "";
    if (sessionState.category === 'ac') {
      specsHtml = `<li><i class="fa-solid fa-expand text-slate-400 mr-1.5"></i>Diện tích: <strong>${product.room_size}</strong></li>
                   <li><i class="fa-solid fa-volume-low text-slate-400 mr-1.5"></i>Độ ồn: <strong>${product.noise}</strong></li>`;
    } else if (sessionState.category === 'fridge') {
      specsHtml = `<li><i class="fa-solid fa-box-open text-slate-400 mr-1.5"></i>Dung tích: <strong>${product.liters} Lít</strong></li>
                   <li><i class="fa-solid fa-snowflake text-slate-400 mr-1.5"></i>Làm lạnh: <strong>${product.family_size}</strong></li>`;
    } else if (sessionState.category === 'laptop') {
      specsHtml = `<li><i class="fa-solid fa-weight-hanging text-slate-400 mr-1.5"></i>Trọng lượng: <strong>${product.weight}</strong></li>
                   <li><i class="fa-solid fa-laptop text-slate-400 mr-1.5"></i>Màn hình: <strong>${product.screen}</strong></li>`;
    }

    cardsHtml += `
      <div class="bg-amber-50/60 dark:bg-amber-950/20 rounded-xl p-4 border border-amber-200/80 dark:border-amber-500/20 flex flex-col justify-between space-y-3.5 shadow-sm transition-all hover:shadow-md hover:border-amber-400/80">
        <div>
          <div class="flex items-center justify-between">
            <span class="px-2 py-0.5 text-[10px] font-bold bg-amber-200/50 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200 rounded">Đề xuất ${idx + 1}</span>
            ${hasZeroInstallment ? `<span class="px-2 py-0.5 text-[10px] font-bold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 rounded flex items-center gap-0.5"><i class="fa-solid fa-bolt text-[8px]"></i> Trả góp 0%</span>` : ''}
          </div>
          <h3 class="font-bold text-[12.5px] text-slate-900 dark:text-white mt-2 line-clamp-2 h-9 leading-snug">${product.name}</h3>
          <div class="text-[15px] font-extrabold text-blue-600 dark:text-brand-electric mt-1.5">${formatVND(product.price)}</div>

          <ul class="text-[11px] text-slate-600 dark:text-slate-400 mt-2.5 space-y-1 bg-white/80 dark:bg-brand-dark/40 p-2.5 rounded-lg border border-amber-100 dark:border-brand-border/30">
            ${specsHtml}
          </ul>

          <p class="text-[11px] text-amber-700 dark:text-amber-400 font-semibold mt-2.5 flex items-start"><i class="fa-solid fa-gift mr-1.5 mt-0.5 text-xs shrink-0"></i><span>Quà tặng: ${promotionGift}</span></p>
        </div>

        <div class="bg-white dark:bg-amber-900/20 p-2.5 rounded-lg text-[11px] text-amber-900 dark:text-amber-400 border border-amber-200/60 leading-relaxed">
          <strong>Điểm đánh đổi (Trade-off):</strong> ${tradeOffAnalysis}
        </div>

        <button class="w-full custom-btn-select text-xs py-2.5 rounded-xl font-bold transition-all shadow-sm">Đặt Mua Ngay</button>
      </div>`;
  });

  cardsHtml += `</div>`;
  appendAssistantMessage(cardsHtml);

  sessionState.stage = 'INIT';
  sessionState.category = null;
  sessionState.collectedData = { brand: null, budget: null, roomSize: null, familySize: null, purpose: null };

  document.getElementById('chat-stage').textContent = sessionState.stage;
  document.getElementById('latency-val').textContent = Math.round(performance.now() - startTime) + 'ms';
}

// ==========================================
// CÁC HÀM KHỞI TẠO VÀ LÀM MỚI PHIÊN
// ==========================================
window.resetConversation = function() {
  currentProfile = {};
  if (activeSessionId) {
    const currentSession = consumerChatSessions.find(item => item.id === activeSessionId);
    if (currentSession && (!currentSession.messages || currentSession.messages.length === 0)) {
      return;
    }
  }

  const newestEmptySession = consumerChatSessions.find(session => !session.messages || session.messages.length === 0);

  if (newestEmptySession) {
    activeSessionId = newestEmptySession.id;
    restoreSessionMessages(newestEmptySession);

    document.getElementById('slang-inspector').textContent = '';
    document.getElementById('rag-catalog-status').textContent = '';
    document.getElementById('rag-promo-status').textContent = '';
    document.getElementById('rag-faq-status').textContent = '';

    renderChatHistoryUI();
  } else {
    const chatBox = document.getElementById('chat-box');
    if (chatBox) {
      chatBox.innerHTML = `
        <div class="flex items-start space-x-3.5 message-fade-in">
          <div class="w-10 h-10 rounded-xl bg-white border border-white flex items-center justify-center overflow-hidden shrink-0 shadow-[0_4px_10px_rgba(0,149,218,0.15)]">
            <img src="img/mascot.png" alt="Avatar" class="w-[85%] h-[85%] object-contain animate-mascot-idle" onerror="this.src='https://placehold.co/100x100?text=AI'">
          </div>
          <div class="space-y-1 max-w-[85%] w-full">
            <div class="bg-blue-50/60 dark:bg-blue-950/30 text-slate-800 dark:text-slate-200 rounded-2xl rounded-tl-none px-5 py-3.5 border border-blue-100 dark:border-blue-900/50 shadow-sm">
              <p class="text-sm">Dạ, phiên hội thoại tư vấn mua sắm mới đã sẵn sàng phục vụ rồi ạ! Anh/chị cần em hỗ trợ tìm kiếm dòng thiết bị công nghệ điện máy nào thế ạ?</p>
            </div>
          </div>
        </div>`;
    }

    sessionState.stage = 'INIT';
    sessionState.category = null;
    sessionState.collectedData = { brand: null, budget: null, roomSize: null, familySize: null, purpose: null };

    document.getElementById('active-category').textContent = 'Chưa xác định';
    document.getElementById('chat-stage').textContent = 'INIT';
    document.getElementById('slang-inspector').textContent = '';
    document.getElementById('rag-catalog-status').textContent = '';
    document.getElementById('rag-promo-status').textContent = '';
    document.getElementById('rag-faq-status').textContent = '';

    createNewChatSession();
  }
};

window.fillQuickPrompt = function(promptText) {
  const input = document.getElementById('user-input');
  if (input) {
    input.value = promptText;
    input.focus();
  }
};

// ĐỒNG BỘ KHỞI TẠO KHI TẢI TRANG HOÀN TẤT
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('chat-form');
  if (form) form.addEventListener('submit', handleFormSubmit);

  initCollapsibleSidebarLogic();
  injectJiggleStyles();

  const allElements = document.getElementsByTagName('*');
  for (let el of allElements) {
    if (el.textContent.trim().startsWith('Dữ liệu bảo mật') && el.children.length === 0) {
      el.style.textAlign = 'left';
      el.style.display = 'block';
      if (el.parentElement) {
        el.parentElement.style.display = 'flex';
        el.parentElement.style.flexDirection = 'column';
        el.parentElement.style.alignItems = 'flex-start';
        el.parentElement.style.textAlign = 'left';
        el.parentElement.style.paddingLeft = '0';
        el.parentElement.style.marginLeft = '0';
      }
    }
  }

  // Ping /api/health (same-origin Vercel) để cập nhật trạng thái trước khi tạo session
  fetchConfig().finally(() => {
    createNewChatSession();
  });
});

// ==========================================
// INJECT NEW DYNAMIC MASCOT ANIMATIONS (FLOATING & VIOLENT BOUNCE)
// ==========================================
(function injectHeaderMascotAnimations() {
  if (document.getElementById('header-mascot-animations')) return;
  const style = document.createElement('style');
  style.id = 'header-mascot-animations';
  style.innerHTML = `
    @keyframes orbFloatGlow {
      0%, 100% {
        transform: translateY(0) scale(1);
        filter: drop-shadow(0 4px 8px rgba(0,149,218,0.25));
      }
      50% {
        transform: translateY(-5px) scale(1.05);
        filter: drop-shadow(0 12px 20px rgba(0,149,218,0.55));
      }
    }
    .animate-glowing-orb {
      animation: orbFloatGlow 3s ease-in-out infinite !important;
      will-change: transform, filter;
    }
    @keyframes violentBounce {
      0%, 100% { transform: translateY(0) scale(1); }
      10% { transform: translateY(-30px) scaleY(1.3) scaleX(0.85); }
      20% { transform: translateY(22px) scaleY(0.7) scaleX(1.25); }
      30% { transform: translateY(-22px) scaleY(1.15) scaleX(0.9); }
      40% { transform: translateY(16px) scaleY(0.85) scaleX(1.1); }
      50% { transform: translateY(-12px) scaleY(1.05); }
      60% { transform: translateY(10px) scaleY(0.95); }
      70% { transform: translateY(-6px); }
      80% { transform: translateY(4px); }
      90% { transform: translateY(-1px); }
    }
    .animate-violent-bounce {
      animation: violentBounce 1s cubic-bezier(.36,.07,.19,.97) both !important;
      will-change: transform;
    }
  `;
  document.head.appendChild(style);
})();
// ==========================================
// FORCE INJECT HACKATHON LIVE DOTS ANIMATION
// ==========================================
(function injectUltraLivelyDots() {
  if (document.getElementById('ultra-lively-dots-style')) return;
  const style = document.createElement('style');
  style.id = 'ultra-lively-dots-style';
  style.innerHTML = `
    .typing-dot {
      display: inline-block !important;
      will-change: transform, opacity, background-color, box-shadow;
      animation: ultra-lively-wave 0.5s infinite cubic-bezier(0.25, 1, 0.5, 1) !important;
    }
    .typing-dot:nth-child(2) { animation-delay: 0.08s !important; }
    .typing-dot:nth-child(3) { animation-delay: 0.16s !important; }

    @keyframes ultra-lively-wave {
      0%, 100% {
        transform: translateY(0) scale(1);
        opacity: 0.4;
      }
      35% {
        transform: translateY(-10px) scaleX(0.8) scaleY(1.25) !important;
        opacity: 1;
        background-color: #0095da !important;
        box-shadow: 0 0 10px #0095da, 0 0 20px rgba(0, 149, 218, 0.4);
      }
      70% {
        transform: translateY(1.5px) scaleX(1.2) scaleY(0.85) !important;
        opacity: 0.7;
      }
    }
  `;
  document.head.appendChild(style);
})();
