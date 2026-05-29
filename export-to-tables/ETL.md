# ETL Documentation — University Data Warehouse

## 1. Overview

This ETL pipeline transforms 34 CSV exports from the university Learning Management System (LMS) into a star-schema data warehouse optimised for analytics and dashboard development.

```
export-to-tables/
  table/              ← 34 source CSV files (read-only)
  warehouse/          ← 25 output parquet/CSV files (generated)
  transform_warehouse.py  ← this ETL script
```

**Data flow:**

```
table/*.csv
    │
    ▼ load_sources()
dict[stem → DataFrame]
    │
    ├─▶ build_dim_*()  ──▶  dim_*.parquet   (18 tables)
    ├─▶ build_bridge_*() ─▶ bridge_*.parquet ( 2 tables)
    └─▶ build_fact_*()  ──▶  fact_*.parquet  ( 7 tables)
                              └─▶ warehouse/
```

**Tech stack:** Python 3.9+, pandas, pyarrow (optional — falls back to CSV).

---

## 2. How to Run

```bash
# Install dependencies (one-time)
pip install pandas pyarrow

# Run from the project root
cd export-to-tables
python transform_warehouse.py
```

Expected output (25 files in `warehouse/`):

```
dim_faculty.parquet           dim_schedule_time.parquet
dim_department.parquet        dim_holiday.parquet
dim_major.parquet             dim_date.parquet
dim_semester.parquet          dim_evaluation_question.parquet
dim_student.parquet           dim_user.parquet
dim_teacher.parquet           dim_course_learning_outcome.parquet
dim_course.parquet            dim_section.parquet
dim_class.parquet             bridge_teacher_course.parquet
dim_schedule.parquet          bridge_major_course.parquet
fact_enrollment.parquet
fact_attendance.parquet
fact_grade.parquet
fact_evaluation_rating.parquet
fact_evaluation_text.parquet
fact_permission.parquet
fact_makeup_class.parquet
```

The script is **fully idempotent** — re-running it overwrites previous outputs.

---

## 3. Source Data Catalog

| Table | ~Rows | Key Columns | Notes |
|---|---|---|---|
| Faculty | 2 | Id, Name, FacultyNameKh, ShortLetter | Top of academic hierarchy |
| Department | 5 | Id, Name, FacultyId | Child of Faculty |
| Major | 1 | Id, Name, DepartmentId | e.g. "SCA" |
| Semester | 30 | Id, Semester, Year, AcademicYear, StartDate, EndDate, MajorId | Scoped per-Major |
| Student | 50 | Id, StudentId, Batch, MajorId, Status, Shift, IsScholarship | Soft delete via DeletedAt |
| Teacher | 30 | Id, Title, FirstName, LastName, DepartmentId, Status | Status="False" = active |
| User | 50 | Id, Username, UserType, AccountId | AccountId → Student.Id or Teacher.Id |
| Course | 80 | Id, Code, Name, Credit, DepartmentId, IsActive | Soft delete via DeletedAt |
| Class | 35 | Id, Name, SemesterId, MajorId, Year, IsActive | A class = cohort in a semester |
| Schedule | 30 | Id, CourseId, TeacherId, ClassId | Assignment: teacher→course→class |
| ScheduleTimes | 70 | Id, ScheduleId, StartTime, EndTime, Day | Recurring weekly slots |
| Enroll | 1 800 | Id, StudentId, ScheduleId, Attendances, LetterGrade, Score* | Core academic record |
| Attendance | 16 000 | Id, UserId, ScheduleTimesId, CheckInAt, CheckOutAt, CheckIn/OutStatus | GPS tracked |
| Score | 50 | Id, StudentId, TotalCredit, EarnedCredit, Gpa | Cumulative record |
| ScoreSemester | 35 | Id, ScoreId, SemesterId, Gpa, Credit | Per-semester GPA |
| EvaluateRate | 12 000 | Id, EnrollId, EvaluationId, Rate, Type | 1-5 rating per question |
| EvaluateText | 500 | Id, EnrollId, EvaluationId, Text, Type | Free-text feedback |
| Evaluation | 18 | Id, No, Question, Type, DepartmentId | Question bank |
| Permission | 14 | Id, UserId, Reason, Attachment | Leave request header |
| PermissionScheduleTimes | 30 | Id, PermissionId, ScheduleTimesId, Status, Date | Session-level details |
| HolidayEntity | 23 | Id, Name, Date, Type, Status | Public holidays |
| MakeUp | 30 | Id, Date, StartTime, EndTime, ScheduleId | Replacement sessions |
| Section | 14 | Id, CourseId, Title, CourseLearningOutComeEntityId | Lesson plan |
| CourseLearningOutCome | 6 | Id, CourseId, Title, LearningDomain | Curriculum outcomes |
| TeacherCourse | 20 | TeacherId, CourseId | Many-to-many |
| MajorCourse | 30 | MajorId, CourseId | Many-to-many |
| Material | 2 | Id, SectionId, Name, Type, Link | Course materials |
| TeacherUnavailableTime | 3 | Id, TeacherId, DayOfWeek, StartDate, EndDate | Scheduling blocks |
| TelegramMessage | 50 | Id, TelegramMessageId, ChatId | Notification metadata only |
| Staff | 1 | Id, FirstName, LastName, DepartmentId | Non-teaching staff |
| Survey | 0 | — | Empty table — skipped |
| CV | 0 | — | Empty table — skipped |
| TeachingHour | 0 | — | Empty table — skipped |

---

## 4. Data Quality Notes

### 4.1 Teacher.Status semantics
The `Status` column in `Teacher.csv` stores `"False"` for **active** teachers. It behaves as an `IsDeleted` flag. The ETL maps `Status == "False"` → `is_active = True`. This is intentional and matches the application logic.

### 4.2 User.AccountId bridge
`User.AccountId` is a polymorphic foreign key: when `UserType = 1` (Student), it points to `Student.Id`; when `UserType = 3` (Teacher), it points to `Teacher.Id`. The `fact_attendance` and `fact_permission` builders use this to resolve `student_key`.

### 4.3 Attendance GPS coordinates
Some attendance records contain GPS coordinates that appear geographically incorrect (non-Cambodia coordinates). These are not filtered — they are excluded from the warehouse output but remain in the source CSV for audit purposes.

### 4.4 PermissionScheduleTimes.Status codes
| Code | Meaning |
|---|---|
| 1 | Approved |
| 2 | Pending |
| 3 | Rejected |

### 4.5 Attendances string format
The `Enroll.Attendances` column is a comma-separated string encoding per-session attendance:
- `1` = Present
- `L` = Late
- `A` = Absent
- (empty/other) = Not recorded

Example: `"1,1,L,1,A,1,1"` → 4 present, 1 late, 1 absent, 7 total.

### 4.6 Semester scope
Each row in `Semester.csv` is specific to a `MajorId`. Different majors can run on different semester calendars. The same academic year / semester number may appear multiple times for different majors.

### 4.7 Soft deletes
Entities with `DeletedAt IS NOT NULL` are excluded from all dimensions. Facts retain all rows (including those referencing soft-deleted dimensions) to preserve historical accuracy.

### 4.8 Class.IsActive
`Class.IsActive = "False"` means the class has ended (completed semester). This is not the same as deleted. Both active and inactive classes are included in `dim_class`.

---

## 5. Dimension Table Specifications

### dim_date
- **Source:** Generated (not from a CSV)
- **Range:** 2022-01-01 to 2028-12-31
- **Enrichment:** Left-joined with `HolidayEntity` to populate `is_holiday` and `holiday_name`
- **Primary key:** `date_key` (Python `date` object, stored as ISO string)
- **Key derived columns:**
  - `academic_year_label`: "YYYY-YYYY+1" (pivot month = August)
  - `is_weekend`: True if day_of_week ∈ {6, 7}

### dim_faculty / dim_department / dim_major
- **Source:** Faculty.csv, Department.csv, Major.csv
- **Filter:** `DeletedAt IS NULL`
- **Denormalization:** Each level includes the parent name for convenience (e.g. `dim_department` has `faculty_name`)

### dim_semester
- **Source:** Semester.csv
- **Filter:** `DeletedAt IS NULL`
- `start_date` / `end_date` parsed as Python `date` objects

### dim_student
- **Source:** Student.csv + Major.csv (left join on MajorId)
- **Filter:** `DeletedAt IS NULL`
- **Derived:** `age` (days from DOB to today ÷ 365), `full_name`, `full_name_kh`, `status_label`, `shift_label`

### dim_teacher
- **Source:** Teacher.csv + Department.csv (left join on DepartmentId)
- **Filter:** No DeletedAt in source — relies on `Status == "False"` as active indicator
- **Derived:** `full_name` (Title + FirstName + LastName), `is_active`
- **Note:** Accepts both `FirstNameInKhmer` (older export) and `FirstNameKh` (newer export) column names

### dim_course
- **Source:** Course.csv + Department.csv
- **Filter:** `DeletedAt IS NULL`

### dim_class
- **Source:** Class.csv + Semester.csv + Major.csv
- **Filter:** `DeletedAt IS NULL`
- Denormalizes `academic_year`, `semester_number`, `semester_start_date`, `semester_end_date`, `major_name`

### dim_schedule
- **Source:** Schedule.csv + Course.csv + Teacher.csv + Class.csv
- Denormalizes `course_name`, `teacher_name`, `class_name`

### dim_schedule_time
- **Source:** ScheduleTimes.csv
- **Derived:** `day_name` from `Day` integer via `DAY_NAME` map

### dim_evaluation_question
- **Source:** Evaluation.csv
- **Filter:** `DeletedAt IS NULL` AND `IsActive == True`

### dim_holiday
- **Source:** HolidayEntity.csv
- **Filter:** `DeletedAt IS NULL` AND `Status == True`

### dim_user
- **Source:** User.csv
- **Filter:** `DeletedAt IS NULL`

### dim_course_learning_outcome / dim_section
- **Source:** CourseLearningOutCome.csv, Section.csv
- **Filter:** `DeletedAt IS NULL`

---

## 6. Fact Table Specifications

### fact_enrollment
- **Grain:** 1 row per student per course offering (schedule)
- **Join chain:** Enroll → Schedule (ScheduleId) → Class (ClassId) → Semester (SemesterId)
- **Derived measures:**

| Measure | Formula |
|---|---|
| `total_score` | Sum of score_attendance + score_research + score_quiz + score_midterm + score_final |
| `gpa_points` | Lookup `letter_grade` in LETTER_GPA map |
| `attendance_present` | Count of `"1"` tokens in Attendances string |
| `attendance_late` | Count of `"L"` tokens |
| `attendance_absent` | Count of `"A"` tokens |
| `attendance_total_sessions` | Total token count |
| `attendance_rate_pct` | present / total × 100 |

### fact_attendance
- **Grain:** 1 row per student check-in event
- **Join chain:** Attendance → ScheduleTimes (ScheduleTimesId) → Schedule (ScheduleId) → Class → Semester; Attendance → User (UserId) for student_key
- **Derived measures:**

| Measure | Formula |
|---|---|
| `duration_hours` | (CheckOutAt − CheckInAt).total_seconds() / 3600 |
| `check_in_status_label` | Map CheckInStatus via CHECKIN_STATUS |
| `check_out_status_label` | Map CheckOutStatus via CHECKOUT_STATUS |
| `day_name` | Map ScheduleTimes.Day via DAY_NAME |

### fact_grade
- **Grain:** 1 row per student per semester
- **Join chain:** ScoreSemester → Score (ScoreId) → Semester (SemesterId)
- **Derived measures:**

| Measure | Formula |
|---|---|
| `credit_completion_rate` | earned_credit / total_credit × 100 |
| `cumulative_earned_credit` | From Score.EarnedCredit (total program credits earned) |

### fact_evaluation_rating
- **Grain:** 1 row per student rating answer per evaluation question
- **Join chain:** EvaluateRate → Enroll (EnrollId) → Schedule → Class → Semester

### fact_evaluation_text
- **Grain:** 1 row per student text answer per evaluation question
- **Join chain:** EvaluateText → Enroll (EnrollId) → Schedule

### fact_permission
- **Grain:** 1 row per permission request × class session it covers
- **Join chain:** PermissionScheduleTimes → Permission (PermissionId) → User (UserId)
- **Derived:**
  - `status_label` from PERMISSION_STATUS map
  - `has_attachment` = Permission.Attachment is not null/empty
  - `permission_date_key` from PermissionScheduleTimes.Date

### fact_makeup_class
- **Grain:** 1 row per makeup session
- **Join chain:** MakeUp → Schedule (ScheduleId) for course/teacher/class denorm
- **Derived:** `duration_hours` = (EndTime − StartTime).total_seconds() / 3600

---

## 7. Surrogate Key Strategy

Source table PKs are used directly as surrogate keys — no separate integer sequence is generated. Source IDs are stable integers that do not change between exports. The exception is `dim_date`, which uses the date itself (`date_key`) as its natural primary key.

---

## 8. Refresh Strategy

1. Export fresh CSVs from the production database using the existing backup pipeline.
2. Place all CSVs in `export-to-tables/table/` (overwriting previous exports).
3. Run `python transform_warehouse.py`.
4. The warehouse output in `export-to-tables/warehouse/` is fully replaced.

The script produces no partial outputs — if it fails mid-run, previously written files from the same run remain (they will be overwritten on the next successful run).

**Recommended schedule:** After each nightly backup export.

---

## 9. Adding New Tables

To add a new dimension or fact table to the warehouse:

**Step 1 — Write the builder function:**
```python
def build_dim_example(raw: dict) -> pd.DataFrame:
    src = raw.get("SourceTableStem", pd.DataFrame())
    if src.empty:
        return pd.DataFrame()
    df = src.copy()
    # filter, join, derive, rename
    return df.rename(columns={...})[["col1", "col2", ...]]
```

**Step 2 — Register in `main()`:**
```python
dims = [
    ...
    ("dim_example", build_dim_example(raw)),
]
```

**Step 3 — Update this document** with source, filter, grain, and derived measures.

**Step 4 — Add to `WAREHOUSE_ER.md`** with the entity and relationships.
