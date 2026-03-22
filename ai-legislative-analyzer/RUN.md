# How to Run the AI Legislative Analyzer

Follow these steps to get the application up and running on your local machine.

## Prerequisites
- Python 3.10+
- Node.js & npm
- An API Key (Google Gemini or OpenAI)

## 1. Backend Setup
The backend is built with FastAPI and handles document processing and AI analysis.

1.  **Navigate to the backend folder**:
    ```powershell
    cd backend
    ```
2.  **Configure Environment Variables**:
    Open the `.env` file and add your Google API Key:
    ```env
    AI_PROVIDER=google
    GOOGLE_API_KEY=your_actual_gemini_api_key_here
    ```
    *(If you prefer OpenAI, set `AI_PROVIDER=openai` and add `OPENAI_API_KEY`.)*
3.  **Install Python Dependencies**:
    ```powershell
    pip install -r requirements.txt
    ```
4.  **Start the Backend Server**:
    ```powershell
    python main.py
    ```
    The API will be available at `http://localhost:8000`.

## 2. Frontend Setup
The frontend is a React application built with Vite.

1.  **Navigate to the frontend folder**:
    ```powershell
    cd ../frontend
    ```
2.  **Install Node Modules**:
    ```powershell
    npm install
    ```
3.  **Start the Development Server**:
    ```powershell
    npm run dev -- --port 3000
    ```
    The application will be available at `http://localhost:3000`.

## 3. Usage
- Open `http://localhost:3000` in your browser.
- Click **"Get Started"** to go to the Dashboard.
- Type a legal question in the query box (e.g., "What is the penalty for data breach in the DPDP act?").
- The system will retrieve relevant context (mocked for now until you upload a PDF) and provide a simplified AI explanation.
