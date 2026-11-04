# Study Buddy – RAG website

## 1. Google Client ID
Google Cloud Console → APIs & Services → Credentials → Create OAuth client ID → *Web application*.
Add Authorized JavaScript origins: `http://localhost:8000` (and your deployed URL later).

## 2. Run
```
pip install -r requirements.txt
cp .env.example .env   # fill in values
uvicorn backend.main:app --reload --port 8000
```
Open http://localhost:8000

## Flow
Google sign-in -> (new user) register: name, college, class, DOB -> upload PDF/TXT/MD notes -> ask questions.
Each student's notes live in their own private Chroma collection.

## Plug in your own RAG
Replace `index_file` / `answer` in `backend/rag.py` with your existing code. Keep the signatures.
