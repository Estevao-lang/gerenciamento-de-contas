// Script para manipulação de datas e melhorias de UX
document.addEventListener('DOMContentLoaded', function() {
    const campoData = document.getElementById('data_vencimento');
    if (campoData) {
        campoData.max = '';
    }

    const valorInput = document.getElementById('valor');
    if (valorInput) {
        valorInput.addEventListener('input', function(e) {
            let value = e.target.value.replace(/\D/g, '');
            value = (value / 100).toFixed(2) + '';
            value = value.replace('.', ',');
            value = value.replace(/(\d)(\d{3})(\d{3}),/g, '$1.$2.$3,');
            value = value.replace(/(\d)(\d{3}),/g, '$1.$2,');
            e.target.value = value;
        });
    }

    const valorFields = document.querySelectorAll('input[type="number"][step="0.01"]');
    valorFields.forEach(field => {
        field.addEventListener('blur', function() {
            this.value = parseFloat(this.value).toFixed(2);
        });
    });
});

// ═══════════════════════════════════════════════════
// FINBOT — Chatbot IA
// ═══════════════════════════════════════════════════

const finbotHistory = [];   // histórico da conversa (memória local)
let finbotAberto = false;

function finbotToggle() {
    const win = document.getElementById('finbot-window');
    const iconOpen  = document.getElementById('finbot-icon-open');
    const iconClose = document.getElementById('finbot-icon-close');
    if (!win) return;

    finbotAberto = !finbotAberto;
    win.style.display = finbotAberto ? 'flex' : 'none';
    iconOpen.style.display  = finbotAberto ? 'none' : 'block';
    iconClose.style.display = finbotAberto ? 'block' : 'none';

    if (finbotAberto) {
        setTimeout(() => document.getElementById('finbot-input')?.focus(), 150);
        finbotScrollBottom();
    }
}

function finbotScrollBottom() {
    const msgs = document.getElementById('finbot-messages');
    if (msgs) msgs.scrollTop = msgs.scrollHeight;
}

function finbotAdicionarMsg(texto, tipo) {
    const msgs = document.getElementById('finbot-messages');
    const div = document.createElement('div');
    div.className = `finbot-msg ${tipo}`;
    const span = document.createElement('span');
    // Formata markdown simples
    span.innerHTML = texto
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');
    div.appendChild(span);
    msgs.appendChild(div);
    finbotScrollBottom();
    return div;
}

async function finbotEnviar() {
    const input = document.getElementById('finbot-input');
    const texto = input.value.trim();
    if (!texto) return;

    input.value = '';
    input.disabled = true;
    document.getElementById('finbot-send')?.setAttribute('disabled', true);

    finbotAdicionarMsg(texto, 'user');
    finbotHistory.push({ role: 'user', content: texto });

    const loadingDiv = finbotAdicionarMsg('...', 'bot loading');

    try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ messages: finbotHistory })
        });
        const data = await res.json();
        loadingDiv.remove();

        const resposta = data.response || data.error || 'Desculpe, não consegui responder agora.';
        finbotAdicionarMsg(resposta, 'bot');
        finbotHistory.push({ role: 'assistant', content: resposta });

    } catch (e) {
        loadingDiv.remove();
        finbotAdicionarMsg('Erro de conexão. Tente novamente.', 'bot');
    }

    input.disabled = false;
    document.getElementById('finbot-send')?.removeAttribute('disabled');
    input.focus();
}