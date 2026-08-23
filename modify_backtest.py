import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern to find the backtest button block
# We'll replace from the line containing 'if st.button(' up to the line before 'conn.close()'
# but we need to be careful.

# Simpler: replace the whole segment after loading data with our version.
# We'll locate:
#       prices_df = pd.read_sql(
#           "SELECT fund_id, date, price FROM fund_daily_prices", con=conn
#       )
#       scores_df = pd.read_sql(
#           "SELECT fund_id, date, signal FROM fund_scores", con=conn
#       )
#
# and then after the else: block.

# We'll reconstruct using regex.

pattern = re.compile(
    r'(      try:\n'
    r'        prices_df = pd\.read_sql\(.+?\)\n'
    r'        scores_df = pd\.read_sql\(.+?\)\n'
    r'.*?\n'
    r'          else:\n'
    r'            st\.warning\("Veritabanında yeterli fiyat veya skor verisi bulunamadı! Lütfen.*?\)\n'
    r'      except Exception as e:\n'
    r'        st\.error\(f"Backtest çalıştırılırken hata oluştu: {e}"\n'
    r'\)\n'
    r'\n'
    r'conn\.close\(\))',
    re.DOTALL
)

# Not reliable.

# Instead let's do line-by-line replacement using a simple approach: we know the exact lines from earlier view.
# We'll replace from line 977 (the try:) to line 1044 (except block) with new version.

# Let's read lines
with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find start index
start_idx = None
for i, line in enumerate(lines):
    if 'with st.spinner(' in line and 'Veritabanından fiyatlar ve skorlar okunuyor' in line:
        start_idx = i
        break

if start_idx is None:
    print("Could not find start")
    exit(1)

# Find end index of the except block (line with 'conn.close()')
end_idx = None
for i in range(start_idx, len(lines)):
    if lines[i].strip() == 'conn.close()':
        end_idx = i
        break

if end_idx is None:
    print("Could not find end")
    exit(1)

# Build new block
new_block = [
    '      try:\n',
    '        prices_df = pd.read_sql(\n',
    '            "SELECT fund_id, date, price FROM fund_daily_prices", con=conn\n',
    '        )\n',
    '        scores_df = pd.read_sql(\n',
    '            "SELECT fund_id, date, signal FROM fund_scores", con=conn\n',
    '        )\n',
    '\n',
    '        if prices_df.empty or scores_df.empty:\n',
    '          st.warning(\n',
    '              "Veritabanında yeterli fiyat veya skor verisi bulunamadı! Lütfen"\n',
    '              " önce sol menüden veri senkronizasyonu çalıştırın."\n',
    '          )\n',
    '        else:\n',
    '          # Ensure we have enough forward data for the selected holding period\n',
    '          max_price_date = prices_df["date"].max()\n',
    '          # Convert selected_period (int) to a Timedelta\n',
    '          from pandas import Timedelta\n',
    '          cutoff_date = max_price_date - Timedelta(days=selected_period)\n',
    '          # Keep only signals that occur on or before cutoff_date\n',
    '          signals_df = scores_df[scores_df["date"] <= cutoff_date].copy()\n',
    '          if signals_df.empty:\n',
    '              st.warning(\n',
    '                  f"Seçilen {b_period_label} için yeterli ileri tarihli fiyat"\n',
    '                  " eşleşmesi olan sinyal bulunamadı. Lütfen daha kısa bir süre"\n',
    '                  " seçin veya daha eski bir tarih aralığı için veri senkronizasyonu yapın."\n',
    '              )\n',
    '          else:\n',
    '            from backtest.engine import VectorizedBacktestEngine\n',
    '\n',
    '            engine = VectorizedBacktestEngine(\n',
    '                holding_periods=[21, 63, 126, 252, 756, 1260]\n',
    '            )\n',
    '            report = engine.run(prices_df=prices_df, signals_df=signals_df)\n',
    '\n',
    '            key_str = f"{selected_period}_days_performance"\n',
    '            if report and key_str in report:\n',
    '              metrics = report[key_str]\n',
    '\n',
    '              if metrics["analyzed_signals"] == 0:\n',
    '                st.warning(\n',
    '                    f"Seçilen {b_period_label} için yeterli ileri tarihli fiyat"\n',
    '                    " eşleşmesi bulunamadı."\n',
    '              )\n',
    '              else:\n',
    '                st.success(f"Backtest ({b_period_label}) başarıyla tamamlandı!")\n',
    '\n',
    '                m1, m2, m3, m4 = st.columns(4)\n',
    '                m1.metric(\n',
    '                    "Strateji Ortalama Getirisi",\n',
    '                    f"%{metrics[\"average_return\"]:+.2f}",\n',
    '                    f"{metrics[\"analyzed_signals\"]} İşlem",\n',
    '                )\n',
    '                m2.metric(\n',
    '                    "İsabet Oranı (Hit Ratio)", f"%{metrics[\"hit_ratio\"]:.1f}"\n',
    '                )\n',
    '                m3.metric("Sharpe Oranı", f"{metrics[\"sharpe_ratio\"]:.2f}")\n',
    '                m4.metric("Maksimum Düşüş", f"%{metrics[\"max_drawdown\"]:.2f}")\n',
    '\n',
    '                st.markdown("---")\n',
    '                st.subheader("📋 Simülasyon İşlem Detayları")\n',
    '                trades_df = metrics["trades_df"]\n',
    '                if not trades_df.empty:\n',
    '                  display_trades = trades_df.copy()\n',
    '                  display_trades["return"] = (\n',
    '                      (display_trades["return"] * 100).round(2).astype(str) + "%"\n',
    '                  )\n',
    '                  display_trades.columns = [\n',
    '                      "Fon ID",\n',
    '                      "Giriş Tarihi",\n',
    '                      "Çıkış Tarihi",\n',
    '                      "Giriş Fiyatı",\n',
    '                      "Çıkış Fiyatı",\n',
    '                      "Getiri (%)",\n',
    '                  ]\n',
    '                  st.dataframe(\n',
    '                      display_trades.head(100), use_container_width=True\n',
    '                  )\n',
    '            else:\n',
    '              st.warning("Seçilen periyot için rapor oluşturulamadı.")\n',
    '      except Exception as e:\n',
    '        st.error(f"Backtest çalıştırılırken hata oluştu: {e}')\n'

# Replace lines
new_lines = lines[:start_idx] + new_block + lines[end_idx+1:]

with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Backtest block updated.")
