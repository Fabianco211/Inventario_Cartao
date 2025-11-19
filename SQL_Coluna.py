
import sqlite3

conn = sqlite3.connect('database.db')
cursor = conn.cursor()

cursor.execute("ALTER TABLE usuarios ADD COLUMN planta TEXT;")
cursor.execute("ALTER TABLE cartoes ADD COLUMN planta TEXT;")
cursor.execute("ALTER TABLE historico_inventario ADD COLUMN planta TEXT;")

conn.commit()
conn.close()
