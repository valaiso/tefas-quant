"""funds tablosundaki kategori ve nitelikli bayrağını FVT verisiyle düzeltir."""

# Anlamsız / boş kategoriler: FVT kategorisi varsa onunla değiştirilir.
JUNK_CATEGORIES = ("Yatırım Fonu", "Yatirim Fonu", "Diğer", "")


# FVT kategori adı -> funds.category'de kullanılan ad
FVT_CATEGORY_MAP = {
    "Altın Fonu": "Altın",
    "Altın Ve Diğer Kıymetli Madenler Fonu": "Altın",
    "Borçlanma Araçları Fonu": "Borçlanma",
    "Değişken Fon": "Değişken",
    "Karma Fon": "Değişken",
    "Fon Sepeti Fonu": "Fon Sepeti",
    "Yabancı Fon Sepeti Fonu": "Fon Sepeti",
    "Hisse Senedi Fonu": "Hisse Senedi",
    "Hisse Senedi Yoğun": "Hisse Senedi",
    "Katılım Fonu": "Katılım",
    "Kisa Vadeli Kira Sertifikalari Katilim Fonu": "Katılım",
    "Para Piyasası Fonu": "Para Piyasası",
    "Serbest Fon": "Serbest",
}


def _clean_fvt_category(name):
    name = (name or "").strip()
    if name in FVT_CATEGORY_MAP:
        return FVT_CATEGORY_MAP[name]
    for suffix in (" Fonu", " Fon"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name or None


def refresh_fund_attributes(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(fund_external_metrics)")}
    if "fvt_category" not in cols:
        return 0, 0

    rows = conn.execute(
        """
        SELECT f.id, e.fvt_category
        FROM funds f JOIN fund_external_metrics e ON e.fund_id = f.id
        WHERE (f.category IS NULL OR f.category IN (?, ?, ?, ?))
          AND e.fvt_category IS NOT NULL
        """,
        JUNK_CATEGORIES,
    ).fetchall()
    recategorized = 0
    for fund_id, fvt_category in rows:
        cat = _clean_fvt_category(fvt_category)
        if cat:
            conn.execute("UPDATE funds SET category = ? WHERE id = ?", (cat, fund_id))
            recategorized += 1

    # FVT'nin serbest fon bayrağı, başlıktaki anahtar kelimelerden daha güvenilir
    qualified = conn.execute(
        """
        UPDATE funds SET is_qualified = 1
        WHERE id IN (SELECT fund_id FROM fund_external_metrics WHERE is_serbest = 1)
          AND COALESCE(is_qualified, 0) = 0
        """
    ).rowcount
    conn.execute("UPDATE funds SET status = 'ACTIVE' WHERE status IS NULL")
    conn.execute("UPDATE funds SET is_qualified = 0 WHERE is_qualified IS NULL")
    conn.commit()
    return recategorized, qualified
