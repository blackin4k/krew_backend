import psycopg2
import os

DB_URL = "postgresql://krew_db_user:WXMteDgjBiceQO2On6GRDOXow3ZWaAIE@dpg-d5pb8aer433s73d713jg-a.singapore-postgres.render.com/krew_db"

def fix_cover():
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        # Based on R2 output
        target_cover = "covers/Kaifi_Khalil_Ario_-_Kahani_Suno_2.O_cover.jpg" # LOG CONFIRMEDfilename (or close to it)
        
        print(f"🔄 FINAL FIX: Updating ID 2771 cover to: {target_cover}")
        cur.execute("UPDATE song SET cover_file = %s WHERE id = 2771;", (target_cover,))
        conn.commit()
        print("✅ Update successful.")
        
        conn.close()

    except Exception as e:
        print(f"❌ Update Failed: {e}")

if __name__ == "__main__":
    fix_cover()
