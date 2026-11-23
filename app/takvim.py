"""Vergi takvimi: yasal son ödeme günleri ve tatil kaydırması (VUK md. 18).

Kayıt (tahakkuk) henüz yokken de "KDV'yi en geç ne zaman ödemeliyim?" sorusu cevaplanabilsin diye:
ay başında (ör. 2 Aralık) Kasım dönemi beyannameleri verilmemiştir ama son günleri bellidir.
"""
from datetime import date, timedelta
import calendar

# 2026–2027 resmî tatilleri (tam gün). Arife yarım gündür, iş günü sayılır.
TATILLER = {
    "2026-01-01", "2026-03-20", "2026-03-21", "2026-03-22", "2026-04-23", "2026-05-01", "2026-05-19",
    "2026-05-27", "2026-05-28", "2026-05-29", "2026-05-30", "2026-07-15", "2026-08-30", "2026-10-29",
    "2027-01-01", "2027-03-10", "2027-03-11", "2027-03-12", "2027-04-23", "2027-05-01", "2027-05-17",
    "2027-05-18", "2027-05-19", "2027-05-20", "2027-07-15", "2027-08-30", "2027-10-29",
}

# Ödeme ayındaki yasal gün: KDV 28, Muhtasar 26, SGK primi ayın son günü, geçici vergi 17
_GUN = {"KDV": 28, "Muhtasar": 26, "Geçici vergi": 17}
# 4. dönem geçici vergi beyannamesi verilmez: geçici vergi yalnızca Mayıs, Ağustos, Kasım'da ödenir
GECICI_AYLAR = (5, 8, 11)


def is_gunu(iso):
    """'2026-11-28' (cumartesi) -> '2026-11-30' (pazartesi). İş günüyse aynen döner."""
    g = date.fromisoformat(iso)
    while g.weekday() >= 5 or g.isoformat() in TATILLER:
        g += timedelta(days=1)
    return g.isoformat()


def yasal_son_tarih(tur, odeme_ayi):
    """'KDV', '2026-12' -> '2026-12-28' (tatildeyse ilk iş günü). Geçici vergi o ay ödenmiyorsa None."""
    y, a = int(odeme_ayi[:4]), int(odeme_ayi[5:7])
    if tur == "Geçici vergi" and a not in GECICI_AYLAR:
        return None
    gun = _GUN.get(tur) or calendar.monthrange(y, a)[1]  # SGK primi: ayın son günü
    return is_gunu(date(y, a, gun).isoformat())


def sonraki_son_tarih(tur, bugun, ay=None):
    """Bugünden sonraki (ya da verilen ayın) yasal son günü ve ait olduğu dönem: ('2026-12-28', '2026-11').
    Dönem = ödeme ayından bir önceki ay (geçici vergide çeyrek: 'Tem–Eyl' gibi gösterimi çağıran yapar)."""
    y, a = (int(ay[:4]), int(ay[5:7])) if ay else (int(bugun[:4]), int(bugun[5:7]))
    for _ in range(14):
        tarih = yasal_son_tarih(tur, f"{y}-{a:02d}")
        if tarih and (ay or tarih >= bugun):
            donem = f"{y - (a == 1)}-{(a - 2) % 12 + 1:02d}"
            return tarih, donem
        if ay:
            return None
        y, a = (y + 1, 1) if a == 12 else (y, a + 1)
    return None
