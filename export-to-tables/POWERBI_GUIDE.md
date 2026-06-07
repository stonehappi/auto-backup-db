# Power BI Developer Guide — University Data Warehouse

Step-by-step guide for connecting to the warehouse and building dashboards across five user roles.

---

## Part A: Connection Setup (All Roles)

### Step 1 — Run the ETL

Before opening Power BI, ensure the warehouse files exist:

```bash
cd export-to-tables
python transform_warehouse.py
```

This creates `export-to-tables/warehouse/*.parquet` (or `*.csv` if pyarrow is unavailable).

---

### Step 2 — Connect Power BI Desktop to the Warehouse

**Option A — Parquet files (recommended):**

1. Open **Power BI Desktop** → **Home** → **Get Data** → **More...**
2. Search for **Parquet** → **Connect**
3. Browse to one `.parquet` file in `export-to-tables/warehouse/`
4. Power BI loads that single file. Repeat for each file, **or** use Option B.

**Option B — Folder connector (load all files at once):**

1. **Get Data** → **Folder**
2. Select the `export-to-tables/warehouse/` directory
3. In the preview dialog, click **Transform Data**
4. In Power Query: filter `Extension` = `.parquet`
5. Use **Combine Files** → Power BI auto-loads all parquet files as separate queries
6. Rename each query to match the table name (e.g. `dim_student`, `fact_enrollment`)

> **Fallback — CSV files:** If `.parquet` is not available, use **Get Data → Text/CSV** for each `.csv` file. The connection steps are otherwise identical.

---

### Step 3 — Set Data Types in Power Query

For each table, open **Transform Data** and verify:

| Column pattern | Correct type |
|---|---|
| `*_key`, `*_id`, `*_code` | Whole Number |
| `date_key`, `*_date_key`, `start_date`, `end_date` | Date |
| `gpa`, `rate`, `*_pct`, `duration_hours`, `total_score` | Decimal Number |
| `is_*`, `has_*`, `allow_*` | True/False |
| Everything else | Text |

Click **Close & Apply** when done.

---

### Step 4 — Build the Data Model (Relationships)

Switch to **Model view** (left sidebar icon).

Create the following relationships (all are **Many-to-One**, Single direction):

**Reference hierarchy:**
| From (Many) | To (One) | Join columns |
|---|---|---|
| dim_department | dim_faculty | faculty_key |
| dim_major | dim_department | department_key |
| dim_semester | dim_major | major_key |
| dim_student | dim_major | major_key |
| dim_teacher | dim_department | department_key |
| dim_course | dim_department | department_key |
| dim_class | dim_semester | semester_key |
| dim_class | dim_major | major_key |
| dim_schedule | dim_course | course_key |
| dim_schedule | dim_teacher | teacher_key |
| dim_schedule | dim_class | class_key |
| dim_schedule_time | dim_schedule | schedule_key |

**Calendar:**
| From (Many) | To (One) | Join columns |
|---|---|---|
| dim_holiday | dim_date | date_key |

**Facts → Dimensions:**
| From (Many) | To (One) | Join columns |
|---|---|---|
| fact_enrollment | dim_student | student_key |
| fact_enrollment | dim_schedule | schedule_key |
| fact_enrollment | dim_semester | semester_key |
| fact_enrollment | dim_date | enrollment_date_key → date_key |
| fact_attendance | dim_student | student_key |
| fact_attendance | dim_user | user_key |
| fact_attendance | dim_schedule_time | schedule_time_key |
| fact_attendance | dim_schedule | schedule_key |
| fact_attendance | dim_date | check_in_date_key → date_key |
| fact_grade | dim_student | student_key |
| fact_grade | dim_semester | semester_key |
| fact_grade | dim_date | semester_date_key → date_key |
| fact_evaluation_rating | fact_enrollment | enrollment_key |
| fact_evaluation_rating | dim_evaluation_question | evaluation_key |
| fact_evaluation_rating | dim_semester | semester_key |
| fact_evaluation_text | fact_enrollment | enrollment_key |
| fact_evaluation_text | dim_evaluation_question | evaluation_key |
| fact_permission | dim_student | student_key |
| fact_permission | dim_user | user_key |
| fact_permission | dim_schedule_time | schedule_time_key |
| fact_permission | dim_date | permission_date_key → date_key |
| fact_makeup_class | dim_schedule | schedule_key |
| fact_makeup_class | dim_date | makeup_date_key → date_key |

> **Tip:** For facts joining `dim_date`, the fact column name differs from `date_key`. In the relationship dialog set the join as `fact_X[*_date_key]` → `dim_date[date_key]`.

---

### Step 5 — Configure the Date Table

1. Select `dim_date` in Model view
2. **Table tools** → **Mark as date table** → select `date_key`
3. Power BI will use this for all time-intelligence DAX functions

---

### Step 6 — Hide FK Columns from Report View

In Model view, right-click each `_key` / `_id` column used only for joining → **Hide in report view**. This keeps the field pane clean for report builders.

Columns to hide: all `*_key`, `*_id`, `*_code` columns that are surrogate/foreign keys.

---

## Part B: Shared DAX Measures

Create a blank table named `_Measures` (**Enter data** → 1 row, 1 column → delete the column). Define these measures inside it so all reports can reuse them.

```dax
-- Enrollment
Total Enrollments =
    COUNTROWS(fact_enrollment)

Active Enrollments =
    CALCULATE(
        COUNTROWS(fact_enrollment),
        dim_student[status_label] = "Active"
    )

-- Students
Active Students =
    CALCULATE(
        COUNTROWS(dim_student),
        dim_student[status_label] = "Active"
    )

-- GPA
Average GPA =
    AVERAGEX(
        FILTER(fact_enrollment, NOT ISBLANK(fact_enrollment[gpa_points])),
        fact_enrollment[gpa_points]
    )

-- Attendance
Attendance Rate % =
    AVERAGEX(
        FILTER(fact_enrollment, NOT ISBLANK(fact_enrollment[attendance_rate_pct])),
        fact_enrollment[attendance_rate_pct]
    )

-- Grade pass/fail
Pass Rate % =
    DIVIDE(
        CALCULATE(COUNTROWS(fact_enrollment), fact_enrollment[letter_grade] <> "F"),
        COUNTROWS(fact_enrollment),
        0
    )

-- Evaluation
Average Evaluation Score =
    AVERAGE(fact_evaluation_rating[rate])

-- Makeup classes
Makeup Sessions =
    COUNTROWS(fact_makeup_class)

-- Permissions
Approved Permission Rate % =
    DIVIDE(
        CALCULATE(COUNTROWS(fact_permission), fact_permission[status_label] = "Approved"),
        COUNTROWS(fact_permission),
        0
    )
```

---

## Part C: Role-Specific Reports

---

### Role 1: Admin / Academic Affairs

**Purpose:** University-wide academic overview and monitoring.

**Tables to load:** All 25 tables.

**Report Pages:**

#### Page 1 — Executive Overview
| Visual | Config |
|---|---|
| KPI card | Active Students (`Active Students` measure) |
| KPI card | Active Teachers (`CALCULATE(COUNTROWS(dim_teacher), dim_teacher[is_active] = TRUE)`) |
| KPI card | Total Enrollments this semester (filter dim_semester[academic_year]) |
| KPI card | University Pass Rate % |
| Donut chart | Student status breakdown — `dim_student[status_label]`, count of student_key |
| Donut chart | Student shift breakdown — `dim_student[shift_label]`, count |
| KPI card | Scholarship students count (`CALCULATE(COUNTROWS(dim_student), dim_student[is_scholarship] = TRUE)`) |

**Slicers:** `dim_semester[academic_year]`, `dim_faculty[name]`, `dim_department[name]`

#### Page 2 — Enrollment Trends
| Visual | Config |
|---|---|
| Line chart | Enrollment count by semester — X: `dim_semester[academic_year]` + `dim_semester[semester_number]`, Y: Total Enrollments |
| Clustered bar | Average GPA by Department — X: `dim_department[name]`, Y: Average GPA |
| Matrix | Pass Rate by Year Level × Semester — Rows: `dim_class[year_level]`, Cols: `dim_semester[semester_number]`, Values: Pass Rate % |
| Table | Top 10 courses by enrollment — `dim_course[name]`, `dim_course[credit]`, Total Enrollments, Pass Rate % |

**Slicers:** `dim_semester[academic_year]`, `dim_major[name]`

#### Page 3 — Teacher Overview
| Visual | Config |
|---|---|
| Table | Teacher roster — `dim_teacher[full_name]`, `dim_department[name]`, `dim_teacher[qualification]`, Average Evaluation Score, Total Enrollments |
| Bar chart | Average evaluation score by teacher (top 20) |
| KPI card | Average evaluation score university-wide |

**Slicers:** `dim_department[name]`, `dim_semester[academic_year]`

#### Page 4 — Attendance Summary
| Visual | Config |
|---|---|
| KPI card | University attendance rate |
| Bar chart | Average attendance rate by class |
| Stacked bar | Check-in status distribution by department (On Time / Late / Absent / Excused) |

---

### Role 2: Teacher

**Purpose:** View my own classes, students, scores, attendance, and evaluation results.

**Tables to load:**
`fact_enrollment`, `fact_attendance`, `fact_evaluation_rating`, `fact_evaluation_text`, `fact_makeup_class`, `dim_student`, `dim_course`, `dim_class`, `dim_semester`, `dim_schedule`, `dim_schedule_time`, `dim_date`, `dim_evaluation_question`, `_Measures`

#### Row-Level Security (RLS) Setup

1. **Modeling** → **Manage Roles** → **Create role** named `Teacher`
2. Apply filter on `dim_schedule`:
   ```dax
   [teacher_key] = LOOKUPVALUE(
       dim_teacher[teacher_key],
       dim_teacher[email], USERPRINCIPALNAME()
   )
   ```
3. In Power BI Service: assign each teacher's email to the `Teacher` role

#### Report Pages:

#### Page 1 — My Classes This Semester
| Visual | Config |
|---|---|
| Table | Classes — `dim_class[name]`, `dim_course[name]`, enrollment count, Average GPA, Attendance Rate % |
| KPI card | Total students I teach |
| KPI card | My average student GPA |
| KPI card | My average attendance rate |
| KPI card | My average evaluation score |

**Slicer:** `dim_semester[academic_year]`

#### Page 2 — Student Score Details
| Visual | Config |
|---|---|
| Table | Student list — `dim_student[full_name]`, `dim_student[student_id]`, `fact_enrollment[score_attendance]`, `fact_enrollment[score_quiz]`, `fact_enrollment[score_midterm]`, `fact_enrollment[score_final]`, `fact_enrollment[total_score]`, `fact_enrollment[letter_grade]`, `fact_enrollment[attendance_rate_pct]` |
| Bar chart | Score distribution — `fact_enrollment[letter_grade]` count |

**Slicers:** `dim_class[name]`, `dim_course[name]`

#### Page 3 — Attendance Analysis
| Visual | Config |
|---|---|
| Line chart | Attendance rate over time — X: `dim_date[date_key]` (week), Y: Attendance Rate % |
| Clustered bar | Attendance status per class — On Time / Late / Absent / Excused |
| Table | Students below 80% attendance — filtered `fact_enrollment[attendance_rate_pct] < 80` |

#### Page 4 — Evaluation Results
| Visual | Config |
|---|---|
| Clustered bar | Per-question average rating — `dim_evaluation_question[question_text]`, Average of `fact_evaluation_rating[rate]`, grouped by `eval_type_label` (Midterm / Final) |
| KPI card | Midterm avg rating vs Final avg rating |
| Table | Text feedback — `dim_evaluation_question[question_text]`, `fact_evaluation_text[response_text]` |

**Slicer:** `fact_evaluation_rating[eval_type_label]`

#### Page 5 — Makeup Classes
| Visual | Config |
|---|---|
| Table | `fact_makeup_class[makeup_date_key]`, `dim_course[name]`, `dim_class[name]`, `fact_makeup_class[start_time_str]`, `fact_makeup_class[end_time_str]`, `fact_makeup_class[duration_hours]` |
| KPI card | Total makeup sessions scheduled |

---

### Role 3: Department Head

**Purpose:** Monitor department teachers, course performance, and academic outcomes.

**Tables to load:**
`dim_teacher`, `dim_course`, `dim_class`, `dim_semester`, `dim_major`, `dim_department`, `fact_enrollment`, `fact_grade`, `fact_evaluation_rating`, `fact_makeup_class`, `bridge_teacher_course`, `_Measures`

#### Row-Level Security (RLS) Setup

1. Create role `DepartmentHead`
2. Filter on `dim_department`:
   ```dax
   [department_key] = LOOKUPVALUE(
       dim_teacher[department_key],
       dim_teacher[email], USERPRINCIPALNAME()
   )
   ```

#### Report Pages:

#### Page 1 — Department Overview
| Visual | Config |
|---|---|
| KPI card | Number of teachers in department |
| KPI card | Total courses offered |
| KPI card | Department-wide average GPA |
| KPI card | Department pass rate % |
| Line chart | Department GPA trend by academic year |

**Slicer:** `dim_semester[academic_year]`, `dim_major[name]`

#### Page 2 — Teacher Performance
| Visual | Config |
|---|---|
| Bar chart | Teacher evaluation scores (ranked) — `dim_teacher[full_name]`, Average Evaluation Score |
| Scatter chart | Teaching rate (hours) vs. average student GPA — X: `dim_teacher[teaching_rate]`, Y: Average GPA, legend: `dim_teacher[qualification]` |
| Table | Teacher roster — `dim_teacher[full_name]`, `dim_teacher[qualification]`, `dim_teacher[teaching_rate]`, Average Evaluation Score, Total Enrollments, Pass Rate % |

#### Page 3 — Course Analysis
| Visual | Config |
|---|---|
| Matrix | Course pass rate × Semester — Rows: `dim_course[name]`, Cols: `dim_semester[semester_number]`, Values: Pass Rate % |
| Table | Courses with pass rate < 70% — filtered |
| Bar chart | Makeup sessions by teacher (disruption indicator) |

---

### Role 4: Academic Affairs / Registrar

**Purpose:** Student lifecycle management — graduation tracking, GPA monitoring, credit progress.

**Tables to load:**
`dim_student`, `fact_grade`, `fact_enrollment`, `dim_semester`, `dim_major`, `dim_department`, `dim_faculty`, `_Measures`

#### Report Pages:

#### Page 1 — Student Status Overview
| Visual | Config |
|---|---|
| KPI card | Total students |
| KPI card | Active students |
| KPI card | Graduated students |
| Funnel chart | Student pipeline — `dim_student[status_label]` count (Active → On Leave → Graduated → Withdrawn) |
| Bar chart | Students per batch — `dim_student[batch]`, count, colored by `status_label` |

**Slicers:** `dim_major[name]`, `dim_student[batch]`

#### Page 2 — GPA & Credit Progress
| Visual | Config |
|---|---|
| Bar chart | Average cumulative GPA by batch — `dim_student[batch]`, Average GPA |
| Bar chart | Average credit completion rate by major |
| Line chart | Semester GPA progression by batch (multi-line) |
| KPI card | Students on academic probation (GPA < 2.0): `CALCULATE(COUNTROWS(fact_grade), fact_grade[gpa] < 2.0)` |

#### Page 3 — At-Risk Student List
| Visual | Config |
|---|---|
| Table | At-risk students — `dim_student[full_name]`, `dim_student[student_id]`, `dim_major[name]`, `dim_student[batch]`, current semester GPA, current attendance rate — filtered where GPA < 2.0 OR attendance_rate_pct < 75 |

#### Page 4 — Scholarship Analysis
| Visual | Config |
|---|---|
| KPI card | Scholarship students count |
| KPI card | Scholarship avg GPA vs non-scholarship avg GPA |
| Bar chart | GPA comparison — scholarship vs non-scholarship by batch |
| Table | Scholarship student list with cumulative GPA and credit completion rate |

**Slicer:** `dim_student[is_scholarship]` (True/False toggle)

---

### Role 5: Student (Self-Service Portal)

**Purpose:** Each student views only their own academic data.

**Tables to load:**
`fact_enrollment`, `fact_attendance`, `fact_grade`, `fact_permission`, `dim_course`, `dim_teacher`, `dim_class`, `dim_semester`, `dim_date`, `_Measures`

#### Row-Level Security (RLS) Setup

1. Create role `Student`
2. Filter on `dim_student`:
   ```dax
   [email] = USERPRINCIPALNAME()
   ```
   (Assumes student email in `dim_student[email]` matches their Power BI login)

#### Report Pages:

#### Page 1 — My Academic Summary
| Visual | Config |
|---|---|
| KPI card | Current semester GPA |
| KPI card | Cumulative GPA |
| KPI card | Attendance rate this semester |
| KPI card | Credits earned / Total credits (shown as fraction) |
| KPI card | Pending permissions count |
| Line chart | My GPA progression — X: `dim_semester[academic_year]` + semester_number, Y: `fact_grade[gpa]` |

#### Page 2 — My Courses
| Visual | Config |
|---|---|
| Table | Enrolled courses — `dim_course[name]`, `dim_teacher[full_name]`, `fact_enrollment[score_attendance]`, `fact_enrollment[score_quiz]`, `fact_enrollment[score_midterm]`, `fact_enrollment[score_final]`, `fact_enrollment[total_score]`, `fact_enrollment[letter_grade]`, `fact_enrollment[attendance_rate_pct]` |
| Bar chart | Score breakdown by course — stacked (attendance / quiz / midterm / final) |

**Slicer:** `dim_semester[academic_year]`

#### Page 3 — My Attendance
| Visual | Config |
|---|---|
| KPI card | Overall attendance rate |
| Clustered bar | Attendance per course — Present / Late / Absent counts from `fact_enrollment` |
| Table | Attendance log — `dim_date[date_key]`, `dim_course[name]`, `fact_attendance[check_in_time]`, `fact_attendance[check_in_status_label]`, `fact_attendance[check_out_time]`, `fact_attendance[duration_hours]` |

#### Page 4 — My Permissions
| Visual | Config |
|---|---|
| Table | Permission requests — `fact_permission[permission_date_key]`, `fact_permission[reason]`, `fact_permission[status_label]`, `fact_permission[has_attachment]` |
| KPI card | Approved count / Total requests |

---

## Part D: Publishing and Row-Level Security in Power BI Service

### Publishing

1. **File → Publish → Publish to Power BI** → select workspace
2. In Power BI Service, open the dataset → **Security**
3. For each role (Teacher, Student, DepartmentHead): add the email addresses of users belonging to that role
4. Admin/Registrar reports typically do not use RLS — all data is visible

### Setting Up Scheduled Refresh

Power BI Service can refresh the dataset automatically when the source files update:

1. Set up a **Power BI Gateway** (Personal or On-premises) pointing to the `warehouse/` directory
2. In the dataset settings → **Scheduled Refresh** → configure daily refresh (recommended: 6:00 AM, after nightly ETL run)
3. Ensure the ETL script runs before the scheduled refresh time

### Workspace Organization

Create separate workspaces (or workspace folders) per role to control who sees what:

| Workspace | Audience |
|---|---|
| **University Admin** | Academic Affairs, Registrar, Rector |
| **Department Reports** | Department Heads (use RLS or separate reports per dept) |
| **Teacher Portal** | All teachers (RLS filters to individual) |
| **Student Portal** | All students (RLS filters to individual) |

---

## Part E: Tips and Best Practices

### Performance
- Import mode (not DirectQuery) is recommended for this data size — all tables fit in memory.
- Keep `dim_date` as the single date table and join all facts through it for consistent time-intelligence.
- Avoid bi-directional relationships — all relationships should be single direction (Many → One).

### DAX Tips
- Use `CALCULATE` + `dim_semester` filters instead of date slicers when filtering by semester.
- Use `USERELATIONSHIP` in measures when you need to activate an inactive relationship (e.g. if a fact table has multiple date columns).
- For "current semester" context, add a `is_current` calculated column to `dim_semester`:
  ```dax
  is_current = dim_semester[start_date] <= TODAY() && dim_semester[end_date] >= TODAY()
  ```

### Localization
- Khmer name columns (`full_name_kh`, `name_kh`) are available on student and teacher dimensions. Switch the display name field in visuals depending on the report audience.
- `dim_date[academic_year_label]` (e.g. "2024-2025") is preferred over calendar year for all academic comparisons.

### Missing Data
- Empty source tables (Survey, CV, TeachingHour) produce empty parquet files. Power BI will load them without error but they will have no rows — this is expected.
- `fact_evaluation_text[response_text]` may contain empty strings for students who submitted the form but left text fields blank. Filter `response_text <> ""` in text analysis visuals.
