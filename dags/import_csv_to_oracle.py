from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import pandas as pd
import oracledb
from pathlib import Path

# NHẮC LẠI: Cách làm này KHÔNG an toàn. Nên dùng Airflow Connections.
ORACLE_CONN = {
    "user": "TEST_01",
    "password": "123123",
    "dsn": "host.docker.internal:1521/FREEPDB1" 
}

DATA_DIR = Path("/opt/airflow/dags/dataset") 

def import_csv_to_oracle_manual_fixed():
    print("[INFO] Bắt đầu tiến trình.")
    try:
        conn = oracledb.connect(**ORACLE_CONN)
        cursor = conn.cursor()
        print("[INFO] Kết nối Oracle thành công.")
    except Exception as e:
        print(f"[FATAL] Không thể kết nối tới Oracle: {e}")
        raise # Gây lỗi để Airflow biết task thất bại

    # Vòng lặp qua từng file CSV
    for path in DATA_DIR.rglob("*.csv"):
        print(f"\n--- Bắt đầu xử lý file: {path.name} ---")
    
        try:
            df = pd.read_csv(path, encoding='utf-8-sig')
            print(f"   -> Đọc thành công {len(df)} dòng.")

            table_name = path.stem.replace(" ", "_").upper()
            
            # <<< THÊM MỚI: Logic xóa bảng nếu tồn tại >>>
            try:
                print(f"   -> Đang kiểm tra và xóa bảng cũ (nếu có): {table_name}")
                # Sử dụng PL/SQL để không bị lỗi nếu bảng không tồn tại
                drop_sql = f"""
                BEGIN
                   EXECUTE IMMEDIATE 'DROP TABLE "{table_name}"';
                EXCEPTION
                   WHEN OTHERS THEN
                      IF SQLCODE != -942 THEN
                         RAISE;
                      END IF;
                END;
                """
                cursor.execute(drop_sql)
                print(f"   -> Đã xóa bảng cũ (nếu có).")
            except Exception as e:
                print(f"[WARN] Không thể xóa bảng {table_name} (có thể vì nó không tồn tại): {e}")


            # <<< THAY ĐỔI: Luôn tạo lại bảng >>>
            df.columns = [col.replace(' ', '_').replace('(', '').replace(')', '') for col in df.columns]
            cols_sql = ', '.join([f'"{col}" VARCHAR2(4000)' for col in df.columns])
            create_sql = f'CREATE TABLE "{table_name}" ({cols_sql})'
            cursor.execute(create_sql)
            print(f"   -> Đã tạo lại bảng mới: {table_name}")


            rows_to_insert = [tuple(x) for x in df.astype(str).where(pd.notna(df), None).values]
            
            if rows_to_insert:
                placeholders = ', '.join([':' + str(i+1) for i in range(len(df.columns))])
                insert_sql = f'INSERT INTO "{table_name}" VALUES ({placeholders})'
                
                cursor.executemany(insert_sql, rows_to_insert, batcherrors=True)
                
                
                for error in cursor.getbatcherrors():
                    print(f"[WARN] Lỗi khi insert dòng {error.offset}: {error.message}")

                print(f"   -> Đã chèn {len(rows_to_insert)} dòng.")
            else:
                print("   -> Không có dữ liệu để chèn.")

            conn.commit()
            print(f"--- Xử lý thành công file: {path.name} ---")

        except Exception as e:
            print(f"[ERROR] Lỗi nghiêm trọng khi xử lý file {path.name}: {e}")
            conn.rollback() 
            print(f"--- Đã rollback các thay đổi cho file: {path.name} ---")
            continue

    cursor.close()
    conn.close()
    print("\n[INFO] Hoàn tất toàn bộ tiến trình.")


with DAG(
    dag_id="import_csv_to_oracle",
    start_date=datetime(2023, 1, 1),
    schedule_interval="0 10 * * *",
    catchup=False
) as dag:
    import_task = PythonOperator(
        task_id="import_csv",
        python_callable=import_csv_to_oracle_manual_fixed
    )