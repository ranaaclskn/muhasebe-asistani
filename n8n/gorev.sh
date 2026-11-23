#!/usr/bin/env bash
# n8n zamanlayıcısının çağırdığı TEK giriş noktası. Yalnızca aşağıdaki iki görev çalışır; başka bir komut
# kabul edilmez (n8n'deki "Execute Command" düğümü yalnızca bu betiği, sabit bir görev adıyla çağırır).
#   hatirlatma   -> scripts/05_hatirlatma.py         (her sabah 09:00: geciken + 3 gün içindeki ödemeler)
#   aylik-rapor  -> scripts/06_aylik_rapor.py --gonder (her ayın 1'i 08:30: geçen ayın PDF raporu)
# Her çalıştırma YENİ bir Python sürecidir: "bugün" tarihi her seferinde doğru hesaplanır.
# Çıktı n8n "Executions" ekranında görünür ve data/gorevler.log dosyasına da eklenir.
# Elle denemek (proje klasöründen):  bash n8n/gorev.sh hatirlatma
set -uo pipefail
KOK="$(cd "$(dirname "$0")/.." && pwd)"
cd "$KOK"
PY="$KOK/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

case "${1:-}" in
    hatirlatma)  KOMUT=("$PY" scripts/05_hatirlatma.py) ;;
    aylik-rapor) KOMUT=("$PY" scripts/06_aylik_rapor.py --gonder) ;;
    *) echo "Bilinmeyen görev: '${1:-}' (izinli: hatirlatma, aylik-rapor)" >&2; exit 2 ;;
esac

mkdir -p data
CIKTI="$("${KOMUT[@]}" 2>&1)"
KOD=$?
{ echo "=== $(date '+%Y-%m-%d %H:%M:%S') · $1 · çıkış kodu $KOD"; echo "$CIKTI"; } >> data/gorevler.log
echo "$CIKTI"
exit $KOD
