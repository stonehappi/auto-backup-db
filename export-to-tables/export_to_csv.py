import csv
import os
import pandas as pd
from botocore.config import Config
from sqlalchemy import create_engine, inspect

# Configuration
BASE_DIR = "/home/sca/document/google-cloud"
OUTPUT_DIR = os.path.join(BASE_DIR, "export-to-tables/warehouse_exports")

DB_CONFIG = {
    "dbname": "lms-prod",
    "user": "postgres",
    "password": "password",
    "host": "127.0.0.1",
    "port": 5432
}

def load_all_tables(engine) -> dict:
    inspector = inspect(engine)
    table_names = [t for t in inspector.get_table_names() if not t.startswith("_")]
    return {t: pd.read_sql_table(t, engine) for t in table_names}


def build_warehouse_tables(raw: dict) -> dict:
    from transform_warehouse import (
        build_dim_date,
        build_dim_student,
        build_dim_teacher,
        build_dim_course,
        build_dim_class,
        build_dim_evaluation_question,
        build_dim_user,
        build_fact_enrollment,
        build_fact_attendance,
        build_fact_grade,
        build_fact_evaluation_rating,
        build_fact_evaluation_text,
        build_fact_permission_request,
    )
    return {
        "dim_date":                build_dim_date(),
        "dim_student":             build_dim_student(raw["Student"], raw["Major"]),
        "dim_teacher":             build_dim_teacher(raw["Teacher"]),
        "dim_course":              build_dim_course(raw["Course"]),
        "dim_class":               build_dim_class(raw["Class"], raw["Semester"]),
        "dim_evaluation_question": build_dim_evaluation_question(raw["Evaluation"]),
        "dim_user":                build_dim_user(raw["User"]),
        "fact_enrollment":         build_fact_enrollment(raw["Enroll"], raw["Schedule"], raw["Class"], raw["Semester"]),
        "fact_attendance":         build_fact_attendance(raw["Attendance"], raw["ScheduleTimes"], raw["Schedule"], raw["User"]),
        "fact_grade":              build_fact_grade(raw["Score"], raw["ScoreSemester"], raw["Semester"]),
        "fact_evaluation_rating":  build_fact_evaluation_rating(raw["EvaluateRate"], raw["Enroll"], raw["Schedule"], raw["Class"], raw["Semester"]),
        "fact_evaluation_text":    build_fact_evaluation_text(raw["EvaluateText"], raw["Enroll"], raw["Schedule"]),
        "fact_permission_request": build_fact_permission_request(raw["Permission"], raw["User"]),
    }

def export_tables():

    conn_str = (
        f"postgresql+psycopg2://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
        f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
    )
    engine = create_engine(conn_str)

    try:
        # ── Step 1: Load ──────────────────────────────────────────────────────
        print("Loading source tables...")
        raw = load_all_tables(engine)

        # save all tables in excel
        # for name, df in raw.items():
        #     path = os.path.join(BASE_DIR, "export-to-tables/tables", f"{name}.csv")
        #     df.to_csv(path, index=False)


        # ── Step 2: Transform & save warehouse CSVs ───────────────────────────
        print("\n--- Transforming to warehouse (Star Schema) ---")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        warehouse = build_warehouse_tables(raw)
        for name, df in warehouse.items():
            path = os.path.join(OUTPUT_DIR, f"{name}.csv")
            # Free-text columns may contain commas/newlines — quote all fields for that table
            quote = csv.QUOTE_ALL if name == "fact_evaluation_text" else csv.QUOTE_MINIMAL
            df.to_csv(path, index=False, quoting=quote)
            print(f"  Saved {name}.csv ({len(df)} rows)")
        

        print("\nAll exports and uploads completed successfully.")
    except Exception as e:
        print(f"An error occurred: {e}")
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    export_tables()
