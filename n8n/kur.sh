#!/usr/bin/env bash
# n8n kurulumu (bir kez; akışlar değişince yeniden): SMTP kimliğini ve beş akışı içe aktarır, yayınlar.
#   - n8n/test_posta_kimligi.json : SMTP -> 127.0.0.1:1025 (scripts/test_posta_kutusu.py)
#   - n8n/akislar.json            : webhook'lar talep-onay, hatirlatma, aylik-rapor (e-posta gönderir) +
#                                   iki zamanlayıcı: her sabah 09:00 hatırlatma, her ayın 1'i 08:30 aylık rapor
#     Zamanlayıcıların komutundaki __PROJE__ yer tutucusu bu klasörün tam yoluyla değiştirilir.
# n8n KAPALIYKEN çalıştırın (açıksa yayınlama n8n yeniden başlayınca devreye girer).
# Çalıştır (proje klasöründen):  bash n8n/kur.sh
# Bellek koruması: her n8n komutu bellek sınırlı bir kafeste çalışır (bkz. n8n/baslat.sh).
set -euo pipefail
cd "$(dirname "$0")"
export N8N_DIAGNOSTICS_ENABLED=false NODE_OPTIONS="--max-old-space-size=450"
# Zamanlayıcı akışlarındaki "Execute Command" düğümü yayınlanırken tanınsın (baslat.sh ile aynı ayar).
export NODES_EXCLUDE='["n8n-nodes-base.localFileTrigger"]'

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
PROJE="$(cd .. && pwd)"
case "$PROJE" in *'"'*|*\\*|*'|'*) echo "Proje yolunda \" \\ ya da | olmamalı: $PROJE" >&2; exit 1 ;; esac
GECICI="$(mktemp --suffix=.json)"
trap 'rm -f "$GECICI"' EXIT
sed "s|__PROJE__|$PROJE|g" akislar.json > "$GECICI"
n8n_komut import:workflow --input="$GECICI"

echo "3/3 Akışlar yayınlanıyor (webhook adresleri ancak yayındaki akışta çalışır)..."
for KIMLIK in MuhasebeTalepOn1 MuhasebeHatirla1 MuhasebeAylikRp1 MuhasebeSabah091 MuhasebeAyBasi01; do
    n8n_komut publish:workflow --id="$KIMLIK"
done

echo "Tamam. n8n'i başlatın:  bash n8n/baslat.sh"
