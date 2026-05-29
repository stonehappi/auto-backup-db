"""
transform_warehouse.py
Standalone ETL script: reads CSVs from ./table/ → writes parquet/CSV to ./warehouse/

Usage:
    pip install pandas pyarrow
    python transform_warehouse.py
"""

import csv
import sys
from pathlib import Path

import pandas as pd

# ─── Lookup maps ─────────────────────────────────────────────────────────────

STUDENT_STATUS = {1: "Active", 3: "On Leave", 5: "Graduated", 6: "Withdrawn"}
SHIFT_MAP = {1.0: "Morning", 2.0: "Afternoon"}
USER_TYPE = {1: "Student", 2: "Admin", 3: "Teacher", 4: "Super Admin"}
EVAL_TYPE = {1: "Midterm", 2: "Final"}
CHECKIN_STATUS = {0: "On Time", 1: "Late", 2: "Absent", 3: "Excused"}
CHECKOUT_STATUS = {0.0: "On Time", 1.0: "Late", 2.0: "Early Leave"}
DAY_NAME = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday"}
LETTER_GPA = {
    "A": 4.0, "A-": 3.67, "B+": 3.33, "B": 3.0, "B-": 2.67,
    "C+": 2.33, "C": 2.0, "C-": 1.67, "D+": 1.33, "D": 1.0, "F": 0.0,
}
HOLIDAY_TYPE = {0: "National Holiday", 1: "Royal Holiday", 2: "Special Holiday"}
PERMISSION_STATUS = {1: "Approved", 2: "Pending", 3: "Rejected"}
SCHEDULE_STATUS = {0: "Active", 1: "Inactive", 2: "Cancelled"}

# ─── I/O helpers ─────────────────────────────────────────────────────────────

def load_sources(table_dir: Path) -> dict:
    """Read all CSVs from table_dir into a dict keyed by filename stem."""
    raw = {}
    for p in sorted(table_dir.glob("*.csv")):
        try:
            df = pd.read_csv(p, encoding="utf-8", low_memory=False)
        except Exception as e:
            print(f"  WARN: could not read {p.name}: {e}")
            df = pd.DataFrame()
        raw[p.stem] = df
    return raw


def _save(df: pd.DataFrame, name: str, out_dir: Path) -> None:
    """Write DataFrame to parquet; fall back to CSV if pyarrow is unavailable."""
    if df.empty:
        print(f"  SKIP {name} (empty)")
        return
    try:
        path = out_dir / f"{name}.parquet"
        df.to_parquet(path, index=False)
        print(f"  {name}.parquet  ({len(df):,} rows)")
    except Exception:
        path = out_dir / f"{name}.csv"
        quoting = csv.QUOTE_ALL if "text" in name else csv.QUOTE_MINIMAL
        df.to_csv(path, index=False, quoting=quoting)
        print(f"  {name}.csv  ({len(df):,} rows)")


def _bool_col(series: pd.Series) -> pd.Series:
    """Coerce a string/numeric boolean column to Python bool."""
    return series.astype(str).str.lower().map(
        {"true": True, "false": False, "1": True, "0": False, "nan": False}
    )


def _parse_attendances(att_str):
    """Return (present, late, absent, total) counts from a comma-separated attendance string."""
    if pd.isna(att_str) or str(att_str).strip() == "":
        return 0, 0, 0, 0
    tokens = [t.strip() for t in str(att_str).split(",")]
    present = sum(1 for t in tokens if t == "1")
    late = sum(1 for t in tokens if t.upper() == "L")
    absent = sum(1 for t in tokens if t.upper() == "A")
    return present, late, absent, len(tokens)


# ─── Dimension builders ───────────────────────────────────────────────────────

def build_dim_faculty(raw: dict) -> pd.DataFrame:
    src = raw.get("Faculty", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src.copy()
    if "DeletedAt" in df.columns:
        df = df[df["DeletedAt"].isna()]
    return df.rename(columns={
        "Id": "faculty_key", "Name": "name", "FacultyNameKh": "name_kh",
        "ShortLetter": "short_letter", "Color": "color", "CreatedAt": "created_at",
    })[["faculty_key", "name", "name_kh", "short_letter", "color", "created_at"]]


def build_dim_department(raw: dict) -> pd.DataFrame:
    src = raw.get("Department", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src.copy()
    if "DeletedAt" in df.columns:
        df = df[df["DeletedAt"].isna()]
    fac = raw.get("Faculty", pd.DataFrame())
    if not fac.empty:
        fac_slim = fac[["Id", "Name"]].rename(columns={"Id": "FacultyId", "Name": "faculty_name"})
        df = df.merge(fac_slim, on="FacultyId", how="left")
    else:
        df["faculty_name"] = pd.NA
    return df.rename(columns={
        "Id": "department_key", "Name": "name", "DepartmentNameKh": "name_kh",
        "ShortLetter": "short_letter", "FacultyId": "faculty_key", "CreatedAt": "created_at",
    })[["department_key", "name", "name_kh", "short_letter", "faculty_key", "faculty_name", "created_at"]]


def build_dim_major(raw: dict) -> pd.DataFrame:
    src = raw.get("Major", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src.copy()
    if "DeletedAt" in df.columns:
        df = df[df["DeletedAt"].isna()]
    dept = raw.get("Department", pd.DataFrame())
    if not dept.empty:
        dept_slim = dept[["Id", "Name"]].rename(columns={"Id": "DepartmentId", "Name": "department_name"})
        df = df.merge(dept_slim, on="DepartmentId", how="left")
    else:
        df["department_name"] = pd.NA
    if "AllowRegistration" in df.columns:
        df["AllowRegistration"] = _bool_col(df["AllowRegistration"])
    return df.rename(columns={
        "Id": "major_key", "Name": "name", "Description": "description",
        "DepartmentId": "department_key", "CreatedAt": "created_at",
        "AllowRegistration": "allow_registration",
    })[["major_key", "name", "description", "department_key", "department_name",
        "allow_registration", "created_at"]]


def build_dim_semester(raw: dict) -> pd.DataFrame:
    src = raw.get("Semester", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src.copy()
    if "DeletedAt" in df.columns:
        df = df[df["DeletedAt"].isna()]
    df["StartDate"] = pd.to_datetime(df["StartDate"], errors="coerce").dt.date
    df["EndDate"] = pd.to_datetime(df["EndDate"], errors="coerce").dt.date
    return df.rename(columns={
        "Id": "semester_key", "Semester": "semester_number", "Year": "year_level",
        "AcademicYear": "academic_year", "StartDate": "start_date", "EndDate": "end_date",
        "FinalPeriod": "final_period", "MajorId": "major_key",
        "NumberOfMonths": "number_of_months", "StartMonth": "start_month",
        "CreatedAt": "created_at",
    })[["semester_key", "semester_number", "year_level", "academic_year",
        "start_date", "end_date", "final_period", "major_key",
        "number_of_months", "start_month"]]


def build_dim_student(raw: dict) -> pd.DataFrame:
    src = raw.get("Student", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src[src["DeletedAt"].isna()].copy()
    major = raw.get("Major", pd.DataFrame())
    if not major.empty:
        major_slim = major[["Id", "Name"]].rename(columns={"Id": "MajorId", "Name": "major_name"})
        df = df.merge(major_slim, on="MajorId", how="left")
    else:
        df["major_name"] = pd.NA

    today = pd.Timestamp.today()
    df["DateOfBirth"] = pd.to_datetime(df["DateOfBirth"], errors="coerce")
    df["age"] = ((today - df["DateOfBirth"]).dt.days // 365).astype("Int64")
    df["full_name"] = df["FirstName"].fillna("").str.strip() + " " + df["LastName"].fillna("").str.strip()
    df["full_name_kh"] = df["FirstNameKh"].fillna("").str.strip() + " " + df["LastNameKh"].fillna("").str.strip()
    df["Status"] = pd.to_numeric(df["Status"], errors="coerce")
    df["status_label"] = df["Status"].map(STUDENT_STATUS).fillna("Unknown")
    df["Shift"] = pd.to_numeric(df["Shift"], errors="coerce")
    df["shift_label"] = df["Shift"].map(SHIFT_MAP).fillna("Unknown")
    if "IsScholarship" in df.columns:
        df["IsScholarship"] = _bool_col(df["IsScholarship"])

    return df.rename(columns={
        "Id": "student_key", "StudentId": "student_id", "Batch": "batch",
        "Year": "year_level", "FirstName": "first_name", "LastName": "last_name",
        "FirstNameKh": "first_name_kh", "LastNameKh": "last_name_kh",
        "Gender": "gender", "DateOfBirth": "date_of_birth", "PlaceOfBirth": "place_of_birth",
        "PhoneNumber": "phone_number", "Email": "email", "Status": "status_code",
        "IsScholarship": "is_scholarship", "MajorId": "major_key", "CreatedAt": "created_at",
    })[["student_key", "student_id", "batch", "year_level", "first_name", "last_name",
        "full_name", "first_name_kh", "last_name_kh", "full_name_kh", "gender",
        "date_of_birth", "age", "place_of_birth", "phone_number", "email",
        "status_code", "status_label", "shift_label", "is_scholarship",
        "major_key", "major_name", "created_at"]]


def build_dim_teacher(raw: dict) -> pd.DataFrame:
    src = raw.get("Teacher", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src.copy()
    if "DeletedAt" in df.columns:
        df = df[df["DeletedAt"].isna()]
    dept = raw.get("Department", pd.DataFrame())
    if not dept.empty:
        dept_slim = dept[["Id", "Name"]].rename(columns={"Id": "DepartmentId", "Name": "department_name"})
        df = df.merge(dept_slim, on="DepartmentId", how="left")
    else:
        df["department_name"] = pd.NA
    df["full_name"] = (
        df["Title"].fillna("").str.strip() + " " +
        df["FirstName"].fillna("").str.strip() + " " +
        df["LastName"].fillna("").str.strip()
    ).str.strip()
    # Teacher.Status = "False" means the teacher IS active (field behaves as IsDeleted)
    df["is_active"] = df["Status"].astype(str).str.lower().eq("false")

    cols = {
        "Id": "teacher_key", "Title": "title", "FirstName": "first_name",
        "LastName": "last_name", "Gender": "gender",
        "StartDate": "start_date", "Qualification": "qualification",
        "Room": "room", "OfficeDay": "office_day", "OfficeTime": "office_time",
        "PhoneNumber": "phone_number", "Email": "email",
        "TeachingRate": "teaching_rate", "DepartmentId": "department_key",
    }
    # Khmer name columns differ by export version
    if "FirstNameInKhmer" in df.columns:
        cols["FirstNameInKhmer"] = "first_name_kh"
        cols["LastNameInKhmer"] = "last_name_kh"
    elif "FirstNameKh" in df.columns:
        cols["FirstNameKh"] = "first_name_kh"
        cols["LastNameKh"] = "last_name_kh"
    else:
        df["first_name_kh"] = pd.NA
        df["last_name_kh"] = pd.NA

    df = df.rename(columns=cols)
    out_cols = ["teacher_key", "title", "first_name", "last_name", "full_name",
                "first_name_kh", "last_name_kh", "gender", "start_date", "qualification",
                "room", "office_day", "office_time", "phone_number", "email",
                "teaching_rate", "department_key", "department_name", "is_active"]
    return df[[c for c in out_cols if c in df.columns]]


def build_dim_course(raw: dict) -> pd.DataFrame:
    src = raw.get("Course", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src[src["DeletedAt"].isna()].copy()
    dept = raw.get("Department", pd.DataFrame())
    if not dept.empty:
        dept_slim = dept[["Id", "Name"]].rename(columns={"Id": "DepartmentId", "Name": "department_name"})
        df = df.merge(dept_slim, on="DepartmentId", how="left")
    else:
        df["department_name"] = pd.NA
    if "IsActive" in df.columns:
        df["IsActive"] = _bool_col(df["IsActive"])
    return df.rename(columns={
        "Id": "course_key", "Code": "code", "Name": "name", "NameInKh": "name_kh",
        "Description": "description", "Credit": "credit", "DepartmentId": "department_key",
        "Semester": "semester_number", "Year": "year_level", "IsActive": "is_active",
    })[["course_key", "code", "name", "name_kh", "description", "credit",
        "department_key", "department_name", "semester_number", "year_level", "is_active"]]


def build_dim_class(raw: dict) -> pd.DataFrame:
    src = raw.get("Class", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src.copy()
    if "DeletedAt" in df.columns:
        df = df[df["DeletedAt"].isna()]
    semester = raw.get("Semester", pd.DataFrame())
    if not semester.empty:
        sem_slim = semester[["Id", "AcademicYear", "Semester", "StartDate", "EndDate"]].rename(columns={
            "Id": "SemesterId", "AcademicYear": "academic_year",
            "Semester": "semester_number", "StartDate": "semester_start_date",
            "EndDate": "semester_end_date",
        })
        df = df.merge(sem_slim, on="SemesterId", how="left")
    major = raw.get("Major", pd.DataFrame())
    if not major.empty:
        major_slim = major[["Id", "Name"]].rename(columns={"Id": "MajorId", "Name": "major_name"})
        df = df.merge(major_slim, on="MajorId", how="left")
    else:
        df["major_name"] = pd.NA
    if "IsActive" in df.columns:
        df["IsActive"] = _bool_col(df["IsActive"])
    return df.rename(columns={
        "Id": "class_key", "Name": "name", "Type": "type_code", "Room": "room",
        "SemesterId": "semester_key", "MajorId": "major_key", "Year": "year_level",
        "IsActive": "is_active",
    })[["class_key", "name", "type_code", "room", "semester_key", "academic_year",
        "semester_number", "semester_start_date", "semester_end_date",
        "major_key", "major_name", "year_level", "is_active"]]


def build_dim_schedule(raw: dict) -> pd.DataFrame:
    src = raw.get("Schedule", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src.copy()
    course = raw.get("Course", pd.DataFrame())
    if not course.empty:
        c = course[["Id", "Name"]].rename(columns={"Id": "CourseId", "Name": "course_name"})
        df = df.merge(c, on="CourseId", how="left")
    teacher = raw.get("Teacher", pd.DataFrame())
    if not teacher.empty:
        full = (teacher["Title"].fillna("").str.strip() + " " +
                teacher["FirstName"].fillna("").str.strip() + " " +
                teacher["LastName"].fillna("").str.strip()).str.strip()
        t = pd.DataFrame({"Id": teacher["Id"], "teacher_name": full})
        t = t.rename(columns={"Id": "TeacherId"})
        df = df.merge(t, on="TeacherId", how="left")
    cls = raw.get("Class", pd.DataFrame())
    if not cls.empty:
        cl = cls[["Id", "Name"]].rename(columns={"Id": "ClassId", "Name": "class_name"})
        df = df.merge(cl, on="ClassId", how="left")
    if "IsOnline" in df.columns:
        df["IsOnline"] = _bool_col(df["IsOnline"])
    if "NoAlert" in df.columns:
        df["NoAlert"] = _bool_col(df["NoAlert"])
    return df.rename(columns={
        "Id": "schedule_key", "CourseId": "course_key", "TeacherId": "teacher_key",
        "ClassId": "class_key", "TeachingRateInHours": "teaching_rate_hours",
        "IsOnline": "is_online", "Status": "status", "NoAlert": "no_alert",
    })[["schedule_key", "course_key", "course_name", "teacher_key", "teacher_name",
        "class_key", "class_name", "teaching_rate_hours", "is_online", "status"]]


def build_dim_schedule_time(raw: dict) -> pd.DataFrame:
    src = raw.get("ScheduleTimes", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src.copy()
    df["Day"] = pd.to_numeric(df["Day"], errors="coerce")
    df["day_name"] = df["Day"].map(DAY_NAME).fillna("Unknown")
    if "IsConfirm" in df.columns:
        df["IsConfirm"] = _bool_col(df["IsConfirm"])
    return df.rename(columns={
        "Id": "schedule_time_key", "ScheduleId": "schedule_key",
        "StartTime": "start_time", "EndTime": "end_time", "Room": "room",
        "Label": "label", "Day": "day_of_week", "AmountInHour": "amount_in_hour",
        "IsConfirm": "is_confirmed",
    })[["schedule_time_key", "schedule_key", "start_time", "end_time",
        "room", "label", "day_of_week", "day_name", "amount_in_hour", "is_confirmed"]]


def build_dim_evaluation_question(raw: dict) -> pd.DataFrame:
    src = raw.get("Evaluation", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src.copy()
    if "DeletedAt" in df.columns:
        df = df[df["DeletedAt"].isna()]
    if "IsActive" in df.columns:
        df = df[df["IsActive"].astype(str).str.lower().eq("true")]
    df["type_label"] = df["Type"].map({0: "Rating", 1: "Text"}).fillna("Unknown")
    return df.rename(columns={
        "Id": "evaluation_key", "No": "question_no", "Question": "question_text",
        "Type": "type_code", "DepartmentId": "department_key", "IsActive": "is_active",
    })[["evaluation_key", "question_no", "question_text", "type_code", "type_label",
        "department_key"]]


def build_dim_holiday(raw: dict) -> pd.DataFrame:
    src = raw.get("HolidayEntity", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src.copy()
    if "DeletedAt" in df.columns:
        df = df[df["DeletedAt"].isna()]
    if "Status" in df.columns:
        df = df[df["Status"].astype(str).str.lower().eq("true")]
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
    df["type_label"] = pd.to_numeric(df["Type"], errors="coerce").map(HOLIDAY_TYPE).fillna("Holiday")
    return df.rename(columns={
        "Id": "holiday_key", "Name": "name", "Date": "date_key",
        "Type": "type_code", "Status": "is_active", "CreatedAt": "created_at",
    })[["holiday_key", "name", "date_key", "type_code", "type_label", "created_at"]]


def build_dim_date(raw: dict, start: str = "2022-01-01", end: str = "2028-12-31") -> pd.DataFrame:
    dates = pd.date_range(start=start, end=end, freq="D")
    df = pd.DataFrame({"date_key": dates})
    df["year"] = df["date_key"].dt.year
    df["month"] = df["date_key"].dt.month
    df["month_name"] = df["date_key"].dt.strftime("%B")
    df["quarter"] = df["date_key"].dt.quarter
    df["day_of_week"] = df["date_key"].dt.dayofweek + 1  # 1=Mon, 7=Sun
    df["day_name"] = df["date_key"].dt.strftime("%A")
    df["week_of_year"] = df["date_key"].dt.isocalendar().week.astype(int)
    df["is_weekend"] = df["day_of_week"].isin([6, 7])
    df["academic_year_label"] = df.apply(
        lambda r: f"{r['year']}-{r['year'] + 1}" if r["month"] >= 8
        else f"{r['year'] - 1}-{r['year']}", axis=1,
    )
    # Enrich with holidays
    holidays = raw.get("HolidayEntity", pd.DataFrame())
    df["is_holiday"] = False
    df["holiday_name"] = pd.NA
    if not holidays.empty:
        h = holidays.copy()
        if "Status" in h.columns:
            h = h[h["Status"].astype(str).str.lower().eq("true")]
        if "DeletedAt" in h.columns:
            h = h[h["DeletedAt"].isna()]
        h["Date"] = pd.to_datetime(h["Date"], errors="coerce").dt.date
        holiday_map = dict(zip(h["Date"], h["Name"]))
        df_date = df["date_key"].dt.date
        df["is_holiday"] = df_date.isin(holiday_map.keys())
        df["holiday_name"] = df_date.map(holiday_map)
    df["date_key"] = df["date_key"].dt.date
    return df


def build_dim_user(raw: dict) -> pd.DataFrame:
    src = raw.get("User", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src.copy()
    if "DeletedAt" in df.columns:
        df = df[df["DeletedAt"].isna()]
    df["user_type_label"] = df["UserType"].map(USER_TYPE).fillna("Unknown")
    return df.rename(columns={
        "Id": "user_key", "Username": "username", "UserType": "user_type_code",
        "AccountId": "account_id", "Photo": "photo", "CreatedAt": "created_at",
    })[["user_key", "username", "user_type_code", "user_type_label",
        "account_id", "photo", "created_at"]]


def build_dim_course_learning_outcome(raw: dict) -> pd.DataFrame:
    src = raw.get("CourseLearningOutCome", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src.copy()
    if "DeletedAt" in df.columns:
        df = df[df["DeletedAt"].isna()]
    return df.rename(columns={
        "Id": "clo_key", "CourseId": "course_key", "Title": "title",
        "Description": "description", "LearningDomain": "learning_domain",
        "CognitiveAffectivePsychomotor": "cognitive_affective_psychomotor",
        "CreatedAt": "created_at",
    })[["clo_key", "course_key", "title", "description",
        "learning_domain", "cognitive_affective_psychomotor"]]


def build_dim_section(raw: dict) -> pd.DataFrame:
    src = raw.get("Section", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src.copy()
    if "DeletedAt" in df.columns:
        df = df[df["DeletedAt"].isna()]
    return df.rename(columns={
        "Id": "section_key", "CourseId": "course_key", "Title": "title",
        "LessonLearningOutcome": "lesson_learning_outcome",
        "Description": "description",
        "CourseLearningOutComeEntityId": "clo_key", "CreatedAt": "created_at",
    })[["section_key", "course_key", "title", "lesson_learning_outcome",
        "description", "clo_key"]]


# ─── Bridge table builders ────────────────────────────────────────────────────

def build_bridge_teacher_course(raw: dict) -> pd.DataFrame:
    src = raw.get("TeacherCourse", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    return src.rename(columns={"TeacherId": "teacher_key", "CourseId": "course_key"})


def build_bridge_major_course(raw: dict) -> pd.DataFrame:
    src = raw.get("MajorCourse", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    return src.rename(columns={"MajorId": "major_key", "CourseId": "course_key"})


# ─── Fact builders ────────────────────────────────────────────────────────────

def build_fact_enrollment(raw: dict) -> pd.DataFrame:
    enroll = raw.get("Enroll", pd.DataFrame())
    schedule = raw.get("Schedule", pd.DataFrame())
    cls = raw.get("Class", pd.DataFrame())
    semester = raw.get("Semester", pd.DataFrame())
    if enroll.empty:
        return pd.DataFrame()

    sched = schedule[["Id", "CourseId", "TeacherId", "ClassId"]].rename(columns={
        "Id": "ScheduleId", "CourseId": "course_key",
        "TeacherId": "teacher_key", "ClassId": "_ClassId",
    })
    cls_slim = cls[["Id", "SemesterId"]].rename(columns={"Id": "_ClassId"})
    sem_slim = semester[["Id", "StartDate"]].rename(columns={
        "Id": "SemesterId", "StartDate": "semester_start_date",
    })

    df = enroll.merge(sched, on="ScheduleId", how="left")
    df = df.merge(cls_slim, on="_ClassId", how="left")
    df = df.merge(sem_slim, on="SemesterId", how="left")

    parsed = df["Attendances"].apply(
        lambda x: pd.Series(
            _parse_attendances(x),
            index=["attendance_present", "attendance_late",
                   "attendance_absent", "attendance_total_sessions"],
        )
    )
    df = pd.concat([df, parsed], axis=1)
    df["attendance_rate_pct"] = (
        df["attendance_present"] / df["attendance_total_sessions"].replace(0, pd.NA) * 100
    ).round(2)

    score_cols = ["ScoreAttendance", "ScoreResearch", "ScoreQuiz", "ScoreMidterm", "ScoreFinal"]
    df["total_score"] = df[score_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1)
    df["gpa_points"] = df["LetterGrade"].map(LETTER_GPA)
    df["enrollment_date_key"] = pd.to_datetime(df["semester_start_date"], errors="coerce").dt.date

    return df.rename(columns={
        "Id": "enrollment_key", "StudentId": "student_key", "ScheduleId": "schedule_key",
        "SemesterId": "semester_key", "_ClassId": "class_key",
        "ScoreAttendance": "score_attendance", "ScoreResearch": "score_research",
        "ScoreQuiz": "score_quiz", "ScoreMidterm": "score_midterm",
        "ScoreFinal": "score_final", "LetterGrade": "letter_grade", "Note": "note",
    })[["enrollment_key", "student_key", "schedule_key", "course_key", "teacher_key",
        "class_key", "semester_key", "enrollment_date_key", "score_attendance",
        "score_research", "score_quiz", "score_midterm", "score_final", "total_score",
        "letter_grade", "gpa_points", "attendance_present", "attendance_late",
        "attendance_absent", "attendance_total_sessions", "attendance_rate_pct", "note"]]


def build_fact_attendance(raw: dict) -> pd.DataFrame:
    attendance = raw.get("Attendance", pd.DataFrame())
    sched_times = raw.get("ScheduleTimes", pd.DataFrame())
    schedule = raw.get("Schedule", pd.DataFrame())
    user = raw.get("User", pd.DataFrame())
    cls = raw.get("Class", pd.DataFrame())
    semester = raw.get("Semester", pd.DataFrame())
    if attendance.empty:
        return pd.DataFrame()

    st = sched_times[["Id", "ScheduleId", "Day"]].rename(columns={"Id": "ScheduleTimesId"})
    sched = schedule[["Id", "CourseId", "TeacherId", "ClassId"]].rename(columns={
        "Id": "ScheduleId", "CourseId": "course_key",
        "TeacherId": "teacher_key", "ClassId": "_ClassId",
    })
    cls_slim = cls[["Id", "SemesterId"]].rename(columns={"Id": "_ClassId"})
    sem_slim = semester[["Id"]].rename(columns={"Id": "SemesterId"})
    user_slim = user[["Id", "AccountId"]].rename(columns={"Id": "UserId", "AccountId": "student_key"})

    df = attendance.merge(st, on="ScheduleTimesId", how="left")
    df = df.merge(sched, on="ScheduleId", how="left")
    df = df.merge(cls_slim, on="_ClassId", how="left")
    df = df.merge(sem_slim, on="SemesterId", how="left")
    df = df.merge(user_slim, on="UserId", how="left")

    df["CheckInAt"] = pd.to_datetime(df["CheckInAt"], errors="coerce", utc=True)
    df["CheckOutAt"] = pd.to_datetime(df["CheckOutAt"], errors="coerce", utc=True)
    df["duration_hours"] = (
        (df["CheckOutAt"] - df["CheckInAt"]).dt.total_seconds() / 3600
    ).round(2)
    df["check_in_date_key"] = df["CheckInAt"].dt.date
    df["check_in_time"] = df["CheckInAt"].dt.strftime("%H:%M:%S")
    df["check_out_time"] = df["CheckOutAt"].dt.strftime("%H:%M:%S")

    df["CheckInStatus"] = pd.to_numeric(df["CheckInStatus"], errors="coerce")
    df["CheckOutStatus"] = pd.to_numeric(df["CheckOutStatus"], errors="coerce")
    df["check_in_status_label"] = df["CheckInStatus"].map(CHECKIN_STATUS).fillna("Unknown")
    df["check_out_status_label"] = df["CheckOutStatus"].map(CHECKOUT_STATUS).fillna("Unknown")
    df["day_of_week"] = df["Day"]
    df["day_name"] = df["Day"].map(DAY_NAME).fillna("Unknown")

    return df.rename(columns={
        "Id": "attendance_key", "UserId": "user_key",
        "ScheduleTimesId": "schedule_time_key", "ScheduleId": "schedule_key",
        "_ClassId": "class_key", "SemesterId": "semester_key",
        "CheckInStatus": "check_in_status_code", "CheckOutStatus": "check_out_status_code",
        "Reason": "reason",
    })[["attendance_key", "student_key", "user_key", "schedule_time_key", "schedule_key",
        "course_key", "teacher_key", "class_key", "semester_key",
        "check_in_date_key", "check_in_time", "check_out_time",
        "check_in_status_code", "check_in_status_label",
        "check_out_status_code", "check_out_status_label",
        "duration_hours", "reason", "day_of_week", "day_name"]]


def build_fact_grade(raw: dict) -> pd.DataFrame:
    score = raw.get("Score", pd.DataFrame())
    score_sem = raw.get("ScoreSemester", pd.DataFrame())
    semester = raw.get("Semester", pd.DataFrame())
    if score_sem.empty:
        return pd.DataFrame()

    sem_slim = semester[["Id", "StartDate"]].rename(columns={
        "Id": "SemesterId", "StartDate": "semester_start_date",
    })
    score_slim = score[["Id", "StudentId", "TotalCredit", "EarnedCredit"]].rename(
        columns={"Id": "ScoreId"}
    )

    df = score_sem.merge(score_slim, on="ScoreId", how="left")
    df = df.merge(sem_slim, on="SemesterId", how="left")

    df["credit_completion_rate"] = (
        df["Credit"] / df["TotalCredit"].replace(0, pd.NA) * 100
    ).round(2)
    df["semester_date_key"] = pd.to_datetime(df["semester_start_date"], errors="coerce").dt.date

    return df.rename(columns={
        "Id": "grade_key", "StudentId": "student_key", "SemesterId": "semester_key",
        "Gpa": "gpa", "TotalCredit": "total_credit", "Credit": "earned_credit",
        "EarnedCredit": "cumulative_earned_credit", "Remarks": "remarks",
    })[["grade_key", "student_key", "semester_key", "semester_date_key",
        "gpa", "total_credit", "earned_credit", "cumulative_earned_credit",
        "credit_completion_rate", "remarks"]]


def build_fact_evaluation_rating(raw: dict) -> pd.DataFrame:
    eval_rate = raw.get("EvaluateRate", pd.DataFrame())
    enroll = raw.get("Enroll", pd.DataFrame())
    schedule = raw.get("Schedule", pd.DataFrame())
    cls = raw.get("Class", pd.DataFrame())
    semester = raw.get("Semester", pd.DataFrame())
    if eval_rate.empty:
        return pd.DataFrame()

    enroll_slim = enroll[["Id", "StudentId", "ScheduleId"]].rename(columns={
        "Id": "EnrollId", "StudentId": "student_key",
    })
    sched = schedule[["Id", "TeacherId", "CourseId", "ClassId"]].rename(columns={
        "Id": "ScheduleId", "TeacherId": "teacher_key", "CourseId": "course_key",
    })
    cls_slim = cls[["Id", "SemesterId"]].rename(columns={"Id": "ClassId"})
    sem_slim = semester[["Id", "StartDate"]].rename(columns={
        "Id": "SemesterId", "StartDate": "eval_start_date",
    })

    df = eval_rate.merge(enroll_slim, on="EnrollId", how="left")
    df = df.merge(sched, on="ScheduleId", how="left")
    df = df.merge(cls_slim, on="ClassId", how="left")
    df = df.merge(sem_slim, on="SemesterId", how="left")

    df["eval_date_key"] = pd.to_datetime(df["eval_start_date"], errors="coerce").dt.date
    df["eval_type_label"] = df["Type"].map(EVAL_TYPE).fillna("Unknown")
    df["Rate"] = pd.to_numeric(df["Rate"], errors="coerce")

    return df.rename(columns={
        "Id": "eval_rating_key", "EnrollId": "enrollment_key",
        "EvaluationId": "evaluation_key", "Rate": "rate",
        "Type": "eval_type_code", "SemesterId": "semester_key",
    })[["eval_rating_key", "enrollment_key", "student_key", "teacher_key",
        "course_key", "evaluation_key", "semester_key", "eval_date_key",
        "rate", "eval_type_code", "eval_type_label"]]


def build_fact_evaluation_text(raw: dict) -> pd.DataFrame:
    eval_text = raw.get("EvaluateText", pd.DataFrame())
    enroll = raw.get("Enroll", pd.DataFrame())
    schedule = raw.get("Schedule", pd.DataFrame())
    if eval_text.empty:
        return pd.DataFrame()

    enroll_slim = enroll[["Id", "StudentId", "ScheduleId"]].rename(columns={
        "Id": "EnrollId", "StudentId": "student_key",
    })
    sched = schedule[["Id", "TeacherId"]].rename(columns={
        "Id": "ScheduleId", "TeacherId": "teacher_key",
    })

    df = eval_text.merge(enroll_slim, on="EnrollId", how="left")
    df = df.merge(sched, on="ScheduleId", how="left")
    df["eval_type_label"] = df["Type"].map(EVAL_TYPE).fillna("Unknown")

    return df.rename(columns={
        "Id": "eval_text_key", "EnrollId": "enrollment_key",
        "EvaluationId": "evaluation_key", "Text": "response_text",
        "Type": "eval_type_code",
    })[["eval_text_key", "enrollment_key", "student_key", "teacher_key",
        "evaluation_key", "response_text", "eval_type_code", "eval_type_label"]]


def build_fact_permission(raw: dict) -> pd.DataFrame:
    perm_sched = raw.get("PermissionScheduleTimes", pd.DataFrame())
    perm = raw.get("Permission", pd.DataFrame())
    user = raw.get("User", pd.DataFrame())
    if perm_sched.empty or perm.empty:
        return pd.DataFrame()

    perm_slim = perm[["Id", "UserId", "Reason", "Attachment"]].rename(
        columns={"Id": "PermissionId"}
    )
    user_slim = user[["Id", "AccountId"]].rename(
        columns={"Id": "UserId", "AccountId": "student_key"}
    )

    df = perm_sched.merge(perm_slim, on="PermissionId", how="left")
    df = df.merge(user_slim, on="UserId", how="left")

    df["Status"] = pd.to_numeric(df["Status"], errors="coerce")
    df["status_label"] = df["Status"].map(PERMISSION_STATUS).fillna("Unknown")
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
    df["has_attachment"] = df["Attachment"].notna() & (df["Attachment"].astype(str).str.strip() != "")

    return df.rename(columns={
        "Id": "permission_schedule_key", "PermissionId": "permission_key",
        "UserId": "user_key", "ScheduleTimesId": "schedule_time_key",
        "Date": "permission_date_key", "Status": "status_code",
        "Reason": "reason",
    })[["permission_schedule_key", "permission_key", "student_key", "user_key",
        "schedule_time_key", "permission_date_key", "status_code", "status_label",
        "reason", "has_attachment"]]


def build_fact_makeup_class(raw: dict) -> pd.DataFrame:
    makeup = raw.get("MakeUp", pd.DataFrame())
    schedule = raw.get("Schedule", pd.DataFrame())
    if makeup.empty:
        return pd.DataFrame()

    sched = schedule[["Id", "CourseId", "TeacherId", "ClassId"]].rename(columns={
        "Id": "ScheduleId", "CourseId": "course_key",
        "TeacherId": "teacher_key", "ClassId": "class_key",
    })
    df = makeup.merge(sched, on="ScheduleId", how="left")

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
    df["StartTime"] = pd.to_datetime(df["StartTime"], errors="coerce", format="mixed")
    df["EndTime"] = pd.to_datetime(df["EndTime"], errors="coerce", format="mixed")
    df["duration_hours"] = (
        (df["EndTime"] - df["StartTime"]).dt.total_seconds() / 3600
    ).round(2)
    df["start_time_str"] = df["StartTime"].dt.strftime("%H:%M:%S")
    df["end_time_str"] = df["EndTime"].dt.strftime("%H:%M:%S")

    return df.rename(columns={
        "Id": "makeup_key", "ScheduleId": "schedule_key",
        "Date": "makeup_date_key",
    })[["makeup_key", "schedule_key", "course_key", "teacher_key", "class_key",
        "makeup_date_key", "start_time_str", "end_time_str", "duration_hours"]]


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    base = Path(__file__).parent
    table_dir = base / "table"
    out_dir = base / "warehouse"
    out_dir.mkdir(exist_ok=True)

    if not table_dir.exists():
        print(f"ERROR: source directory not found: {table_dir}", file=sys.stderr)
        sys.exit(1)

    print("Loading sources...")
    raw = load_sources(table_dir)
    print(f"  Loaded {len(raw)} tables\n")

    print("Building dimensions...")
    dims = [
        ("dim_faculty",                 build_dim_faculty(raw)),
        ("dim_department",              build_dim_department(raw)),
        ("dim_major",                   build_dim_major(raw)),
        ("dim_semester",                build_dim_semester(raw)),
        ("dim_student",                 build_dim_student(raw)),
        ("dim_teacher",                 build_dim_teacher(raw)),
        ("dim_course",                  build_dim_course(raw)),
        ("dim_class",                   build_dim_class(raw)),
        ("dim_schedule",                build_dim_schedule(raw)),
        ("dim_schedule_time",           build_dim_schedule_time(raw)),
        ("dim_holiday",                 build_dim_holiday(raw)),
        ("dim_date",                    build_dim_date(raw)),
        ("dim_evaluation_question",     build_dim_evaluation_question(raw)),
        ("dim_user",                    build_dim_user(raw)),
        ("dim_course_learning_outcome", build_dim_course_learning_outcome(raw)),
        ("dim_section",                 build_dim_section(raw)),
        ("bridge_teacher_course",       build_bridge_teacher_course(raw)),
        ("bridge_major_course",         build_bridge_major_course(raw)),
    ]
    for name, df in dims:
        _save(df, name, out_dir)

    print("\nBuilding facts...")
    facts = [
        ("fact_enrollment",         build_fact_enrollment(raw)),
        ("fact_attendance",         build_fact_attendance(raw)),
        ("fact_grade",              build_fact_grade(raw)),
        ("fact_evaluation_rating",  build_fact_evaluation_rating(raw)),
        ("fact_evaluation_text",    build_fact_evaluation_text(raw)),
        ("fact_permission",         build_fact_permission(raw)),
        ("fact_makeup_class",       build_fact_makeup_class(raw)),
    ]
    for name, df in facts:
        _save(df, name, out_dir)

    total = len(dims) + len(facts)
    print(f"\nDone. {total} files written to {out_dir}/")


if __name__ == "__main__":
    main()
