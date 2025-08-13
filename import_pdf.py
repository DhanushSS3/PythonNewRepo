import pandas as pd
import camelot
from sqlalchemy import create_engine

# ==== CONFIG ====
PDF_PATH = r"C:\Users\Dhanush\Downloads\instrument-profile-update-20250714.pdf"
CSV_PREVIEW_PATH = r"C:\Users\Dhanush\Downloads\extracted_instruments.csv"

DB_URL = "mysql+pymysql://u436589492_testingserver:Lkj%40asd%40123@89.117.188.103:3306/u436589492_testingserver"
# DB_URL = "mysql+pymysql://u436589492_testingserver:Lkj@asd@123@89.117.188.103:3306/u436589492_testingserver"
TABLE_NAME = "external_symbol_info"  # Change to your actual table name

# ==== CONTRACT SIZE MAPPING ====
def get_contract_size(symbol):
    s = symbol.upper().replace("-", "_").replace(" ", "_")  # Normalize names

    # FX Pairs
    fx_prefixes = ["AUD", "CAD", "CHF", "CNH", "EUR", "GBP", "JPY", "MXN", "NOK", "NZD", "SEK", "SGD", "TRY", "USD", "ZAR"]
    if any(s.startswith(prefix) for prefix in fx_prefixes) and len(s) <= 6:
        return 100000

    # Metals
    if s.startswith("XAU") and not s.startswith("GAU"):  # Gold in ounces
        return 100
    if s.startswith("XAG"):  # Silver in ounces
        return 5000
    if s.startswith("GAU"):  # Gold in grams
        return 1
    if s.startswith("XPD"):  # Palladium
        return 100
    if s.startswith("XPT"):  # Platinum
        return 100

    # Indices
    index_prefixes = ["GER", "NAS", "SPX", "UK1", "US3", "AUS", "EU5", "FRA", "HK5", "JPN", "VIX", "USDX", "ESP"]
    if any(s.startswith(prefix) for prefix in index_prefixes):
        return 1
    if s in ["US2000"]:
        return 1

    # Oil & Energy
    if s in ["UKOUSD", "USOUSD", "WTIUSD"]:
        return 1000
    if "NGAS" in s:
        return 10000
    if "GASOIL" in s:
        return 100
    if "GASOLINE" in s:
        return 42000

    # Commodities
    commodity_sizes = {
        "COCOA": 10000,
        "COFFEE_ARABICA": 37500,
        "COFFEE_ROBUSTA": 10000,
        "COTTON": 50000,
        "ORANGE_JUICE": 15000,
        "SUGAR_RAW": 112000,
        "SOYBEAN": 5000,
        "WHEAT": 5000
    }
    if s in commodity_sizes:
        return commodity_sizes[s]

    # Crypto
    crypto_suffixes = [
        "USD", "EUR", "USDT", "BTC", "ETH", "BNB", "XRP", "DOGE", "SOL", "LTC", "DOT", "UNI", "MATIC", "AVAX"
    ]
    if any(s.endswith(suffix) for suffix in crypto_suffixes):
        return 1

    # Default
    return 1

# ==== STEP 1: Extract PDF ====
tables = camelot.read_pdf(
    PDF_PATH,
    pages='all',
    flavor='stream',
    strip_text='\n'
)

if not tables:
    raise ValueError("No tables found in PDF.")

df_list = [table.df for table in tables if not table.df.empty]
if not df_list:
    raise ValueError("No valid tables extracted.")

df = pd.concat(df_list, ignore_index=True)

# ==== STEP 2: Select Symbol & Quote columns ====
df.columns = range(df.shape[1])  # Temporary numeric headers
symbol_col_idx = 0
quote_col_idx = 4
df = df[[symbol_col_idx, quote_col_idx]]
df.columns = ["fix_symbol", "profit"]

# ==== STEP 3: Clean Data ====
df["fix_symbol"] = df["fix_symbol"].str.strip()
df["profit"] = df["profit"].str.strip()

# Remove header rows and empty rows
df = df[df["fix_symbol"].str.lower() != "symbol"]
df = df.dropna(subset=["fix_symbol", "profit"])
df = df.drop_duplicates(subset=["fix_symbol"])

# ==== STEP 4: Add Contract Size ====
df["contract_size"] = df["fix_symbol"].apply(get_contract_size)

# ==== STEP 5: Save Preview ====
df.to_csv(CSV_PREVIEW_PATH, index=False)
print(f"✅ Preview saved to {CSV_PREVIEW_PATH}")
print(df.head(10))

# ==== STEP 6: Insert into DB (only new symbols) ====
engine = create_engine(DB_URL)
existing_df = pd.read_sql(f"SELECT fix_symbol FROM {TABLE_NAME}", con=engine)
existing_symbols = set(existing_df["fix_symbol"])
new_df = df[~df["fix_symbol"].isin(existing_symbols)]

if not new_df.empty:
    new_df[["fix_symbol", "profit", "contract_size"]].to_sql(TABLE_NAME, con=engine, if_exists='append', index=False)
    print(f"✅ Inserted {len(new_df)} new symbols into {TABLE_NAME}")
else:
    print("ℹ No new symbols to insert.")
