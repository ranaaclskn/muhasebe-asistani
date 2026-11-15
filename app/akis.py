"""LangGraph akışı: soruyu ANLA -> doğru kola yönlendir -> gerekirse eksik bilgiyi SOR -> onayla -> uygula.

Atölye 7. gün (destek_grafi.py) yapısının bu projeye uyarlaması:
  niyet ─┬─ kayit  -> sql ─────────────────────────────────────────────┐
         ├─ belge  -> rag (önce kendi kayıtlarında açıklama araması) ──┤
         ├─ sorgula-> talep durumu (atölyedeki SORGULA kolu) ───────────┤
         ├─ islem  -> emir_hazirla -> eksik_kontrol ⇄ eksik_sor ⏸      ├─> logla -> END
         │                              └-> ozetle -> onay_sor ⏸ -> uygula ┤
         └─ diğer  -> reddet ───────────────────────────────────────────┘
⏸ = interrupt(): grafik DURUR, durumu SQLite'a kaydedilir (SqliteSaver checkpoint); kullanıcının
cevabıyla Command(resume=...) KALDIĞI YERDEN devam eder. interrupt'tan ÖNCE yan etkili işlem yapılmaz.

Kontrol (proje klasöründen):  python -m app.akis
"""
import sqlite3
import time
import uuid
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.config import VERI_DIR
from app.db import belge_bul, firma_talepleri, kayitli_eposta, planli_islem_ekle, talep_ekle
from app.emirler import (EKSIK_SORULARI, alan_cozumle, emir_cikar, evet_mi, iptal_mi,
                         talep_no_bul, talep_sorgu_kalibi)
from app.kayit import cevapla_kayit, donem_tr, planli_aciklama_cevabi, tarih_tr, tl
from app.log import log_yaz
from app.niyet import baska_firma_adi, niyet_belirle
from app.rag import cevapla_belge

CHECKPOINT_YOLU = VERI_DIR / "langgraph_checkpoint.sqlite"
EMIR_SORUSU = ("Ne yapmamı istersiniz? Örneğin: 'Eylül KDV beyannamemi e-postama gönder', "
               "'5 Aralık'ta 20.000 TL kira ödeyeceğim, kaydet' veya 'Muhasebecimle görüşme talebi oluştur'.")


# 1) DURUM (State): düğümler arasında taşınan "not defteri" (checkpoint ile diske de yazılır)
class Durum(TypedDict, total=False):
    soru: str
    firma_id: str          # OTURUMDAN gelir (Kural 2)
    kullanici_id: int
    baslangic: float
    niyet: dict            # niyet_belirle() çıktısı
    cevap: str
    kaynaklar: list
    arac: str              # sql | rag | sorgula | talep | kayit | iptal | ret
    # --- emir (çok adımlı) kolu ---
    emir: str
    alanlar: dict
    eksik: list            # henüz sorulup doldurulmamış alanlar
    deneme: int            # aynı alanda anlaşılmayan cevap sayısı
    ozet: str
    onay: bool
    bitti: bool            # özet aşamasında iş bitti mi (ör. belge bulunamadı / iptal)


# 2) DÜĞÜMLER
def niyet_dugumu(d: Durum):
    baska = baska_firma_adi(d["soru"], d["firma_id"])
    if baska:  # başka firma adı geçiyorsa modele hiç sormadan reddet (T12)
        return {"niyet": {"niyet": "baska_firma", "firma": baska}}
    if talep_sorgu_kalibi(d["soru"]):  # "3 numaralı talebim ne durumda" (atölye SORGULA kolu)
        return {"niyet": {"niyet": "sorgula"}}
    return {"niyet": niyet_belirle(d["soru"])}


def sql_dugumu(d: Durum):
    r = cevapla_kayit(d["soru"], d["firma_id"], d["niyet"])
    return {"cevap": r["cevap"], "kaynaklar": r["kaynaklar"], "arac": "sql"}


def rag_dugumu(d: Durum):
    # Önce kullanıcının KENDİ eklediği kayıtların açıklamalarında ara (ör. "ev satın alma ücreti ne")
    kendi = planli_aciklama_cevabi(d["soru"], d["firma_id"])
    if kendi:
        return {"cevap": kendi["cevap"], "kaynaklar": kendi["kaynaklar"], "arac": "sql"}
    r = cevapla_belge(d["soru"], d["firma_id"])
    kaynak = [r["kanit"]["kaynak"]] if r["atif"] else []  # yalnızca cevapta kullanılan kaynak
    return {"cevap": r["cevap"], "kaynaklar": kaynak, "arac": "rag"}


def sorgula_dugumu(d: Durum):
    """Talep DURUMU: numara varsa o talep, yoksa son talepler. Yalnızca KENDİ firmasının talepleri."""
    talepler = firma_talepleri(d["firma_id"])
    no = talep_no_bul(d["soru"])
    if no is not None:
        t = next((t for t in talepler if t["id"] == no), None)
        if not t:  # başka firmanın talebi de "bulunamadı" (varlığı sızdırılmaz)
            return {"cevap": f"{no} numaralı bir talebiniz bulunamadı.", "kaynaklar": [], "arac": "sorgula"}
        talepler = [t]
    if not talepler:
        return {"cevap": "Henüz bir talebiniz yok.", "kaynaklar": [], "arac": "sorgula"}
    satirlar = [f"- **#{t['id']}** · {t['durum']} · {t['talep']} ({t['olusturma_tarihi'][:10]})" for t in talepler[:5]]
    baslik = "Talebinizin durumu:" if no is not None else "Son talepleriniz:"
    return {"cevap": baslik + "\n\n" + "\n".join(satirlar),
            "kaynaklar": [f"talep:{t['id']}" for t in talepler[:5]], "arac": "sorgula"}


# --- EMİR KOLU (çok adımlı) ---
def emir_hazirla(d: Durum):
    n = d["niyet"]
    eksik = list(n.get("eksik", [])) if n.get("emir") else ["emir"]
    return {"emir": n.get("emir") or "", "alanlar": dict(n.get("alanlar", {})), "eksik": eksik,
            "deneme": 0, "bitti": False}


def eksik_kontrol(d: Durum):
    return {}  # yalnızca yönlendirme noktası (atölyedeki next_question)


def eksik_rota(d: Durum):
    if d.get("bitti"):
        return "logla"
    return "eksik_sor" if d.get("eksik") else "ozetle"


def eksik_sor(d: Durum):
    """Eksik alanı SOR ve cevabı bekle. interrupt'tan ÖNCE yan etki yok (resume düğümü baştan çalıştırır)."""
    alan = d["eksik"][0]
    soru = EMIR_SORUSU if alan == "emir" else EKSIK_SORULARI[alan]
    if d.get("deneme"):
        soru = "Anlayamadım, tekrar yazar mısınız? " + soru
    cevap = str(interrupt({"tur": "alan", "alan": alan, "soru": soru}))

    if iptal_mi(cevap):
        return {"bitti": True, "cevap": "Tamam, işlemi iptal ettim. Hiçbir kayıt oluşturulmadı.",
                "kaynaklar": [], "arac": "iptal"}
    if alan == "emir":  # "ne yapmamı istersiniz?" cevabı yeni bir emir cümlesidir
        e = emir_cikar(cevap)
        if e["emir"]:
            return {"emir": e["emir"], "alanlar": e["alanlar"], "eksik": e["eksik"], "deneme": 0, "soru": cevap}
    else:
        deger = alan_cozumle(alan, cevap)
        if deger is not None:
            alanlar = {**d["alanlar"], alan: deger}
            # Aynı cevapta diğer eksik alanlar da varsa onları da al ("Eylül KDV", "5 Aralık 20 bin")
            for diger in d["eksik"][1:]:
                if (dv := alan_cozumle(diger, cevap)) is not None:
                    alanlar[diger] = dv
            return {"alanlar": alanlar, "eksik": [a for a in d["eksik"] if a not in alanlar], "deneme": 0}
    if d.get("deneme", 0) >= 2:  # 3. anlaşılmayan cevapta vazgeç
        return {"bitti": True, "cevap": "Bilgiyi anlayamadım; işlemi iptal ettim. Lütfen talebinizi "
                                        "tek cümlede tekrar yazın.", "kaynaklar": [], "arac": "iptal"}
    return {"deneme": d.get("deneme", 0) + 1}


def ozetle(d: Durum):
    """Kullanıcıya NE yapılacağını göster (atölye: kayıt hazırlığı tamamlandı -> onay)."""
    emir, alanlar, firma_id = d["emir"], dict(d["alanlar"]), d["firma_id"]
    if emir == "planli_ekle":
        ne = "ödeme yapılacak" if alanlar["yon"] == "Gider" else "tahsilat bekleniyor"
        alanlar.setdefault("aciklama", d["soru"][:200])
        ozet = f"📝 Planlı kayıt: **{tarih_tr(alanlar['tarih'])} · {tl(alanlar['tutar_tl'])} {ne} · “{alanlar['aciklama']}”**"
    elif emir == "belge_gonder":
        belge = belge_bul(firma_id, alanlar["belge_turu"], alanlar["donem"])
        if not belge:
            return {"bitti": True, "cevap": "İstediğiniz beyanname kayıtlarınızda bulunamadı; dönemi kontrol "
                                            "eder misiniz?", "kaynaklar": [], "arac": "talep_eksik"}
        eposta = kayitli_eposta(firma_id)  # metindeki adres DEĞİL, kayıtlı adres
        alanlar.update(dosya=belge["dosya_adi"], donem=belge["donem"], eposta=eposta)
        ozet = (f"📨 Muhasebeci onayına gidecek talep: **{donem_tr(belge['donem'])} {belge['tur']} "
                f"({belge['dosya_adi']})** kayıtlı e-posta adresinize ({eposta}) gönderilecek.")
        if "@" in d["soru"]:
            ozet += " Güvenlik nedeniyle belgeler yalnızca kayıtlı adresinize gönderilir."
    else:  # gorusme_talebi
        ozet = f"📨 Muhasebeci onayına gidecek talep: **Görüşme talebi** “{alanlar.get('konu', d['soru'])}”"
    return {"alanlar": alanlar, "ozet": ozet}


def ozet_rota(d: Durum):
    return "logla" if d.get("bitti") else "onay_sor"


def onay_sor(d: Durum):
    """KULLANICI ONAYI ⏸ (atölye ask_user_approval). Onaysız hiçbir kayıt yazılmaz."""
    cevap = str(interrupt({"tur": "onay", "soru": d["ozet"] + "\n\nOnaylıyor musunuz? (evet / hayır)"}))
    return {"onay": evet_mi(cevap)}


def uygula(d: Durum):
    """Onaydan SONRA tek yan etkili adım. Belge gönderimi yine muhasebeci onayına gider (Kural 5)."""
    if not d.get("onay"):
        return {"cevap": "Tamam, vazgeçtim; hiçbir kayıt oluşturulmadı.", "kaynaklar": [], "arac": "iptal"}
    emir, a, firma_id = d["emir"], d["alanlar"], d["firma_id"]
    if emir == "planli_ekle":
        try:
            no = planli_islem_ekle(firma_id, d.get("kullanici_id"), a["yon"], a["tarih"], a["tutar_tl"], a["aciklama"])
        except ValueError as e:
            return {"cevap": f"Kaydedilemedi: {e}", "kaynaklar": [], "arac": "iptal"}
        return {"cevap": f"✅ Kaydedildi (#{no}). “📅 Planlı ödeme ve tahsilatlarım” bölümünde görebilirsiniz.",
                "kaynaklar": [f"plan#{no}"], "arac": "kayit"}
    ozet = d["ozet"].replace("**", "").replace("📨 Muhasebeci onayına gidecek talep: ", "")
    talep_id = talep_ekle(firma_id, d["soru"], emir=emir, detay=a, ozet=ozet)
    return {"cevap": f"📨 Talebiniz muhasebecinize iletildi (talep no: {talep_id}). Muhasebeciniz onayladıktan "
                     f"sonra işlem yapılacak. Durumunu “{talep_id} numaralı talebim ne durumda?” diye sorabilirsiniz.",
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
            d.get("arac", ""), d.get("kaynaklar", []), d.get("cevap", ""), sure_ms)
    return {}


# 3) YÖNLENDİRME: niyete göre hangi düğüme gidilecek?
def yonlendir(d: Durum):
    return {"kayit": "sql", "belge": "rag", "islem": "emir_hazirla",
            "sorgula": "sorgula"}.get(d["niyet"]["niyet"], "reddet")


# 4) GRAFİĞİ KUR (checkpoint ile)
def akis_kur(checkpoint_yolu=CHECKPOINT_YOLU):
    g = StateGraph(Durum)
    for ad, fn in [("niyet", niyet_dugumu), ("sql", sql_dugumu), ("rag", rag_dugumu),
                   ("sorgula", sorgula_dugumu), ("emir_hazirla", emir_hazirla),
                   ("eksik_kontrol", eksik_kontrol), ("eksik_sor", eksik_sor), ("ozetle", ozetle),
                   ("onay_sor", onay_sor), ("uygula", uygula), ("reddet", reddet_dugumu),
                   ("logla", logla_dugumu)]:
        g.add_node(ad, fn)
    g.add_edge(START, "niyet")
    g.add_conditional_edges("niyet", yonlendir, ["sql", "rag", "sorgula", "emir_hazirla", "reddet"])
    g.add_edge("emir_hazirla", "eksik_kontrol")
    g.add_conditional_edges("eksik_kontrol", eksik_rota, ["eksik_sor", "ozetle", "logla"])
    g.add_edge("eksik_sor", "eksik_kontrol")  # soru-cevap döngüsü
    g.add_conditional_edges("ozetle", ozet_rota, ["onay_sor", "logla"])
    g.add_edge("onay_sor", "uygula")
    for dugum in ["sql", "rag", "sorgula", "uygula", "reddet"]:
        g.add_edge(dugum, "logla")
    g.add_edge("logla", END)
    baglanti = sqlite3.connect(str(checkpoint_yolu), check_same_thread=False)  # Streamlit iş parçacıkları
    return g.compile(checkpointer=SqliteSaver(baglanti))


asistan = akis_kur()


def _sonuc(cikti):
    """Arayüze tek tip sonuç: bitti mi, yoksa kullanıcıdan cevap mı bekleniyor?"""
    bekleyen = None
    if cikti.get("__interrupt__"):
        bekleyen = cikti["__interrupt__"][0].value
    return {"cevap": bekleyen["soru"] if bekleyen else cikti.get("cevap", ""),
            "kaynaklar": [] if bekleyen else cikti.get("kaynaklar", []),
            "arac": "soru" if bekleyen else cikti.get("arac", ""),
            "niyet": cikti.get("niyet", {}), "bekleyen": bekleyen}


def sor(soru, firma_id, kullanici_id=None, thread_id=None):
    """YENİ soru. Her soru yeni bir thread_id ile başlar; cevap bekleniyorsa sonuç['bekleyen'] doludur."""
    cfg = {"configurable": {"thread_id": thread_id or uuid.uuid4().hex}, "recursion_limit": 60}
    cikti = asistan.invoke({"soru": soru, "firma_id": firma_id, "kullanici_id": kullanici_id,
                            "baslangic": time.time()}, cfg)
    return {**_sonuc(cikti), "thread_id": cfg["configurable"]["thread_id"]}


def devam(cevap, thread_id):
    """Bekleyen soruya kullanıcının cevabıyla KALDIĞI YERDEN devam et (atölye: Command(resume=...))."""
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    return {**_sonuc(asistan.invoke(Command(resume=cevap), cfg)), "thread_id": thread_id}


def _kontrol():
    """Uçtan uca: bilgi kolları + çok adımlı emir (soru-cevap-onay) + talep sorgusu."""
    from app.db import baglan
    for firma, soru in [("F001", "Ekim SGK primi ödendi mi?"),
                        ("F001", "Eylül KDV beyannamemde ödenecek KDV ne kadardı?"),
                        ("F001", "Demo Yazılım'ın Ekim KDV tutarı ne kadar?"),
                        ("F003", "Hangi hisseyi almalıyım?")]:
        s = sor(soru, firma)
        print(f"\n[{firma}] {soru}\n  arac={s['arac']} kaynaklar={s['kaynaklar']}\n  cevap: {s['cevap']}")

    print("\n--- ÇOK ADIMLI EMİR (F001) ---")
    adimlar = ["Beyannamemi e-postama gönder", "KDV", "Eylül", "evet"]
    s = sor(adimlar[0], "F001")
    print(f"KULLANICI: {adimlar[0]}\nASİSTAN: {s['cevap']}")
    for cevap in adimlar[1:]:
        s = devam(cevap, s["thread_id"])
        print(f"KULLANICI: {cevap}\nASİSTAN: {s['cevap']}")
    s = sor("Taleplerim ne durumda?", "F001")
    print(f"KULLANICI: Taleplerim ne durumda?\nASİSTAN: {s['cevap']}")

    con = baglan()
    talep = con.execute("SELECT id, durum, ozet FROM talepler ORDER BY id DESC LIMIT 1").fetchone()
    con.close()
    print("\n--- KONTROL ---")
    print("OK   " if talep and talep["durum"] == "Onay bekliyor" else "HATA ", "son talep:", dict(talep) if talep else None)


if __name__ == "__main__":
    _kontrol()
