import re

with open('app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line where scores_df is assigned
for i, line in enumerate(lines):
    if line.strip().startswith('scores_df = pd.read_sql('):
        # Find the closing parenthesis line (could be same line or next)
        j = i
        while j < len(lines) and ')' not in lines[j]:
            j += 1
        # Insert after line j
        insert_idx = j + 1
        # Build insertion lines
        indent = '        '  # based on existing indentation
        insertion = [
            indent + '# Ensure we have enough forward data for the selected holding period\n',
            indent + 'max_price_date = prices_df["date"].max()\n',
            indent + 'from pandas import Timedelta\n',
            indent + 'cutoff_date = max_price_date - Timedelta(days=selected_period)\n',
            indent + 'signals_df = scores_df[scores_df["date"] <= cutoff_date].copy()\n',
            indent + 'if signals_df.empty:\n',
            indent + '    st.warning(\n',
            indent + '        f"Seçilen {b_period_label} için yeterli ileri tarihli fiyat"\n',
            indent + '        " eşleşmesi olan sinyal bulunamadı. Lütfen daha kısa bir süre"\n',
            indent + '        " seçin veya daha eski bir tarih aralığı için veri senkronizasyonu yapın."\n',
            indent + '    )\n',
            indent + 'else:\n'
        ]
        # We need to adjust the existing if-else block to use signals_df instead of scores_df
        # We'll replace the existing 'else:' block that starts after the empty check.
        # Let's find the line after insertion where we have 'if prices_df.empty or scores_df.empty:'
        # We'll change that to use signals_df later.
        # For simplicity, we'll replace the whole block from 'if prices_df.empty or scores_df.empty:' to the line before 'except Exception as e:'
        # But that's more complex.
        # Instead, we'll just change the variable name used in the engine.run call.
        # We'll keep the existing if empty check using scores_df (still fine) and then after that, we filter.
        # However we need to ensure that if scores_df empty we already warned and returned.
        # So we can keep the existing empty check, then after that we filter signals_df.
        # We'll need to modify the line where engine.run is called to use signals_df.
        # Let's find the line with 'engine = VectorizedBacktestEngine('
        for k in range(insert_idx, len(lines)):
            if lines[k].strip().startswith('engine = VectorizedBacktestEngine('):
                # Find the line with 'report = engine.run(prices_df=prices_df, signals_df=scores_df)'
                for m in range(k, len(lines)):
                    if 'report = engine.run' in lines[m]:
                        # Replace that line
                        lines[m] = lines[m].replace('signals_df=scores_df', 'signals_df=signals_df')
                        break
                break
        # Insert our block at insert_idx
        lines[insert_idx:insert_idx] = insertion
        break

with open('app.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("Patch applied.")
