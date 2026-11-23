#!/usr/bin/env bash
# n8n'i YALNIZCA bu bilgisayardan erişilecek şekilde başlatır (varsayılan npx n8n tüm ağa açık dinler).
# Arayüz: http://localhost:5678   Webhook'lar: http://localhost:5678/webhook/talep-onay , /webhook/hatirlatma
# Çalıştır (proje klasöründen):  bash n8n/baslat.sh     Durdurmak: Ctrl + C
#
# Bellek koruması: bu proje 6 GB RAM'li bir makinede geliştirildi; n8n belleği doldurunca sistem başka
# programları (tarayıcı, editör) kapatabiliyordu. systemd-run varsa n8n bellek sınırlı bir "kafes" içinde
# çalışır: sınır aşılırsa YALNIZCA n8n durur. Sınırı değiştirmek için:  N8N_BELLEK=1200M bash n8n/baslat.sh
set -euo pipefail
export N8N_LISTEN_ADDRESS=127.0.0.1 N8N_DIAGNOSTICS_ENABLED=false
export GENERIC_TIMEZONE=Europe/Istanbul TZ=Europe/Istanbul
export NODE_OPTIONS="--max-old-space-size=600"
BELLEK="${N8N_BELLEK:-900M}"
if command -v systemd-run >/dev/null && systemd-run --user --scope -q true 2>/dev/null; then
    echo "n8n bellek sınırı: $BELLEK (yalnızca n8n etkilenir)"
    exec systemd-run --user --scope -q -p MemoryMax="$BELLEK" -p MemorySwapMax=0 \
        --setenv=PATH="$PATH" -- npx n8n start
fi
exec npx n8n start
