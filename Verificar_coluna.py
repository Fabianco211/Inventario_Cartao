
import sqlite3

conn = sqlite3.connect('database.db')
cursor = conn.cursor()

for tabela in ['usuarios', 'cartoes', 'historico_inventario']:
    print(f"Colunas da tabela {tabela}:")
    cursor.execute(f"PRAGMA table_info({tabela});")
    for col in cursor.fetchall():
        print(col)
    print("-" * 40)

conn.close()
