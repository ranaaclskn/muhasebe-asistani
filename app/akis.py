"""LangGraph akışı: niyet -> {sql, rag, talep, reddet} -> logla -> END.

Kontrol (proje klasöründen):  python -m app.akis
"""
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.db import talep_ekle
from app.kayit import cevapla_kayit
from app.log import log_yaz
from app.niyet import baska_firma_adi, niyet_belirle
from app.rag import cevapla_belge


# 1) DURUM (State): düğümler arasında taşınan "not defteri"
class Durum(TypedDict, total=False):
    soru: str
    firma_id: str          # OTURUMDAN gelir (Kural 2)
    kullanici_id: int
    baslangic: float
    niyet: dict            # niyet_belirle() çıktısı
    cevap: str
    kaynaklar: list
    arac: str              # sql | rag | talep | ret


    # 2) DÜĞÜMLER: her biri Durum'u alır, değişen alanları sözlük olarak döndürür
def niyet_dugumu(d: Durum):
    baska = baska_firma_adi(d["soru"], d["firma_id"])
    if baska:  # başka firma adı geçiyorsa modele hiç sormadan reddet (T12)
        return {"niyet": {"niyet": "baska_firma", "firma": baska}}
    return {"niyet": niyet_belirle(d["soru"])}


def sql_dugumu(d: Durum):
    r = cevapla_kayit(d["soru"], d["firma_id"], d["niyet"])
    return {"cevap": r["cevap"], "kaynaklar": r["kaynaklar"], "arac": "sql"}


def rag_dugumu(d: Durum):
    r = cevapla_belge(d["soru"], d["firma_id"])
    kaynak = [r["kanit"]["kaynak"]] if r["atif"] else []  # yalnızca cevapta kullanılan kaynak
    return {"cevap": r["cevap"], "kaynaklar": kaynak, "arac": "rag"}


def talep_dugumu(d: Durum):
    talep_id = talep_ekle(d["firma_id"], d["soru"])  # Kural 5: sadece KAYDET, dışarı bir şey gönderme
    return {"cevap": f"Talebiniz muhasebecinize iletildi (talep no: {talep_id}). "
                     "Muhasebeciniz onayladıktan sonra işlem yapılacak.",
            "kaynaklar": [f"talep:{talep_id}"], "arac": "talep"}


def reddet_dugumu(d: Durum):
    if d["niyet"]["niyet"] == "baska_firma":
        cevap = (f"Yalnızca kendi firmanızın bilgilerini görebilirsiniz; "
                 f"{d['niyet']['firma']} hakkında bilgi veremem.")
    else:
        cevap = ("Ben yalnızca vergi, prim, beyanname ve fatura kayıtlarınızla ilgili sorulara "
                 "yardımcı olabilirim. Bu konuda muhasebecinize danışabilirsiniz.")
    return {"cevap": cevap, "kaynaklar": [], "arac": "ret"}


def logla_dugumu(d: Durum):
    sure_ms = int((time.time() - d["baslangic"]) * 1000)
    log_yaz(d.get("kullanici_id"), d["firma_id"], d["soru"], d["niyet"]["niyet"],
            d["arac"], d["kaynaklar"], d["cevap"], sure_ms)
    return {}



    # 3) YÖNLENDİRME: niyete göre hangi düğüme gidilecek?
def yonlendir(d: Durum):
    return {"kayit": "sql", "belge": "rag", "islem": "talep"}.get(d["niyet"]["niyet"], "reddet")


# 4) GRAFİĞİ KUR
graf = StateGraph(Durum)
graf.add_node("niyet", niyet_dugumu)
graf.add_node("sql", sql_dugumu)
graf.add_node("rag", rag_dugumu)
graf.add_node("talep", talep_dugumu)
graf.add_node("reddet", reddet_dugumu)
graf.add_node("logla", logla_dugumu)

graf.add_edge(START, "niyet")
graf.add_conditional_edges("niyet", yonlendir, ["sql", "rag", "talep", "reddet"])
for dugum in ["sql", "rag", "talep", "reddet"]:
    graf.add_edge(dugum, "logla")
graf.add_edge("logla", END)

asistan = graf.compile()


def sor(soru, firma_id, kullanici_id=None):
    """Arayüzün çağıracağı tek fonksiyon."""
    return asistan.invoke({"soru": soru, "firma_id": firma_id, "kullanici_id": kullanici_id,
                           "baslangic": time.time()})


def _kontrol():
    """CLAUDE.md Adım 8 Kontrol: talep sorusu sonrası talepler'de 'Onay bekliyor'; loglar'da kayıt."""
    from app.db import baglan
    sorular = [("F001", "Ekim SGK primi ödendi mi?"),
               ("F001", "Eylül KDV beyannamemde ödenecek KDV ne kadardı?"),
               ("F001", "Son muhtasar beyannamemi e-postama gönder."),
               ("F001", "Demo Yazılım'ın Ekim KDV tutarı ne kadar?"),
               ("F003", "Hangi hisseyi almalıyım?")]
    for firma, soru in sorular:
        s = sor(soru, firma)
        print(f"\n[{firma}] {soru}\n  niyet={s['niyet']['niyet']} arac={s['arac']} kaynaklar={s['kaynaklar']}"
              f"\n  cevap: {s['cevap']}")

    con = baglan()
    talep = con.execute("SELECT id, firma_id, talep_metni, durum FROM talepler ORDER BY id DESC LIMIT 1").fetchone()
    loglar = con.execute("SELECT soru, niyet, arac, sure_ms FROM loglar ORDER BY id DESC LIMIT 5").fetchall()
    con.close()
    print("\n--- KONTROL ---")
    print("OK   " if talep and talep["durum"] == "Onay bekliyor" else "HATA ", "son talep:", dict(talep) if talep else None)
    print("OK   " if len(loglar) == 5 else "HATA ", f"loglar tablosunda son {len(loglar)} kayıt:")
    for l in reversed(loglar):
        print("      ", dict(l))


if __name__ == "__main__":
    _kontrol()