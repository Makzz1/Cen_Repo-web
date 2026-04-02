import os
import time
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, current_user, logout_user
from werkzeug.utils import secure_filename
import requests

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-vault-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vault.db'
app.config['UPLOAD_FOLDER'] = 'uploads/'

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login' # Redirects to the secure login page if not authenticated

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- DATABASE MODELS ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    role = db.Column(db.String(50), nullable=False) # 'admin', 'staff', 'student'
    name = db.Column(db.String(100), nullable=False)
    
    # Target identifiers for specific sharing
    year = db.Column(db.String(10), nullable=True)       # e.g., '2'
    stu_class = db.Column(db.String(10), nullable=True)  # e.g., 'B'

class FileAsset(db.Model):
    """Represents the logical file. e.g., 'Math_Notes.pdf' owned by User A"""
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    visibility = db.Column(db.String(20), default='public')
    audience = db.Column(db.String(20), default='all')
    target_data = db.Column(db.String(500), nullable=True) # Emails OR "Year X - Class Y"
    
    uploader = db.relationship('User', backref=db.backref('assets', lazy=True))
    versions = db.relationship('FileVersion', backref='asset', lazy=True, cascade="all, delete-orphan")

class FileVersion(db.Model):
    """Represents the physical file versions."""
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('file_asset.id'))
    version_number = db.Column(db.Integer, nullable=False)
    filepath = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(50), default='pending') # 'pending' or 'live'
    is_active = db.Column(db.Boolean, default=True) # Only one active version per asset
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- AUTHENTICATION ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        email = request.form.get('email').strip().lower()
        user = User.query.filter_by(email=email).first()
        
        if user:
            login_user(user)
            return redirect(url_for('index'))
        else:
            error = "Email not found in the system."
            
    return render_template('login.html', error=error)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- MAIN APP ROUTES ---

@app.route('/')
@login_required
def index():
    return render_template('index.html', user=current_user)

@app.route('/api/upload', methods=['POST'])
@login_required
def upload_file():
    if current_user.role == 'admin':
        return jsonify({"error": "Admins cannot upload files"}), 403

    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
        
    file = request.files['file']
    filename = secure_filename(file.filename)
    
    # Save physically (append timestamp to prevent OS-level overwrites for same names)
    safe_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}")
    file.save(safe_filepath)

    # Permission Data Setup
    visibility = request.form.get('visibility', 'public')
    audience = request.form.get('audience', 'all')
    target_data = ""
    
    if audience == 'specific':
        if current_user.role == 'student':
            target_data = request.form.get('target_emails', '')
        elif current_user.role == 'staff':
            year = request.form.get('target_year', '')
            stu_class = request.form.get('target_class', '')
            target_data = f"Year {year} - Class {stu_class}"

    # Version Control Logic
    asset = FileAsset.query.filter_by(filename=filename, uploader_id=current_user.id).first()
    
    if not asset:
        asset = FileAsset(
            filename=filename, uploader_id=current_user.id,
            visibility=visibility, audience=audience, target_data=target_data
        )
        db.session.add(asset)
        db.session.flush() 
        next_version = 1
    else:
        asset.visibility = visibility
        asset.audience = audience
        asset.target_data = target_data
        
        for v in asset.versions:
            v.is_active = False
            
        next_version = len(asset.versions) + 1

    file_status = 'live' if current_user.role == 'staff' else 'pending'

    new_version = FileVersion(
        asset_id=asset.id, version_number=next_version,
        filepath=safe_filepath, status=file_status, is_active=True
    )
    db.session.add(new_version)
    db.session.commit()
    db.session.commit() # Save to SQLite first so we have an asset.id

    # --- Send to Content Search Microservice (Port 5001) ---
    try:
        with open(safe_filepath, 'rb') as f:
            # We now pass both the file AND the asset.id
            requests.post(
                "http://127.0.0.1:5001/upload", 
                files={'file': (filename, f)},
                data={'asset_id': asset.id} 
            )
    except Exception as e:
        print(f"Content indexing failed: {e}")

    return jsonify({"message": "File uploaded successfully"}), 200


@app.route('/api/files', methods=['GET'])
@login_required
def search_files():
    search_query = request.args.get('q', '').lower()
    search_type = request.args.get('type', 'name')

    # 1. Base Query: Fetch all active versions
    base_query = db.session.query(FileAsset, FileVersion).join(FileVersion).filter(FileVersion.is_active == True)

    # 2. Apply Role-Based Privacy and Visibility Rules
    if current_user.role == 'admin':
        # ADMIN RULE: Can see all files EXCEPT those marked 'private'
        # (Since admins don't upload, they only see what others made public)
        base_query = base_query.filter(FileAsset.visibility != 'private')
    else:
        # USER RULE (Staff/Student):
        # Can see: (Own files, even private) OR (Live + Public + Shared to them)
        class_str = f"Year {current_user.year} - Class {current_user.stu_class}"
        
        own_files = (FileAsset.uploader_id == current_user.id)
        public_all = (FileAsset.visibility == 'public') & (FileAsset.audience == 'all')
        
        targeted_files = False
        if current_user.role == 'student':
            # Shared via email or shared to their specific Year/Class
            email_match = FileAsset.target_data.ilike(f'%{current_user.email}%')
            class_match = (FileAsset.target_data == class_str)
            targeted_files = (FileAsset.visibility == 'public') & \
                             (FileAsset.audience == 'specific') & \
                             (email_match | class_match)
        elif current_user.role == 'staff':
            # Staff see files specifically targeted to their email
            targeted_files = (FileAsset.visibility == 'public') & \
                             (FileAsset.audience == 'specific') & \
                             (FileAsset.target_data.ilike(f'%{current_user.email}%'))

        base_query = base_query.filter(
            own_files | ((FileVersion.status == 'live') & (public_all | targeted_files))
        )

    # 3. Fetch preliminary results from SQLite
    results = base_query.all()

    # 4. Filter by Search Query
    if search_query:
        if search_type == 'name':
            # Standard Filename Search
            results = [(a, v) for a, v in results if search_query in a.filename.lower()]
        elif search_type == 'content':
            # Deep Content Search via ChromaDB Microservice (Port 5001)
            try:
                response = requests.post("http://127.0.0.1:5001/search", json={"query": search_query, "top_k": 15})
                if response.status_code == 200:
                    search_data = response.json().get('results', [])
                    found_asset_ids = [item['asset_id'] for item in search_data]
                    
                    # Intersect SQLite results with ChromaDB findings (keeps security intact)
                    results = [(a, v) for a, v in results if a.id in found_asset_ids]
                else:
                    results = []
            except Exception as e:
                print(f"ChromaDB Search Failed: {e}")
                results = []

    # 5. Format JSON Response
    filtered_results = []
    for asset, version in results:
        filtered_results.append({
            "id": asset.id,
            "name": asset.filename,
            "uploader": asset.uploader.email,
            "status": version.status,
            "version": version.version_number,
            "version_id": version.id,   # Required for Admin Approval action
            "visibility": asset.visibility # Required to hide/show 'Approve' button on frontend
        })

    return jsonify(filtered_results)

@app.route('/api/profile/files', methods=['GET'])
@login_required
def get_profile_files():
    assets = FileAsset.query.filter_by(uploader_id=current_user.id).all()
    data = []
    for asset in assets:
        versions = []
        for v in sorted(asset.versions, key=lambda x: x.version_number, reverse=True):
            versions.append({
                "id": v.id, "version_number": v.version_number,
                "date": v.created_at.strftime('%b %d, %Y'),
                "is_active": v.is_active, "status": v.status
            })
        data.append({
            "id": asset.id, "name": asset.filename, 
            "uploader": current_user.email, "versions": versions
        })
    return jsonify(data)

@app.route('/api/versions/set_active', methods=['POST'])
@login_required
def set_active_version():
    data = request.json
    asset_id = data.get('asset_id')
    version_id = data.get('version_id')

    asset = FileAsset.query.get(asset_id)
    if not asset or asset.uploader_id != current_user.id:
        return jsonify({"error": "Unauthorized"}), 403

    for v in asset.versions:
        v.is_active = (v.id == version_id)
    
    db.session.commit()
    return jsonify({"message": "Active version updated"})

@app.route('/api/download/<int:asset_id>')
@login_required
def download_file(asset_id):
    """Serves the physical file to the user's browser."""
    asset = FileAsset.query.get_or_404(asset_id)
    active_version = next((v for v in asset.versions if v.is_active), None)
    
    if not active_version:
        return "File not available", 404
        
    return send_file(active_version.filepath, as_attachment=True, download_name=asset.filename)

@app.route('/api/admin/approve/<int:version_id>', methods=['POST'])
@login_required
def approve_file(version_id):
    """Allows admins to set a pending file to live."""
    if current_user.role != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
        
    version = FileVersion.query.get_or_404(version_id)
    version.status = 'live'
    db.session.commit()
    return jsonify({"message": "File approved and is now live"})

@app.route('/api/summarize/<int:asset_id>')
@login_required
def summarize_file(asset_id):
    """Sends the physical file to the external NLP API for summarization."""
    asset = FileAsset.query.get_or_404(asset_id)
    
    # Get the active version's file path
    active_version = next((v for v in asset.versions if v.is_active), None)
    if not active_version or not os.path.exists(active_version.filepath):
        return jsonify({"summary": "<p class='text-red-500'>Error: Physical file not found.</p>"}), 404
        
    # The URL of your new external summarizer API
    SUMMARIZE_API_URL = "http://127.0.0.1:5002/summarize"
    
    try:
        # Open the file in binary mode and send it
        with open(active_version.filepath, 'rb') as f:
            files = {'file': (asset.filename, f)}
            response = requests.post(SUMMARIZE_API_URL, files=files)
            
        # Handle successful response
        if response.status_code == 200:
            data = response.json()
            raw_summary = data.get('summary', 'No summary generated.')
            chunks = data.get('original_chunks', 1)
            
            # Format the raw AI text into beautiful HTML for the sidebar
            formatted_summary = f"""
            <div class="mb-4">
                <span class="inline-block px-2 py-1 bg-blue-50 text-[#00327d] rounded text-[9px] font-bold uppercase tracking-widest mb-2 border border-blue-100">
                    AI Generated • Processed {chunks} chunks
                </span>
            </div>
            <div class="text-sm text-slate-700 leading-relaxed space-y-3 font-body">
                {raw_summary}
            </div>
            """
            
            return jsonify({
                "filename": asset.filename,
                "summary": formatted_summary
            })
            
        # Handle API errors (e.g., file unreadable by PyPDF2)
        else:
            error_msg = response.json().get('error', 'Summarizer API failed.')
            return jsonify({"summary": f"<p class='text-red-500'>Error: {error_msg}</p>"}), response.status_code

    except requests.exceptions.ConnectionError:
        return jsonify({
            "summary": "<p class='text-red-500 font-bold'>Connection Failed!</p><p class='text-sm mt-2'>Is the Summarizer API running on port 5002?</p>"
        }), 503
    except Exception as e:
        return jsonify({"summary": f"<p class='text-red-500'>Server error: {str(e)}</p>"}), 500
    
# --- ADMIN MANAGEMENT ROUTES ---

@app.route('/api/admin/delete/<int:asset_id>', methods=['DELETE'])
@login_required
def delete_file(asset_id):
    """
    Admin only: Deletes the file asset and its physical versions from the Vault.
    ChromaDB chunks are preserved as per configuration.
    """
    if current_user.role != 'admin':
        return jsonify({"error": "Unauthorized access"}), 403
    
    asset = FileAsset.query.get_or_404(asset_id)
    
    try:
        # 1. Physical Cleanup: Remove files from the local 'uploads/' directory
        for v in asset.versions:
            if os.path.exists(v.filepath):
                try:
                    os.remove(v.filepath)
                except OSError as e:
                    print(f"Error deleting physical file {v.filepath}: {e}")
        
        # 2. Database Cleanup: asset.versions will be deleted via cascade
        db.session.delete(asset)
        db.session.commit()
        
        return jsonify({"message": f"Successfully removed {asset.filename} from the Vault."}), 200
    
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Database operation failed: {str(e)}"}), 500


@app.route('/api/admin/add_user', methods=['POST'])
@login_required
def add_user():
    """
    Admin only: Manually registers a new Staff or Student.
    Default 'password' is implicitly handled by the email-login logic.
    """
    if current_user.role != 'admin':
        return jsonify({"error": "Unauthorized access"}), 403
    
    data = request.json
    email = data.get('email', '').strip().lower()
    
    # Validation: Ensure email is unique
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "A user with this email already exists."}), 400

    try:
        new_user = User(
            email=email,
            name=data.get('name'),
            role=data.get('role'),      # Expects 'staff' or 'student'
            year=data.get('year'),      # Stored as string, e.g., "2"
            stu_class=data.get('stu_class') # Stored as string, e.g., "B"
        )
        
        db.session.add(new_user)
        db.session.commit()
        return jsonify({"message": f"User {new_user.name} created successfully."}), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to create user: {str(e)}"}), 500
# --- INITIALIZATION ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Seed test users
        if not User.query.first():
            db.session.add_all([
                User(email='admin@ssn.edu.in', role='admin', name='Admin User'),
                User(email='alex.thompson@ssn.edu.in', role='staff', name='Alex Thompson'),
                User(email='student@ssn.edu.in', role='student', name='Test Student', year='2', stu_class='B')
            ])
            db.session.commit()
            print("Seed users created. Go to http://127.0.0.1:5000/login to access the vault.")
            
    app.run(debug=True, port=5000)