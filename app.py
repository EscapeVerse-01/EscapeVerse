from flask import Flask, request, jsonify, session
import json
from flask_cors import CORS
import os
import google.generativeai as genai
from dotenv import load_dotenv
from flask_bcrypt import Bcrypt
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)
load_dotenv()

# Add session secret key
app.secret_key = os.getenv("SESSION_SECRET_KEY", "your-secret-key-for-development")

# Configure the Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Create the model with configuration
generation_config = {
  "temperature": 0,
  "top_p": 0.95,
  "top_k": 64,
  "max_output_tokens": 8192,
  "response_mime_type": "text/plain",
}
safety_settings = [
  {
    "category": "HARM_CATEGORY_HARASSMENT",
    "threshold": "BLOCK_NONE",
  },
  {
    "category": "HARM_CATEGORY_HATE_SPEECH",
    "threshold": "BLOCK_MEDIUM_AND_ABOVE",
  },
  {
    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "threshold": "BLOCK_MEDIUM_AND_ABOVE",
  },
  {
    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
    "threshold": "BLOCK_MEDIUM_AND_ABOVE",
  },
]

# Updated system instruction that includes handling quiz results
system_instruction = '''
IMPORTANT ... Do not use Markdown formatting (e.g., **bold**, *italics*, `code blocks`, bullet points, or numbered lists). Always return plain text.
Role & Purpose:

You are Cipher, an AI tutor for an interactive learning platform. Your goal is to help users understand topics, solve doubts, and improve their skills based on their learning level. Users may be Beginners, Intermediate, or Advanced learners.

Guidelines:
	1.	Adaptive Explanations:
	- If the user is a Beginner, explain concepts in simple terms with real-life analogies.
	- If the user is Intermediate, provide concise explanations with examples and encourage them to think critically.
	- If the user is Advanced, use technical explanations and discuss optimization strategies or deeper insights.
	2.	Code & Examples (For Coding Topics):
	- Provide well-commented code snippets where needed.
	- Break down complex concepts into step-by-step solutions.
	- When applicable, include multiple solutions (brute force & optimized).
	3.	Encouraging Problem-Solving:
	- Instead of directly giving answers, guide the user by asking leading questions.
	- Encourage them to try solving problems before revealing the solution.
	- Offer hints if the user is stuck.
	4.	Personalized Study Assistance:
	- Suggest relevant study materials (videos, articles, exercises) based on their skill level.
	- Recommend daily challenges based on their weak areas.
	- If the user has completed a quiz, refer to their results and roadmap for tailored responses.
	5.	Escape Room & Challenges:
	- If the user is in the Escape Room Challenge, give hints without revealing direct answers.
	- Ensure fairness by not providing solutions outright.
	- Track their progress and provide explanations for wrong answers.
	6.	Interactive & Engaging:
	- Keep responses engaging and motivating to encourage learning.
	- Recognize achievements (e.g., "Great job! You've mastered this concept!").
	- If a user asks an unrelated question, gently guide them back to learning.
	7.	Learning Roadmap:
	- If the user has quiz results, create personalized learning roadmaps based on their strengths and weaknesses.
	- Focus on strategies to improve weak areas while leveraging their strengths.
	- Provide specific practice exercises, resources, and milestones to track progress.
dont go on giving paragraphs unless necessary keep the answers crisp no unnecessary info
also dont give the text in markdown format
'''

model = genai.GenerativeModel(
  model_name="gemini-1.5-pro",
  safety_settings=safety_settings,
  generation_config=generation_config,
  system_instruction=system_instruction
)

# Configure database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# User Model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    rank = db.Column(db.String(50), default="Beginner")
    achievements = db.Column(db.Text, default="") 
    badges = db.Column(db.Text, default="")

# Create database file (Only runs once)
with app.app_context():
    db.create_all()

# Store chat sessions for different users
chat_sessions = {}
# Store quiz results for different users
user_quiz_results = {}

# Load questions from JSON file
try:
    with open("static/pythonBig.json", "r") as f:
        questions = json.load(f)
except FileNotFoundError:
    questions = []
    print("Warning: pythonBig.json file not found. Quiz functionality will be limited.")

@app.route('/')
def index():
    return app.send_static_file('homepage.html')

@app.route('/login')
def login_page():
    return app.send_static_file('login.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    user_message = data.get('message', '')
    session_id = request.remote_addr  # Using IP as a simple session identifier
    
    # Create a new chat session if one doesn't exist for this user
    if session_id not in chat_sessions:
        chat_sessions[session_id] = model.start_chat(history=[])
        
        # If user has quiz results, add them to the first message but don't send them to the frontend
        if session_id in user_quiz_results:
            quiz_info = user_quiz_results[session_id]
            initial_context = f"User Quiz Results - Level: {quiz_info['level']}, " \
                             f"Score: {quiz_info['score']}/{quiz_info['total']}, " \
                             f"Next Level: {quiz_info['next_level']}, " \
                             f"Strengths: {', '.join(quiz_info['strengths'])}, " \
                             f"Weaknesses: {', '.join(quiz_info['weaknesses'])}. " \
                             f"Please use this information to provide personalized guidance when the user asks about specific topics."
            
            # Add the context as a system message but don't display it to the user
            chat_sessions[session_id].send_message(initial_context)
    
    try:
        # Send the message to the model
        response = chat_sessions[session_id].send_message(user_message)
        model_response = response.text
        
        # Return the response
        return jsonify({"response": model_response})
    except Exception as e:
        return jsonify({"response": f"Sorry, I encountered an error: {str(e)}"})

# Process user's answers
# Process user's answers
@app.route('/evaluate_quiz', methods=['POST'])
def evaluate_quiz():
    data = request.json
    level = data.get("level")  # Beginner, Intermediate, or Advanced
    answers = data.get("answers", [])
    session_id = request.remote_addr  # Using IP as a simple session identifier
    
    filename = ""
    if level.lower() == "beginner":
        filename = "static/pythonBig.json"
    elif level.lower() == "intermediate":
        filename = "static/pythonInter.json"
    elif level.lower() == "advanced":
        filename = "static/pythonAd.json"
        
    try:
        # Try with the relative path first
        with open(filename, "r") as f:
            questions = json.load(f)
    except FileNotFoundError:
        # If that fails, try with absolute path
        try:
            with open(os.path.join(os.path.dirname(__file__), filename), "r") as f:
                questions = json.load(f)
        except FileNotFoundError:
            # As a last resort, try without the static folder
            base_filename = os.path.basename(filename)
            with open(base_filename, "r") as f:
                questions = json.load(f)
    
    correct_count = 0
    total_questions = len(questions)
    subtopic_analysis = {}
    for answer in answers:
        qid = answer["Qid"]
        selected_option = answer["Selected"]
        # Find the correct answer from the JSON data
        question_data = next((q for q in questions if q["Qid"] == qid), None)
        if question_data:
            subtopic = question_data.get("Subtopic", "General")
            correct_answer = question_data["Correct Answer"]
            if selected_option == correct_answer:
                correct_count += 1
                subtopic_analysis[subtopic] = subtopic_analysis.get(subtopic, 0) + 1
            else:
                subtopic_analysis[subtopic] = subtopic_analysis.get(subtopic, 0) - 1
    # Determine strengths and weaknesses
    strengths = [sub for sub, score in subtopic_analysis.items() if score > 0]
    weaknesses = [sub for sub, score in subtopic_analysis.items() if score <= 0]
    # Determine if the user passes to the next level
    percentage = (correct_count / total_questions) * 100
    if percentage >= 80:
        status = "Congratulations! You passed."
        next_level = "Intermediate" if level == "Beginner" else "Advanced" if level == "Intermediate" else "Expert"
    else:
        status = "You are currently at the same level."
        next_level = level
    # Store the quiz results for this user
    user_quiz_results[session_id] = {
        "level": level,
        "score": correct_count,
        "total": total_questions,
        "next_level": next_level,
        "strengths": strengths,
        "weaknesses": weaknesses
    }
    
    # Reset chat session if it exists to incorporate new quiz results
    if session_id in chat_sessions:
        del chat_sessions[session_id]
    return jsonify({
        "score": correct_count,
        "total_questions": total_questions,
        "status": status,
        "next_level": next_level,
        "strengths": strengths,
        "weaknesses": weaknesses
    })
# Endpoint to get learning roadmap based on quiz results
@app.route('/api/roadmap', methods=['GET'])
def get_roadmap():
    session_id = request.remote_addr  # Using IP as a simple session identifier
    
    if session_id not in user_quiz_results:
        return jsonify({"response": "Please complete a quiz first to get a personalized roadmap."})
    
    quiz_info = user_quiz_results[session_id]
    
    # Create or reset the chat session
    if session_id in chat_sessions:
        del chat_sessions[session_id]
    
    chat_sessions[session_id] = model.start_chat(history=[])
    
    # Construct a prompt for the roadmap
    roadmap_prompt = f"Based on my quiz results (Level: {quiz_info['level']}, " \
                     f"Strengths: {', '.join(quiz_info['strengths'])}, " \
                     f"Weaknesses: {', '.join(quiz_info['weaknesses'])}), " \
                     f"please provide a detailed learning roadmap to help me improve my weaknesses " \
                     f"while building on my strengths. Include specific resources, practice exercises, " \
                     f"and a timeline for progression to reach {quiz_info['next_level']} level."
    
    try:
        response = chat_sessions[session_id].send_message(roadmap_prompt)
        model_response = response.text
        
        return jsonify({"response": model_response})
    except Exception as e:
        return jsonify({"response": f"Sorry, I encountered an error generating your roadmap: {str(e)}"})

# ✅ Register Route
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    hashed_password = bcrypt.generate_password_hash(data['password']).decode('utf-8')

    new_user = User(username=data['username'], email=data['email'], password=hashed_password)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message": "User registered successfully!"})

@app.route('/users', methods=['GET'])
def get_users():
    users = User.query.all()
    result = []
    for user in users:
        result.append({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            # 🔐 Don't include the password in real apps, but okay for testing
            "password": user.password,
            "rank": user.rank,
            "achievements": user.achievements,
            "badges": user.badges
        })
    return jsonify(result)

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(email=data['email']).first()

    if user and bcrypt.check_password_hash(user.password, data['password']):
        return jsonify({"message": "Login successful!", "username": user.username})
    else:
        return jsonify({"message": "Invalid email or password"}), 401

@app.route('/award_badge', methods=['POST'])
def award_badge():
    data = request.json
    email = data['email']
    new_badge = data['badge']

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Add badge if not already present
    current_badges = user.badges.split(',') if user.badges else []
    if new_badge not in current_badges:
        current_badges.append(new_badge)
        user.badges = ','.join(current_badges)
        db.session.commit()

    return jsonify({"message": f"Badge '{new_badge}' awarded to {user.username}!"})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
