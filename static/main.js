// ============================================
// MAIN.JS - OneInBox Sistema de Mensajería
// ============================================

// Variables globales
let autoGenerateInterval = null;

// ============================================
// CARGAR MENSAJES
// ============================================
async function loadMessages() {
    try {
        const res = await fetch("/api/messages");
        const messages = await res.json();
        
        const box = document.getElementById("messages");
        
        if (messages.length === 0) {
            box.innerHTML = `
                <div class="text-center py-16 opacity-60">
                    <div class="text-6xl mb-4">📭</div>
                    <p class="text-xl font-bold">No hay mensajes aún</p>
                    <p class="text-sm mt-2">Usa el simulador o espera la generación automática</p>
                </div>
            `;
            return;
        }

        // Limpiar y renderizar mensajes
        box.innerHTML = "";
        
        // Mostrar solo los últimos 50 mensajes para performance
        const recentMessages = messages.slice(-50);
        
        recentMessages.forEach((m, index) => {
            const messageDiv = createMessageElement(m, index);
            box.appendChild(messageDiv);
        });

        // Scroll al final
        box.scrollTop = box.scrollHeight;
        
        // Actualizar estadísticas
        loadStats();
        
    } catch (error) {
        console.error('Error cargando mensajes:', error);
    }
}

// ============================================
// CREAR ELEMENTO DE MENSAJE
// ============================================
function createMessageElement(m, index) {
    const div = document.createElement("div");
    div.className = "message-item";
    div.style.animationDelay = `${index * 0.05}s`;
    
    const isBot = m.type === "bot";
    const platform = m.platform || "Desconocido";
    const customer = m.customer || "Anónimo";
    const time = m.time || "--:--";
    const content = m.content || "";
    const icon = m.icon || "💬";
    
    // Clases según plataforma - diseño plano
    let borderClass = "";
    let iconBgClass = "";
    
    if (isBot) {
        borderClass = "border-bot";
        iconBgClass = "bg-bot";
    } else {
        if (platform === "WhatsApp") {
            borderClass = "border-whatsapp";
            iconBgClass = "bg-whatsapp";
        }
        if (platform === "Facebook") {
            borderClass = "border-facebook";
            iconBgClass = "bg-facebook";
        }
        if (platform === "Instagram") {
            borderClass = "border-instagram";
            iconBgClass = "bg-instagram";
        }
    }
    
    div.innerHTML = `
        <div class="card p-4 ${borderClass} hover:shadow-lg transition-shadow">
            <!-- Header -->
            <div class="flex items-center justify-between mb-3">
                <div class="flex items-center gap-3">
                    <div class="platform-icon ${iconBgClass}">
                        ${icon}
                    </div>
                    <div>
                        <p class="font-semibold text-sm text-slate-900 dark:text-white">${customer}</p>
                        <p class="text-xs text-slate-500 dark:text-slate-400">${platform}</p>
                    </div>
                </div>
                <div class="text-right">
                    <p class="text-xs font-mono text-slate-500 dark:text-slate-400">${time}</p>
                    ${isBot ? '<span class="inline-block px-2 py-1 bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 rounded-md text-xs font-semibold mt-1">AUTO</span>' : ''}
                </div>
            </div>
            
            <!-- Content -->
            <div class="pl-13 bg-slate-50 dark:bg-slate-900 rounded-lg p-3 border border-slate-200 dark:border-slate-800">
                <p class="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">${content}</p>
            </div>
        </div>
    `;
    
    return div;
}

// ============================================
// CARGAR ESTADÍSTICAS
// ============================================
async function loadStats() {
    try {
        const res = await fetch("/api/stats");
        const stats = await res.json();
        
        // Animar números
        animateNumber("stat-total", stats.total);
        animateNumber("stat-whatsapp", stats.whatsapp);
        animateNumber("stat-instagram", stats.instagram);
        animateNumber("stat-facebook", stats.facebook);
        
    } catch (error) {
        console.error('Error cargando estadísticas:', error);
    }
}

// ============================================
// ANIMAR NÚMEROS
// ============================================
function animateNumber(elementId, targetValue) {
    const element = document.getElementById(elementId);
    const currentValue = parseInt(element.textContent) || 0;
    
    if (currentValue === targetValue) return;
    
    const duration = 500; // ms
    const steps = 20;
    const stepValue = (targetValue - currentValue) / steps;
    const stepDuration = duration / steps;
    
    let current = currentValue;
    let step = 0;
    
    const interval = setInterval(() => {
        step++;
        current += stepValue;
        
        if (step >= steps) {
            element.textContent = targetValue;
            clearInterval(interval);
        } else {
            element.textContent = Math.round(current);
        }
    }, stepDuration);
}

// ============================================
// GENERAR MENSAJE AUTOMÁTICO
// ============================================
async function generateMessage() {
    try {
        await fetch("/api/generate");
        await loadMessages();
    } catch (error) {
        console.error('Error generando mensaje:', error);
    }
}

// ============================================
// ENVIAR MENSAJE MANUAL
// ============================================
async function sendManualMessage() {
    const platform = document.getElementById("platform-select").value;
    const message = document.getElementById("message-input").value.trim();
    
    if (!message) {
        alert("⚠️ Por favor escribe un mensaje");
        return;
    }
    
    try {
        const response = await fetch("/api/send", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                platform: platform,
                message: message,
                customer: "Usuario Demo"
            })
        });
        
        if (response.ok) {
            // Limpiar input
            document.getElementById("message-input").value = "";
            
            // Feedback visual
            const button = event.target;
            const originalText = button.textContent;
            button.textContent = "✅ ENVIADO!";
            button.classList.add("bg-green-500");
            
            setTimeout(() => {
                button.textContent = originalText;
                button.classList.remove("bg-green-500");
            }, 1500);
            
            // Recargar mensajes
            await loadMessages();
        }
        
    } catch (error) {
        console.error('Error enviando mensaje:', error);
        alert("❌ Error al enviar mensaje");
    }
}

// ============================================
// LIMPIAR MENSAJES
// ============================================
async function clearMessages() {
    if (!confirm("¿Estás seguro de que quieres eliminar todos los mensajes?")) {
        return;
    }
    
    try {
        await fetch("/api/clear", { method: "POST" });
        await loadMessages();
        
        // Feedback
        alert("✅ Mensajes eliminados correctamente");
        
    } catch (error) {
        console.error('Error limpiando mensajes:', error);
        alert("❌ Error al limpiar mensajes");
    }
}

// ============================================
// ENTER para enviar
// ============================================
document.addEventListener('DOMContentLoaded', function() {
    const messageInput = document.getElementById('message-input');
    
    if (messageInput) {
        messageInput.addEventListener('keydown', function(e) {
            // Ctrl/Cmd + Enter para enviar
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                sendManualMessage();
            }
        });
    }
});

// ============================================
// INICIALIZACIÓN
// ============================================

// Cargar mensajes al inicio
loadMessages();

// Auto-generar cada 5 segundos
autoGenerateInterval = setInterval(generateMessage, 5000);

// Actualizar estadísticas cada 2 segundos
setInterval(loadStats, 2000);

// Log de inicio
console.log("🚀 OneInBox iniciado correctamente");
console.log("⚡ Generación automática: Cada 5 segundos");
console.log("📊 Actualización de stats: Cada 2 segundos");
