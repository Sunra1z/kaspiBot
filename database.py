import aiosqlite

async def init_db():
    async with aiosqlite.connect('receipts.db') as db:
        await db.execute('''
                    CREATE TABLE IF NOT EXISTS receipts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        username TEXT,
                        text_hash TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(text_hash)
                    )
                ''')
        await db.commit()