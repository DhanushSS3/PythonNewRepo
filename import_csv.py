import pandas as pd
from sqlalchemy import create_engine

# Load CSV
csv_path = r'C:\Users\Dhanush\Downloads\groups1.csv'
df = pd.read_csv(csv_path)

# Drop auto-managed columns
for col in ['id', 'created_at', 'updated_at']:
    if col in df.columns:
        df.drop(columns=[col], inplace=True)

# Fill missing optional columns
expected_columns = [
    'symbol', 'name', 'commision_type', 'commision_value_type', 'type',
    'pip_currency', 'show_points', 'swap_buy', 'swap_sell', 'commision',
    'margin', 'spread', 'deviation', 'min_lot', 'max_lot', 'pips',
    'spread_pip', 'sending_orders', 'book'
]

for col in expected_columns:
    if col not in df.columns:
        df[col] = None

# Reorder columns to match DB schema
df = df[expected_columns]

# Connect to MySQL
db_url = "mysql+pymysql://u436589492_testingserver:Lkj%40asd%40123@89.117.188.103:3306/u436589492_testingserver"
# db_url = "mysql+pymysql://u436589492_testingserver:Lkj@asd@123@89.117.188.103:3306/u436589492_testingserver"
engine = create_engine(db_url)

# Append to existing table
df.to_sql('groups', con=engine, if_exists='append', index=False)