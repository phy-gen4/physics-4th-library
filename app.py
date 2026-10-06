
import os, sqlite3, secrets
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, send_file, session, flash, abort
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "library.db")
UPLOADS = os.path.join(BASE, "static", "uploads")
os.makedirs(UPLOADS, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

SUBJECTS = [
    ("quantum", "ميكانيك الكم", "⚛️"),
    ("measurement", "القياس والتقويم", "📏"),
    ("educational_lab", "المختبر التعليمي", "🔬"),
    ("nuclear", "الفيزياء النووية", "☢️"),
    ("solid_state", "فيزياء الحالة الصلبة", "🧊"),
    ("nuclear_lab", "مختبر النووية", "🧪"),
    ("laser", "الليزر", "🔦"),
    ("electromagnetic", "النظرية الكهرومغناطيسية", "⚡"),
    ("teaching", "التربية التعليمية", "👨‍🏫"),
]
CATEGORIES = ["ملازم", "محاضرات", "ملخصات", "أسئلة وامتحانات", "مصادر", "أخرى"]

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS files(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      subject TEXT NOT NULL,
      category TEXT NOT NULL DEFAULT 'ملازم',
      title TEXT NOT NULL,
      filename TEXT NOT NULL,
      original_name TEXT NOT NULL,
      teacher TEXT DEFAULT '',
      downloads INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS announcements(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      body TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS schedule(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      day TEXT NOT NULL,
      time TEXT NOT NULL,
      subject TEXT NOT NULL,
      room TEXT DEFAULT ''
    );
    """)
    c.commit(); c.close()

def subject_map():
    return {s[0]: s[1] for s in SUBJECTS}

def admin_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return wrap

@app.context_processor
def inject():
    return dict(subjects=SUBJECTS, categories=CATEGORIES, admin=session.get("admin", False), subject_map=subject_map())

@app.route("/")
def home():
    c=db()
    counts={r["subject"]:r["n"] for r in c.execute("SELECT subject,COUNT(*) n FROM files GROUP BY subject")}
    total=c.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    downloads=c.execute("SELECT COALESCE(SUM(downloads),0) FROM files").fetchone()[0]
    announcements=c.execute("SELECT * FROM announcements ORDER BY id DESC LIMIT 5").fetchall()
    c.close()
    return render_template("home.html", counts=counts,total=total,downloads=downloads,announcements=announcements)

@app.route("/subject/<slug>")
def subject(slug):
    names=subject_map()
    if slug not in names: abort(404)
    category=request.args.get("category","")
    q=request.args.get("q","").strip()
    c=db()
    sql="SELECT * FROM files WHERE subject=?"
    args=[slug]
    if category:
        sql+=" AND category=?"; args.append(category)
    if q:
        sql+=" AND (title LIKE ? OR teacher LIKE ? OR original_name LIKE ?)"
        like=f"%{q}%"; args += [like,like,like]
    sql+=" ORDER BY id DESC"
    files=c.execute(sql,args).fetchall(); c.close()
    return render_template("subject.html", slug=slug, subject_name=names[slug], files=files, active_category=category, q=q)

@app.route("/search")
def search():
    q=request.args.get("q","").strip()
    files=[]
    if q:
        c=db()
        like=f"%{q}%"
        files=c.execute("""SELECT * FROM files WHERE title LIKE ? OR teacher LIKE ? OR original_name LIKE ?
                           ORDER BY id DESC""",(like,like,like)).fetchall()
        c.close()
    return render_template("search.html", q=q, files=files)

@app.route("/pdf/<int:file_id>")
def view_pdf(file_id):
    c=db(); f=c.execute("SELECT * FROM files WHERE id=?",(file_id,)).fetchone(); c.close()
    if not f: abort(404)
    path=os.path.join(UPLOADS,f["filename"])
    if not os.path.exists(path): abort(404)
    return send_file(path, mimetype="application/pdf", as_attachment=False)

@app.route("/download/<int:file_id>")
def download(file_id):
    c=db(); f=c.execute("SELECT * FROM files WHERE id=?",(file_id,)).fetchone()
    if not f: c.close(); abort(404)
    c.execute("UPDATE files SET downloads=downloads+1 WHERE id=?",(file_id,)); c.commit(); c.close()
    path=os.path.join(UPLOADS,f["filename"])
    return send_file(path, mimetype="application/pdf", as_attachment=True, download_name=f["original_name"])

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        user=request.form.get("username","")
        pw=request.form.get("password","")
        admin_user=os.environ.get("ADMIN_USER","admin")
        admin_pass=os.environ.get("ADMIN_PASSWORD","physics2026")
        if user==admin_user and pw==admin_pass:
            session["admin"]=True
            return redirect(request.args.get("next") or url_for("admin"))
        flash("اسم المستخدم أو كلمة المرور غير صحيحة","error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

@app.route("/admin")
@admin_required
def admin():
    c=db()
    files=c.execute("SELECT * FROM files ORDER BY id DESC").fetchall()
    total=c.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    downloads=c.execute("SELECT COALESCE(SUM(downloads),0) FROM files").fetchone()[0]
    announcements=c.execute("SELECT * FROM announcements ORDER BY id DESC").fetchall()
    schedule=c.execute("SELECT * FROM schedule ORDER BY id DESC").fetchall()
    c.close()
    return render_template("admin.html", files=files,total=total,downloads=downloads,announcements=announcements,schedule=schedule)

@app.route("/admin/upload", methods=["POST"])
@admin_required
def upload():
    subject=request.form.get("subject","")
    category=request.form.get("category","ملازم")
    title=request.form.get("title","").strip()
    teacher=request.form.get("teacher","").strip()
    files=request.files.getlist("files")
    if subject not in subject_map(): flash("اختر مادة صحيحة","error"); return redirect(url_for("admin"))
    added=0
    c=db()
    for file in files:
        if not file or not file.filename: continue
        if not file.filename.lower().endswith(".pdf"): continue
        original=file.filename
        safe=secure_filename(original) or f"file_{secrets.token_hex(5)}.pdf"
        stored=f"{secrets.token_hex(8)}_{safe}"
        file.save(os.path.join(UPLOADS,stored))
        final_title=title or os.path.splitext(original)[0]
        c.execute("INSERT INTO files(subject,category,title,filename,original_name,teacher) VALUES(?,?,?,?,?,?)",
                  (subject,category,final_title,stored,original,teacher))
        added+=1
    c.commit(); c.close()
    flash(f"تمت إضافة {added} ملف PDF بنجاح","success")
    return redirect(url_for("admin"))

@app.route("/admin/delete/<int:file_id>", methods=["POST"])
@admin_required
def delete(file_id):
    c=db(); f=c.execute("SELECT * FROM files WHERE id=?",(file_id,)).fetchone()
    if f:
        path=os.path.join(UPLOADS,f["filename"])
        if os.path.exists(path): os.remove(path)
        c.execute("DELETE FROM files WHERE id=?",(file_id,)); c.commit()
    c.close()
    flash("تم حذف الملف","success")
    return redirect(url_for("admin"))

@app.route("/admin/announcement", methods=["POST"])
@admin_required
def announcement():
    title=request.form.get("title","").strip(); body=request.form.get("body","").strip()
    if title and body:
        c=db(); c.execute("INSERT INTO announcements(title,body) VALUES(?,?)",(title,body)); c.commit(); c.close()
    return redirect(url_for("admin"))

@app.route("/admin/announcement/delete/<int:item_id>", methods=["POST"])
@admin_required
def announcement_delete(item_id):
    c=db(); c.execute("DELETE FROM announcements WHERE id=?",(item_id,)); c.commit(); c.close()
    return redirect(url_for("admin"))

@app.route("/schedule")
def schedule():
    c=db(); rows=c.execute("SELECT * FROM schedule ORDER BY id DESC").fetchall(); c.close()
    return render_template("schedule.html", rows=rows)

@app.route("/admin/schedule", methods=["POST"])
@admin_required
def schedule_add():
    day=request.form.get("day","").strip(); time=request.form.get("time","").strip()
    subject=request.form.get("subject","").strip(); room=request.form.get("room","").strip()
    if day and time and subject:
        c=db(); c.execute("INSERT INTO schedule(day,time,subject,room) VALUES(?,?,?,?)",(day,time,subject,room)); c.commit(); c.close()
    return redirect(url_for("admin"))

@app.route("/admin/schedule/delete/<int:item_id>", methods=["POST"])
@admin_required
def schedule_delete(item_id):
    c=db(); c.execute("DELETE FROM schedule WHERE id=?",(item_id,)); c.commit(); c.close()
    return redirect(url_for("admin"))

init_db()
if __name__=="__main__":
    app.run(debug=True)
