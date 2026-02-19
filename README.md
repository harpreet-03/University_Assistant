# EduVerse AI 🎓

**EduVerse AI** is a specialized **Hybrid RAG (Retrieval-Augmented Generation)** assistant designed for universities (specifically configured for **Lovely Professional University (LPU)**). It allows students and faculty to query university data—ranging from structured timetables to unstructured policy documents—using natural language.

The system combines **SQL** (for precise structured data queries like timetables) and **Vector Database** (ChromaDB for semantic search over policies, notices, and scholarships) to provide accurate, hallucination-free answers. It runs entirely locally using **Ollama** for the LLM inference.

---

## 🚀 Features

-   **Hybrid Retrieval Engine**:
    -   **Structured Data**: Automatically parses Excel (`.xlsx`) timetables into an SQLite database for precise lookups (e.g., "Where is Dr. Manik's class at 9 AM?").
    -   **Unstructured Data**: Embeds PDFs, Word docs, and Text files into a Vector Database (ChromaDB) for semantic Q&A (e.g., "What is the attendance policy?").
-   **Local & Private**: Powered by **Ollama**, ensuring no data leaves your server.
-   **Smart Routing**: An intelligent router decides whether to query the SQL DB, Vector DB, or both based on user intent.
-   **Admin Dashboard**: A clean web interface to upload, categorize, and manage university documents.
-   **Streaming Support**: Real-time token streaming for a responsive chat experience.

---

## 🛠️ Tech Stack

-   **Backend**: [FastAPI](https://fastapi.tiangolo.com/) (Python)
-   **LLM**: [Ollama](https://ollama.com/) (Running `qwen2.5` or `llama3`)
-   **Vector DB**: [ChromaDB](https://www.trychroma.com/) (Local persistence)
-   **Relational DB**: SQLite (for Timetables)
-   **Frontend**: HTML5, CSS3, Vanilla JavaScript (Responsive & distinct UI)

---

## ⚙️ Installation & Setup

### 1. Prerequisites
-   **Python 3.10+**
-   **Ollama** installed and running. [Download Ollama](https://ollama.com/download)

### 2. Clone the Repository
```bash
git clone https://github.com/harpreet-03/University_Assistant.git
cd University_Assistant
cd eduVerse_ai
```

### 3. Setup Virtual Environment
It's recommended to use a virtual environment to manage dependencies.
```bash
# Create virtual environment
python -m venv venv

# Activate it
# On Windows:
venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r backend/requirements.txt
```

### 5. Setup Ollama (LLM)
Ensure Ollama is running and pull the default model. The system defaults to `qwen2.5:7b-instruct` but can fallback to `llama3`.
```bash
# Start Ollama
ollama serve

# In a new terminal, pull the model
ollama pull qwen2.5:7b-instruct
```
*Note: You can change the model in `backend/llm.py` or by setting the `OLLAMA_MODEL` environment variable.*

---

## ▶️ Running the Application

1.  **Start the Backend Server**:
    Navigate to the `backend` directory (or run from root):
    ```bash
    # Run from inside 'eduVerse_ai' folder
    uvicorn backend.main:app --reload --port 8000
    ```
    *Note: If you are inside the `backend` folder, run `uvicorn main:app --reload`.*

2.  **Access the Application**:
    Open your browser and visit:
    👉 **http://localhost:8000**

---

## 📖 Usage Guide

### 1. Uploading Documents (Admin Panel)
Click on the **"Upload"** tab in the UI.
-   **Timetables**: Upload `.xlsx` files. The system will auto-detect "timetable" structure and store it in SQL for precise querying.
-   **Policies / Notices**: Upload `.pdf`, `.docx`, or `.txt`. These are chunked and stored in the Vector DB.
-   **Auto-Detection**: The system attempts to guess the document type (Policy, Timetable, Notice) based on the filename.

### 2. Chatting
Switch to the **"Chat"** tab.
-   **Ask about Timetables**: "When is the Python class usually held?" or "Show timetable for Dr. Smith".
-   **Ask about Rules**: "What is the minimum attendance required?"
-   **General Queries**: "Tell me about scholarship criteria."

---

## 📂 Project Structure
```
eduVerse_ai/
├── backend/
│   ├── main.py          # FastAPI Entry point & Routes
│   ├── llm.py           # Ollama interaction logic
│   ├── router.py        # Intent classification (SQL vs Vector)
│   ├── sqldb.py         # SQLite handling for structured data
│   ├── vectordb.py      # ChromaDB handling for unstructured data
│   ├── parsers.py       # File parsers (PDF, XLSX, DOCX)
│   └── requirements.txt # Python dependencies
├── frontend/
│   ├── index.html       # Main UI
│   ├── script.js        # Frontend logic
│   └── style.css        # Styling
├── db/                  # Database storage (Ignored in Git)
├── uploads/             # Uploaded files storage (Ignored in Git)
└── README.md            # Project Documentation
```

## 🤝 Contributing
Contributions are welcome! Please feel free to submit a Pull Request.
