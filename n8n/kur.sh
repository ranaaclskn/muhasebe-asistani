#!/usr/bin/env bash
# n8n kurulumu (bir kez): test posta kutusu SMTP kimliğini ve iki akışı içe aktarır, akışları yayınlar.
#   - n8n/test_posta_kimligi.json : SMTP -> 127.0.0.1:1025 (scripts/test_posta_kutusu.py)
#   - n8n/akislar.json            : /webhook/talep-onay ve /webhook/hatirlatma akışları
# n8n KAPALIYKEN çalıştırın (açıksa yayınlama n8n yeniden başlayınca devreye girer).
# Çalıştır (proje klasöründen):  bash n8n/kur.sh
# Bellek koruması: her n8n komutu bellek sınırlı bir kafeste çalışır (bkz. n8n/baslat.sh).
set -euo pipefail
cd "$(dirname "$0")"
export N8N_DIAGNOSTICS_ENABLED=false NODE_OPTIONS="--max-old-space-size=450"

n8n_komut() {
    if command -v systemd-run >/dev/null && systemd-run --user --scope -q true 2>/dev/null; then
        systemd-run --user --scope -q -p MemoryMax="${N8N_BELLEK:-700M}" -p MemorySwapMax=0 \
            --setenv=PATH="$PATH" --working-directory="$PWD" -- npx n8n "$@"
    else
        npx n8n "$@"
    fi
}

echo "1/3 SMTP kimliği içe aktarılıyor (test posta kutusu)..."
n8n_komut import:credentials --input=test_posta_kimligi.json

echo "2/3 Akışlar içe aktarılıyor..."
n8n_komut import:workflow --input=akislar.json

echo "3/3 Akışlar yayınlanıyor (webhook adresleri ancak yayındaki akışta çalışır)..."
n8n_komut publish:workflow --id=MuhasebeTalepOn1
n8n_komut publish:workflow --id=MuhasebeHatirla1

echo "Tamam. n8n'i başlatın:  bash n8n/baslat.sh"
