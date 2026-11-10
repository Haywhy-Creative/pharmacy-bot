import sqlite3
import os

DB_NAME = "pharmacy_bot.db"

def view_chat_history():
    # Check if database file exists
    if not os.path.exists(DB_NAME):
        print(f"\n❌ The database file '{DB_NAME}' does not exist yet.")
        print("💡 Tip: Make sure you run your bot (`python bot.py`) and send at least one message to it on Telegram first!\n")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT id, user_id, username, message, response, timestamp FROM chat_history")
        rows = cursor.fetchall()

        print(f"\n--- Total Chat Interactions Logged: {len(rows)} ---\n")
        
        if len(rows) == 0:
            print("The database exists, but no chat history has been logged yet. Try chatting with your bot on Telegram!")
            return

        for row in rows:
            print(f"ID: {row[0]}")
            print(f"User ID: {row[1]} | Username: @{row[2]}")
            print(f"Time: {row[5]}")
            print(f"Patient Message: {row[3]}")
            print(f"AI Bot Response: {row[4][:100]}...") # Print first 100 chars
            print("-" * 50)

    except sqlite3.OperationalError:
        print("\n❌ The 'chat_history' table does not exist in the database yet.")
        print("💡 Tip: Run `python bot.py` at least once so `init_db()` can create the table.\n")
    
    finally:
        conn.close()

if __name__ == "__main__":
    view_chat_history()