import sqlite3
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt

# This is a placeholder for the User class we will create in app.py
# We will pass the actual User class to the init_auth function
User = None 

# This is a placeholder for the database connection function
get_db_connection = None

auth_bp = Blueprint('auth', __name__)
bcrypt = Bcrypt()

def init_auth(app, user_class, db_conn_func):
    """Initializes the authentication blueprint with dependencies from the main app."""
    global User, get_db_connection
    User = user_class
    get_db_connection = db_conn_func
    bcrypt.init_app(app)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home')) # Or 'dashboard_page'

    if request.method == 'POST':
        email = request.form.get('email')
        username = request.form.get('username')
        password = request.form.get('password')

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if email or username already exists
        cursor.execute("SELECT * FROM users WHERE email = ? OR username = ?", (email, username))
        existing_user = cursor.fetchone()

        if existing_user:
            flash('Email or username already exists. Please choose another.', 'danger')
            conn.close()
            return redirect(url_for('auth.register'))

        # Hash the password
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        # Insert new user
        try:
            cursor.execute(
                "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                (username, email, hashed_password)
            )
            user_id = cursor.lastrowid
            
            # --- CRITICAL STEP: Create the empty resume data profile ---
            # The 'experience', 'projects', 'education', 'skills' columns store JSON text
            cursor.execute(
                """
                INSERT INTO user_resume_data (user_id, name, email, phone, linkedin, github, summary, experience, projects, education, skills, activities, custom_sections)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, '', email, '', '', '', '', '[]', '[]', '[]', '{}', '[]', '[]')
            )
            # -----------------------------------------------------------

            conn.commit()
            flash('Registration successful! Please log in.', 'success')
            conn.close()
            return redirect(url_for('auth.login'))
        except sqlite3.IntegrityError:
            flash('An error occurred. It is likely the email or username was taken.', 'danger')
            conn.close()
            return redirect(url_for('auth.register'))
        except Exception as e:
            flash(f'An unexpected error occurred: {e}', 'danger')
            conn.close()
            return redirect(url_for('auth.register'))

    return render_template('register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        user_row = cursor.fetchone()
        conn.close()

        if user_row and bcrypt.check_password_hash(user_row['password_hash'], password):
            user_obj = User(id=user_row['id'], email=user_row['email'], username=user_row['username'])
            login_user(user_obj, remember=True)
            flash('Logged in successfully!', 'success')
            
            # Redirect to the page they were trying to access, or dashboard
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard_page'))
        else:
            flash('Login failed. Check your email and password.', 'danger')
            return redirect(url_for('auth.login'))

    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))