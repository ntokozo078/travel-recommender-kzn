import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Note: This assumes your password is 'password'. 
# If you set a different password when installing Postgres, change it below.
db_password = "Ntokozo@02" 

try:
    # Connect to the system database 'postgres' to create a new one
    con = psycopg2.connect(
        dbname='postgres', 
        user='postgres', 
        host='127.0.0.1', 
        password=db_password
    )
    
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()
    
    # Check if DB exists first
    cur.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = 'travel_db'")
    exists = cur.fetchone()
    
    if not exists:
        cur.execute('CREATE DATABASE travel_db;')
        print("✅ Success! Database 'travel_db' created.")
    else:
        print("ℹ️ Database 'travel_db' already exists.")

    cur.close()
    con.close()

except Exception as e:
    print(f"❌ Error: {e}")
    print("TIP: If the error is 'password authentication failed', open setup_db.py and fix the password.")