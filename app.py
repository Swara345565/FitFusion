from flask import Flask, request, jsonify, redirect, url_for, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
import bcrypt
from functools import wraps
import pandas as pd
import pickle
import os

# Load the model and scaler
with open('kmeans_model.pkl', 'rb') as f:
    kmeans = pickle.load(f)

with open('scaler.pkl', 'rb') as f:
    scaler = pickle.load(f)

app = Flask(__name__)

# SQLite Database setup
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fitness_website.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.urandom(24)  # Required for session management
db = SQLAlchemy(app)

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Workout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # This is critical
    date = db.Column(db.DateTime, default=db.func.current_timestamp())
    exercise = db.Column(db.String(100), nullable=False)
    duration = db.Column(db.Float, nullable=False)
    calories_burned = db.Column(db.Float, nullable=False)

    user = db.relationship('User', backref='workouts')  # Relationship to User

# Decorator to check if user is logged in
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))  # Redirect to login if not logged in
        return f(*args, **kwargs)
    return decorated_function

# Route for the home page (index.html)
@app.route('/')
def home():
    return send_from_directory('static', 'index.html')

# Route for signup
@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    # Validate input
    if not username or not email or not password:
        return jsonify({'message': 'All fields are required!', 'success': False}), 400

    # Check if user already exists
    if User.query.filter_by(email=email).first():
        return jsonify({'message': 'User already exists!', 'success': False}), 400

    # Hash the password before storing
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    # Store user in the database
    new_user = User(username=username, email=email, password=hashed_password)
    db.session.add(new_user)
    db.session.commit()
    
    return jsonify({'message': 'User created successfully!', 'success': True})

# Route for login
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    # Validate input
    if not email or not password:
        return jsonify({'message': 'Email and password are required!', 'success': False}), 400

    # Find user in the database
    user = User.query.filter_by(email=email).first()
    if user and bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')):
        session['user_id'] = user.id  # Store user id in session
        return jsonify({'message': 'Login successful!', 'success': True})
    else:
        return jsonify({'message': 'Invalid email or password!', 'success': False}), 401

# Route for diet.html (protected)
@app.route('/diet')
@login_required
def diet():
    return send_from_directory('static', 'diet.html')

@app.route('/recommend', methods=['POST'])
@login_required
def recommend():
    try:
        # Get user goal from the request
        user_goal = request.json.get('goal')
        
        if not user_goal:
            return jsonify({'message': 'No goal provided!', 'success': False}), 400

        # Load the cleaned dataset
        df_cleaned = pd.read_csv("df_cleaned.csv")  # Ensure this path is correct

        # Identify numeric columns for scaling
        nutritional_columns = df_cleaned.select_dtypes(include=['float64', 'int64']).columns

        # Feature Scaling
        X_scaled = scaler.transform(df_cleaned[nutritional_columns])

        # K-Means Clustering
        df_cleaned['Cluster'] = kmeans.predict(X_scaled)

        # Define the goal-to-cluster mapping
        goal_mapping = {
            "maintain weight": 0,
            "muscle gain": 1,
            "fat burn with lean muscle retention": 2,
            "enhance athletic performance": 3,
            "improve immunity": 4,
            "bone and joint health": 5,
            "gut health": 6,
            "mental wellness": 7,
            "energy boost": 8,
            "recovery from illness/surgery": 9
        }

        # Check if the user goal is valid
        user_goal = user_goal.strip().lower()
        if user_goal not in goal_mapping:
            return jsonify({'message': 'Invalid goal specified.', 'success': False}), 400

        # Get the cluster number based on the user's goal
        goal_cluster = goal_mapping[user_goal]

        # Filter dataset based on the user's goal cluster
        recommended_foods = df_cleaned[df_cleaned['Cluster'] == goal_cluster]

        # Randomize and select limited recommendations (e.g., 5 recommendations)
        if not recommended_foods.empty:
            random_recommendations = recommended_foods.sample(n=min(5, len(recommended_foods)), random_state=1)

            # Convert the selected recommendations to JSON format
            recommendations_list = random_recommendations[['Category', 'Description', 'Data.Protein', 'Data.Kilocalories']].to_dict(orient='records')

            # Return recommendations as JSON response
            return jsonify(recommendations_list)
        else:
            return jsonify({'message': 'No recommendations available based on your preferences.', 'success': False}), 404

    except Exception as e:
        print(f"Error in recommend route: {e}")
        return jsonify({'message': 'An error occurred during recommendation.', 'success': False}), 500

@app.route('/add_workout', methods=['POST'])
@login_required  # Ensure that only logged-in users can access this route
def add_workout():
    data = request.get_json()
    exercise = data.get('exercise')
    duration = data.get('duration')
    calories_burned = data.get('calories_burned')

    # Retrieve user_id from session
    user_id = session.get('user_id')

    # Validate input
    if not exercise or duration is None or calories_burned is None:
        return jsonify({'message': 'All fields are required!', 'success': False}), 400

    # Create a new workout entry
    new_workout = Workout(user_id=user_id, exercise=exercise, duration=duration, calories_burned=calories_burned)
    
    try:
        db.session.add(new_workout)
        db.session.commit()
        return jsonify({'message': 'Workout logged successfully!', 'success': True})
    except Exception as e:
        db.session.rollback()  # Roll back the session in case of error
        return jsonify({'message': 'Failed to log workout.', 'success': False, 'error': str(e)}), 500

@app.route('/workouts', methods=['GET'])
@login_required
def get_workouts():
    user_id = session.get('user_id')
    workouts = Workout.query.filter_by(user_id=user_id).all()
    workout_list = []
    for workout in workouts:
        workout_list.append({
            'date': workout.date,
            'exercise': workout.exercise,
            'duration': workout.duration,
            'calories_burned': workout.calories_burned
        })
    return jsonify(workout_list)


# Route for logout
@app.route('/logout')
def logout():
    session.pop('user_id', None)  # Remove user id from session
    return redirect(url_for('home'))  # Redirect to home page

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Ensure the database and tables are created
    app.run(debug=True)